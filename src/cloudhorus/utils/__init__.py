"""Utilities package."""

from .change_style import (
    CHANGE_STYLES,
    LEGEND_TITLE,
    ChangeStyle,
    decorate_label,
    legend_label,
    reset_style_warnings,
    resolve_style,
)
from .graph_utils import GraphNodeBuilder, add_node_in_subgraph, get_node_builder
from .icon_manager import IconManager, get_icon, get_icon_manager
from .logger import CloudHorusLogger, SingletonLogger, get_logger
from .resource_filter import ResourceFilter, get_filter, should_skip, should_skip_dependency
from .windows_utils import (
    remove_emojis_from_text,
    safe_print,
    setup_windows_console,
    strip_ansi_codes,
)

__all__ = [
    "CloudHorusLogger",
    "SingletonLogger",
    "get_logger",
    "ResourceFilter",
    "should_skip",
    "should_skip_dependency",
    "get_filter",
    "GraphNodeBuilder",
    "add_node_in_subgraph",
    "get_node_builder",
    "IconManager",
    "get_icon",
    "get_icon_manager",
    "CHANGE_STYLES",
    "LEGEND_TITLE",
    "ChangeStyle",
    "decorate_label",
    "legend_label",
    "reset_style_warnings",
    "resolve_style",
    "setup_windows_console",
    "safe_print",
    "remove_emojis_from_text",
    "strip_ansi_codes",
]
