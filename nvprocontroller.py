from enum import Enum
import logging
import re
import time
import threading
from typing import Any, Dict, List, Optional, Tuple, Union

from serialconnection import SerialConnection
from command import Command


FORMATTER = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')
LOGGING_LEVEL = logging.INFO
LOGGER = logging.getLogger(__name__)
for handler in LOGGER.handlers:
    LOGGER.removeHandler(handler)
LOGGER.setLevel(LOGGING_LEVEL)
handler = logging.StreamHandler()
handler.setFormatter(FORMATTER)
LOGGER.addHandler(handler)
LOGGER.propagate = False


class TEMP_COMPENSATION(Enum):
    NONE = "0"
    ON_SET = "1"
    _1_SEC = "2"
    _10_SEC = "3"

class RF_DETECTOR_MODE(Enum):
    INSTANTANEOUS = "0"
    LOW_PASS = "1"
    EXPERIMENTAL = "2"

class RF_MUTE(Enum):
    NOT_MUTED = "1"
    MUTED = "0"

class REFERENCE_SOURCE(Enum):
    EXTERNAL = "0"
    INTERNAL_27MHZ = "1"
    INTERNAL_10MHZ = "2"

class TRIGGER_MODE(Enum):
    NO_TRIGGERS = "0"
    TRIGGER_FULL_FREQUENCY_SWEEP = "1"
    TRIGGER_SINGLE_FREQUENCY_STEP = "2"
    TRIGGER_STOP_ALL = "3"
    TRIGGER_DIGITAL_RF_ON_OFF = "4"
    REMOVE_INTERRUPTS = "5"
    RESERVED_1 = "6"
    RESERVED_2 = "7"
    EXTERNAL_AM_MODULATION_INPUT = "8"
    EXTERNAL_FM_MODULATION_INPUT = "9"

class SynthNVProController:

    def __init__(
        self,
        serial_connection: SerialConnection,
    ):
        self.connection = serial_connection
        self._lock = threading.RLock()

        self._is_initialised: bool = False
        "Set to true after initialise(). Set to false after finalise()."


    @classmethod
    def from_serial_port(
        cls, port: str = '/dev/ttyACM1', baud_rate: int = 2000000, *args, **kwargs
    ) -> "SynthNVProController":
        return cls(SerialConnection(port, baud_rate), *args, **kwargs)


    def send_command(self, command: str, wait_time: float = 0) -> str:
        LOGGER.debug(f"Sending command {command}.")
        with self._lock:
            self.connection.send_command(command)

    def get_help(self) -> str:
        command = Command.format(Command._QUERY_CHAR)
        self.send_command(command)
        return self.connection.read_responses(0.01)

    def set_rf_frequency(self, frequency_mhz: float):
        """The SynthNV Pro frequency is settable between 12.5MHz and 6400.0MHz. The setting is
        always in MHz.
        fxxxx.xxxxxxx sets frequency to x MHz in 0.1Hz resolution
        f? queries frequency setting in 0.1Hz resolution
        
        Args:
            frequency_mhz (float): The frequency in MHz
        
        Returns:
            None
        """
        command = Command.format(Command.SET_FREQUENCY_MHZ, arg=frequency_mhz)
        self.send_command(command)

    def get_rf_frequency(self) -> float:
        """The SynthNV Pro frequency is settable between 12.5MHz and 6400.0MHz. The setting is
        always in MHz.
        fxxxx.xxxxxxx sets frequency to x MHz in 0.1Hz resolution
        f? queries frequency setting in 0.1Hz resolution
        
        Args:
            None

        Returns:
            float: The frequency in MHz
        """
        command = Command.format(Command.SET_FREQUENCY_MHZ, query=True)
        self.send_command(command)
        return float(self.connection.read_response())
        
    def set_rf_power(self, power_dbm: float):
        """The SynthNV Pro RF power is settable between -60dBm and +20dBm depending on frequency.
        With this setting the SynthNV Pro will automatically calibrate itself and set the power as close as
        it can get to what is requested.
        Wxx.xxx sets RF power to x dBm in 0.001dB resolution
        W? queries the RF output power setting in 0.001dB resolution
        
        Args:
            power_dbm (float): The power in dBm
        
        Returns:
            None
        """
        command = Command.format(Command.SET_RF_POWER_dBm, arg=float(power_dbm), sigfigs=3)
        self.send_command(command)

    def get_rf_power(self) -> float:
        """The SynthNV Pro RF power is settable between -60dBm and +20dBm depending on frequency.
        With this setting the SynthNV Pro will automatically calibrate itself and set the power as close as
        it can get to what is requested.
        Wxx.xxx sets RF power to x dBm in 0.001dB resolution
        W? queries the RF output power setting in 0.001dB resolution
        
        Args:
            None

        Returns:
            float: The power in dBm
        """
        command = Command.format(Command.SET_RF_POWER_dBm, query=True)
        self.send_command(command)
        return float(self.connection.read_response())
    
    def get_calibration_succesful(self) -> bool:
        """If the SynthNV Pro can successfully complete its calibration routine upon frequency or
        amplitude set, it will set a flag of 1 showing the output should be accurate and leveled.
        V queries if there was successful calibration. 1=success, 0=failure
        
        Args:
            None
        
        Returns:
            bool: True if the calibration was successful, False otherwise
            """
        command = Command.format(Command.QUERY_CAL_SUCCESS)
        self.send_command(command)
        return bool(self.connection.read_response())

    def set_temp_compensation(self, method: TEMP_COMPENSATION):
        """The SynthNV Pro RF power can be stabilized over temperature. “On set” means that it will only
        be adjusted for when frequency or power is set. The 1 second and 10 second setting will also
        both be adjusted “on set” as well but also automatically compensate every 1 or 10 seconds
        respectively. The default setting is to automatically run the routine every 10 seconds. During
        modulation, the temperature compensation routine is put on hold and resumes once modulation is
        turned off.
        Zx sets the method for temperature compensation (x=0=none, 1=on set, 2=1sec, 3=10sec).
        Z? queries the setting for Temperature Compensation
        
        Args:
            method (TEMP_COMPENSATION): The method for temperature compensation

        Returns:
            None
            """
        command = Command.format(Command.SET_TEMP_COMPENSATION, arg=method.value)
        self.send_command(command)

    def read_power_detector(self, x: int = None) -> float:
        """Measure detected RF power on the RFin connector. The report is in dBm followed by
        `/nEOM./n` where `/n` is a line feed termination character. Sending `w` or `w0` or `w1` all
        respond with 1 measurement. If requesting more than 1 measurement, the device measures as
        fast as it can and each dBm response is followed by “/n” with the end of message designated by
        `EOM./n` . The RF detector uses the RF generator frequency setting for its calibration
        frequency. Disable the RF generator (`E0`) for maximum dynamic range if not concurrently
        using the RF generator.
        An example response for a `w5` command is as follows:
        ```
        -10.176  
        -10.176  
        -10.149  
        -10.176  
        -10.176  
        EOM.
        ```
        wx measures RFin power x times

        Args:
            x (int): The number of measurements to take. If None, defaults to 1.

        Returns:
            float or List[float]: The power in dBm
        """
        command = Command.format(Command.READ_POWER_DETECTOR, arg=x)
        self.send_command(command)
        responses = []
        while (response := self.connection.read_response()) != "EOM.":
            responses.append(float(response))
        return responses

    def set_rf_detector_mode(self, mode: RF_DETECTOR_MODE):
        """The RF power detector can asynchronously measure RF power in 1 of 3 modes:
        0) (“&0”) The default measurement mode is instantaneous. This mode sets the log detector
        to measure with no averaging. Its best for CW signals with similar peak and average
        power levels. This mode is calibrated.
        1) (“&1”) This mode runs the output of the log detector through an RC (series resistor, shunt
        capacitor) low pass filter to achieve some amount of averaging of the incoming signal.
        Use this mode for signals with different peak and average powers that vary quickly. The
        RC time constant (t=R*C) is 5.6mS. This mode is calibrated.
        2) (“&2”) This mode runs the output of the log detector through a series diode, shunt
        capacitor to attempt to capture sporadic peak RF events, possibly in conjunction with
        using the internal speaker. This mode is experimental and not calibrated due to the diode

        Args:
            mode (RF_DETECTOR_MODE): The mode for the RF detector
        
        Returns:
            None
        """
        command = Command.format(Command.SET_RF_DETECTOR_MODE, arg=mode.value)
        self.send_command(command)

    def get_rf_detector_mode(self):
        """The RF power detector can asynchronously measure RF power in 1 of 3 modes:
        0) (“&0”) The default measurement mode is instantaneous. This mode sets the log detector
        to measure with no averaging. Its best for CW signals with similar peak and average
        power levels. This mode is calibrated.
        1) (“&1”) This mode runs the output of the log detector through an RC (series resistor, shunt
        capacitor) low pass filter to achieve some amount of averaging of the incoming signal.
        Use this mode for signals with different peak and average powers that vary quickly. The
        RC time constant (t=R*C) is 5.6mS. This mode is calibrated.
        2) (“&2”) This mode runs the output of the log detector through a series diode, shunt
        capacitor to attempt to capture sporadic peak RF events, possibly in conjunction with
        using the internal speaker. This mode is experimental and not calibrated due to the diode

        Args:
            None
        
        Returns:
            RF_DETECTOR_MODE: The mode for the RF detector
        """
        command = Command.format(Command.SET_RF_DETECTOR_MODE, query=True)
        self.send_command(command)
        return RF_DETECTOR_MODE(self.connection.read_response())

    def set_raw_dac(self, dac_value: int):
        """The SynthNV Pro RF power setting can be bypassed and set with a raw VGA DAC value
        between 0 and 4000. A setting of 0 is minimal and 4000 would be maximum gain. To use this
        function Temperature Compensation must be turned off with “Z0”.
        ax sets DAC value for x drive level where x is between 0 and 4000
        a? queries the DAC setting
        
        Args:
            dac_value (int): The DAC value
        
        Returns:
            None
        """
        command = Command.format(Command.SET_RAW_DAC, arg=dac_value)
        self.send_command(command)

    def get_raw_dac(self) -> int:
        """The SynthNV Pro RF power setting can be bypassed and set with a raw VGA DAC value
        between 0 and 4000. A setting of 0 is minimal and 4000 would be maximum gain. To use this
        function Temperature Compensation must be turned off with “Z0”.
        ax sets DAC value for x drive level where x is between 0 and 4000
        a? queries the DAC setting
        
        Args:
            None
        
        Returns:
            int: The DAC value
        """
        command = Command.format(Command.SET_RAW_DAC, query=True)
        self.send_command(command)
        return int(self.connection.read_response())

    def set_phase_step(self, phase_step: float):
        """The SynthNV Pro RF phase can be adjusted. These adjustments are relative adjustments that add
        the phase amount to the current phase being generated. There is no way (currently) to know the
        absolute phase setting of the SynthNV Pro without external measurement. Every reboot or
        frequency change (besides FM) will reset the phase to an arbitrary value.
        ~xxx.xxx sends a phase increment to the SynthNV Pro in x degrees. (Sending x359.0 will appear
        to decrement the phase by 1.0 degrees).
        ~? Has no real meaning.
        
        Args:
            phase_step (float) : The phase increment in degrees

        Returns:
            None
        """
        command = Command.format(Command.SET_PHASE_STEP, arg=phase_step)
        self.send_command(command)

    def set_rf_mute(self, mute: RF_MUTE):
        """The SynthNV Pro output power can be muted without fully powering down the PLL. The
        amount of muting depends on frequency.
        hx sets the muting function where x=1=not muted and x=0=muted
        h? queries the setting
        
        Args:
            mute (RF_MUTE): The mute setting

        Returns:
            None
        """
        command = Command.format(Command.SET_RF_MUTE, arg=mute.value)
        self.send_command(command)

    def get_rf_mute(self) -> RF_MUTE:
        """The SynthNV Pro output power can be muted without fully powering down the PLL. The
        amount of muting depends on frequency.
        hx sets the muting function where x=1=not muted and x=0=muted
        h? queries the setting
        
        Args:
            None

        Returns:
            RF_MUTE: The mute setting
        """
        command = Command.format(Command.SET_RF_MUTE, query=True)
        self.send_command(command)
        return RF_MUTE(self.connection.read_response())

    def set_pll_enable(self, enable: bool):
        """The SynthNV Pro PLL can be powered down for absolute minimum noise on the output
        connector. This command enables and disables the PLL and VCO to save energy and can take
        20mS to boot up.
        Ex sets the enable function where x=1=powered on and x=0=powered off
        E? queries the setting
        
        Args:
            enable (bool): True to enable, False to disable

        Returns:
            None
        """
        command = Command.format(Command.PLL_ENABLE, arg=int(enable))
        self.send_command(command)

    def get_pll_enable(self) -> bool:
        """The SynthNV Pro PLL can be powered down for absolute minimum noise on the output
        connector. This command enables and disables the PLL and VCO to save energy and can take
        20mS to boot up.
        Ex sets the enable function where x=1=powered on and x=0=powered off
        E? queries the setting
        
        Args:
            None

        Returns:
            bool: True if enabled, False if disabled
        """
        command = Command.format(Command.PLL_ENABLE, query=True)
        response = self.send_command(command)
        return bool(response)
    
    def set_pll_charge_pump_current(self, x: int) -> None:
        """PLL loop filter bandwidth can be adjusted to a certain degree through the PLL charge pump
        current setting. This can affect things like lock time, phase noise and FM quantization noise. In
        general, higher values give higher loop filter bandwidths, but the steps are not monotonic. Higher
        bandwidths tend to have better phase noise and stepping times, but possibly higher spurs. A
        setting of zero should be avoided as the charge pump output is tri-stated and the PLL will not
        phase lock.
        Ux sets the the charge pump current where x=1 through 15 is allowed
        U? queries the setting
        """
        x = int(x)
        if x < 1 or x > 15:
            raise ValueError("Charge pump current must be between 1 and 15.")
        command = Command.format(Command.SET_PLL_CHARGE_PUMP_CURRENT, arg=x)
        self.send_command(command)

    def get_pll_charge_pump_current(self) -> int:
        """PLL loop filter bandwidth can be adjusted to a certain degree through the PLL charge pump
        current setting. This can affect things like lock time, phase noise and FM quantization noise. In
        general, higher values give higher loop filter bandwidths, but the steps are not monotonic. Higher
        bandwidths tend to have better phase noise and stepping times, but possibly higher spurs. A
        setting of zero should be avoided as the charge pump output is tri-stated and the PLL will not
        phase lock.
        Ux sets the the charge pump current where x=1 through 15 is allowed
        U? queries the setting
        """
        command = Command.format(Command.SET_PLL_CHARGE_PUMP_CURRENT, query=True)
        self.send_command(command)
        return int(self.connection.read_response())
    
    def set_reference_doubler(self, x: int):
        """
        The doubler will control whether the phase detector phase comparison frequency runs at the
        reference frequency or at double the reference frequency. Keep the comparison frequency below
        100MHz. Use the doubler and higher comparison frequencies for achieving better phase noise.
        Dx turns on and off the reference doubler where x=0 doubler disabled and x=1 is doubler
        enabled.
        """
        if x not in [0, 1]:
            raise ValueError("Invalid value for reference doubler. Must be 0 (disabled) or 1 (enabled).")
        self.send_command(Command.format(Command.SET_REFERENCE_DOUBLER, arg=x))

    def query_reference_doubler(self):
        """
        The doubler will control whether the phase detector phase comparison frequency runs at the
        reference frequency or at double the reference frequency. Keep the comparison frequency below
        100MHz. Use the doubler and higher comparison frequencies for achieving better phase noise.
        Dx turns on and off the reference doubler where x=0 doubler disabled and x=1 is doubler
        enabled.
        """
        self.send_command(Command.format(Command.SET_REFERENCE_DOUBLER, query=True))
        return int(self.connection.read_response())

    def set_channel_spacing(self, frequency: float):
        """
        Sets the frequency resolution for the RF signal generator between 0.1Hz and 1000Hz. The
        SynthNV Pro will attempt to achieve mathematically perfect RF frequency settings at the
        fundamental VCO frequency. The drawback for small settings can be very long phase tuning
        time, especially at low RF frequencies. Smaller channel spacing will have higher phase and
        frequency resolutions but slower phase tuning speed. Going below 100MHz carrier with smaller
        channel spacing than 100Hz may be prohibitively slow and/or erratic and may cause slow USB
        communication response times.
        ix sets the channel spacing x is the frequency in Hz
        """
        frequency = float(frequency)
        if not 0.1 <= frequency <= 1000:
            raise ValueError("Channel spacing must be between 0.1Hz and 1000Hz.")
        self.send_command(Command.format(Command.SET_CHANNEL_SPACING, arg=frequency))

    def query_channel_spacing(self):
        """
        Sets the frequency resolution for the RF signal generator between 0.1Hz and 1000Hz. The
        SynthNV Pro will attempt to achieve mathematically perfect RF frequency settings at the
        fundamental VCO frequency. The drawback for small settings can be very long phase tuning
        time, especially at low RF frequencies. Smaller channel spacing will have higher phase and
        frequency resolutions but slower phase tuning speed. Going below 100MHz carrier with smaller
        channel spacing than 100Hz may be prohibitively slow and/or erratic and may cause slow USB
        communication response times.
        ix sets the channel spacing x is the frequency in Hz
        """
        self.send_command(Command.format(Command.SET_CHANNEL_SPACING, query=True))
        return float(self.connection.read_response())

    def save_settings_to_eeprom(self):
        """
        All of the settings currently set in the SynthNV Pro can be programmed to the SynthNV Pro
        nonvolatile memory for default operation on power up. Verify that the SynthNV Pro is set
        exactly the way you need it set before sending this command since it will also save a state that
        may not work. Almost all functions like modulation, sweep etc. are saved. Lookup tables
        (sweep, FM, AM) may not be saved.
        e saves all variables in the SynthNV Pro for power up boot
        """
        self.send_command(Command.format(Command.SAVE_SETTINGS_TO_EEPROM))

    def set_reference_source(self, source: REFERENCE_SOURCE):
        """
        The SynthNV Pro has two internal references (10MHz and 27MHz). It also has the ability to use
        an external reference. If using an external reference, see the “*” PLL Reference Frequency
        Command.
        xy sets the reference where y=0=external, y=1=internal 27MHz, y=2=internal 10MHz
        """
        self.send_command(Command.format(Command.SET_REFERENCE_SOURCE, arg=source.value))

    def query_reference_source(self):
        """
        The SynthNV Pro has two internal references (10MHz and 27MHz). It also has the ability to use
        an external reference. If using an external reference, see the “*” PLL Reference Frequency
        Command.
        xy sets the reference where y=0=external, y=1=internal 27MHz, y=2=internal 10MHz
        """
        self.send_command(Command.format(Command.SET_REFERENCE_SOURCE, query=True))
        return int(self.connection.read_response())

    def set_reference_frequency(self, frequency: float):
        """
        The SynthNV Pro reference frequency is settable between 10.0MHz and 100.0MHz. The setting
        is always in MHz. Reference frequency is automatically set when one of the internal frequencies
        is selected with the “x” command.
        *xxx.xxx sets frequency to x MHz in 0.001MHz resolution
        """
        frequency = float(frequency)
        if not 10.0 <= frequency <= 100.0:
            raise ValueError("Reference frequency must be between 10.0MHz and 100.0MHz.")
        self.send_command(Command.format(Command.SET_REFERENCE_FREQUENCY, arg=frequency))

    def query_reference_frequency(self):
        """
        The SynthNV Pro reference frequency is settable between 10.0MHz and 100.0MHz. The setting
        is always in MHz. Reference frequency is automatically set when one of the internal frequencies
        is selected with the “x” command.
        *xxx.xxx sets frequency to x MHz in 0.001MHz resolution
        """
        self.send_command(Command.format(Command.SET_REFERENCE_FREQUENCY, query=True))
        return float(self.connection.read_response())
        
    def set_trigger_connector_function(self, function: TRIGGER_MODE) -> None:
        """The SynthNV Pro Trigger input is a multifunction input. It is used for trigger events, but also
        used for other things like external FM, AM and Pulse modulation inputs. The values are:```
        0) No Triggers
        12.5MHz – 6.4GHz Signal Generator plus RF Detector
        10 Windfreak Technologies, LLC.
        1) Trigger full frequency sweep
        2) Trigger single frequency step
        3) Trigger “stop all” which pauses sequencing through all functions of the SynthNV Pro
        4) Trigger digital RF ON/OFF – Could be used for External Pulse Modulation
        5) Remove Interrupts (Makes modulation have less jitter – use carefully)
        6) Reserved
        7) Reserved
        8) External AM modulation input (requires AM Internal modulation LUT set to ramp)
        9) External FM modulation input (requires FM Internal modulation set to chirp)```
        """
        self.send_command(Command.format(Command.SET_TRIGGER_CONNECTOR_FUNCTION, arg=function.value))

    def get_trigger_connector_function(self) -> TRIGGER_MODE:
        """The SynthNV Pro Trigger input is a multifunction input. It is used for trigger events, but also
        used for other things like external FM, AM and Pulse modulation inputs. The values are:```
        0) No Triggers
        12.5MHz – 6.4GHz Signal Generator plus RF Detector
        10 Windfreak Technologies, LLC.
        1) Trigger full frequency sweep
        2) Trigger single frequency step
        3) Trigger “stop all” which pauses sequencing through all functions of the SynthNV Pro
        4) Trigger digital RF ON/OFF – Could be used for External Pulse Modulation
        5) Remove Interrupts (Makes modulation have less jitter – use carefully)
        6) Reserved
        7) Reserved
        8) External AM modulation input (requires AM Internal modulation LUT set to ramp)
        9) External FM modulation input (requires FM Internal modulation set to chirp)```
        """
        self.send_command(Command.format(Command.SET_TRIGGER_CONNECTOR_FUNCTION, query=True))
        return TRIGGER_MODE(self.connection.read_response())
    
    def set_lower_freq_linear_sweep(self, frequency: float):
        """Sets the lower frequency for the linear sweep in MHz. This frequency should be lower than the
        Upper Frequency and kept within 12.5MHz – 6400MHz."""
        frequency = float(frequency)
        if not 12.5 <= frequency <= 6400:
            raise ValueError("Lower frequency for linear sweep must be between 12.5MHz and 6400MHz.")
        self.send_command(Command.format(Command.SET_LOWER_FREQ_LINEAR_SWEEP, arg=frequency))

    def get_lower_freq_linear_sweep(self) -> float:
        """Gets the lower frequency for the linear sweep in MHz. This frequency should be lower than the
        Upper Frequency and kept within 12.5MHz – 6400MHz."""
        self.send_command(Command.format(Command.SET_LOWER_FREQ_LINEAR_SWEEP, query=True))
        return float(self.connection.read_response())
    
    def set_upper_freq_linear_sweep(self, frequency: float):
        """Sets the upper frequency for the linear sweep in MHz. This frequency should be higher than the
        Lower Frequency and kept within 12.5MHz – 6400MHz."""
        frequency = float(frequency)
        if not 12.5 <= frequency <= 6400:
            raise ValueError("Lower frequency for linear sweep must be between 12.5MHz and 6400MHz.")
        self.send_command(Command.format(Command.SET_UPPER_FREQ_LINEAR_SWEEP, arg=frequency))

    def get_upper_freq_linear_sweep(self) -> float:
        """Gets the upper frequency for the linear sweep in MHz. This frequency should be higher than the
        Lower Frequency and kept within 12.5MHz – 6400MHz."""
        self.send_command(Command.format(Command.SET_UPPER_FREQ_LINEAR_SWEEP, query=True))
        return float(self.connection.read_response())
    
    def set_step_size_freq_linear_sweep(self, frequency: float):
        """Sets the step size frequency for the linear sweep in MHz. This frequency should be smaller than
        the range between Lower and Upper frequencies."""
        frequency = float(frequency)
        self.send_command(Command.format(Command.SET_STEP_SIZE_FREQ_LINEAR_SWEEP, arg=frequency))

    def get_step_size_freq_linear_sweep(self) -> float:
        """Gets the step size frequency for the linear sweep in MHz. This frequency should be smaller than
        the range between Lower and Upper frequencies."""
        self.send_command(Command.format(Command.SET_STEP_SIZE_FREQ_LINEAR_SWEEP, query=True))
        return float(self.connection.read_response())
    
    def set_linear_sweep_power_low(self, power: float):
        """Sets the sweep RF power in dBm for the Lower Frequency setting of the sweep. RF Power
        should be within the range of -50 to +20dBm. This value is used in combination with the Sweep
        Power High (]) and causes a linear adjustment of power as the sweep occurs. Keep both values
        the same to have a level sweep.
        [xx.xxx sets the lower RF sweep power setting in dBm.
        [? queries the setting
        """
        power = float(power)
        if not -50 <= power <= 20:
            raise ValueError("Sweep RF power must be within the range of -50 to +20dBm.")
        self.send_command(Command.format(Command.SET_LINEAR_SWEEP_POWER_LOW, arg=power, sigfigs=3))

    def get_linear_sweep_power_low(self) -> float:
        """Gets the sweep RF power in dBm for the Lower Frequency setting of the sweep. RF Power
        should be within the range of -50 to +20dBm. This value is used in combination with the Sweep
        Power High (]) and causes a linear adjustment of power as the sweep occurs. Keep both values
        the same to have a level sweep.
        [xx.xxx sets the lower RF sweep power setting in dBm.
        [? queries the setting
        """
        self.send_command(Command.format(Command.SET_LINEAR_SWEEP_POWER_LOW, query=True))
        return float(self.connection.read_response())

    def set_linear_sweep_power_high(self, power: float):
        """Sets the sweep RF power in dBm for the Upper Frequency setting of the sweep. RF Power
        should be within the range of -50 to +20dBm. This value is used in combination with the Sweep
        Power Low ([) and causes a linear adjustment of power as the sweep occurs. Keep both values
        the same to have a level sweep.
        ]xx.xxx sets the upper frequency RF sweep power setting in dBm.
        ]? queries the setting
        """
        power = float(power)
        if not -50 <= power <= 20:
            raise ValueError("Sweep RF power must be within the range of -50 to +20dBm.")
        self.send_command(Command.format(Command.SET_LINEAR_SWEEP_POWER_HIGH, arg=power, sigfigs=3))

    def get_linear_sweep_power_high(self) -> float:
        """Gets the sweep RF power in dBm for the Upper Frequency setting of the sweep. RF Power
        should be within the range of -50 to +20dBm. This value is used in combination with the Sweep
        Power Low ([) and causes a linear adjustment of power as the sweep occurs. Keep both values
        the same to have a level sweep.
        ]xx.xxx sets the upper frequency RF sweep power setting in dBm.
        ]? queries the setting
        """
        self.send_command(Command.format(Command.SET_LINEAR_SWEEP_POWER_HIGH, query=True))
        return float(self.connection.read_response())

    def set_sweep_direction(self, direction: int):
        """Sets the sweep direction from upper frequency to lower frequency or vice versa.
        ^x sets the direction where x=0 is from upper frequency to lower frequency and x=1 is from
        lower frequency to upper frequency. For tabular sweep x=0 reverses the order of the steps and
        x=1 is normal increment.
        ^? queries the setting
        """
        if direction not in [0, 1]:
            raise ValueError("Invalid sweep direction. Use 0 for upper frequency to lower frequency and 1 for lower frequency to upper frequency.")
        self.send_command(Command.format(Command.SET_SWEEP_DIRECTION, arg=direction))

    def get_sweep_direction(self) -> int:
        """Gets the sweep direction from upper frequency to lower frequency or vice versa.
        ^x sets the direction where x=0 is from upper frequency to lower frequency and x=1 is from
        lower frequency to upper frequency. For tabular sweep x=0 reverses the order of the steps and
        x=1 is normal increment.
        ^? queries the setting
        """
        self.send_command(Command.format(Command.SET_SWEEP_DIRECTION, query=True))
        return int(self.connection.read_response())

    def set_sweep_type(self, sweep_type: int):
        """Determines whether to do a linear sweep (0), tabular sweep (1) (500 point frequency and power
        table hopping), or a percentage of frequency sweep (3).
        Xy toggles the type of sweep to perform where y=0=linear, y=1=tabular and y=2=percentage
        X? queries the setting
        """
        if sweep_type not in [0, 1, 2]:
            raise ValueError("Invalid sweep type. Use 0 for linear sweep, 1 for tabular sweep, and 2 for percentage of frequency sweep.")
        self.send_command(Command.format(Command.SET_SWEEP_TYPE, arg=sweep_type))

    def get_sweep_type(self) -> int:
        """Gets the sweep type: linear sweep (0), tabular sweep (1) (500 point frequency and power
        table hopping), or a percentage of frequency sweep (3).
        Xy toggles the type of sweep to perform where y=0=linear, y=1=tabular and y=2=percentage
        X? queries the setting
        """
        self.send_command(Command.format(Command.SET_SWEEP_TYPE, query=True))
        return int(self.connection.read_response())

    def set_read_while_sweep(self, read: bool):
        """Sets the SynthNV pro to measure its power detector on RFin after every new frequency is set in
        the generator - only during an automated sweep. This does not control the display of the data,
        only the measurement.
        rx sets read while sweep, where x=0 is don’t read and x=1 is to read.
        r? queries the setting
        """
        self.send_command(Command.format(Command.SET_READ_WHILE_SWEEP, arg=int(read)))

    def get_read_while_sweep(self) -> bool:
        """Gets the setting for measuring the power detector on RFin after every new frequency is set in
        the generator - only during an automated sweep. This does not control the display of the data,
        only the measurement.
        rx sets read while sweep, where x=0 is don’t read and x=1 is to read.
        r? queries the setting
        """
        self.send_command(Command.format(Command.SET_READ_WHILE_SWEEP, query=True))
        response = self.connection.read_response()
        return bool(int(response))
    
    def set_sweep_display_style(self, style: int):
        """Sets the SynthNV Pro to display the frequency in MHz and/or power in dBm after every new
        frequency is set in the generator - only during an automated sweep. Every value of the sweep is
        followed by a “/n” (line feed) termination character and the total sweep is final after an
        “EOM./n” end of message flag.
        A sweep of 6 data points from 1000.0MHz to 2000.0MHz at 200.0MHz steps with a “d1” setting
        would look similar to:
        1000.00000
        -9.96
        1200.00000
        -10.26
        1400.00000
        -10.38
        1600.00000
        -10.08
        1800.00000
        -9.81
        2000.00000
        -9.84
        EOM.
        dx sets sweep display style, where x=0 is don’t display, x=1 is display frequency and amplitude,
        and x=2 is display only amplitude.
        d? queries the setting
        """
        if style not in [0, 1, 2]:
            raise ValueError("Invalid sweep display style. Use 0 for don't display, 1 for display frequency and amplitude, and 2 for display only amplitude.")
        self.send_command(Command.format(Command.SET_SWEEP_DISPLAY_STYLE, arg=style))

    def get_sweep_display_style(self) -> int:
        """Gets the sweep display style: 0 for don't display, 1 for display frequency and amplitude, and 2 for display only amplitude.
        d? queries the setting
        """
        self.send_command(Command.format(Command.SET_SWEEP_DISPLAY_STYLE, query=True))
        return int(self.connection.read_response())

    def run_sweep(self):
        """Starts a sweep. Once complete the value is automatically returned to 0 unless Sweep Continuous
        “c” is set to 1. If “c” is set to 1 then the sweep process automatically repeats forever. If Sweep
        Continuous “c” is set to 0 a g1 will completely restart the sweep no matter where the sweep is at.
        If “c” is set to 1 a “g0” will pause the sweep and a “g1” will continue the sweep.
        gx controls running a single sweep when x=1=start, restart or continue and x=0=pause
        g? queries the setting
        """
        self.send_command(Command.format(Command.RUN_SWEEP))

    def set_sweep_continuous(self, continuous: bool):
        """Sets sweep continuously mode. If asserted (“c1”) the Run Sweep “g” command will not be reset
        to 0 after a complete sweep and sweeping or hopping will continue until a “g0” command is sent.
        Alternatively, a “c0” will terminate the sweep after it is complete.
        cx controls running a single sweep when x=0 and continuous, repetitive sweeping when x=1
        c? queries the setting
        """
        self.send_command(Command.format(Command.SET_SWEEP_CONTINUOUS, arg=int(continuous)))

    def get_sweep_continuous(self) -> bool:
        """Gets the setting for sweep continuously mode: True if continuous, False if single sweep.
        c? queries the setting
        """
        self.send_command(Command.format(Command.SET_SWEEP_CONTINUOUS, query=True))
        response = self.connection.read_response()
        return bool(int(response))
    
    def query_internal_temperature(self) -> float:
        """Queries the temperature of the SynthNV Pro and returns the value in degrees C."""
        self.send_command(Command.format(Command.QUERY_INTERNAL_TEMPERATURE, query=True))
        return float(self.connection.read_response())

    def show_version(self, version_type: int) -> str:
        """Shows the version of firmware and hardware used in the SynthNV Pro.
        version_type: 0 for firmware version, 1 for hardware version.
        """
        if version_type not in [0, 1]:
            raise ValueError("Invalid version type. Use 0 for firmware version and 1 for hardware version.")
        self.send_command(Command.format(Command.SHOW_VERSION, arg=version_type))
        return self.connection.read_response()

    def show_model_type(self) -> str:
        """Shows the version of firmware and hardware used in the SynthNV Pro.
        Example: “WFT SynthNVP 55”
        """
        self.send_command(Command.format(Command.SHOW_MODEL_TYPE))
        return self.connection.read_response()

    def show_serial_number(self) -> str:
        """Shows the unique serial number used in the SynthNV Pro.
        It’s the same number as shown on the sticker on the bottom of the device.
        """
        self.send_command(Command.format(Command.SHOW_SERIAL_NUMBER))
        return self.connection.read_response()