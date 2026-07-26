"""WebUI tests for the Terraform plan diff feature.

Two layers:

* Python marshalling — `CloudHorusAPI._build_command`, `read_change_summary`,
  `rerun_with_change_types` and the `pick_files` plan branch.
* DOM behaviour — the real `webui/app.js` executed in Node on top of the stub DOM
  in `tests/webui_dom_harness.js`, seeded from the real `webui/index.html`.
  The repository ships no JS toolchain, so this keeps the front-end assertions in
  the pytest suite at the cost of a stub DOM that models only what app.js touches
  (see the harness header for the tradeoff).

Requirements: 1.3, 6.1, 6.2, 6.8, 7.5, 8.4, 8.8, 11.3
"""

import json
import os
import shutil
import subprocess
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import cloudhorus_webui  # noqa: E402
from cloudhorus_webui import CloudHorusAPI  # noqa: E402
from core.plan_diff import CHANGE_CATEGORIES  # noqa: E402

HARNESS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webui_dom_harness.js")
INDEX_HTML = os.path.join(PROJECT_ROOT, "webui", "index.html")
NODE = shutil.which("node")

requires_node = pytest.mark.skipif(NODE is None, reason="node is required for the WebUI DOM harness")


@pytest.fixture
def api():
    return CloudHorusAPI()


def base_terraform_args(**overrides):
    """Argument payload shaped like the one webui/app.js posts for Terraform mode."""
    args = {
        "mode": "terraform",
        "authMethod": "device-code",
        "edgeDirection": "TB",
        "tenantDirection": "LR",
        "maxSubnetPerline": 4,
        "resourcesEdgeLength": 1,
        "rankDebug": False,
        "privateDnsZonesOptimization": True,
    }
    args.update(overrides)
    return args


def arg_values(cmd, flag):
    """Values following *flag* in a built command, up to the next flag."""
    if flag not in cmd:
        return None
    values = []
    for token in cmd[cmd.index(flag) + 1 :]:
        if token.startswith("--"):
            break
        values.append(token)
    return values


# ─── _build_command marshalling ───────────────────────────────────────────


def test_build_command_emits_terraform_json_files_for_a_plan_selection(api):
    """Requirement 1.3: the plan selection reaches the CLI as --terraformJsonFiles."""
    cmd = api._build_command(base_terraform_args(terraformJsonFiles=["/plans/network.plan.json"]))

    assert arg_values(cmd, "--terraformJsonFiles") == ["/plans/network.plan.json"]
    assert "--terraformRootDirs" not in cmd
    assert "--terraformVarFiles" not in cmd


def test_build_command_plan_selection_wins_over_source_selection(api):
    """A plan replaces the source pairing for that run (Requirement 1.5 marshalling side)."""
    cmd = api._build_command(
        base_terraform_args(
            terraformJsonFiles=["/plans/app.plan.json"],
            terraformRootDirs=["/stacks/app"],
            terraformVarFiles=["/stacks/app/app.tfvars"],
        )
    )

    assert arg_values(cmd, "--terraformJsonFiles") == ["/plans/app.plan.json"]
    assert "--terraformRootDirs" not in cmd
    assert "--terraformVarFiles" not in cmd


def test_build_command_appends_change_types_for_a_strict_subset(api):
    """Requirement 8.3: only a strict subset narrows the run, in canonical order."""
    cmd = api._build_command(
        base_terraform_args(
            terraformJsonFiles=["/plans/network.plan.json"],
            changeTypes=["delete", "create"],
        )
    )

    assert arg_values(cmd, "--changeTypes") == ["create", "delete"]


def test_build_command_omits_change_types_for_the_full_set_and_for_no_selection(api):
    """The full category set is the CLI default, so it stays off the command line."""
    full = api._build_command(
        base_terraform_args(
            terraformJsonFiles=["/plans/network.plan.json"],
            changeTypes=list(CHANGE_CATEGORIES),
        )
    )
    empty = api._build_command(base_terraform_args(terraformJsonFiles=["/plans/network.plan.json"]))

    assert "--changeTypes" not in full
    assert "--changeTypes" not in empty


def test_build_command_drops_unknown_change_types(api):
    cmd = api._build_command(
        base_terraform_args(
            terraformJsonFiles=["/plans/network.plan.json"],
            changeTypes=["delete", "explode", ""],
        )
    )

    assert arg_values(cmd, "--changeTypes") == ["delete"]


def test_build_command_source_only_selection_is_unchanged(api):
    """Requirement 8.8: without a plan file the Terraform card marshals as before."""
    source_args = base_terraform_args(
        terraformRootDirs=["/stacks/network", "/stacks/app"],
        terraformVarFiles=["/stacks/network/net.tfvars", "/stacks/app/app.tfvars"],
    )
    cmd = api._build_command(source_args)

    assert arg_values(cmd, "--terraformRootDirs") == ["/stacks/network", "/stacks/app"]
    assert arg_values(cmd, "--terraformVarFiles") == [
        "/stacks/network/net.tfvars",
        "/stacks/app/app.tfvars",
    ]
    assert "--terraformJsonFiles" not in cmd
    assert "--changeTypes" not in cmd

    # A stale change-type selection must not leak into a source-only run either
    with_change_types = api._build_command(dict(source_args, changeTypes=["delete"]))
    assert with_change_types == cmd


# ─── read_change_summary ──────────────────────────────────────────────────


def write_sidecar(tmp_path, payload, png_name="azure_resources_20240101_101010.png"):
    png_path = tmp_path / png_name
    png_path.write_bytes(b"")
    sidecar = tmp_path / (png_path.stem + cloudhorus_webui._change_summary_suffix())
    sidecar.write_text(json.dumps(payload), encoding="utf-8")
    return str(png_path), sidecar


def test_read_change_summary_reads_the_sidecar_beside_the_png(api, tmp_path):
    """Requirement 7.5: the WebUI reads the Change_Summary written next to the PNG."""
    payload = {
        "counts": {"create": 2, "update": 0, "replace": 0, "delete": 1, "unchanged": 4},
        "presentCategories": ["create", "delete", "unchanged"],
        "notDisplayed": [{"address": "azurerm_kusto_cluster.analytics", "reason": "unmapped-type"}],
        "changeStyles": {"create": {"color": "#107C10", "flag": "+"}},
    }
    png_path, _ = write_sidecar(tmp_path, payload)

    assert api.read_change_summary(png_path) == payload


def test_read_change_summary_returns_none_without_a_sidecar(api, tmp_path):
    """A Legacy_Mode run writes no sidecar, which is not an error."""
    png_path = tmp_path / "azure_resources_20240101_101010.png"
    png_path.write_bytes(b"")

    assert api.read_change_summary(str(png_path)) is None


def test_read_change_summary_returns_none_for_unreadable_payloads(api, tmp_path):
    png_path, sidecar = write_sidecar(tmp_path, {})
    sidecar.write_text("{ not json", encoding="utf-8")

    assert api.read_change_summary(png_path) is None


# ─── rerun_with_change_types ──────────────────────────────────────────────


def test_rerun_with_change_types_swaps_only_the_selection(api, monkeypatch):
    """Requirement 6.9: a filtered re-run differs from the first run by --changeTypes alone."""
    captured = {}

    def fake_start_generation(args_json):
        captured["args"] = json.loads(args_json)
        return {"success": True, "file": "/out/azure_resources.png"}

    monkeypatch.setattr(api, "start_generation", fake_start_generation)

    original = base_terraform_args(
        terraformJsonFiles=["/plans/network.plan.json"],
        scopeMetadataFiles=["/plans/scope.json"],
        changeTypes=list(CHANGE_CATEGORIES),
    )
    result = api.rerun_with_change_types(json.dumps(original), ["delete", "create", "nonsense"])

    assert result == {"success": True, "file": "/out/azure_resources.png"}
    assert captured["args"]["changeTypes"] == ["create", "delete"]
    assert captured["args"]["terraformJsonFiles"] == ["/plans/network.plan.json"]
    assert captured["args"]["scopeMetadataFiles"] == ["/plans/scope.json"]
    # Everything except the selection is carried over untouched
    assert {k: v for k, v in captured["args"].items() if k != "changeTypes"} == {
        k: v for k, v in original.items() if k != "changeTypes"
    }


def test_rerun_with_change_types_reports_invalid_payloads(api):
    result = api.rerun_with_change_types("{ not json", ["delete"])

    assert result["success"] is False
    assert "Invalid args" in result["error"]


# ─── pick_files plan branch ───────────────────────────────────────────────


class FakeWindow:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def create_file_dialog(self, dialog_type, allow_multiple=False, file_types=()):
        self.calls.append({"type": dialog_type, "allow_multiple": allow_multiple, "file_types": file_types})
        return self.result


def test_pick_files_terraform_plan_offers_json_files(api):
    """Requirement 1.3: the plan control accepts .json files."""
    window = FakeWindow(["/plans/network.plan.json"])
    api.set_window(window)

    selected = api.pick_files("terraform-plan")

    assert selected == ["/plans/network.plan.json"]
    assert any("*.json" in entry for entry in window.calls[0]["file_types"])
    assert window.calls[0]["allow_multiple"] is True


# ─── index.html structure ─────────────────────────────────────────────────


def read_index_html():
    with open(INDEX_HTML, "r", encoding="utf-8") as handle:
        return handle.read()


def test_index_html_keeps_the_source_zones_and_adds_the_plan_zone():
    """Requirements 1.3, 8.8: the plan zone is additive next to main.tf / .tfvars."""
    html = read_index_html()

    for element_id in (
        'id="drop-terraform-main"',
        'id="file-list-terraform-main"',
        'id="drop-terraform-vars"',
        'id="file-list-terraform-vars"',
        'id="drop-terraform-plan"',
        'id="file-list-terraform-plan"',
    ):
        assert element_id in html

    plan_zone_start = html.index('id="drop-terraform-plan"')
    section_start = html.index('id="section-terraform-files"')
    assert section_start < plan_zone_start


def test_index_html_ships_a_hidden_change_filter_panel():
    """Requirements 6.1, 7.5, 8.4: chips and badge exist and start hidden."""
    html = read_index_html()

    panel_start = html.index('id="change-filter-panel"')
    panel_tag_start = html.rindex("<div", 0, panel_start)
    panel_tag = html[panel_tag_start : html.index(">", panel_start)]
    assert "hidden" in panel_tag

    # Chips and badge live inside the panel, ahead of the viewer action buttons
    panel_block = html[panel_start : html.index('class="viewer-actions"', panel_start)]
    assert 'id="change-filter-chips"' in panel_block
    assert 'id="change-undisplayed-badge"' in panel_block

    badge_start = html.index('id="change-undisplayed-badge"')
    badge_tag = html[html.rindex("<span", 0, badge_start) : html.index(">", badge_start)]
    assert "hidden" in badge_tag


# ─── DOM behaviour through the app.js harness ─────────────────────────────


def run_app_js(snippet):
    """Run *snippet* inside the app.js script scope and return the harness payload."""
    completed = subprocess.run(
        [NODE, HARNESS],
        input=snippet,
        capture_output=True,
        text=True,
        timeout=120,
        cwd=PROJECT_ROOT,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["ok"], payload.get("error")
    return payload


PLAN_DIFF_SETUP = """
state.mode = 'terraform';
state.terraformPlanFiles = ['/plans/network.plan.json'];
"""


@requires_node
def test_app_js_change_categories_match_the_python_definition():
    payload = run_app_js(
        "return { categories: CHANGE_CATEGORIES, empty: EMPTY_SELECTION_MESSAGE, "
        "conflict: TERRAFORM_INPUT_CONFLICT_MESSAGE };"
    )

    assert payload["value"]["categories"] == list(CHANGE_CATEGORIES)
    assert payload["value"]["empty"] == "No resources match the selected change types"
    assert payload["value"]["conflict"] == "Choose exactly one Terraform input: plan JSON or source directories"


@requires_node
def test_chips_render_one_control_per_present_category_all_selected():
    """Requirements 6.1, 6.2: one chip per present category, every one selected."""
    payload = run_app_js(
        PLAN_DIFF_SETUP
        + """
applyChangeSummary({
  counts: { create: 2, update: 0, replace: 0, delete: 3, unchanged: 5 },
  presentCategories: ['delete', 'create', 'unchanged'],
  notDisplayed: []
});
return { snapshot: __domSnapshot(), selected: selectedChangeTypes() };
"""
    )
    value = payload["value"]
    chips = value["snapshot"]["chipsHtml"]

    assert 'id="change-chip-create"' in chips
    assert 'id="change-chip-delete"' in chips
    assert 'id="change-chip-unchanged"' in chips
    assert 'id="change-chip-update"' not in chips
    assert 'id="change-chip-replace"' not in chips

    assert chips.count('aria-pressed="true"') == 3
    assert 'aria-pressed="false"' not in chips
    assert '<span class="change-chip-count">3</span>' in chips
    assert "#107C10" in chips  # create colour token stays with the chip

    # Canonical order, and the panel becomes visible for a Plan_Diff_Mode run
    assert value["selected"] == ["create", "delete", "unchanged"]
    assert value["snapshot"]["panelHidden"] is False


@requires_node
def test_deselecting_every_category_keeps_the_diagram_and_reports_the_message():
    """Requirement 6.8: empty selection shows the message and retains the diagram."""
    payload = run_app_js(
        PLAN_DIFF_SETUP
        + """
document.getElementById('viewer-img').src = 'data:image/png;base64,PREVIOUS';
window.pywebview.api.rerun_with_change_types = async function () {
  __record('rerun', {});
  return { success: true };
};
applyChangeSummary({
  counts: { create: 1, delete: 1 },
  presentCategories: ['create', 'delete'],
  notDisplayed: []
});
await toggleChangeType('create');
await toggleChangeType('delete');
return { snapshot: __domSnapshot() };
"""
    )
    calls = payload["calls"]
    snapshot = payload["value"]["snapshot"]

    toasts = [c for c in calls if c["fn"] == "showToast"]
    assert toasts[-1]["message"] == "No resources match the selected change types"
    assert toasts[-1]["type"] == "warning"

    # One re-run for the intermediate single-category selection, none once empty
    assert len([c for c in calls if c["fn"] == "rerun"]) == 1
    assert snapshot["changeTypes"] == []
    assert snapshot["imgSrc"] == "data:image/png;base64,PREVIOUS"
    assert [c for c in calls if c["fn"] == "showImage"] == []


@requires_node
def test_undisplayed_badge_reports_the_count_of_changes_not_displayed():
    """Requirement 7.5: the count of undisplayed changes sits next to the chips."""
    payload = run_app_js(
        PLAN_DIFF_SETUP
        + """
const results = {};
applyChangeSummary({
  counts: { delete: 2 },
  presentCategories: ['delete'],
  notDisplayed: [
    { address: 'azurerm_subnet.legacy', reason: 'skip-filter' },
    { address: 'azurerm_kusto_cluster.analytics', reason: 'unmapped-type' }
  ]
});
results.plural = __domSnapshot();
applyChangeSummary({
  counts: { delete: 2 },
  presentCategories: ['delete'],
  notDisplayed: [{ address: 'azurerm_subnet.legacy', reason: 'skip-filter' }]
});
results.singular = __domSnapshot();
applyChangeSummary({ counts: { delete: 2 }, presentCategories: ['delete'], notDisplayed: [] });
results.none = __domSnapshot();
return results;
"""
    )
    value = payload["value"]

    assert value["plural"]["badgeText"] == "2 changes not displayed"
    assert value["plural"]["badgeHidden"] is False
    assert value["singular"]["badgeText"] == "1 change not displayed"
    assert value["singular"]["badgeHidden"] is False
    assert value["none"]["badgeText"] == ""
    assert value["none"]["badgeHidden"] is True


@requires_node
def test_filter_panel_is_hidden_outside_plan_diff_mode():
    """Requirement 8.4: Live, Bicep and Terraform source selections hide the chips."""
    payload = run_app_js(
        PLAN_DIFF_SETUP
        + """
applyChangeSummary({
  counts: { create: 1, delete: 1 },
  presentCategories: ['create', 'delete'],
  notDisplayed: []
});
const results = { planDiff: __domSnapshot().panelHidden };
selectMode('live');
results.live = __domSnapshot().panelHidden;
selectMode('bicep');
results.bicep = __domSnapshot().panelHidden;
selectMode('terraform');
results.terraformPlan = __domSnapshot().panelHidden;
state.terraformPlanFiles = [];
selectMode('terraform');
results.terraformSource = __domSnapshot().panelHidden;
return results;
"""
    )
    value = payload["value"]

    assert value["planDiff"] is False
    assert value["live"] is True
    assert value["bicep"] is True
    assert value["terraformPlan"] is False
    assert value["terraformSource"] is True


@requires_node
def test_progress_indicator_stays_up_during_a_filtered_rerun():
    """Requirements 6.3, 11.3: the chip toggle re-runs with the selection under a progress indicator."""
    payload = run_app_js(
        PLAN_DIFF_SETUP
        + """
let duringRun = null;
window.pywebview.api.rerun_with_change_types = async function (argsJson, changeTypes) {
  duringRun = {
    progressHidden: document.getElementById('progress-container').classList.contains('hidden'),
    running: state.running,
    changeTypes: changeTypes,
    args: JSON.parse(argsJson)
  };
  return { success: true, file: '/out/azure_resources_20240101/azure_resources_20240101.png' };
};
window.pywebview.api.read_change_summary = async function () {
  return { counts: { delete: 3 }, presentCategories: ['delete'], notDisplayed: [] };
};
applyChangeSummary({
  counts: { create: 1, delete: 3 },
  presentCategories: ['create', 'delete'],
  notDisplayed: []
});
const beforeRun = __domSnapshot().progressHidden;
await toggleChangeType('create');
return { beforeRun: beforeRun, duringRun: duringRun, after: __domSnapshot() };
"""
    )
    value = payload["value"]

    assert value["beforeRun"] is True
    # Progress indicator visible, and the run flagged as in flight, while filtering
    assert value["duringRun"]["progressHidden"] is False
    assert value["duringRun"]["running"] is True
    # The selection reaches the backend, and only the selection changed
    assert value["duringRun"]["changeTypes"] == ["delete"]
    assert value["duringRun"]["args"]["changeTypes"] == ["delete"]
    assert value["duringRun"]["args"]["terraformJsonFiles"] == ["/plans/network.plan.json"]

    after = value["after"]
    assert after["running"] is False
    assert after["changeTypes"] == ["delete"]  # selection survives the round trip
    assert "--changeTypes delete" in after["commandPreview"]
    assert [c["file"] for c in payload["calls"] if c["fn"] == "showImage"] == [
        "/out/azure_resources_20240101/azure_resources_20240101.png"
    ]
