import pytest

from SynthNVProDriver.protocol import ResponseTimeout
from tests.fake import FakeSerial, make_transport


def test_query_returns_one_line():
    t = make_transport()
    assert t.query("f") == "1000.0000000"
    assert t._serial.written == ["f?"]


def test_request_until_eom_returns_lines_before_marker():
    t = make_transport()
    assert t.request_until_eom("w", 5, timeout=0.2) == ["-10.1"] * 5


def test_stale_input_is_discarded_before_a_query():
    fake = FakeSerial()
    fake.rx = b"stale echo\r\n"
    t = make_transport(fake)
    assert t.query("f") == "1000.0000000"


def test_timeout_raises():
    fake = FakeSerial()
    t = make_transport(fake)
    fake.settings["f"] = ""  # device answers with a blank line only
    with pytest.raises(ResponseTimeout, match="may still have executed"):
        t.query("f", timeout=0.05)


def test_missing_eom_times_out_instead_of_hanging():
    fake = FakeSerial()
    t = make_transport(fake)
    with pytest.raises(ResponseTimeout):
        t.request_until_eom("L", query=False, timeout=0.05)  # fake sends nothing for "L"


def test_request_for_collects_lines():
    t = make_transport()
    assert t.request_for("?", 0.1) == ["help line 1", "help line 2"]
