"""Unit tests for the plan diff Change_Summary.

Covers Requirement 7.1 (per-category counts on the console), Requirement 7.2
(Skip_Filter removals listed under ``Changes not displayed``), Requirement 7.3
(Unmapped_Resources listed with their Terraform type), Requirement 7.4
(addresses without a resource entry) and Requirement 10.3 (no sensitive value
reaches the summary payload).
"""

import pytest

from cloudhorus.models.local_template_document import LocalTemplateDocument, LocalTemplateResource
from core.plan_diff import (
    CHANGE_CATEGORIES,
    NO_RESOURCE_ENTRY_REASON,
    NOT_DISPLAYED_HEADING,
    SKIP_FILTER_REASON,
    SUMMARY_HEADING,
    UNDISPLAYED_REASONS,
    UNMAPPED_TYPE_REASON,
    ChangeModel,
    ChangeRecord,
    ChangeSummary,
    UndisplayedChange,
    build_change_summary,
    format_change_summary,
    is_skipped_by_skip_filter,
)

SENSITIVE_LITERAL = "super-secret-password"


def make_record(address, category="update", terraform_type="azurerm_linux_web_app"):
    """Build a Change_Record the way the extractor would."""
    return ChangeRecord(
        address=address,
        category=category,
        actions=(category,),
        terraform_type=terraform_type,
        provider_name="registry.terraform.io/hashicorp/azurerm",
    )


def make_model(*records):
    """Build a Change_Model whose counts derive from the given records."""
    return ChangeModel.from_records({record.address: record for record in records})


def make_resource(address, renderer_type="Microsoft.Web/sites", name="app-web", properties=None):
    """Build a normalized document resource for one Terraform address."""
    return LocalTemplateResource(
        address=address,
        provider_name="azurerm",
        source_type="azurerm_linux_web_app",
        renderer_type=renderer_type,
        name=name,
        properties=properties if properties is not None else {},
    )


def make_document(*resources):
    """Build the post-filter document that feeds the renderer."""
    return LocalTemplateDocument(
        source_format="terraform-json",
        provider_name="azurerm",
        resources=list(resources),
    )


class TestRenderedChangesAreNotReported:
    """A change that reaches a diagram node stays out of the report."""

    def test_a_rendered_change_is_not_listed(self):
        record = make_record("azurerm_linux_web_app.web", "create")
        summary = build_change_summary(make_model(record), make_document(make_resource(record.address)))

        assert summary.not_displayed == []
        assert summary.has_undisplayed() is False
        assert summary.undisplayed_count == 0

    def test_an_unchanged_record_with_a_node_is_not_listed(self):
        record = make_record("azurerm_linux_web_app.web", "unchanged")
        summary = build_change_summary(make_model(record), make_document(make_resource(record.address)))

        assert summary.not_displayed == []


class TestCountsAndPresentCategories:
    """Requirement 7.1: the summary reports the count of every category."""

    def test_counts_cover_every_category_including_zeros(self):
        model = make_model(
            make_record("azurerm_linux_web_app.a", "create"),
            make_record("azurerm_linux_web_app.b", "create"),
            make_record("azurerm_subnet.c", "delete"),
        )
        summary = build_change_summary(model, make_document())

        assert set(summary.counts) == set(CHANGE_CATEGORIES)
        assert summary.counts["create"] == 2
        assert summary.counts["delete"] == 1
        assert summary.counts["update"] == 0
        assert summary.counts["replace"] == 0
        assert summary.counts["unchanged"] == 0

    def test_present_categories_follow_canonical_order(self):
        model = make_model(
            make_record("azurerm_subnet.c", "delete"),
            make_record("azurerm_linux_web_app.a", "create"),
        )
        summary = build_change_summary(model, make_document())

        assert summary.present_categories == ["create", "delete"]

    def test_an_empty_model_reports_only_zeros(self):
        summary = build_change_summary(ChangeModel(), make_document())

        assert summary.counts == {category: 0 for category in CHANGE_CATEGORIES}
        assert summary.present_categories == []
        assert summary.not_displayed == []

    def test_a_missing_model_is_tolerated(self):
        summary = build_change_summary(None, None)

        assert summary.counts == {category: 0 for category in CHANGE_CATEGORIES}
        assert summary.not_displayed == []


class TestSkipFilterReason:
    """Requirement 7.2: Skip_Filter removals are reported with their address."""

    @pytest.mark.parametrize(
        "renderer_type",
        [
            "Microsoft.Network/networkSecurityGroups/securityRules",
            "Microsoft.Network/routeTables/routes",
            "Microsoft.Network/privateDnsZones",
            "Microsoft.Network/bastionHosts",
        ],
    )
    def test_the_real_skip_filter_decides(self, renderer_type):
        assert is_skipped_by_skip_filter(renderer_type) is True

        record = make_record("module.net.azurerm_network_security_group.app", "update", "azurerm_network_security_group")
        document = make_document(make_resource(record.address, renderer_type=renderer_type, name="nsg-app"))
        summary = build_change_summary(make_model(record), document)

        assert [entry.reason for entry in summary.not_displayed] == [SKIP_FILTER_REASON]
        assert summary.not_displayed[0].address == record.address
        assert summary.not_displayed[0].terraform_type == "azurerm_network_security_group"
        assert summary.not_displayed[0].category == "update"

    def test_an_unchanged_skipped_resource_is_not_reported(self):
        record = make_record("azurerm_network_security_group.app", "unchanged", "azurerm_network_security_group")
        document = make_document(
            make_resource(
                record.address,
                renderer_type="Microsoft.Network/networkSecurityGroups/securityRules",
                name="nsg-app",
            )
        )
        summary = build_change_summary(make_model(record), document)

        assert summary.not_displayed == []

    def test_an_explicitly_skipped_address_is_reported(self):
        record = make_record("azurerm_monitor_metric_alert.cpu", "create", "azurerm_monitor_metric_alert")
        document = make_document(make_resource(record.address, renderer_type="Microsoft.Web/sites"))
        summary = build_change_summary(make_model(record), document, skipped=[record.address])

        assert summary.addresses_by_reason(SKIP_FILTER_REASON) == [record.address]

    def test_a_resource_type_not_removed_by_the_skip_filter_is_rendered(self):
        assert is_skipped_by_skip_filter("Microsoft.Web/sites") is False

        record = make_record("azurerm_linux_web_app.web", "update")
        summary = build_change_summary(make_model(record), make_document(make_resource(record.address)))

        assert summary.not_displayed == []


class TestUnmappedTypeReason:
    """Requirement 7.3: Unmapped_Resources carry their Terraform type."""

    def test_an_unmapped_terraform_type_is_reported(self):
        record = make_record("module.app.azurerm_cosmosdb_account.main", "create", "azurerm_cosmosdb_account")
        summary = build_change_summary(make_model(record), make_document(), unmapped=["azurerm_cosmosdb_account"])

        entry = summary.not_displayed[0]
        assert entry.reason == UNMAPPED_TYPE_REASON
        assert entry.address == record.address
        assert entry.terraform_type == "azurerm_cosmosdb_account"

    def test_an_unmapped_address_is_reported(self):
        record = make_record("azurerm_cosmosdb_account.main", "delete", "azurerm_cosmosdb_account")
        summary = build_change_summary(make_model(record), make_document(), unmapped={record.address})

        assert summary.addresses_by_reason(UNMAPPED_TYPE_REASON) == [record.address]

    def test_unmapped_wins_over_the_missing_resource_entry(self):
        record = make_record("azurerm_cosmosdb_account.main", "create", "azurerm_cosmosdb_account")
        summary = build_change_summary(make_model(record), make_document(), unmapped=["azurerm_cosmosdb_account"])

        assert [entry.reason for entry in summary.not_displayed] == [UNMAPPED_TYPE_REASON]


class TestNoResourceEntryReason:
    """Requirement 7.4: an address without a resource entry is reported."""

    def test_an_address_absent_from_the_document_is_reported(self):
        record = make_record("azurerm_linux_web_app.gone", "delete")
        summary = build_change_summary(make_model(record), make_document(make_resource("azurerm_subnet.other")))

        entry = summary.not_displayed[0]
        assert entry.reason == NO_RESOURCE_ENTRY_REASON
        assert entry.address == "azurerm_linux_web_app.gone"

    def test_an_unchanged_address_without_a_node_is_reported(self):
        record = make_record("data.azurerm_client_config.current", "unchanged", "azurerm_client_config")
        summary = build_change_summary(make_model(record), make_document())

        assert summary.addresses_by_reason(NO_RESOURCE_ENTRY_REASON) == ["data.azurerm_client_config.current"]

    def test_every_reason_used_belongs_to_the_closed_set(self):
        model = make_model(
            make_record("azurerm_network_security_group.app", "update", "azurerm_network_security_group"),
            make_record("azurerm_cosmosdb_account.main", "create", "azurerm_cosmosdb_account"),
            make_record("azurerm_linux_web_app.gone", "delete"),
        )
        document = make_document(
            make_resource(
                "azurerm_network_security_group.app",
                renderer_type="Microsoft.Network/networkSecurityGroups/securityRules",
                name="nsg-app",
            )
        )
        summary = build_change_summary(model, document, unmapped=["azurerm_cosmosdb_account"])

        assert len(summary.not_displayed) == 3
        assert {entry.reason for entry in summary.not_displayed} == set(UNDISPLAYED_REASONS)
        assert all(entry.reason in UNDISPLAYED_REASONS for entry in summary.not_displayed)


class TestSensitiveValuesAreExcluded:
    """Requirement 10.3: no plan value reaches the summary payload."""

    def test_the_payload_carries_no_property_value(self):
        record = make_record("azurerm_key_vault_secret.db", "update", "azurerm_key_vault_secret")
        document = make_document(
            make_resource(
                record.address,
                renderer_type="Microsoft.Network/routeTables/routes",
                name="secret",
                properties={"value": SENSITIVE_LITERAL, "nested": {"password": SENSITIVE_LITERAL}},
            )
        )
        summary = build_change_summary(make_model(record), document)
        payload = summary.to_payload()

        assert summary.addresses_by_reason(SKIP_FILTER_REASON) == [record.address]
        assert SENSITIVE_LITERAL not in repr(payload)
        assert SENSITIVE_LITERAL not in "\n".join(format_change_summary(summary))
        assert set(payload) == {"counts", "presentCategories", "notDisplayed"}
        assert set(payload["notDisplayed"][0]) == {"address", "terraformType", "category", "reason"}


class TestFormatChangeSummary:
    """Console rendering of the summary lines (Requirements 7.1 to 7.4)."""

    def test_counts_block_lists_every_category(self):
        model = make_model(
            make_record("azurerm_linux_web_app.a", "create"),
            make_record("azurerm_subnet.b", "delete"),
        )
        lines = format_change_summary(build_change_summary(model, make_document()))

        assert lines[0] == SUMMARY_HEADING
        rendered = [line.split() for line in lines[1:6]]
        assert rendered == [
            ["create", "1"],
            ["update", "0"],
            ["replace", "0"],
            ["delete", "1"],
            ["unchanged", "0"],
        ]

    def test_no_heading_when_every_change_is_displayed(self):
        record = make_record("azurerm_linux_web_app.web", "create")
        lines = format_change_summary(build_change_summary(make_model(record), make_document(make_resource(record.address))))

        assert all(NOT_DISPLAYED_HEADING not in line for line in lines)

    def test_undisplayed_block_carries_heading_count_and_reason_wording(self):
        model = make_model(
            make_record("module.net.azurerm_network_security_group.app", "update", "azurerm_network_security_group"),
            make_record("module.app.azurerm_cosmosdb_account.main", "create", "azurerm_cosmosdb_account"),
            make_record("data.azurerm_client_config.current", "unchanged", "azurerm_client_config"),
        )
        document = make_document(
            make_resource(
                "module.net.azurerm_network_security_group.app",
                renderer_type="Microsoft.Network/networkSecurityGroups/securityRules",
                name="nsg-app",
            )
        )
        summary = build_change_summary(model, document, unmapped=["azurerm_cosmosdb_account"])
        lines = format_change_summary(summary)

        assert lines[6] == f"{NOT_DISPLAYED_HEADING} (3)"
        assert "module.net.azurerm_network_security_group.app" in lines[7]
        assert "azurerm_network_security_group" in lines[7]
        assert lines[7].rstrip().endswith("(filtered resource type)")
        assert lines[8].rstrip().endswith("(unmapped type)")
        assert lines[9].rstrip().endswith("(no diagram node)")

    def test_a_missing_summary_renders_no_line(self):
        assert format_change_summary(None) == []


class TestChangeSummaryHolder:
    """The holder normalizes what it is handed."""

    def test_counts_are_normalized_to_the_closed_category_set(self):
        summary = ChangeSummary(counts={"create": 2, "bogus": 5})

        assert summary.counts == {"create": 2, "update": 0, "replace": 0, "delete": 0, "unchanged": 0}

    def test_present_categories_are_reordered_canonically(self):
        summary = ChangeSummary(present_categories=["unchanged", "create", "bogus"])

        assert summary.present_categories == ["create", "unchanged"]

    def test_undisplayed_entries_serialize_to_the_sidecar_shape(self):
        entry = UndisplayedChange(
            address="azurerm_subnet.a",
            terraform_type="azurerm_subnet",
            category="delete",
            reason=SKIP_FILTER_REASON,
        )

        assert entry.to_payload() == {
            "address": "azurerm_subnet.a",
            "terraformType": "azurerm_subnet",
            "category": "delete",
            "reason": SKIP_FILTER_REASON,
        }
