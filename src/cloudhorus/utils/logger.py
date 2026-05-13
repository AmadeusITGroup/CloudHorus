"""Logging utilities with color support."""

import inspect
import logging
import os
import sys
from typing import Optional


class Colors:
    """ANSI color codes for terminal output."""

    # Only use colors on non-Windows or if explicitly enabled
    _USE_COLORS = not (os.name == "nt" or sys.platform.startswith("win"))

    RED = "\033[91m" if _USE_COLORS else ""
    GREEN = "\033[92m" if _USE_COLORS else ""
    YELLOW = "\033[93m" if _USE_COLORS else ""
    BLUE = "\033[94m" if _USE_COLORS else ""
    PURPLE = "\033[95m" if _USE_COLORS else ""
    CYAN = "\033[96m" if _USE_COLORS else ""
    WHITE = "\033[97m" if _USE_COLORS else ""
    RESET = "\033[0m" if _USE_COLORS else ""


class CloudHorusLogger:
    """Logger for CloudHorus with colored output and singleton pattern."""

    _instance: Optional["CloudHorusLogger"] = None
    _logger: Optional[logging.Logger] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, level: int = logging.INFO):
        """Initialize the logger."""
        if self._logger is None:
            self._setup_logger(level)

    def _setup_logger(self, level: int) -> None:
        """Setup the logger with colored formatter."""
        self._logger = logging.getLogger("CloudHorus")
        self._logger.setLevel(level)
        self._logger.propagate = False

        if not self._logger.handlers:
            formatter = self._create_colored_formatter()
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            self._logger.addHandler(console_handler)

    def _create_colored_formatter(self) -> logging.Formatter:
        """Create a colored formatter for the logger."""

        class ColoredFormatter(logging.Formatter):
            """Colored formatter for log records."""

            def format(self, record: logging.LogRecord) -> str:
                """Format the log record with colors."""
                try:
                    frame = inspect.stack()[8]
                    module = inspect.getmodule(frame[0])
                    module_name = module.__name__ if module else ""
                    class_name = ""
                    if "self" in frame[0].f_locals:
                        class_name = frame[0].f_locals["self"].__class__.__name__
                    function_name = frame[3]
                    caller_name = f"{module_name}.{class_name}.{function_name}".strip(".")
                except:
                    caller_name = "unknown"

                color = Colors.WHITE
                if record.levelno == logging.DEBUG:
                    color = Colors.BLUE
                elif record.levelno == logging.INFO:
                    color = Colors.GREEN
                elif record.levelno == logging.WARNING:
                    color = Colors.YELLOW
                elif record.levelno == logging.ERROR:
                    color = Colors.RED
                elif record.levelno == logging.CRITICAL:
                    color = Colors.PURPLE

                record.msg = f"{color}{record.msg}{Colors.RESET}"
                record.name = caller_name
                return super().format(record)

        return ColoredFormatter(
            "%(asctime)s - %(levelname)s - %(message)s (%(filename)s:%(lineno)d)",
            "%Y-%m-%d %H:%M:%S",
        )

    def set_level(self, level: int) -> None:
        """Set the logging level."""
        if self._logger:
            self._logger.setLevel(level)

    def get_logger(self) -> logging.Logger:
        """Get the logger instance."""
        if self._logger is None:
            self._setup_logger(logging.INFO)
        assert self._logger is not None
        return self._logger


# Singleton instance for backward compatibility
class SingletonLogger(CloudHorusLogger):
    """Backward compatibility alias."""

    pass


def get_logger() -> logging.Logger:
    """Get the CloudHorus logger instance."""
    return CloudHorusLogger().get_logger()
