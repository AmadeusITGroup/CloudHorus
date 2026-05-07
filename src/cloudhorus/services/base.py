"""Base service class for all CloudHorus services."""

import logging
from abc import ABC, abstractmethod
from typing import Optional

from ..utils.logger import get_logger


class BaseService(ABC):
    """Abstract base class for all services in CloudHorus.

    Provides common functionality like logging and configuration access.
    """

    def __init__(self):
        """Initialize the base service."""
        self._logger: Optional[logging.Logger] = None

    @property
    def logger(self) -> logging.Logger:
        """Get the logger instance."""
        if self._logger is None:
            self._logger = get_logger()
        return self._logger

    @abstractmethod
    def validate(self) -> bool:
        """Validate service configuration and dependencies.

        Returns:
            True if service is properly configured, False otherwise
        """
        pass
