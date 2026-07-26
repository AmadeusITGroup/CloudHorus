"""Unit tests for the Change_Extractor classification decision table.

Covers Requirements 2.3, 2.4, 2.5, 2.6, 2.7, 2.8 and 9.6.
"""

from unittest.mock import patch

import pytest

from core.plan_diff import CHANGE_CATEGORIES, UNCHANGED_CATEGORY, ChangeExtractor


@pytest.fixture
def extractor():
    return ChangeExtractor()


class TestDecisionTable:
    """Each documented actions array resolves to exactly one category."""

    @pytest.mark.parametrize(
        "actions, expected",
        [
            (["create"], "create"),
            (["update"], "update"),
            (["delete"], "delete"),
            (["no-op"], UNCHANGED_CATEGORY),
            (["read"], UNCHANGED_CATEGORY),
            (["create", "delete"], "replace"),
            (["delete", "create"], "replace"),
        ],
    )
    def test_known_action_arrays_map_to_their_category(self, extractor, actions, expected):
        category, raw = extractor.classify(actions)

        assert category == expected
        assert category in CHANGE_CATEGORIES
        assert raw == tuple(actions)

    def test_replace_wins_over_the_single_action_rows(self, extractor):
        # An array holding both create and delete is a replace whatever else it carries.
        assert extractor.classify(["delete", "create", "delete"])[0] == "replace"

    def test_repeated_known_action_keeps_its_category(self, extractor):
        assert extractor.classify(["update", "update"]) == ("update", ("update", "update"))


class TestRawActionsArePreserved:
    """The record keeps the plan's original array, order included."""

    def test_action_order_is_preserved(self, extractor):
        _, raw = extractor.classify(["delete", "create"])
        assert raw == ("delete", "create")

    def test_actions_are_returned_as_a_tuple_of_strings(self, extractor):
        _, raw = extractor.classify(("create",))
        assert raw == ("create",)
        assert isinstance(raw, tuple)


class TestUnclassifiableInput:
    """Unknown, missing and malformed actions fall back to unchanged with a warning."""

    def test_unknown_action_value_is_unchanged_and_warns_naming_the_value(self, extractor):
        with patch("core.plan_diff.logger") as mock_logger:
            category, raw = extractor.classify(["forget"])

        assert category == UNCHANGED_CATEGORY
        assert raw == ("forget",)
        assert mock_logger.warning.called
        assert "forget" in str(mock_logger.warning.call_args)

    def test_missing_change_object_is_unchanged_and_warns_naming_the_address(self, extractor):
        with patch("core.plan_diff.logger") as mock_logger:
            category, raw = extractor.classify(None, address="module.app.azurerm_linux_web_app.api")

        assert (category, raw) == (UNCHANGED_CATEGORY, ())
        assert "module.app.azurerm_linux_web_app.api" in str(mock_logger.warning.call_args)

    @pytest.mark.parametrize("actions", ["create", 7, True, {"actions": "create"}])
    def test_non_list_actions_is_unchanged_and_warns(self, extractor, actions):
        with patch("core.plan_diff.logger") as mock_logger:
            category, raw = extractor.classify(actions)

        assert (category, raw) == (UNCHANGED_CATEGORY, ())
        assert mock_logger.warning.called

    @pytest.mark.parametrize("actions", [[], ["update", "read"]])
    def test_unsupported_combination_is_unchanged_and_warns(self, extractor, actions):
        with patch("core.plan_diff.logger") as mock_logger:
            category, raw = extractor.classify(actions)

        assert category == UNCHANGED_CATEGORY
        assert raw == tuple(actions)
        assert mock_logger.warning.called


def _entry(address, actions=("create",), **overrides):
    """Build a minimal managed change entry with a supported provider."""
    entry = {
        "address": address,
        "mode": "managed",
        "type": "azurerm_linux_web_app",
        "name": address.rsplit(".", 1)[-1],
        "provider_name": "registry.terraform.io/hashicorp/azurerm",
        "change": {"actions": list(actions)},
    }
    entry.update(overrides)
    return entry


class TestExtractRetainsManagedEntries:
    """Requirements 2.1, 2.9, 2.11."""

    def test_one_record_per_managed_entry_keyed_by_full_address(self, extractor):
        model = extractor.extract(
            [
                _entry("azurerm_virtual_network.core", ["update"], type="azurerm_virtual_network"),
                _entry("module.app.azurerm_linux_web_app.api", ["delete", "create"]),
            ]
        )

        assert set(model.records) == {
            "azurerm_virtual_network.core",
            "module.app.azurerm_linux_web_app.api",
        }
        record = model.records["module.app.azurerm_linux_web_app.api"]
        assert record.category == "replace"
        assert record.actions == ("delete", "create")
        assert record.terraform_type == "azurerm_linux_web_app"
        assert record.provider_name == "registry.terraform.io/hashicorp/azurerm"

    def test_counts_are_derived_from_the_retained_records(self, extractor):
        model = extractor.extract(
            [
                _entry("azurerm_subnet.a", ["create"]),
                _entry("azurerm_subnet.b", ["create"]),
                _entry("azurerm_subnet.c", ["no-op"]),
            ]
        )

        assert model.counts == {"create": 2, "update": 0, "replace": 0, "delete": 0, "unchanged": 1}
        assert sum(model.counts.values()) == len(model.records)
        assert model.present_categories() == ["create", "unchanged"]

    def test_missing_change_object_is_recorded_as_unchanged(self, extractor):
        entry = _entry("azurerm_subnet.a")
        entry.pop("change")

        model = extractor.extract([entry])

        assert model.records["azurerm_subnet.a"].category == UNCHANGED_CATEGORY
        assert model.records["azurerm_subnet.a"].actions == ()

    def test_empty_array_yields_an_empty_model_without_warnings(self, extractor):
        model = extractor.extract([])

        assert model.records == {}
        assert model.warnings == []
        assert model.counts == {category: 0 for category in CHANGE_CATEGORIES}
        assert model.has_changes() is False


class TestExtractExclusions:
    """Requirements 2.1, 2.10, 9.4, 9.7, 9.8."""

    @pytest.mark.parametrize("mode", ["data", None, "Managed"])
    def test_non_managed_entries_are_skipped_with_a_warning(self, extractor, mode):
        entry = _entry("data.azurerm_subnet.a")
        if mode is None:
            entry.pop("mode")
        else:
            entry["mode"] = mode

        model = extractor.extract([entry])

        assert model.records == {}
        assert any("not 'managed'" in warning for warning in model.warnings)

    def test_entry_without_an_address_is_skipped_with_a_warning(self, extractor):
        entry = _entry("azurerm_subnet.a")
        entry.pop("address")

        model = extractor.extract([entry])

        assert model.records == {}
        assert any("no address" in warning for warning in model.warnings)

    def test_unsupported_provider_is_skipped_and_named_in_the_warning(self, extractor):
        model = extractor.extract(
            [_entry("aws_instance.web", provider_name="registry.terraform.io/hashicorp/aws")]
        )

        assert model.records == {}
        assert any("hashicorp/aws" in warning for warning in model.warnings)

    def test_duplicate_address_keeps_the_first_entry_and_warns(self, extractor):
        model = extractor.extract(
            [
                _entry("azurerm_subnet.a", ["create"]),
                _entry("azurerm_subnet.a", ["delete"]),
            ]
        )

        assert model.records["azurerm_subnet.a"].category == "create"
        assert len(model.records) == 1
        assert any("Duplicate" in warning for warning in model.warnings)

    @pytest.mark.parametrize("resource_changes", [None, {}, "resource_changes", 7])
    def test_non_list_input_yields_an_empty_model_and_a_type_warning(self, extractor, resource_changes):
        with patch("core.plan_diff.logger") as mock_logger:
            model = extractor.extract(resource_changes)

        assert model.records == {}
        assert model.counts == {category: 0 for category in CHANGE_CATEGORIES}
        assert any("unsupported type" in warning for warning in model.warnings)
        assert mock_logger.warning.called

    def test_non_object_entries_are_skipped(self, extractor):
        model = extractor.extract(["azurerm_subnet.a", None, _entry("azurerm_subnet.b", ["delete"])])

        assert set(model.records) == {"azurerm_subnet.b"}
        assert len(model.warnings) == 2


class TestExtractWarningsAreLoggedAndRetained:
    """Warnings reach both the log and the Change_Model."""

    def test_skip_warnings_are_logged_and_kept_on_the_model(self, extractor):
        entry = _entry("azurerm_subnet.a")
        entry["mode"] = "data"

        with patch("core.plan_diff.logger") as mock_logger:
            model = extractor.extract([entry])

        assert mock_logger.warning.called
        assert model.warnings
        assert model.to_metadata()["warnings"] == model.warnings


# ─── Property 1: Classification totality and closure ─────────────────────────

from hypothesis import HealthCheck, given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from core.plan_diff import SUPPORTED_PROVIDER_NAMES  # noqa: E402
from strategies.plan_json import resource_change_arrays, resource_change_entries  # noqa: E402


def _eligible_entries(resource_changes):
    """Reference model of the entries the extractor must retain (first address wins)."""
    eligible = {}
    for entry in resource_changes:
        if not isinstance(entry, dict):
            continue
        if entry.get("mode") != "managed":
            continue
        address = entry.get("address")
        if not isinstance(address, str) or not address:
            continue
        if entry.get("provider_name") not in SUPPORTED_PROVIDER_NAMES:
            continue
        eligible.setdefault(address, entry)
    return eligible


def _expected_raw_actions(entry):
    """The raw actions tuple a record must carry for a given change entry."""
    change = entry.get("change")
    actions = change.get("actions") if isinstance(change, dict) else None
    if isinstance(actions, (list, tuple)) and not isinstance(actions, (str, bytes)):
        return tuple(str(action) for action in actions)
    return ()


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    resource_changes=resource_change_arrays(
        entries=resource_change_entries(allow_missing_address=False),
        min_size=0,
        max_size=6,
    )
)
def test_property_classification_totality_and_closure(resource_changes):
    """Property 1: Classification totality and closure.

    Every managed entry the Change_Extractor retains carries exactly one
    Change_Category drawn from the closed set, no retained entry is left
    unclassified, and the raw actions value is preserved on the record.

    **Validates: Requirements 2.2, 2.8, 9.6, 12.1**
    """
    model = ChangeExtractor().extract(resource_changes)

    expected = _eligible_entries(resource_changes)

    # Closure: exactly the eligible managed entries are retained, keyed by address.
    assert set(model.records) == set(expected)

    for address, record in model.records.items():
        # Totality: exactly one category, drawn from the closed set.
        assert record.address == address
        assert isinstance(record.category, str)
        assert record.category in CHANGE_CATEGORIES
        assert sum(1 for category in CHANGE_CATEGORIES if record.category == category) == 1
        # The plan's original actions value survives on the record, order included.
        assert record.actions == _expected_raw_actions(expected[address])


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    resource_changes=st.lists(
        resource_change_entries(
            allow_missing_address=False,
            allow_missing_change=True,
            modes=("managed",),
            providers=tuple(sorted(SUPPORTED_PROVIDER_NAMES)),
        ),
        min_size=1,
        max_size=6,
    )
)
def test_property_classification_totality_on_managed_only_arrays(resource_changes):
    """Property 1: Classification totality and closure (managed-only arrays).

    With every entry eligible, the record count matches the number of distinct
    addresses and every record still carries a category from the closed set.

    **Validates: Requirements 2.2, 2.8, 9.6, 12.1**
    """
    model = ChangeExtractor().extract(resource_changes)

    distinct_addresses = {entry["address"] for entry in resource_changes}

    assert set(model.records) == distinct_addresses
    assert len(model.records) == len(distinct_addresses)
    assert all(record.category in CHANGE_CATEGORIES for record in model.records.values())


# ─── Property 2: Classification follows the action decision table ─────────────

from core.plan_diff import KNOWN_ACTIONS  # noqa: E402
from strategies.plan_json import (  # noqa: E402
    actions_for_category,
    known_action_arrays,
    replace_action_arrays,
)


def _reference_decision_table(actions):
    """Independent restatement of the Requirement 2.3-2.7 decision table.

    Written from the requirements rather than from the implementation, evaluated
    in the documented order: replace first, then the single-action rows, then the
    no-op/read rows. Any other combination of known actions has no documented
    row, so it falls back to unchanged.
    """
    distinct = set(actions)
    if "create" in distinct and "delete" in distinct:
        return "replace"
    if distinct == {"create"}:
        return "create"
    if distinct == {"update"}:
        return "update"
    if distinct == {"delete"}:
        return "delete"
    if distinct in ({"no-op"}, {"read"}):
        return UNCHANGED_CATEGORY
    return UNCHANGED_CATEGORY


#: Action arrays built only from the known Terraform action vocabulary: the
#: documented single-action rows, both replace permutations, one array per
#: Change_Category, and arbitrary orderings/repetitions of known tokens.
_known_only_action_arrays = st.one_of(
    known_action_arrays(),
    replace_action_arrays(),
    st.sampled_from(CHANGE_CATEGORIES).flatmap(actions_for_category),
    st.lists(st.sampled_from(sorted(KNOWN_ACTIONS)), min_size=1, max_size=4),
    st.lists(st.sampled_from(sorted(KNOWN_ACTIONS)), min_size=1, max_size=4).flatmap(
        lambda actions: st.permutations(actions).map(list)
    ),
)


@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(actions=_known_only_action_arrays)
def test_property_classification_follows_the_action_decision_table(actions):
    """Property 2: Classification follows the action decision table.

    For any action array composed of values from {create, update, delete, no-op,
    read} in any order, the assigned Change_Category equals the reference
    decision table: replace when the array holds both create and delete in any
    order, otherwise create for ["create"], update for ["update"], delete for
    ["delete"], and unchanged for ["no-op"] and ["read"].

    **Validates: Requirements 2.3, 2.4, 2.5, 2.6, 2.7**
    """
    category, raw = ChangeExtractor().classify(actions)

    assert category == _reference_decision_table(actions)
    assert category in CHANGE_CATEGORIES
    # The raw array survives whatever the decision table resolved to.
    assert raw == tuple(actions)

    # Order independence of the replace row: a permutation cannot change the
    # category, since the table reads the array as a set of actions.
    assert ChangeExtractor().classify(list(reversed(actions)))[0] == category

# ─── Property 3: Count conservation ───────────────────────────────────────────

from strategies.plan_json import json_values, plan_documents  # noqa: E402

#: Any ``resource_changes`` value a plan can carry: well-shaped arrays (duplicate
#: addresses included), the arrays produced by whole plan documents, and values
#: that are not arrays at all.
_any_resource_changes = st.one_of(
    resource_change_arrays(min_size=0, max_size=6),
    plan_documents(max_resources=4).map(lambda document: document.get("resource_changes")),
    json_values(max_leaves=8),
)


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(resource_changes=_any_resource_changes)
def test_property_count_conservation(resource_changes):
    """Property 3: Count conservation.

    For any Change_Model produced from any ``resource_changes`` value, the sum of
    the per-category counts equals the number of Change_Records, and the count
    mapping holds exactly one entry per Change_Category.

    **Validates: Requirements 2.11, 12.2**
    """
    model = ChangeExtractor().extract(resource_changes)

    # Exactly one entry per Change_Category, and nothing else.
    assert set(model.counts) == set(CHANGE_CATEGORIES)
    assert len(model.counts) == len(CHANGE_CATEGORIES)

    # Conservation: the counts partition the records, none negative.
    assert sum(model.counts.values()) == len(model.records)
    for category in CHANGE_CATEGORIES:
        count = model.counts[category]
        assert isinstance(count, int)
        assert count >= 0
        assert count == sum(1 for record in model.records.values() if record.category == category)

    # Categories with no record are present at zero, and only non-zero ones are
    # reported as present.
    assert model.present_categories() == [
        category for category in CHANGE_CATEGORIES if model.counts[category] > 0
    ]

    # The invariant survives the metadata round trip the template relies on.
    assert model.to_metadata()["counts"] == model.counts

# ─── Property 4: Extraction membership and address keying ─────────────────────

from strategies.plan_json import terraform_addresses  # noqa: E402


def _eligible_occurrences(resource_changes):
    """Every entry that passes the mode/address/provider gates, duplicates included."""
    return [
        entry
        for entry in resource_changes
        if isinstance(entry, dict)
        and entry.get("mode") == "managed"
        and isinstance(entry.get("address"), str)
        and entry.get("address")
        and entry.get("provider_name") in SUPPORTED_PROVIDER_NAMES
    ]


@st.composite
def _address_collided_arrays(draw):
    """Arrays whose entries share a small address pool, so duplicates are dense.

    The colliding entries keep their independently drawn ``change``, ``type`` and
    ``provider_name``, which is what makes the first-wins rule observable.
    """
    pool = draw(st.lists(terraform_addresses(), min_size=1, max_size=3, unique=True))
    entries = draw(
        st.lists(resource_change_entries(allow_missing_address=False), min_size=1, max_size=6)
    )
    for entry in entries:
        address = draw(st.sampled_from(pool))
        entry["address"] = address
        # Keep module_address consistent with the rewritten address.
        head = address.rsplit(".", 2)
        if len(head) == 3 and head[0]:
            entry["module_address"] = head[0]
        else:
            entry.pop("module_address", None)
    return entries


#: Any ``resource_changes`` value: well-shaped arrays with injected duplicates,
#: address-collided arrays, whole-document arrays, and values that are not arrays.
_membership_inputs = st.one_of(
    resource_change_arrays(min_size=0, max_size=6, inject_duplicates=True),
    _address_collided_arrays(),
    plan_documents(max_resources=4).map(lambda document: document.get("resource_changes")),
    json_values(max_leaves=8),
)


@settings(max_examples=250, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(resource_changes=_membership_inputs)
def test_property_extraction_membership_and_address_keying(resource_changes):
    """Property 4: Extraction membership and address keying.

    For any ``resource_changes`` array, the Change_Model holds exactly one
    Change_Record per distinct address among the entries that are managed, carry
    an address and declare a supported azurerm provider name; each key equals the
    entry's full Terraform address verbatim, module prefixes included; on a
    duplicated address the record derives from the first occurrence; and a
    ``resource_changes`` value that is not an array yields an empty model.

    **Validates: Requirements 2.1, 2.9, 2.10, 9.4, 9.7, 9.8, 11.4**
    """
    model = ChangeExtractor().extract(resource_changes)

    # Requirement 9.8: a non-array value yields an empty model plus a warning.
    if not isinstance(resource_changes, list):
        assert model.records == {}
        assert model.counts == {category: 0 for category in CHANGE_CATEGORIES}
        assert model.has_changes() is False
        assert model.warnings
        return

    expected = _eligible_entries(resource_changes)
    occurrences = _eligible_occurrences(resource_changes)

    # Membership: exactly the eligible entries, one record per distinct address.
    # Ineligible entries (Requirements 2.1, 9.4, 9.7) are absent by construction.
    assert set(model.records) == set(expected)
    assert len(model.records) == len(expected)

    raw_addresses = [
        entry.get("address") for entry in resource_changes if isinstance(entry, dict)
    ]

    for address, first_entry in expected.items():
        record = model.records[address]

        # Requirement 2.9: the key is the plan's address verbatim, module prefixes
        # and all, never a shortened or module-stripped form.
        assert record.address == address
        assert address in raw_addresses
        module_address = first_entry.get("module_address")
        if isinstance(module_address, str) and module_address:
            assert address.startswith(f"{module_address}.")

        # Requirement 2.10: the retained record derives from the first occurrence.
        assert record.actions == _expected_raw_actions(first_entry)
        assert record.category == ChangeExtractor().classify(
            first_entry.get("change", {}).get("actions")
            if isinstance(first_entry.get("change"), dict)
            else None,
            address=address,
        )[0]
        assert record.terraform_type == str(first_entry.get("type", "") or "")
        assert record.provider_name == str(first_entry.get("provider_name"))

    # Requirement 2.10: every dropped duplicate is reported, exactly once each.
    duplicate_warnings = [warning for warning in model.warnings if "Duplicate" in warning]
    assert len(duplicate_warnings) == len(occurrences) - len(expected)

    # Requirement 11.4: at most one record per managed entry is ever held.
    managed_entries = [
        entry
        for entry in resource_changes
        if isinstance(entry, dict) and entry.get("mode") == "managed"
    ]
    assert len(model.records) <= len(managed_entries)

# ─── Property 22: No unhandled failure for any JSON plan input ────────────────
# Feature: terraform-plan-diff-visualization, Property 22: For any JSON document
# supplied as a Plan_File, including documents with unsupported `format_version`
# values, missing value sections, arbitrary `resource_changes` shapes, and
# arbitrarily nested attribute trees, CloudHorus either produces a
# Renderer_Template or raises `ValueError`, and never raises any other exception
# type.

import json  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402

from core.plan_diff import ChangeModel  # noqa: E402
from core.terraform_builder import build_terraform_template  # noqa: E402
from strategies.plan_json import change_filters, json_documents  # noqa: E402


def _extract_outcome(resource_changes):
    """Run the Change_Extractor, allowing only a ChangeModel or a ValueError.

    Requirement 9.9: for all plan contents that parse as JSON the extractor
    returns a Change_Model or raises `ValueError`. Any other exception type is a
    property violation, reported here with the offending type.
    """
    try:
        return ChangeExtractor().extract(resource_changes)
    except ValueError:
        return None
    except Exception as exc:  # noqa: BLE001 - the property is about the exception type
        raise AssertionError(
            f"ChangeExtractor.extract raised {type(exc).__name__} instead of ValueError: {exc}"
        ) from exc


def _build_outcome(document, change_types):
    """Write ``document`` as a Plan_File and build the Renderer_Template from it.

    Returns the parsed Renderer_Template when one was produced, or ``None`` when
    the failure was reported through the builder's error path. Any exception
    escaping the builder is a property violation (Requirement 12.8).
    """
    with tempfile.TemporaryDirectory(prefix="cloudhorus_prop22_") as work_dir:
        plan_path = os.path.join(work_dir, "plan.json")
        output_path = os.path.join(work_dir, "template.json")
        with open(plan_path, "w", encoding="utf-8") as handle:
            json.dump(document, handle)

        try:
            result = build_terraform_template(plan_path, output_path, change_types)
        except ValueError:
            return None
        except Exception as exc:  # noqa: BLE001 - the property is about the exception type
            raise AssertionError(
                f"build_terraform_template raised {type(exc).__name__} instead of "
                f"reporting the error or raising ValueError: {exc}"
            ) from exc

        if result is None:
            # Reported failure: nothing half-written is claimed as a template.
            return None

        assert result == output_path
        with open(result, "r", encoding="utf-8") as handle:
            return json.load(handle)


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(document=json_documents(), change_types=st.one_of(st.none(), change_filters()))
def test_property_no_unhandled_failure_for_any_json_plan_input(document, change_types):
    """Property 22: No unhandled failure for any JSON plan input.

    For any JSON document used as a Plan_File - unsupported `format_version`
    values, missing `planned_values`/`values` sections, arbitrary
    `resource_changes` shapes, arbitrarily nested attribute trees, and documents
    that are not objects at all - the Change_Extractor returns a Change_Model or
    raises `ValueError`, and the full build path terminates with either a written
    Renderer_Template or a reported error. No other exception type escapes.

    **Validates: Requirements 9.1, 9.9, 12.8**
    """
    raw_changes = document.get("resource_changes") if isinstance(document, dict) else document

    model = _extract_outcome(raw_changes)
    if model is not None:
        assert isinstance(model, ChangeModel)
        assert set(model.counts) == set(CHANGE_CATEGORIES)
        assert sum(model.counts.values()) == len(model.records)

    template = _build_outcome(document, change_types)
    if template is None:
        # The error path is the other legal outcome: reported, never crashed.
        return

    # A produced Renderer_Template always satisfies the renderer contract.
    assert isinstance(template, dict)
    assert isinstance(template.get("resources"), list)
    assert all(isinstance(resource, dict) for resource in template["resources"])
    assert template.get("contentVersion") == "1.0.0.0"

    # Requirement 9.1: a template is only produced for a supported format_version.
    if isinstance(document, dict):
        format_version = str(document.get("format_version", "1.0"))
        assert format_version.split(".")[0] in ("", "1")
