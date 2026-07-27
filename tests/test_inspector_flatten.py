"""Unit tests for the Inspector flattening and scalar rendering rules.

Feature: interactive-resource-inspector

Covers the documented behaviours of ``flatten_values`` (Requirements 5.3, 5.8,
12.4, 13.10, 13.11), ``render_scalar`` (Requirements 5.7, 12.3, 13.9), and the
Row_Bound and record-assembly rules of ``apply_bounds`` and ``build_record``
(Requirements 4.9, 12.2, 12.5). The property-based coverage of the same
functions lives in the Property 2, 3 and 12 tests of this file.
"""

import datetime
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.inspector import (  # noqa: E402
    DEPTH_REASON,
    MAX_ATTRIBUTE_ROWS,
    MAX_SCALAR_CHARS,
    MAX_TREE_DEPTH,
    ROOT_PATH,
    ROWS_REASON,
    TRUNCATION_MARKER,
    VALUE_REASON,
    AttributeEntry,
    InspectorIdentity,
    apply_bounds,
    build_record,
    flatten_values,
    is_replacement,
    render_scalar,
)

# ─── flatten_values: path grammar (Requirement 5.3) ───────────────────────────


def test_flatten_joins_map_keys_with_dots():
    """Nested map keys become dot-joined Attribute_Path segments."""
    flat = flatten_values({"site_config": {"application_stack": {"node_version": "18"}}})

    assert flat == {"site_config.application_stack.node_version": "18"}


def test_flatten_writes_list_indices_as_zero_based_segments():
    """List positions become zero-based decimal segments of the Attribute_Path."""
    flat = flatten_values({"stack": [{"node_version": "18"}, {"node_version": "20"}]})

    assert flat == {
        "stack.0.node_version": "18",
        "stack.1.node_version": "20",
    }


def test_flatten_keeps_a_key_holding_a_dot_verbatim():
    """A key carrying a literal ``.`` is written verbatim, the documented limitation."""
    flat = flatten_values({"tags": {"my.key": "value"}})

    assert flat == {"tags.my.key": "value"}


def test_flatten_of_an_empty_snapshot_is_empty():
    """Two empty Config_Snapshots must produce a record with no Attribute_Entries."""
    assert flatten_values({}) == {}


def test_flatten_reports_a_non_container_snapshot_at_the_root_path():
    """A scalar supplied where a tree is expected is reported, not dropped."""
    assert flatten_values("not-a-tree") == {ROOT_PATH: "not-a-tree"}


# ─── flatten_values: empty containers (Requirement 5.8) ──────────────────────


def test_flatten_emits_empty_map_and_empty_list_at_their_own_path():
    """An empty map and an empty list are leaves that render as ``{}`` and ``[]``."""
    flat = flatten_values({"tags": {}, "zones": [], "name": "web"})

    assert flat == {"tags": {}, "zones": [], "name": "web"}
    assert render_scalar(flat["tags"]) == "{}"
    assert render_scalar(flat["zones"]) == "[]"


# ─── flatten_values: non-string keys (Requirement 13.10) ─────────────────────


@pytest.mark.parametrize(
    "key, segment",
    [
        (7, "7"),
        (True, "True"),
        (None, "None"),
        (2.5, "2.5"),
        (("a", 1), "('a', 1)"),
    ],
)
def test_flatten_renders_a_non_string_key_through_str(key, segment):
    """A key that is not a string becomes ``str(key)``, used verbatim as the segment."""
    flat = flatten_values({"outer": {key: "leaf"}})

    assert flat == {f"outer.{segment}": "leaf"}


# ─── flatten_values: Depth_Bound (Requirement 12.4) ──────────────────────────


def _chain(depth: int) -> dict:
    """A single map chain ``level0.level1…`` ending in a scalar leaf."""
    node: object = "bottom"
    for level in reversed(range(depth)):
        node = {f"level{level}": node}
    return node  # type: ignore[return-value]


def test_flatten_collapses_a_branch_past_the_depth_bound():
    """The container at depth 12 collapses to the marker and the deeper leaves go."""
    reasons: set = set()

    flat = flatten_values(_chain(MAX_TREE_DEPTH + 4), reasons=reasons)

    assert len(flat) == 1
    path, value = next(iter(flat.items()))
    assert len(path.split(".")) == MAX_TREE_DEPTH
    assert value == TRUNCATION_MARKER
    assert reasons == {DEPTH_REASON}


def test_flatten_leaves_a_branch_at_the_depth_bound_untouched():
    """A leaf sitting exactly at the Depth_Bound is emitted with its real value."""
    reasons: set = set()

    flat = flatten_values(_chain(MAX_TREE_DEPTH), reasons=reasons)

    assert list(flat.values()) == ["bottom"]
    assert len(next(iter(flat)).split(".")) == MAX_TREE_DEPTH
    assert reasons == set()


def test_flatten_honours_a_caller_supplied_max_depth():
    """``max_depth`` is a parameter, so a caller can bound a walk more tightly."""
    reasons: set = set()

    flat = flatten_values({"a": {"b": {"c": "leaf"}}}, max_depth=2, reasons=reasons)

    assert flat == {"a.b": TRUNCATION_MARKER}
    assert reasons == {DEPTH_REASON}


def test_flatten_reports_no_depth_reason_without_an_accumulator():
    """``reasons`` is optional: omitting it discards the report, nothing raises."""
    assert flatten_values(_chain(MAX_TREE_DEPTH + 2)) != {}


# ─── flatten_values: enclosing subtrees (Requirement 13.11) ──────────────────


def test_flatten_terminates_on_a_self_referential_map():
    """A subtree repeating its own ancestor collapses to the marker, walk terminates."""
    cyclic: dict = {"name": "web"}
    cyclic["self"] = cyclic

    flat = flatten_values({"resource": cyclic})

    assert flat == {
        "resource.name": "web",
        "resource.self": TRUNCATION_MARKER,
    }


def test_flatten_terminates_on_a_cycle_that_runs_through_a_list():
    """The ancestor guard covers lists as well as maps."""
    cyclic: dict = {"name": "web"}
    cyclic["via_list"] = [cyclic]

    flat = flatten_values({"resource": cyclic})

    assert flat == {
        "resource.name": "web",
        "resource.via_list.0": TRUNCATION_MARKER,
    }


def test_flatten_expands_a_shared_sibling_subtree_in_both_places():
    """A dict reused as a *sibling* encloses nothing, so both copies flatten fully."""
    shared = {"tier": "standard", "capacity": 2}

    flat = flatten_values({"left": shared, "right": {"nested": shared}})

    assert flat == {
        "left.tier": "standard",
        "left.capacity": 2,
        "right.nested.tier": "standard",
        "right.nested.capacity": 2,
    }


def test_flatten_expands_a_subtree_reused_after_the_walk_left_it():
    """A subtree revisited once it is off the ancestor stack is not a repeat."""
    shared = {"k": "v"}

    flat = flatten_values({"a": {"inner": shared}, "b": [shared, shared]})

    assert flat == {
        "a.inner.k": "v",
        "b.0.k": "v",
        "b.1.k": "v",
    }


def test_flatten_records_no_truncation_reason_for_a_cycle_collapse():
    """The Truncation_Reason set is closed over the Value_Bounds; a cycle is not one."""
    cyclic: dict = {}
    cyclic["self"] = cyclic
    reasons: set = set()

    flatten_values({"resource": cyclic}, reasons=reasons)

    assert reasons == set()


# ─── render_scalar: JSON rendering (Requirement 5.7) ─────────────────────────


def test_render_scalar_passes_a_string_through_verbatim():
    """A string leaf is its own display text, unquoted."""
    assert render_scalar("westeurope") == "westeurope"


@pytest.mark.parametrize(
    "value, rendered",
    [
        (True, "true"),
        (False, "false"),
        (None, "null"),
        (42, "42"),
        (1.5, "1.5"),
        ({}, "{}"),
        ([], "[]"),
        ([1, "a"], '[1, "a"]'),
        ({"b": 1, "a": 2}, '{"a": 2, "b": 1}'),
    ],
)
def test_render_scalar_renders_a_non_string_leaf_as_json(value, rendered):
    """A leaf that is not a string is rendered as its JSON representation."""
    assert render_scalar(value) == rendered


def test_render_scalar_keeps_non_ascii_text_unescaped():
    """JSON rendering stays readable: no ``\\uXXXX`` escapes in the panel."""
    assert render_scalar(["café"]) == '["café"]'


# ─── render_scalar: JSON fallback (Requirement 13.9) ─────────────────────────


class _Unserializable:
    def __str__(self) -> str:
        return "custom-object"


@pytest.mark.parametrize(
    "value, rendered",
    [
        ({1, 2}, None),
        (datetime.date(2026, 7, 26), "2026-07-26"),
        (b"\x00\xffbytes", None),
        (_Unserializable(), "custom-object"),
    ],
)
def test_render_scalar_falls_back_to_str_for_an_unserializable_value(value, rendered):
    """A value the JSON serializer refuses is rendered through ``str(value)``."""
    with pytest.raises(TypeError):
        json.dumps(value)

    text = render_scalar(value)

    assert text == (rendered if rendered is not None else str(value))


def test_render_scalar_falls_back_for_a_container_holding_an_unserializable_leaf():
    """The fallback covers a nested failure, not just a top-level one."""
    value = {"when": datetime.date(2026, 7, 26)}

    assert render_scalar(value) == str(value)


# ─── render_scalar: Scalar_Bound (Requirement 12.3) ──────────────────────────


def test_render_scalar_truncates_past_the_scalar_bound():
    """Past 2048 characters the text is cut to 2048 and the marker is appended."""
    reasons: set = set()

    text = render_scalar("a" * (MAX_SCALAR_CHARS + 50), reasons=reasons)

    assert text == "a" * MAX_SCALAR_CHARS + TRUNCATION_MARKER
    assert reasons == {VALUE_REASON}


def test_render_scalar_leaves_a_value_at_the_scalar_bound_untouched():
    """Exactly 2048 characters is inside the bound, so nothing is appended."""
    reasons: set = set()

    text = render_scalar("a" * MAX_SCALAR_CHARS, reasons=reasons)

    assert text == "a" * MAX_SCALAR_CHARS
    assert reasons == set()


def test_render_scalar_truncates_a_json_rendered_value_too():
    """The bound applies to the rendered text, not to the input type."""
    reasons: set = set()

    text = render_scalar(["b" * MAX_SCALAR_CHARS], reasons=reasons)

    assert text.endswith(TRUNCATION_MARKER)
    assert len(text) == MAX_SCALAR_CHARS + len(TRUNCATION_MARKER)
    assert reasons == {VALUE_REASON}


def test_render_scalar_honours_a_caller_supplied_max_chars():
    """``max_chars`` is a parameter, so a caller can bound a value more tightly."""
    reasons: set = set()

    assert render_scalar("abcdef", max_chars=3, reasons=reasons) == "abc" + TRUNCATION_MARKER
    assert reasons == {VALUE_REASON}


# ─── Shared reason accumulator across both functions ─────────────────────────


def test_both_functions_report_into_one_accumulator():
    """``build_record`` collects depth and value reasons for a record in one set."""
    reasons: set = set()
    tree = {"deep": _chain(MAX_TREE_DEPTH + 2), "long": "x" * (MAX_SCALAR_CHARS + 1)}

    flat = flatten_values(tree, reasons=reasons)
    for value in flat.values():
        render_scalar(value, reasons=reasons)

    assert reasons == {DEPTH_REASON, VALUE_REASON}


# ─── apply_bounds: Row_Bound (Requirements 12.2, 12.5) ───────────────────────


def _entry(path: str, state: str = "unchanged") -> AttributeEntry:
    """One Attribute_Entry with the given path and state."""
    return AttributeEntry(
        path=path,
        state=state,
        before="a",
        after="a" if state == "unchanged" else "b",
    )


def _paths(entries) -> list:
    """The Attribute_Paths of an entry list, in order."""
    return [entry.path for entry in entries]


def test_apply_bounds_preserves_the_input_order_under_the_cap():
    """Inside the Row_Bound the input sequence is returned untouched."""
    entries = [
        _entry("zone", "changed"),
        _entry("alpha"),
        _entry("beta", "added"),
    ]
    reasons: set = set()

    kept, omitted = apply_bounds(entries, reasons=reasons)

    assert kept == entries
    assert omitted == 0
    assert reasons == set()


def test_apply_bounds_keeps_an_entry_list_exactly_at_the_cap():
    """500 entries is inside the bound: nothing is dropped and nothing is reordered."""
    entries = [_entry(f"attr{index:04d}") for index in range(MAX_ATTRIBUTE_ROWS)]
    reasons: set = set()

    kept, omitted = apply_bounds(entries, reasons=reasons)

    assert kept == entries
    assert omitted == 0
    assert reasons == set()


def test_apply_bounds_keeps_changed_rows_first_and_fills_with_unchanged():
    """Over the cap, non-``unchanged`` rows are retained, then ascending filler."""
    entries = [_entry(f"u{index:04d}") for index in range(6)]
    entries.insert(3, _entry("z-changed", "changed"))
    entries.insert(0, _entry("y-removed", "removed"))
    reasons: set = set()

    kept, omitted = apply_bounds(entries, max_rows=4, reasons=reasons)

    assert _paths(kept) == ["y-removed", "z-changed", "u0000", "u0001"]
    assert omitted == len(entries) - 4
    assert reasons == {ROWS_REASON}


def test_apply_bounds_cuts_the_changed_block_when_it_exceeds_the_cap():
    """More changed rows than the bound: ascending cut, no filler at all."""
    entries = [_entry(f"c{index:04d}", "changed") for index in reversed(range(5))]
    entries.append(_entry("a-unchanged"))
    reasons: set = set()

    kept, omitted = apply_bounds(entries, max_rows=3, reasons=reasons)

    assert _paths(kept) == ["c0000", "c0001", "c0002"]
    assert omitted == 3
    assert reasons == {ROWS_REASON}


def test_apply_bounds_enforces_the_default_row_bound():
    """The default bound is 500, and the omitted count reports the rest."""
    entries = [_entry(f"attr{index:04d}") for index in range(MAX_ATTRIBUTE_ROWS + 25)]

    kept, omitted = apply_bounds(entries)

    assert len(kept) == MAX_ATTRIBUTE_ROWS
    assert omitted == 25
    assert _paths(kept) == sorted(_paths(kept))


def test_apply_bounds_reports_no_rows_reason_without_an_accumulator():
    """``reasons`` is optional: omitting it discards the report, nothing raises."""
    entries = [_entry(f"attr{index}") for index in range(4)]

    assert apply_bounds(entries, max_rows=2) == (entries[:2], 2)


# ─── build_record: identity, bounds and reporting (Requirement 12.5) ──────────


def _identity(change_category=None) -> InspectorIdentity:
    """An identity header for a node-drawn resource."""
    return InspectorIdentity(
        key="api-web-rg-app",
        kind="node",
        name="api-web",
        resource_type="Microsoft.Web/sites",
        resource_group="rg-app",
        address="module.app.azurerm_linux_web_app.api",
        change_category=change_category,
    )


def test_build_record_carries_the_identity_header_and_the_entries():
    """The identity fields are copied verbatim and the diff becomes the entry list."""
    record = build_record(_identity("update"), {"https_only": False}, {"https_only": True})

    assert (record.key, record.kind, record.name) == ("api-web-rg-app", "node", "api-web")
    assert record.resource_type == "Microsoft.Web/sites"
    assert record.resource_group == "rg-app"
    assert record.address == "module.app.azurerm_linux_web_app.api"
    assert record.change_category == "update"
    assert [(entry.path, entry.state) for entry in record.attributes] == [
        ("https_only", "changed")
    ]
    assert record.omitted_attributes == 0
    assert record.truncations == []


def test_build_record_of_two_empty_snapshots_still_yields_a_record():
    """An element with nothing to show gets a header and an empty attribute list."""
    record = build_record(_identity(), {}, {})

    assert record.attributes == []
    assert record.omitted_attributes == 0
    assert record.truncations == []


def test_build_record_reports_the_rows_reason_and_the_omitted_count():
    """Over the Row_Bound: entries capped, count reported, ``rows`` recorded."""
    snapshot = {f"attr{index:04d}": index for index in range(MAX_ATTRIBUTE_ROWS + 10)}

    record = build_record(_identity(), snapshot, snapshot)

    assert len(record.attributes) == MAX_ATTRIBUTE_ROWS
    assert record.omitted_attributes == 10
    assert record.truncations == [ROWS_REASON]


def test_build_record_reports_only_the_value_reason_for_a_long_scalar():
    """A cut value records ``value`` and nothing else."""
    record = build_record(_identity(), {}, {"script": "x" * (MAX_SCALAR_CHARS + 1)})

    assert record.truncations == [VALUE_REASON]
    assert record.attributes[0].after.endswith(TRUNCATION_MARKER)


def test_build_record_reports_only_the_depth_reason_for_a_deep_subtree():
    """A collapsed subtree records ``depth`` and nothing else."""
    record = build_record(_identity(), {}, _chain(MAX_TREE_DEPTH + 2))

    assert record.truncations == [DEPTH_REASON]


def test_build_record_reports_every_applied_reason_in_canonical_order():
    """All three bounds applied: ``truncations`` is ordered value, depth, rows."""
    snapshot = {f"attr{index:04d}": index for index in range(MAX_ATTRIBUTE_ROWS + 5)}
    snapshot["deep"] = _chain(MAX_TREE_DEPTH + 2)
    snapshot["long"] = "y" * (MAX_SCALAR_CHARS + 1)

    record = build_record(_identity(), {}, snapshot)

    assert record.truncations == [VALUE_REASON, DEPTH_REASON, ROWS_REASON]
    assert record.omitted_attributes > 0


def test_build_record_reports_no_reason_when_no_bound_applied():
    """A record inside every bound carries an empty ``truncations`` list."""
    record = build_record(_identity(), {"location": "westeurope"}, {"location": "westeurope"})

    assert record.truncations == []
    assert record.omitted_attributes == 0


# ─── build_record: the replacement marker (Requirement 4.9) ───────────────────


@pytest.mark.parametrize(
    "category, expected",
    [
        ("replace", True),
        ("create", False),
        ("delete", False),
        ("update", False),
        ("unchanged", False),
        ("Replace", False),
        ("exploded", False),
        (None, False),
    ],
)
def test_build_record_sets_the_replacement_marker_only_for_replace(category, expected):
    """The marker is set exactly for the Change_Category ``replace``."""
    record = build_record(_identity(category), {"a": 1}, {"a": 2})

    assert record.replacement is expected
    assert is_replacement(category) is expected

# ─── Properties 2, 3 and 12 ───────────────────────────────────────────────────
#
# The generators are the shared ones of ``tests/strategies/inspector_trees.py``:
# ``bounded_trees()`` for the lossless round trip, ``snapshot_pairs()`` for the
# path union, ``unbounded_trees()`` for the Value_Bounds. Nothing is generated
# locally, so the input space stays owned by the strategy module.

from hypothesis import HealthCheck, given, settings  # noqa: E402

from core.inspector import UNCHANGED_STATE, diff_attributes  # noqa: E402
from strategies import inspector_trees  # noqa: E402
from strategies.inspector_trees import (  # noqa: E402
    bounded_trees,
    snapshot_pairs,
    unbounded_trees,
)

# ─── Property 3 reference model: unflattening ─────────────────────────────────


def _safe_key(key: str) -> str:
    """Constrain one map key to the input space Property 3 quantifies over.

    Property 3 asks for trees "whose map keys are strings holding no ``.``
    character", because a key carrying the path separator collides with the
    nesting it denotes — the documented limitation of Requirement 5.3. A key that
    is a decimal string is the same class of collision against a list index
    segment, so it is prefixed for the same reason.
    """
    cleaned = key.replace(".", "_")
    return f"k{cleaned}" if cleaned.isdigit() else cleaned


def _round_trippable(node):
    """Rewrite a drawn tree's map keys through :func:`_safe_key`, shape untouched."""
    if isinstance(node, dict):
        return {_safe_key(key): _round_trippable(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_round_trippable(item) for item in node]
    return node


def _unflatten(flat: dict):
    """Rebuild a tree from an ``{Attribute_Path: raw leaf}`` map.

    Each path is split on ``.``, every segment but the last opens a container, and
    the last one carries the raw leaf. A container whose segments are exactly the
    zero-based indices ``0…n-1`` is restored as a list, which is the inverse of
    the index-segment rule of Requirement 5.3.
    """
    root: dict = {}
    for path, leaf in flat.items():
        segments = path.split(".")
        node = root
        for segment in segments[:-1]:
            node = node.setdefault(segment, {})
        node[segments[-1]] = leaf
    return _restore_lists(root)


def _restore_lists(node):
    """Turn every index-keyed container of a rebuilt tree back into a list."""
    if not isinstance(node, dict) or not node:
        return node
    rebuilt = {key: _restore_lists(value) for key, value in node.items()}
    if set(rebuilt) == {str(index) for index in range(len(rebuilt))}:
        return [rebuilt[str(index)] for index in range(len(rebuilt))]
    return rebuilt


# Feature: interactive-resource-inspector, Property 3: For any attribute tree
# within the Value_Bounds whose map keys are strings holding no `.` character and
# whose lists hold no gaps, unflattening the result of `flatten_values`
# reconstructs the original tree, including empty maps rendered as `{}` and empty
# lists rendered as `[]` at their own Attribute_Path.
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(drawn=bounded_trees())
def test_property_flatten_round_trip(drawn):
    """Property 3: Flatten round trip.

    Flattening a Config_Snapshot inside the Value_Bounds loses nothing: the
    Attribute_Path grammar of Requirement 5.3 is invertible, and an empty map and
    an empty list survive as leaves at their own path that render as ``{}`` and
    ``[]`` (Requirement 5.8).

    **Validates: Requirements 5.3, 5.8, 14.3**
    """
    tree = _round_trippable(drawn)
    reasons: set = set()

    flat = flatten_values(tree, reasons=reasons)

    # Inside every bound, so no truncation may have applied.
    assert reasons == set()
    assert all(len(path.split(".")) <= MAX_TREE_DEPTH for path in flat)

    # The round trip: unflattening reconstructs the tree exactly.
    assert _unflatten(flat) == tree

    # Empty containers are leaves of their own, rendered as `{}` and `[]`.
    for path, leaf in flat.items():
        assert path
        if isinstance(leaf, dict):
            assert leaf == {}
            assert render_scalar(leaf) == "{}"
        elif isinstance(leaf, list):
            assert leaf == []
            assert render_scalar(leaf) == "[]"


# Feature: interactive-resource-inspector, Property 2: For any pair of
# Config_Snapshots within the Value_Bounds, the Attribute_Path sequence of the
# produced Attribute_Entry list equals the union of the Attribute_Paths of the
# two flattened snapshots in ascending lexicographic order — no input path is
# dropped, no path is invented, and no path appears twice.
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(pair=snapshot_pairs())
def test_property_path_coverage_and_ordering(pair):
    """Property 2: Path coverage and ordering.

    The Attribute_Entry list covers every leaf of either Config_Snapshot exactly
    once (Requirement 5.2) and arrives in ascending lexicographic Attribute_Path
    order (Requirement 5.4).

    **Validates: Requirements 5.2, 5.4, 14.2**
    """
    before, after = pair

    entries = diff_attributes(before, after)

    paths = [entry.path for entry in entries]
    expected = sorted(set(flatten_values(before)) | set(flatten_values(after)))

    assert paths == expected
    assert paths == sorted(paths)
    assert len(paths) == len(set(paths))


# ─── Property 12 reference model: the Row_Bound selection ─────────────────────


def _expected_kept(entries, max_rows=MAX_ATTRIBUTE_ROWS):
    """The entries the Row_Bound must retain: changed block, then filler."""
    if len(entries) <= max_rows:
        return list(entries)
    changed = sorted(
        (entry for entry in entries if entry.state != UNCHANGED_STATE),
        key=lambda entry: entry.path,
    )
    unchanged = sorted(
        (entry for entry in entries if entry.state == UNCHANGED_STATE),
        key=lambda entry: entry.path,
    )
    kept = changed[:max_rows]
    kept.extend(unchanged[: max_rows - len(kept)])
    return kept


def _expected_reasons(before, after, entry_count):
    """The Truncation_Reasons the two Value_Bound-reporting primitives raise."""
    reasons: set = set()
    for tree in (before, after):
        for leaf in flatten_values(tree, reasons=reasons).values():
            render_scalar(leaf, reasons=reasons)
    if entry_count > MAX_ATTRIBUTE_ROWS:
        reasons.add(ROWS_REASON)
    return [reason for reason in (VALUE_REASON, DEPTH_REASON, ROWS_REASON) if reason in reasons]


# Feature: interactive-resource-inspector, Property 12: For any attribute tree
# pair, every rendered value of the resulting Inspector_Record is at most the
# Scalar_Bound of 2048 characters plus the Truncation_Marker, every
# Attribute_Path holds at most the Depth_Bound of 12 segments, the
# Attribute_Entry count is at most the Row_Bound of 500, the retained entries
# under the Row_Bound are all entries whose Attribute_State differs from
# `unchanged` followed by the remainder in ascending Attribute_Path order,
# `omittedAttributes` equals the number of dropped entries, `truncations` holds
# `value`, `depth` and `rows` exactly when the corresponding bound applied, and
# the Inspector_Index reports the three bounds the run used.
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
@given(before=unbounded_trees(), after=unbounded_trees())
def test_property_bound_enforcement_and_reporting(before, after):
    """Property 12: Bound enforcement and reporting.

    Every Value_Bound holds on the assembled Inspector_Record, the Row_Bound
    keeps the rows that carry a change ahead of the ``unchanged`` filler, the
    omitted count matches what was dropped, and the applied Truncation_Reasons
    are reported exactly (Requirements 12.2 to 12.5, 12.10).

    **Validates: Requirements 12.2, 12.3, 12.4, 12.5, 12.10, 14.12**
    """
    record = build_record(_identity("update"), before, after)

    # Scalar_Bound: no rendered value exceeds 2048 characters plus the marker.
    for entry in record.attributes:
        for value in (entry.before, entry.after):
            if value is None:
                continue
            assert len(value) <= MAX_SCALAR_CHARS + len(TRUNCATION_MARKER)
            if len(value) > MAX_SCALAR_CHARS:
                assert value.endswith(TRUNCATION_MARKER)

    # Depth_Bound: no Attribute_Path holds more than 12 segments.
    assert all(len(entry.path.split(".")) <= MAX_TREE_DEPTH for entry in record.attributes)

    # Row_Bound: the count, the retained selection and the omitted count.
    full = diff_attributes(before, after)
    assert len(record.attributes) <= MAX_ATTRIBUTE_ROWS
    assert record.attributes == _expected_kept(full)
    assert record.omitted_attributes == len(full) - len(record.attributes)

    # The retained order is the non-``unchanged`` block, then ascending filler.
    if record.omitted_attributes:
        states = [entry.state for entry in record.attributes]
        split = states.index(UNCHANGED_STATE) if UNCHANGED_STATE in states else len(states)
        changed_block = record.attributes[:split]
        filler_block = record.attributes[split:]
        assert all(entry.state != UNCHANGED_STATE for entry in changed_block)
        assert all(entry.state == UNCHANGED_STATE for entry in filler_block)
        assert _paths(changed_block) == sorted(_paths(changed_block))
        assert _paths(filler_block) == sorted(_paths(filler_block))

    # Reporting: exactly the reasons the two bound-reporting primitives raise.
    assert record.truncations == _expected_reasons(before, after, len(full))

    # The three bounds the run used, which the Inspector_Index carries verbatim.
    assert (MAX_ATTRIBUTE_ROWS, MAX_SCALAR_CHARS, MAX_TREE_DEPTH) == (500, 2048, 12)
    assert (
        inspector_trees.MAX_ATTRIBUTE_ROWS,
        inspector_trees.MAX_SCALAR_CHARS,
        inspector_trees.MAX_TREE_DEPTH,
    ) == (MAX_ATTRIBUTE_ROWS, MAX_SCALAR_CHARS, MAX_TREE_DEPTH)
