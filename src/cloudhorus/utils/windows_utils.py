"""Windows encoding and console utilities."""

import os
import re
import sys
from typing import Any, TextIO


def setup_windows_console() -> None:
    """Setup Windows console for UTF-8 encoding."""
    if sys.platform.startswith("win"):
        try:
            # Set console code page to UTF-8
            import ctypes

            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleCP(65001)
            kernel32.SetConsoleOutputCP(65001)
        except Exception:
            pass

        # Reconfigure stdout and stderr for UTF-8
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            # Python < 3.7
            pass


def safe_print(*args, **kwargs) -> None:
    """Print with fallback encoding for Windows compatibility.

    Args:
        *args: Arguments to print
        **kwargs: Keyword arguments for print function
    """
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        # Fallback: remove emojis and try again
        safe_args = [remove_emojis_from_text(str(arg)) for arg in args]
        try:
            print(*safe_args, **kwargs)
        except Exception:
            # Last resort: ASCII only
            ascii_args = [str(arg).encode("ascii", "ignore").decode("ascii") for arg in args]
            print(*ascii_args, **kwargs)


def remove_emojis_from_text(text: str) -> str:
    """Remove emojis and special Unicode characters from text.

    Args:
        text: Input text possibly containing emojis

    Returns:
        Text with emojis removed
    """
    # Pattern to match emojis and special Unicode characters
    emoji_pattern = re.compile(
        "["
        "\U0001f600-\U0001f64f"  # emoticons
        "\U0001f300-\U0001f5ff"  # symbols & pictographs
        "\U0001f680-\U0001f6ff"  # transport & map symbols
        "\U0001f1e0-\U0001f1ff"  # flags
        "\U00002702-\U000027b0"
        "\U000024c2-\U0001f251"
        "]+",
        flags=re.UNICODE,
    )
    return emoji_pattern.sub(r"", text)


def strip_ansi_codes(text: str) -> str:
    """Remove ANSI color codes from text.

    Args:
        text: Text possibly containing ANSI codes

    Returns:
        Text without ANSI codes
    """
    ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    return ansi_escape.sub("", text)


def safe_file_operation(filename: str, mode: str = "r", encoding: str = "utf-8", errors: str = "replace") -> TextIO:
    """Open a file with safe encoding for Windows.

    Args:
        filename: Path to the file
        mode: File open mode
        encoding: File encoding
        errors: Error handling strategy

    Returns:
        File object
    """
    import typing

    return typing.cast(TextIO, open(filename, mode=mode, encoding=encoding, errors=errors))
