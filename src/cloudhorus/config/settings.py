"""Application configuration and settings management."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class Settings:
    """Application settings with environment variable support."""

    # Logging
    log_level: str = "INFO"
    use_colors: bool = True

    # Output
    output_format: str = "png"
    output_directory: Path = field(default_factory=lambda: Path.cwd())
    output_filename_template: str = "azure_resources_{timestamp}"

    # Azure CLI
    az_command: str = "az"
    azure_timeout: int = 300

    # Graphviz
    graphviz_engine: str = "dot"
    graphviz_dpi: int = 300

    # Icons
    icons_directory: Path = field(default_factory=lambda: Path(__file__).parent.parent.parent.parent / "icons")
    default_icon: str = "default.png"

    # Performance
    enable_caching: bool = True
    parallel_processing: bool = True
    max_workers: int = 4

    # Windows compatibility
    force_ascii: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        """Create settings from environment variables."""
        return cls(
            log_level=os.getenv("CLOUDHORUS_LOG_LEVEL", "INFO"),
            use_colors=os.getenv("CLOUDHORUS_USE_COLORS", "true").lower() == "true",
            output_format=os.getenv("CLOUDHORUS_OUTPUT_FORMAT", "png"),
            output_directory=Path(os.getenv("CLOUDHORUS_OUTPUT_DIR", os.getcwd())),
            az_command=os.getenv("CLOUDHORUS_AZ_COMMAND", "az"),
            azure_timeout=int(os.getenv("CLOUDHORUS_AZURE_TIMEOUT", "300")),
            enable_caching=os.getenv("CLOUDHORUS_ENABLE_CACHING", "true").lower() == "true",
            force_ascii=os.getenv("CLOUDHORUS_FORCE_ASCII", "false").lower() == "true",
        )

    def validate(self) -> None:
        """Validate settings."""
        if not self.output_directory.exists():
            self.output_directory.mkdir(parents=True, exist_ok=True)

        if not self.icons_directory.exists():
            raise ValueError(f"Icons directory not found: {self.icons_directory}")

    @property
    def output_path(self) -> Path:
        """Get the full output path with timestamp."""
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = self.output_filename_template.format(timestamp=timestamp)
        return self.output_directory / f"{filename}.{self.output_format}"


# Global settings instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get or create the global settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings


def set_settings(settings: Settings) -> None:
    """Set the global settings instance."""
    global _settings
    _settings = settings
