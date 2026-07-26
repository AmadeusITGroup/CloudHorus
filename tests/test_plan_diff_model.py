"""Unit tests for the plan diff change model foundations.

Covers Requirements 2.2, 2.9, 2.11 and 4.4.
"""

from core.plan_diff import (
    CHANGE_CATEGORIES,
    KNOWN_ACTIONS,
    SUPPORTED_PROVIDER_NAMES,
    ChangeModel,
    ChangeRecord,
)


def _record(address, category, actions=(), terraform_type="azurerm_linux_web_app"):
    return ChangeRecord(
        address=address,
        category=category,
        actions=tuple(actions),
        terraform_type=terraform_type,
        provider_name="registry.terraform.io/hashicorp/azurerm",
    )


class TestConstants:
    """The closed sets the change model is built on."""

    def test_change_categories_are_the_closed_set_in_canonical_order(self):
        assert CHANGE_CATEGORIES == ("create", "update", "replace", "delete", "unchanged")

    def test_known_actions_match_the_terraform_action_vocabulary(self):
        assert KNOWN_ACTIONS == frozenset({"create", "update", "delete", "no-op", "read"})

    def test_supported_provider_names_mirror_the_terraform_builder(self):
        from core.terraform_builder import _SUPPORTED_PROVIDER_NAMES

        assert SUPPORTED_PROVIDER_NAMES == frozenset(_SUPPORTED_PROVIDER_NAMES)


class TestChangeRecord:
    """Change records are immutable and keep the raw action array."""

    def test_record_is_frozen(self):
        record = _record("azurerm_linux_web_app.api", "replace", ("delete", "create"))
        try:
            record.category = "create"
        except Exception as error:  # dataclasses raises FrozenInstanceError
            assert "frozen" in type(error).__name__.lower() or "frozen" in str(error).lower()
        else:
            raise AssertionError("ChangeRecord should be immutable")

    def test_record_preserves_action_order(self):
        record = _record("azurerm_linux_web_app.api", "replace", ("delete", "create"))
        assert record.actions == ("delete", "create")


class TestCountInvariant:
    """counts always holds exactly one entry per category, absent ones at zero."""

    def test_counts_cover_every_category_when_constructed_empty(self):
        model = ChangeModel()
        assert set(model.counts) == set(CHANGE_CATEGORIES)
        assert all(count == 0 for count in model.counts.values())

    def test_partial_counts_are_completed_with_zeros(self):
        model = ChangeModel(counts={"delete": 2})
        assert set(model.counts) == set(CHANGE_CATEGORIES)
        assert model.counts["delete"] == 2
        assert model.counts["create"] == 0

    def test_unknown_categories_are_dropped_from_counts(self):
        model = ChangeModel(counts={"delete": 1, "explode": 7})
        assert "explode" not in model.counts
        assert set(model.counts) == set(CHANGE_CATEGORIES)

    def test_counts_from_records_conserve_the_record_total(self):
        records = {
            "azurerm_virtual_network.core": _record("azurerm_virtual_network.core", "unchanged", ("no-op",)),
            "module.app.azurerm_linux_web_app.api": _record(
                "module.app.azurerm_linux_web_app.api", "delete", ("delete",)
            ),
            "azurerm_storage_account.data": _record("azurerm_storage_account.data", "delete", ("delete",)),
        }
        model = ChangeModel.from_records(records)
        assert sum(model.counts.values()) == len(model.records)
        assert model.counts["delete"] == 2
        assert model.counts["unchanged"] == 1


class TestModelQueries:
    """category_for, has_changes and present_categories."""

    def test_category_for_known_and_unknown_addresses(self):
        model = ChangeModel.from_records(
            {"module.app.azurerm_linux_web_app.api": _record("module.app.azurerm_linux_web_app.api", "update")}
        )
        assert model.category_for("module.app.azurerm_linux_web_app.api") == "update"
        assert model.category_for("azurerm_storage_account.absent") is None

    def test_has_changes_is_false_for_an_all_unchanged_model(self):
        model = ChangeModel.from_records({"a": _record("a", "unchanged", ("no-op",))})
        assert model.has_changes() is False

    def test_has_changes_is_true_when_any_record_differs(self):
        model = ChangeModel.from_records(
            {"a": _record("a", "unchanged", ("no-op",)), "b": _record("b", "create", ("create",))}
        )
        assert model.has_changes() is True

    def test_present_categories_follow_canonical_order_and_skip_zeros(self):
        model = ChangeModel.from_records(
            {
                "a": _record("a", "delete", ("delete",)),
                "b": _record("b", "create", ("create",)),
                "c": _record("c", "delete", ("delete",)),
            }
        )
        assert model.present_categories() == ["create", "delete"]

    def test_empty_model_has_no_present_categories(self):
        assert ChangeModel().present_categories() == []


class TestMetadataRoundTrip:
    """to_metadata / from_metadata preserve the model."""

    def test_round_trip_preserves_records_counts_and_warnings(self):
        model = ChangeModel.from_records(
            {
                "module.app.azurerm_linux_web_app.api": _record(
                    "module.app.azurerm_linux_web_app.api", "replace", ("delete", "create")
                ),
                "azurerm_virtual_network.core": _record(
                    "azurerm_virtual_network.core", "unchanged", ("no-op",), "azurerm_virtual_network"
                ),
            },
            warnings=["Unrecognized action 'forget' for azurerm_storage_account.s"],
        )
        assert ChangeModel.from_metadata(model.to_metadata()) == model

    def test_round_trip_of_an_empty_model(self):
        model = ChangeModel()
        assert ChangeModel.from_metadata(model.to_metadata()) == model

    def test_metadata_payload_shape(self):
        model = ChangeModel.from_records(
            {"azurerm_storage_account.data": _record("azurerm_storage_account.data", "delete", ("delete",))}
        )
        payload = model.to_metadata()
        assert set(payload) == {"counts", "records"}
        assert payload["records"] == [
            {
                "address": "azurerm_storage_account.data",
                "category": "delete",
                "actions": ["delete"],
                "terraformType": "azurerm_linux_web_app",
                "providerName": "registry.terraform.io/hashicorp/azurerm",
            }
        ]

    def test_from_metadata_tolerates_malformed_payloads(self):
        model = ChangeModel.from_metadata({"records": ["not-a-record", {"category": "delete"}], "counts": "nope"})
        assert model.records == {}
        assert set(model.counts) == set(CHANGE_CATEGORIES)

    def test_from_metadata_keeps_the_first_duplicate_address(self):
        payload = {
            "records": [
                {"address": "a", "category": "delete", "actions": ["delete"]},
                {"address": "a", "category": "create", "actions": ["create"]},
            ]
        }
        model = ChangeModel.from_metadata(payload)
        assert model.category_for("a") == "delete"
        assert sum(model.counts.values()) == 1
