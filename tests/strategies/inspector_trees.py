"""Shared Hypothesis strategies for the Interactive Resource Inspector.

Every strategy here is a **function returning a strategy**, matching the house
style of :mod:`strategies.plan_json`, so a caller can constrain the input space
(a fixed depth, a fixed Change_Category, a fixed record count) and still reuse
the shapes below. Where a shape already exists for the plan-diff feature it is
imported rather than duplicated: :func:`azurerm_resource_values`,
:func:`sensitive_masks` and :func:`plan_documents` all come from
``strategies.plan_json``.

Feature: interactive-resource-inspector
Covers Requirements 14.1, 14.3, 14.8 and 14.14.

Overview of the public strategies:

- :func:`attribute_keys` - map keys holding ``.``, dashes and non-ASCII characters.
- :func:`attribute_scalars` - the leaf values a Config_Snapshot can carry.
- :func:`attribute_trees` - Config_Snapshot trees: nested maps, lists, lists of
  maps (so index segments appear in Attribute_Paths), empty maps and empty lists.
- :func:`bounded_trees` / :func:`unbounded_trees` - the same shape inside the
  Value_Bounds (lossless round trip) and deliberately outside them.
- :func:`hostile_trees` - non-string keys, values ``json.dumps`` refuses, shared
  and cyclic references, and scalars supplied where a tree is expected.
- :func:`snapshot_pairs` - ``(before, after)`` pairs derived from one base tree so
  ``added``, ``removed``, ``changed`` and ``unchanged`` all occur per example.
- :func:`sensitivity_masks` - ``(value_tree, mask)`` pairs, reusing the plan-diff
  ``sensitive_masks()`` strategy.
- :func:`change_entries` - a Change_Category paired with ``change.before`` /
  ``change.after`` / ``after_unknown`` present, ``None`` or absent.
- :func:`inspector_record_fields` - Inspector_Record field maps, dependency-free.
- :func:`inspector_records` - the same fields materialised as
  ``core.inspector`` dataclasses (imported lazily, see the note below).
- :func:`payload_bytes` - ``(records_bytes, index)`` payloads, valid and mutated.
- :func:`markup_strings` - strings carrying markup metacharacters and injection
  payloads, for the panel-escaping property.
- :func:`svg_documents` - Graphviz-shaped SVG text with repeated ``<image>``
  elements across several ``(href, width, height, preserveAspectRatio)`` groups.

The Inspector constants are mirrored locally rather than imported, so this module
imports cleanly on its own and one strategy draw never pulls in the whole core.
:func:`inspector_records` is the single strategy that needs
:mod:`core.inspector`, and it imports it lazily inside the builder.
"""

from __future__ import annotations

import datetime
import json
import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

from hypothesis import strategies as st

# Allow importing the strategy module on its own, mirroring tests/conftest.py.
_TESTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_SRC_DIR = os.path.join(_TESTS_DIR, "..", "src")
for _path in (_SRC_DIR, _TESTS_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from core.plan_diff import CHANGE_CATEGORIES  # noqa: E402
from strategies.plan_json import (  # noqa: E402
    address_parts,
    azurerm_resource_values,
    plan_documents,
    resource_names,
    sensitive_masks,
    terraform_types,
)

__all__ = [
    "ATTRIBUTE_STATES",
    "MAX_ATTRIBUTE_ROWS",
    "MAX_SCALAR_CHARS",
    "MAX_TREE_DEPTH",
    "RECORD_KINDS",
    "REDACTION_LITERAL",
    "TRUNCATION_MARKER",
    "UNKNOWN_MARKER",
    "attribute_keys",
    "attribute_scalars",
    "attribute_trees",
    "bounded_trees",
    "change_entries",
    "hostile_trees",
    "inspector_record_fields",
    "inspector_records",
    "markup_strings",
    "payload_bytes",
    "sensitivity_masks",
    "snapshot_pairs",
    "svg_documents",
    "unbounded_trees",
    # Re-exported from strategies.plan_json for callers of this module.
    "azurerm_resource_values",
    "plan_documents",
    "sensitive_masks",
]

# ─── Mirrored Inspector constants ─────────────────────────────────────────────
# Deliberate copies of the ``src/core/inspector.py`` literals. Keeping them here
# means a strategy draw never imports the core, so the strategies stay usable in
# isolation; the values are asserted against the core's own constants by the
# bound-enforcement test rather than by a shared import.

#: The closed Attribute_State set (Requirement 7.1).
ATTRIBUTE_STATES: Tuple[str, ...] = ("added", "removed", "changed", "unchanged")

#: Row_Bound, Scalar_Bound and Depth_Bound (Requirements 12.2, 12.3, 12.4).
MAX_ATTRIBUTE_ROWS = 500
MAX_SCALAR_CHARS = 2048
MAX_TREE_DEPTH = 12

#: Markers the renderer emits verbatim (Requirements 12.3, 6.6). The Redaction
#: literal mirrors ``terraform_builder._SENSITIVE_PLACEHOLDER`` (Requirement 11.1).
TRUNCATION_MARKER = "(truncated)"
UNKNOWN_MARKER = "(known after apply)"
REDACTION_LITERAL = "(sensitive)"

#: Inspector_Record kinds the collector assigns (Requirements 4.1, 4.2, 4.3).
RECORD_KINDS: Tuple[str, ...] = ("node", "virtualNetwork", "subnet")

#: Attribute-key alphabet: dots and dashes so a key collides with the path
#: separator, plus non-ASCII characters (Requirement 5.3).
_KEY_ALPHABET = "abcXY01-._ éüñ漢"


# ─── Keys and leaves ──────────────────────────────────────────────────────────


def attribute_keys(min_size: int = 1, max_size: int = 6) -> st.SearchStrategy[str]:
    """Map keys for a Config_Snapshot, including ``.``, dashes and non-ASCII text."""
    return st.text(alphabet=_KEY_ALPHABET, min_size=min_size, max_size=max_size)


def attribute_scalars(max_text: int = 12) -> st.SearchStrategy[Any]:
    """The leaf values a Terraform value tree can carry, JSON scalars only."""
    return st.one_of(
        st.none(),
        st.booleans(),
        st.integers(min_value=-(10**6), max_value=10**6),
        st.floats(allow_nan=False, allow_infinity=False, width=32),
        st.text(max_size=max_text),
    )


# ─── Attribute trees ──────────────────────────────────────────────────────────


@st.composite
def _value_nodes(
    draw: st.DrawFn,
    depth: int,
    max_depth: int,
    max_breadth: int,
    leaves: st.SearchStrategy[Any],
) -> Any:
    """Draw one node of a value tree, never nesting past ``max_depth``.

    Recursion happens at draw time rather than through ``st.recursive`` so the
    depth is an exact bound, which is what lets :func:`bounded_trees` promise a
    tree inside the Depth_Bound and :func:`unbounded_trees` promise one outside it.
    """
    if depth >= max_depth:
        return draw(leaves)

    shape = draw(
        st.sampled_from(
            (
                "leaf",
                "leaf",
                "map",
                "list",
                "list_of_maps",
                "empty_map",
                "empty_list",
            )
        )
    )
    if shape == "leaf":
        return draw(leaves)
    if shape == "empty_map":
        return {}
    if shape == "empty_list":
        return []

    child = _value_nodes(depth + 1, max_depth, max_breadth, leaves)
    if shape == "map":
        return draw(st.dictionaries(attribute_keys(), child, max_size=max_breadth))
    if shape == "list":
        return draw(st.lists(child, max_size=max_breadth))
    # A list of maps, so zero-based index segments show up in Attribute_Paths.
    return draw(
        st.lists(
            st.dictionaries(attribute_keys(), child, min_size=1, max_size=2),
            min_size=1,
            max_size=max_breadth,
        )
    )


def attribute_trees(
    max_depth: int = 4,
    max_breadth: int = 3,
    max_text: int = 12,
    min_size: int = 0,
) -> st.SearchStrategy[Dict[str, Any]]:
    """Config_Snapshot trees: a map of nested maps, lists, lists of maps and leaves.

    The root is always a map, which is the shape ``_inspector_values_for`` hands
    to ``flatten_values``. Empty maps and empty lists appear at their own paths
    (Requirement 5.8), keys carry ``.``, dashes and non-ASCII characters, and
    lists of maps guarantee index segments in the generated Attribute_Paths.
    Nesting never exceeds ``max_depth`` levels below the root.
    """
    return st.dictionaries(
        attribute_keys(),
        _value_nodes(1, max_depth, max_breadth, attribute_scalars(max_text=max_text)),
        min_size=min_size,
        max_size=max_breadth,
    )


def bounded_trees(max_depth: int = 6, max_breadth: int = 3) -> st.SearchStrategy[Dict[str, Any]]:
    """Trees strictly inside every Value_Bound, for the lossless round trip.

    ``max_depth`` stays well under :data:`MAX_TREE_DEPTH`, the breadth keeps the
    leaf count far under :data:`MAX_ATTRIBUTE_ROWS`, and the text bound keeps
    every rendered value under :data:`MAX_SCALAR_CHARS`, so nothing a draw
    produces can trip a truncation.
    """
    return attribute_trees(max_depth=max_depth, max_breadth=max_breadth, max_text=24)


@st.composite
def _deep_trees(draw: st.DrawFn, extra_depth: int = 4) -> Dict[str, Any]:
    """A single chain nested past the Depth_Bound, alternating maps and lists."""
    levels = MAX_TREE_DEPTH + draw(st.integers(min_value=1, max_value=extra_depth))
    node: Any = draw(attribute_scalars())
    for level in range(levels):
        node = [node] if level % 2 else {f"level{level}": node}
    return {"deep": node}


@st.composite
def _long_value_trees(draw: st.DrawFn) -> Dict[str, Any]:
    """A tree holding one rendered value past the Scalar_Bound."""
    overshoot = draw(st.integers(min_value=1, max_value=64))
    filler = draw(st.sampled_from(("a", "é", "漢", '"')))
    return {
        "short": draw(attribute_scalars()),
        "long": filler * (MAX_SCALAR_CHARS + overshoot),
    }


@st.composite
def _wide_trees(draw: st.DrawFn) -> Dict[str, Any]:
    """A tree holding more leaves than the Row_Bound admits."""
    overshoot = draw(st.integers(min_value=1, max_value=40))
    leaf = draw(attribute_scalars())
    return {f"attr{index:04d}": leaf for index in range(MAX_ATTRIBUTE_ROWS + overshoot)}


def unbounded_trees() -> st.SearchStrategy[Dict[str, Any]]:
    """Trees that breach at least one Value_Bound, for the bound-enforcement property.

    Every draw exceeds the Depth_Bound, the Scalar_Bound or the Row_Bound, and
    some draws exceed more than one, so the reported Truncation_Reasons are
    observable rather than incidental.
    """
    single = st.one_of(_deep_trees(), _long_value_trees(), _wide_trees())
    combined = st.tuples(_deep_trees(), _long_value_trees()).map(
        lambda pair: {"deep": pair[0], "long": pair[1]}
    )
    return st.one_of(single, combined)


# ─── Hostile trees ────────────────────────────────────────────────────────────


class _Unserializable:
    """A value ``json.dumps`` refuses, with a stable repr for shrink output."""

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return "<_Unserializable>"


def _unserializable_values() -> st.SearchStrategy[Any]:
    """Values the JSON serializer cannot represent (Requirement 13.9)."""
    return st.one_of(
        st.just(_Unserializable()),
        st.builds(set, st.lists(st.integers(min_value=0, max_value=5), max_size=3)),
        st.just(datetime.datetime(2026, 7, 26, 14, 52, 33)),
        st.just(datetime.date(2026, 7, 26)),
        st.just(b"\x00\xffbytes"),
        st.just(complex(1, 2)),
    )


def _non_string_keys() -> st.SearchStrategy[Any]:
    """Map keys that are not strings (Requirement 13.10)."""
    return st.one_of(
        st.integers(min_value=-5, max_value=5),
        st.booleans(),
        st.none(),
        st.floats(allow_nan=False, allow_infinity=False, width=32),
        st.tuples(st.integers(min_value=0, max_value=3), st.text(max_size=2)),
    )


@st.composite
def hostile_trees(draw: st.DrawFn) -> Any:
    """Trees built to break a naive walker, for the no-unhandled-failure property.

    A draw carries some combination of: non-string map keys rendered through
    ``str(key)`` (Requirement 13.10), values ``json.dumps`` refuses
    (Requirement 13.9), one dict shared at two depths and one genuinely cyclic
    dict (Requirement 13.11), and, some of the time, a bare scalar where a tree
    is expected. Feeds Property 14 only - nothing here is round-trippable.
    """
    if draw(st.integers(min_value=0, max_value=5)) == 0:
        # A scalar, a list or ``None`` supplied where a Config_Snapshot is expected.
        return draw(st.one_of(attribute_scalars(), _unserializable_values(), st.lists(attribute_scalars(), max_size=2)))

    tree: Dict[Any, Any] = dict(draw(attribute_trees(max_depth=3, max_breadth=2)))

    if draw(st.booleans()):
        tree[draw(_non_string_keys())] = draw(st.one_of(attribute_scalars(), _unserializable_values()))
    if draw(st.booleans()):
        tree["unserializable"] = draw(_unserializable_values())
    if draw(st.booleans()):
        tree["nested_bad_keys"] = {draw(_non_string_keys()): draw(attribute_scalars())}
    if draw(st.booleans()):
        shared = dict(draw(attribute_trees(max_depth=2, max_breadth=2, min_size=1)))
        tree["shared_a"] = shared
        tree["shared_b"] = {"again": shared, "in_a_list": [shared]}
    if draw(st.booleans()):
        cyclic: Dict[str, Any] = {"name": draw(resource_names())}
        cyclic["self"] = cyclic
        cyclic["via_list"] = [cyclic]
        tree["cyclic"] = cyclic
    return tree


# ─── Snapshot pairs ───────────────────────────────────────────────────────────


@st.composite
def _derive_pair(draw: st.DrawFn, node: Any) -> Tuple[Any, Any]:
    """Derive a ``(before, after)`` pair from one node, per-key and per-leaf.

    A map key lands on both sides, on the before side only (which surfaces as
    ``removed``) or on the after side only (which surfaces as ``added``); a leaf
    either survives untouched (``unchanged``) or is mutated (``changed``).
    """
    if isinstance(node, dict) and node:
        before: Dict[Any, Any] = {}
        after: Dict[Any, Any] = {}
        for key, child in node.items():
            fate = draw(st.sampled_from(("both", "both", "before_only", "after_only")))
            child_before, child_after = draw(_derive_pair(child))
            if fate in {"both", "before_only"}:
                before[key] = child_before
            if fate in {"both", "after_only"}:
                after[key] = child_after
        return before, after

    if isinstance(node, list) and node:
        pairs = [draw(_derive_pair(item)) for item in node]
        before_list = [item for item, _ in pairs]
        after_list = [item for _, item in pairs]
        if draw(st.booleans()):
            # A shorter after list, so trailing index paths turn up as ``removed``.
            after_list = after_list[: max(0, len(after_list) - 1)]
        return before_list, after_list

    # A leaf, an empty map or an empty list: keep it, or mutate the after side.
    if draw(st.sampled_from(("same", "same", "changed"))) == "same":
        return node, node
    mutated = draw(attribute_scalars().filter(lambda value: repr(value) != repr(node)))
    return node, mutated


@st.composite
def snapshot_pairs(
    draw: st.DrawFn,
    trees: Optional[st.SearchStrategy[Dict[str, Any]]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Draw two Config_Snapshots derived from one base tree.

    Leaves are kept, dropped from one side or mutated on the after side, so a
    single example normally produces ``added``, ``removed``, ``changed`` and
    ``unchanged`` entries together instead of by luck (Requirements 7.1 to 7.5).
    """
    base = draw(trees if trees is not None else bounded_trees(max_depth=4))
    before, after = draw(_derive_pair(base))
    return (before if isinstance(before, dict) else {}), (after if isinstance(after, dict) else {})


# ─── Sensitivity and unknown masks ────────────────────────────────────────────


def sensitivity_masks(
    values: Optional[st.SearchStrategy[Dict[str, Any]]] = None,
) -> st.SearchStrategy[Tuple[Dict[str, Any], Any]]:
    """``(value_tree, mask)`` pairs, reusing the plan-diff ``sensitive_masks()``.

    The mask mirrors the tree's shape: ``True`` marks a sensitive leaf or a whole
    container, an absent key marks a value that must survive untouched, and a
    mask can be shallower than the tree it describes (Requirements 11.1 to 11.4).
    The same shape serves ``before_sensitive``, ``after_sensitive``,
    ``sensitive_values`` and ``after_unknown``.
    """
    return sensitive_masks(values=values if values is not None else azurerm_resource_values())


def _mask_for(tree: Any) -> st.SearchStrategy[Any]:
    """A mask aligned with an already-drawn ``tree``, for ``after_unknown``."""
    return sensitive_masks(values=st.just(tree)).map(lambda pair: pair[1])


# ─── Change entries ───────────────────────────────────────────────────────────


def _phase_presence() -> st.SearchStrategy[str]:
    """How one phase of a change object shows up: present, ``None`` or absent."""
    return st.sampled_from(("present", "present", "null", "absent"))


@st.composite
def change_entries(
    draw: st.DrawFn,
    categories: Optional[Sequence[str]] = None,
    types: Optional[st.SearchStrategy[str]] = None,
    allow_missing_change: bool = True,
) -> Dict[str, Any]:
    """A Change_Category paired with the change object that must drive it.

    The returned map carries the pieces ``_inspector_values_for`` consumes::

        {"address", "type", "name", "category", "values", "change"}

    ``change`` is ``None`` when the plan carries no change object at all
    (``allow_missing_change``), and each of ``before``, ``after`` and
    ``after_unknown`` is independently present, explicitly ``None`` or absent,
    which is what walks the Requirement 6.7 / 6.8 fallback branches. Sensitivity
    masks come along for both phases so redaction has something to do.
    """
    address, terraform_type, resource_name = draw(address_parts(types=types or terraform_types()))
    values = draw(azurerm_resource_values(terraform_type=terraform_type, resource_name=resource_name))
    category = draw(st.sampled_from(list(categories or CHANGE_CATEGORIES)))

    entry: Dict[str, Any] = {
        "address": address,
        "type": terraform_type,
        "name": resource_name,
        "category": category,
        "values": values,
        "change": None,
    }
    if allow_missing_change and draw(st.integers(min_value=0, max_value=4)) == 0:
        return entry

    change: Dict[str, Any] = {}
    for phase in ("before", "after"):
        presence = draw(_phase_presence())
        if presence == "absent":
            continue
        if presence == "null":
            change[phase] = None
            change[f"{phase}_sensitive"] = None
            continue
        tree, mask = draw(
            sensitivity_masks(values=azurerm_resource_values(terraform_type=terraform_type, resource_name=resource_name))
        )
        change[phase] = tree
        change[f"{phase}_sensitive"] = mask

    unknown_presence = draw(_phase_presence())
    if unknown_presence == "null":
        change["after_unknown"] = None
    elif unknown_presence == "present":
        after_tree = change.get("after")
        change["after_unknown"] = draw(_mask_for(after_tree if isinstance(after_tree, dict) else values))

    entry["change"] = change
    return entry


# ─── Inspector records ────────────────────────────────────────────────────────


@st.composite
def _attribute_entry_fields(
    draw: st.DrawFn,
    paths: Optional[st.SearchStrategy[str]] = None,
    values: Optional[st.SearchStrategy[str]] = None,
) -> Dict[str, Any]:
    """One Attribute_Entry as a field map, consistent with its Attribute_State.

    ``added`` carries no before value, ``removed`` carries no after value, and the
    marker literals turn up in place of a rendered value often enough to be
    exercised (Requirements 6.6, 11.1, 12.3).
    """
    path_strategy = paths if paths is not None else _attribute_paths()
    value_strategy = values if values is not None else _rendered_values()
    state = draw(st.sampled_from(ATTRIBUTE_STATES))
    before = None if state == "added" else draw(value_strategy)
    if state == "removed":
        after = None
    elif state == "unchanged":
        after = before
    else:
        after = draw(value_strategy)
    return {"path": draw(path_strategy), "state": state, "before": before, "after": after}


def _attribute_paths() -> st.SearchStrategy[str]:
    """Attribute_Paths as ``flatten_values`` writes them, index segments included."""
    segment = st.one_of(attribute_keys(), st.integers(min_value=0, max_value=9).map(str))
    return st.lists(segment, min_size=1, max_size=4).map(".".join)


def _rendered_values() -> st.SearchStrategy[str]:
    """Rendered leaf text, including the markers the panel prints verbatim."""
    return st.one_of(
        st.text(max_size=24),
        st.sampled_from((REDACTION_LITERAL, UNKNOWN_MARKER, f"value{TRUNCATION_MARKER}", "{}", "[]")),
        markup_strings(),
        # Multi-byte characters, embedded newlines and quotation marks, which is
        # what makes the payload round trip worth asserting (Requirement 12.8).
        st.sampled_from(('line\nbreak', 'quote"inside', "漢字éüñ", "tab\tsep", "back\\slash")),
    )


@st.composite
def inspector_record_fields(
    draw: st.DrawFn,
    kinds: Optional[Sequence[str]] = None,
    max_attributes: int = 6,
    keys: Optional[st.SearchStrategy[str]] = None,
    text_values: Optional[st.SearchStrategy[str]] = None,
) -> Dict[str, Any]:
    """One Inspector_Record as a plain field map, with no core import at all.

    Field names match the dataclass of the design's Data Models section, so a
    caller can hand the map straight to ``InspectorRecord(**fields)``. The
    ``attributes`` value is a list of Attribute_Entry field maps. Use this
    strategy when a test only needs the values; use :func:`inspector_records`
    when it needs the dataclasses.
    """
    key_strategy = keys if keys is not None else _inspector_keys()
    value_strategy = text_values if text_values is not None else _rendered_values()
    category = draw(st.one_of(st.none(), st.sampled_from(list(CHANGE_CATEGORIES))))
    entries = draw(
        st.lists(
            _attribute_entry_fields(values=value_strategy),
            max_size=max_attributes,
            unique_by=lambda fields: fields["path"],
        )
    )
    return {
        "key": draw(key_strategy),
        "kind": draw(st.sampled_from(list(kinds or RECORD_KINDS))),
        "name": draw(resource_names()),
        "resource_type": draw(
            st.sampled_from(
                (
                    "Microsoft.Web/sites",
                    "Microsoft.Network/virtualNetworks",
                    "Microsoft.Network/virtualNetworks/subnets",
                    "Microsoft.Storage/storageAccounts",
                )
            )
        ),
        "resource_group": draw(st.sampled_from(("rg-app", "rg-network", "rg-data", ""))),
        "address": draw(st.one_of(st.none(), st.text(alphabet="abc._-", min_size=1, max_size=12))),
        "change_category": category,
        "replacement": category == "replace",
        "attributes": entries,
        "omitted_attributes": draw(st.integers(min_value=0, max_value=40)),
        "truncations": draw(st.lists(st.sampled_from(("value", "depth", "rows")), max_size=3, unique=True)),
    }


def _inspector_keys() -> st.SearchStrategy[str]:
    """Inspector_Keys in the three shapes the collector produces."""
    name = resource_names(min_size=1, max_size=8)
    return st.one_of(
        st.tuples(name, st.sampled_from(("rg-app", "rg-network"))).map(lambda parts: f"{parts[0]}-{parts[1]}"),
        name.map(lambda value: f"cluster_vnet{value}"),
        name.map(lambda value: f"cluster_subnet{value}"),
    )


def _build_record(fields: Dict[str, Any]) -> Any:
    """Materialise one field map as a ``core.inspector`` record.

    The import is deliberately lazy: importing this strategy module must not pull
    in the Inspector core, so a test that only needs field maps
    (:func:`inspector_record_fields`) stays independent of it.
    """
    from core.inspector import AttributeEntry, InspectorRecord  # noqa: PLC0415

    materialised = dict(fields)
    materialised["attributes"] = [AttributeEntry(**entry) for entry in fields["attributes"]]
    return InspectorRecord(**materialised)


def inspector_records(
    kinds: Optional[Sequence[str]] = None,
    max_attributes: int = 6,
    keys: Optional[st.SearchStrategy[str]] = None,
    text_values: Optional[st.SearchStrategy[str]] = None,
) -> st.SearchStrategy[Any]:
    """Inspector_Record dataclasses, for the payload and reader properties.

    Values carry multi-byte characters, embedded newlines and quotation marks, so
    the JSONL round trip and the byte offsets in the index are asserted against
    text that actually stresses them (Requirements 12.8, 14.10).
    """
    return inspector_record_fields(
        kinds=kinds, max_attributes=max_attributes, keys=keys, text_values=text_values
    ).map(_build_record)


# ─── Payload bytes ────────────────────────────────────────────────────────────


def _record_line(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Serialise one record field map into the documented wire shape."""
    line: Dict[str, Any] = {
        "key": fields["key"],
        "kind": fields["kind"],
        "name": fields["name"],
        "resourceType": fields["resource_type"],
        "resourceGroup": fields["resource_group"],
        "address": fields["address"],
        "changeCategory": fields["change_category"],
        "replacement": fields["replacement"],
        "attributes": [
            {key: value for key, value in entry.items() if value is not None or key in {"path", "state"}}
            for entry in fields["attributes"]
        ],
        "omittedAttributes": fields["omitted_attributes"],
        "truncations": fields["truncations"],
    }
    return line


def _encode_payload(records: List[Dict[str, Any]]) -> Tuple[bytes, Dict[str, Any]]:
    """Encode field maps as ``(jsonl_bytes, index)`` with true byte offsets."""
    blob = b""
    keys: Dict[str, Any] = {}
    for fields in records:
        encoded = (json.dumps(_record_line(fields), ensure_ascii=False) + "\n").encode("utf-8")
        keys[fields["key"]] = {
            "offset": len(blob),
            "length": len(encoded) - 1,  # the line without its newline
            "kind": fields["kind"],
        }
        blob += encoded
    index = {
        "schemaVersion": 1,
        "diagram": "diagram.png",
        "records": "diagram.inspector.jsonl",
        "recordCount": len(records),
        "keyCollisions": 0,
        "keys": keys,
        "bounds": {
            "maxRows": MAX_ATTRIBUTE_ROWS,
            "maxScalarChars": MAX_SCALAR_CHARS,
            "maxDepth": MAX_TREE_DEPTH,
        },
    }
    return blob, index


@st.composite
def payload_bytes(
    draw: st.DrawFn,
    max_records: int = 4,
    mutations: bool = True,
) -> Tuple[bytes, Dict[str, Any]]:
    """``(records_bytes, index)`` payloads for the reader half of Property 14.

    One draw is either an arbitrary byte sequence with an index that describes
    nothing, or a valid payload put through one mutation: bytes deleted from the
    middle, a line truncated, or the index offsets shifted. No mutation may make
    a reader raise - returning ``None`` is the contract (Requirements 13.4, 13.5).
    """
    records = draw(
        st.lists(
            inspector_record_fields(max_attributes=3),
            min_size=1,
            max_size=max_records,
            unique_by=lambda fields: fields["key"],
        )
    )
    blob, index = _encode_payload(records)
    if not mutations:
        return blob, index

    mutation = draw(
        st.sampled_from(("none", "arbitrary", "delete_middle", "truncate_line", "shift_offsets", "garbage_line"))
    )
    if mutation == "none":
        return blob, index
    if mutation == "arbitrary":
        return draw(st.binary(max_size=64)), index
    if mutation == "delete_middle" and len(blob) > 4:
        start = draw(st.integers(min_value=1, max_value=len(blob) - 2))
        end = draw(st.integers(min_value=start + 1, max_value=len(blob) - 1))
        return blob[:start] + blob[end:], index
    if mutation == "truncate_line":
        cut = draw(st.integers(min_value=0, max_value=len(blob)))
        return blob[:cut], index
    if mutation == "shift_offsets":
        shift = draw(st.integers(min_value=-len(blob) - 8, max_value=len(blob) + 8))
        shifted = dict(index)
        shifted["keys"] = {
            key: {**entry, "offset": entry["offset"] + shift} for key, entry in index["keys"].items()
        }
        return blob, shifted
    # A line that is not JSON at all, spliced in place of a valid one.
    return blob + b"not json at all\n", index


# ─── Markup strings ───────────────────────────────────────────────────────────


#: Payloads that must arrive in the panel as text, never as live markup.
_INJECTION_PAYLOADS: Tuple[str, ...] = (
    "<script>alert(1)</script>",
    '" onclick="alert(1)',
    "' onmouseover='alert(1)",
    "<img src=x onerror=alert(1)>",
    "</td></tr><tr><td>",
    "&lt;script&gt;",
    "&amp;&quot;&#39;",
    "<svg/onload=alert(1)>",
    "{{constructor}}",
    "javascript:alert(1)",
)

_MARKUP_ALPHABET = "<>&\"'/=`{} aé漢\n"


def markup_strings(max_size: int = 24) -> st.SearchStrategy[str]:
    """Strings carrying markup metacharacters and injection payloads.

    Feeds record keys, Attribute_Paths and rendered values for Property 20: every
    one of these must come back escaped, with the Attribute_Flag_Token as the
    only markup the panel adds.
    """
    payloads = st.sampled_from(_INJECTION_PAYLOADS)
    noisy = st.text(alphabet=_MARKUP_ALPHABET, min_size=1, max_size=max_size)
    wrapped = st.tuples(st.text(max_size=6), payloads, st.text(max_size=6)).map("".join)
    return st.one_of(payloads, noisy, wrapped)


# ─── SVG documents ────────────────────────────────────────────────────────────


_SVG_HEADER = (
    '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
    '<svg width="800pt" height="600pt" viewBox="0 0 800 600" xmlns="http://www.w3.org/2000/svg"'
    ' xmlns:xlink="http://www.w3.org/1999/xlink">\n<g id="graph0" class="graph">\n'
)
_SVG_FOOTER = "</g>\n</svg>\n"


def _svg_escape(text: str) -> str:
    """Escape one generated name so the fixture stays well-formed XML."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


@st.composite
def svg_documents(
    draw: st.DrawFn,
    icon_paths: Optional[Sequence[str]] = None,
    max_nodes: int = 4,
    max_clusters: int = 2,
) -> str:
    """Graphviz-shaped SVG text with repeated ``<image>`` elements.

    Each ``g.node`` carries a ``<title>`` holding its Inspector_Key and one
    ``<image>`` drawn from a small pool of ``(href, width, height,
    preserveAspectRatio)`` groups, so several occurrences share a group and
    ``embed_svg_icons`` has something to hoist (Requirement 3.7). Clusters carry
    a filled ``<polygon>`` and their own ``<title>``, matching the hit-test
    reasoning the front end relies on. ``icon_paths`` lets a caller point the
    hrefs at real files on disk; the default hrefs are relative names.
    """
    hrefs = list(icon_paths or ("icons/webapp.png", "icons/vnet.png", "icons/storage.png"))
    groups = [
        (draw(st.sampled_from(hrefs)), size, size, ratio)
        for size, ratio in draw(
            st.lists(
                st.tuples(st.sampled_from(("16", "24", "32")), st.sampled_from(("xMidYMid meet", "none"))),
                min_size=1,
                max_size=3,
            )
        )
    ]

    parts: List[str] = [_SVG_HEADER]
    for index in range(draw(st.integers(min_value=1, max_value=max_clusters))):
        name = draw(resource_names(min_size=1, max_size=6))
        parts.append(
            f'<g id="clust{index}" class="cluster">\n'
            f"<title>cluster_vnet{_svg_escape(name)}</title>\n"
            '<polygon fill="#eef6ff" stroke="#0078D4" points="8,-8 8,-400 400,-400 400,-8 8,-8"/>\n'
            f'<text text-anchor="middle" x="200" y="-380">{_svg_escape(name)}</text>\n'
            "</g>\n"
        )

    for index in range(draw(st.integers(min_value=1, max_value=max_nodes))):
        name = draw(resource_names(min_size=1, max_size=6))
        group = draw(st.sampled_from(groups))
        href, width, height, ratio = group
        key = f"{name}-rg-app"
        parts.append(
            f'<g id="node{index}" class="node">\n'
            f"<title>{_svg_escape(key)}</title>\n"
            f'<ellipse fill="none" stroke="#333333" cx="{100 + index * 60}" cy="-200" rx="27" ry="18"/>\n'
            f'<image xlink:href="{_svg_escape(href)}" width="{width}" height="{height}"'
            f' preserveAspectRatio="{_svg_escape(ratio)}" x="{80 + index * 60}" y="-216"/>\n'
            f'<text text-anchor="middle" x="{100 + index * 60}" y="-176">{_svg_escape(name)}</text>\n'
            "</g>\n"
        )

    parts.append(_SVG_FOOTER)
    return "".join(parts)
