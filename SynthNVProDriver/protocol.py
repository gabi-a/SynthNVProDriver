"""Wire protocol encoding/decoding (pure functions; no serial I/O here).

The SynthNV Pro speaks a terse ASCII protocol over USB serial. A command is a
single letter followed by an optional value; appending ``?`` queries the
setting instead of changing it::

    f1000.0000000     set the frequency to 1000 MHz
    f?                query the frequency (reply: one line, e.g. ``1000.0000000``)
    w5                measure RFin power 5 times (reply: 5 lines, then ``EOM.``)

Setting commands produce no reply, so a setting can only be confirmed by
querying it back (see :mod:`SynthNVProDriver.synth`).
"""

from __future__ import annotations

EOM = "EOM"
"""Prefix of the line that ends multi-line replies (the device sends ``EOM.``)."""

QUERY_CHAR = "?"


class SynthNVProError(Exception):
    """Base class for all errors raised by this package."""


class ProtocolError(SynthNVProError):
    """The device sent something that cannot be parsed as the expected reply."""


class ResponseTimeout(SynthNVProError):
    """No reply arrived in time.

    The device may still have executed the command; callers must not blindly
    retry commands with side effects.
    """


class CommandError(SynthNVProError):
    """The device accepted a command but its state is not what was asked for.

    Raised when read-back verification of a setting fails.
    """

    def __init__(self, command: str, message: str):
        super().__init__(f"{command}: {message}")
        self.command = command
        self.message = message


class SynthNVProNotFound(ProtocolError):
    """No serial port with a SynthNV Pro on the other end was found."""


def format_arg(value: bool | int | float | str, decimals: int = 7) -> str:
    """Formats one command argument. Floats are fixed-point with ``decimals``
    places (the device has 0.1 Hz frequency and 0.001 dB power resolution)."""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.{decimals}f}"
    if isinstance(value, str):
        return value
    raise TypeError(f"unsupported argument type {type(value).__name__}: {value!r}")


def encode_command(command: str, arg: bool | int | float | str | None = None, *,
                   query: bool = False, decimals: int = 7) -> bytes:
    """Encodes a command, e.g. ``encode_command("f", 1000.0)`` -> ``b"f1000.0000000"``.

    The device expects no line terminator.
    """
    if not command:
        raise ValueError("empty command")
    if query and arg is not None:
        raise ValueError("a query takes no argument")
    text = command
    if arg is not None:
        text += format_arg(arg, decimals)
    if query:
        text += QUERY_CHAR
    return text.encode("ascii")


def parse_float(line: str) -> float:
    try:
        return float(line)
    except ValueError:
        raise ProtocolError(f"expected a number, got {line!r}") from None


def parse_int(line: str) -> int:
    try:
        return int(line)
    except ValueError:
        raise ProtocolError(f"expected an integer, got {line!r}") from None


def parse_bool(line: str) -> bool:
    """Parses a ``0``/``1`` flag. (``bool("0")`` is True, so never use that.)"""
    if line not in ("0", "1"):
        raise ProtocolError(f"expected 0 or 1, got {line!r}")
    return line == "1"


def is_eom(line: str) -> bool:
    return line.startswith(EOM)
