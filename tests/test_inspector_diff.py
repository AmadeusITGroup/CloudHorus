"""Unit tests for the Inspector Attribute_Differ.

Feature: interactive-resource-inspector

Covers the decision table of ``diff_attributes`` (Requirements 7.1-7.5), its path
coverage and ordering (Requirements 5.2, 5.4), the unknown mask consumed into the
Unknown_Marker (Requirement 6.6), and the redacted-on-both-sides classification
(Requirement 11.7). The property-based coverage of the same function — Properties
1, 4, 6 and 7 — lives in this file too.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.inspector import (  # noqa: E402
    ATTRIBUTE_STATES,
    MAX_SCALAR_CHARS,
    MAX_TREE_DEPTH,
    REDACTION_LITERAL,
    ROOT_PATH,
    TRUNCATION_MARKER,
    UNKNOWN_MARKER,
    VALUE_REASON,
    AttributeEntry,
    diff_attributes,
)


def _by_path(entries):
    """Index an Attribute_Entry list by Attribute_Path for assertion convenience."""
    return {entry.path: entry for entry in entries}


# ─── Decision table (Requirements 7.1, 7.2, 7.3, 7.4, 7.5) ───────────────────


def test_diff_assigns_every_state_of_the_decision_table():
    """One pair drives all four Attribute_States through the reference table."""
    before = {"gone": "old", "same": "westeurope", "moved": "false"}
    after = {"new": "true", "same": "westeurope", "moved": "true"}

    entries = _by_path(diff_attributes(before, after))

    assert entries["new"] == AttributeEntry(path="new", state="added", after="true")
    assert entries["gone"] == AttributeEntry(path="gone", state="removed", before="old")
    assert entries["moved"] == AttributeEntry(
        path="moved", state="changed", before="false", after="true"
    )
    assert entries["same"] == AttributeEntry(
        path="same", state="unchanged", before="westeurope", after="westeurope"
    )


def test_diff_assigns_exactly_one_state_from_the_closed_set():
    """Every entry carries one Attribute_State drawn from the closed set."""
    entries = diff_attributes({"a": 1, "b": 2}, {"b": 3, "c": 4})

    assert [entry.state for entry in entries] == ["removed", "changed", "added"]
    assert all(entry.state in ATTRIBUTE_STATES for entry in entries)


def test_diff_of_an_empty_before_snapshot_is_all_added():
    """A `create` resource: an empty before phase makes every path `added`."""
    entries = diff_attributes({}, {"name": "web", "tags": {"owner": "platform"}})

    assert [(entry.path, entry.state, entry.before, entry.after) for entry in entries] == [
        ("name", "added", None, "web"),
        ("tags.owner", "added", None, "platform"),
    ]


def test_diff_of_an_empty_after_snapshot_is_all_removed():
    """A `delete` resource: an empty after phase makes every path `removed`."""
    entries = diff_attributes({"name": "web", "zones": []}, {})

    assert [(entry.path, entry.state, entry.before, entry.after) for entry in entries] == [
        ("name", "removed", "web", None),
        ("zones", "removed", "[]", None),
    ]


def test_diff_of_two_empty_snapshots_is_empty():
    """Two empty Config_Snapshots produce a record with no Attribute_Entries."""
    assert diff_attributes({}, {}) == []


def test_diff_of_a_snapshot_against_itself_is_all_unchanged():
    """The identity diff of Requirement 6.5 leaves every path `unchanged`."""
    snapshot = {"name": "web", "tags": {"owner": "platform"}, "zones": [1, 2]}

    entries = diff_attributes(snapshot, snapshot)

    assert {entry.state for entry in entries} == {"unchanged"}
    assert all(entry.before == entry.after for entry in entries)


def test_diff_classifies_a_container_against_a_scalar_as_changed():
    """A path holding a container in one phase and a scalar in the other is comparable."""
    entries = _by_path(diff_attributes({"tags": {}}, {"tags": "opaque"}))

    assert entries["tags"].state == "changed"
    assert (entries["tags"].before, entries["tags"].after) == ("{}", "opaque")


def test_diff_treats_a_type_only_difference_as_unchanged():
    """The comparison is on the rendered text the panel shows, not on the raw type."""
    entries = _by_path(diff_attributes({"count": 1, "flag": True}, {"count": "1", "flag": "true"}))

    assert entries["count"].state == "unchanged"
    assert entries["flag"].state == "unchanged"


def test_diff_reports_a_non_container_snapshot_at_the_root_path():
    """A scalar supplied where a tree is expected is diffed at the root path."""
    entries = diff_attributes("old", "new")

    assert entries == [AttributeEntry(path=ROOT_PATH, state="changed", before="old", after="new")]


# ─── Path coverage and ordering (Requirements 5.2, 5.4) ──────────────────────


def test_diff_emits_the_union_of_paths_in_ascending_lexicographic_order():
    """The entry sequence is the union of both flattened snapshots, sorted."""
    before = {"zone": "1", "app": {"b": 1, "a": 2}}
    after = {"middle": "x", "app": {"a": 2}}

    paths = [entry.path for entry in diff_attributes(before, after)]

    assert paths == ["app.a", "app.b", "middle", "zone"]
    assert paths == sorted(paths)


def test_diff_emits_one_entry_per_path_with_no_duplicates():
    """No path is dropped, invented, or emitted twice."""
    before = {"a": {"b": [1, 2]}, "c": "x"}
    after = {"a": {"b": [1, 9, 3]}, "d": "y"}

    paths = [entry.path for entry in diff_attributes(before, after)]

    assert paths == ["a.b.0", "a.b.1", "a.b.2", "c", "d"]
    assert len(paths) == len(set(paths))


def test_diff_orders_list_indices_lexicographically_not_numerically():
    """Ordering is lexicographic on the Attribute_Path, which is the documented rule."""
    snapshot = {"ips": list(range(11))}

    paths = [entry.path for entry in diff_attributes(snapshot, snapshot)]

    assert paths[:3] == ["ips.0", "ips.1", "ips.10"]


# ─── Unknown mask (Requirement 6.6) ──────────────────────────────────────────


def test_diff_sets_the_unknown_marker_as_the_after_value():
    """A flagged path carries the Unknown_Marker as its After_Value."""
    entries = _by_path(
        diff_attributes(
            {"ip": "20.1.2.3", "name": "web"},
            {"ip": None, "name": "web"},
            unknown={"ip": True},
        )
    )

    assert entries["ip"] == AttributeEntry(
        path="ip", state="changed", before="20.1.2.3", after=UNKNOWN_MARKER
    )
    assert entries["name"].state == "unchanged"


def test_diff_marks_a_flagged_path_absent_from_the_after_snapshot_as_changed():
    """A flagged path counts as present after, so it reads `changed`, not `removed`."""
    entries = _by_path(diff_attributes({"ip": "20.1.2.3"}, {}, unknown={"ip": True}))

    assert entries["ip"].state == "changed"
    assert entries["ip"].after == UNKNOWN_MARKER


def test_diff_marks_a_flagged_path_absent_from_both_phases_nowhere():
    """The mask introduces no Attribute_Path of its own."""
    entries = diff_attributes({"name": "web"}, {"name": "web"}, unknown={"ip": True})

    assert [entry.path for entry in entries] == ["name"]


def test_diff_applies_a_container_level_flag_to_every_path_beneath_it():
    """A mask flagging a whole container marks each of the container's leaves."""
    entries = _by_path(
        diff_attributes(
            {"site": {"host": "old", "nested": {"port": 80}}, "name": "web"},
            {"site": {"host": "old", "nested": {"port": 80}}, "name": "web"},
            unknown={"site": True},
        )
    )

    assert entries["site.host"].after == UNKNOWN_MARKER
    assert entries["site.nested.port"].after == UNKNOWN_MARKER
    assert entries["name"].after == "web"


def test_diff_applies_a_flag_inside_a_list_by_index():
    """A mask aligned with a list flags exactly the flagged position."""
    entries = _by_path(
        diff_attributes(
            {"ips": ["10.0.0.1", "10.0.0.2"]},
            {"ips": ["10.0.0.1", "10.0.0.2"]},
            unknown={"ips": [False, True]},
        )
    )

    assert entries["ips.0"].after == "10.0.0.1"
    assert entries["ips.1"].after == UNKNOWN_MARKER


@pytest.mark.parametrize("mask", [None, {}, {"ip": False}, {"ip": "yes"}, {"ip": 1}])
def test_diff_treats_a_non_true_mask_leaf_as_not_flagged(mask):
    """Only an exact ``True`` flags a path; nothing else may fabricate the marker."""
    entries = _by_path(diff_attributes({"ip": "20.1.2.3"}, {"ip": "20.1.2.3"}, unknown=mask))

    assert entries["ip"].after == "20.1.2.3"
    assert entries["ip"].state == "unchanged"


def test_diff_honours_a_mask_flagged_at_the_root():
    """A mask that is a bare ``True`` marks every path of the resource."""
    entries = diff_attributes({"a": 1, "b": {"c": 2}}, {"a": 1, "b": {"c": 2}}, unknown=True)

    assert {entry.after for entry in entries} == {UNKNOWN_MARKER}
    assert {entry.state for entry in entries} == {"changed"}


# ─── Redaction (Requirement 11.7) ────────────────────────────────────────────


def test_diff_classifies_a_path_redacted_in_both_phases_as_unchanged():
    """Redaction removes the information needed to compare, so the state is `unchanged`."""
    entries = _by_path(
        diff_attributes(
            {"app_settings": {"KEY": REDACTION_LITERAL}},
            {"app_settings": {"KEY": REDACTION_LITERAL}},
        )
    )

    entry = entries["app_settings.KEY"]
    assert entry.state == "unchanged"
    assert (entry.before, entry.after) == (REDACTION_LITERAL, REDACTION_LITERAL)


def test_diff_keeps_the_other_phase_value_when_only_one_phase_is_redacted():
    """A path flagged in one phase only stays comparable and reads `changed`."""
    entries = _by_path(diff_attributes({"key": REDACTION_LITERAL}, {"key": "public"}))

    assert entries["key"].state == "changed"
    assert (entries["key"].before, entries["key"].after) == (REDACTION_LITERAL, "public")


def test_redaction_wins_over_the_unknown_mask():
    """A both-sides-redacted path stays `unchanged` rather than becoming unknown."""
    entries = _by_path(
        diff_attributes(
            {"key": REDACTION_LITERAL},
            {"key": REDACTION_LITERAL},
            unknown={"key": True},
        )
    )

    assert entries["key"].state == "unchanged"
    assert (entries["key"].before, entries["key"].after) == (REDACTION_LITERAL, REDACTION_LITERAL)


def test_a_one_sided_redaction_still_takes_the_unknown_marker():
    """The override is scoped to *both* sides redacted, not to either side."""
    entries = _by_path(
        diff_attributes({"key": "public"}, {"key": REDACTION_LITERAL}, unknown={"key": True})
    )

    assert entries["key"].after == UNKNOWN_MARKER
    assert entries["key"].state == "changed"


# ─── Value_Bounds forwarded through the differ (Requirements 12.3, 12.4) ─────


def test_diff_reports_the_truncation_reasons_of_both_phases():
    """The differ forwards the caller's accumulator into both bounds."""
    reasons: set = set()

    diff_attributes(
        {"long": "a" * (MAX_SCALAR_CHARS + 1)},
        {"long": "a" * (MAX_SCALAR_CHARS + 1)},
        reasons=reasons,
    )

    assert reasons == {VALUE_REASON}


def test_diff_forwards_a_caller_supplied_depth_bound():
    """``max_depth`` reaches the flatten step of both phases."""
    entries = diff_attributes({"a": {"b": {"c": 1}}}, {"a": {"b": {"c": 2}}}, max_depth=2)

    assert entries == [
        AttributeEntry(
            path="a.b", state="unchanged", before=TRUNCATION_MARKER, after=TRUNCATION_MARKER
        )
    ]


def test_diff_bounds_a_deep_snapshot_to_the_depth_bound():
    """No Attribute_Path the differ emits holds more than MAX_TREE_DEPTH segments."""
    node: object = "bottom"
    for level in reversed(range(MAX_TREE_DEPTH + 5)):
        node = {f"level{level}": node}

    entries = diff_attributes(node, {})

    assert [len(entry.path.split(".")) for entry in entries] == [MAX_TREE_DEPTH]


# ─── Determinism (Requirement 14.4) ──────────────────────────────────────────


def test_diff_is_idempotent_across_invocations():
    """The same arguments produce an equal Attribute_Entry list every time."""
    before = {"a": 1, "b": {"c": [1, 2]}}
    after = {"a": 2, "b": {"c": [1]}, "d": None}

    first = diff_attributes(before, after, unknown={"a": True})
    second = diff_attributes(before, after, unknown={"a": True})

    assert first == second

# ─── Property harness ─────────────────────────────────────────────────────────
#
# The four properties below are the property-based coverage of ``diff_attributes``
# the design assigns to this file: Properties 1, 4, 6 and 7. Everything they need
# is a dictionary in and a list out, so no mocking and no fixtures are involved.

from collections import Counter  # noqa: E402

from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from core.inspector import (  # noqa: E402
    InspectorIdentity,
    apply_bounds,
    build_record,
    flatten_values,
    render_scalar,
)
from strategies.inspector_trees import (  # noqa: E402
    attribute_keys,
    attribute_scalars,
    attribute_trees,
    bounded_trees,
    sensitivity_masks,
    snapshot_pairs,
)

#: A fixed identity header, so a record-level assertion measures the attribute
#: list rather than the identity fields (which Property 5 owns).
_IDENTITY = InspectorIdentity(
    key="web-rg-app",
    kind="node",
    name="web",
    resource_type="Microsoft.Web/sites",
    resource_group="rg-app",
)


def _stringify_leaves(node):
    """Return ``node`` with every leaf replaced by its own rendered text.

    The Attribute_Path set is preserved and every rendered value is preserved, so
    the result differs from ``node`` in leaf *type* only — ``1`` becomes ``"1"``,
    ``True`` becomes ``"true"``, ``None`` becomes ``"null"``. That is the pair the
    decision table has to call `unchanged` (Requirement 7.5).
    """
    if isinstance(node, dict):
        return {key: _stringify_leaves(child) for key, child in node.items()}
    if isinstance(node, list):
        return [_stringify_leaves(child) for child in node]
    return render_scalar(node)


@st.composite
def _container_versus_scalar_pairs(draw):
    """Two snapshots agreeing everywhere except one path: container vs scalar."""
    shared = draw(bounded_trees(max_depth=3))
    key = draw(attribute_keys())
    container = draw(
        st.sampled_from(
            (
                {},
                [],
                {"nested": {"leaf": 1}},
                [{"a": 1}, 2],
            )
        )
    )
    with_container = {**shared, key: container}
    with_scalar = {**shared, key: draw(attribute_scalars())}
    if draw(st.booleans()):
        return with_container, with_scalar
    return with_scalar, with_container


def _classification_pairs():
    """Config_Snapshot pairs covering every branch Property 1 names.

    Derived pairs from a common base (so all four states occur together), pairs
    with one side empty and both sides empty, pairs where one path holds a
    container on one side and a scalar on the other, and pairs differing in leaf
    type only.
    """
    one_sided = st.tuples(bounded_trees(max_depth=3), st.just({}))
    return st.one_of(
        snapshot_pairs(),
        one_sided,
        one_sided.map(lambda pair: (pair[1], pair[0])),
        st.just(({}, {})),
        _container_versus_scalar_pairs(),
        bounded_trees(max_depth=3).map(lambda tree: (tree, _stringify_leaves(tree))),
    )


def _reference_states(before, after):
    """The reference decision table of Requirement 7, over the *rendered* values."""
    flat_before = flatten_values(before)
    flat_after = flatten_values(after)

    states = {}
    for path in set(flat_before) | set(flat_after):
        if path not in flat_before:
            states[path] = "added"
        elif path not in flat_after:
            states[path] = "removed"
        elif render_scalar(flat_before[path]) == render_scalar(flat_after[path]):
            states[path] = "unchanged"
        else:
            states[path] = "changed"
    return states


def _paths_by_state(entries):
    """Group the Attribute_Paths of an entry list into one path set per state."""
    grouped = {state: set() for state in ATTRIBUTE_STATES}
    for entry in entries:
        grouped[entry.state].add(entry.path)
    return grouped


# ─── Property 1: Classification totality and closure ──────────────────────────
# Feature: interactive-resource-inspector, Property 1: Classification totality
# and closure — for any pair of Config_Snapshots, including pairs where one or
# both are empty, where a path holds a container in one snapshot and a scalar in
# the other, and where values differ only in type, the Attribute_Differ assigns
# to every Attribute_Path present in either snapshot exactly one Attribute_State
# drawn from {added, removed, changed, unchanged}, leaves no such path
# unclassified, and the assigned state equals the reference decision table.


@settings(max_examples=200, deadline=None)
@given(pair=_classification_pairs())
def test_property_1_classification_totality_and_closure(pair):
    """Property 1: Classification totality and closure.

    Every Attribute_Path present in either Config_Snapshot gets exactly one
    entry, every state is drawn from the closed Attribute_State set, and the
    assigned state equals the reference table computed over the rendered values.

    **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 14.1**
    """
    before, after = pair

    entries = diff_attributes(before, after)
    reference = _reference_states(before, after)
    paths = [entry.path for entry in entries]

    # Totality: every input path is classified, and nothing else is.
    assert set(paths) == set(reference)
    # Exactly one state per path: no path is classified twice.
    assert len(paths) == len(set(paths))
    # Closure: every assigned state is drawn from the closed set.
    assert all(entry.state in ATTRIBUTE_STATES for entry in entries)
    # The assignment equals the reference decision table.
    assert {entry.path: entry.state for entry in entries} == reference


# ─── Property 4: Diff idempotence ─────────────────────────────────────────────
# Feature: interactive-resource-inspector, Property 4: Diff idempotence — for any
# pair of Config_Snapshots, diff_attributes returns an equal Attribute_Entry list
# on every invocation with the same arguments, and diffing the pair a second time
# — including re-diffing after apply_bounds has run — yields the same list as
# diffing it once.


@st.composite
def _pairs_with_masks(draw):
    """A Config_Snapshot pair with an ``after_unknown`` mask, absent or aligned."""
    before, after = draw(snapshot_pairs())
    mask = draw(
        st.one_of(
            st.none(),
            st.just(True),
            sensitivity_masks(values=st.just(after)).map(lambda pair: pair[1]),
        )
    )
    return before, after, mask


@settings(max_examples=150, deadline=None)
@given(triple=_pairs_with_masks())
def test_property_4_diff_idempotence(triple):
    """Property 4: Diff idempotence.

    The same arguments produce an equal Attribute_Entry list on every invocation,
    and running ``apply_bounds`` over a result leaves a re-diff of the same
    arguments equal to the first one.

    **Validates: Requirements 14.4**
    """
    before, after, mask = triple

    first = diff_attributes(before, after, unknown=mask)
    second = diff_attributes(before, after, unknown=mask)

    assert second == first

    original = list(first)
    apply_bounds(first)

    # apply_bounds neither mutates the list it was handed nor the entries in it.
    assert list(first) == original
    assert diff_attributes(before, after, unknown=mask) == first


# ─── Property 6: Identity diff ────────────────────────────────────────────────
# Feature: interactive-resource-inspector, Property 6: Identity diff — for any
# Config_Snapshot, diffing it against itself produces an Attribute_Entry list in
# which every entry carries the Attribute_State unchanged, every Before_Value
# equals its After_Value, and the record's per-state counts report zero for
# added, removed and changed.


@settings(max_examples=150, deadline=None)
@given(snapshot=st.one_of(attribute_trees(max_depth=4), bounded_trees(max_depth=5)))
def test_property_6_identity_diff(snapshot):
    """Property 6: Identity diff.

    An unchanged resource — the Legacy_Mode and Live_Mode case, where both
    Config_Snapshots are the same attribute map — carries no change anywhere.

    **Validates: Requirements 6.5, 6.9, 10.2, 10.7, 14.6**
    """
    entries = diff_attributes(snapshot, snapshot)

    assert all(entry.state == "unchanged" for entry in entries)
    assert all(entry.before == entry.after for entry in entries)

    record = build_record(_IDENTITY, snapshot, snapshot)
    counts = Counter(entry.state for entry in record.attributes)

    assert counts["added"] == 0
    assert counts["removed"] == 0
    assert counts["changed"] == 0
    assert counts["unchanged"] == len(record.attributes)


# ─── Property 7: Diff antisymmetry ────────────────────────────────────────────
# Feature: interactive-resource-inspector, Property 7: Diff antisymmetry — for
# any pair of Config_Snapshots, the set of Attribute_Paths that the pair
# classifies as added equals the set that the reversed pair classifies as
# removed and vice versa, and the changed and unchanged path sets are identical
# under reversal.


@settings(max_examples=200, deadline=None)
@given(pair=_classification_pairs())
def test_property_7_diff_antisymmetry(pair):
    """Property 7: Diff antisymmetry.

    Swapping the two Config_Snapshots swaps `added` with `removed` and preserves
    `changed` and `unchanged`. Stated for the mask-free diff: the unknown mask
    describes the after phase only, so it has no reversed counterpart.

    **Validates: Requirements 14.7**
    """
    before, after = pair

    forward = _paths_by_state(diff_attributes(before, after))
    reverse = _paths_by_state(diff_attributes(after, before))

    assert forward["added"] == reverse["removed"]
    assert forward["removed"] == reverse["added"]
    assert forward["changed"] == reverse["changed"]
    assert forward["unchanged"] == reverse["unchanged"]
