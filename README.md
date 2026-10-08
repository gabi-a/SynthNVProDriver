# SynthNVProDriver

Python client for the Windfreak SynthNV Pro RF synthesizer (USB serial). The API
follows the conventions of the `syncboard` client: auto-discovery, a context
manager that leaves the hardware safe, synchronous calls that succeed or raise,
per-subsystem sub-APIs, and unit tests that need no hardware.

```python
from SynthNVProDriver import SynthNVPro

with SynthNVPro.connect() as synth:     # port auto-discovered
    synth.set_frequency(2870.0)         # MHz
    synth.set_power(-10.0)              # dBm
    synth.enable()                      # PLL on: RF output live

    synth.sweep.configure(2800, 2900, step_mhz=1, step_time_ms=10, power_dbm=-10)
    synth.sweep.start()
    ...
    synth.sweep.stop()

    print(synth.detector.read(5))       # RFin power, dBm
# leaving the block stops sweeps, powers the PLL/VCO down (no RF) and closes the port
```

`SynthNVPro.connect(port=None)` probes the USB serial ports with a harmless
model query (`+`) and uses the one that answers as a SynthNV Pro. With several
devices, use `find_ports()` and pass the port you want.

## Safety and error handling

- The device does not acknowledge commands, so every setting is **read back and
  checked** (`verify=True`); a mismatch raises `CommandError`. Pass
  `verify=False` to skip this.
- Arguments are range-checked **before anything is sent** (`ValueError`).
- `max_power_dbm` (constructor or attribute) caps every power this API will set,
  including sweeps and tables; `start()` re-reads the stored sweep and refuses
  an inconsistent or over-limit configuration. `set_raw_dac` bypasses the
  calibration, so it is refused when a limit is set unless `force=True`.
- `disable()` stops sweeps and powers the PLL/VCO down; `close()` does this
  unless `close(disable=False)`.
- No reply within the timeout raises `ResponseTimeout` (the device may still
  have executed the command). Unsolicited input is discarded before each query.
- `synth.reconnect()` reopens the port after the device re-enumerates.

Logging goes to the `"SynthNVProDriver"` logger; nothing is configured on import:

```python
import logging
logging.basicConfig(level=logging.DEBUG)   # DEBUG shows every byte sent/received
```

## API sketch

| Area | Methods |
|---|---|
| System | `connect`, `close`, `reconnect`, `ping`, `info`, `status`, `enable`, `disable`, `is_enabled`, `get_temperature`, `save_to_eeprom`, `help` |
| RF output | `set/get_frequency`, `set/get_power`, `is_calibrated`, `set_muted`/`mute`/`unmute`/`is_muted`, `set_phase_step`, `set/get_temp_compensation`, `set/get_raw_dac`, `set/get_channel_spacing`, `set/get_pll_charge_pump_current`, `set/get_trigger_function` |
| `synth.reference` | `set/get_source`, `set/get_frequency`, `set/get_doubler` |
| `synth.detector` | `set/get_mode`, `read(n)`, `read_one` |
| `synth.sweep` | `configure`, `start`, `stop`, `is_running`, `read_results`, `set/get_type/direction/continuous/display/read_while_sweep`, `get_lower/upper/step/step_time/power_low/power_high`, `read_table`, `write_table` |

## Development

```sh
uv run --group dev pytest        # unit tests against a fake serial device
uv run python hwtest/checkout.py # interactive check with the real device
```

## Migrating from the old `SynthNVProController`

The old `nvprocontroller`, `NVPserialconnection` and `NVPcommand` modules are
gone. `SynthNVProController.from_serial_port(port)` becomes
`SynthNVPro.connect(port)`; `query_*` getters are now `get_*`; enums are
`IntEnum`s; the RF mute setting is a bool. Two old bugs were fixed:
`get_calibration_succesful` returned True for `"0"` (now `is_calibrated`), and
`get_pll_enable` always returned False (now `is_enabled`).

## Hardware notes

Verified on a real device (firmware 2.07, USB id `0483:a3e7`): discovery, info,
status, frequency/power/enable/disable with read-back verification, the
detector, and sweep configuration. Setting commands produce no reply. `z?`
(temperature) must be sent as plain `z`, since the trailing `?` also triggers
the help dump. The device can power up with its output **on** (at its saved
power), so start scripts with `synth.disable()`.

Not yet verified: `sweep.start()` results, tabular sweeps (`write_table`, whose
direction digit is kept from the old driver), and the 499-entry table limit.

On Linux, give your user access to the port, e.g.:

```sh
echo 'SUBSYSTEM=="tty", ATTRS{idVendor}=="0483", ATTRS{idProduct}=="a3e7", MODE="0666"' | sudo tee /etc/udev/rules.d/99-synthnvpro.rules
sudo udevadm control --reload && sudo udevadm trigger
```
