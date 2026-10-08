import pytest

from SynthNVProDriver.protocol import (
    ProtocolError,
    encode_command,
    is_eom,
    parse_bool,
    parse_float,
    parse_int,
)


def test_encode_set_and_query():
    assert encode_command("f", 1000.0) == b"f1000.0000000"
    assert encode_command("W", -10.0, decimals=3) == b"W-10.000"
    assert encode_command("f", query=True) == b"f?"
    assert encode_command("E", True) == b"E1"
    assert encode_command("Z", 3) == b"Z3"
    assert encode_command("g") == b"g"


def test_query_with_argument_rejected():
    with pytest.raises(ValueError):
        encode_command("f", 1.0, query=True)


def test_parse_bool_is_not_python_truthiness():
    assert parse_bool("0") is False
    assert parse_bool("1") is True
    with pytest.raises(ProtocolError):
        parse_bool("yes")


def test_parse_numbers_reject_garbage():
    assert parse_float("-10.5") == -10.5
    assert parse_int("7") == 7
    with pytest.raises(ProtocolError):
        parse_float("abc")
    with pytest.raises(ProtocolError):
        parse_int("1.5")


def test_eom():
    assert is_eom("EOM.")
    assert not is_eom("-10.1")
