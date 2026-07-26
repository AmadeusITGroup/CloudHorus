"""Change_Style table and node decoration (mirror of ``utils.change_style``).

Kept in step with the top-level module so both packages can decorate nodes
without importing across package roots.
"""

import re
from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Sequence, Set, Tuple

from .logger import get_logger

logger = get_logger()


@dataclass(frozen=True)
class ChangeStyle:
    """Colour token, Flag_Token, tint, and display label of one Change_Category."""

    color: str
    flag: str
    label: str
    tint: str = ""


#: Change_Style table. ``unchanged`` is explicitly styleless. ``tint`` is the
#: colour token blended 15% into white.
CHANGE_STYLES: Dict[str, Optional[ChangeStyle]] = {
    "delete": ChangeStyle(color="#D13438", flag="-", label="Delete", tint="#F8E1E1"),
    "update": ChangeStyle(color="#0078D4", flag="~", label="Update", tint="#D9EBF9"),
    "create": ChangeStyle(color="#107C10", flag="+", label="Create", tint="#DBEBDB"),
    "replace": ChangeStyle(color="#D13438", flag="±", label="Replace", tint="#F8E1E1"),
    "unchanged": None,
}

#: Node attributes that carry the change decoration.
NODE_DECORATION_KEYS: Tuple[str, ...] = ("shape", "style", "color", "fillcolor", "penwidth")

#: Cluster attributes that carry the change decoration. The cluster keeps its
#: own ``style`` (``dashed``) and its own label.
CLUSTER_DECORATION_KEYS: Tuple[str, ...] = ("color", "bgcolor", "penwidth")

#: Border width of a decorated node, in points.
NODE_PENWIDTH: str = "2"

#: Border width of a decorated cluster, in points.
CLUSTER_PENWIDTH: str = "3"

#: Canonical display order used by the Legend.
LEGEND_ORDER: Tuple[str, ...] = ("create", "update", "replace", "delete", "unchanged")

#: Title row of the Legend cluster label.
LEGEND_TITLE: str = "Change Legend"

#: Display label of the styleless category.
UNCHANGED_LABEL: str = "Unchanged"

_WARNED_CATEGORIES: Set[str] = set()

_FIRST_CELL_RE = re.compile(r"<TD(?P<attrs>[^>]*)>", re.IGNORECASE)
_CELL_RE = re.compile(r"<TD[^>]*>", re.IGNORECASE)


def reset_style_warnings() -> None:
    """Forget which out-of-set categories were already reported."""
    _WARNED_CATEGORIES.clear()


def resolve_style(change_category: Optional[str]) -> Optional[ChangeStyle]:
    """Return the Change_Style of a category, or ``None`` for no decoration."""
    if change_category is None:
        return None

    try:
        style = CHANGE_STYLES[change_category]
    except (KeyError, TypeError):
        _warn_unknown(change_category)
        return None
    return style


def _warn_unknown(change_category: object) -> None:
    """Log an unknown Change_Category once per distinct value."""
    try:
        key = change_category if isinstance(change_category, str) else repr(change_category)
    except Exception:  # pragma: no cover - defensive
        key = "<unrepresentable>"
    if key in _WARNED_CATEGORIES:
        return
    _WARNED_CATEGORIES.add(key)
    logger.warning(
        "Unknown change category %s; rendering it without change decoration.",
        key,
    )


def node_style_attributes(style: ChangeStyle) -> Dict[str, str]:
    """Return the node attributes that draw the change state over the whole node."""
    if style is None:
        return {}
    return {
        "shape": "box",
        "style": "filled,rounded",
        "color": style.color,
        "fillcolor": style.tint or "white",
        "penwidth": NODE_PENWIDTH,
    }


def cluster_style_attributes(style: ChangeStyle) -> Dict[str, str]:
    """Return the cluster attributes that draw the change state around a container.

    Cluster equivalent of :func:`node_style_attributes`: the fill is ``bgcolor``
    rather than ``fillcolor``, and the cluster's dashed outline and label are
    left untouched.
    """
    if style is None:
        return {}
    return {
        "color": style.color,
        "bgcolor": style.tint or "white",
        "penwidth": CLUSTER_PENWIDTH,
    }


def decorate_label(label_html: str, style: ChangeStyle) -> str:
    """Prepend the coloured Flag_Token to an HTML table label."""
    if style is None:
        return label_html
    return _prepend_flag(label_html, style)


def decorate_cluster_label(label_html: str, style: ChangeStyle) -> str:
    """Prepend the coloured Flag_Token to the first *text* cell of a cluster label.

    Graphviz rejects a table cell that mixes an image with text, and a cluster
    label opens with the container icon, so the flag goes into the first non-image
    cell instead of the first cell.
    """
    if style is None:
        return label_html

    flag_markup = f"<FONT COLOR='{style.color}'><B>{style.flag}</B></FONT> "
    for cell in _CELL_RE.finditer(label_html):
        if label_html[cell.end() :].lstrip()[:4].lower() == "<img":
            continue
        return label_html[: cell.end()] + flag_markup + label_html[cell.end() :]

    return _prepend_flag(label_html, style)


def _prepend_flag(label_html: str, style: ChangeStyle) -> str:
    """Insert the coloured Flag_Token at the start of the first label cell."""
    flag_markup = f"<FONT COLOR='{style.color}'><B>{style.flag}</B></FONT> "

    cell = _FIRST_CELL_RE.search(label_html)
    if cell is not None:
        return label_html[: cell.end()] + flag_markup + label_html[cell.end() :]

    if label_html.startswith("<<") and label_html.endswith(">>"):
        return "<<" + flag_markup + label_html[2:-2] + ">>"
    return flag_markup + label_html


def legend_label(categories: Sequence[str], counts: Mapping[str, int]) -> str:
    """Build the Legend HTML table label."""
    present = set(categories or ())
    rows = [f"<TR><TD COLSPAN='3'><B>{LEGEND_TITLE}</B></TD></TR>"]

    for category in LEGEND_ORDER:
        if category not in present:
            continue
        style = CHANGE_STYLES.get(category)
        count = _as_count(counts, category)
        if style is None:
            rows.append(f"<TR><TD></TD><TD>{UNCHANGED_LABEL}</TD><TD>{count}</TD></TR>")
        else:
            rows.append(
                f"<TR><TD BGCOLOR='{style.tint or style.color}' COLOR='{style.color}' "
                f"BORDER='1' WIDTH='14' HEIGHT='14'></TD>"
                f"<TD><FONT COLOR='{style.color}'><B>{style.flag}</B></FONT> {style.label}</TD>"
                f"<TD>{count}</TD></TR>"
            )

    return "<<TABLE border='0' cellborder='0' cellspacing='1'>" + "".join(rows) + "</TABLE>>"


def _as_count(counts: Mapping[str, int], category: str) -> int:
    """Return the count of a category, defaulting to zero for anything odd."""
    try:
        return int(counts.get(category, 0) or 0)
    except (AttributeError, TypeError, ValueError):
        return 0
