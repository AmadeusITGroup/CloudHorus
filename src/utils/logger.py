import inspect
import logging
import os
import sys


class Colors:
    """ANSI color codes for terminal output"""

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


class SingletonLogger:
    """
    Singleton class for a colored logger
    """

    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls)
            cls._instance._initialize(*args, **kwargs)
        return cls._instance

    def _initialize(self, level=logging.INFO) -> None:
        """
        Initialize the logger
        :param level: The logging level to set. Defaults to INFO. Possible values: DEBUG, INFO, WARNING, ERROR
        :type level: int
        """
        self.logger = logging.getLogger("SingletonLogger")
        self.logger.setLevel(level)
        self.logger.propagate = False

        if not self.logger.handlers:
            formatter = self._get_colored_formatter()

            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)

    def _get_colored_formatter(self) -> logging.Formatter:
        """
        Get a colored formatter for the logger
        :return: The colored formatter
        :rtype: logging.Formatter
        """

        class ColoredFormatter(logging.Formatter):
            """Colored formatter for the logger"""

            def format(self, record) -> str:
                """
                Format the log record
                :param record: The log record
                :type record: logging.LogRecord
                :return: The formatted log record
                :rtype: str
                """
                frame = inspect.stack()[8]  # Adjust index to reach the caller
                module = inspect.getmodule(frame[0])
                module_name = module.__name__ if module else ""
                class_name = ""
                if "self" in frame[0].f_locals:
                    class_name = frame[0].f_locals["self"].__class__.__name__
                function_name = frame[3]
                caller_name = f"{module_name}.{class_name}.{function_name}".strip(".")

                color = Colors.WHITE  # default to white
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
        """
        Set the logging level of the logger
        :param level: The logging level to set
        :type level: int
        """
        self.logger.setLevel(level)

    def get_logger(self) -> logging.Logger:
        """
        Returns the logger instance
        :return: The logger instance
        :rtype: logging.Logger
        """
        return self.logger
