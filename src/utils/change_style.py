"""Change_Style table and node decoration for the Terraform plan diff.

Pure presentation helpers. The Change_Category of a resource is mapped to a
colour token, a light background tint, and a Flag_Token:

- :func:`node_style_attributes` draws the coloured border and the tinted
  background around the *whole* node, icon included;
- :func:`decorate_label` prepends the Flag_Token to the existing HTML table
  label built by ``add_node_in_subgraph``.

Only the border, the fill, and the shape family change. The icon path and
scale, the node geometry, and the group are never produced here, so a decorated
node occupies the same box and shows the same icon as in Legacy_Mode
(Requirements 5.5, 5.6). The label still carries only resource name, short
resource type, and Flag_Token, never attribute values (Requirement 10.2).
"""

import re
from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Sequence, Set, Tuple

from utils.logger import SingletonLogger

logger = SingletonLogger().get_logger()


@dataclass(frozen=True)
class ChangeStyle:
    """Colour token, Flag_Token, tint, and display label of one Change_Category."""

    color: str
    flag: str
    label: str
    tint: str = ""


#: Change_Style table. ``unchanged`` is explicitly present and explicitly
#: styleless so that "no decoration" is a table entry rather than a fallback.
#: ``tint`` is the colour token blended 15% into white, light enough for the
#: resource icon and the label to stay readable on top of it.
CHANGE_STYLES: Dict[str, Optional[ChangeStyle]] = {
    "delete": ChangeStyle(color="#D13438", flag="-", label="Delete", tint="#F8E1E1"),
    "update": ChangeStyle(color="#0078D4", flag="~", label="Update", tint="#D9EBF9"),
    "create": ChangeStyle(color="#107C10", flag="+", label="Create", tint="#DBEBDB"),
    "replace": ChangeStyle(color="#D13438", flag="±", label="Replace", tint="#F8E1E1"),
    "unchanged": None,
}

#: Node attributes that carry the change decoration. Everything else about a
#: node — the icon path and scale, the geometry, the group — is untouched, so a
#: decorated node still occupies the same box and shows the same icon.
NODE_DECORATION_KEYS: Tuple[str, ...] = ("shape", "style", "color", "fillcolor", "penwidth")

#: Cluster attributes that carry the change decoration. A cluster keeps its own
#: ``style`` (``dashed``) and its own label, so neither is produced here: only
#: the border colour, the background tint, and the border width change.
CLUSTER_DECORATION_KEYS: Tuple[str, ...] = ("color", "bgcolor", "penwidth")

#: Border width of a decorated node, in points.
NODE_PENWIDTH: str = "2"

#: Border width of a decorated cluster, in points. A cluster border encloses a
#: whole VNet or subnet, so it needs to be thicker than a node border to read at
#: the zoom level a full diagram is viewed at.
CLUSTER_PENWIDTH: str = "3"

#: Canonical display order used by the Legend.
LEGEND_ORDER: Tuple[str, ...] = ("create", "update", "replace", "delete", "unchanged")

#: Title row of the Legend cluster label.
LEGEND_TITLE: str = "Change Legend"

#: Display label of the styleless category.
UNCHANGED_LABEL: str = "Unchanged"

# Values already reported through resolve_style, so an out-of-set category
# warns once per distinct value instead of once per node (Requirement 4.6).
_WARNED_CATEGORIES: Set[str] = set()

_FIRST_CELL_RE = re.compile(r"<TD(?P<attrs>[^>]*)>", re.IGNORECASE)
_CELL_RE = re.compile(r"<TD[^>]*>", re.IGNORECASE)


def reset_style_warnings() -> None:
    """Forget which out-of-set categories were already reported."""
    _WARNED_CATEGORIES.clear()


def resolve_style(change_category: Optional[str]) -> Optional[ChangeStyle]:
    """Return the Change_Style of a category, or ``None`` for no decoration.

    ``None`` (Legacy_Mode) and ``unchanged`` resolve to ``None`` silently. An
    out-of-set value resolves to ``None`` too, with one warning per distinct
    value so rendering continues instead of failing (Requirement 4.6).
    """
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
    except Exception:  # pragma: no cover - defensive, repr of exotic objects
        key = "<unrepresentable>"
    if key in _WARNED_CATEGORIES:
        return
    _WARNED_CATEGORIES.add(key)
    logger.warning(
        "Unknown change category %s; rendering it without change decoration.",
        key,
    )


def node_style_attributes(style: ChangeStyle) -> Dict[str, str]:
    """Return the node attributes that draw the change state over the whole node.

    The coloured border and the light background belong to the node rather than
    to the label, so they surround the resource icon as well as the text. The
    fill is drawn before the icon, so the icon stays visible on top of it.
    """
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

    The cluster equivalent of :func:`node_style_attributes`: a VNet or a subnet
    renders as a Graphviz cluster rather than a node, so its border colour is
    ``color``, its fill is ``bgcolor`` rather than ``fillcolor``, and its dashed
    outline and its label are left alone. The returned keys are exactly
    :data:`CLUSTER_DECORATION_KEYS`, so the caller merges them over the legacy
    cluster attributes and nothing else moves.
    """
    if style is None:
        return {}
    return {
        "color": style.color,
        "bgcolor": style.tint or "white",
        "penwidth": CLUSTER_PENWIDTH,
    }


def decorate_label(label_html: str, style: ChangeStyle) -> str:
    """Prepend the coloured Flag_Token to an HTML table label.

    The border and the background live on the node (see
    :func:`node_style_attributes`); the label only carries the Flag_Token, which
    is what keeps the Change_Category readable in a monochrome print
    (Requirement 5.9). The table structure and every existing cell are untouched.
    """
    if style is None:
        return label_html
    return _prepend_flag(label_html, style)


def decorate_cluster_label(label_html: str, style: ChangeStyle) -> str:
    """Prepend the coloured Flag_Token to the first *text* cell of a cluster label.

    A cluster label is an HTML table whose first cell holds the container icon,
    and Graphviz rejects a table cell that mixes an image with text — it fails the
    whole render rather than dropping the cell — so the Flag_Token goes into the
    first cell that is not an image cell, which is the one naming the container.
    The table structure and every existing cell content are untouched
    (Requirement 5.9).
    """
    if style is None:
        return label_html

    flag_markup = f"<FONT COLOR='{style.color}'><B>{style.flag}</B></FONT> "
    for cell in _CELL_RE.finditer(label_html):
        if label_html[cell.end() :].lstrip()[:4].lower() == "<img":
            continue
        return label_html[: cell.end()] + flag_markup + label_html[cell.end() :]

    # No text cell (defensive): fall back to the node behaviour.
    return _prepend_flag(label_html, style)


def _prepend_flag(label_html: str, style: ChangeStyle) -> str:
    """Insert the coloured Flag_Token at the start of the first label cell."""
    flag_markup = f"<FONT COLOR='{style.color}'><B>{style.flag}</B></FONT> "

    cell = _FIRST_CELL_RE.search(label_html)
    if cell is not None:
        return label_html[: cell.end()] + flag_markup + label_html[cell.end() :]

    # Labels without a table cell (defensive): keep the HTML-like wrapping.
    if label_html.startswith("<<") and label_html.endswith(">>"):
        return "<<" + flag_markup + label_html[2:-2] + ">>"
    return flag_markup + label_html


def legend_label(categories: Sequence[str], counts: Mapping[str, int]) -> str:
    """Build the Legend HTML table label.

    One row per present Change_Category in canonical order, each carrying the
    colour swatch, the Flag_Token, the display label, and the count
    (Requirements 5.7, 5.8). Unknown categories are ignored.
    """
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
            # The swatch mirrors a decorated node: tinted fill, coloured border.
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
