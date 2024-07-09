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
            # TODO SyncBoard does not seem to respond that fast
            response = self.connection.read_response(wait_time=wait_time)
        if 'error' in response:
            LOGGER.error(response.rstrip('#%').lstrip('$error/'))
        return response

    def set_rf_frequency(self, frequency_mhz: float):
        command = Command.format(Command.SET_FREQUENCY_MHZ, arg=frequency_mhz)
        self.send_command(command)

    def get_rf_frequency(self) -> float:
        command = Command.format(Command.SET_FREQUENCY_MHZ, query=True)
        response = self.send_command(command)
        return Command.parse_reply(response)
    
    def set_rf_power(self, power_dbm: float):
        command = Command.format(Command.SET_RF_POWER_dBm, arg=float(power_dbm), sigfigs=3)
        self.send_command(command)

    def get_rf_power(self) -> float:
        command = Command.format(Command.SET_RF_POWER_dBm, query=True)
        response = self.send_command(command)
        return Command.parse_reply(response)
    
    def query_calibration_succesful(self) -> bool:
        command = Command.format(Command.QUERY_CAL_SUCCESS)
        response = self.send_command(command)
        return Command.parse_reply(response)
    
    def set_temp_compensation(self, method: TEMP_COMPENSATION)