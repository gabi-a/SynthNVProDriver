import logging
from typing import Dict, List, Optional, Tuple, Union

LOGGER = logging.getLogger(__name__)


class NVPCommand:
    SET_FREQUENCY_MHZ = "f"
    SET_RF_POWER_dBm  = "W"
    QUERY_CAL_SUCCESS = "V"
    SET_TEMP_COMPENSATION = "Z"
    READ_POWER_DETECTOR = "w"
    SET_RF_DETECTOR_MODE = "&"
    SET_RAW_DAC = "a"
    SET_PHASE_STEP = "~"
    SET_RF_MUTE = "h"
    SET_PLL_CHARGE_PUMP_CURRENT = "U"
    SET_REFERENCE_DOUBLER = "D"
    SET_CHANNEL_SPACING = "i"
    SAVE_SETTINGS_TO_EEPROM = "e"
    SET_REFERENCE_SOURCE = "x"
    SET_REFERENCE_FREQUENCY = "*"
    SET_TRIGGER_CONNECTOR_FUNCTION = "y"
    SET_LOWER_FREQ_LINEAR_SWEEP = "l"
    SET_UPPER_FREQ_LINEAR_SWEEP = "u"
    SET_STEP_SIZE_FREQ_LINEAR_SWEEP = "s"
    SET_TIME_LINEAR_SWEEP = "t"
    SET_LINEAR_SWEEP_POWER_LOW = "["
    SET_LINEAR_SWEEP_POWER_HIGH = "]"
    SET_SWEEP_DIRECTION = "^"
    SET_SWEEP_TYPE = "X"
    SET_READ_WHILE_SWEEP = "r"
    SET_SWEEP_DISPLAY_STYLE = "d"
    RUN_SWEEP = "g"
    SET_SWEEP_CONTINUOUS = "c"
    QUERY_INTERNAL_TEMPERATURE = "z"
    SHOW_VERSION = "v"
    SHOW_MODEL_TYPE = "+"
    SHOW_SERIAL_NUMBER = "-"

    PLL_ENABLE = "E"

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