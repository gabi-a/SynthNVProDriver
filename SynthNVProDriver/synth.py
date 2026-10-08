"""High-level SynthNV Pro API.

Typical use::

    from SynthNVProDriver import SynthNVPro

    with SynthNVPro.connect() as synth:      # auto-discovers the port
        synth.set_frequency(2870.0)          # MHz
        synth.set_power(-10.0)               # dBm
        synth.enable()                       # PLL on: RF output live
        ...
    # leaving the block powers the RF output down and closes the port

All methods are synchronous. Settings are read back from the device and
checked (``verify=True``, the default) because the device does not
acknowledge commands; a mismatch raises :class:`CommandError`. Out-of-range
arguments raise ``ValueError`` before anything is sent.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from enum import IntEnum
from typing import Callable, Sequence, TypeVar

from SynthNVProDriver.protocol import (
    CommandError,
    ProtocolError,
    parse_bool,
    parse_float,
    parse_int,
)
from SynthNVProDriver.transport import Transport

logger = logging.getLogger("SynthNVProDriver")

T = TypeVar("T")

FREQUENCY_RANGE_MHZ = (12.5, 6400.0)
POWER_RANGE_DBM = (-60.0, 20.0)
SWEEP_POWER_RANGE_DBM = (-50.0, 20.0)


class TempCompensation(IntEnum):
    NONE = 0
    ON_SET = 1
    EVERY_1_S = 2
    EVERY_10_S = 3


class DetectorMode(IntEnum):
    INSTANTANEOUS = 0   # no averaging; best for CW. Calibrated.
    LOW_PASS = 1        # 5.6 ms RC filter. Calibrated.
    EXPERIMENTAL = 2    # peak-capture diode. Not calibrated.


class ReferenceSource(IntEnum):
    EXTERNAL = 0
    INTERNAL_27MHZ = 1
    INTERNAL_10MHZ = 2


class TriggerFunction(IntEnum):
    NO_TRIGGERS = 0
    FULL_FREQUENCY_SWEEP = 1
    SINGLE_FREQUENCY_STEP = 2
    STOP_ALL = 3
    DIGITAL_RF_ON_OFF = 4
    REMOVE_INTERRUPTS = 5   # less modulation jitter; use carefully
    RESERVED_1 = 6
    RESERVED_2 = 7
    EXTERNAL_AM_INPUT = 8   # needs the AM LUT set to ramp
    EXTERNAL_FM_INPUT = 9   # needs FM set to chirp


class SweepType(IntEnum):
    LINEAR = 0
    TABULAR = 1      # up to ~500-point frequency/power table hopping
    PERCENTAGE = 2


class SweepDirection(IntEnum):
    UPPER_TO_LOWER = 0
    LOWER_TO_UPPER = 1


class SweepDisplay(IntEnum):
    NONE = 0
    FREQUENCY_AND_POWER = 1
    POWER_ONLY = 2


@dataclass(frozen=True)
class DeviceInfo:
    model: str
    serial: str
    firmware: str
    hardware: str


@dataclass(frozen=True)
class Status:
    pll_enabled: bool      # False: RF generator powered down
    muted: bool
    frequency_mhz: float
    power_dbm: float
    calibrated: bool       # device reports the output is leveled and accurate


@dataclass(frozen=True)
class SweepResult:
    """Measurements streamed during a sweep (see :meth:`SweepApi.read_results`)."""

    power_dbm: list[float]
    frequency_mhz: list[float] | None  # None when the display style omits frequency


def _check_range(name: str, value: float, lo: float, hi: float, unit: str = "") -> float:
    value = float(value)
    if not lo <= value <= hi:  # also rejects NaN
        raise ValueError(f"{name} must be between {lo:g} and {hi:g} {unit}, got {value:g}")
    return value


class SynthNVPro:
    """Owns the transport and exposes the device through per-subsystem APIs:
    :attr:`sweep`, :attr:`reference`, :attr:`detector`.

    ``max_power_dbm`` is a software cap on any RF output power this API will
    set (including sweeps and tables); it defaults to the hardware maximum.
    ``verify`` enables read-back checking of every setting.
    """

    ENABLE_SETTLE_S = 0.05      # PLL/VCO power-up takes ~20 ms
    SET_TIMEOUT_S = 5.0         # frequency/power sets can recalibrate
    FREQUENCY_TOLERANCE_MHZ = 1e-3
    POWER_TOLERANCE_DB = 0.1

    def __init__(self, transport: Transport, *, verify: bool = True,
                 max_power_dbm: float | None = None):
        self._t = transport
        self.verify = verify
        self._max_power_dbm = POWER_RANGE_DBM[1]
        if max_power_dbm is not None:
            self.max_power_dbm = max_power_dbm
        self.sweep = SweepApi(self)
        self.reference = ReferenceApi(self)
        self.detector = DetectorApi(self)

    @classmethod
    def connect(cls, port: str | None = None, **kwargs) -> "SynthNVPro":
        """Opens the device (auto-discovering the port if none is given) and
        verifies it answers as a SynthNV Pro."""
        transport = Transport(port)
        synth = cls(transport, **kwargs)
        try:
            synth.ping()
        except Exception:
            transport.close()
            raise
        return synth

    def __enter__(self) -> "SynthNVPro":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def close(self, disable: bool = True) -> None:
        """Powers the RF output down (best effort) and closes the port."""
        try:
            if disable:
                self.disable()
        except Exception:
            logger.warning("could not disable the RF output while closing", exc_info=True)
        finally:
            self._t.close()

    def reconnect(self) -> None:
        """Reopens the serial connection, rediscovering the port. The device
        state is unknown afterwards; re-apply your settings."""
        self._t.reconnect()
        self.ping()

    # -- safety limits -------------------------------------------------------

    @property
    def max_power_dbm(self) -> float:
        return self._max_power_dbm

    @max_power_dbm.setter
    def max_power_dbm(self, value: float) -> None:
        self._max_power_dbm = _check_range("max_power_dbm", value, *POWER_RANGE_DBM, "dBm")

    def _check_power(self, name: str, power_dbm: float,
                     lo_hi: tuple[float, float] = POWER_RANGE_DBM) -> float:
        power = _check_range(name, power_dbm, *lo_hi, "dBm")
        if power > self._max_power_dbm:
            raise ValueError(f"{name} {power:g} dBm exceeds the configured limit "
                             f"max_power_dbm = {self._max_power_dbm:g} dBm")
        return power

    # -- verified settings ---------------------------------------------------

    def _set(self, command: str, value, read: Callable[[], T], expected: T | None = None, *,
             tolerance: float = 0.0, decimals: int = 7, name: str | None = None) -> None:
        """Sends a setting and (if verification is on) checks it by reading it back."""
        self._t.send(command, value, decimals=decimals)
        if not self.verify:
            return
        if expected is None:
            expected = value
        actual = read()
        if isinstance(expected, float) or isinstance(actual, float):
            ok = abs(actual - expected) <= tolerance
        else:
            ok = actual == expected
        if not ok:
            raise CommandError(name or command,
                               f"device reports {actual!r} after setting {expected!r}")

    def _query_float(self, command: str, timeout: float | None = None) -> float:
        return parse_float(self._t.query(command, timeout=timeout))

    def _query_int(self, command: str) -> int:
        return parse_int(self._t.query(command))

    def _query_bool(self, command: str) -> bool:
        return parse_bool(self._t.query(command))

    # -- system --------------------------------------------------------------

    def ping(self) -> str:
        """Returns the model string; raises if this is not a SynthNV Pro."""
        model = self._t.request("+")
        if "synthnv" not in model.lower():
            raise ConnectionError(f"device did not identify as a SynthNV Pro: {model!r}")
        return model

    def info(self) -> DeviceInfo:
        return DeviceInfo(
            model=self._t.request("+"),
            serial=self._t.request("-"),
            firmware=self._t.request("v", 0),
            hardware=self._t.request("v", 1),
        )

    def status(self) -> Status:
        return Status(
            pll_enabled=self.is_enabled(),
            muted=self.is_muted(),
            frequency_mhz=self.get_frequency(),
            power_dbm=self.get_power(),
            calibrated=self.is_calibrated(),
        )

    def enable(self) -> None:
        """Powers up the PLL and VCO: the RF output is live at the configured
        frequency and power. Takes ~20 ms."""
        self._set("E", 1, self.is_enabled, True, name="enable")
        time.sleep(self.ENABLE_SETTLE_S)

    def disable(self) -> None:
        """Stops any sweep and powers the PLL and VCO down, so there is no
        RF output. Safe to call in any state."""
        self.sweep.stop()
        self._set("E", 0, self.is_enabled, False, name="disable")

    def is_enabled(self) -> bool:
        return self._query_bool("E")

    def help(self, duration_s: float = 0.3) -> list[str]:
        """The device's own command summary."""
        return self._t.request_for("?", duration_s)

    def get_temperature(self) -> float:
        """Internal temperature in degrees C."""
        # Plain "z", not "z?": the trailing "?" is also the help command and
        # makes the device dump its whole menu after the temperature.
        return parse_float(self._t.request("z"))

    def save_to_eeprom(self) -> None:
        """Stores all current settings as the power-up defaults. Check that
        the device is configured exactly as needed first, including that the
        saved RF state is safe at boot (sweep and modulation settings are
        saved too; lookup tables may not be)."""
        self._t.send("e")

    # -- RF output -----------------------------------------------------------

    def set_frequency(self, frequency_mhz: float) -> None:
        """Sets the RF frequency (12.5-6400 MHz, 0.1 Hz resolution)."""
        f = _check_range("frequency_mhz", frequency_mhz, *FREQUENCY_RANGE_MHZ, "MHz")
        self._set("f", f, lambda: self._read_frequency(), tolerance=self.FREQUENCY_TOLERANCE_MHZ,
                  name="set_frequency")

    def get_frequency(self) -> float:
        return self._read_frequency()

    def _read_frequency(self) -> float:
        return self._query_float("f", self.SET_TIMEOUT_S)

    def set_power(self, power_dbm: float) -> None:
        """Sets the RF power (-60 to +20 dBm depending on frequency, 0.001 dB
        resolution, capped by :attr:`max_power_dbm`). The device recalibrates
        itself and gets as close as it can; check :meth:`is_calibrated`."""
        p = self._check_power("power_dbm", power_dbm)
        self._set("W", p, lambda: self._query_float("W", self.SET_TIMEOUT_S),
                  tolerance=self.POWER_TOLERANCE_DB, decimals=3, name="set_power")
        if self.verify and not self.is_calibrated():
            logger.warning("device reports the output is not calibrated/leveled at "
                           "%.3f dBm, %.4f MHz", p, self.get_frequency())

    def get_power(self) -> float:
        return self._query_float("W", self.SET_TIMEOUT_S)

    def is_calibrated(self) -> bool:
        """Whether the last frequency/power set calibrated successfully, i.e.
        the output should be accurate and leveled."""
        return parse_bool(self._t.request("V"))

    def set_muted(self, muted: bool = True) -> None:
        """Mutes the RF output without powering down the PLL. The amount of
        muting depends on frequency; use :meth:`disable` for a guaranteed off."""
        self._set("h", not muted, lambda: not self.is_muted(), not muted, name="set_muted")

    def mute(self) -> None:
        self.set_muted(True)

    def unmute(self) -> None:
        self.set_muted(False)

    def is_muted(self) -> bool:
        return not self._query_bool("h")

    def set_phase_step(self, degrees: float) -> None:
        """Adds a relative phase step (0-360 deg; 359 appears as -1). The
        absolute phase is unknown and resets on reboot or frequency change."""
        step = _check_range("degrees", degrees, 0.0, 360.0, "deg")
        self._t.send("~", step, decimals=3)

    def set_temp_compensation(self, method: TempCompensation) -> None:
        """How RF power is stabilised over temperature (default: every 10 s)."""
        method = TempCompensation(method)
        self._set("Z", int(method), lambda: TempCompensation(self._query_int("Z")), method,
                  name="set_temp_compensation")

    def get_temp_compensation(self) -> TempCompensation:
        return TempCompensation(self._query_int("Z"))

    def set_raw_dac(self, value: int, *, force: bool = False) -> None:
        """Bypasses the calibrated power setting with a raw VGA DAC value
        (0-4000; needs temperature compensation off). Because this skips the
        calibration it cannot honour :attr:`max_power_dbm`, so it is refused
        unless the limit is at its default or ``force=True``."""
        value = int(_check_range("value", value, 0, 4000))
        if self._max_power_dbm < POWER_RANGE_DBM[1] and not force:
            raise ValueError("raw DAC output bypasses max_power_dbm; pass force=True to allow")
        self._set("a", value, lambda: self._query_int("a"), name="set_raw_dac")

    def get_raw_dac(self) -> int:
        return self._query_int("a")

    def set_channel_spacing(self, hz: float) -> None:
        """Frequency resolution, 0.1-1000 Hz. Small spacings below 100 MHz can
        make tuning very slow and USB responses laggy."""
        hz = _check_range("hz", hz, 0.1, 1000.0, "Hz")
        self._set("i", hz, lambda: self._query_float("i"), tolerance=1e-3, name="set_channel_spacing")

    def get_channel_spacing(self) -> float:
        return self._query_float("i")

    def set_pll_charge_pump_current(self, value: int) -> None:
        """PLL loop bandwidth setting, 1-15 (0 would leave the PLL unlocked)."""
        value = int(_check_range("value", value, 1, 15))
        self._set("U", value, lambda: self._query_int("U"), name="set_pll_charge_pump_current")

    def get_pll_charge_pump_current(self) -> int:
        return self._query_int("U")

    def set_trigger_function(self, function: TriggerFunction) -> None:
        """What the trigger connector does (sweep/step triggers, external
        modulation inputs, ...)."""
        function = TriggerFunction(function)
        self._set("y", int(function), lambda: TriggerFunction(self._query_int("y")), function,
                  name="set_trigger_function")

    def get_trigger_function(self) -> TriggerFunction:
        return TriggerFunction(self._query_int("y"))


class ReferenceApi:
    """The 10 MHz / 27 MHz / external frequency reference."""

    def __init__(self, synth: SynthNVPro):
        self._s = synth

    def set_source(self, source: ReferenceSource) -> None:
        source = ReferenceSource(source)
        self._s._set("x", int(source), lambda: ReferenceSource(self._s._query_int("x")), source,
                     name="reference.set_source")

    def get_source(self) -> ReferenceSource:
        return ReferenceSource(self._s._query_int("x"))

    def set_frequency(self, frequency_mhz: float) -> None:
        """Frequency of an external reference, 10-100 MHz."""
        f = _check_range("frequency_mhz", frequency_mhz, 10.0, 100.0, "MHz")
        self._s._set("*", f, lambda: self._s._query_float("*"), tolerance=1e-3,
                     name="reference.set_frequency")

    def get_frequency(self) -> float:
        return self._s._query_float("*")

    def set_doubler(self, enabled: bool) -> None:
        """Doubles the phase-comparison frequency (keep it below 100 MHz);
        better phase noise at higher comparison frequencies."""
        self._s._set("D", bool(enabled), lambda: self._s._query_bool("D"), bool(enabled),
                     name="reference.set_doubler")

    def get_doubler(self) -> bool:
        return self._s._query_bool("D")


class DetectorApi:
    """The RFin power detector. Disable the generator (:meth:`SynthNVPro.disable`)
    for maximum dynamic range when not using it."""

    PER_READING_TIMEOUT_S = 0.05

    def __init__(self, synth: SynthNVPro):
        self._s = synth

    def set_mode(self, mode: DetectorMode) -> None:
        mode = DetectorMode(mode)
        self._s._set("&", int(mode), lambda: DetectorMode(self._s._query_int("&")), mode,
                     name="detector.set_mode")

    def get_mode(self) -> DetectorMode:
        return DetectorMode(self._s._query_int("&"))

    def read(self, n: int = 1) -> list[float]:
        """Measures RFin power ``n`` times (as fast as the device can); dBm."""
        n = int(_check_range("n", n, 1, 100000))
        lines = self._s._t.request_until_eom(
            "w", n, timeout=1.0 + n * self.PER_READING_TIMEOUT_S)
        values = [parse_float(line) for line in lines]
        if len(values) != n:
            raise ProtocolError(f"asked for {n} power readings, got {len(values)}")
        return values

    def read_one(self) -> float:
        return self.read(1)[0]


_TABLE_LINE = re.compile(r"L(\d+)f(\d+\.\d+)a(-?\d+\.\d+)")


class SweepApi:
    """Linear, tabular and percentage frequency sweeps.

    Typical use::

        synth.sweep.configure(2800, 2900, step_mhz=1, step_time_ms=10, power_dbm=-10)
        synth.enable()
        synth.sweep.start()
    """

    MAX_TABLE_POINTS = 499
    """500-entry table less one for the end-of-table entry (conservative)."""

    def __init__(self, synth: SynthNVPro):
        self._s = synth

    # -- configuration -------------------------------------------------------

    def configure(self, lower_mhz: float, upper_mhz: float, step_mhz: float, step_time_ms: float,
                  power_dbm: float | None = None, *, power_low_dbm: float | None = None,
                  power_high_dbm: float | None = None,
                  direction: SweepDirection = SweepDirection.LOWER_TO_UPPER,
                  continuous: bool = False) -> None:
        """Sets up a linear sweep. ``power_dbm`` applies to both ends; give
        ``power_low_dbm``/``power_high_dbm`` instead for a power ramp. With no
        power given, the powers already stored in the device are kept (and
        checked against the limit by :meth:`start`)."""
        if power_dbm is not None and (power_low_dbm is not None or power_high_dbm is not None):
            raise ValueError("give either power_dbm or power_low_dbm/power_high_dbm, not both")
        if power_dbm is not None:
            power_low_dbm = power_high_dbm = power_dbm
        lo = _check_range("lower_mhz", lower_mhz, *FREQUENCY_RANGE_MHZ, "MHz")
        hi = _check_range("upper_mhz", upper_mhz, *FREQUENCY_RANGE_MHZ, "MHz")
        if lo >= hi:
            raise ValueError(f"lower_mhz ({lo:g}) must be below upper_mhz ({hi:g})")
        step = float(step_mhz)
        if not 0 < step <= hi - lo:
            raise ValueError(f"step_mhz must be in (0, {hi - lo:g}], got {step:g}")
        time_ms = _check_range("step_time_ms", step_time_ms, 0.1, 60000.0, "ms")
        if power_low_dbm is not None:
            power_low_dbm = self._s._check_power("power_low_dbm", power_low_dbm, SWEEP_POWER_RANGE_DBM)
        if power_high_dbm is not None:
            power_high_dbm = self._s._check_power("power_high_dbm", power_high_dbm, SWEEP_POWER_RANGE_DBM)

        self.set_type(SweepType.LINEAR)
        self._set_freq("l", lo, "sweep.lower")
        self._set_freq("u", hi, "sweep.upper")
        self._set_freq("s", step, "sweep.step")
        self._s._set("t", time_ms, lambda: self._s._query_float("t"), tolerance=0.01,
                     decimals=3, name="sweep.step_time")
        if power_low_dbm is not None:
            self._set_power("[", power_low_dbm, "sweep.power_low")
        if power_high_dbm is not None:
            self._set_power("]", power_high_dbm, "sweep.power_high")
        self.set_direction(direction)
        self.set_continuous(continuous)

    def _set_freq(self, command: str, value: float, name: str) -> None:
        self._s._set(command, value, lambda: self._s._query_float(command),
                     tolerance=self._s.FREQUENCY_TOLERANCE_MHZ, name=name)

    def _set_power(self, command: str, value: float, name: str) -> None:
        self._s._set(command, value, lambda: self._s._query_float(command),
                     tolerance=self._s.POWER_TOLERANCE_DB, decimals=3, name=name)

    def set_type(self, sweep_type: SweepType) -> None:
        sweep_type = SweepType(sweep_type)
        self._s._set("X", int(sweep_type), lambda: SweepType(self._s._query_int("X")), sweep_type,
                     name="sweep.set_type")

    def get_type(self) -> SweepType:
        return SweepType(self._s._query_int("X"))

    def set_direction(self, direction: SweepDirection) -> None:
        direction = SweepDirection(direction)
        self._s._set("^", int(direction), lambda: SweepDirection(self._s._query_int("^")), direction,
                     name="sweep.set_direction")

    def get_direction(self) -> SweepDirection:
        return SweepDirection(self._s._query_int("^"))

    def set_continuous(self, continuous: bool) -> None:
        """Repeat the sweep forever (until :meth:`stop`) instead of once."""
        self._s._set("c", bool(continuous), lambda: self._s._query_bool("c"), bool(continuous),
                     name="sweep.set_continuous")

    def get_continuous(self) -> bool:
        return self._s._query_bool("c")

    def set_read_while_sweep(self, read: bool) -> None:
        """Measure RFin power after every new frequency during a sweep."""
        self._s._set("r", bool(read), lambda: self._s._query_bool("r"), bool(read),
                     name="sweep.set_read_while_sweep")

    def get_read_while_sweep(self) -> bool:
        return self._s._query_bool("r")

    def set_display(self, style: SweepDisplay) -> None:
        """What the device streams per step during a sweep; the stream ends
        with ``EOM.`` (see :meth:`read_results`)."""
        style = SweepDisplay(style)
        self._s._set("d", int(style), lambda: SweepDisplay(self._s._query_int("d")), style,
                     name="sweep.set_display")

    def get_display(self) -> SweepDisplay:
        return SweepDisplay(self._s._query_int("d"))

    def get_lower(self) -> float:
        return self._s._query_float("l")

    def get_upper(self) -> float:
        return self._s._query_float("u")

    def get_step(self) -> float:
        return self._s._query_float("s")

    def get_step_time(self) -> float:
        return self._s._query_float("t")

    def get_power_low(self) -> float:
        return self._s._query_float("[")

    def get_power_high(self) -> float:
        return self._s._query_float("]")

    # -- running -------------------------------------------------------------

    def start(self) -> None:
        """Starts (or restarts) the sweep after re-reading and sanity-checking
        what is stored in the device: ordering of the limits, a positive step
        and powers within :attr:`SynthNVPro.max_power_dbm`. The PLL must be
        enabled for there to be RF output."""
        sweep_type = self.get_type()
        if sweep_type == SweepType.LINEAR:
            lo, hi, step = self.get_lower(), self.get_upper(), self.get_step()
            if not lo < hi:
                raise ValueError(f"sweep lower ({lo:g} MHz) must be below upper ({hi:g} MHz)")
            if not 0 < step <= hi - lo:
                raise ValueError(f"sweep step {step:g} MHz is not within (0, {hi - lo:g}]")
            self._s._check_power("sweep power_low", self.get_power_low(), SWEEP_POWER_RANGE_DBM)
            self._s._check_power("sweep power_high", self.get_power_high(), SWEEP_POWER_RANGE_DBM)
        elif sweep_type == SweepType.TABULAR:
            for amp in self.read_table()["amplitude"]:
                self._s._check_power("sweep table power", amp)
        self._s._t.send("g", 1)

    def stop(self) -> None:
        """Pauses the sweep and clears continuous mode so it cannot resume
        on its own. Safe to call at any time."""
        self._s._t.send("g", 0)
        self._s._t.send("c", 0)

    def is_running(self) -> bool:
        return self._s._query_bool("g")

    def read_results(self, timeout: float = 10.0) -> SweepResult:
        """Collects the per-step output of a sweep (needs :meth:`set_display`
        not NONE) up to its ``EOM.`` marker."""
        style = self.get_display()
        if style == SweepDisplay.NONE:
            raise ValueError("sweep display is off; call set_display first")
        values = [parse_float(line) for line in self._s._t.read_until_eom(timeout=timeout)]
        if style == SweepDisplay.POWER_ONLY:
            return SweepResult(power_dbm=values, frequency_mhz=None)
        if len(values) % 2:
            raise ProtocolError(f"odd number of values ({len(values)}) in a frequency/power sweep")
        return SweepResult(power_dbm=values[1::2], frequency_mhz=values[0::2])

    # -- tabular sweep -------------------------------------------------------

    def read_table(self) -> dict[str, list[float]]:
        """Reads the frequency/power table: ``{"frequency": [...], "amplitude": [...]}``."""
        freqs: list[float] = []
        amps: list[float] = []
        for line in self._s._t.request_until_eom("L", query=True, timeout=10.0):
            match = _TABLE_LINE.match(line)
            if match is None:
                raise ProtocolError(f"unrecognised table line: {line!r}")
            if int(match.group(1)) != len(freqs):
                raise ProtocolError(f"unexpected table index in line: {line!r}")
            freqs.append(float(match.group(2)))
            amps.append(float(match.group(3)))
        return {"frequency": freqs, "amplitude": amps}

    def write_table(self, freqs_mhz: Sequence[float], powers_dbm: Sequence[float],
                    direction: SweepDirection = SweepDirection.LOWER_TO_UPPER) -> None:
        """Writes the frequency/power table (up to :attr:`MAX_TABLE_POINTS`
        entries) and checks it by reading it back."""
        if len(freqs_mhz) != len(powers_dbm):
            raise ValueError("frequency and power lists must be the same length")
        n = len(freqs_mhz)
        if not 1 <= n <= self.MAX_TABLE_POINTS:
            raise ValueError(f"table needs 1..{self.MAX_TABLE_POINTS} entries, got {n}")
        freqs = [_check_range("table frequency", f, *FREQUENCY_RANGE_MHZ, "MHz") for f in freqs_mhz]
        powers = [self._s._check_power("table power", p) for p in powers_dbm]
        direction = SweepDirection(direction)

        for i, (f, p) in enumerate(zip(freqs, powers)):
            self._s._t.send_raw(f"L{i:02}f{f:.6f}L{i:02}a{p:.2f}")
        # End-of-table entry plus direction, kept byte-for-byte from the
        # previous driver (note the direction digit is inverted relative to
        # set_direction; not yet confirmed on hardware).
        self._s._t.send_raw(f"L{n}f0.0L{n}a0.0^" + ("0" if direction == 1 else "1"))

        if self._s.verify:
            table = self.read_table()
            if (len(table["frequency"]) != n
                    or any(abs(a - b) > 1e-5 for a, b in zip(table["frequency"], freqs))
                    or any(abs(a - b) > 0.01 for a, b in zip(table["amplitude"], powers))):
                raise CommandError("sweep.write_table", "table read back does not match what was written")
