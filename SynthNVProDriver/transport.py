"""Serial transport: port discovery, framing, and the command/reply cycle."""

from __future__ import annotations

import logging
import threading
import time

import serial
import serial.tools.list_ports

from SynthNVProDriver.protocol import (
    ResponseTimeout,
    SynthNVProNotFound,
    encode_command,
    is_eom,
)

logger = logging.getLogger("SynthNVProDriver")

MODEL_COMMAND = "+"
MODEL_SUBSTRING = "synthnv"
"""Lower-case text the ``+`` (model type) reply must contain to be a SynthNV Pro."""

PROBE_TIMEOUT_S = 0.5


def probe_port(port: str, baud_rate: int = 2_000_000) -> str | None:
    """Asks the device on ``port`` for its model (a read-only query).

    Returns the model string if it identifies as a SynthNV Pro, else None
    (including when the port cannot be opened, e.g. because it is in use).
    """
    try:
        with serial.Serial(port=port, baudrate=baud_rate, timeout=PROBE_TIMEOUT_S,
                           write_timeout=PROBE_TIMEOUT_S) as ser:
            ser.reset_input_buffer()
            ser.write(encode_command(MODEL_COMMAND))
            reply = ser.readline().decode("ascii", errors="replace").strip()
    except (serial.SerialException, OSError):
        return None
    return reply if MODEL_SUBSTRING in reply.lower() else None


def find_ports(hwid: str | None = None) -> list[str]:
    """Returns the device paths of all connected SynthNV Pros.

    Candidate ports are the USB serial ports (optionally only those whose
    ``hwid`` contains the string ``hwid``, e.g. ``"VID:PID=16D0:0AAD"``). Each
    candidate is probed with a harmless model query and kept only if it
    answers as a SynthNV Pro, so other serial devices are never mistaken for
    one (they do receive the single byte ``+``).
    """
    found = []
    for port in sorted(serial.tools.list_ports.comports(), key=lambda p: p.device):
        if "VID:PID" not in port.hwid.upper():
            continue  # not a USB serial device
        if hwid is not None and hwid.upper() not in port.hwid.upper():
            continue
        model = probe_port(port.device)
        if model is not None:
            logger.debug("found %r on %s", model, port.device)
            found.append(port.device)
    return found


def find_port(hwid: str | None = None) -> str:
    """Returns the device path of the only connected SynthNV Pro.

    Raises SynthNVProNotFound if there is none, and ValueError if there are
    several (pass ``port`` explicitly, or use :func:`find_ports`).
    """
    ports = find_ports(hwid)
    if not ports:
        raise SynthNVProNotFound("no SynthNV Pro found on any serial port")
    if len(ports) > 1:
        raise ValueError(f"several SynthNV Pros found ({', '.join(ports)}); choose a port")
    return ports[0]


class Transport:
    """A thread-safe, synchronous command/reply channel to the device.

    One command is in flight at a time (enforced with a lock). Anything the
    device sends that is not the reply to the current query (echoes, replies to
    earlier timed-out queries) is discarded before each new command, so a late
    reply can never be mistaken for the answer to a later query.
    """

    DEFAULT_TIMEOUT_S = 1.0

    def __init__(self, port: str | None = None, baud_rate: int = 2_000_000,
                 hwid: str | None = None):
        self.port = port if port is not None else find_port(hwid)
        self._hwid = hwid
        # USB CDC ignores the baud rate, but pyserial wants one.
        self._serial = serial.Serial(port=self.port, baudrate=baud_rate, timeout=0.05,
                                     write_timeout=1.0)
        self._lock = threading.RLock()
        self._rx = bytearray()
        logger.debug("connected to %s", self.port)

    def close(self) -> None:
        self._serial.close()

    def reconnect(self, port: str | None = None) -> None:
        """Reopens the connection, rediscovering the port if none is given.

        Useful when the device re-enumerates and reappears on a different
        path. Device state is unknown afterwards.
        """
        with self._lock:
            try:
                self._serial.close()
            except Exception:
                pass
            self.port = port if port is not None else find_port(self._hwid)
            self._serial = serial.Serial(port=self.port, baudrate=self._serial.baudrate,
                                         timeout=0.05, write_timeout=1.0)
            self._rx.clear()
            logger.info("reconnected on %s", self.port)

    def __enter__(self) -> "Transport":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def send(self, command: str, arg=None, *, decimals: int = 7) -> None:
        """Sends a command that has no reply (a setting)."""
        with self._lock:
            self._drain()
            self._write(encode_command(command, arg, decimals=decimals))

    def send_raw(self, text: str) -> None:
        """Sends pre-formatted command text that has no reply."""
        with self._lock:
            self._drain()
            self._write(text.encode("ascii"))

    def query(self, command: str, *, timeout: float | None = None) -> str:
        """Queries a setting (``<command>?``) and returns the one-line reply."""
        return self._exchange(encode_command(command, query=True), command, timeout)[0]

    def request(self, command: str, arg=None, *, timeout: float | None = None,
                decimals: int = 7) -> str:
        """Sends a command that is answered with one line (e.g. ``+``, ``V``)."""
        return self._exchange(encode_command(command, arg, decimals=decimals), command, timeout)[0]

    def request_until_eom(self, command: str, arg=None, *, timeout: float | None = None,
                          decimals: int = 7, query: bool = False) -> list[str]:
        """Sends a command whose reply is any number of lines ended by ``EOM.``;
        returns the lines before the marker."""
        data = encode_command(command, arg, query=query, decimals=decimals)
        return self._exchange(data, command, timeout, until_eom=True)

    def request_for(self, command: str, duration: float) -> list[str]:
        """Sends a command and returns every line that arrives within
        ``duration`` seconds (for replies with no end marker, e.g. help)."""
        with self._lock:
            self._drain()
            self._write(encode_command(command))
            deadline = time.monotonic() + duration
            lines = []
            while (line := self._read_line(deadline)) is not None:
                if line:
                    lines.append(line)
            return lines

    def read_until_eom(self, *, timeout: float | None = None) -> list[str]:
        """Collects lines already being produced by the device (e.g. a running
        sweep with display on) up to the ``EOM.`` marker, without sending."""
        timeout = self.DEFAULT_TIMEOUT_S if timeout is None else timeout
        with self._lock:
            return self._collect("(unsolicited)", time.monotonic() + timeout, True)

    # -- internals ----------------------------------------------------------

    def _write(self, data: bytes) -> None:
        logger.debug("-> %r", data)
        try:
            self._serial.write(data)
        except serial.SerialTimeoutException:
            raise ResponseTimeout("timed out writing to the device") from None

    def _exchange(self, data: bytes, command: str, timeout: float | None,
                  until_eom: bool = False) -> list[str]:
        timeout = self.DEFAULT_TIMEOUT_S if timeout is None else timeout
        with self._lock:
            self._drain()
            self._write(data)
            return self._collect(command, time.monotonic() + timeout, until_eom, timeout)

    def _collect(self, command: str, deadline: float, until_eom: bool,
                 timeout: float | None = None) -> list[str]:
        lines: list[str] = []
        while True:
            line = self._read_line(deadline)
            if line is None:
                what = "EOM" if until_eom else "reply"
                raise ResponseTimeout(
                    f"no {what} to '{command}' within {timeout if timeout is not None else 0:.1f} s "
                    f"(the device may still have executed it)"
                )
            logger.debug("<- %r", line)
            if not line:
                continue
            if not until_eom:
                return [line]
            if is_eom(line):
                return lines
            lines.append(line)

    def _pop_line(self) -> str | None:
        newline = self._rx.find(b"\n")
        if newline == -1:
            return None
        raw = self._rx[:newline]
        del self._rx[: newline + 1]
        return raw.rstrip(b"\r").decode("ascii", errors="replace").strip()

    def _read_line(self, deadline: float) -> str | None:
        """Returns the next complete line, or None once ``deadline`` passes."""
        while True:
            line = self._pop_line()
            if line is not None:
                return line
            if time.monotonic() >= deadline:
                return None
            waiting = self._serial.in_waiting
            self._rx.extend(self._serial.read(waiting if waiting > 0 else 1))

    def _drain(self) -> None:
        """Discards pending input without blocking."""
        waiting = self._serial.in_waiting
        if waiting:
            self._rx.extend(self._serial.read(waiting))
        for line in self._rx.decode("ascii", errors="replace").splitlines():
            if line.strip():
                logger.debug("discarding unsolicited input: %r", line)
        self._rx.clear()
