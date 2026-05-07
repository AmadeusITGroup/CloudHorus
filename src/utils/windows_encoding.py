# -*- coding: utf-8 -*-
"""
Windows Encoding Fix Utility

This module provides utilities to handle Windows console encoding issues
and prevent 'charmap' codec errors when dealing with emoji or special characters.
"""

import codecs
import locale
import os
import sys
from contextlib import contextmanager


def setup_windows_console():
    """
    Setup Windows console for proper UTF-8 handling.

    This function:
    1. Sets the console to UTF-8 mode on Windows 10+
    2. Configures environment variables for Python I/O encoding
    3. Provides fallback handling for older Windows versions
    """
    try:
        if os.name == "nt":  # Windows
            # Try to set console to UTF-8 mode (Windows 10 version 1903+)
            try:
                # Enable UTF-8 mode in console
                os.system("chcp 65001 >nul 2>&1")
            except Exception:
                pass

            # Set environment variables for Python I/O encoding
            os.environ["PYTHONIOENCODING"] = "utf-8:replace"
            os.environ["PYTHONLEGACYWINDOWSSTDIO"] = "0"

            # Configure stdout/stderr with UTF-8 encoding and error handling
            try:
                if hasattr(sys.stdout, "reconfigure"):
                    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
                    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                # Fallback for older Python versions
                sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, errors="replace")
                sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, errors="replace")

    except Exception as e:
        # Silent fallback - don't break the application
        pass


def safe_print(*args, **kwargs):
    """
    Safe print function that handles encoding errors gracefully.

    Args:
        *args: Arguments to print
        **kwargs: Keyword arguments for print function

    This function ensures that emoji and special characters are handled
    without causing 'charmap' codec errors on Windows systems.
    """
    try:
        # First try normal print
        print(*args, **kwargs)
    except UnicodeEncodeError:
        try:
            # Convert args to safe ASCII representation
            safe_args = []
            for arg in args:
                if isinstance(arg, str):
                    # Replace problematic characters with safe alternatives
                    safe_arg = arg.encode("ascii", errors="replace").decode("ascii")
                    safe_args.append(safe_arg)
                else:
                    safe_args.append(str(arg))
            print(*safe_args, **kwargs)
        except Exception:
            # Last resort - print a generic message
            print("Output contains characters that cannot be displayed in this console", **kwargs)


@contextmanager
def safe_file_operation(filename, mode="r", encoding="utf-8", errors="replace"):
    """
    Context manager for safe file operations with proper encoding.

    Args:
        filename: Path to the file
        mode: File mode ('r', 'w', 'a', etc.)
        encoding: Character encoding (default: 'utf-8')
        errors: Error handling strategy (default: 'replace')

    Usage:
        with safe_file_operation('file.txt', 'w') as f:
            f.write("Content with special characters")
    """
    try:
        if "b" in mode:
            # Binary mode - no encoding needed
            file_obj = open(filename, mode)
        else:
            # Text mode - use UTF-8 with error handling
            file_obj = open(filename, mode, encoding=encoding, errors=errors)

        try:
            yield file_obj
        finally:
            file_obj.close()

    except Exception as e:
        # Fallback to basic file operations
        try:
            file_obj = open(filename, mode.replace("t", ""))
            try:
                yield file_obj
            finally:
                file_obj.close()
        except Exception:
            # Create a dummy file object that does nothing
            class DummyFile:
                def write(self, *args):
                    pass

                def read(self, *args):
                    return ""

                def close(self):
                    pass

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    pass

            yield DummyFile()


def remove_emojis_from_text(text):
    """
    Remove emoji and special Unicode characters from text.

    Args:
        text: Input text string

    Returns:
        str: Text with emojis removed and replaced with safe alternatives
    """
    if not isinstance(text, str):
        return str(text)

    # First remove ANSI color codes if on Windows
    if os.name == "nt":
        import re

        ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
        text = ansi_escape.sub("", text)

    # Common emoji replacements for CloudHorus
    replacements = {
        "🦅": "CloudHorus",
        "👁️": "Eye",
        "⚡": "Lightning",
        "☁️": "Cloud",
        "📜": "Template",
        "🛡️": "Shield",
        "🔧": "Tool",
        "🚀": "Rocket",
        "✅": "[OK]",
        "❌": "[ERROR]",
        "⚠️": "[WARNING]",
        "⭐": "Star",
        "💡": "Idea",
        "🎯": "Target",
        "📊": "Chart",
        "🔍": "Search",
        "🌟": "Star",
        "💾": "Save",
        "🖼️": "Image",
        "🖥️": "Desktop",
        "💻": "Computer",
        "📱": "Mobile",
        "🔐": "Lock",
        "🏛️": "Building",
        "👑": "Crown",
        "👨‍💻": "Developer",
        "🌐": "Globe",
        "📚": "Books",
        "✈️": "Plane",
        "🌍": "World",
        "🔄": "Refresh",
        "⏳": "Loading",
    }

    # Replace known emojis
    safe_text = text
    for emoji, replacement in replacements.items():
        safe_text = safe_text.replace(emoji, replacement)

    # Remove any remaining emoji-like characters (Unicode ranges for emojis)
    import re

    emoji_pattern = re.compile(
        "["
        "\U0001f600-\U0001f64f"  # emoticons
        "\U0001f300-\U0001f5ff"  # symbols & pictographs
        "\U0001f680-\U0001f6ff"  # transport & map symbols
        "\U0001f1e0-\U0001f1ff"  # flags (iOS)
        "\U00002700-\U000027bf"  # dingbats
        "\U0001f926-\U0001f937"  # gestures
        "\U00010000-\U0010ffff"  # supplementary multilingual plane
        "\u2640-\u2642"  # gender symbols
        "\u2600-\u2b55"  # misc symbols
        "\u200d"  # zero width joiner
        "\u23cf"  # eject symbol
        "\u23e9"  # fast forward
        "\u231a"  # watch
        "\ufe0f"  # variation selector
        "]+",
        flags=re.UNICODE,
    )

    safe_text = emoji_pattern.sub("", safe_text)

    return safe_text


def strip_ansi_codes(text):
    """
    Remove ANSI color codes from text.

    Args:
        text: Input text string with potential ANSI codes

    Returns:
        str: Text with ANSI codes removed
    """
    if not isinstance(text, str):
        return str(text)

    import re

    ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    return ansi_escape.sub("", text)


# Initialize Windows console on module import
if __name__ != "__main__":
    setup_windows_console()
