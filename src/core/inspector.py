"""Interactive Resource Inspector core for CloudHorus.

Pure, dependency-light module: no Graphviz, no Azure SDK, no pywebview. It owns
the Attribute_Style table, the Value_Bounds, and the data models that carry one
Inspector_Record per drawn diagram element from the Config_Snapshots of a
resource through to the Inspector_Payload written beside the PNG.

The chain is dictionary in / dictionary out, which is what keeps the property
tests cheap and the Inspector_Mode-off path untouched.
"""

import base64
import json
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Mapping,
    MutableSet,
    Optional,
    Sequence,
    Tuple,
)

from utils.logger import SingletonLogger

logger = SingletonLogger().get_logger()

#: Closed set of Attribute_States, in the canonical order the legend uses.
ATTRIBUTE_STATES: Tuple[str, ...] = ("added", "removed", "changed", "unchanged")

#: The state assigned to an Attribute_Path whose two rendered values are equal,
#: and the presentation an out-of-set state falls back to (Requirement 13.8).
UNCHANGED_STATE: str = "unchanged"

#: Attribute_State of a path present in the after Config_Snapshot only (Requirement 7.2).
ADDED_STATE: str = "added"

#: Attribute_State of a path present in the before Config_Snapshot only (Requirement 7.3).
REMOVED_STATE: str = "removed"

#: Attribute_State of a path whose two rendered values differ (Requirement 7.4).
CHANGED_STATE: str = "changed"

#: Row_Bound: Attribute_Entry values kept per Inspector_Record (Requirement 12.2).
MAX_ATTRIBUTE_ROWS: int = 500

#: Scalar_Bound: characters kept per rendered value (Requirement 12.3).
MAX_SCALAR_CHARS: int = 2048

#: Depth_Bound: levels of Config_Snapshot nesting walked (Requirement 12.4).
MAX_TREE_DEPTH: int = 12

#: Truncation_Marker appended to a bounded value and standing in for a subtree
#: dropped by the Depth_Bound or by an already-visited ancestor.
TRUNCATION_MARKER: str = "(truncated)"

#: After_Value of an Attribute_Path the plan reports as not yet known.
UNKNOWN_MARKER: str = "(known after apply)"

#: Redaction_Literal that ``TerraformTemplateBuilder._redact_sensitive`` already
#: writes in place of a value the plan marks as sensitive. The Attribute_Differ
#: only ever compares it, never produces it: redaction happens upstream, in the
#: builder, so no value the mask flags reaches this module (Requirement 11.5).
REDACTION_LITERAL: str = "(sensitive)"

#: The one Change_Category that sets the ``replacement`` marker of an
#: Inspector_Record (Requirement 4.9). The literal is the plan-diff
#: Change_Category value, kept local so this module imports nothing.
REPLACE_CATEGORY: str = "replace"

#: Closed set of Truncation_Reasons, one per Value_Bound (Requirement 12.10).
TRUNCATION_REASONS: Tuple[str, ...] = ("value", "depth", "rows")

#: Truncation_Reason of the Depth_Bound, recorded by :func:`flatten_values`.
DEPTH_REASON: str = "depth"

#: Truncation_Reason of the Scalar_Bound, recorded by :func:`render_scalar`.
VALUE_REASON: str = "value"

#: Truncation_Reason of the Row_Bound, recorded by ``apply_bounds``.
ROWS_REASON: str = "rows"

#: Suffix of the Interaction_Layer written beside the PNG (Requirement 3.6). The
#: three artifact suffixes live here rather than in the render pipeline because
#: both writers and the reader in ``cloudhorus_webui.py`` need them, and the GUI
#: host has no reason to import Graphviz to learn a filename.
INTERACTION_LAYER_SUFFIX: str = ".svg"

#: Suffix of the Inspector_Record JSONL file, one record per line.
INSPECTOR_RECORDS_SUFFIX: str = ".inspector.jsonl"

#: Suffix of the Inspector_Index, the offset map the single-record read seeks with.
INSPECTOR_INDEX_SUFFIX: str = ".inspector-index.json"

#: Version of the Inspector_Index shape, so a reader can reject a payload it does
#: not understand rather than misinterpret its offsets.
INSPECTOR_SCHEMA_VERSION: int = 1

#: Inspector kind of an element the Graph_Pipeline draws as a node.
NODE_KIND: str = "node"

#: Inspector kind of a virtual network drawn as a container (Requirement 3.5).
VNET_KIND: str = "virtualNetwork"

#: Inspector kind of a subnet drawn as a container (Requirement 3.5).
SUBNET_KIND: str = "subnet"

#: Closed set of Inspector kinds, in the order the diagram nests them.
INSPECTOR_KINDS: Tuple[str, ...] = (NODE_KIND, VNET_KIND, SUBNET_KIND)

#: Renderer type assumed for a container whose source dict carries none, which is
#: the case for a subnet read out of its parent VNet's ``properties["subnets"]``
#: list when the Renderer_Template holds no standalone subnet resource.
_KIND_FALLBACK_TYPES: Dict[str, str] = {
    VNET_KIND: "Microsoft.Network/virtualNetworks",
    SUBNET_KIND: "Microsoft.Network/virtualNetworks/subnets",
}

#: Cluster_Key prefixes, longest first, stripped to recover a container's display
#: name when its source dict carries no ``name`` (Requirement 3.5).
_CLUSTER_KEY_PREFIXES: Tuple[str, ...] = ("cluster_subnet", "cluster_vnet")

#: Keys of a Renderer_Template or Azure resource dict that carry identity or
#: wiring rather than configuration. They are excluded from the Config_Snapshot
#: the collector falls back to when a source dict carries no ``inspectorValues``,
#: which mirrors the exclusion ``TerraformTemplateBuilder`` already applies.
SOURCE_IDENTITY_KEYS: frozenset = frozenset(
    {
        "address",
        "changeCategory",
        "change_category",
        "dependsOn",
        "depends_on",
        "index",
        "inspectorValues",
        "mode",
        "name",
        "properties",
        "provider_name",
        "schema_version",
        "sensitive_values",
        "type",
        "values",
    }
)

#: Attribute_Path of a Config_Snapshot that is not a container at all. A leaf
#: supplied where a tree is expected has no key and no index leading to it, so it
#: is reported at the empty path rather than dropped (Requirement 14.14).
ROOT_PATH: str = ""


@dataclass(frozen=True)
class AttributeStyle:
    """Colour token, Attribute_Flag_Token, and display label of one Attribute_State."""

    color: str
    flag: str
    label: str

    def to_payload(self) -> Dict[str, str]:
        """Return the JSON form carried by the Inspector_Index (Requirement 7.13)."""
        return {"color": self.color, "flag": self.flag, "label": self.label}


#: Attribute_Style table. ``unchanged`` is explicitly present and explicitly
#: styleless, so "no decoration" is a table entry rather than a fallback. The
#: colour tokens are the plan-diff Change_Style tokens reused deliberately, and
#: the flag column is the non-colour cue the panel always renders as text.
ATTRIBUTE_STYLES: Dict[str, Optional[AttributeStyle]] = {
    "added": AttributeStyle(color="#107C10", flag="+", label="Added"),
    "removed": AttributeStyle(color="#D13438", flag="-", label="Removed"),
    "changed": AttributeStyle(color="#0078D4", flag="~", label="Changed"),
    "unchanged": None,
}


@dataclass(frozen=True)
class AttributeEntry:
    """One Attribute_Path of a resource with its state and its rendered values.

    ``before`` is ``None`` exactly when the path is absent from the before
    Config_Snapshot, ``after`` is ``None`` exactly when it is absent from the
    after Config_Snapshot.
    """

    path: str
    state: str
    before: Optional[str] = None
    after: Optional[str] = None

    def to_payload(self) -> Dict[str, Any]:
        """Return the JSON-serializable form written to the Inspector_Payload."""
        payload: Dict[str, Any] = {"path": self.path, "state": self.state}
        if self.before is not None:
            payload["before"] = self.before
        if self.after is not None:
            payload["after"] = self.after
        return payload

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "AttributeEntry":
        """Rebuild an entry from its serialized form, keeping absent values absent."""
        before = payload.get("before")
        after = payload.get("after")
        return cls(
            path=str(payload.get("path", "")),
            state=str(payload.get("state", UNCHANGED_STATE)),
            before=None if before is None else str(before),
            after=None if after is None else str(after),
        )


@dataclass
class InspectorIdentity:
    """The identity header of one Interaction_Layer element.

    ``key`` is the Inspector_Key: the Node_Key for a resource drawn as a node,
    the Cluster_Key for a resource drawn as a container. ``kind`` is one of
    ``"node"``, ``"virtualNetwork"`` or ``"subnet"``.
    """

    key: str
    kind: str
    name: str
    resource_type: str = ""
    resource_group: str = ""
    address: Optional[str] = None
    change_category: Optional[str] = None


@dataclass
class InspectorRecord:
    """The full configuration of one Interaction_Layer element (Requirement 4.4)."""

    key: str
    kind: str
    name: str
    resource_type: str = ""
    resource_group: str = ""
    address: Optional[str] = None
    change_category: Optional[str] = None
    replacement: bool = False
    attributes: List[AttributeEntry] = field(default_factory=list)
    omitted_attributes: int = 0
    truncations: List[str] = field(default_factory=list)

    def to_payload(self) -> Dict[str, Any]:
        """Return the JSON-serializable form of one Inspector_Payload line."""
        return {
            "key": self.key,
            "kind": self.kind,
            "name": self.name,
            "resourceType": self.resource_type,
            "resourceGroup": self.resource_group,
            "address": self.address,
            "changeCategory": self.change_category,
            "replacement": self.replacement,
            "attributes": [entry.to_payload() for entry in self.attributes],
            "omittedAttributes": self.omitted_attributes,
            "truncations": list(self.truncations),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "InspectorRecord":
        """Rebuild a record from its serialized form."""
        raw_attributes = payload.get("attributes") or ()
        raw_truncations = payload.get("truncations") or ()
        address = payload.get("address")
        change_category = payload.get("changeCategory")
        return cls(
            key=str(payload.get("key", "")),
            kind=str(payload.get("kind", "")),
            name=str(payload.get("name", "")),
            resource_type=str(payload.get("resourceType", "") or ""),
            resource_group=str(payload.get("resourceGroup", "") or ""),
            address=None if address is None else str(address),
            change_category=None if change_category is None else str(change_category),
            replacement=bool(payload.get("replacement", False)),
            attributes=[AttributeEntry.from_payload(entry) for entry in raw_attributes],
            omitted_attributes=int(payload.get("omittedAttributes", 0) or 0),
            truncations=[str(reason) for reason in raw_truncations],
        )


@dataclass
class InspectorPayload:
    """Every Inspector_Record of one run, plus the collision count of that run.

    The Inspector_Index derives its record count from ``records`` and its
    Attribute_Style table and Value_Bounds from this module's constants, so the
    front end never carries a second copy of those constants.
    """

    records: List[InspectorRecord] = field(default_factory=list)
    key_collisions: int = 0

    @property
    def record_count(self) -> int:
        """Return the number of Inspector_Records the payload carries."""
        return len(self.records)


# ─── Truncation_Reason reporting ──────────────────────────────────────────────
#
# ``flatten_values`` and ``render_scalar`` are pure functions whose return values
# are fixed by the design (a path map and a display string), yet an
# Inspector_Record has to report *which* Value_Bounds applied so ``build_record``
# can fill its ``truncations`` list (Requirements 12.3, 12.4, 12.10). Rather than
# widen the return types — which would make every caller unpack a tuple, and the
# path map is consumed by name in three places — both functions take an optional
# ``reasons`` accumulator: a mutable set the caller owns and reads afterwards.
#
#     reasons: set[str] = set()
#     flat = flatten_values(tree, reasons=reasons)
#     text = render_scalar(flat[path], reasons=reasons)
#     # reasons now holds "depth" and/or "value" for this record
#
# Passing ``None`` (the default) discards the report, which is what a caller that
# only wants the values does. Nothing is ever dropped silently: the marker in the
# value says *that* a truncation happened, the accumulator says *which bound*.
#
# One deliberate gap: a subtree that repeats an enclosing subtree collapses to the
# Truncation_Marker (Requirement 13.11) but records no Truncation_Reason, because
# the Truncation_Reason set is closed over the three Value_Bounds and a cyclic
# reference is not one of them. That collapse is reported by the marker alone.


def _record_reason(reasons: Optional[MutableSet[str]], reason: str) -> None:
    """Add one Truncation_Reason to the caller's accumulator, if it supplied one."""
    if reasons is not None:
        reasons.add(reason)


def render_scalar(
    value: Any,
    *,
    max_chars: int = MAX_SCALAR_CHARS,
    reasons: Optional[MutableSet[str]] = None,
) -> str:
    """Render one Config_Snapshot leaf as the display text of an Attribute_Entry.

    A string is used verbatim. Any other value is rendered as its JSON
    representation (Requirement 5.7), which is what makes ``true``, ``null``,
    numbers and the empty containers ``{}`` and ``[]`` read the way the plan
    writes them. A value the JSON serializer cannot represent — a ``set``, a
    ``datetime``, ``bytes``, an arbitrary object — falls back to ``str(value)``
    rather than raising or dropping the row (Requirement 13.9).

    Past ``max_chars`` the text is cut to exactly ``max_chars`` characters and the
    Truncation_Marker is appended, and the ``value`` Truncation_Reason is added to
    ``reasons`` when the caller supplied an accumulator (Requirement 12.3).

    Args:
        value: The leaf value to render.
        max_chars: Scalar_Bound in characters, before the Truncation_Marker.
        reasons: Optional accumulator that collects the applied Truncation_Reasons.

    Returns:
        The display text, at most ``max_chars`` characters plus the
        Truncation_Marker.
    """
    text = _render_text(value)

    limit = max(0, int(max_chars))
    if len(text) > limit:
        _record_reason(reasons, VALUE_REASON)
        return text[:limit] + TRUNCATION_MARKER
    return text


def _render_text(value: Any) -> str:
    """Return the untruncated display text of one leaf, never raising.

    The three-step ladder is JSON, then ``str``, then a type-named placeholder.
    The last step exists because ``str`` runs user-supplied ``__str__`` code, and
    Requirement 14.14 admits no unhandled exception from any attribute tree.
    """
    if isinstance(value, str):
        return value

    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        pass

    try:
        return str(value)
    except Exception:  # pragma: no cover - defensive, needs a hostile __str__
        return f"<unrenderable {type(value).__name__}>"


def flatten_values(
    tree: Any,
    *,
    max_depth: int = MAX_TREE_DEPTH,
    reasons: Optional[MutableSet[str]] = None,
) -> Dict[str, Any]:
    """Flatten a Config_Snapshot into an ``{Attribute_Path: leaf}`` map.

    Map keys and zero-based list indices join with ``.``, so the leaf
    ``node_version`` of the first element of ``application_stack`` inside
    ``site_config`` lands at ``site_config.application_stack.0.node_version``
    (Requirement 5.3). A key that is not a string is rendered through
    ``str(key)`` and the result is used verbatim as the segment
    (Requirement 13.10) — as is a key holding a literal ``.``, which the design
    records as a known path-collision limitation rather than escaping.

    The values in the returned map are the **raw** leaves, not display text: an
    empty map stays ``{}`` and an empty list stays ``[]`` at its own
    Attribute_Path, which :func:`render_scalar` then renders as ``{}`` and ``[]``
    (Requirement 5.8). Keeping the leaves raw is what makes the flatten step
    lossless and the round trip exact.

    Two guards stop the walk:

    * **Depth_Bound.** A container sitting at a path that already holds
      ``max_depth`` segments is not descended into. The Truncation_Marker is
      emitted at that path, the deeper leaves are omitted, and the ``depth``
      Truncation_Reason is recorded (Requirement 12.4). No Attribute_Path the
      function returns therefore holds more than ``max_depth`` segments.
    * **Enclosing subtree.** The identity of every container currently on the
      walk is tracked, so a subtree that repeats one of its own ancestors — a
      cyclic or self-referential reference — is replaced by the Truncation_Marker
      and the walk terminates (Requirement 13.11). Only *ancestors* count: the
      same dict reused as a sibling in two places is flattened normally in both,
      because it encloses nothing.

    A ``tree`` that is not a container at all is reported as its single leaf at
    :data:`ROOT_PATH`, and an empty container yields an empty map, so a resource
    with two empty Config_Snapshots produces an Inspector_Record with no
    Attribute_Entry values rather than no record.

    Args:
        tree: The Config_Snapshot to flatten. Any value is accepted.
        max_depth: Depth_Bound in Attribute_Path segments.
        reasons: Optional accumulator that collects the applied Truncation_Reasons.

    Returns:
        A map from Attribute_Path to raw leaf value, in walk order.
    """
    flat: Dict[str, Any] = {}
    limit = max(0, int(max_depth))

    if not _is_container(tree):
        flat[ROOT_PATH] = tree
        return flat

    _walk_container(tree, "", 0, limit, [], flat, reasons)
    return flat


def _is_container(value: Any) -> bool:
    """Return whether ``value`` is walked as a branch rather than emitted as a leaf.

    A string is a leaf even though it is a sequence, and so is ``bytes``: neither
    has attribute paths inside it.
    """
    if isinstance(value, Mapping):
        return True
    return isinstance(value, (list, tuple)) and not isinstance(value, (str, bytes, bytearray))


def _walk_container(
    container: Any,
    prefix: str,
    depth: int,
    max_depth: int,
    ancestors: List[int],
    flat: Dict[str, Any],
    reasons: Optional[MutableSet[str]],
) -> None:
    """Walk one container, appending its leaves to ``flat``.

    ``ancestors`` holds the ``id()`` of every container on the path from the root
    to ``container`` inclusive; it is pushed on entry and popped on exit, which is
    what limits the repeat guard to *enclosing* subtrees.
    """
    ancestors.append(id(container))
    try:
        for segment, child in _child_items(container):
            path = f"{prefix}.{segment}" if prefix else segment
            _emit(child, path, depth + 1, max_depth, ancestors, flat, reasons)
    finally:
        ancestors.pop()


def _child_items(container: Any) -> Iterable[Tuple[str, Any]]:
    """Yield the ``(path segment, child)`` pairs of one container.

    Map keys become ``str(key)`` segments, list positions become zero-based
    decimal segments.
    """
    if isinstance(container, Mapping):
        return [(_key_segment(key), child) for key, child in container.items()]
    return [(str(index), child) for index, child in enumerate(container)]


def _key_segment(key: Any) -> str:
    """Render one map key as an Attribute_Path segment (Requirement 13.10)."""
    if isinstance(key, str):
        return key
    try:
        return str(key)
    except Exception:  # pragma: no cover - defensive, needs a hostile __str__
        return f"<unrenderable {type(key).__name__}>"


def _emit(
    value: Any,
    path: str,
    depth: int,
    max_depth: int,
    ancestors: List[int],
    flat: Dict[str, Any],
    reasons: Optional[MutableSet[str]],
) -> None:
    """Emit one value at ``path``, descending into it when it is a walkable branch."""
    if not _is_container(value):
        flat[path] = value
        return

    if not value:
        # An empty map or an empty list is a leaf of its own (Requirement 5.8).
        flat[path] = value
        return

    if id(value) in ancestors:
        # The subtree repeats one of its own ancestors (Requirement 13.11).
        flat[path] = TRUNCATION_MARKER
        return

    if depth >= max_depth:
        # Deeper leaves are omitted; the marker stands in for them (Requirement 12.4).
        flat[path] = TRUNCATION_MARKER
        _record_reason(reasons, DEPTH_REASON)
        return

    _walk_container(value, path, depth, max_depth, ancestors, flat, reasons)


# ─── Attribute_Differ ─────────────────────────────────────────────────────────


def diff_attributes(
    before: Any,
    after: Any,
    *,
    unknown: Any = None,
    max_depth: int = MAX_TREE_DEPTH,
    max_chars: int = MAX_SCALAR_CHARS,
    reasons: Optional[MutableSet[str]] = None,
) -> List[AttributeEntry]:
    """Diff two Config_Snapshots into one Attribute_Entry per Attribute_Path.

    Both phases are flattened, the union of their Attribute_Paths is taken, and
    one Attribute_Entry is emitted per path in ascending lexicographic order
    (Requirements 5.2, 5.4). Each entry carries exactly one Attribute_State drawn
    from :data:`ATTRIBUTE_STATES`, assigned by this decision table over the
    *rendered* values (Requirement 7.1):

    * before absent, after present → ``added`` (Requirement 7.2)
    * before present, after absent → ``removed`` (Requirement 7.3)
    * both present, rendered values differ → ``changed`` (Requirement 7.4)
    * both present, rendered values equal → ``unchanged`` (Requirement 7.5)

    The comparison is on the rendered text rather than the raw leaves, so a value
    that changes only in type — ``1`` to ``"1"``, ``true`` to ``"true"`` — reads
    as ``unchanged``, which is what the Operator sees in the panel and therefore
    what the state has to describe.

    Two overrides sit on top of the table, in this order:

    1. **Redaction.** A path whose two rendered values are both the
       Redaction_Literal is ``unchanged`` with the Redaction_Literal on both
       sides, because redaction removes the information needed to compare the
       phases (Requirement 11.7). This override wins over the unknown mask: a
       redacted-in-both-phases path stays comparable-as-redacted rather than
       becoming a spurious ``changed`` against the Unknown_Marker.
    2. **Unknown mask.** Where ``unknown`` flags a path — directly, or through a
       flagged ancestor container — the After_Value becomes the Unknown_Marker
       (Requirement 6.6). A flagged path counts as present in the after phase, so
       a value the plan will only know after apply reads as ``changed`` against
       its before value rather than as ``removed``.

    The mask also contributes Attribute_Paths of its own. A path the mask flags
    as an individual ``True`` leaf is an attribute the plan will know only after
    apply, and for a ``create`` that is most of the resource: Terraform emits no
    value for it, so it appears in neither snapshot, and taking only the union of
    the two snapshots dropped it from the panel entirely. Such a path is emitted
    with no Before_Value and the Unknown_Marker as its After_Value, which reads as
    ``added`` — the same row `terraform plan` prints as ``(known after apply)``.

    A flagged path that one of the snapshots already carries is not duplicated —
    it keeps its own row and gets the Unknown_Marker as its After_Value through
    override 2 above. Only a flagged path that neither snapshot carries becomes a
    new row, so the entry set is the union of the two snapshots plus exactly the
    attributes the plan says it cannot know yet (Requirement 6.6).

    Args:
        before: The before phase Config_Snapshot, already redacted.
        after: The after phase Config_Snapshot, already redacted.
        unknown: The plan's ``after_unknown`` mask, or ``None`` for no mask.
        max_depth: Depth_Bound forwarded to :func:`flatten_values`.
        max_chars: Scalar_Bound forwarded to :func:`render_scalar`.
        reasons: Optional accumulator that collects the applied Truncation_Reasons.

    Returns:
        The Attribute_Entry list, ordered by Attribute_Path ascending.
    """
    flat_before = flatten_values(before, max_depth=max_depth, reasons=reasons)
    flat_after = flatten_values(after, max_depth=max_depth, reasons=reasons)
    unknown_paths = _unknown_paths(unknown, max_depth=max_depth)

    # An attribute the plan will only know after apply carries no value in either
    # phase, so the union of the two snapshots omits it. Terraform still names it,
    # and for a `create` most of the resource sits here, so the flagged paths that
    # no snapshot carries join the entry set (Requirement 6.6).
    #
    # A flag that covers paths the snapshots *do* carry names no attribute of its
    # own — it is a container flag, or the bare root flag, and override 2 above
    # already applies it to every path beneath it. Adding a row for it would put a
    # container's name in the panel next to the leaves it already marked.
    known_paths = set(flat_before) | set(flat_after)
    unknown_only = {
        path
        for path in unknown_paths
        if path not in known_paths
        and path != ROOT_PATH
        and not any(covered.startswith(f"{path}.") for covered in known_paths)
    }

    entries: List[AttributeEntry] = []
    for path in sorted(set(flat_before) | set(flat_after) | unknown_only):
        before_text = (
            render_scalar(flat_before[path], max_chars=max_chars, reasons=reasons)
            if path in flat_before
            else None
        )
        after_text = (
            render_scalar(flat_after[path], max_chars=max_chars, reasons=reasons)
            if path in flat_after
            else None
        )

        if not _redacted_on_both_sides(before_text, after_text) and _is_unknown(
            path, unknown_paths
        ):
            after_text = UNKNOWN_MARKER

        entries.append(
            AttributeEntry(
                path=path,
                state=_classify(before_text, after_text),
                before=before_text,
                after=after_text,
            )
        )
    return entries


def _classify(before_text: Optional[str], after_text: Optional[str]) -> str:
    """Return the Attribute_State of one path from its two rendered values."""
    if before_text is None:
        if after_text is None:
            # Unreachable through diff_attributes, which only walks the union of
            # the two snapshots. Classified rather than raised so the closure of
            # ATTRIBUTE_STATES holds for every caller (Requirement 7.1).
            return UNCHANGED_STATE
        return ADDED_STATE
    if after_text is None:
        return REMOVED_STATE
    return UNCHANGED_STATE if before_text == after_text else CHANGED_STATE


def _redacted_on_both_sides(before_text: Optional[str], after_text: Optional[str]) -> bool:
    """Return whether both phases of one path hold the Redaction_Literal."""
    return before_text == REDACTION_LITERAL and after_text == REDACTION_LITERAL


def _unknown_paths(unknown: Any, *, max_depth: int) -> frozenset:
    """Flatten an ``after_unknown`` mask into the set of Attribute_Paths it flags.

    The mask is a parallel tree of booleans, so it is flattened by the same walk
    as a Config_Snapshot and every leaf that is exactly ``True`` is a flag. A
    mask that flags a whole container flags it as one ``True`` leaf at that
    container's path, which :func:`_is_unknown` then applies to every path
    beneath it.

    Only ``True`` counts. A mask leaf holding a string — the Truncation_Marker a
    depth-collapsed mask branch leaves behind, say — is not treated as a flag, so
    a bound applied to the mask can never turn a known value into
    ``(known after apply)``. No Truncation_Reason is recorded for the mask walk
    either: the mask is not a value the record displays.
    """
    if unknown is None:
        return frozenset()
    return frozenset(
        path for path, flag in flatten_values(unknown, max_depth=max_depth).items() if flag is True
    )


def _is_unknown(path: str, unknown_paths: frozenset) -> bool:
    """Return whether ``path`` or one of its ancestor containers is flagged unknown."""
    if not unknown_paths:
        return False
    if ROOT_PATH in unknown_paths:
        return True

    candidate = path
    while True:
        if candidate in unknown_paths:
            return True
        cut = candidate.rfind(".")
        if cut == -1:
            return False
        candidate = candidate[:cut]


# ─── Value_Bounds: the Row_Bound ──────────────────────────────────────────────


def apply_bounds(
    entries: Sequence[AttributeEntry],
    *,
    max_rows: int = MAX_ATTRIBUTE_ROWS,
    reasons: Optional[MutableSet[str]] = None,
) -> Tuple[List[AttributeEntry], int]:
    """Cap an Attribute_Entry list at the Row_Bound and report what was dropped.

    Inside the bound the input sequence is returned in the order it arrived,
    untouched: :func:`diff_attributes` already emits ascending Attribute_Path
    order, and a caller that ordered its entries some other way keeps that order
    when nothing has to go.

    Over the bound the selection is by Attribute_State, which is what
    Requirement 12.2 asks for: every entry whose state differs from ``unchanged``
    is retained first, then the ``unchanged`` remainder fills the rows that are
    left in ascending Attribute_Path order until the bound is reached, and the
    rest are omitted. The retained list is therefore the non-``unchanged`` block
    followed by the ``unchanged`` filler block, each block ascending by
    Attribute_Path — not one globally ascending run. That is the ordering the
    requirement and Property 12 both describe, and it is the ordering the panel
    wants: on a resource with more than 500 attributes the rows that carry a
    change are the rows the Operator reads first.

    Both blocks are sorted rather than merely filtered, so the result is
    deterministic even when the caller's input was not ordered by path. When more
    than ``max_rows`` entries carry a change, the non-``unchanged`` block itself
    is cut at the bound in ascending Attribute_Path order and no filler is added.

    ``rows`` is added to ``reasons`` exactly when at least one entry is omitted
    (Requirement 12.5).

    Args:
        entries: The Attribute_Entry values of one Inspector_Record.
        max_rows: Row_Bound in Attribute_Entry values.
        reasons: Optional accumulator that collects the applied Truncation_Reasons.

    Returns:
        A ``(kept entries, omitted count)`` pair. The omitted count is ``0``
        exactly when the input fits inside the bound.
    """
    ordered = list(entries)
    limit = max(0, int(max_rows))

    if len(ordered) <= limit:
        return ordered, 0

    changed_rows = sorted(
        (entry for entry in ordered if entry.state != UNCHANGED_STATE),
        key=lambda entry: entry.path,
    )
    unchanged_rows = sorted(
        (entry for entry in ordered if entry.state == UNCHANGED_STATE),
        key=lambda entry: entry.path,
    )

    kept = changed_rows[:limit]
    kept.extend(unchanged_rows[: limit - len(kept)])

    omitted = len(ordered) - len(kept)
    if omitted:
        _record_reason(reasons, ROWS_REASON)
    return kept, omitted


# ─── Inspector_Record assembly ────────────────────────────────────────────────


def is_replacement(change_category: Optional[str]) -> bool:
    """Return whether a Change_Category marks the resource for replacement.

    The marker is set for the Change_Category ``replace`` and for nothing else:
    ``create``, ``delete``, ``update``, ``unchanged``, an unrecognized value and
    a Legacy_Mode record with no category at all are all ``False``
    (Requirement 4.9).
    """
    return change_category == REPLACE_CATEGORY


def _ordered_reasons(reasons: Iterable[str]) -> List[str]:
    """Return the applied Truncation_Reasons in the canonical order, deduplicated.

    A reason outside the closed set is dropped rather than carried into the
    payload, so ``truncations`` is always a subset of
    :data:`TRUNCATION_REASONS` (Requirement 12.10).
    """
    applied = set(reasons)
    return [reason for reason in TRUNCATION_REASONS if reason in applied]


def build_record(
    identity: InspectorIdentity,
    before: Any,
    after: Any,
    unknown: Any = None,
    *,
    max_rows: int = MAX_ATTRIBUTE_ROWS,
    max_depth: int = MAX_TREE_DEPTH,
    max_chars: int = MAX_SCALAR_CHARS,
) -> InspectorRecord:
    """Assemble one Inspector_Record from an identity header and two snapshots.

    The identity fields are copied across verbatim, the two Config_Snapshots are
    diffed into Attribute_Entry values, the entry list is capped at the Row_Bound,
    and the three Value_Bounds report themselves into ``truncations``: ``value``
    when a rendered value was cut, ``depth`` when a subtree was collapsed, and
    ``rows`` when the Row_Bound omitted at least one entry — each present exactly
    when the corresponding bound applied (Requirements 12.3, 12.4, 12.5, 12.10).
    The reasons appear in the canonical :data:`TRUNCATION_REASONS` order, so two
    records with the same applied bounds serialize identically.

    ``replacement`` is set exactly for the Change_Category ``replace``
    (Requirement 4.9). Both snapshots are expected to be redacted already:
    redaction happens upstream in the builder, never here.

    A resource whose two snapshots are both empty yields a record with the
    identity header and an empty attribute list rather than no record, so the
    Interaction_Layer never holds an element the Inspector_Index cannot answer
    for.

    Args:
        identity: The identity header of the drawn element.
        before: The redacted before phase Config_Snapshot.
        after: The redacted after phase Config_Snapshot.
        unknown: The plan's ``after_unknown`` mask, or ``None`` for no mask.
        max_rows: Row_Bound in Attribute_Entry values.
        max_depth: Depth_Bound in Attribute_Path segments.
        max_chars: Scalar_Bound in characters per rendered value.

    Returns:
        The assembled Inspector_Record.
    """
    reasons: MutableSet[str] = set()

    entries = diff_attributes(
        before,
        after,
        unknown=unknown,
        max_depth=max_depth,
        max_chars=max_chars,
        reasons=reasons,
    )
    kept, omitted = apply_bounds(entries, max_rows=max_rows, reasons=reasons)

    return InspectorRecord(
        key=identity.key,
        kind=identity.kind,
        name=identity.name,
        resource_type=identity.resource_type,
        resource_group=identity.resource_group,
        address=identity.address,
        change_category=identity.change_category,
        replacement=is_replacement(identity.change_category),
        attributes=kept,
        omitted_attributes=omitted,
        truncations=_ordered_reasons(reasons),
    )


# ─── Element collection ───────────────────────────────────────────────────────
#
# The collector is fed from the render pass, at the points where the
# Graph_Pipeline creates a node or opens a cluster, so the Inspector_Index
# describes exactly the elements the Diagram draws rather than a second notion of
# the displayed set (Requirement 4.8). Everything a record needs is read from the
# source dict already in scope at that call site: no Plan_File is re-read and no
# Azure request is issued (Requirements 6.10, 10.5).

#: Key of the redacted ``{before, after, afterUnknown}`` triple that
#: ``TerraformTemplateBuilder._inspector_values_for`` attaches to a
#: Renderer_Template resource when Inspector_Mode is on.
INSPECTOR_VALUES_KEY: str = "inspectorValues"

#: Keys of that triple.
BEFORE_KEY: str = "before"
AFTER_KEY: str = "after"
AFTER_UNKNOWN_KEY: str = "afterUnknown"


@dataclass
class CollectedElement:
    """One drawn diagram element, as the render pass hands it over.

    ``source`` is a *reference* to the dict the render pass already holds — the
    Renderer_Template resource, the Azure resource dict in Live mode, or a subnet
    entry read out of its parent VNet's ``properties["subnets"]`` list. Nothing is
    copied and nothing is diffed here: collection has to stay cheap because it
    runs inside the render loop, so the whole transform chain is deferred to
    :meth:`InspectorCollector.build_payload`.
    """

    key: str
    kind: str
    source: Any
    resource_group: str = ""


class InspectorCollector:
    """Collects one entry per drawn diagram element and builds the payload.

    One instance per run, constructed only when Inspector_Mode is enabled; the
    disabled path uses :class:`NullInspectorCollector` so the call sites carry no
    new branching at all.

    Recording is order-preserving and first-write-wins: when two elements produce
    the same Inspector_Key the first record is retained, the duplicate is logged
    at warning level, and the collision counter that the Inspector_Index reports
    is incremented (Requirement 4.5).

    An element whose source is ``None`` is not recorded at all: see the guard in
    :meth:`_record` (Requirement 3.2).
    """

    def __init__(
        self,
        *,
        max_rows: int = MAX_ATTRIBUTE_ROWS,
        max_depth: int = MAX_TREE_DEPTH,
        max_chars: int = MAX_SCALAR_CHARS,
    ) -> None:
        """Store the Value_Bounds this run applies to every record it builds."""
        self._elements: List[CollectedElement] = []
        self._keys: Dict[str, int] = {}
        self._key_collisions: int = 0
        self._max_rows = max_rows
        self._max_depth = max_depth
        self._max_chars = max_chars

    # ─── Recording ────────────────────────────────────────────────────────────

    def record_node(self, node_key: str, resource: Any, resource_group: str = "") -> None:
        """Record the element of a resource the Graph_Pipeline draws as a node.

        ``node_key`` is the Node_Key ``<resource_name>-<resource_group>``, which is
        the identifier the Graph_Pipeline gives the node and therefore the text of
        the ``<title>`` the Interaction_Layer carries (Requirement 3.4).

        Args:
            node_key: The Inspector_Key of the drawn node.
            resource: The resource dict in scope at the creation site.
            resource_group: The resource group the node is drawn in.
        """
        self._record(node_key, NODE_KIND, resource, resource_group)

    def record_cluster(
        self,
        cluster_key: str,
        kind: str,
        source: Any,
        resource_group: str = "",
    ) -> None:
        """Record the element of a resource the Graph_Pipeline draws as a container.

        ``cluster_key`` is the Cluster_Key — ``cluster_vnet<name>`` for a virtual
        network, ``cluster_subnet<name>`` for a subnet (Requirement 3.5) — and
        ``kind`` is ``"virtualNetwork"`` or ``"subnet"``.

        Args:
            cluster_key: The Inspector_Key of the drawn cluster.
            kind: The Inspector kind of the container.
            source: The resource dict, or the embedded ``subnets`` entry.
            resource_group: The resource group the container is drawn in.
        """
        self._record(cluster_key, kind, source, resource_group)

    def _record(self, key: Any, kind: str, source: Any, resource_group: Any) -> None:
        """Append one element, keeping the first record of a duplicate key."""
        if not isinstance(key, str) or not key:
            # An Inspector_Key has to match the ``<title>`` the layer carries, so a
            # key that is not usable text cannot be repaired here. Dropping it is a
            # warning rather than an exception (Requirement 1.9).
            logger.warning(f"Inspector element with an unusable Inspector_Key {key!r} was not recorded")
            return

        if source is None:
            # The sourceless-record guard, and the only one: every call site funnels
            # through here, so no call site carries its own version of this test.
            #
            # An element is only worth making activatable when the Inspector can
            # describe it (Requirement 3.2). Some nodes the Diagram draws come from an
            # Azure API lookup rather than from a Renderer_Template entry — a private
            # DNS zone, a Bastion host, a route table reached through a subnet
            # dependency — and in Live and Bicep mode the subject of that lookup may be
            # absent from the exported resource list, so the source resolution misses
            # and the caller hands over ``None``. Recording it anyway would produce an
            # identity-only record with zero Attribute_Entry rows, and because the panel
            # gates activatability on the Inspector_Index key set, the Operator would get
            # a clickable element with an empty panel. Dropping the record instead leaves
            # the element inert, which is the honest outcome.
            #
            # A caller that can *synthesize* a source — the aggregated private-DNS-zone
            # node builds one from the zone list — passes that synthesized dict and is
            # recorded normally. Debug rather than warning: a lookup subject missing from
            # the resource list is expected in those modes, not an anomaly, and the
            # message names the Inspector_Key so the gap is traceable.
            logger.debug(f"No Inspector source for '{key}'; the element was left inert")
            return

        if key in self._keys:
            self._key_collisions += 1
            logger.warning(f"Duplicate Inspector_Key '{key}' ignored; the first record is retained")
            return

        self._keys[key] = len(self._elements)
        self._elements.append(
            CollectedElement(
                key=key,
                kind=kind if isinstance(kind, str) and kind else NODE_KIND,
                source=source,
                resource_group=resource_group if isinstance(resource_group, str) else "",
            )
        )

    # ─── Reporting ────────────────────────────────────────────────────────────

    @property
    def element_count(self) -> int:
        """Return the number of elements recorded, collisions excluded."""
        return len(self._elements)

    @property
    def key_collisions(self) -> int:
        """Return the number of duplicate Inspector_Keys dropped (Requirement 4.5)."""
        return self._key_collisions

    def keys(self) -> List[str]:
        """Return the recorded Inspector_Keys in collection order."""
        return [element.key for element in self._elements]

    # ─── Payload assembly ─────────────────────────────────────────────────────

    def build_payload(self) -> InspectorPayload:
        """Diff, bound and assemble one Inspector_Record per collected element.

        Each record is built behind its own guard: a source dict that breaks the
        transform chain costs that one record a warning naming its Inspector_Key,
        and every other record is still built and still written
        (Requirements 1.9, 4.1).

        Returns:
            The Inspector_Payload of this run, carrying the collision count.
        """
        records: List[InspectorRecord] = []
        for element in self._elements:
            try:
                records.append(self._build_element_record(element))
            except Exception as error:  # noqa: BLE001 - one bad record is a warning
                logger.warning(f"Could not build the Inspector record of '{element.key}': {error}")
        return InspectorPayload(records=records, key_collisions=self._key_collisions)

    def _build_element_record(self, element: CollectedElement) -> InspectorRecord:
        """Build the Inspector_Record of one collected element."""
        before, after, unknown = _element_snapshots(element.source)
        return build_record(
            _element_identity(element),
            before,
            after,
            unknown,
            max_rows=self._max_rows,
            max_depth=self._max_depth,
            max_chars=self._max_chars,
        )


class NullInspectorCollector(InspectorCollector):
    """The Inspector_Mode-off collector: every method returns immediately.

    The render pass calls ``record_node`` and ``record_cluster`` unconditionally,
    eight to ten levels deep inside the graph builder, so the disabled path is
    kept free of new branching by swapping the object rather than guarding each
    call site. ``build_payload`` returns an empty payload, which no caller writes:
    the payload write itself is the one place Inspector_Mode is tested.
    """

    def record_node(self, node_key: str, resource: Any, resource_group: str = "") -> None:
        """Do nothing (Inspector_Mode is off)."""

    def record_cluster(
        self,
        cluster_key: str,
        kind: str,
        source: Any,
        resource_group: str = "",
    ) -> None:
        """Do nothing (Inspector_Mode is off)."""

    def build_payload(self) -> InspectorPayload:
        """Return an empty Inspector_Payload."""
        return InspectorPayload()


def _element_identity(element: CollectedElement) -> InspectorIdentity:
    """Derive the identity header of one collected element from its source dict."""
    source = element.source if isinstance(element.source, Mapping) else None
    return InspectorIdentity(
        key=element.key,
        kind=element.kind,
        name=_element_name(element, source),
        resource_type=_element_type(element, source),
        resource_group=_element_resource_group(element, source),
        address=_element_address(source),
        change_category=_element_change_category(source),
    )


def _first_text(source: Optional[Mapping], *names: str) -> Optional[str]:
    """Return the first non-empty string value of ``names`` present in ``source``."""
    if source is None:
        return None
    for name in names:
        value = source.get(name)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _element_name(element: CollectedElement, source: Optional[Mapping]) -> str:
    """Return the display name of an element, falling back to its Inspector_Key.

    A container drawn from an embedded ``subnets`` entry may carry no ``name`` at
    all, in which case the Cluster_Key prefix is stripped to recover the name the
    Diagram drew (Requirement 3.5).
    """
    named = _first_text(source, "name", "displayName")
    if named is not None:
        return named

    for prefix in _CLUSTER_KEY_PREFIXES:
        if element.key.startswith(prefix) and len(element.key) > len(prefix):
            return element.key[len(prefix) :]
    return element.key


def _element_type(element: CollectedElement, source: Optional[Mapping]) -> str:
    """Return the renderer type of an element, or the kind's fallback type."""
    typed = _first_text(source, "type", "resourceType", "renderer_type")
    if typed is not None:
        return typed
    return _KIND_FALLBACK_TYPES.get(element.kind, "")


def _element_resource_group(element: CollectedElement, source: Optional[Mapping]) -> str:
    """Return the resource group of an element, preferring the collected value."""
    if element.resource_group:
        return element.resource_group
    return _first_text(source, "resourceGroup", "resource_group", "resourceGroupName") or ""


def _element_address(source: Optional[Mapping]) -> Optional[str]:
    """Return the Terraform address of an element when the input provides one."""
    return _first_text(source, "address")


def _element_change_category(source: Optional[Mapping]) -> Optional[str]:
    """Return the Change_Category of an element when a Change_Record exists."""
    return _first_text(source, "changeCategory", "change_category")


def _element_snapshots(source: Any) -> Tuple[Any, Any, Any]:
    """Resolve the ``(before, after, unknown)`` triple of one source dict.

    A source carrying the ``inspectorValues`` triple that
    ``TerraformTemplateBuilder._inspector_values_for`` attached is used as is: the
    Change_Category table, the redaction and the unknown mask were all resolved
    there, against the plan, and are not re-derived here (Requirement 6.10).

    A source carrying no triple — every Legacy_Mode element, and every container
    drawn from an embedded ``subnets`` entry — is described by the configuration
    that source dict holds, on both sides, so every Attribute_Entry of the record
    is ``unchanged`` (Requirements 6.9, 10.1, 10.4, 9.5).
    """
    if isinstance(source, Mapping):
        values = source.get(INSPECTOR_VALUES_KEY)
        if isinstance(values, Mapping):
            return (
                values.get(BEFORE_KEY),
                values.get(AFTER_KEY),
                values.get(AFTER_UNKNOWN_KEY),
            )
        snapshot = _source_snapshot(source)
        return snapshot, snapshot, None

    # A source that is not a map at all is still displayable as its own leaf.
    return source, source, None


def _source_snapshot(source: Mapping) -> Dict[str, Any]:
    """Build a Config_Snapshot from a source dict that carries no triple.

    The attribute map is used when the source carries one, which is the plan-entry
    shape; otherwise the Renderer_Template shape is described by its
    ``properties`` map plus the extra fields, which is the only configuration such
    an entry holds (Requirement 10.4). The exclusion set mirrors the one
    ``TerraformTemplateBuilder`` already applies, so the same element described
    through either path yields the same Attribute_Paths.
    """
    values = source.get("values")
    if isinstance(values, Mapping) and values:
        return dict(values)

    snapshot: Dict[str, Any] = {}
    properties = source.get("properties")
    if isinstance(properties, Mapping) and properties:
        snapshot["properties"] = properties
    for key, value in source.items():
        if key in SOURCE_IDENTITY_KEYS or value is None:
            continue
        snapshot[key] = value
    return snapshot


# ─── Inspector_Payload on disk ────────────────────────────────────────────────
#
# Two files beside the PNG, sharing the diagram's stem (Requirement 3.6): one
# JSONL file holding one Inspector_Record per line, and one index holding the byte
# offset and byte length of each line. The offsets are what make a single-record
# read a seek rather than a scan of the whole payload (Requirement 12.1), and the
# index is written last, after the JSONL handle closes, so a failed run never
# leaves an index pointing into a file that does not match it (Requirement 12.8).


def bounds_payload(
    *,
    max_rows: int = MAX_ATTRIBUTE_ROWS,
    max_chars: int = MAX_SCALAR_CHARS,
    max_depth: int = MAX_TREE_DEPTH,
) -> Dict[str, int]:
    """Return the Value_Bounds block the Inspector_Index carries."""
    return {"maxRows": max_rows, "maxScalarChars": max_chars, "maxDepth": max_depth}


def attribute_styles_payload() -> Dict[str, Dict[str, str]]:
    """Return the Attribute_Style table the Inspector_Index carries.

    Only the styled states appear: ``unchanged`` is styleless by definition, and
    the panel reads "no entry" as "default text colour, no marker" rather than
    carrying a second copy of that decision (Requirement 7.13).
    """
    table: Dict[str, Dict[str, str]] = {}
    for state in ATTRIBUTE_STATES:
        style = ATTRIBUTE_STYLES.get(state)
        if style is not None:
            table[state] = style.to_payload()
    return table


def _record_line(record: InspectorRecord) -> bytes:
    """Encode one Inspector_Record as one UTF-8 JSONL line, newline included.

    ``ensure_ascii=False`` keeps multi-byte text readable in the file; the index
    records *byte* offsets, so the encoded length is what matters and the
    non-ASCII path is the one the round-trip property exercises.
    """
    text = json.dumps(record.to_payload(), ensure_ascii=False)
    return (text + "\n").encode("utf-8")


def write_inspector_payload(payload: InspectorPayload, output_filename: str) -> Optional[str]:
    """Write the Inspector_Payload beside the diagram and return the index path.

    ``output_filename`` is the extension-less diagram path the render pass uses,
    so ``<diagram>.inspector.jsonl`` and ``<diagram>.inspector-index.json`` land in
    the run's output folder next to the PNG and share its timestamp
    (Requirement 3.6) — the same derivation the Change_Summary sidecar uses, which
    is what lets the Inspector_Bridge resolve both from a PNG path alone.

    The JSONL file is written first and closed, recording the UTF-8 byte offset and
    byte length of every line; the index is written second, carrying
    ``schemaVersion``, the diagram and records file names, the record count, the
    collision count, the ``keys`` offset map with each key's kind, the
    Attribute_Style table and the applied Value_Bounds (Requirements 7.13, 12.8,
    12.10).

    The ``length`` of a key excludes the line's terminating newline, so a reader
    that seeks to ``offset`` and reads exactly ``length`` bytes gets one JSON
    object and nothing else (Requirement 13.5).

    An `OSError` on either write is a warning naming the path and a ``None``
    return, never an exception: the diagram is already on disk and no failure
    inside the Inspector may cost the Operator the run (Requirement 1.9). The
    index is removed if it exists but the JSONL never got written, so no partial
    payload is left behind for the bridge to read.

    Args:
        payload: The Inspector_Payload of the run.
        output_filename: The extension-less diagram path.

    Returns:
        The Inspector_Index path, or ``None`` when the payload could not be written.
    """
    records_path = f"{output_filename}{INSPECTOR_RECORDS_SUFFIX}"
    index_path = f"{output_filename}{INSPECTOR_INDEX_SUFFIX}"

    keys: Dict[str, Dict[str, Any]] = {}
    written = 0
    try:
        with open(records_path, "wb") as handle:
            for record in payload.records:
                try:
                    line = _record_line(record)
                except (TypeError, ValueError) as error:
                    # A record that will not serialize is dropped rather than
                    # aborting the payload (Requirement 1.9).
                    logger.warning(f"Could not serialize the Inspector record of '{record.key}': {error}")
                    continue
                handle.write(line)
                keys[record.key] = {
                    "offset": written,
                    "length": len(line) - 1,
                    "kind": record.kind,
                }
                written += len(line)
    except OSError as error:
        logger.warning(f"Could not write the Inspector records file {records_path}: {error}")
        _discard_partial(records_path)
        _discard_partial(index_path)
        return None

    index = {
        "schemaVersion": INSPECTOR_SCHEMA_VERSION,
        "diagram": f"{os.path.basename(output_filename)}.png",
        "records": os.path.basename(records_path),
        "recordCount": len(keys),
        "keyCollisions": payload.key_collisions,
        "keys": keys,
        "attributeStyles": attribute_styles_payload(),
        "bounds": bounds_payload(),
    }

    try:
        with open(index_path, "w", encoding="utf-8") as handle:
            json.dump(index, handle, indent=2, ensure_ascii=False)
    except (OSError, TypeError, ValueError) as error:
        logger.warning(f"Could not write the Inspector index {index_path}: {error}")
        _discard_partial(index_path)
        return None

    logger.info(f"Saved Inspector payload: {os.path.abspath(index_path)} ({len(keys)} records)")
    return index_path


def _discard_partial(path: str) -> None:
    """Remove a partially written artifact, ignoring a failure to do so."""
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError as error:  # pragma: no cover - defensive
        logger.warning(f"Could not remove the partial Inspector artifact {path}: {error}")


# ─── Interaction_Layer post-processing ────────────────────────────────────────
#
# Graphviz writes every resource icon into the SVG as
# ``<image xlink:href="/absolute/path/on/the/build/machine/icons/webapp.png" …/>``.
# That path is unresolvable anywhere else, which Requirement 3.7 forbids, and the
# same icon is repeated once per node, which makes the layer needlessly large. Both
# problems have one answer: hoist one ``<image>`` per distinct
# ``(href, width, height, preserveAspectRatio)`` group into ``<defs>`` as a data
# URI and rewrite every occurrence into a ``<use>`` referencing it.

#: SVG and XLink namespace URIs, as Graphviz declares them.
SVG_NAMESPACE: str = "http://www.w3.org/2000/svg"
XLINK_NAMESPACE: str = "http://www.w3.org/1999/xlink"

#: Prefix of the generated ``<defs>`` icon identifiers. The number is the
#: zero-based index of the group in document order, so the same SVG always
#: produces the same identifiers (Requirement 3.10).
ICON_ID_PREFIX: str = "ch-icon-"

#: XML declaration prepended to the rewritten document, matching what Graphviz writes.
_XML_DECLARATION: str = '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'

#: MIME types of the icon formats the render pipeline ships, by lowercase extension.
_ICON_MIME_TYPES: Dict[str, str] = {
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

#: Fallback MIME type of an icon whose extension is not in the table.
_ICON_MIME_FALLBACK: str = "application/octet-stream"

#: Attributes of an ``<image>`` that define the icon rather than its position, and
#: therefore travel to the hoisted ``<defs>`` copy rather than staying on the
#: ``<use>`` that replaces the occurrence.
_ICON_GROUP_ATTRIBUTES: Tuple[str, ...] = ("width", "height", "preserveAspectRatio")

#: Attributes of an ``<image>`` that describe where this occurrence sits and stay
#: on the ``<use>`` element.
_ICON_PLACEMENT_ATTRIBUTES: Tuple[str, ...] = ("x", "y", "transform")


def _qualified(namespace: str, tag: str) -> str:
    """Return the ``{namespace}tag`` form ``xml.etree`` uses internally."""
    return f"{{{namespace}}}{tag}"


def _local_name(tag: Any) -> str:
    """Return the local name of a possibly namespaced element tag."""
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def _icon_href(element: ET.Element) -> Optional[str]:
    """Return the icon reference of an ``<image>``, namespaced or plain."""
    for name in (_qualified(XLINK_NAMESPACE, "href"), "href", "xlink:href"):
        value = element.get(name)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _read_icon_file(path: str) -> bytes:
    """Default icon reader: read the bytes of one icon file from disk."""
    with open(path, "rb") as handle:
        return handle.read()


def _icon_data_uri(href: str, read_icon: Callable[[str], bytes]) -> str:
    """Return the ``data:`` URI of one icon, or the href when it is already one.

    An href that is already a data URI or a remote URL carries no filesystem path
    of the generating machine, so it is left exactly as it is.
    """
    lowered = href.strip().lower()
    if lowered.startswith(("data:", "http://", "https://")):
        return href

    payload = read_icon(href)
    if not isinstance(payload, (bytes, bytearray)):
        raise ValueError(f"icon reader returned {type(payload).__name__} for {href}")
    mime = _ICON_MIME_TYPES.get(os.path.splitext(href)[1].lower(), _ICON_MIME_FALLBACK)
    return f"data:{mime};base64,{base64.b64encode(bytes(payload)).decode('ascii')}"


def embed_svg_icons(svg_text: str, *, read_icon: Callable[[str], bytes] = _read_icon_file) -> str:
    """Rewrite every ``<image>`` of an Interaction_Layer into a ``<use>``.

    Every ``<image>`` is grouped by ``(href, width, height, preserveAspectRatio)``,
    one ``<image>`` per group is hoisted into ``<defs>`` as a ``data:`` URI with the
    identifier ``ch-icon-<n>``, and each occurrence becomes
    ``<use xlink:href="#ch-icon-<n>" x=… y=…/>``. No filesystem path of the
    generating machine survives the rewrite, which is what Requirement 3.7 asks
    for, and an icon drawn N times is carried once.

    Only element identity is touched. The ``<title>`` elements the Inspector_Key
    lookup reads are left exactly as Graphviz wrote them, and no attribute value of
    any resource is added to the document — the layer carries identity, the payload
    carries configuration (Requirement 11.10).

    Failure is loud and total rather than partial: text that is not well-formed XML
    and an icon the reader cannot read both raise after a warning naming the cause,
    so the caller discards the SVG instead of shipping one that carries absolute
    paths or half a rewrite.

    Args:
        svg_text: The SVG document Graphviz wrote.
        read_icon: Reader returning the bytes of one icon, given its href.

    Returns:
        The rewritten SVG text. An SVG carrying no ``<image>`` is returned unchanged.

    Raises:
        ValueError: The text is not well-formed XML, or an icon could not be read.
    """
    if not isinstance(svg_text, str) or not svg_text.strip():
        raise ValueError("the Interaction_Layer SVG text is empty")

    try:
        root = ET.fromstring(svg_text)
    except ET.ParseError as error:
        logger.warning(f"The Interaction_Layer SVG is not well-formed XML: {error}")
        raise ValueError(f"malformed Interaction_Layer SVG: {error}") from error

    # Materialised before any rewrite, so mutating an element cannot disturb the walk.
    occurrences = [element for element in root.iter() if _local_name(element.tag) == "image"]
    if not occurrences:
        return svg_text

    groups: Dict[Tuple[str, ...], str] = {}
    defs = ET.Element(_qualified(SVG_NAMESPACE, "defs"))

    for element in occurrences:
        href = _icon_href(element)
        if href is None:
            logger.warning("An Interaction_Layer <image> carries no icon reference")
            raise ValueError("Interaction_Layer <image> without an icon reference")

        group_key = (href,) + tuple(element.get(name) or "" for name in _ICON_GROUP_ATTRIBUTES)
        icon_id = groups.get(group_key)
        if icon_id is None:
            icon_id = f"{ICON_ID_PREFIX}{len(groups)}"
            groups[group_key] = icon_id
            try:
                data_uri = _icon_data_uri(href, read_icon)
            except (OSError, ValueError, TypeError) as error:
                logger.warning(f"Interaction_Layer icon {href} could not be embedded: {error}")
                raise ValueError(f"unreadable Interaction_Layer icon {href}: {error}") from error
            hoisted = ET.SubElement(defs, _qualified(SVG_NAMESPACE, "image"))
            hoisted.set("id", icon_id)
            hoisted.set(_qualified(XLINK_NAMESPACE, "href"), data_uri)
            for name in _ICON_GROUP_ATTRIBUTES:
                value = element.get(name)
                if value:
                    hoisted.set(name, value)

        placement = {
            name: element.get(name) for name in _ICON_PLACEMENT_ATTRIBUTES if element.get(name)
        }
        element.tag = _qualified(SVG_NAMESPACE, "use")
        element.attrib.clear()
        element.set(_qualified(XLINK_NAMESPACE, "href"), f"#{icon_id}")
        for name, value in placement.items():
            element.set(name, value)

    root.insert(0, defs)
    ET.register_namespace("", SVG_NAMESPACE)
    ET.register_namespace("xlink", XLINK_NAMESPACE)
    return _XML_DECLARATION + ET.tostring(root, encoding="unicode")


def write_svg_with_embedded_icons(
    svg_path: str,
    *,
    read_icon: Optional[Callable[[str], bytes]] = None,
) -> Optional[str]:
    """Rewrite the Interaction_Layer in place, or discard it with a warning.

    The file is read, put through :func:`embed_svg_icons`, written to a sibling
    temporary file and moved into place, so a reader never sees a half-rewritten
    layer. When the rewrite fails — unreadable icon, malformed XML, unreadable or
    unwritable file — the SVG is **removed** rather than left behind: a layer
    carrying absolute filesystem paths is exactly what Requirement 3.7 forbids, and
    the PNG the run returns is unaffected either way (Requirement 1.9).

    Icon hrefs are resolved relative to the SVG's own folder when they are not
    absolute, which is where the render pass writes both.

    Args:
        svg_path: Path of the SVG Graphviz wrote.
        read_icon: Optional reader override, for tests and for callers that resolve
            icons through something other than the filesystem.

    Returns:
        ``svg_path`` when the layer was rewritten, ``None`` when it was discarded.
    """
    folder = os.path.dirname(os.path.abspath(svg_path))

    def _resolve(href: str) -> bytes:
        candidate = href if os.path.isabs(href) else os.path.join(folder, href)
        return _read_icon_file(candidate)

    reader = read_icon if read_icon is not None else _resolve
    temporary = f"{svg_path}.tmp"

    try:
        with open(svg_path, "r", encoding="utf-8") as handle:
            svg_text = handle.read()
        rewritten = embed_svg_icons(svg_text, read_icon=reader)
        with open(temporary, "w", encoding="utf-8") as handle:
            handle.write(rewritten)
        os.replace(temporary, svg_path)
    except Exception as error:  # noqa: BLE001 - the layer is optional, the PNG is not
        logger.warning(f"Interaction_Layer {svg_path} was discarded: {error}")
        _discard_partial(temporary)
        _discard_partial(svg_path)
        return None

    return svg_path
