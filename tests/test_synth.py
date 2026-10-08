import pytest

from SynthNVProDriver import (
    CommandError,
    DetectorMode,
    SweepDirection,
    SweepDisplay,
    SweepType,
    TempCompensation,
)
from tests.fake import FakeSerial, make_synth


def sent(fake):
    return fake.written


def test_ping_requires_a_synthnv():
    synth, _ = make_synth()
    assert "SynthNV" in synth.ping()
    synth, _ = make_synth(FakeSerial({"+": "Something else"}))
    with pytest.raises(ConnectionError):
        synth.ping()


def test_info_and_status():
    synth, _ = make_synth()
    info = synth.info()
    assert (info.serial, info.firmware, info.hardware) == ("1234", "fw 1.2", "hw 3")
    status = synth.status()
    assert status.pll_enabled and not status.muted and status.calibrated
    assert status.frequency_mhz == 1000.0 and status.power_dbm == -10.0


def test_calibration_flag_zero_is_false():
    synth, _ = make_synth(FakeSerial({"V": "0"}))
    assert synth.is_calibrated() is False


def test_set_frequency_sends_and_verifies():
    synth, fake = make_synth()
    synth.set_frequency(2870.0)
    assert sent(fake)[:2] == ["f2870.0000000", "f?"]


def test_ignored_setting_raises_command_error():
    synth, _ = make_synth(FakeSerial(silent={"f"}))
    with pytest.raises(CommandError, match="set_frequency"):
        synth.set_frequency(2870.0)


def test_verify_off_skips_readback():
    synth, fake = make_synth(FakeSerial(silent={"f"}), verify=False)
    synth.set_frequency(2870.0)
    assert sent(fake) == ["f2870.0000000"]


@pytest.mark.parametrize("freq", [12.4, 6400.1, float("nan")])
def test_frequency_out_of_range_sends_nothing(freq):
    synth, fake = make_synth()
    with pytest.raises(ValueError):
        synth.set_frequency(freq)
    assert sent(fake) == []


def test_power_range_and_limit():
    synth, fake = make_synth(max_power_dbm=-5.0)
    with pytest.raises(ValueError, match="max_power_dbm"):
        synth.set_power(0.0)
    with pytest.raises(ValueError):
        synth.set_power(-61.0)
    assert sent(fake) == []
    synth.set_power(-10.0)
    assert sent(fake)[0] == "W-10.000"


def test_invalid_limit_rejected():
    with pytest.raises(ValueError):
        make_synth(max_power_dbm=25.0)


def test_enable_disable_and_close_power_down():
    synth, fake = make_synth()
    synth.enable()
    assert fake.settings["E"] == "1"
    synth.close()
    assert fake.settings["E"] == "0"
    assert "g0" in sent(fake) and "c0" in sent(fake)  # sweep stopped first


def test_close_without_disable_leaves_output_alone():
    synth, fake = make_synth()
    synth.close(disable=False)
    assert sent(fake) == []


def test_mute_logic_is_inverted_on_the_wire():
    synth, fake = make_synth()
    synth.mute()
    assert fake.settings["h"] == "0"
    assert synth.is_muted()
    synth.unmute()
    assert fake.settings["h"] == "1"


def test_enum_settings_round_trip():
    synth, _ = make_synth()
    synth.set_temp_compensation(TempCompensation.NONE)
    assert synth.get_temp_compensation() is TempCompensation.NONE
    synth.detector.set_mode(DetectorMode.LOW_PASS)
    assert synth.detector.get_mode() is DetectorMode.LOW_PASS


def test_charge_pump_and_spacing_ranges():
    synth, _ = make_synth()
    for call, bad in [(synth.set_pll_charge_pump_current, 0), (synth.set_pll_charge_pump_current, 16),
                      (synth.set_channel_spacing, 0.05), (synth.set_channel_spacing, 2000),
                      (synth.reference.set_frequency, 5.0)]:
        with pytest.raises(ValueError):
            call(bad)


def test_raw_dac_refused_when_power_limited():
    synth, _ = make_synth(max_power_dbm=0.0)
    with pytest.raises(ValueError, match="bypasses"):
        synth.set_raw_dac(100)
    synth.set_raw_dac(100, force=True)


def test_detector_read():
    synth, _ = make_synth()
    assert synth.detector.read(5) == [-10.1] * 5


# -- sweep ----------------------------------------------------------------------


def test_sweep_configure_writes_all_parameters():
    synth, fake = make_synth()
    synth.sweep.configure(2800, 2900, step_mhz=1, step_time_ms=10, power_dbm=-10)
    for key, value in [("l", "2800.0000000"), ("u", "2900.0000000"), ("s", "1.0000000"),
                       ("t", "10.000"), ("[", "-10.000"), ("]", "-10.000"),
                       ("X", "0"), ("^", "1"), ("c", "0")]:
        assert fake.settings[key] == value, key


@pytest.mark.parametrize("kwargs", [
    dict(lower_mhz=2900, upper_mhz=2800, step_mhz=1, step_time_ms=10),
    dict(lower_mhz=2800, upper_mhz=2900, step_mhz=0, step_time_ms=10),
    dict(lower_mhz=2800, upper_mhz=2900, step_mhz=200, step_time_ms=10),
    dict(lower_mhz=2800, upper_mhz=2900, step_mhz=1, step_time_ms=0.01),
    dict(lower_mhz=2800, upper_mhz=2900, step_mhz=1, step_time_ms=10, power_dbm=-55),
    dict(lower_mhz=2800, upper_mhz=2900, step_mhz=1, step_time_ms=10, power_dbm=-10, power_low_dbm=-20),
])
def test_sweep_configure_rejects_bad_arguments_without_sending(kwargs):
    synth, fake = make_synth()
    with pytest.raises(ValueError):
        synth.sweep.configure(**kwargs)
    assert sent(fake) == []


def test_sweep_configure_respects_power_limit():
    synth, fake = make_synth(max_power_dbm=-20.0)
    with pytest.raises(ValueError, match="max_power_dbm"):
        synth.sweep.configure(2800, 2900, 1, 10, power_dbm=-10)
    assert sent(fake) == []


def sweep_fake(**settings):
    base = {"X": "0", "l": "2800", "u": "2900", "s": "1", "[": "-10", "]": "-10"}
    base.update(settings)
    return FakeSerial(base)


def test_sweep_start_checks_stored_state():
    synth, fake = make_synth(sweep_fake())
    synth.sweep.start()
    assert fake.written[-1] == "g1"


@pytest.mark.parametrize("settings", [{"l": "2900", "u": "2800"}, {"s": "0"}, {"s": "500"}])
def test_sweep_start_refuses_inconsistent_device_state(settings):
    synth, fake = make_synth(sweep_fake(**settings))
    with pytest.raises(ValueError):
        synth.sweep.start()
    assert "g1" not in fake.written


def test_sweep_start_refuses_power_above_limit():
    synth, fake = make_synth(sweep_fake(**{"]": "10"}), max_power_dbm=0.0)
    with pytest.raises(ValueError, match="max_power_dbm"):
        synth.sweep.start()
    assert "g1" not in fake.written


def test_sweep_stop_clears_continuous():
    synth, fake = make_synth()
    synth.sweep.stop()
    assert fake.written == ["g0", "c0"]


def test_sweep_results_parsing():
    synth, fake = make_synth(FakeSerial({"d": "1"}))
    fake.rx = b"1000.0\r\n-9.9\r\n1200.0\r\n-10.2\r\nEOM.\r\n"
    # read_until_eom does not send; the query for the display style drains pending
    # input, so queue the sweep output after it.
    orig_write = fake.write

    def write(data):
        orig_write(data)
        if data.decode() == "d?":
            fake.rx += b"1000.0\r\n-9.9\r\n1200.0\r\n-10.2\r\nEOM.\r\n"

    fake.write = write
    result = synth.sweep.read_results(timeout=0.2)
    assert result.frequency_mhz == [1000.0, 1200.0]
    assert result.power_dbm == [-9.9, -10.2]


def test_table_read_and_write_round_trip():
    synth, fake = make_synth(verify=False)
    synth.sweep.write_table([1000.0, 2000.0], [-10.0, -20.0], SweepDirection.LOWER_TO_UPPER)
    assert fake.written == ["L00f1000.000000L00a-10.00", "L01f2000.000000L01a-20.00",
                            "L2f0.0L2a0.0^0"]
    assert synth.sweep.read_table() == {"frequency": [1000.0, 2000.0], "amplitude": [-10.0, -20.0]}


def test_table_write_verifies_readback():
    synth, _ = make_synth()
    synth.sweep.write_table([1000.0, 2000.0], [-10.0, -20.0])  # fake table matches
    with pytest.raises(CommandError, match="read back"):
        synth.sweep.write_table([1000.0, 2500.0], [-10.0, -20.0])


@pytest.mark.parametrize("freqs, powers", [([1000.0], [-10.0, -20.0]), ([], []),
                                           ([5.0], [-10.0]), ([1000.0], [30.0]),
                                           ([1000.0] * 500, [-10.0] * 500)])
def test_table_write_rejects_bad_input(freqs, powers):
    synth, fake = make_synth()
    with pytest.raises(ValueError):
        synth.sweep.write_table(freqs, powers)
    assert fake.written == []
