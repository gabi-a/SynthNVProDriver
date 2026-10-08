"""A scripted fake serial port that behaves like a SynthNV Pro: settings are
stored, queries (``<cmd>?``) answer with the stored value."""

import re
import threading

from SynthNVProDriver.synth import SynthNVPro
from SynthNVProDriver.transport import Transport


class FakeSerial:
    def __init__(self, settings=None, silent=()):
        self.settings = {"+": "SynthNV PRO", "-": "1234", "V": "1", "E": "1", "h": "1",
                         "f": "1000.0000000", "W": "-10.000"}
        self.settings.update(settings or {})
        self.silent = set(silent)  # commands whose settings are ignored
        self.written = []
        self.rx = b""
        self.baudrate = 2_000_000

    def write(self, data):
        text = data.decode()
        self.written.append(text)
        if text == "?":
            self.rx += (b"f) RF Frequency Now (MHz) 1000.00000000\r\nE) PLL Chip En On(1) or Off(0) 1\r\n"
                        b"e) Write all settings to eeprom \r\nCal datecode YYWW 2635\r\nEOM.\r\n")
        elif text == "w5":
            self.rx += b"".join(b"-10.1\r\n" for _ in range(5)) + b"EOM.\r\n"
        elif text == "L?":
            self.rx += b"L00f1000.000000a-10.00\r\nL01f2000.000000a-20.00\r\nEOM.\r\n"
        elif text.endswith("?"):
            key = text[:-1]
            self.rx += f"{self.settings[key]}\r\n".encode()
        elif text in ("+", "-", "V"):
            self.rx += f"{self.settings[text]}\r\n".encode()
        elif text.startswith("v"):
            self.rx += (b"fw 1.2\r\n" if text == "v0" else b"hw 3\r\n")
        else:
            match = re.fullmatch(r"([A-Za-z&~*\[\]^])(.*)", text)
            if match and match.group(1) not in self.silent:
                self.settings[match.group(1)] = match.group(2)

    @property
    def in_waiting(self):
        return len(self.rx)

    def read(self, n):
        chunk, self.rx = self.rx[:n], self.rx[n:]
        return chunk

    def close(self):
        pass


def make_transport(fake=None):
    transport = Transport.__new__(Transport)
    transport._serial = fake or FakeSerial()
    transport._lock = threading.RLock()
    transport._rx = bytearray()
    transport._hwid = None
    transport.port = "fake"
    return transport


def make_synth(fake=None, **kwargs):
    fake = fake or FakeSerial()
    return SynthNVPro(make_transport(fake), **kwargs), fake
