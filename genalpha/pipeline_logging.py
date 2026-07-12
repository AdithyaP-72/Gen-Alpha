"""
Shared logging for the pipeline: console + pipeline_progress.log.

Replaces the old builtins.print monkey-patch, which teed every print in the
whole process into the log file and double-wrote lines that were also logged
explicitly.
"""

import logging
import sys

from genalpha.config import PIPELINE_LOG as LOG_FILE
_LOGGER_NAME = "genalpha"


def get_logger():
    logger = logging.getLogger(_LOGGER_NAME)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    logger.propagate = False

    fmt = logging.Formatter("[%(asctime)s] %(message)s", datefmt="%H:%M:%S")

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    logger.addHandler(console)

    try:
        file_handler = logging.FileHandler(LOG_FILE)
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    except OSError:
        pass  # log file unavailable — console only

    return logger


def log(msg=""):
    get_logger().info(msg)
