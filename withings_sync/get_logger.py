"""Created on 2020-05-06 20:49.

@author: Lev Velykoivanenko (velykoivanenko.lev@gmail.com)
"""

from __future__ import annotations

__all__ = ["get_logger"]
__license__ = "GPLv3"

import verboselogs


def get_logger(name: str) -> verboselogs.VerboseLogger:
    """Creates and returns a verbose logger with colored output.

    :param name: Name of the logger.
    :return: a VerboseLogger instance that can be used as a regular logger.
    """
    logger = verboselogs.VerboseLogger(name)
    logger.spam("Finished logging init")
    return logger
