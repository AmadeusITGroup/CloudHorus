import base64
import html
import json
import os
import platform
import re
import subprocess
import time
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

import graphviz
from graphviz import Digraph
from graphviz.backend.execute import ExecutableNotFound
from tqdm import tqdm

from utils.change_style import (
    CHANGE_STYLES,
    cluster_style_attributes,
    decorate_cluster_label,
    legend_label,
    resolve_style,
)
from utils.geticons import ICONS_DIR, get_icon
from utils.graph_utils import add_node_in_subgraph, should_skip, should_skip_dependency
from utils.heartbeat import Heartbeat
from utils.logger import SingletonLogger

from .azure_cli import (
    az_sdk,
    export_resource_group_template,
    get_api_cache_stats,
    get_bastion_host_name,
    get_pe_subnet,
    get_private_dns_zones_without_vnets,
    get_resource_group_location,
    get_subscription_name,
    is_resource_group_in_subscription,
    is_resource_group_not_in_all_subscriptions,
    is_subscription_in_tenant,
    is_vnet_linked_to_private_dns_zone,
    login_to_tenant,
)
from .bicep_builder import build_bicep_template
from .plan_diff import (
    CHANGE_CATEGORIES,
    NO_RESOURCE_ENTRY_REASON,
    UNCHANGED_CATEGORY,
    UNDISPLAYED_REASONS,
    ChangeSummary,
    UndisplayedChange,
    format_change_summary,
)
from .terraform_builder import TerraformTemplateBuilder, build_terraform_template
from .resource_processor import get_cross_resource_group_dependencies, get_subnet_implicit_dependencies

logger = SingletonLogger().get_logger()

#: Key of the per-template change index: (resource name, renderer resource type).
ChangeIndexKey = Tuple[str, str]


def build_change_index(template_data: Any) -> Dict[ChangeIndexKey, str]:
    """Index the `changeCategory` of one registered template by (name, type).

    The subnet placement loop of the render pass works from `dependencies` keys
    rather than from resource dicts, so it needs this lookup to recover the
    Change_Category of a resource it is about to place inside a subnet.

    Legacy templates carry no `changeCategory`, which yields an empty index and
    therefore Legacy_Mode styling everywhere (Requirement 4.5).
    """
    index: Dict[ChangeIndexKey, str] = {}
    if not isinstance(template_data, dict):
        return index

    resources = template_data.get("resources")
    if not isinstance(resources, list):
        return index

    for resource in resources:
        if not isinstance(resource, dict):
            continue
        category = resource.get("changeCategory")
        if not isinstance(category, str) or not category:
            continue
        name = resource.get("name")
        resource_type = resource.get("type")
        if not isinstance(name, str) or not isinstance(resource_type, str):
            continue
        index[(name, resource_type)] = category

    return index


#: Renderer resource type of a subnet. Its `name` in the Renderer_Template is the
#: compound `"<vnet>/<subnet>"`, while the render pass works from the bare subnet
#: name, hence `resolve_subnet_change_category`.
SUBNET_RENDERER_TYPE: str = "Microsoft.Network/virtualNetworks/subnets"


def resolve_subnet_change_category(
    change_index: Dict[ChangeIndexKey, str],
    vnet_name: str,
    subnet_name: str,
) -> Optional[str]:
    """Return the Change_Category of a subnet cluster, or None when it has none.

    `build_change_index` keys a subnet by the name the Renderer_Template carries,
    which the Terraform builder writes as the compound `"<vnet>/<subnet>"`. The
    render pass only holds the bare subnet name, so the compound key is tried
    first and the bare name second, which covers a template that names its
    subnets without their virtual network.
    """
    if not change_index or not subnet_name:
        return None

    compound = f"{vnet_name}/{subnet_name}" if vnet_name else subnet_name
    category = change_index.get((compound, SUBNET_RENDERER_TYPE))
    if category is None:
        category = change_index.get((subnet_name, SUBNET_RENDERER_TYPE))
    return category


def apply_cluster_change_style(
    label: str,
    attributes: Dict[str, str],
    change_category: Optional[str],
) -> Tuple[str, Dict[str, str]]:
    """Merge the Change_Style of a container cluster into its legacy attributes.

    VNets and subnets render as Graphviz clusters rather than nodes, so they never
    reach `add_node_in_subgraph` and need the decoration applied here: the
    Flag_Token goes into the HTML table label and the colour tokens replace the
    legacy `color`/`bgcolor`, with a thicker border (Requirements 5.1-5.4, 5.9).
    The flag lands in the cell naming the container rather than in the first cell,
    because the first cell of a cluster label holds the container icon and
    Graphviz refuses a cell that mixes an image with text.

    A category of `None`, `unchanged`, or an out-of-set value returns the label
    and the attribute mapping unchanged, so Legacy_Mode DOT stays byte-identical
    (Requirement 5.5).
    """
    style = resolve_style(change_category)
    if style is None:
        return label, attributes

    decorated = dict(attributes)
    decorated.update(cluster_style_attributes(style))
    return decorate_cluster_label(label, style), decorated


def style_subnet_cluster(
    subnet_subgraph: Any,
    subnet_name: str,
    subnet_cidr: Any,
    vnet_name: str,
    change_index: Dict[ChangeIndexKey, str],
) -> None:
    """Emit the cluster attributes of one subnet subgraph, decoration included.

    The render pass opens `cluster_subnet<name>` from four different places; all
    four emit the same label and the same legacy attributes, so they share this
    helper rather than repeating the block.
    """
    label = (
        "<<TABLE border='0' cellborder='0' cellspacing='0' cellpadding='0'>"
        f"<TR><TD align='center' rowspan='2'><img src='{ICONS_DIR}/subnets.png' scale='true'/></TD>"
        f"<TD align='left'>{subnet_name}</TD></TR>"
        f"<TR><TD align='left'>CIDR: {subnet_cidr}</TD></TR></TABLE>>"
    )
    label, attributes = apply_cluster_change_style(
        label,
        {"style": "dashed", "fontsize": "30", "color": "black", "bgcolor": "whitesmoke"},
        resolve_subnet_change_category(change_index, vnet_name, subnet_name),
    )
    subnet_subgraph.attr(label=label, **attributes)


def accumulate_change_metadata(
    template_data: Any,
    aggregate_counts: Dict[str, int],
    aggregate_summary: List[Any],
) -> None:
    """Fold the change metadata of one template into the run-level aggregates.

    `aggregate_counts` holds one entry per Change_Category as soon as a single
    template reports change counts, so its truthiness is the Plan_Diff_Mode
    signal the Legend and the Change_Summary guard on. `aggregate_summary`
    collects the `changesNotDisplayed` entries of every template.
    """
    if not isinstance(template_data, dict):
        return

    metadata = template_data.get("metadata")
    if not isinstance(metadata, dict):
        return

    counts = metadata.get("changeCounts")
    if isinstance(counts, dict):
        for category in CHANGE_CATEGORIES:
            value = counts.get(category, 0)
            if isinstance(value, bool) or not isinstance(value, int):
                value = 0
            aggregate_counts[category] = aggregate_counts.get(category, 0) + value

    not_displayed = metadata.get("changesNotDisplayed")
    if isinstance(not_displayed, list):
        aggregate_summary.extend(not_displayed)


def has_rendered_changes(aggregate_counts: Dict[str, int]) -> bool:
    """Return True when the run carries at least one non-`unchanged` category.

    Consumed by the Legend cluster (task 7.4) and the Change_Summary reporting
    (task 7.6) so both guard on the same condition (Requirements 5.7, 5.8).
    """
    return any(count > 0 for category, count in aggregate_counts.items() if category != UNCHANGED_CATEGORY)


#: Filename suffix of the Change_Summary sidecar written next to the PNG.
CHANGE_SUMMARY_SUFFIX: str = ".change-summary.json"


def build_run_change_summary(aggregate_counts: Dict[str, int], aggregate_summary: List[Any]) -> ChangeSummary:
    """Fold the run-level aggregates into the Change_Summary of the whole run.

    The aggregates are what survives the render pass: `aggregate_counts` sums
    the per-template `changeCounts`, and `aggregate_summary` concatenates the
    per-template `changesNotDisplayed` payloads. Rebuilding a
    :class:`~core.plan_diff.ChangeSummary` from them keeps one console format
    and one sidecar payload for the run instead of one per template
    (Requirement 7.1).

    Malformed entries are dropped rather than raised on, and an address is
    reported once even when several templates carry it.
    """
    not_displayed: List[UndisplayedChange] = []
    seen: set = set()
    for entry in aggregate_summary or []:
        if not isinstance(entry, dict):
            continue
        address = entry.get("address")
        if not isinstance(address, str) or not address or address in seen:
            continue
        seen.add(address)
        terraform_type = entry.get("terraformType")
        category = entry.get("category")
        reason = entry.get("reason")
        not_displayed.append(
            UndisplayedChange(
                address=address,
                terraform_type=terraform_type if isinstance(terraform_type, str) else "",
                category=category if category in CHANGE_CATEGORIES else UNCHANGED_CATEGORY,
                reason=reason if reason in UNDISPLAYED_REASONS else NO_RESOURCE_ENTRY_REASON,
            )
        )

    present_categories = [category for category in CHANGE_CATEGORIES if aggregate_counts.get(category, 0) > 0]
    return ChangeSummary(
        counts=dict(aggregate_counts),
        present_categories=present_categories,
        not_displayed=not_displayed,
    )


def change_styles_payload() -> Dict[str, Optional[Dict[str, str]]]:
    """Return the Change_Style table in JSON form for the sidecar consumers.

    The WebUI colours its filter chips from this block, so the sidecar carries
    the same colour and Flag_Token the Legend and the node labels use.
    `unchanged` is explicitly `null`: styleless is a table entry, not a gap.
    """
    payload: Dict[str, Optional[Dict[str, str]]] = {}
    for category in CHANGE_CATEGORIES:
        style = CHANGE_STYLES.get(category)
        payload[category] = None if style is None else {"color": style.color, "flag": style.flag, "label": style.label}
    return payload


def write_change_summary_sidecar(summary: ChangeSummary, output_filename: str) -> Optional[str]:
    """Write `azure_resources_<timestamp>.change-summary.json` beside the PNG.

    `output_filename` is the extension-less PNG path, so the sidecar lands in
    the existing output folder next to the diagram and shares its timestamp
    (Requirement 7.5). A write failure is degraded to a warning: the diagram is
    already on disk and the summary is also on the console, so the run must not
    fail over the sidecar.
    """
    sidecar_path = f"{output_filename}{CHANGE_SUMMARY_SUFFIX}"
    payload = summary.to_payload()
    payload["changeStyles"] = change_styles_payload()
    try:
        with open(sidecar_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
    except OSError as error:
        logger.warning(f"Could not write the change summary sidecar {sidecar_path}: {error}")
        return None

    logger.info(f"Saved change summary: {os.path.abspath(sidecar_path)}")
    return sidecar_path


#: Flag_Tokens the Change_Style table can prepend to a node label. Longest
#: first, so a multi-character token is stripped before a single-character one.
_CHANGE_FLAGS: Tuple[str, ...] = tuple(
    sorted((style.flag for style in CHANGE_STYLES.values() if style is not None), key=len, reverse=True)
)

#: A quoted identifier followed by an attribute list. The DOT written for the
#: Draw.io export goes through ``unflatten``, which pretty-prints one attribute
#: per line, so the statement must be matched across line breaks rather than
#: anchored to a single line.
_DOT_NODE_STATEMENT_RE = re.compile(r'"(?P<node_id>[^"\n]+)"[ \t\r\n]*\[(?P<attrs>[^\[\]]*)\]', re.DOTALL)
_DOT_FIRST_CELL_RE = re.compile(r"<TR><TD[^>]*>(?P<cell>.*?)</TD></TR>", re.IGNORECASE | re.DOTALL)
_DOT_IMAGE_ATTR_RE = re.compile(r'image="(?P<path>[^"]+)"')
_DOT_BORDER_COLOR_ATTR_RE = re.compile(r'(?<!fill)color="(?P<value>#[0-9A-Fa-f]{3,8})"')
_DOT_FILL_COLOR_ATTR_RE = re.compile(r'fillcolor="(?P<value>#[0-9A-Fa-f]{3,8})"')
_DOT_PENWIDTH_ATTR_RE = re.compile(r'penwidth="?(?P<value>[0-9.]+)"?')

#: Cluster header and the two forms its attributes take. Graphviz writes them as
#: bare assignments on the line after the header; ``unflatten`` rewrites the same
#: attributes into a ``graph [ ... ]`` block spread over several lines, and the
#: Draw.io export reads the unflattened source, so both forms are matched.
_DOT_CLUSTER_HEADER_RE = re.compile(r'subgraph[ \t]+"?(?P<name>cluster_[^"\n{]*?)"?[ \t]*\{')
_DOT_CLUSTER_GRAPH_ATTRS_RE = re.compile(r"[ \t\r\n]*graph[ \t\r\n]*\[(?P<attrs>[^\[\]]*)\]", re.DOTALL)
#: ``color`` of a cluster, excluding ``bgcolor`` and ``fillcolor``.
_DOT_CLUSTER_COLOR_ATTR_RE = re.compile(r'(?<![A-Za-z])color="(?P<value>#[0-9A-Fa-f]{3,8})"')
_DOT_CLUSTER_BGCOLOR_ATTR_RE = re.compile(r'bgcolor="(?P<value>#[0-9A-Fa-f]{3,8})"')
#: A single HTML table cell of a label, used to find the cell naming a cluster.
_DOT_TABLE_CELL_RE = re.compile(r"<TD[^>]*>(?P<cell>.*?)</TD>", re.IGNORECASE | re.DOTALL)
_LABEL_SEGMENT_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_MARKUP_RE = re.compile(r"<[^>]*>")

#: Style prefix graphviz2drawio produces for an icon node. Re-applied to node
#: cells whose icon the converter dropped, so a change-decorated node keeps the
#: shape and icon it has without Plan_Diff_Mode (Requirement 8.6).
_NODE_ICON_STYLE = (
    "shape=image;verticalLabelPosition=bottom;labelBackgroundColor=default;aspect=fixed;imageAspect=0;image={icon};"
)


def _label_resource_name(markup: str) -> str:
    """Return the resource name carried by an HTML-ish node label.

    Markup is dropped, the label is split on its line breaks, and a leading
    Flag_Token is removed, so the decorated and the undecorated form of the same
    node label both yield the bare resource name.
    """
    for segment in _LABEL_SEGMENT_RE.split(markup):
        text = " ".join(html.unescape(_MARKUP_RE.sub(" ", segment)).split())
        if not text or text in _CHANGE_FLAGS:
            continue
        for flag in _CHANGE_FLAGS:
            if text.startswith(f"{flag} "):
                text = text[len(flag) :].strip()
                break
        if text:
            return text
    return ""


def _resolve_node_key(markup: str, keys: Iterable[str]) -> str:
    """Return the DOT node key a Draw.io cell label belongs to.

    ``_label_resource_name`` yields the bare resource name when the label keeps
    its line breaks. graphviz2drawio does not always keep them: a node whose
    label it reads as a single run of text produces ``"<name> <short type>"``, so
    an exact lookup misses. The longest key the label text starts with is
    therefore accepted as well, which is unambiguous because the remainder is the
    resource type rather than more of the name.
    """
    text = _label_resource_name(markup)
    if not text:
        return ""

    keys = list(keys)
    if text in keys:
        return text

    candidates = [key for key in keys if key and text.startswith(f"{key} ")]
    return max(candidates, key=len) if candidates else ""


def _iter_dot_node_attributes(dot_source: str) -> Iterable[str]:
    """Yield the attribute list of every node declaration in a DOT source.

    Edge statements end in the same ``"id" [attrs]`` shape, so a match whose
    identifier is preceded by ``->`` is an edge target rather than a node
    declaration and is skipped.
    """
    for match in _DOT_NODE_STATEMENT_RE.finditer(dot_source):
        if dot_source[: match.start()].rstrip().endswith("->"):
            continue
        yield match.group("attrs")


def _dot_node_icons(dot_source: str) -> Dict[str, List[str]]:
    """Map the resource name of every DOT node statement to its icon paths."""
    icons: Dict[str, List[str]] = {}
    for attributes in _iter_dot_node_attributes(dot_source):
        image = _DOT_IMAGE_ATTR_RE.search(attributes)
        if image is None:
            continue
        cell = _DOT_FIRST_CELL_RE.search(attributes)
        name = _label_resource_name(cell.group("cell")) if cell is not None else ""
        if not name:
            continue
        paths = icons.setdefault(name, [])
        if image.group("path") not in paths:
            paths.append(image.group("path"))
    return icons


def _dot_node_decorations(dot_source: str) -> Dict[str, Dict[str, str]]:
    """Map the resource name of every decorated DOT node to its Draw.io style keys.

    The Change_Style decoration lives in the node attributes (``color``,
    ``fillcolor``, ``penwidth``). graphviz2drawio reads a node carrying an
    ``image`` as a pure icon cell and emits ``strokeColor=none;fillColor=none``,
    dropping it, so the decoration is translated here and re-applied to the cell
    (Requirement 8.7).
    """
    decorations: Dict[str, Dict[str, str]] = {}
    for attributes in _iter_dot_node_attributes(dot_source):
        border = _DOT_BORDER_COLOR_ATTR_RE.search(attributes)
        if border is None:
            continue
        cell = _DOT_FIRST_CELL_RE.search(attributes)
        name = _label_resource_name(cell.group("cell")) if cell is not None else ""
        if not name or name in decorations:
            continue
        style = {"strokeColor": border.group("value")}
        fill = _DOT_FILL_COLOR_ATTR_RE.search(attributes)
        if fill is not None:
            style["fillColor"] = fill.group("value")
        penwidth = _DOT_PENWIDTH_ATTR_RE.search(attributes)
        if penwidth is not None:
            style["strokeWidth"] = penwidth.group("value")
        decorations[name] = style
    return decorations


def _iter_dot_cluster_attributes(dot_source: str) -> Iterable[Tuple[str, str]]:
    """Yield ``(cluster name, attribute text)`` for every cluster of a DOT source.

    Graphviz emits cluster attributes as bare assignments on the line following
    the ``subgraph`` header, while ``unflatten`` rewrites them into a multi-line
    ``graph [ ... ]`` block. Both are yielded as one flat attribute string. A
    cluster that opens straight onto a node or a nested subgraph carries no
    attributes and yields nothing, so a decorated node statement is never read as
    its enclosing cluster's attributes.
    """
    for match in _DOT_CLUSTER_HEADER_RE.finditer(dot_source):
        rest = dot_source[match.end() :]
        block = _DOT_CLUSTER_GRAPH_ATTRS_RE.match(rest)
        if block is not None:
            yield match.group("name"), block.group("attrs")
            continue
        lines = rest.split("\n", 2)
        candidate = lines[1] if len(lines) > 1 else ""
        if "[" in candidate or "{" in candidate:
            continue
        yield match.group("name"), candidate


def _dot_cluster_decorations(dot_source: str) -> Dict[str, Dict[str, str]]:
    """Map every change-decorated cluster to its Draw.io style keys.

    A VNet or a subnet renders as a Graphviz cluster, so its Change_Style lives in
    the cluster attributes (``color``, ``bgcolor``, ``penwidth``). The Draw.io
    cluster cell is rebuilt from a fixed style string, which would drop the change
    state; it is translated here and re-applied to the container cell, exactly as
    node decorations already are (Requirements 8.6, 8.7).
    """
    decorations: Dict[str, Dict[str, str]] = {}
    for name, attributes in _iter_dot_cluster_attributes(dot_source):
        border = _DOT_CLUSTER_COLOR_ATTR_RE.search(attributes)
        if border is None or name in decorations:
            continue
        style = {"strokeColor": border.group("value")}
        fill = _DOT_CLUSTER_BGCOLOR_ATTR_RE.search(attributes)
        if fill is not None:
            style["fillColor"] = fill.group("value")
            style["fillOpacity"] = "100"
        penwidth = _DOT_PENWIDTH_ATTR_RE.search(attributes)
        if penwidth is not None:
            style["strokeWidth"] = penwidth.group("value")
        decorations[name] = style
    return decorations


#: Flag_Tokens a decorated label opens with, stripped when a cluster label is
#: reduced to the text that identifies it.
_FLAG_TOKENS: str = "".join(style.flag for style in CHANGE_STYLES.values() if style is not None)


def _cluster_label_text(attributes: str) -> str:
    """Return the text identifying a cluster, taken from its label.

    The first cell of a cluster label holds the container icon, so the first cell
    that is not an image cell is the one naming the container ("Name :core-vnet",
    "app"). The Flag_Token a decoration prepends is stripped, so the same text
    identifies the cluster before and after decoration.
    """
    for match in _DOT_TABLE_CELL_RE.finditer(attributes):
        content = match.group("cell")
        if "<img" in content.lower():
            continue
        text = _MARKUP_RE.sub("", content).strip().lstrip(_FLAG_TOKENS).strip()
        if text:
            return text
    return ""


def _dot_cluster_label_texts(dot_source: str) -> Dict[str, str]:
    """Map every cluster of a DOT source to the text identifying it."""
    texts: Dict[str, str] = {}
    for name, attributes in _iter_dot_cluster_attributes(dot_source):
        if name in texts:
            continue
        text = _cluster_label_text(attributes)
        if text:
            texts[name] = text
    return texts


def _resolve_cluster_decoration(
    cell_text: str,
    decorations: Dict[str, Dict[str, str]],
    label_texts: Dict[str, str],
) -> Dict[str, str]:
    """Return the decoration of the cluster a Draw.io container cell belongs to.

    The cluster cells are matched by their label text rather than by the
    ``clustN`` order: a cluster that the render pass re-opens appears several
    times in the DOT but only once in the converter output, so the positional
    mapping the surrounding code uses does not line up with the cells. An
    ambiguous match (two containers with the same label) yields no decoration
    rather than a guess.
    """
    if not cell_text:
        return {}
    matches = [
        decorations[name]
        for name, text in label_texts.items()
        if name in decorations and text and text in cell_text
    ]
    if len(matches) != 1:
        return {}
    return matches[0]


def _apply_drawio_style_keys(style: str, keys: Dict[str, str]) -> str:
    """Replace or append Draw.io style keys on an existing style string."""
    for key, value in keys.items():
        style = re.sub(rf"{key}=[^;]*;?", "", style)
        if style and not style.endswith(";"):
            style += ";"
        style += f"{key}={value};"
    return style


def _icon_data_uri(icon_path: str, cache: Dict[str, Optional[str]]) -> Optional[str]:
    """Return an icon file as a base64 data URI, or None when it is unreadable."""
    if icon_path in cache:
        return cache[icon_path]
    try:
        with open(icon_path, "rb") as icon_file:
            uri: Optional[str] = "data:image/png," + base64.b64encode(icon_file.read()).decode("utf-8")
    except Exception as exc:
        logger.warning(f"Failed to read/convert node icon {icon_path}: {exc}")
        uri = None
    cache[icon_path] = uri
    return uri


def fix_drawio_hierarchy(dot_source: str, xml_content: str) -> str:
    """
    Post-process graphviz2drawio XML to create proper nested containers.

    graphviz2drawio has a limitation where clusters become flat cells instead of proper
    container groups. This function fixes the parent-child relationships by:
    1. Parsing the DOT source to understand the nesting structure
    2. Mapping cluster names to their generated mxCell IDs (clust1, clust2, etc.)
    3. Updating parent attributes to create proper nesting
    4. Extracting and applying background colors from DOT bgcolor attributes

    Args:
        dot_source: The original DOT source code
        xml_content: The XML output from graphviz2drawio

    Returns:
        Fixed XML with proper parent-child relationships for clusters
    """
    import re
    import xml.etree.ElementTree as ET

    # Map of DOT color names to hex values for Draw.io
    COLOR_MAP = {
        "lightcyan": "#E0FFFF",
        "ivory1": "#FFFFF0",
        "ghostwhite": "#F8F8FF",
        "lightblue": "#ADD8E6",
        "lightyellow": "#FFFFE0",
        "white": "#FFFFFF",
    }

    try:
        # Parse the XML
        root = ET.fromstring(xml_content)

        # Build cluster hierarchy from DOT source
        # This maps cluster names to their nesting level, parent, and bgcolor
        cluster_order = []  # Ordered list of (cluster_name, level, parent_cluster, bgcolor)
        cluster_stack: List[str] = []
        lines = dot_source.split("\n")

        # Track current cluster being defined to capture its bgcolor
        current_cluster_name = None
        current_cluster_parent = None
        current_cluster_level = 0
        current_bgcolor = None
        in_graph_attrs = False  # Track if we're inside the graph attributes section
        line_since_subgraph = 0  # Track lines since last subgraph declaration

        for line in lines:
            # Match subgraph declarations (with or without quotes)
            subgraph_match = re.search(r'subgraph\s+["]?(\S+?)["]?\s*\{', line)
            if subgraph_match:
                # If we had a pending cluster, add it now (likely has no graph attrs)
                if current_cluster_name:
                    cluster_order.append(
                        (current_cluster_name, current_cluster_level, current_cluster_parent, current_bgcolor)
                    )
                    logger.debug(f"Added pending cluster: {current_cluster_name} (bgcolor={current_bgcolor})")
                    current_cluster_name = None

                cluster_name = subgraph_match.group(1)
                parent = cluster_stack[-1] if cluster_stack else None
                level = len(cluster_stack)

                # Store cluster info temporarily (bgcolor will be found in next lines)
                current_cluster_name = cluster_name
                current_cluster_parent = parent
                current_cluster_level = level
                current_bgcolor = None
                in_graph_attrs = False
                line_since_subgraph = 0

                cluster_stack.append(cluster_name)

            # Check if we're entering the graph attributes section
            elif current_cluster_name and "graph [" in line:
                in_graph_attrs = True
                line_since_subgraph = 0
                # Check if bgcolor is on the same line
                if "bgcolor=" in line:
                    bgcolor_match = re.search(r"bgcolor=([a-zA-Z0-9]+)", line)
                    if bgcolor_match:
                        current_bgcolor = bgcolor_match.group(1)

            # Look for bgcolor attribute within the graph attributes section
            elif current_cluster_name and in_graph_attrs:
                if "bgcolor=" in line:
                    bgcolor_match = re.search(r"bgcolor=([a-zA-Z0-9]+)", line)
                    if bgcolor_match:
                        current_bgcolor = bgcolor_match.group(1)
                # End of graph attributes section
                if "];" in line or ("]" in line and not "bgcolor=" in line):
                    # Now we have complete cluster info, add to list
                    cluster_order.append(
                        (current_cluster_name, current_cluster_level, current_cluster_parent, current_bgcolor)
                    )
                    current_cluster_name = None  # Reset
                    in_graph_attrs = False

            elif "}" in line and cluster_stack:
                # If we haven't captured this cluster yet, add it without bgcolor
                if current_cluster_name:
                    cluster_order.append(
                        (current_cluster_name, current_cluster_level, current_cluster_parent, current_bgcolor)
                    )
                    current_cluster_name = None
                cluster_stack.pop()

            elif current_cluster_name:
                line_since_subgraph += 1

        logger.debug(f"Found {len(cluster_order)} clusters in DOT source")

        # Map cluster numbers (clust1, clust2, etc.) to cluster names
        # graphviz2drawio generates IDs like clust1, clust2 in order of appearance
        cluster_id_map: Dict[str, Dict[str, Any]] = {}  # Maps "clust1" -> cluster_name, level, parent, bgcolor
        parent_to_id = {}  # Maps cluster_name -> clust_id for parent lookup

        for i, (cluster_name, level, parent, bgcolor) in enumerate(cluster_order, start=1):
            cluster_id = f"clust{i}"
            cluster_id_map[cluster_id] = {"name": cluster_name, "level": level, "parent": parent, "bgcolor": bgcolor}
            parent_to_id[cluster_name] = cluster_id
            logger.debug(f"Mapped {cluster_id} to {cluster_name} (level={level}, parent={parent}, bgcolor={bgcolor})")

        # Build map from DOT source to find which nodes belong to which cluster
        # Parse DOT source to track node definitions within subgraphs
        node_to_cluster = {}  # Maps node_id -> cluster_name
        current_cluster_stack = []

        for line in lines:
            # Track subgraph nesting
            subgraph_match = re.search(r'subgraph\s+["]?(\S+?)["]?\s*\{', line)
            if subgraph_match:
                current_cluster_stack.append(subgraph_match.group(1))
            elif "}" in line and current_cluster_stack:
                current_cluster_stack.pop()
            # Match node definitions (various formats)
            # Format 1: "node-id" [attributes...] (multi-line node definitions)
            # Format 2: "node-id"; (bare node reference)
            # Format 3: unquoted_id [attributes...] (simple identifiers)
            # Skip: node-id -> other-node (edges)
            elif current_cluster_stack and "->" not in line and "--" not in line:
                # Try to match node definition patterns
                # Pattern 1: quoted string followed by [ or ;
                quoted_match = re.match(r'\s*"([^"]+)"\s*[\[\;]', line)
                # Pattern 2: unquoted identifier followed by [
                unquoted_match = re.match(r"\s*([a-zA-Z0-9_-]+)\s*\[", line)

                node_id = None
                if quoted_match:
                    node_id = quoted_match.group(1)
                elif unquoted_match:
                    node_id = unquoted_match.group(1)

                if node_id:
                    # Assign to the deepest (innermost) cluster
                    innermost_cluster = current_cluster_stack[-1]
                    node_to_cluster[node_id] = innermost_cluster
                    logger.debug(f"Node '{node_id}' belongs to cluster {innermost_cluster}")

        logger.debug(f"Mapped {len(node_to_cluster)} nodes to their parent clusters")

        # Create a mapping from XML node labels back to DOT node names
        # This is needed because graphviz2drawio uses node1, node2, etc. as IDs
        # but we need to match them to actual DOT node names
        # Build a reverse lookup: display_name -> list of full_dot_node_ids
        # Handle multi-line node definitions by tracking the current node being defined
        # IMPORTANT: Multiple nodes can have the same display name (e.g., shared route tables)
        # so we build a list and match based on XML cell position/context later
        display_name_to_dot_ids: Dict[str, List[str]] = {}  # Maps display name to LIST of full DOT node IDs
        current_node_id = None
        in_node_definition = False

        for line in lines:
            # Start of a node definition: "node-id" [
            if not in_node_definition:
                node_start_match = re.match(r'\s*"([^"]+)"\s*\[', line)
                if node_start_match:
                    current_node_id = node_start_match.group(1)
                    in_node_definition = True
                    # Check if label is on the same line
                    if "<TR><TD>" in line:
                        label_match = re.search(r"<TR><TD>([^<]+)</TD></TR>", line)
                        if label_match:
                            display_name = label_match.group(1).strip()
                            if display_name not in display_name_to_dot_ids:
                                display_name_to_dot_ids[display_name] = []
                            display_name_to_dot_ids[display_name].append(current_node_id)
                            logger.debug(f"Display name '{display_name}' maps to DOT ID '{current_node_id}'")
            # Inside a node definition, look for the label
            elif in_node_definition:
                if "<TR><TD>" in line:
                    label_match = re.search(r"<TR><TD>([^<]+)</TD></TR>", line)
                    if label_match:
                        display_name = label_match.group(1).strip()
                        if display_name not in display_name_to_dot_ids:
                            display_name_to_dot_ids[display_name] = []
                        if current_node_id is not None:
                            display_name_to_dot_ids[display_name].append(current_node_id)
                        logger.debug(f"Display name '{display_name}' maps to DOT ID '{current_node_id}'")
                # End of node definition: ];
                if "];" in line:
                    in_node_definition = False
                    current_node_id = None

        xml_node_to_dot_name = {}  # Maps "node1" -> actual_dot_node_name
        xml_node_counter = {}  # Track which occurrence of duplicate display names we're on

        for cell in root.findall(".//mxCell"):
            cell_id = cell.get("id", "")
            if cell_id.startswith("node"):
                # Extract the actual node name from the label
                value = cell.get("value", "")
                # Parse the label to get the first line (node name)
                # Format: <font ...>node-name<br/>type</font>
                name_match = re.search(r">([^<]+)<br", value)
                if name_match:
                    display_name = name_match.group(1).strip()
                    # Lookup full DOT node IDs from display name
                    dot_ids = display_name_to_dot_ids.get(display_name, [display_name])

                    # If there's only one match, use it
                    if len(dot_ids) == 1:
                        full_dot_id = dot_ids[0]
                    else:
                        # Multiple matches - use occurrence counter to match DOT order
                        # graphviz2drawio processes nodes in order, so node1, node2, node3...
                        # should map to the 1st, 2nd, 3rd occurrence of that display name in DOT
                        if display_name not in xml_node_counter:
                            xml_node_counter[display_name] = 0
                        idx = xml_node_counter[display_name]
                        if idx < len(dot_ids):
                            full_dot_id = dot_ids[idx]
                            xml_node_counter[display_name] += 1
                            logger.debug(
                                f"XML {cell_id} display name '{display_name}' occurrence #{idx+1} -> '{full_dot_id}'"
                            )
                        else:
                            # Fallback to first if we somehow have more XML nodes than DOT nodes
                            full_dot_id = dot_ids[0]
                            logger.warning(
                                f"XML {cell_id} has more occurrences than DOT for '{display_name}', using first"
                            )

                    xml_node_to_dot_name[cell_id] = full_dot_id
                    logger.debug(f"Mapped XML {cell_id} to DOT node '{full_dot_id}'")

        logger.debug(f"Created XML-to-DOT mapping for {len(xml_node_to_dot_name)} nodes")

        # Build geometry recalculation to fix visual containment
        # Collect all cell geometries first
        cell_geometries = {}  # Maps cell_id -> geometry dict

        for cell in root.findall(".//mxCell"):
            cell_id = cell.get("id", "")
            geom = cell.find("mxGeometry")
            if geom is not None:
                try:
                    cell_geometries[cell_id] = {
                        "x": float(geom.get("x", 0)),
                        "y": float(geom.get("y", 0)),
                        "width": float(geom.get("width", 0)),
                        "height": float(geom.get("height", 0)),
                    }
                except (ValueError, TypeError):
                    pass

        # Build a mapping of which cells belong to which cluster (based on DOT hierarchy)
        cell_to_parent_cluster = {}  # Maps cell_id -> parent_cluster_name

        # For each node, find its parent cluster
        for cell_id in cell_geometries:
            if cell_id in xml_node_to_dot_name:
                dot_name = xml_node_to_dot_name[cell_id]
                if dot_name in node_to_cluster:
                    cell_to_parent_cluster[cell_id] = node_to_cluster[dot_name]

        # For each cluster, find its parent cluster
        for clust_id, info in cluster_id_map.items():
            if info["parent"]:
                cell_to_parent_cluster[clust_id] = info["parent"]

        logger.debug(f"Mapped {len(cell_to_parent_cluster)} cells to their parent clusters")

        # Calculate proper bounding boxes for clusters based on their children
        # Work from deepest to shallowest level
        cluster_bounds: Dict[str, Dict[str, float]] = {}  # Maps cluster_name -> {'x', 'y', 'width', 'height'}

        # Sort clusters by level (deepest first) to process children before parents
        sorted_clusters = sorted(cluster_id_map.items(), key=lambda x: x[1]["level"], reverse=True)

        padding = 40
        label_height = 60

        for clust_id, info in sorted_clusters:
            cluster_name = info["name"]

            # Find all direct children (nodes and sub-clusters)
            child_bounds = []

            # Check all cells to see if they belong to this cluster
            for cell_id, parent_cluster in cell_to_parent_cluster.items():
                if parent_cluster == cluster_name and cell_id in cell_geometries:
                    cell_geom = cell_geometries[cell_id]
                    child_bounds.append(
                        {
                            "min_x": cell_geom["x"],
                            "min_y": cell_geom["y"],
                            "max_x": cell_geom["x"] + cell_geom["width"],
                            "max_y": cell_geom["y"] + cell_geom["height"],
                        }
                    )

            # Also include any child clusters that have already been processed
            for child_cluster_name, child_bounds_data in cluster_bounds.items():
                # Find the cluster info for this child
                for check_id, check_info in cluster_id_map.items():
                    if check_info["name"] == child_cluster_name and check_info["parent"] == cluster_name:
                        child_bounds.append(
                            {
                                "min_x": child_bounds_data["x"],
                                "min_y": child_bounds_data["y"],
                                "max_x": child_bounds_data["x"] + child_bounds_data["width"],
                                "max_y": child_bounds_data["y"] + child_bounds_data["height"],
                            }
                        )
                        break

            if child_bounds:
                # Calculate bounding box that contains all children
                min_x = min(b["min_x"] for b in child_bounds)
                min_y = min(b["min_y"] for b in child_bounds)
                max_x = max(b["max_x"] for b in child_bounds)
                max_y = max(b["max_y"] for b in child_bounds)

                # Apply padding and label space
                cluster_bounds[cluster_name] = {
                    "x": min_x - padding,
                    "y": min_y - padding - label_height,
                    "width": (max_x - min_x) + 2 * padding,
                    "height": (max_y - min_y) + 2 * padding + label_height,
                }
                logger.debug(
                    f"Calculated bounds for '{cluster_name}': x={cluster_bounds[cluster_name]['x']:.1f}, y={cluster_bounds[cluster_name]['y']:.1f}, w={cluster_bounds[cluster_name]['width']:.1f}, h={cluster_bounds[cluster_name]['height']:.1f}"
                )

        # Map cluster names back to clust IDs
        cluster_geoms = {}
        for clust_id, info in cluster_id_map.items():
            if info["name"] in cluster_bounds:
                cluster_geoms[clust_id] = cluster_bounds[info["name"]]

        logger.info(f"Recalculated geometry for {len(cluster_geoms)} clusters to ensure proper visual containment")

        # Icons of every DOT node, used to restore the icon of node cells the
        # converter emitted without one (Requirement 8.6).
        node_icons = _dot_node_icons(dot_source)
        icon_data_cache: Dict[str, Optional[str]] = {}

        # Change decoration of every DOT node, used to re-apply the border and
        # the background the converter drops on icon cells (Requirement 8.7).
        node_decorations = _dot_node_decorations(dot_source)

        # Change decoration of every VNet and subnet cluster, used to re-apply the
        # border and the background over the fixed container style built below.
        # The cells are matched by label text, not by the positional `clustN` map:
        # a cluster the render pass re-opens is one cell but several DOT blocks.
        cluster_decorations = _dot_cluster_decorations(dot_source)
        cluster_label_texts = _dot_cluster_label_texts(dot_source)

        # Second pass: Update styling and geometry for cluster cells
        # IMPORTANT: Keep parent relationships flat (as set by graphviz2drawio) to preserve positioning
        # Only update visual styles (colors, fonts, icons)
        for cell in root.findall(".//mxCell"):
            cell_id = cell.get("id", "")

            if cell_id in cluster_id_map:
                # This is a cluster cell
                cluster_info = cluster_id_map[cell_id]
                bgcolor = cluster_info["bgcolor"]

                # Mark as container so it can hold child elements in Draw.io
                cell.set("vertex", "1")
                cell.set("connectable", "1")
                cell.set("container", "1")

                # DO NOT CHANGE PARENT - Keep graphviz2drawio's flat structure for proper positioning
                # The hierarchy is achieved through visual nesting in the diagram

                # Get existing style - preserve icon if present
                original_style = cell.get("style", "")

                # Extract icon/image from original style (graphviz2drawio already converted it to base64)
                icon_match = re.search(r"image=([^;]+)", original_style)
                icon_data = icon_match.group(1) if icon_match else None

                # If no icon in the style, graphviz2drawio failed to convert it (nested cluster bug)
                # Extract from DOT source and manually convert to base64
                if not icon_data:
                    cluster_name = cluster_info["name"]
                    if "vnet" in cluster_name.lower() or "subnet" in cluster_name.lower():
                        # Search for icon path in DOT source
                        cluster_pattern = rf'subgraph\s+["\']?{re.escape(cluster_name)}["\']?\s*\{{[^}}]*?<img\s+src=["\']([^"\']+)["\']'
                        cluster_match = re.search(cluster_pattern, dot_source, re.DOTALL)
                        if cluster_match:
                            icon_path = cluster_match.group(1)
                            cluster_type = "VNet" if "vnet" in cluster_name.lower() else "Subnet"

                            # Manually convert icon file to base64
                            try:
                                import base64

                                with open(icon_path, "rb") as icon_file:
                                    icon_bytes = icon_file.read()
                                    icon_b64 = base64.b64encode(icon_bytes).decode("utf-8")
                                    icon_data = f"data:image/png,{icon_b64}"
                                    logger.debug(
                                        f"Manually converted {cluster_type} icon to base64 for {cell_id}: {icon_path}"
                                    )
                            except Exception as e:
                                logger.warning(f"Failed to read/convert icon {icon_path}: {e}")
                                icon_data = None

                # Create proper container style with increased left spacing for larger icons
                style = "verticalAlign=top;align=left;spacingLeft=140;html=1;rounded=0;labelBackgroundColor=none;strokeColor=black;strokeWidth=1;dashed=0;whiteSpace=wrap;"

                # Add icon if we found one (already in base64 from graphviz2drawio OR manually converted)
                # Increase icon size for cluster titles and add more spacing to prevent overlap with text
                if icon_data:
                    style += f"image={icon_data};imageAlign=left;imageVerticalAlign=top;imageWidth=110;imageHeight=110;spacingTop=20;spacingLeft=140;"
                    logger.debug(f"Added larger icon to {cell_id}")

                # Apply background color to the style attribute
                # Special case: cluster_parent should be transparent (no fill)
                if cluster_info["name"] == "cluster_parent":
                    # Remove any existing fillColor and opacity settings
                    style = re.sub(r"fillColor=[^;]*;?", "", style)
                    style = re.sub(r"fillOpacity=[^;]*;?", "", style)
                    # Make it transparent with no fill
                    style += "fillColor=none;fillOpacity=0;"
                    logger.debug(f"Set {cell_id} (cluster_parent) to transparent background")
                elif bgcolor:
                    # Apply the specified background color
                    hex_color = COLOR_MAP.get(bgcolor, bgcolor)  # Use COLOR_MAP or raw value
                    # Remove any existing fillColor and opacity settings
                    style = re.sub(r"fillColor=[^;]*;?", "", style)
                    style = re.sub(r"fillOpacity=[^;]*;?", "", style)
                    # Add new fillColor with full opacity (100)
                    style += f"fillColor={hex_color};fillOpacity=100;"
                    logger.debug(f"Applied bgcolor {bgcolor} ({hex_color}) to {cell_id}")

                # Restore the change decoration of a VNet or subnet cluster: the
                # container style above hardcodes a black one-point border, which
                # would drop the Change_Style the DOT cluster carries. The colour
                # tokens are re-applied here so the exported diagram shows the same
                # change state as the rendered image (Requirements 8.6, 8.7).
                cluster_decoration = _resolve_cluster_decoration(
                    _MARKUP_RE.sub("", html.unescape(cell.get("value", ""))),
                    cluster_decorations,
                    cluster_label_texts,
                )
                if cluster_decoration:
                    style = _apply_drawio_style_keys(style, cluster_decoration)
                    logger.debug(f"Restored change decoration for {cell_id}: {cluster_decoration}")

                cell.set("style", style)

                # Increase cluster title font size and make bold (20px instead of 14px)
                label = cell.get("value", "")
                if label:
                    # Replace font-size with larger size and add bold
                    label = re.sub(r"font-size:\s*\d+(\.\d+)?px", "font-size: 30px; font-weight: bold", label)
                    cell.set("value", label)
                    logger.debug(f"Adjusted font size for {cell_id} label")

                # Apply recalculated geometry to ensure clusters visually contain their children
                geom = cell.find("mxGeometry")
                if geom is not None and cell_id in cluster_geoms:
                    geom.set("as", "geometry")
                    new_geom = cluster_geoms[cell_id]
                    geom.set("x", str(new_geom["x"]))
                    geom.set("y", str(new_geom["y"]))
                    geom.set("width", str(new_geom["width"]))
                    geom.set("height", str(new_geom["height"]))
                    logger.debug(f"Applied geometry to {cell_id} for visual containment")

            elif cell_id.startswith("node"):
                # Fix node label positioning: place labels BELOW icons with CLOSE spacing
                # graphviz2drawio generates nodes with verticalLabelPosition=top and sometimes
                # BOTH verticalAlign=top AND verticalAlign=bottom (last one wins)
                # We need: verticalLabelPosition=bottom + verticalAlign=top for close spacing
                style = cell.get("style", "")

                # Restore a dropped icon: a label carrying a visible border (the
                # Change_Style decoration) makes graphviz2drawio read the node as
                # a shape with an HTML label, so it emits no shape=image and no
                # icon. The icon is in the DOT node attributes either way, so it
                # is re-attached here, exactly as the cluster branch above does
                # for nested clusters (Requirement 8.6).
                node_value = cell.get("value", "")
                if "image=" not in style:
                    node_name = _resolve_node_key(node_value, node_icons)
                    for icon_path in node_icons.get(node_name, []):
                        icon_data = _icon_data_uri(icon_path, icon_data_cache)
                        if icon_data:
                            style = _NODE_ICON_STYLE.format(icon=icon_data) + style
                            logger.debug(f"Restored icon for {cell_id} ({node_name}) from {icon_path}")
                            break

                # Restore the change decoration: graphviz2drawio reads a node
                # carrying an icon as a pure image cell and emits
                # strokeColor=none;fillColor=none, which drops the coloured
                # border and the tinted background the DOT node carries. They are
                # re-applied here so the exported diagram shows the same change
                # state as the rendered image (Requirement 8.7).
                node_name = _resolve_node_key(node_value, node_decorations)
                decoration = node_decorations.get(node_name)
                if decoration:
                    style = _apply_drawio_style_keys(style, decoration)
                    logger.debug(f"Restored change decoration for {cell_id} ({node_name}): {decoration}")

                # Always fix nodes (whether they had top or bottom originally)
                # Step 1: Change label position to bottom
                style = style.replace("verticalLabelPosition=top", "verticalLabelPosition=bottom")
                # Step 2: Remove ALL verticalAlign occurrences
                style = re.sub(r"verticalAlign=[^;]+;?", "", style)
                # Step 3: Add single verticalAlign=top at the end (keeps icon at top for close spacing)
                if not style.endswith(";"):
                    style += ";"
                style += "verticalAlign=top;"
                cell.set("style", style)
                logger.debug(f"Fixed label position for {cell_id} (label below icon, close spacing)")

        # Fix missing edges: graphviz2drawio skips edges with lhead/ltail attributes (cluster connections)
        # Parse DOT source to find these edges and manually add them to DrawIO
        missing_edge_count = 0
        edge_id_counter = 1000  # Start with high number to avoid conflicts

        # Find the highest existing edge ID
        for cell in root.findall(".//mxCell"):
            cell_id = cell.get("id", "")
            if cell_id.startswith("edge"):
                try:
                    num = int(cell_id[4:])
                    edge_id_counter = max(edge_id_counter, num + 1)
                except:
                    pass

        # Join multi-line edge definitions in DOT source
        dot_single_line = " ".join(lines)

        # Parse edges from DOT source (now as single line)
        # Match: "source" -> "target" [attributes] or source -> target [attributes]
        edge_pattern = r'(["\'][^"\']+["\']|[a-zA-Z0-9_-]+)\s*->\s*(["\'][^"\']+["\']|[a-zA-Z0-9_-]+)\s*\[([^\]]+)\]'
        for edge_match in re.finditer(edge_pattern, dot_single_line):
            source_dot_name = edge_match.group(1).strip().strip("\"'")
            target_dot_name = edge_match.group(2).strip().strip("\"'")
            attributes = edge_match.group(3)

            # Check if this edge has lhead or ltail (cluster connection)
            lhead_match = re.search(r"lhead\s*=\s*([a-zA-Z0-9_-]+)", attributes)
            ltail_match = re.search(r"ltail\s*=\s*([a-zA-Z0-9_-]+)", attributes)

            if lhead_match or ltail_match:
                # Skip invisible layout edges (style=invis) — these exist only for
                # Graphviz ranking/ordering and must NOT appear in DrawIO
                style_val = re.search(r"style\s*=\s*(\w+)", attributes)
                if style_val and style_val.group(1) == "invis":
                    continue

                # This is a visible cluster connection edge that graphviz2drawio likely skipped
                # Find the corresponding XML node IDs
                source_xml_id = None
                target_xml_id = None

                # Handle ltail (source is inside a cluster)
                if ltail_match:
                    ltail_cluster = ltail_match.group(1)
                    source_xml_id = parent_to_id.get(ltail_cluster)
                else:
                    # Normal source node lookup
                    for xml_node_id, dot_name in xml_node_to_dot_name.items():
                        if dot_name == source_dot_name:
                            source_xml_id = xml_node_id
                            break

                # Handle lhead (target is inside a cluster)
                if lhead_match:
                    lhead_cluster = lhead_match.group(1)
                    target_xml_id = parent_to_id.get(lhead_cluster)
                else:
                    # Normal target node lookup
                    for xml_node_id, dot_name in xml_node_to_dot_name.items():
                        if dot_name == target_dot_name:
                            target_xml_id = xml_node_id
                            break

                if source_xml_id and target_xml_id:
                    # Check if this edge already exists
                    edge_exists = False
                    for existing_cell in root.findall(".//mxCell"):
                        if (
                            existing_cell.get("source") == source_xml_id
                            and existing_cell.get("target") == target_xml_id
                        ):
                            edge_exists = True
                            break

                    if not edge_exists:
                        # Create new edge element
                        edge_id = f"edge{edge_id_counter}"
                        edge_id_counter += 1

                        # Build style from DOT attributes
                        style_parts = ["html=1", "rounded=0"]

                        # Parse color
                        color_match = re.search(r"color\s*=\s*([a-zA-Z0-9#]+)", attributes)
                        if color_match:
                            color = color_match.group(1)
                            # Convert named colors to hex
                            color_map = {"royalblue2": "#5B9BD5", "black": "#000000", "red": "#FF0000"}
                            hex_color = color_map.get(color, color if color.startswith("#") else "#000000")
                            style_parts.append(f"strokeColor={hex_color}")

                        # Parse penwidth
                        penwidth_match = re.search(r"penwidth\s*=\s*([0-9.]+)", attributes)
                        if penwidth_match:
                            width = penwidth_match.group(1)
                            style_parts.append(f"strokeWidth={width}")

                        # Parse style (solid/dashed)
                        style_match = re.search(r"style\s*=\s*([a-zA-Z]+)", attributes)
                        if style_match and style_match.group(1) == "dashed":
                            style_parts.append("dashed=1")
                        else:
                            style_parts.append("dashed=0")

                        # Arrow style
                        style_parts.append("endArrow=block")
                        style_parts.append("endFill=1")

                        edge_style = ";".join(style_parts) + ";"

                        # Determine actual target (cluster if lhead present)
                        final_target: Optional[str] = target_xml_id
                        if lhead_match:
                            cluster_name = lhead_match.group(1)
                            target_cluster_id = parent_to_id.get(cluster_name)
                            if target_cluster_id:
                                final_target = target_cluster_id

                        if final_target is None:
                            continue

                        # Create edge cell
                        root_elem = root.find(".//root")
                        if root_elem is None:
                            continue
                        edge_cell = ET.SubElement(root_elem, "mxCell")
                        edge_cell.set("id", edge_id)
                        edge_cell.set("style", edge_style)
                        edge_cell.set("parent", "1")
                        edge_cell.set("source", source_xml_id)
                        edge_cell.set("target", final_target)
                        edge_cell.set("edge", "1")

                        # Add geometry for cluster border attachment
                        geom = ET.SubElement(edge_cell, "mxGeometry")
                        geom.set("relative", "1")
                        geom.set("as", "geometry")

                        # If targeting a cluster, attach to its border
                        if final_target.startswith("clust"):
                            geom.set("entryPerimeter", "1")
                            geom.set("entryX", "0")
                            geom.set("entryY", "0.5")

                        # Extract and add xlabel (edge label) if present
                        xlabel_match = re.search(r'xlabel\s*=\s*["\']([^"\']+)["\']', attributes)
                        if xlabel_match:
                            label_text = xlabel_match.group(1)
                            edge_cell.set(
                                "value",
                                f'<font style="font-size: 14.0px;" face="Times,serif" color="#000000">{label_text}</font>',
                            )

                        missing_edge_count += 1
                        logger.debug(f"Added missing cluster edge {edge_id}: {source_xml_id} -> {final_target}")

        if missing_edge_count > 0:
            logger.info(f"✓ Added {missing_edge_count} missing cluster edges (graphviz2drawio limitation workaround)")

        # Clean up broken edges from graphviz2drawio:
        # - Edges with empty/missing target (graphviz2drawio loses target on lhead edges)
        # - Edges connected to invisible helper nodes (label="-", no real content)
        graph_root = root.find(".//root")
        if graph_root is not None:
            # Identify invisible helper node IDs (nodes with value "-" or empty)
            invisible_ids = set()
            for cell in graph_root.findall("mxCell"):
                if cell.get("vertex") == "1":
                    val = cell.get("value", "").strip()
                    # Match nodes that are invisible helpers: value is "-" or empty
                    # with invisible-like styling (no fill, no stroke, zero-size)
                    if val in ("-", ""):
                        cell_style = cell.get("style", "")
                        if (
                            "fillColor=none" in cell_style
                            or "strokeColor=none" in cell_style
                            or "opacity=0" in cell_style
                            or val == "-"
                        ):
                            invisible_ids.add(cell.get("id", ""))

            cells_to_remove = []
            for cell in graph_root.findall("mxCell"):
                if cell.get("edge") == "1":
                    src = cell.get("source", "")
                    tgt = cell.get("target", "")

                    # Remove edges with empty target (broken by graphviz2drawio)
                    if not tgt:
                        cells_to_remove.append(cell)
                        continue

                    # Remove edges connected to invisible helper nodes
                    if src in invisible_ids or tgt in invisible_ids:
                        cells_to_remove.append(cell)
                        continue

            # Also remove orphaned child cells (labels) of removed edges
            removed_ids = {c.get("id") for c in cells_to_remove}
            for cell in graph_root.findall("mxCell"):
                if cell.get("parent", "") in removed_ids and cell not in cells_to_remove:
                    cells_to_remove.append(cell)

            for cell in cells_to_remove:
                try:
                    graph_root.remove(cell)
                except ValueError:
                    pass

            if cells_to_remove:
                logger.info(f"✓ Cleaned {len(cells_to_remove)} broken/invisible edges from DrawIO XML")

        # Convert back to string
        fixed_xml = ET.tostring(root, encoding="unicode")
        logger.info(f"✓ Fixed cluster hierarchy for Draw.io (clusters + nodes + colors)")
        return fixed_xml

    except Exception as e:
        logger.warning(f"Could not fix cluster hierarchy: {e}")
        logger.debug(f"Hierarchy fix error details:", exc_info=True)
        return xml_content


def parse_dependency_string(dependency_str: str, current_resource_group: str) -> tuple[str, str, str]:
    """
    Parse dependency string from ARM template to extract resource info.

    Args:
        dependency_str: The dependency string from ARM template
        current_resource_group: Default resource group name

    Returns:
        Tuple of (dependency_name, dependency_type, dependency_rg)
    """
    import re

    try:
        # Handle format() function with subnet references
        # Example: [format('{0}/subnets/WebAppSubnet', resourceId('Microsoft.Network/virtualNetworks', variables('vnetName')))]
        if "format(" in dependency_str and "/subnets/" in dependency_str:
            subnet_match = re.search(r'/subnets/([^\'",}]+)', dependency_str)
            if subnet_match:
                subnet_name = subnet_match.group(1)
                return subnet_name, "Microsoft.Network/virtualNetworks/subnets", current_resource_group

        # Handle resourceId function format: [resourceId('type', 'name', ...)]
        if "resourceId(" in dependency_str:
            # Extract the arguments from resourceId function
            match = re.search(r"resourceId\([^)]+\)", dependency_str)
            if match:
                resource_id_call = match.group(0)

                # Use regex to extract quoted strings and function calls
                # This handles both 'literal' and variables('name') formats
                arg_pattern = r"'([^']+)'|variables\('([^']+)'\)|parameters\('([^']+)'\)"
                args = re.findall(arg_pattern, resource_id_call)

                # Flatten the captured groups
                parsed_args = []
                for groups in args:
                    for group in groups:
                        if group:  # Only add non-empty groups
                            parsed_args.append(group)

                if len(parsed_args) >= 2:
                    dependency_type = parsed_args[0]  # First argument is always the type

                    # Handle different resourceId formats
                    if dependency_type == "Microsoft.Network/virtualNetworks/subnets":
                        # For subnets: resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, subnetName)
                        if len(parsed_args) >= 3:
                            dependency_name = parsed_args[2]  # Third argument is subnet name
                        else:
                            dependency_name = parsed_args[1]  # Fallback to second argument
                    elif dependency_type == "Microsoft.Sql/servers/databases":
                        # For SQL databases: resourceId('Microsoft.Sql/servers/databases', serverName, databaseName)
                        # Use the server name as the primary dependency
                        dependency_name = parsed_args[1]  # Second argument is server name
                    else:
                        dependency_name = parsed_args[1]  # Second argument is the resource name

                    # Try to extract resource group from dependency string
                    dependency_rg = current_resource_group  # Default fallback

                    # Check if we have more arguments that might be resource group
                    # Format: resourceId('subscriptionId', 'resourceGroupName', 'type', 'name')
                    if len(parsed_args) >= 4:
                        # If we have 4+ args, the pattern might be (rg, type, name, ...)
                        # But typically it's (type, name, ...) so stick with default
                        pass

                    return dependency_name, dependency_type, dependency_rg

        # Handle old format with direct string splitting (fallback)
        if "'" in dependency_str:
            parts = dependency_str.split("'")
            if len(parts) >= 4:
                dependency_type = parts[1]
                dependency_name = parts[3]
                dependency_rg = parts[7] if len(parts) > 7 else current_resource_group
                return dependency_name, dependency_type, dependency_rg

        # Handle direct resource name references (fallback)
        logger.warning(f"Could not parse dependency format: {dependency_str}, treating as direct resource reference")
        return dependency_str, "Unknown", current_resource_group

    except Exception as e:
        logger.error(
            f"Failed to parse dependency string '{dependency_str}' in resource group '{current_resource_group}': {e}"
        )
        # Return safe defaults to prevent crashes
        return "unknown-dependency", "Unknown", current_resource_group


def _remove_stale_subnet_subgraphs(source: str, stale_subnets: set) -> str:
    """Remove subnet subgraphs and related layout edges for subnets that
    should have been hidden.  Called after all RGs are processed so that
    hidden_pe_nodes is complete.

    Handles:
    - ``subgraph cluster_subnet<name> { ... }`` blocks (including quoted names)
    - Layout edges created by ``create_subnet_edges`` that reference the stale
      subnet's invisible anchor node
    """
    import re

    for subnet_name in stale_subnets:
        esc = re.escape(subnet_name)
        # 1. Remove the subgraph block.
        #    Subnet subgraphs never contain nested subgraphs, so a single
        #    brace-depth match is safe.
        source = re.sub(r'\s*subgraph\s+["\']?cluster_subnet' + esc + r'["\']?\s*\{[^}]*\}', "", source)
        # 2. Remove layout edges FROM this subnet (source position)
        #    Format: <subnet_name> -> <target> [attrs...];
        source = re.sub(r"\n[^\n]*\b" + esc + r"\b\s*->\s*[^;]+;", "", source)
        # 3. Remove layout edges TO this subnet (target position)
        source = re.sub(r'\n[^\n]*->\s*"?' + esc + r'"?\s*\[[^;]+;', "", source)
    return source


# adapt rank between subnets subgraph
def create_subnet_edges(dot: Digraph, subnets: list, max_subnet_in_line: int, rankDebug: str) -> None:
    """
    Create invisible edges between subnet invisible nodes to control layout.
    Handles both odd and even numbers of subnets.
    """
    if not subnets:
        return

    # Remove duplicates while preserving order
    unique_subnets = list(dict.fromkeys(subnets))
    if len(unique_subnets) < max_subnet_in_line + 1:
        return
    first_subnet = unique_subnets[0]

    while len(unique_subnets) > 0:
        # the last max_subnet_in_line-1 subnets to be placed at the top of the first subnet
        if len(unique_subnets) <= max_subnet_in_line - 1:
            break
        else:
            # Create edges from first subnet to others in a balanced way
            # Fix: Ensure we don't exceed the list bounds
            end_index = min(max_subnet_in_line + 1, len(unique_subnets))
            for i in range(1, end_index):
                target_subnet = unique_subnets[i]
                dot.edge(
                    first_subnet,
                    target_subnet,
                    style=rankDebug,
                    constraint="true",
                    ltail=f"cluster_subnet{first_subnet}",
                    lhead=f"cluster_subnet{target_subnet}",
                    weight="2",
                    minlen="1",
                )
            # Fix: Ensure we don't go out of bounds when setting the new first_subnet
            next_first_index = min(max_subnet_in_line, len(unique_subnets) - 1)
            if next_first_index >= len(unique_subnets):
                break
            first_subnet = unique_subnets[next_first_index]
            unique_subnets = unique_subnets[next_first_index:]


def create_resource_group_edges(
    dot: Digraph, resource_groups: list, central_rg: str, graph_minlen: str, rankDebug: str
) -> None:
    """
    Create invisible edges from the central resource group to others.

    Args:
        dot: Graphviz diagram object
        resource_groups: List of resource group names
        central_rg: Name of the resource group with most subnets
    """
    if not central_rg or central_rg not in resource_groups:
        return

    for rg in resource_groups:
        if rg != central_rg:
            dot.edge(
                f"cluster_resource_group{central_rg}",
                f"cluster_resource_group{rg}",
                style=rankDebug,
                constraint="true",
                ltail=f"cluster_resource_group{central_rg}",
                lhead=f"cluster_resource_group{rg}",
                weight="20",
                minlen=graph_minlen,
            )


# Add a new function to format time
def format_duration(seconds: float) -> str:
    """Format duration in seconds to a human-readable string."""
    if seconds < 60:
        return f"{seconds:.1f} seconds"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f} minutes"
    else:
        hours = seconds / 3600
        return f"{hours:.1f} hours"


def generate_resource_graph(
    tenants,
    subscriptions,
    resource_groups,
    subnet_optimization,
    direction,
    tenant_minlen,
    max_subnet_in_line,
    rankDebug,
    peOptimization,
    privateDnsZonesOptimization,
    resourcesEdgeLength,
    resourceGroupsEdgeLengthListBySubscription,
    crossPeOptimization,
    discoverResourceGroups=None,
    exportDrawio=False,
    use_local_template=False,
    local_template_mode=None,
    bicep_files=None,
    parameters_files=None,
    terraform_json_files=None,
    terraform_root_dirs=None,
    terraform_var_files=None,
    change_types=None,
):
    """
    Generate Azure resource graph visualization.

    Args:
        tenants: List of tenant IDs
        subscriptions: List of subscription IDs
        resource_groups: List of resource group names
        subnet_optimization: Can be a single boolean (legacy) or a list of booleans (one per subscription).
                           When True for a subscription, subnet optimization will be enabled.
        direction: Graph direction (TB, BT, LR, RL)
        tenant_minlen: Tenant minimum length setting
        max_subnet_in_line: Maximum subnets per line
        rankDebug: Debug ranking mode
        peOptimization: Can be a single boolean (legacy) or a list of booleans (one per subscription).
                       When True for a subscription, private endpoints will be optimized for display in subnets.
        privateDnsZonesOptimization: Enable private DNS zones optimization
        resourcesEdgeLength: Edge length for resources
        resourceGroupsEdgeLengthListBySubscription: Edge length for resource groups per subscription
        crossPeOptimization: Can be a single boolean (legacy) or a list of booleans (one per subscription).
                           When True for a subscription, private endpoints without cross-resource-group
                           dependencies will be skipped from visualization.
        discoverResourceGroups: List of RG names for which discovery is enabled. Empty list or None = disabled.
        exportDrawio: If True, export the graph to Draw.io XML format in addition to PNG
        use_local_template: If True, use local Bicep template instead of Azure export
        local_template_mode: Local template input mode (`bicep`, `terraform-json`, `terraform-source`)
        bicep_files: List of paths to Bicep template files (required when use_local_template=True)
        parameters_files: List of paths to parameters files (required when use_local_template=True)
        terraform_json_files: List of Terraform `show -json` files (required when local_template_mode is `terraform-json`)
        terraform_root_dirs: List of Terraform working directories (required when local_template_mode is `terraform-source`)
        terraform_var_files: List of Terraform var files aligned to terraform_root_dirs
        change_types: Terraform plan Change_Categories to display (None = every category)
    """
    start_time = time.time()

    # ---------- Generic heartbeat: emits keepalive logs during any silent
    # period (Azure API calls, Graphviz rendering, CPU-heavy loops, etc.)
    # so that pipe-based readers (WebUI) never appear frozen.
    _heartbeat = Heartbeat(logger, "Initializing", interval=5)
    _heartbeat.__enter__()

    try:
        return _generate_resource_graph_inner(
            tenants,
            subscriptions,
            resource_groups,
            subnet_optimization,
            direction,
            tenant_minlen,
            max_subnet_in_line,
            rankDebug,
            peOptimization,
            privateDnsZonesOptimization,
            resourcesEdgeLength,
            resourceGroupsEdgeLengthListBySubscription,
            crossPeOptimization,
            discoverResourceGroups,
            exportDrawio,
            use_local_template,
            local_template_mode,
            bicep_files,
            parameters_files,
            terraform_json_files,
            terraform_root_dirs,
            terraform_var_files,
            start_time,
            _heartbeat,
            change_types,
        )
    finally:
        _heartbeat.__exit__(None, None, None)


def _generate_resource_graph_inner(
    tenants,
    subscriptions,
    resource_groups,
    subnet_optimization,
    direction,
    tenant_minlen,
    max_subnet_in_line,
    rankDebug,
    peOptimization,
    privateDnsZonesOptimization,
    resourcesEdgeLength,
    resourceGroupsEdgeLengthListBySubscription,
    crossPeOptimization,
    discoverResourceGroups,
    exportDrawio,
    use_local_template,
    local_template_mode,
    bicep_files,
    parameters_files,
    terraform_json_files,
    terraform_root_dirs,
    terraform_var_files,
    start_time,
    _heartbeat,
    change_types=None,
):
    """Inner implementation of generate_resource_graph (wrapped by heartbeat)."""

    # ── Plan_Diff_Mode state ──────────────────────────────────────────────
    # `change_index` recovers the Change_Category of a resource from
    # (name, type) at the subnet placement call site; the aggregates are the
    # single source consumed by the Legend cluster and the Change_Summary.
    # All three stay empty in Legacy_Modes.
    change_index: Dict[ChangeIndexKey, str] = {}
    aggregate_counts: Dict[str, int] = {}
    aggregate_summary: List[Any] = []

    # Register local templates FIRST if in offline mode (before any Azure calls)
    if use_local_template:
        logger.info("Registering local templates for multiple template support...")

        templates_data = []
        source_kind = "local templates"

        if local_template_mode == "bicep" and bicep_files and parameters_files:
            source_kind = "Bicep templates"
            for i, (bicep_file, parameters_file) in enumerate(zip(bicep_files, parameters_files)):
                logger.info(f"Building Bicep template {i+1}/{len(bicep_files)}: {bicep_file}")
                template_file = build_bicep_template(bicep_file, parameters_file)
                if not template_file:
                    logger.error(f"Failed to build Bicep template {i+1}: {bicep_file}")
                    return

                try:
                    with open(template_file, "r") as f:
                        template_data = json.load(f)
                    templates_data.append(template_data)
                    logger.info(
                        f"Successfully loaded template {i+1} with {len(template_data.get('resources', []))} resources"
                    )
                except Exception as e:
                    logger.error(f"Error loading template {i+1}: {str(e)}")
                    return
        elif local_template_mode == "terraform-json" and terraform_json_files:
            source_kind = "Terraform JSON files"
            for i, terraform_json_file in enumerate(terraform_json_files):
                logger.info(
                    f"Building Terraform template {i+1}/{len(terraform_json_files)} from JSON: {terraform_json_file}"
                )
                # `change_types` is a trailing optional builder parameter: it is only
                # passed when the Operator made a selection, so a run without
                # `--changeTypes` reaches the builder exactly as it did before.
                builder_kwargs = {} if change_types is None else {"change_types": change_types}
                template_file = build_terraform_template(terraform_json_file, **builder_kwargs)
                if not template_file:
                    logger.error(f"Failed to build Terraform template {i+1}: {terraform_json_file}")
                    return

                try:
                    with open(template_file, "r") as f:
                        template_data = json.load(f)
                    templates_data.append(template_data)
                    logger.info(
                        f"Successfully loaded template {i+1} with {len(template_data.get('resources', []))} resources"
                    )
                except Exception as e:
                    logger.error(f"Error loading Terraform template {i+1}: {str(e)}")
                    return

                # Plan diff state travels on the template dict itself; a plan without
                # `resource_changes` carries none, which keeps Legacy_Mode behaviour.
                change_index.update(build_change_index(template_data))
                accumulate_change_metadata(template_data, aggregate_counts, aggregate_summary)
        elif local_template_mode == "terraform-source" and terraform_root_dirs:
            source_kind = "Terraform source directories"
            terraform_builder = TerraformTemplateBuilder()
            for i, terraform_root_dir in enumerate(terraform_root_dirs):
                aligned_var_files: Optional[List[str]] = None
                if terraform_var_files and i < len(terraform_var_files) and terraform_var_files[i]:
                    aligned_var_files = [terraform_var_files[i]]

                logger.info(
                    f"Building Terraform template {i+1}/{len(terraform_root_dirs)} from source: {terraform_root_dir}"
                )
                template_file = terraform_builder.build_terraform_source(terraform_root_dir, aligned_var_files)
                if not template_file:
                    logger.error(f"Failed to build Terraform source template {i+1}: {terraform_root_dir}")
                    return

                try:
                    with open(template_file, "r") as f:
                        template_data = json.load(f)
                    templates_data.append(template_data)
                    logger.info(
                        f"Successfully loaded template {i+1} with {len(template_data.get('resources', []))} resources"
                    )
                except Exception as e:
                    logger.error(f"Error loading Terraform source template {i+1}: {str(e)}")
                    return
        else:
            logger.error(f"Unsupported or incomplete local template mode: {local_template_mode}")
            return

        # Register all templates with the Azure utility
        try:
            success = az_sdk.register_local_templates(
                templates_data=templates_data,
                resource_groups=resource_groups,
                subscriptions=subscriptions,
                tenants=tenants,
                source_kind=source_kind,
            )

            if success:
                logger.info(
                    f"Successfully registered {len(templates_data)} local templates with {len(resource_groups)} resource groups"
                )
            else:
                logger.error("Failed to register local templates")
                return

        except Exception as e:
            logger.error(f"Error registering local templates: {str(e)}")
            return

    dot = Digraph(comment="Azure Resources")
    CategoryDepth = 1

    # Snapshot the original RG count before any discovery.
    # Discovered RGs are appended to resource_groups for edge rendering
    # but must NOT be exported/scanned in the main loop.
    original_rg_count = len(resource_groups)

    # Track which subscriptions have already been processed to avoid
    # rendering the same subscription in multiple tenants.
    # A subscription belongs to exactly one Azure AD tenant; guest access
    # can make it *accessible* from other tenants, but we only render it once.
    processed_subscriptions = set()

    # Track which resource groups have been fully rendered (subgraph + nodes)
    # so that cross-RG edges only target nodes that actually exist.
    rendered_resource_groups = set()

    # Calculate total operations for progress tracking
    total_tenants = len(tenants)
    total_subscriptions = len(subscriptions)
    total_resource_groups = len(resource_groups)
    total_operations = total_tenants * total_subscriptions * total_resource_groups
    with tqdm(total=total_operations, desc="Overall Progress", position=tqdm._get_free_pos()) as tenant_pbar:
        # parent subgraph
        with dot.subgraph(name="cluster_parent") as parent_cluster:
            cross_resource_group_dependencies = {}
            hidden_pe_nodes = set()  # Track PE nodes hidden by crossPeOptimization
            stale_subnet_names: set = set()  # Subnets to remove after rendering (hidden PE cleanup)
            # Add tenants subgraph
            for tenant_id in tenants:
                # Login with tenant ID
                if not use_local_template:
                    tenant_name = login_to_tenant(tenant_id)
                else:
                    tenant_name = tenant_id
                with parent_cluster.subgraph(name="cluster_tenant" + tenant_id) as tenant:
                    tenant.attr(
                        label=f"<<TABLE border='0' cellborder='0' cellspacing='5' cellpadding='0'><TR><TD align='left' rowspan='2'><img src='{ICONS_DIR}/azure.png' scale='true'/></TD><TD align='left'>Tenant: {tenant_name}</TD></TR><TR><TD align='left'>Tenant Id: {tenant_id}</TD></TR></TABLE>>",
                        labeljust="l",
                        style="rounded,solid",
                        fontsize="40",
                        color="black",
                        bgcolor="lightcyan",
                        rankdir="TB",
                        margin="35,35",
                    )
                    # Add invisible nodes for direction control
                    if len(tenants) > 1:
                        tenant.node(
                            f"cluster_tenant{tenant_id}",
                            label="-",
                            shape="none",
                            style=rankDebug,
                            width="0",
                            height="0",
                        )
                        if tenants[0] != tenant_id:
                            dot.edge(
                                f"cluster_tenant{tenants[0]}",
                                f"cluster_tenant{tenant_id}",
                                ltail=f"cluster_tenant{tenants[0]}",
                                lhead=f"cluster_tenant{tenant_id}",
                                style=rankDebug,
                                constraint="false",
                                weight="50",
                                minlen=tenant_minlen,
                            )

                    with tqdm(
                        total=total_subscriptions,
                        desc=f"Processing Subscriptions in {tenant_name}",
                        position=tqdm._get_free_pos(),
                        leave=True,
                    ) as sub_pbar:
                        # Add subscription subgraph
                        for subscription_index, subscription_id in enumerate(subscriptions):
                            # Avoid processing the same subscription in multiple tenants.
                            # Guest access can make a subscription visible from several tenants,
                            # but it belongs to exactly one; we render it in the first tenant found.
                            if subscription_id in processed_subscriptions:
                                sub_pbar.update(1)
                                tenant_pbar.update(total_resource_groups)
                                continue
                            # Determine whether this subscription belongs to the current tenant.
                            # In live mode, ask Azure.  In template mode, check the registered
                            # subscription→tenant mapping so cross-tenant scenarios render
                            # each subscription inside the correct tenant cluster.
                            if use_local_template:
                                mapped_tenant = az_sdk.get_tenant_for_subscription(subscription_id)
                                sub_belongs_to_tenant = mapped_tenant is None or mapped_tenant == tenant_id
                            else:
                                # Pass is_multitenant so cross-tenant AuthorizationFailed
                                # noise is silenced, while real single-tenant RBAC failures
                                # still surface as WARNING (and trigger the WebUI popup).
                                sub_belongs_to_tenant = is_subscription_in_tenant(
                                    subscription_id, tenant_id, is_multitenant=(len(tenants) > 1)
                                )
                            # Initialise with safe defaults so the stale-subnet guard
                            # (after the sub_belongs_to_tenant block) never hits an
                            # UnboundLocalError when the subscription is skipped.
                            current_subnet_optimization = False
                            subnet_implicit_dependencies: dict = {}
                            if sub_belongs_to_tenant:
                                processed_subscriptions.add(subscription_id)
                                # Get the crossPeOptimization value for this specific subscription
                                current_crossPeOptimization = (
                                    crossPeOptimization[subscription_index]
                                    if isinstance(crossPeOptimization, list)
                                    else crossPeOptimization
                                )
                                # Get the peOptimization value for this specific subscription
                                current_peOptimization = (
                                    peOptimization[subscription_index]
                                    if isinstance(peOptimization, list)
                                    else peOptimization
                                )
                                # Get the subnet_optimization value for this specific subscription
                                current_subnet_optimization = (
                                    subnet_optimization[subscription_index]
                                    if isinstance(subnet_optimization, list)
                                    else subnet_optimization
                                )

                                # Dictionary to hold resources and their dependencies
                                dependencies: dict[tuple[str, str, str], list[tuple[str, str, str]]] = (
                                    {}
                                )  # Updated type hint
                                subnet_implicit_dependencies = {}
                                subnets: dict[str, list[str]] = {}
                                rg_subnet_counts = {}
                                rg_resource_counts = {}  # Reset per subscription — prevents cross-sub leak
                                vnet_lines = {}
                                is_vnet_in_subscription = False
                                with tenant.subgraph(name="cluster_subscription" + subscription_id) as subscription:
                                    subscription_name = (
                                        get_subscription_name(subscription_id)
                                        if not use_local_template
                                        else subscription_id
                                    )
                                    subscription.attr(
                                        label=f"<<TABLE border='0' cellborder='0' cellspacing='5' cellpadding='0'><TR><TD align='left' rowspan='2'><img src='{ICONS_DIR}/Subscriptions.png' scale='true'/></TD><TD align='left'>Subscription: {subscription_name}</TD></TR><TR><TD align='left'>Subscription Id: {subscription_id}</TD></TR></TABLE>>",
                                        labeljust="l",
                                        style="rounded,solid",
                                        fontsize="40",
                                        color="black",
                                        bgcolor="ivory1",
                                        rankdir="TB",
                                    )

                                    # Track cross-RG ghost resources: resources that appear in
                                    # another RG's ARM template export because they depend on a
                                    # subnet in that RG.  These ghosts must be suppressed to
                                    # avoid rendering duplicate nodes.
                                    cross_rg_ghost_resources = set()
                                    subnet_implicit_dependencies = get_subnet_implicit_dependencies(
                                        resource_groups,
                                        subscription_id,
                                        CategoryDepth,
                                        current_peOptimization,
                                        subnet_implicit_dependencies,
                                        use_local_template,
                                        bicep_files,
                                        parameters_files,
                                        subscriptions,
                                        dependencies,
                                        True,  # add_to_dependencies_dict
                                        discoverResourceGroups,
                                        original_rg_count=original_rg_count,
                                        cross_rg_ghost_resources=cross_rg_ghost_resources,
                                    )
                                    with tqdm(
                                        total=total_resource_groups,
                                        desc=f"Processing RGs in {subscription_name}",
                                        position=tqdm._get_free_pos(),
                                        leave=True,
                                    ) as rg_pbar:
                                        rg_index = 0
                                        while rg_index < len(resource_groups):
                                            resourceGroup = resource_groups[rg_index]
                                            template = None
                                            if use_local_template:
                                                # Skip resource groups that don't belong to the current subscription
                                                # (critical for cross-tenant / cross-subscription Bicep scenarios)
                                                if not is_resource_group_in_subscription(
                                                    resourceGroup, subscription_id, use_local_template
                                                ):
                                                    rg_pbar.update(1)
                                                    rg_index += 1
                                                    continue
                                                template = az_sdk.get_template_data_for_resource_group(resourceGroup)
                                                if template is None and local_template_mode == "bicep" and bicep_files and parameters_files:
                                                    # Legacy fallback: keep Bicep-only rebuilding behavior if registration did not occur.
                                                    if rg_index < len(bicep_files):
                                                        bicep_file = bicep_files[rg_index]
                                                        parameters_file = parameters_files[rg_index]
                                                    else:
                                                        bicep_file = bicep_files[-1]
                                                        parameters_file = parameters_files[-1]

                                                    logger.info(
                                                        f"Building Bicep template {rg_index + 1} for RG '{resourceGroup}': {bicep_file} with parameters: {parameters_file}"
                                                    )
                                                    output_file = build_bicep_template(bicep_file, parameters_file)
                                                    if not output_file:
                                                        logger.error("Failed to build Bicep template")
                                                        rg_pbar.update(1)
                                                        rg_index += 1
                                                        continue
                                                    logger.info(f"Built Bicep template to {output_file}")
                                                elif template is None:
                                                    logger.error(
                                                        f"No registered local template found for resource group {resourceGroup}"
                                                    )
                                                    rg_pbar.update(1)
                                                    rg_index += 1
                                                    continue
                                            else:
                                                is_discovered_rg = rg_index >= original_rg_count
                                                if is_discovered_rg:
                                                    # Discovered RG: check subscription ownership via cross-deps
                                                    # (skip is_resource_group_in_subscription which may return Forbidden)
                                                    belongs_to_this_sub = False
                                                    # ── 1. Check PE-based cross-RG dependencies ──
                                                    for _dep_src, dep_info in cross_resource_group_dependencies.items():
                                                        if not isinstance(dep_info, dict):
                                                            continue
                                                        trg_rgs = dep_info.get("target_resource_groups", [])
                                                        trg_subs = dep_info.get("target_subscriptions", [])
                                                        for i, trg in enumerate(trg_rgs):
                                                            if (
                                                                trg == resourceGroup
                                                                and (trg_subs[i] if i < len(trg_subs) else None)
                                                                == subscription_id
                                                            ):
                                                                belongs_to_this_sub = True
                                                                break
                                                        if belongs_to_this_sub:
                                                            break
                                                    # ── 2. Fallback: subnet-based discovery (cross_rg_ghost_resources)
                                                    # is populated by get_subnet_implicit_dependencies for the current
                                                    # subscription only, so any RG appearing here belongs to this sub.
                                                    if not belongs_to_this_sub and any(
                                                        ghost[2] == resourceGroup for ghost in cross_rg_ghost_resources
                                                    ):
                                                        belongs_to_this_sub = True
                                                        logger.debug(
                                                            f"Discovered RG {resourceGroup} validated via subnet "
                                                            f"dependency (cross_rg_ghost_resources)"
                                                        )
                                                    if not belongs_to_this_sub:
                                                        rg_pbar.update(1)
                                                        rg_index += 1
                                                        continue
                                                    if resourceGroup in rendered_resource_groups:
                                                        rg_pbar.update(1)
                                                        rg_index += 1
                                                        continue
                                                    logger.info(
                                                        f"Processing discovered RG: {resourceGroup} in subscription {subscription_name}"
                                                    )
                                                elif not is_resource_group_in_subscription(
                                                    resourceGroup, subscription_id, use_local_template
                                                ):
                                                    # Skip resource groups not in current subscription
                                                    rg_pbar.update(1)
                                                    rg_index += 1
                                                    continue
                                                # Export the resource group template from Azure
                                                output_file = export_resource_group_template(
                                                    subscription_id, resourceGroup
                                                )
                                                logger.info(
                                                    f"Exported template for resource group {resourceGroup} to {output_file}"
                                                )
                                                if output_file is None:
                                                    if is_discovered_rg:
                                                        logger.warning(
                                                            f"Could not export template for discovered RG {resourceGroup} — skipping"
                                                        )
                                                    else:
                                                        logger.error(
                                                            f"Failed to export template for resource group {resourceGroup} — skipping"
                                                        )
                                                    rg_pbar.update(1)
                                                    rg_index += 1
                                                    continue

                                            # Initialize and parse the template variable inside the loop
                                            try:
                                                if template is None:
                                                    with open(output_file, "r") as file:
                                                        template = json.load(file)
                                                logger.info(
                                                    f'Processing resources in {"local template" if use_local_template else f"resource group {resourceGroup}"}'
                                                )
                                            except (json.JSONDecodeError, FileNotFoundError) as e:
                                                logger.error(f"Failed to load template file {output_file}: {e}")
                                                rg_pbar.update(1)
                                                rg_index += 1
                                                continue
                                            # Extract resources and dependencies
                                            resources = template.get("resources", [])

                                            # ── Pre-fetch RG-level data ONCE (avoid redundant API calls per resource) ──
                                            _pre_t0 = time.time()
                                            if use_local_template:
                                                _cached_rg_location = "Local Template"
                                            else:
                                                logger.debug(
                                                    f"[DIAG] PRE-FETCH get_resource_group_location('{resourceGroup}') — once per RG"
                                                )
                                                _cached_rg_location = get_resource_group_location(
                                                    resourceGroup, subscription_id
                                                )
                                                if not _cached_rg_location:
                                                    _cached_rg_location = "Discovered"
                                            logger.debug(
                                                f"[DIAG] PRE-FETCH get_private_dns_zones_without_vnets('{resourceGroup}') — once per RG"
                                            )
                                            _cached_no_vnet_dns_zones = get_private_dns_zones_without_vnets(
                                                resourceGroup, subscription_id, use_local_template
                                            )
                                            # PE subnet cache is now centralized in az_sdk._pe_subnet_cache
                                            # (shared across resource_processor and graph_generator).
                                            # The local _pe_subnet_cache below acts as a fast-path for the
                                            # current RG loop to avoid dict-key construction overhead.
                                            _pe_subnet_cache: dict[str, Optional[str]] = {}
                                            logger.debug(
                                                f"[DIAG] PRE-FETCH for RG '{resourceGroup}' completed in {time.time()-_pre_t0:.3f}s (location={_cached_rg_location}, dns_zones={len(_cached_no_vnet_dns_zones) if _cached_no_vnet_dns_zones else 0})"
                                            )

                                            _heartbeat.update_phase(
                                                f"Processing {len(resources)} resources in {resourceGroup}"
                                            )
                                            with tqdm(
                                                total=len(resources),
                                                desc=f"Processing Resources in {resourceGroup}",
                                                position=tqdm._get_free_pos(),
                                                leave=False,
                                            ) as res_pbar:
                                                _res_loop_start = time.time()
                                                for _res_idx, resource in enumerate(resources):
                                                    _iter_start = time.time()
                                                    resource_type = resource["type"]
                                                    resource_raw_name = resource.get("name", "unknown")
                                                    logger.debug(
                                                        f"[DIAG] res#{_res_idx}/{len(resources)} START type={resource_type} name={resource_raw_name}"
                                                    )
                                                    # Skip resource types matching the regex patterns
                                                    if should_skip(resource_type):
                                                        res_pbar.update(1)
                                                        logger.debug(
                                                            f"[DIAG] res#{_res_idx} SKIPPED (should_skip) dt={time.time()-_iter_start:.3f}s"
                                                        )
                                                        continue
                                                    resource_type_parts = resource_type.split("/")
                                                    if (
                                                        len(resource_type_parts) <= (CategoryDepth + 1)
                                                        or resource_type == "Microsoft.Network/virtualNetworks"
                                                        or resource_type == "Microsoft.Network/virtualNetworks/subnets"
                                                    ):
                                                        if resource_type == "Microsoft.Network/virtualNetworks/subnets":
                                                            resource_name = resource["name"].split("/")[-1]
                                                        elif (
                                                            current_peOptimization
                                                            and resource_type == "Microsoft.Network/privateEndpoints"
                                                        ):
                                                            if not use_local_template:
                                                                _pe_name = resource["name"]
                                                                if _pe_name in _pe_subnet_cache:
                                                                    logger.debug(
                                                                        f"[DIAG] res#{_res_idx} get_pe_subnet CACHE HIT for '{_pe_name}'"
                                                                    )
                                                                    resource_name = (
                                                                        "privateEndpoints"
                                                                        + "-"
                                                                        + _pe_subnet_cache[_pe_name]
                                                                    )
                                                                else:
                                                                    _t0 = time.time()
                                                                    logger.debug(
                                                                        f"[DIAG] res#{_res_idx} Resolving PE subnet for '{_pe_name}' (Azure API call)..."
                                                                    )
                                                                    _pe_subnet_result = get_pe_subnet(
                                                                        _pe_name, resourceGroup, subscription_id
                                                                    )
                                                                    _pe_subnet_cache[_pe_name] = _pe_subnet_result
                                                                    resource_name = (
                                                                        "privateEndpoints" + "-" + _pe_subnet_result
                                                                    )
                                                                    logger.debug(
                                                                        f"[DIAG] res#{_res_idx} PE subnet resolved: {_pe_name} -> {_pe_subnet_result} ({time.time()-_t0:.3f}s)"
                                                                    )
                                                            else:
                                                                resource_name = (
                                                                    "privateEndpoints"
                                                                    + "-"
                                                                    + resource["properties"]["subnet"]["id"].split("/")[
                                                                        -1
                                                                    ]
                                                                )

                                                        else:
                                                            resource_name = resource["name"]
                                                    else:
                                                        res_pbar.update(1)
                                                        continue
                                                    # Initialize dependencies list for this resource
                                                    resource_key = (resource_name, resource_type, resourceGroup)
                                                    if "dependsOn" in resource:
                                                        if resource_key not in dependencies:
                                                            dependencies[resource_key] = (
                                                                []
                                                            )  # Initialize as an empty list
                                                        for dependency in resource["dependsOn"]:
                                                            try:
                                                                # Use robust dependency parsing
                                                                dependency_name, dependency_type, dependency_rg = (
                                                                    parse_dependency_string(dependency, resourceGroup)
                                                                )

                                                                if should_skip_dependency(dependency_type):
                                                                    continue

                                                                # Handle special cases for optimized resources
                                                                if (
                                                                    dependency_type
                                                                    == "Microsoft.Network/virtualNetworks/subnets"
                                                                ):
                                                                    # Keep the parsed dependency_name from parse_dependency_string
                                                                    pass
                                                                elif (
                                                                    current_peOptimization
                                                                    and dependency_type
                                                                    == "Microsoft.Network/privateEndpoints"
                                                                ):
                                                                    if dependency_name in _pe_subnet_cache:
                                                                        logger.debug(
                                                                            f"[DIAG] res#{_res_idx} dep get_pe_subnet CACHE HIT for '{dependency_name}'"
                                                                        )
                                                                        dependency_name = (
                                                                            "privateEndpoints"
                                                                            + "-"
                                                                            + _pe_subnet_cache[dependency_name]
                                                                        )
                                                                    else:
                                                                        _t0 = time.time()
                                                                        logger.debug(
                                                                            f"[DIAG] res#{_res_idx} dep CALLING get_pe_subnet('{dependency_name}') for dependency"
                                                                        )
                                                                        _dep_pe_subnet = get_pe_subnet(
                                                                            dependency_name,
                                                                            resourceGroup,
                                                                            subscription_id,
                                                                        )
                                                                        _pe_subnet_cache[dependency_name] = (
                                                                            _dep_pe_subnet
                                                                        )
                                                                        dependency_name = (
                                                                            "privateEndpoints" + "-" + _dep_pe_subnet
                                                                        )
                                                                        logger.debug(
                                                                            f"[DIAG] res#{_res_idx} dep get_pe_subnet DONE dt={time.time()-_t0:.3f}s"
                                                                        )

                                                                dependencies[resource_key].append(
                                                                    (dependency_name, dependency_type, dependency_rg)
                                                                )
                                                            except Exception as e:
                                                                logger.warning(
                                                                    f"Failed to parse dependency '{dependency}' for resource '{resource_name}': {e}"
                                                                )
                                                                continue
                                                    else:
                                                        dependencies[resource_key] = []

                                                    _t0 = time.time()
                                                    logger.debug(
                                                        f"[DIAG] res#{_res_idx} CALLING get_cross_resource_group_dependencies"
                                                    )
                                                    cross_resource_group_dependencies = (
                                                        get_cross_resource_group_dependencies(
                                                            resource,
                                                            resource_name,
                                                            resource_groups,
                                                            cross_resource_group_dependencies,
                                                            subscription_id,
                                                            resourceGroup,
                                                            discoverResourceGroups,
                                                        )
                                                    )
                                                    logger.debug(
                                                        f"[DIAG] res#{_res_idx} get_cross_resource_group_dependencies DONE dt={time.time()-_t0:.3f}s"
                                                    )

                                                    # Use pre-fetched RG location (cached before the resource loop)
                                                    resource_group_location = _cached_rg_location
                                                    with subscription.subgraph(
                                                        name="cluster_resource_group" + resourceGroup
                                                    ) as resource_group:
                                                        resource_group.attr(
                                                            label=f"<<TABLE border='0' cellborder='0' cellspacing='0' cellpadding='0'><TR><TD align='center' rowspan='2'><img src='{ICONS_DIR}/ResourceGroups.png' scale='true'/></TD><TD align='left'>Name: {resourceGroup}</TD></TR><TR><TD align='left'>Location: {resource_group_location}</TD></TR></TABLE>>",
                                                            style="rounded,solid",
                                                            fontsize="40",
                                                            color="black",
                                                            bgcolor="ghostwhite",
                                                            rankdir="TB",
                                                            ranksep="1.0",
                                                        )
                                                        # Initialize resource counters if not already done
                                                        # (rg_resource_counts is reset at subscription level)

                                                        # Count resources in this resource group
                                                        rg_resource_counts[resourceGroup] = len(
                                                            [r for r in resources if not should_skip(r["type"])]
                                                        )

                                                        # After all resource groups are processed, determine the one with most resources
                                                        max_resources_rg = (
                                                            max(rg_resource_counts.items(), key=lambda x: x[1])[0]
                                                            if rg_resource_counts
                                                            else None
                                                        )

                                                        # Only add invisible nodes to the resource group with most resources
                                                        if max_resources_rg and resourceGroup == max_resources_rg:
                                                            resource_group.node(
                                                                subscription_id + "invis2",
                                                                label="",
                                                                shape="none",
                                                                style=rankDebug,
                                                                width="0",
                                                                height="0",
                                                            )
                                                            resource_group.node(
                                                                subscription_id + "invis3",
                                                                label="",
                                                                shape="none",
                                                                style=rankDebug,
                                                                width="0",
                                                                height="0",
                                                            )

                                                        resource_group.node(
                                                            f"cluster_resource_group{resourceGroup}",
                                                            label="-",
                                                            shape="none",
                                                            style=rankDebug,
                                                            width="0",
                                                            height="0",
                                                        )
                                                        # Optionally avoid plotting PE without cross resource group dependencies.
                                                        # crossPeOptimization=True hides PEs whose service connections
                                                        # ALL point to the same resource group (no cross-RG targets).
                                                        # VNet integration alone does NOT prevent hiding — only actual
                                                        # cross-RG resource dependencies count.
                                                        if (
                                                            resource_type == "Microsoft.Network/privateEndpoints"
                                                            and current_crossPeOptimization
                                                        ):
                                                            pe_deps = cross_resource_group_dependencies.get(
                                                                resource_name, {}
                                                            )
                                                            pe_target_rgs = pe_deps.get("target_resource_groups", [])
                                                            has_cross_rg = any(
                                                                tg != resourceGroup for tg in pe_target_rgs
                                                            )
                                                            if not has_cross_rg:
                                                                logger.debug(
                                                                    f"Private Endpoint {resource_name} in resource group {resourceGroup} has no cross resource group dependencies, skipping it (crossPeOptimization=True)."
                                                                )
                                                                hidden_pe_nodes.add(
                                                                    resource_name
                                                                )  # for cross_resource_group_dependencies loop
                                                                hidden_pe_nodes.add(
                                                                    resource_name + "-" + resourceGroup
                                                                )  # for subnet_implicit_dependencies loop
                                                                dependencies.pop(resource_key, None)
                                                                res_pbar.update(1)
                                                                continue
                                                            else:
                                                                # This PE survives — undo any earlier hiding by a merged
                                                                # sibling PE (peOptimization merges multiple PEs in the
                                                                # same subnet into one resource_name; an earlier PE with
                                                                # only same-RG targets may have added the name to
                                                                # hidden_pe_nodes before this PE's cross-RG targets
                                                                # were accumulated).
                                                                hidden_pe_nodes.discard(resource_name)
                                                                hidden_pe_nodes.discard(
                                                                    resource_name + "-" + resourceGroup
                                                                )
                                                        # Add resources to the resource group subgraph
                                                        icon_path = get_icon(resource["type"])

                                                        # Use pre-fetched DNS zone list (cached before the resource loop)
                                                        no_vnet_dns_zone_list = _cached_no_vnet_dns_zones
                                                        if no_vnet_dns_zone_list:
                                                            for zone in no_vnet_dns_zone_list:
                                                                zone_icon_path = get_icon(
                                                                    "Microsoft.Network/privateDnsZones"
                                                                )
                                                                add_node_in_subgraph(
                                                                    resource_group,
                                                                    zone,
                                                                    zone,
                                                                    zone_icon_path,
                                                                    resource_type="Microsoft.Network/privateDnsZones",
                                                                )
                                                        if resource["type"] == "Microsoft.Network/virtualNetworks":
                                                            is_vnet_in_subscription = True
                                                            # get vnet CIDR
                                                            vnet_cidr = (
                                                                resource.get("properties", {})
                                                                .get("addressSpace", {})
                                                                .get("addressPrefixes", [])[0]
                                                            )
                                                            with resource_group.subgraph(
                                                                name="cluster_vnet" + resource_name
                                                            ) as vnet_subgraph:
                                                                # The VNet is a cluster, not a node, so its Change_Category
                                                                # is decorated here rather than in `add_node_in_subgraph`.
                                                                vnet_label, vnet_attributes = apply_cluster_change_style(
                                                                    f"<<TABLE border='0' cellborder='0' cellspacing='0' cellpadding='0'><TR><TD align='center' rowspan='2'><img src='{ICONS_DIR}/Virtual-Networks.png' scale='true'/></TD><TD align='left'>Name :{resource_name}</TD></TR><TR><TD align='left'>CIDR: {vnet_cidr}</TD></TR></TABLE>>",
                                                                    {
                                                                        "style": "dashed",
                                                                        "fontsize": "40",
                                                                        "color": "black",
                                                                        "bgcolor": "lightblue",
                                                                        "rankdir": "TB",  # Top to bottom direction
                                                                        "ranksep": "1.0",  # Separation between ranks
                                                                    },
                                                                    resource.get("changeCategory"),
                                                                )
                                                                vnet_subgraph.attr(label=vnet_label, **vnet_attributes)
                                                                # add empty node for rank control
                                                                vnet_subgraph.node(
                                                                    subscription_id + "invis",
                                                                    label="-",
                                                                    shape="none",
                                                                    style=rankDebug,
                                                                    width="0",
                                                                    height="0",
                                                                )
                                                                # Add Private DNS zone in the Vnet graph if they exist
                                                                # Only pass original RGs (not discovered ones) to avoid
                                                                # AuthorizationFailed errors on RGs in other subscriptions.
                                                                dns_zone_rgs = [
                                                                    rg
                                                                    for rg in resource_groups[:original_rg_count]
                                                                    if is_resource_group_in_subscription(
                                                                        rg, subscription_id, use_local_template
                                                                    )
                                                                ]
                                                                _t0 = time.time()
                                                                logger.debug(
                                                                    f"[DIAG] res#{_res_idx} Checking VNet '{resource_name}' DNS zone links across {len(dns_zone_rgs)} RG(s) (Azure API call)..."
                                                                )
                                                                dns_zone_list = is_vnet_linked_to_private_dns_zone(
                                                                    resource_name,
                                                                    dns_zone_rgs,
                                                                    subscription_id,
                                                                    use_local_template,
                                                                )
                                                                logger.debug(
                                                                    f"[DIAG] res#{_res_idx} VNet DNS zone check complete: {len(dns_zone_list)} zones linked ({time.time()-_t0:.3f}s)"
                                                                )
                                                                if dns_zone_list:
                                                                    if privateDnsZonesOptimization:
                                                                        pdz_icon_path = get_icon(
                                                                            "Microsoft.Network/privateDnsZones"
                                                                        )
                                                                        add_node_in_subgraph(
                                                                            vnet_subgraph,
                                                                            "PrivateDNSZones-" + resource_name,
                                                                            "PrivateDNSZones" + resource_name,
                                                                            pdz_icon_path,
                                                                            resource_type="Microsoft.Network/privateDnsZones",
                                                                        )
                                                                    else:
                                                                        # plot explicit DNS zones
                                                                        for zone in dns_zone_list:
                                                                            zone_icon_path = get_icon(
                                                                                "Microsoft.Network/privateDnsZones"
                                                                            )
                                                                            add_node_in_subgraph(
                                                                                vnet_subgraph,
                                                                                zone,
                                                                                zone,
                                                                                zone_icon_path,
                                                                                resource_type="Microsoft.Network/privateDnsZones",
                                                                            )
                                                                # Add Bastion Host check

                                                                _t0 = time.time()
                                                                logger.debug(
                                                                    f"[DIAG] res#{_res_idx} Checking Bastion Host for VNet '{resource_name}' (Azure API call)..."
                                                                )
                                                                bastion_name = get_bastion_host_name(
                                                                    resource_name,
                                                                    resourceGroup,
                                                                    subscription_id,
                                                                    use_local_template,
                                                                )
                                                                logger.debug(
                                                                    f"[DIAG] res#{_res_idx} Bastion check complete: {'found '+bastion_name if bastion_name else 'none'} ({time.time()-_t0:.3f}s)"
                                                                )
                                                                if bastion_name:
                                                                    bastion_icon_path = get_icon(
                                                                        "Microsoft.Network/bastionHosts"
                                                                    )
                                                                    add_node_in_subgraph(
                                                                        vnet_subgraph,
                                                                        bastion_name,
                                                                        bastion_name,
                                                                        bastion_icon_path,
                                                                        resource_type="Microsoft.Network/bastionHosts",
                                                                    )
                                                                # Count subnets for get central Resource group
                                                                subnet_count = len(
                                                                    resource.get("properties", {}).get("subnets", [])
                                                                )
                                                                rg_subnet_counts[resourceGroup] = subnet_count
                                                                # initials the subnets dict to orgnise them inside vnet
                                                                subnets[resource_name] = []
                                                                placed_in_subnet = (
                                                                    {}
                                                                )  # Track which subnet each resource node was placed in
                                                                # Pre-compute subnets with VNet integration (cross-RG + same-RG).
                                                                # Infrastructure-only resources (NSGs, route tables) don't count.
                                                                INFRA_ONLY_TYPES = {
                                                                    "Microsoft.Network/networkSecurityGroups",
                                                                    "Microsoft.Network/routeTables",
                                                                }
                                                                # Exclude subnets whose ONLY implicit dependency source is a PE
                                                                # hidden by crossPeOptimization (hidden_pe_nodes stores keys in
                                                                # the same "resource_name-resourceGroup" format used by
                                                                # subnet_implicit_dependencies).
                                                                vnet_integrated_subnets = set(
                                                                    subnet
                                                                    for key, subnet in subnet_implicit_dependencies.items()
                                                                    if key not in hidden_pe_nodes
                                                                )
                                                                for (_, res_type, _), res_deps in dependencies.items():
                                                                    if res_type not in INFRA_ONLY_TYPES:
                                                                        for dep_name, dep_type, _ in res_deps:
                                                                            if (
                                                                                dep_type
                                                                                == "Microsoft.Network/virtualNetworks/subnets"
                                                                            ):
                                                                                vnet_integrated_subnets.add(dep_name)
                                                                # Add subnets as subgraphs of the VNet
                                                                for subnet in resource.get("properties", {}).get(
                                                                    "subnets", []
                                                                ):
                                                                    subnet_name = subnet["name"]
                                                                    # get subnet CIDR
                                                                    subnet_cidr = subnet.get("properties", {}).get(
                                                                        "addressPrefix"
                                                                    )
                                                                    # plot empty subnets not in dependencies dict
                                                                    # When subnet optimization is ON, still render subnets that
                                                                    # are VNet-integrated (e.g. cross-RG PE targets).
                                                                    if subnet_name not in dependencies and (
                                                                        not current_subnet_optimization
                                                                        or subnet_name in vnet_integrated_subnets
                                                                    ):
                                                                        subnets[resource_name].append(subnet_name)
                                                                        with vnet_subgraph.subgraph(
                                                                            name="cluster_subnet" + subnet_name
                                                                        ) as subnet_subgraph:
                                                                            style_subnet_cluster(
                                                                                subnet_subgraph,
                                                                                subnet_name,
                                                                                subnet_cidr,
                                                                                resource_name,
                                                                                change_index,
                                                                            )
                                                                            subnet_subgraph.node(
                                                                                subnet_name,
                                                                                label="",
                                                                                style=rankDebug,
                                                                                shape="none",
                                                                                labelloc="b",
                                                                                imagescale="false",
                                                                                width="1.5",
                                                                                height="1.5",
                                                                                imagepos="tc",
                                                                            )
                                                                    # Add resources to the subnet subgraph
                                                                    for resource_key, deps in dependencies.items():
                                                                        subnet_resource_name = resource_key[0]
                                                                        resource_type = resource_key[1]
                                                                        resource_rg = resource_key[2]
                                                                        if deps != []:
                                                                            for dep_infos in deps:
                                                                                dep = dep_infos[0]
                                                                                dep_type = dep_infos[1]
                                                                                if dep == subnet_name:
                                                                                    # subnetOptimization: skip subnets that have no VNet
                                                                                    # integration (not referenced in subnet_implicit_dependencies).
                                                                                    # Infrastructure resources (NSGs, route tables) inside these
                                                                                    # subnets are not enough to force them visible.
                                                                                    if (
                                                                                        current_subnet_optimization
                                                                                        and subnet_name
                                                                                        not in vnet_integrated_subnets
                                                                                    ):
                                                                                        continue
                                                                                    # Skip resources from a different resource group than the VNet's RG.
                                                                                    # Those cross-RG resources get a VNet integration edge instead
                                                                                    # (via subnet_implicit_dependencies) — placing them here would
                                                                                    # duplicate them inside the subnet subgraph.
                                                                                    if resource_rg != resourceGroup:
                                                                                        continue

                                                                                    # Skip cross-RG ghost resources: these appear in the
                                                                                    # current RG's ARM export because they depend on a
                                                                                    # subnet here, but actually belong to another RG.
                                                                                    if (
                                                                                        subnet_resource_name,
                                                                                        resource_type,
                                                                                        resource_rg,
                                                                                    ) in cross_rg_ghost_resources:
                                                                                        logger.debug(
                                                                                            f"Skipping cross-RG ghost '{subnet_resource_name}' in subnet '{subnet_name}' — resource actually belongs to another RG"
                                                                                        )
                                                                                        continue
                                                                                    # for application gateways avoid the inteference of multiple subnets in dependency and only keep ( for now ) the one linked to the resource
                                                                                    # if resource_type == 'Microsoft.Network/applicationGateways':
                                                                                    #     continue

                                                                                    node_id = (
                                                                                        subnet_resource_name
                                                                                        + "-"
                                                                                        + resourceGroup
                                                                                    )
                                                                                    # Only place a resource node in one subnet (the first match)
                                                                                    if node_id in placed_in_subnet:
                                                                                        continue
                                                                                    placed_in_subnet[node_id] = (
                                                                                        subnet_name
                                                                                    )
                                                                                    subnet_resources_icon_path = (
                                                                                        get_icon(resource_type)
                                                                                    )
                                                                                    if (
                                                                                        subnet_name
                                                                                        not in subnets[resource_name]
                                                                                    ):
                                                                                        subnets[resource_name].append(
                                                                                            subnet_name
                                                                                        )
                                                                                    with vnet_subgraph.subgraph(
                                                                                        name="cluster_subnet"
                                                                                        + subnet_name
                                                                                    ) as subnet_subgraph:
                                                                                        style_subnet_cluster(
                                                                                            subnet_subgraph,
                                                                                            subnet_name,
                                                                                            subnet_cidr,
                                                                                            resource_name,
                                                                                            change_index,
                                                                                        )
                                                                                        add_node_in_subgraph(
                                                                                            subnet_subgraph,
                                                                                            node_id,
                                                                                            subnet_resource_name,
                                                                                            subnet_resources_icon_path,
                                                                                            resource_type=resource_type,
                                                                                            change_category=change_index.get(
                                                                                                (
                                                                                                    subnet_resource_name,
                                                                                                    resource_type,
                                                                                                )
                                                                                            ),
                                                                                        )
                                                                                if subnet_resource_name == subnet_name:
                                                                                    if (
                                                                                        current_subnet_optimization
                                                                                        and subnet_name
                                                                                        not in vnet_integrated_subnets
                                                                                    ):
                                                                                        continue
                                                                                    else:
                                                                                        if (
                                                                                            subnet_name
                                                                                            not in subnets[
                                                                                                resource_name
                                                                                            ]
                                                                                        ):
                                                                                            subnets[
                                                                                                resource_name
                                                                                            ].append(subnet_name)
                                                                                        with vnet_subgraph.subgraph(
                                                                                            name="cluster_subnet"
                                                                                            + subnet_name
                                                                                        ) as subnet_subgraph:
                                                                                            style_subnet_cluster(
                                                                                                subnet_subgraph,
                                                                                                subnet_name,
                                                                                                subnet_cidr,
                                                                                                resource_name,
                                                                                                change_index,
                                                                                            )
                                                                                            subnet_resources_icon_path = get_icon(
                                                                                                dep_type
                                                                                            )
                                                                                            # empty node for subnet external dependencies
                                                                                            subnet_subgraph.node(
                                                                                                subnet_name,
                                                                                                label="",
                                                                                                shape="none",
                                                                                                style=rankDebug,
                                                                                                width="0",
                                                                                                height="0",
                                                                                            )
                                                                                            # duplicate common route table icon for all subnets
                                                                                            if (
                                                                                                dep_type
                                                                                                == "Microsoft.Network/routeTables"
                                                                                            ):
                                                                                                add_node_in_subgraph(
                                                                                                    subnet_subgraph,
                                                                                                    dep
                                                                                                    + "-"
                                                                                                    + subnet_name,
                                                                                                    dep,
                                                                                                    subnet_resources_icon_path,
                                                                                                    resource_type=dep_type,
                                                                                                )
                                                                                            else:
                                                                                                add_node_in_subgraph(
                                                                                                    subnet_subgraph,
                                                                                                    dep
                                                                                                    + "-"
                                                                                                    + resourceGroup,
                                                                                                    dep,
                                                                                                    subnet_resources_icon_path,
                                                                                                    resource_type=dep_type,
                                                                                                )
                                                                        # plot empty subnet
                                                                        elif (
                                                                            deps == []
                                                                            and subnet_resource_name == subnet_name
                                                                            and subnet_resource_name
                                                                            in vnet_integrated_subnets
                                                                        ):
                                                                            with vnet_subgraph.subgraph(
                                                                                name="cluster_subnet" + subnet_name
                                                                            ) as subnet_subgraph:
                                                                                style_subnet_cluster(
                                                                                    subnet_subgraph,
                                                                                    subnet_name,
                                                                                    subnet_cidr,
                                                                                    resource_name,
                                                                                    change_index,
                                                                                )
                                                                                subnet_subgraph.node(
                                                                                    subnet_resource_name,
                                                                                    label="",
                                                                                    style=rankDebug,
                                                                                    shape="none",
                                                                                    labelloc="b",
                                                                                    imagescale="false",
                                                                                    width="1.5",
                                                                                    height="1.5",
                                                                                    imagepos="tc",
                                                                                )
                                                                # adapt rank between subnets subgraph
                                                                create_subnet_edges(
                                                                    dot,
                                                                    subnets[resource_name],
                                                                    int(max_subnet_in_line),
                                                                    rankDebug,
                                                                )
                                                                vnet_line = len(
                                                                    list(dict.fromkeys(subnets[resource_name]))
                                                                ) // int(max_subnet_in_line)
                                                                logger.info(
                                                                    f"Vnet {resource_name} has {len(list(dict.fromkeys(subnets[resource_name])))} subnets and line count is {vnet_line}"
                                                                )
                                                                vnet_lines[resource_name] = vnet_line
                                                            # progress update is handled by trailing res_pbar.update(1)
                                                        elif (
                                                            resource["type"]
                                                            == "Microsoft.Network/virtualNetworks/subnets"
                                                        ):
                                                            res_pbar.update(1)  # Update resource progress bar
                                                            continue
                                                        # avoid plotting route tables in the resource group since we have changed the node Id to include them in subnet graph
                                                        elif resource["type"] == "Microsoft.Network/routeTables":
                                                            res_pbar.update(1)  # Update resource progress bar
                                                            continue
                                                        elif (
                                                            resource["type"]
                                                            == "Microsoft.Network/networkSecurityGroups"
                                                        ):
                                                            res_pbar.update(1)  # Update resource progress bar
                                                            continue
                                                        else:
                                                            # Skip cross-RG ghost resources — they appear in this
                                                            # RG's ARM export because they depend on a resource
                                                            # here, but actually belong to another RG.
                                                            if (
                                                                resource_name,
                                                                resource["type"],
                                                                resourceGroup,
                                                            ) in cross_rg_ghost_resources:
                                                                # Clean up dependencies to avoid orphan edges
                                                                dependencies.pop(resource_key, None)
                                                                logger.debug(
                                                                    f"Suppressed cross-RG ghost node '{resource_name}' in RG '{resourceGroup}'"
                                                                )
                                                                res_pbar.update(1)
                                                                continue
                                                            add_node_in_subgraph(
                                                                resource_group,
                                                                resource_name + "-" + resourceGroup,
                                                                resource_name,
                                                                icon_path,
                                                                resource_type=resource["type"],
                                                                group=resourceGroup,
                                                                change_category=resource.get("changeCategory"),
                                                            )
                                                            # progress update is handled by trailing res_pbar.update(1)
                                                    _iter_elapsed = time.time() - _iter_start
                                                    if _iter_elapsed > 2.0:
                                                        logger.debug(
                                                            f"[DIAG] res#{_res_idx} SLOW ITERATION dt={_iter_elapsed:.3f}s type={resource_type} name={resource_raw_name}"
                                                        )
                                                    else:
                                                        logger.debug(
                                                            f"[DIAG] res#{_res_idx} END dt={_iter_elapsed:.3f}s"
                                                        )
                                                    res_pbar.update(1)  # Single update per resource iteration
                                                _total_res_elapsed = time.time() - _res_loop_start
                                                logger.debug(
                                                    f"[DIAG] Resource loop for {resourceGroup} completed: {len(resources)} resources in {_total_res_elapsed:.1f}s"
                                                )
                                            rendered_resource_groups.add(resourceGroup)
                                            if is_resource_group_not_in_all_subscriptions(
                                                resourceGroup, subscriptions, use_local_template
                                            ):
                                                logger.debug(
                                                    f"Resource group {resourceGroup} is not in all subscriptions provided — this is expected in multi-subscription setups."
                                                )
                                            rg_pbar.update(1)  # Update resource group progress bar
                                            rg_index += 1  # Increment index for while loop

                                    # get max vnet lines
                                    if vnet_lines:
                                        max_vnet_lines = max(vnet_lines.values())
                                        graph_minlen = str(max_vnet_lines)
                                    else:
                                        max_vnet_lines = 1
                                        graph_minlen = "1"
                                    # Add dependencies to the graph
                                    _heartbeat.update_phase("Adding dependency edges")
                                    for resource_key, deps in dependencies.items():
                                        resource_name = resource_key[0]
                                        resource_type = resource_key[1]
                                        resource_group = resource_key[2]
                                        # move down the resources with no dependencies
                                        # Exclude VNets (rendered as clusters, not node IDs) to avoid orphan nodes
                                        if (
                                            dependencies[resource_key] == []
                                            and resource_type != "Microsoft.Network/routeTables"
                                            and resource_type != "Microsoft.Network/networkSecurityGroups"
                                            and resource_type != "Microsoft.Network/virtualNetworks/subnets"
                                            and resource_type != "Microsoft.Network/virtualNetworks"
                                        ):
                                            dot.edge(
                                                subscription_id + "invis3",
                                                resource_name + "-" + resource_group,
                                                style=rankDebug,
                                                arrowhead="normal",
                                                penwidth="1",
                                                concentrate="true",
                                                color="black",
                                                constraint="true",
                                                minlen=graph_minlen,
                                            )  # Make edges dashed
                                        for dep_infos in deps:
                                            dep = dep_infos[0]
                                            dep_type = dep_infos[1]
                                            dep_rg = dep_infos[2]
                                            if (
                                                should_skip_dependency(resource_type)
                                                or should_skip_dependency(dep_type)
                                                or resource_type == "Microsoft.Network/virtualNetworks/subnets"
                                                or dep_type == "Microsoft.Network/virtualNetworks/subnets"
                                            ):
                                                continue
                                            else:
                                                if is_vnet_in_subscription:
                                                    dot.edge(
                                                        subscription_id + "invis",
                                                        subscription_id + "invis2",
                                                        style=rankDebug,
                                                        arrowhead="normal",
                                                        penwidth="1",
                                                        concentrate="true",
                                                        color="black",
                                                        constraint="true",
                                                        minlen="1",
                                                    )  # Make edges dashed
                                                dot.edge(
                                                    subscription_id + "invis2",
                                                    subscription_id + "invis3",
                                                    style=rankDebug,
                                                    arrowhead="normal",
                                                    penwidth="1",
                                                    concentrate="true",
                                                    color="black",
                                                    constraint="true",
                                                    minlen="1",
                                                )  # Make edges dashed
                                                # move down the dependencies having no dependencies
                                                dep_key = (dep, dep_type, dep_rg)
                                                if dep_key in dependencies and dependencies[dep_key] == []:
                                                    dot.edge(
                                                        subscription_id + "invis3",
                                                        dep + "-" + dep_rg,
                                                        style=rankDebug,
                                                        arrowhead="normal",
                                                        penwidth="1",
                                                        concentrate="true",
                                                        color="black",
                                                        constraint="true",
                                                        minlen="1",
                                                    )  # Make edges dashed
                                                else:
                                                    dot.edge(
                                                        subscription_id + "invis2",
                                                        dep + "-" + dep_rg,
                                                        style=rankDebug,
                                                        arrowhead="normal",
                                                        penwidth="1",
                                                        concentrate="true",
                                                        color="black",
                                                        constraint="true",
                                                        minlen=graph_minlen,
                                                    )  # Make edges dashed
                                                dot.edge(
                                                    resource_name + "-" + resource_group,
                                                    dep + "-" + dep_rg,
                                                    style="dashed",
                                                    arrowhead="normal",
                                                    penwidth="3",
                                                    concentrate="true",
                                                    color="black",
                                                    constraint="true",
                                                    minlen=str(resourcesEdgeLength),
                                                    weight="1",
                                                )  # Make edges dashed
                                    # Add implicit subnet dependencies
                                    for resource_name, subnet_name in subnet_implicit_dependencies.items():
                                        # Skip VNet integration edges for PEs hidden by crossPeOptimization
                                        # to prevent orphan node references that crash Graphviz.
                                        if resource_name in hidden_pe_nodes:
                                            logger.debug(
                                                f"Skipping VNet integration edge for hidden PE: {resource_name} -> {subnet_name}"
                                            )
                                            continue
                                        # Use shorter minlen to keep VNet integration edges closer to their targets
                                        dot.edge(
                                            resource_name,
                                            subnet_name,
                                            lhead=f"cluster_subnet{subnet_name}",
                                            style="solid",
                                            arrowhead="normal",
                                            penwidth="5",
                                            concentrate="true",
                                            color="royalblue2",
                                            constraint="true",
                                            minlen="1",
                                            weight="1.5",
                                            xlabel="Vnet integration",
                                            labelfontsize="20",
                                        )  # Make edges dashed

                                    # Find RG with max subnets
                                    if rg_subnet_counts:
                                        central_rg = max(rg_subnet_counts.items(), key=lambda x: x[1])
                                        # adapt rank between resource group subgraph — original RGs + discovered RGs rendered in this subscription
                                        subscription_resource_groups = [
                                            rg
                                            for rg in resource_groups[:original_rg_count]
                                            if is_resource_group_in_subscription(
                                                rg, subscription_id, use_local_template
                                            )
                                        ]
                                        # Include discovered RGs that were rendered in this subscription so they participate in layout ranking
                                        for disc_rg_name in resource_groups[original_rg_count:]:
                                            if (
                                                disc_rg_name in rendered_resource_groups
                                                and disc_rg_name not in subscription_resource_groups
                                            ):
                                                subscription_resource_groups.append(disc_rg_name)

                                        # Get the correct edge length value for this subscription
                                        subscription_index = subscriptions.index(subscription_id)

                                        # Add safety check to prevent index out of range errors
                                        if subscription_index < len(resourceGroupsEdgeLengthListBySubscription):
                                            rg_edge_length = int(
                                                resourceGroupsEdgeLengthListBySubscription[subscription_index]
                                            )
                                        else:
                                            # Use default value if the list is too short
                                            logger.warning(
                                                f"No edge length specified for subscription {subscription_id}, using default value of 4"
                                            )
                                            rg_edge_length = 4

                                        # Calculate final minlen by adding vnet lines max value and the subscription-specific edge length
                                        rg_minlen = (
                                            max(vnet_lines.values()) + rg_edge_length if vnet_lines else rg_edge_length
                                        )

                                        create_resource_group_edges(
                                            dot, subscription_resource_groups, central_rg[0], str(rg_minlen), rankDebug
                                        )
                            # Detect subnets that were rendered because of cross-RG PE
                            # implicit dependencies, but whose PEs have since been hidden
                            # by crossPeOptimization.  These subnets should not be visible
                            # when subnet optimization is ON.
                            if current_subnet_optimization and subnet_implicit_dependencies:
                                _INFRA_TYPES = {
                                    "Microsoft.Network/networkSecurityGroups",
                                    "Microsoft.Network/routeTables",
                                }
                                _truly_integrated = set(
                                    subnet
                                    for key, subnet in subnet_implicit_dependencies.items()
                                    if key not in hidden_pe_nodes
                                )
                                for (_, _rtype, _), _rdeps in dependencies.items():
                                    if _rtype not in _INFRA_TYPES:
                                        for _dname, _dtype, _ in _rdeps:
                                            if _dtype == "Microsoft.Network/virtualNetworks/subnets":
                                                _truly_integrated.add(_dname)
                                _stale = set(subnet_implicit_dependencies.values()) - _truly_integrated
                                if _stale:
                                    logger.debug(f"Stale subnets from hidden PEs: {_stale}")
                                stale_subnet_names.update(_stale)
                            sub_pbar.update(1)  # Update main progress bar
                tenant_pbar.update(1)  # Update main progress bar
            # print cross-resource group dependencies
            _heartbeat.update_phase("Cross-resource-group dependencies")
            logger.debug(f"Adding cross-resource group dependencies to the graph: {cross_resource_group_dependencies}")
            for resource_name, dependency_info in cross_resource_group_dependencies.items():
                # Skip indigo edges for PEs hidden by crossPeOptimization
                if resource_name in hidden_pe_nodes:
                    logger.debug(f"Skipping cross-RG edges for hidden PE: {resource_name}")
                    continue
                # Check if it's using the new format with targets and minlens
                if isinstance(dependency_info, dict) and "targets" in dependency_info and "minlens" in dependency_info:
                    targets = dependency_info["targets"]
                    minlens = dependency_info["minlens"]
                    source_resource_group = dependency_info["source_resource_group"]
                    target_resource_groups = dependency_info.get("target_resource_groups", [])  # Get list of target RGs

                    # Fallback for old format with single target_resource_group
                    if not target_resource_groups and "target_resource_group" in dependency_info:
                        target_resource_groups = [dependency_info["target_resource_group"]] * len(targets)

                    # Skip entirely if source RG was not rendered
                    if source_resource_group not in rendered_resource_groups:
                        logger.warning(
                            f"Skipping cross-RG edges from {resource_name} — source RG {source_resource_group} was not rendered"
                        )
                        continue

                    for i, target in enumerate(targets):
                        minlen_value = minlens[i] if i < len(minlens) else 1
                        target_resource_group = (
                            target_resource_groups[i] if i < len(target_resource_groups) else source_resource_group
                        )

                        # Only draw edge if the target RG was actually rendered;
                        # otherwise graphviz auto-creates orphan nodes at root level.
                        if target_resource_group not in rendered_resource_groups:
                            logger.warning(
                                f"Skipping cross-RG edge from {resource_name} to {target} — target RG {target_resource_group} was not rendered (discovered but not accessible)"
                            )
                            continue

                        dot.edge(
                            resource_name + "-" + source_resource_group,
                            target + "-" + target_resource_group,
                            style="solid",
                            arrowhead="normal",
                            penwidth="3",
                            concentrate="true",
                            color="indigo",
                            constraint="false",
                            weight="0",
                            minlen=str(minlen_value),
                        )

    # ── Plan_Diff_Mode reporting ──────────────────────────────────────────
    # `aggregate_counts` is non-empty exactly when a registered template
    # reported change counts, so this is the Plan_Diff_Mode condition the
    # Legend below guards on too. Legacy_Modes therefore log no Change_Summary
    # and write no sidecar (Requirements 7.1, 7.6).
    run_change_summary: Optional[ChangeSummary] = None
    if use_local_template and local_template_mode == "terraform-json" and aggregate_counts:
        run_change_summary = build_run_change_summary(aggregate_counts, aggregate_summary)
        for line in format_change_summary(run_change_summary):
            logger.info(line)

    # Legend cluster: only in Plan_Diff_Mode and only when the run rendered at
    # least one non-`unchanged` Change_Category, so Legacy_Modes and
    # all-unchanged plans emit byte-identical DOT (Requirements 5.7, 5.8).
    if (
        use_local_template
        and local_template_mode == "terraform-json"
        and aggregate_counts
        and has_rendered_changes(aggregate_counts)
    ):
        present_categories = [category for category in CHANGE_CATEGORIES if aggregate_counts.get(category, 0) > 0]
        with dot.subgraph(name="cluster_change_legend") as legend_cluster:
            legend_cluster.attr(
                label="",
                style="rounded,solid",
                color="black",
                bgcolor="white",
                margin="10",
            )
            legend_cluster.node(
                "change_legend",
                label=legend_label(present_categories, aggregate_counts),
                shape="none",
                margin="0",
                fontsize="20",
            )

    dot.attr(
        splines="ortho",
        nodesep="0.1",
        ratio="auto",
        ranksep="2",
        rankdir=direction,
        fontsize="40",
        compound="true",
        concentrate="true",
    )

    # Post-process: remove subnet subgraphs that were rendered because of
    # cross-RG PE implicit dependencies, but whose PEs have since been hidden
    # by crossPeOptimization.  This must happen after all RGs are processed
    # so that hidden_pe_nodes is complete.
    if stale_subnet_names:
        logger.info(
            f"Removing {len(stale_subnet_names)} stale subnet subgraph(s) (PE hidden by crossPeOptimization): {stale_subnet_names}"
        )
        # Get the complete DOT source, apply removals, and rebuild the Digraph
        # body from the modified source.  We replace the entire body with a
        # single entry containing the cleaned-up DOT (minus the wrapping
        # "digraph { ... }").
        full_source = dot.source
        cleaned = _remove_stale_subnet_subgraphs(full_source, stale_subnet_names)
        # Extract the inner body (between the first { and the last })
        first_brace = cleaned.index("{")
        last_brace = cleaned.rindex("}")
        inner = cleaned[first_brace + 1 : last_brace]
        dot.body.clear()
        dot.body.append(inner)

    # Save the graph to a file
    _heartbeat.update_phase("Optimizing layout")
    dot = dot.unflatten(stagger=10)

    end_time = time.time()
    duration = end_time - start_time
    formatted_duration = format_duration(duration)

    # Generate timestamp for unique filename and output folder
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = f"azure_resources_{timestamp}"
    os.makedirs(output_dir, exist_ok=True)
    output_filename = os.path.join(output_dir, f"azure_resources_{timestamp}")

    logger.info(f"Graph generation completed in {formatted_duration}!")

    # Log API cache performance stats
    try:
        cache_stats = get_api_cache_stats()
        total_cached = sum(cache_stats.values())
        if total_cached > 0:
            logger.info(f"API cache stats ({total_cached} total cached entries):")
            for cache_name, count in cache_stats.items():
                if count > 0:
                    logger.info(f"  {cache_name}: {count} entries")
    except Exception:
        pass  # Cache stats are informational only

    logger.info(f"Saving all outputs to folder: {os.path.abspath(output_dir)}")
    _heartbeat.update_phase("Rendering PNG")
    logger.info(f"Saving diagram as {output_filename}.png")
    dot.render(output_filename, format="png")

    # Change_Summary sidecar, written beside the PNG so it shares the output
    # folder and the timestamp of the diagram (Requirement 7.5). Only reached in
    # Plan_Diff_Mode, since `run_change_summary` stays None otherwise.
    if run_change_summary is not None:
        write_change_summary_sidecar(run_change_summary, output_filename)

    # Export to Draw.io XML format if requested
    if exportDrawio:
        dot_path = f"{output_filename}.dot"
        drawio_path = f"{output_filename}.drawio"

        try:
            from graphviz2drawio import graphviz2drawio

            # Save DOT file first (required - graphviz2drawio needs a file path, not string)
            with open(dot_path, "w", encoding="utf-8") as f:
                f.write(dot.source)
            logger.info(f"Saved DOT file: {os.path.abspath(dot_path)}")

            # Convert using graphviz2drawio (pass file path, not string content)
            _heartbeat.update_phase("Converting to Draw.io")
            logger.info(f"Converting to Draw.io XML format...")
            xml = graphviz2drawio.convert(dot_path)

            # Fix the hierarchy for proper nesting in Draw.io
            logger.info(f"Fixing cluster hierarchy for Draw.io nested containers...")
            xml = fix_drawio_hierarchy(dot.source, xml)

            # Save the Draw.io XML
            with open(drawio_path, "w", encoding="utf-8") as f:
                f.write(xml)

            logger.info(f"✓ Successfully exported Draw.io file: {os.path.abspath(drawio_path)}")
            logger.info(f"  DOT file: {os.path.abspath(dot_path)}")
            logger.info(f"  Draw.io XML: {os.path.abspath(drawio_path)} ({len(xml):,} bytes)")
            logger.info(f"")
            logger.info(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            logger.info(f"📝 Open the .drawio file in Draw.io:")
            logger.info(f"   https://app.diagrams.net/")
            logger.info(f"   File → Open from → Device → Select {os.path.basename(drawio_path)}")
            logger.info(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            logger.info(f"")

        except ImportError:
            logger.error("graphviz2drawio module not installed")
            logger.info("Install with: pip install graphviz2drawio")
        except (IndexError, AttributeError, KeyError) as e:
            logger.warning(f"graphviz2drawio cannot parse this complex graph: {type(e).__name__}")
            logger.info(f"DOT file saved at: {os.path.abspath(dot_path)}")
            logger.info(f"You can import the DOT file manually into Draw.io")
        except Exception as e:
            logger.error(f"Draw.io export failed: {type(e).__name__}: {e}")
            logger.info(f"DOT file available at: {os.path.abspath(dot_path)}")
            import traceback

            logger.debug(traceback.format_exc())

    # Return value for callers
    png_path = os.path.abspath(f"{output_filename}.png")

    # Cross-platform auto-open of the generated PNG (use OS default handler)
    try:
        system = platform.system().lower()
        # Detect WSL (Linux kernel on Windows) and open via Windows default handler
        is_wsl = system == "linux" and ("microsoft" in platform.uname().release.lower())
        if system.startswith("win"):
            os.startfile(png_path)  # type: ignore[attr-defined]
        elif is_wsl:
            # Convert to Windows path and open with Start-Process
            try:
                result = subprocess.run(
                    ["wslpath", "-w", png_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False
                )
                win_path = result.stdout.strip() or png_path
                subprocess.run(
                    ["powershell.exe", "-NoProfile", "-Command", f'Start-Process -FilePath "{win_path}"'], check=False
                )
            except Exception as sub_e:
                logger.warning(f"WSL open fallback failed, trying xdg-open: {sub_e}")
                subprocess.run(["xdg-open", png_path], check=False)
        elif system == "darwin":
            subprocess.run(["open", png_path], check=False)
        else:
            # On Linux desktops, prefer xdg-open; skip in headless environments
            if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
                logger.warning("No GUI display detected; skipping auto-open. File saved at: %s", png_path)
            else:
                subprocess.run(["xdg-open", png_path], check=False)
        logger.info(f"Opened diagram: {png_path}")
    except Exception as e:
        logger.warning(f"Could not open diagram automatically: {e}")

    return png_path
