import logging
from typing import Dict, List, Optional, Tuple, Union

LOGGER = logging.getLogger(__name__)


class Command:
    SET_FREQUENCY_MHZ = "f"
    SET_RF_POWER_dBm  = "W"
    QUERY_CAL_SUCCESS = "V"
    SET_TEMP_COMPENSATION = "Z"

    _QUERY_CHAR = "?"
    _NUM_SIG_FIG_FLOAT = 7

    @classmethod
    def format(
        cls,
        command: str,
        query: bool = False,
        arg: Union[str, float, None] = None,
        sigfigs: int = _NUM_SIG_FIG_FLOAT,
    ) -> str:
        args_str = str(cls.format_float(arg, sigfigs) if isinstance(arg, float) else (arg if arg is not None else ""))
        command_formatted = f"{command}{args_str}" if not query else f"{command}{args_str}{cls._QUERY_CHAR}"
        LOGGER.debug(f"Formatted command: {command_formatted}")
        return command_formatted

    @classmethod
    def format_float(
            cls,
            val: float,
            sigfigs: int,
    ) -> str:
        # TODO warning about precision
        return f"{val:.{sigfigs}f}"


    @classmethod
    def parse_reply(
            cls,
            reply: str,
    ) -> str: # Tuple[str, List[Union[str, float]]]:

        # reply = reply.strip()
        # if not reply.startswith(cls._START_CHAR) or not reply.endswith(cls._TRANS_STOP_CHAR):
        #     raise ValueError("Invalid reply: " + reply)

        # parts = reply.lstrip(cls._START_CHAR).rstrip(cls._TRANS_STOP_CHAR).rstrip(cls._END_CHAR).split(cls._DELIM_CHAR)
        # return parts[0], [cls.convert_float(val) for val in parts[1:]]
        return reply

    @staticmethod
    def convert_float(val: str) -> Union[str, float]:
        try:
            return float(val)
        except ValueError:
            return val


