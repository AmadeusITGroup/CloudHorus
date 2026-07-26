"""Tests for the Change_Summary console output and the sidecar JSON.

Task 7.6 of the terraform-plan-diff-visualization spec: the formatted
Change_Summary lines logged through `logger.info` inside the Plan_Diff_Mode
guarded block, and the `azure_resources_<timestamp>.change-summary.json`
sidecar written beside the PNG with `counts`, `presentCategories`,
`notDisplayed`, and `changeStyles`. A sidecar write failure is a warning, never
a failed run.

The property test of the design (Property 18) is appended below the unit tests.

Requirements covered: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6.
"""

import glob
import json
import logging
import os
import re
import sys
from contextlib import contextmanager
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import main  # noqa: E402  (src/main.py, on sys.path through tests/conftest.py)
from core.graph_generator import (  # noqa: E402
    CHANGE_SUMMARY_SUFFIX,
    accumulate_change_metadata,
    build_run_change_summary,
    change_styles_payload,
    write_change_summary_sidecar,
)
from core.plan_diff import (  # noqa: E402
    CHANGE_CATEGORIES,
    NOT_DISPLAYED_HEADING,
    NO_RESOURCE_ENTRY_REASON,
    REASON_LABELS,
    SKIP_FILTER_REASON,
    SUMMARY_HEADING,
    UNCHANGED_CATEGORY,
    UNDISPLAYED_REASONS,
    UNMAPPED_TYPE_REASON,
    ChangeExtractor,
    ChangeFilter,
    ChangeSummary,
    UndisplayedChange,
    build_change_summary,
    format_change_summary,
    is_skipped_by_skip_filter,
)
from core.local_input_metadata import (  # noqa: E402
    parse_scope_metadata_files,
    scope_lists_from_scopes,
)
from core.terraform_builder import _TERRAFORM_TO_RENDERER_TYPE, TerraformTemplateBuilder  # noqa: E402
from strategies.plan_json import change_filters, plan_documents  # noqa: E402
from utils.change_style import resolve_style  # noqa: E402
from test_plan_diff_graph_plumbing import (  # noqa: E402
    VNET,
    plan_template,
    run_terraform_json_generation,
)


#: The console handler of the singleton logger rewrites `record.msg` with ANSI
#: colour codes, so a second handler sees the coloured text.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class _RecordCollector(logging.Handler):
    """Collects the log records emitted by the singleton logger."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: List[Any] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append((record.levelno, _ANSI_RE.sub("", record.getMessage())))

    def messages(self, level: Optional[int] = None) -> List[str]:
        return [message for levelno, message in self.records if level is None or levelno == level]


@contextmanager
def captured_logs():
    """Attach a collecting handler to the singleton logger for the block.

    The singleton logger does not propagate, so `caplog` sees nothing; this
    handler is the way to observe what the CLI console and the WebUI console
    receive.
    """
    logger = logging.getLogger("SingletonLogger")
    handler = _RecordCollector()
    previous_level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


def summary_lines(handler: _RecordCollector) -> List[str]:
    """Return the logged INFO lines from the Change_Summary heading onwards."""
    messages = handler.messages(logging.INFO)
    for index, message in enumerate(messages):
        if message == SUMMARY_HEADING:
            return messages[index:]
    return []


def output_dir_of(work_dir: str) -> str:
    """Return the single `azure_resources_<timestamp>` folder a run produced."""
    folders = sorted(glob.glob(os.path.join(work_dir, "azure_resources_*")))
    folders = [folder for folder in folders if os.path.isdir(folder)]
    assert len(folders) == 1, f"expected one output folder in {work_dir}, found {folders}"
    return folders[0]


def collapsed(lines: List[str]) -> List[str]:
    """Collapse the column padding of the summary lines for easy comparison."""
    return [" ".join(line.split()) for line in lines]


def read_sidecar(work_dir: str) -> Dict[str, Any]:
    """Load the sidecar JSON of a run, asserting exactly one was written."""
    output_dir = output_dir_of(work_dir)
    matches = glob.glob(os.path.join(output_dir, f"*{CHANGE_SUMMARY_SUFFIX}"))
    assert len(matches) == 1, f"expected one sidecar in {output_dir}, found {matches}"
    with open(matches[0], encoding="utf-8") as handle:
        return json.load(handle)


def with_not_displayed(template: Dict[str, Any], entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Attach `changesNotDisplayed` entries to a plan template's metadata."""
    template["metadata"]["changesNotDisplayed"] = entries
    return template


# ─── Console Change_Summary (Requirement 7.1) ────────────────────────────────


def test_change_summary_is_logged_in_plan_diff_mode(tmp_path):
    with captured_logs() as handler:
        run_terraform_json_generation(
            [plan_template({"planstorage": "create", "pe-storage": "delete"})],
            work_dir=str(tmp_path),
        )

    lines = summary_lines(handler)
    assert lines, "no Change_Summary logged in Plan_Diff_Mode"
    # One line per Change_Category, zeros included.
    for category in CHANGE_CATEGORIES:
        assert any(line.strip().startswith(category) for line in lines), category
    assert "create 1" in collapsed(lines)
    assert "delete 1" in collapsed(lines)


def test_change_summary_reports_undisplayed_changes(tmp_path):
    template = with_not_displayed(
        plan_template({"planstorage": "delete"}),
        [
            {
                "address": "azurerm_dns_zone.internal",
                "terraformType": "azurerm_dns_zone",
                "category": "delete",
                "reason": SKIP_FILTER_REASON,
            },
            {
                "address": "azurerm_role_assignment.reader",
                "terraformType": "azurerm_role_assignment",
                "category": "create",
                "reason": NO_RESOURCE_ENTRY_REASON,
            },
        ],
    )

    with captured_logs() as handler:
        run_terraform_json_generation([template], work_dir=str(tmp_path))

    lines = summary_lines(handler)
    assert f"{NOT_DISPLAYED_HEADING} (2)" in lines
    joined = "\n".join(lines)
    assert "azurerm_dns_zone.internal" in joined
    assert "(filtered resource type)" in joined
    assert "azurerm_role_assignment.reader" in joined
    assert "(no diagram node)" in joined


def test_change_summary_is_logged_for_an_all_unchanged_plan(tmp_path):
    """The summary guard is Plan_Diff_Mode, not the presence of a real change."""
    with captured_logs() as handler:
        run_terraform_json_generation(
            [plan_template({"planstorage": "unchanged", "pe-storage": "unchanged", VNET: "unchanged"})],
            work_dir=str(tmp_path),
        )

    lines = summary_lines(handler)
    assert lines
    assert "unchanged 3" in collapsed(lines)


def test_no_change_summary_in_legacy_mode(tmp_path):
    with captured_logs() as handler:
        run_terraform_json_generation(
            [plan_template()],
            pass_change_types=False,
            work_dir=str(tmp_path),
        )

    assert summary_lines(handler) == []
    assert SUMMARY_HEADING not in "\n".join(handler.messages())


# ─── Sidecar JSON (Requirements 7.5, 7.6) ────────────────────────────────────


def test_sidecar_lands_beside_the_png_with_the_same_basename(tmp_path):
    run_terraform_json_generation(
        [plan_template({"planstorage": "create"})],
        work_dir=str(tmp_path),
    )

    output_dir = output_dir_of(str(tmp_path))
    stem = os.path.basename(output_dir)  # azure_resources_<timestamp>
    assert os.path.isfile(os.path.join(output_dir, f"{stem}.png"))
    assert os.path.isfile(os.path.join(output_dir, f"{stem}{CHANGE_SUMMARY_SUFFIX}"))


def test_sidecar_carries_counts_present_categories_and_change_styles(tmp_path):
    run_terraform_json_generation(
        [plan_template({"planstorage": "create", "pe-storage": "delete"})],
        work_dir=str(tmp_path),
    )
    payload = read_sidecar(str(tmp_path))

    assert set(payload) == {"counts", "presentCategories", "notDisplayed", "changeStyles"}
    assert payload["counts"] == {"create": 1, "update": 0, "replace": 0, "delete": 1, "unchanged": 0}
    assert payload["presentCategories"] == ["create", "delete"]
    assert payload["notDisplayed"] == []
    assert payload["changeStyles"]["create"] == {"color": "#107C10", "flag": "+", "label": "Create"}
    assert payload["changeStyles"]["unchanged"] is None


def test_sidecar_carries_the_undisplayed_entries(tmp_path):
    template = with_not_displayed(
        plan_template({"planstorage": "delete"}),
        [
            {
                "address": "azurerm_dns_zone.internal",
                "terraformType": "azurerm_dns_zone",
                "category": "delete",
                "reason": SKIP_FILTER_REASON,
            }
        ],
    )
    run_terraform_json_generation([template], work_dir=str(tmp_path))

    payload = read_sidecar(str(tmp_path))
    assert payload["notDisplayed"] == [
        {
            "address": "azurerm_dns_zone.internal",
            "terraformType": "azurerm_dns_zone",
            "category": "delete",
            "reason": SKIP_FILTER_REASON,
        }
    ]


def test_sidecar_counts_are_aggregated_across_templates(tmp_path):
    templates = [
        plan_template({"planstorage0": "delete"}, suffix="-0", resource_group="test-rg-plan-0"),
        plan_template({"planstorage1": "create"}, suffix="-1", resource_group="test-rg-plan-1"),
    ]
    run_terraform_json_generation(templates, work_dir=str(tmp_path))

    payload = read_sidecar(str(tmp_path))
    assert payload["counts"]["delete"] == 1
    assert payload["counts"]["create"] == 1


def test_no_sidecar_in_legacy_mode(tmp_path):
    run_terraform_json_generation(
        [plan_template()],
        pass_change_types=False,
        work_dir=str(tmp_path),
    )

    output_dir = output_dir_of(str(tmp_path))
    assert glob.glob(os.path.join(output_dir, f"*{CHANGE_SUMMARY_SUFFIX}")) == []


# ─── Write failure is a warning (Requirement 7.5) ────────────────────────────


def test_a_sidecar_write_failure_is_downgraded_to_a_warning(tmp_path):
    """An unwritable target must warn and return None instead of raising."""
    missing_dir = tmp_path / "does-not-exist" / "azure_resources_20240101_000000"
    summary = ChangeSummary(counts={"delete": 1}, present_categories=["delete"])

    with captured_logs() as handler:
        result = write_change_summary_sidecar(summary, str(missing_dir / "azure_resources_20240101_000000"))

    assert result is None
    warnings = handler.messages(logging.WARNING)
    assert any("change summary sidecar" in message for message in warnings), warnings


def test_a_successful_write_returns_the_sidecar_path(tmp_path):
    summary = ChangeSummary(
        counts={"create": 2},
        present_categories=["create"],
        not_displayed=[UndisplayedChange("a.b", "azurerm_x", "create", NO_RESOURCE_ENTRY_REASON)],
    )
    output_filename = str(tmp_path / "azure_resources_20240101_000000")

    path = write_change_summary_sidecar(summary, output_filename)

    assert path == f"{output_filename}{CHANGE_SUMMARY_SUFFIX}"
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    assert payload["counts"]["create"] == 2
    assert payload["notDisplayed"][0]["address"] == "a.b"
    assert payload["changeStyles"]["delete"]["flag"] == "-"


# ─── Run-level aggregation helpers ───────────────────────────────────────────


def test_build_run_change_summary_reports_an_address_once():
    entry = {"address": "a.b", "terraformType": "azurerm_x", "category": "delete", "reason": SKIP_FILTER_REASON}
    summary = build_run_change_summary({"delete": 2}, [entry, dict(entry)])

    assert [item.address for item in summary.not_displayed] == ["a.b"]
    assert summary.present_categories == ["delete"]


@pytest.mark.parametrize(
    "entry",
    [None, "text", 42, {}, {"address": ""}, {"address": 7}],
)
def test_build_run_change_summary_drops_malformed_entries(entry):
    summary = build_run_change_summary({"create": 1}, [entry])
    assert summary.not_displayed == []


def test_build_run_change_summary_normalizes_unknown_category_and_reason():
    summary = build_run_change_summary(
        {"create": 1},
        [{"address": "a.b", "terraformType": 5, "category": "forget", "reason": "mystery"}],
    )

    entry = summary.not_displayed[0]
    assert entry.terraform_type == ""
    assert entry.category == "unchanged"
    assert entry.reason == NO_RESOURCE_ENTRY_REASON


def test_change_styles_payload_covers_every_category():
    payload = change_styles_payload()
    assert set(payload) == set(CHANGE_CATEGORIES)
    assert payload["replace"] == {"color": "#D13438", "flag": "±", "label": "Replace"}
    assert payload["unchanged"] is None


# ─── Property 18: Every change is either rendered or reported ────────────────
# Feature: terraform-plan-diff-visualization, Property 18: For any Plan_File,
# each Change_Record whose Change_Category differs from `unchanged` is either
# present as a resource entry in the Renderer_Template or listed under
# `Changes not displayed` with its Terraform address, its Terraform type, and a
# reason drawn from {skip-filter, unmapped-type, no-resource-entry}; the
# Change_Summary reports the resource count of every Change_Category; and no
# Change_Summary is produced for Legacy_Mode inputs.


def _unmapped_types(model) -> set:
    """Return the Terraform types of the model that carry no renderer mapping.

    The builder falls back to `Terraform.Azurerm/<type>` for an Unmapped_Resource
    rather than dropping it, so the caller of `build_change_summary` is what
    declares those types unmapped — exactly as the graph pipeline does after its
    icon lookup comes up empty (Requirement 7.3).
    """
    return {
        record.terraform_type
        for record in model.records.values()
        if record.terraform_type not in _TERRAFORM_TO_RENDERER_TYPE
    }


def _resources_by_address(document) -> Dict[str, List[Any]]:
    """Group the post-filter document resources by their Terraform address."""
    grouped: Dict[str, List[Any]] = {}
    for resource in document.resources:
        grouped.setdefault(resource.address, []).append(resource)
    return grouped


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(plan=plan_documents(max_resources=5), selection=change_filters())
def test_property_18_every_change_is_rendered_or_reported(plan, selection):
    """For any plan, every change either reaches a node or is reported once.

    Feature: terraform-plan-diff-visualization, Property 18: Every change is
    either rendered or reported — for any Plan_File, each Change_Record whose
    Change_Category differs from ``unchanged`` is either present as a resource
    entry in the Renderer_Template or listed under ``Changes not displayed`` with
    its Terraform address, its Terraform type, and a reason drawn from
    {skip-filter, unmapped-type, no-resource-entry}; the Change_Summary reports
    the resource count of every Change_Category; and no Change_Summary is
    produced for Legacy_Mode inputs.

    The two sides of the partition are read off the real pipeline: the
    Renderer_Template that `build_document_from_json` plus `ChangeFilter`
    produce, and the Change_Summary that `build_change_summary` derives from the
    same document. The generated type pool reaches all three reasons — unmapped
    azurerm types, Skip_Filter types such as `azurerm_network_security_group` and
    `azurerm_route_table`, and addresses the filter drops.

    **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.6**
    """
    model = ChangeExtractor().extract(plan.get("resource_changes"))
    builder = TerraformTemplateBuilder()
    document = ChangeFilter(selection).apply(builder.build_document_from_json(plan, change_model=model))
    template = document.to_renderer_template()
    summary = build_change_summary(model, document, unmapped=_unmapped_types(model))

    # ── The summary reports the count of every Change_Category (7.1) ──────────
    assert set(summary.counts) == set(CHANGE_CATEGORIES)
    assert summary.counts == model.counts
    assert sum(summary.counts.values()) == len(model.records)

    # ── Each reported change is reported once, with identifying metadata ──────
    reported: Dict[str, UndisplayedChange] = {}
    for entry in summary.not_displayed:
        assert entry.reason in UNDISPLAYED_REASONS
        assert entry.address in model.records
        assert entry.address not in reported, f"{entry.address} reported twice"
        assert entry.terraform_type == model.records[entry.address].terraform_type
        assert entry.category == model.records[entry.address].category
        reported[entry.address] = entry

    rendered_entries = {(resource["type"], resource["name"]) for resource in template["resources"]}
    grouped = _resources_by_address(document)

    for address, record in model.records.items():
        if record.category == UNCHANGED_CATEGORY:
            continue

        resources = grouped.get(address, [])
        displayable = [
            resource
            for resource in resources
            if record.terraform_type in _TERRAFORM_TO_RENDERER_TYPE
            and not is_skipped_by_skip_filter(resource.renderer_type)
        ]

        if displayable:
            # Rendered: a Renderer_Template entry exists, and nothing is reported.
            for resource in displayable:
                assert (resource.renderer_type, resource.name) in rendered_entries
            assert address not in reported, f"{address} is both rendered and reported"
            continue

        # Reported: never silently missing, and the reason matches the cause.
        entry = reported.get(address)
        assert entry is not None, f"{address} is neither rendered nor reported"
        if record.terraform_type not in _TERRAFORM_TO_RENDERER_TYPE:
            assert entry.reason == UNMAPPED_TYPE_REASON  # Requirement 7.3
        elif not resources:
            assert entry.reason == NO_RESOURCE_ENTRY_REASON  # Requirement 7.4
        else:
            assert entry.reason == SKIP_FILTER_REASON  # Requirement 7.2

    # ── The console rendering carries the same information ────────────────────
    lines = format_change_summary(summary)
    assert lines[0] == SUMMARY_HEADING
    for category in CHANGE_CATEGORIES:
        assert f"{category} {summary.counts[category]}" in collapsed(lines)
    if reported:
        assert f"{NOT_DISPLAYED_HEADING} ({len(reported)})" in lines
        joined = "\n".join(lines)
        for entry in reported.values():
            assert entry.address in joined
            assert entry.terraform_type in joined
            assert f"({REASON_LABELS[entry.reason]})" in joined
    else:
        assert NOT_DISPLAYED_HEADING not in "\n".join(lines)

    # ── Legacy_Mode produces no Change_Summary at all (7.6) ──────────────────
    legacy_plan = {key: value for key, value in plan.items() if key != "resource_changes"}
    legacy_document = builder.build_document_from_json(legacy_plan)
    assert "changeCounts" not in legacy_document.metadata
    assert "changeModel" not in legacy_document.metadata
    assert "changesNotDisplayed" not in legacy_document.metadata

    # The graph pipeline guards the summary on the aggregated counts, which stay
    # empty for a legacy template, and an absent summary formats to no lines.
    legacy_counts: Dict[str, int] = {}
    legacy_entries: List[Any] = []
    accumulate_change_metadata(legacy_document.to_renderer_template(), legacy_counts, legacy_entries)
    assert legacy_counts == {}
    assert legacy_entries == []
    assert format_change_summary(None) == []


# ─── Property 23: Plan diff activation and scope resolution parity ───────────
# Feature: terraform-plan-diff-visualization, Property 23: For any Terraform
# JSON document, Plan_Diff_Mode artifacts (`changeCategory` keys and
# `metadata.changeCounts`) appear exactly when the document contains a
# `resource_changes` array, and for any scope metadata input the resolved
# tenants, subscriptions, and resource groups are identical whether or not the
# document contains that array.

#: The metadata keys `build_document_from_json` adds in Plan_Diff_Mode only.
CHANGE_METADATA_KEYS = ("changeCounts", "changeModel", "changesNotDisplayed")

#: The scope lists `main.main()` hands to the generator service.
SCOPE_KEYS = ("tenants", "subscriptions", "resource_groups")

_SCOPE_NAMES = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=12)


def scope_metadata_documents() -> st.SearchStrategy[Dict[str, Any]]:
    """A `--scopeMetadataFiles` document as `_extract_scope_metadata` reads it."""
    return st.fixed_dictionaries(
        {
            "_cloudHorus": st.fixed_dictionaries(
                {
                    "provider": st.just("azurerm"),
                    "tenant": _SCOPE_NAMES,
                    "subscription": _SCOPE_NAMES,
                    "resourceGroup": _SCOPE_NAMES,
                }
            )
        }
    )


def write_json(path: str, document: Any) -> str:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(document, handle)
    return path


def categories_of(template: Dict[str, Any]) -> List[Optional[str]]:
    """The `changeCategory` value of every resource entry, `None` when absent."""
    return [resource.get("changeCategory") for resource in template["resources"]]


def change_metadata_keys_of(template: Dict[str, Any]) -> set:
    metadata = template.get("metadata", {})
    return {key for key in CHANGE_METADATA_KEYS if key in metadata}


def without_change_keys(template: Dict[str, Any]) -> Dict[str, Any]:
    """Strip every Plan_Diff_Mode artifact, leaving the Legacy_Mode shape."""
    stripped = dict(template)
    stripped["resources"] = [
        {key: value for key, value in resource.items() if key != "changeCategory"}
        for resource in template["resources"]
    ]
    metadata = {key: value for key, value in template.get("metadata", {}).items() if key not in CHANGE_METADATA_KEYS}
    if "metadata" in template:
        stripped["metadata"] = metadata
    return stripped


@contextmanager
def preserved_cli_environment():
    """Keep the CLI's environment side effects out of the rest of the suite."""
    watched = ("CLOUDHORUS_NON_INTERACTIVE", "CLOUDHORUS_AUTH_METHOD")
    snapshot = {name: os.environ.get(name) for name in watched}
    try:
        yield
    finally:
        for name, value in snapshot.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def resolved_scope(
    plan_files: List[str],
    scope_files: List[str],
    change_types: Optional[List[str]] = None,
) -> Dict[str, List[str]]:
    """Run the real CLI scope resolution and return the scope lists it forwards.

    Everything up to `GraphGeneratorService` is `main.main()` itself: argument
    parsing, Terraform JSON mode detection, the `--scopeMetadataFiles` count and
    existence checks, `parse_scope_metadata_files` and `scope_lists_from_scopes`.
    Only the generation call is doubled, so what comes back is exactly the scope
    the pipeline would render with.
    """
    argv = ["cloudhorus", "--terraformJsonFiles", *plan_files, "--scopeMetadataFiles", *scope_files]
    if change_types:
        argv += ["--changeTypes", *change_types]
    argv += ["--nonInteractive", "true"]

    with (
        preserved_cli_environment(),
        patch.object(sys, "argv", argv),
        patch.object(main, "logger"),
        patch.object(main, "GraphGeneratorService") as service_class,
    ):
        service = service_class.return_value
        service.validate.return_value = True
        service.generate_graph.return_value = "azure_resources.png"

        main.main()  # a non-zero exit raises SystemExit and fails the property

        kwargs = service.generate_graph.call_args.kwargs

    return {key: list(kwargs[key]) for key in SCOPE_KEYS}


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
@given(
    plan=plan_documents(max_resources=4),
    plain_plan=plan_documents(max_resources=4, with_resource_changes=False),
    scopes=st.lists(scope_metadata_documents(), min_size=2, max_size=2),
)
def test_property_23_plan_diff_activation_and_scope_parity(plan, plain_plan, scopes, tmp_path):
    """Plan_Diff_Mode switches on `resource_changes`, and scope resolution does not.

    Feature: terraform-plan-diff-visualization, Property 23: Plan diff
    activation and scope resolution parity — for any Terraform JSON document,
    Plan_Diff_Mode artifacts (`changeCategory` keys and `metadata.changeCounts`)
    appear exactly when the document contains a `resource_changes` array, and for
    any scope metadata input the resolved tenants, subscriptions, and resource
    groups are identical whether or not the document contains that array.

    Activation is read off `_build_plan_document`, the single decision point of
    the builder. The design splits Requirement 1.2 in two: an **absent** array
    takes the exact legacy path, so no resource carries a `changeCategory` key at
    all and the resources still render as unchanged because
    `resolve_style(None)` and `resolve_style("unchanged")` are the same absence of
    decoration; an **empty** array is Plan_Diff_Mode with every resource
    explicitly `unchanged`. Both are asserted, together with the equality of the
    two renderer templates once the additive keys are stripped.

    Scope parity is read off the real `main.main()` path with only the generation
    call doubled, so the comparison is between the scope lists the pipeline would
    actually receive.

    **Validates: Requirements 1.1, 1.2, 1.7**
    """
    builder = TerraformTemplateBuilder()
    stripped_plan = {key: value for key, value in plan.items() if key != "resource_changes"}
    empty_changes_plan = {**stripped_plan, "resource_changes": []}

    diff_template = builder._build_plan_document(plan).to_renderer_template()
    legacy_template = builder._build_plan_document(stripped_plan).to_renderer_template()
    plain_template = builder._build_plan_document(plain_plan).to_renderer_template()
    empty_template = builder._build_plan_document(empty_changes_plan).to_renderer_template()

    # ── Activation: artifacts appear exactly with a `resource_changes` array (1.1) ──
    assert change_metadata_keys_of(diff_template) == set(CHANGE_METADATA_KEYS)
    assert all(category in CHANGE_CATEGORIES for category in categories_of(diff_template))

    assert change_metadata_keys_of(empty_template) == set(CHANGE_METADATA_KEYS)

    for legacy in (legacy_template, plain_template):
        assert change_metadata_keys_of(legacy) == set()
        assert categories_of(legacy) == [None] * len(legacy["resources"])

    # ── Requirement 1.2, absent array: legacy path, rendered as unchanged ─────
    assert legacy_template == builder.build_document_from_json(stripped_plan).to_renderer_template()
    assert resolve_style(None) is None
    assert resolve_style(UNCHANGED_CATEGORY) is None

    # ── Requirement 1.2, empty array: Plan_Diff_Mode, everything unchanged ────
    assert categories_of(empty_template) == [UNCHANGED_CATEGORY] * len(empty_template["resources"])
    assert empty_template["metadata"]["changeCounts"] == {category: 0 for category in CHANGE_CATEGORIES}
    # The only difference between the two readings of Requirement 1.2 is the
    # additive metadata, so both render the same resources the same way.
    assert without_change_keys(empty_template) == legacy_template

    # ── Requirement 1.7: scope resolution is identical in both modes ──────────
    diff_file = write_json(str(tmp_path / "diff-plan.json"), plan)
    legacy_file = write_json(str(tmp_path / "legacy-plan.json"), stripped_plan)
    scope_files = [write_json(str(tmp_path / f"scope-{index}.json"), scope) for index, scope in enumerate(scopes)]

    expected_single = scope_lists_from_scopes(parse_scope_metadata_files(scope_files[:1])["scopes"])
    single_scopes = [
        resolved_scope([diff_file], scope_files[:1]),
        resolved_scope([legacy_file], scope_files[:1]),
        resolved_scope([diff_file], scope_files[:1], change_types=["delete"]),
    ]
    for resolved in single_scopes:
        assert resolved == {
            "tenants": expected_single["tenants"],
            "subscriptions": expected_single["subscriptions"],
            "resource_groups": expected_single["resourcegroups"],
        }

    # Two inputs: the scope file at position i belongs to the plan at position i,
    # whichever of the two carries a `resource_changes` array.
    expected_pair = scope_lists_from_scopes(parse_scope_metadata_files(scope_files)["scopes"])
    pair_scopes = [
        resolved_scope([diff_file, legacy_file], scope_files),
        resolved_scope([legacy_file, diff_file], scope_files),
    ]
    for resolved in pair_scopes:
        assert resolved == {
            "tenants": expected_pair["tenants"],
            "subscriptions": expected_pair["subscriptions"],
            "resource_groups": expected_pair["resourcegroups"],
        }
