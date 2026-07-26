"""Performance benchmarks for the Terraform plan diff on large plans.

Task 11.1 of the terraform-plan-diff-visualization spec, covering Requirement 11:

* 11.1 - the Change_Extractor turns a plan holding 5000 managed change entries
  into a Change_Model in under 5 seconds;
* 11.2 - the runtime the diff feature *adds* stays below 10 percent of the total
  generation runtime for the same 5000-entry plan.

What is measured for 11.2, and why
----------------------------------
Requirement 11.2 is a ratio, so it needs a numerator (what the diff adds) and a
denominator (the total generation runtime). Timing a diff-enabled generation
against a diff-disabled one and asserting on the difference of the two totals is
the obvious shape, and it is the wrong one here: the two totals are dominated by
graph rendering, which is the same work in both runs, so the difference is a
small number obtained by subtracting two large noisy ones. This module measures
the two sides separately instead, each in the way that makes the assertion hold
for the right reason.

**Numerator - everything the diff adds, at the full 5000 entries.**
Two parts, summed:

* the *document build delta*: the same 5000-entry plan built with and without
  its ``resource_changes`` array. The diff-enabled side additionally performs
  change extraction, delete reconstruction, sensitive redaction, the
  ``change_category`` assignment, the change metadata, and the Change_Filter
  pass, so the difference is exactly the diff work inside the build. Both plans
  describe the same resource set - the benchmark asserts equal resource counts
  before comparing timings - so the delta is not a different amount of
  normalization;
* the *styling and reporting phases* that the graph pipeline runs on top:
  ``resolve_style``/``decorate_label`` once per node label, the Legend label,
  and Change_Summary generation.

This is a superset of the three phases Requirement 11.2 names, which keeps the
numerator on the safe side of the requirement.

**Denominator - a deliberate under-estimate of the total generation runtime.**
The denominator is one full pass through ``generate_resource_graph`` over a
plan-diff template, with Graphviz layout faked out, at
``GENERATION_ENTRY_COUNT`` resources rather than at 5000. Both reductions shrink
the denominator, and a smaller denominator can only make the measured percentage
*larger* than the real one, so passing this assertion implies passing the
requirement:

* Graphviz layout is pure denominator - the ``dot`` process does not care
  whether labels carry change decoration - and at 5000 nodes it costs tens of
  seconds of external-process time that would make the benchmark slow and noisy
  for no gain in what is being verified;
* the render pass is measured at ``GENERATION_ENTRY_COUNT`` resources because
  its per-resource cost grows with the resource count (measured on the
  development machine: 1.8 ms/resource at 500 resources, 5.9 ms at 2000, 12.8 ms
  at 5000 - the subnet and edge passes are super-linear). A render pass over
  fewer resources is therefore strictly cheaper than the 5000-resource pass the
  requirement talks about, and the numerator is still measured at the full 5000.

The resulting margin is wide - the diff work lands in the low single-digit
percent of a denominator that is itself an order of magnitude below a real
5000-resource render - which is what keeps the assertion stable across machines
instead of turning it into a speed test of the host.

Timing tests are sensitive to machine load. The cheap measurements are the
minimum of several repetitions (the least-disturbed run), the expensive render
pass runs once, and the whole module is marked ``performance`` so it can be
deselected with ``-m "not performance"``.
"""

import time
from typing import Any, Callable, Dict, List, Optional, Sequence

import pytest

from test_plan_diff_graph_plumbing import run_terraform_json_generation

from core.plan_diff import (
    ChangeExtractor,
    ChangeModel,
    build_change_summary,
    format_change_summary,
)
from core.terraform_builder import TerraformTemplateBuilder
from utils.change_style import decorate_label, legend_label, resolve_style

pytestmark = pytest.mark.performance

PROVIDER = "registry.terraform.io/hashicorp/azurerm"
SUBSCRIPTION = "00000000-0000-0000-0000-000000000000"
RESOURCE_GROUP = "rg-landing-zone"

#: Plan size Requirement 11 is written against.
ENTRY_COUNT = 5000

#: Requirement 11.1 budget.
EXTRACTION_BUDGET_SECONDS = 5.0

#: Requirement 11.2 budget, as a fraction of the total generation runtime.
OVERHEAD_BUDGET_RATIO = 0.10

#: Resource count of the render pass used as the Requirement 11.2 denominator.
#: Deliberately below `ENTRY_COUNT`; see the module docstring for why that keeps
#: the assertion conservative. Raise it for a stricter (and much slower) run.
GENERATION_ENTRY_COUNT = 2000

#: Repetitions per cheap measured path; the minimum is kept.
REPEATS = 3

#: Stand-in for the HTML table label `add_node_in_subgraph` builds per node.
LABEL_TEMPLATE = (
    "<<TABLE border='0' cellborder='0' cellspacing='0'>"
    "<TR><TD>{name}</TD></TR>"
    "<TR><TD><FONT POINT-SIZE='9'>{short_type}</FONT></TD></TR>"
    "</TABLE>>"
)

# Actions cycled through the synthetic plan. The delete-free cycle keeps every
# change entry backed by a `planned_values` resource, which is what makes the
# diff-enabled and diff-disabled document builds comparable.
ACTION_CYCLE_WITH_DELETES: Sequence[List[str]] = (
    ["create"],
    ["update"],
    ["delete"],
    ["create", "delete"],
    ["no-op"],
    ["read"],
)
ACTION_CYCLE_WITHOUT_DELETES: Sequence[List[str]] = (["create"], ["update"], ["no-op"])


def _subnet_id(vnet_name: str, subnet_name: str) -> str:
    return (
        f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{RESOURCE_GROUP}"
        f"/providers/Microsoft.Network/virtualNetworks/{vnet_name}/subnets/{subnet_name}"
    )


def _synthetic_entry(index: int) -> Dict[str, Any]:
    """Build the Terraform type, name and values of one synthetic resource.

    Entries are laid out in repeating blocks of ten so the plan holds a realistic
    mix: virtual networks with subnets, storage accounts, web apps bound to a
    subnet, network security groups and route tables.
    """
    group = index // 10
    slot = index % 10
    vnet_name = f"vnet-{group}"
    subnet_name = f"snet-{group}-1"

    if slot == 0:
        return {
            "type": "azurerm_virtual_network",
            "name": vnet_name,
            "values": {
                "name": vnet_name,
                "location": "westeurope",
                "resource_group_name": RESOURCE_GROUP,
                "address_space": [f"10.{group % 250}.0.0/16"],
            },
        }
    if slot in (1, 2):
        name = f"snet-{group}-{slot}"
        return {
            "type": "azurerm_subnet",
            "name": name,
            "values": {
                "name": name,
                "resource_group_name": RESOURCE_GROUP,
                "virtual_network_name": vnet_name,
                "address_prefixes": [f"10.{group % 250}.{slot}.0/24"],
                "service_endpoints": ["Microsoft.Storage"],
            },
        }
    if slot in (3, 4, 5):
        name = f"st{group}{slot}"
        return {
            "type": "azurerm_storage_account",
            "name": name,
            "values": {
                "name": name,
                "location": "westeurope",
                "resource_group_name": RESOURCE_GROUP,
                "account_tier": "Standard",
                "account_replication_type": "LRS",
                "primary_access_key": "super-secret-key",
                "tags": {"env": "prod", "owner": "platform"},
            },
            # Exercises the Plan_Diff_Mode redaction pass (Requirement 10.1).
            "sensitive": {"primary_access_key": True},
        }
    if slot in (6, 7):
        name = f"app-{group}-{slot}"
        return {
            "type": "azurerm_linux_web_app",
            "name": name,
            "values": {
                "name": name,
                "location": "westeurope",
                "resource_group_name": RESOURCE_GROUP,
                "https_only": True,
                "virtual_network_subnet_id": _subnet_id(vnet_name, subnet_name),
            },
        }
    if slot == 8:
        name = f"nsg-{group}"
        return {
            "type": "azurerm_network_security_group",
            "name": name,
            "values": {
                "name": name,
                "location": "westeurope",
                "resource_group_name": RESOURCE_GROUP,
            },
        }
    name = f"rt-{group}"
    return {
        "type": "azurerm_route_table",
        "name": name,
        "values": {
            "name": name,
            "location": "westeurope",
            "resource_group_name": RESOURCE_GROUP,
        },
    }


def synthetic_plan(entry_count: int = ENTRY_COUNT, include_deletes: bool = True) -> Dict[str, Any]:
    """Build a plan document with `entry_count` managed `resource_changes` entries.

    Generated in memory rather than read from a fixture so the benchmark stays
    deterministic and carries no multi-megabyte file into the repository. Every
    change entry has a matching `planned_values` resource except the `delete`
    entries, which a real plan also omits from `planned_values`.
    """
    actions_cycle = ACTION_CYCLE_WITH_DELETES if include_deletes else ACTION_CYCLE_WITHOUT_DELETES

    resource_changes: List[Dict[str, Any]] = []
    planned_resources: List[Dict[str, Any]] = []

    for index in range(entry_count):
        entry = _synthetic_entry(index)
        terraform_type = entry["type"]
        address = f"{terraform_type}.r{index}"
        values = entry["values"]
        sensitive = entry.get("sensitive", {})
        actions = list(actions_cycle[index % len(actions_cycle)])
        is_delete_only = actions == ["delete"]

        resource_changes.append(
            {
                "address": address,
                "mode": "managed",
                "type": terraform_type,
                "name": entry["name"],
                "provider_name": PROVIDER,
                "change": {
                    "actions": actions,
                    "before": None if actions == ["create"] else values,
                    "after": None if is_delete_only else values,
                    "before_sensitive": {} if actions == ["create"] else dict(sensitive),
                    "after_sensitive": {} if is_delete_only else dict(sensitive),
                },
            }
        )

        if not is_delete_only:
            planned_resources.append(
                {
                    "address": address,
                    "mode": "managed",
                    "type": terraform_type,
                    "name": entry["name"],
                    "provider_name": PROVIDER,
                    "values": values,
                    "sensitive_values": dict(sensitive),
                }
            )

    return {
        "format_version": "1.2",
        "terraform_version": "1.7.5",
        "planned_values": {"root_module": {"resources": planned_resources}},
        "resource_changes": resource_changes,
    }


def renderer_template(entry_count: int) -> Dict[str, Any]:
    """Build the plan-diff renderer template of an `entry_count`-entry plan."""
    document = TerraformTemplateBuilder()._build_plan_document(
        synthetic_plan(entry_count, include_deletes=False), None
    )
    return document.to_renderer_template()


def measure(operation: Callable[[], Any], repeats: int = REPEATS) -> float:
    """Return the fastest wall-clock runtime of `operation` over `repeats` runs."""
    best: Optional[float] = None
    for _ in range(repeats):
        start = time.perf_counter()
        operation()
        elapsed = time.perf_counter() - start
        best = elapsed if best is None else min(best, elapsed)
    assert best is not None
    return best


# ─── Requirement 11.1 - extraction of 5000 managed entries ───────────────────


def test_extracting_5000_managed_entries_stays_within_the_budget(capsys) -> None:
    """The Change_Model of a 5000-entry plan is produced in under 5 seconds."""
    resource_changes = synthetic_plan(ENTRY_COUNT, include_deletes=True)["resource_changes"]
    assert len(resource_changes) == ENTRY_COUNT

    model = ChangeExtractor().extract(resource_changes)
    # Every managed entry is classified and held exactly once (Requirements 2.11, 11.4).
    assert len(model.records) == ENTRY_COUNT
    assert sum(model.counts.values()) == ENTRY_COUNT
    assert model.warnings == []

    elapsed = measure(lambda: ChangeExtractor().extract(resource_changes))

    with capsys.disabled():
        print(f"\n[perf] extraction of {ENTRY_COUNT} managed entries: {elapsed * 1000:.1f} ms")

    assert elapsed < EXTRACTION_BUDGET_SECONDS, (
        f"extraction of {ENTRY_COUNT} managed entries took {elapsed:.3f}s, "
        f"budget is {EXTRACTION_BUDGET_SECONDS}s"
    )


# ─── Requirement 11.2 - added runtime versus total generation runtime ────────


def _style_every_node(resources: Sequence[Any]) -> int:
    """Run the per-node change styling pass, returning the decorated node count."""
    decorated = 0
    for resource in resources:
        style = resolve_style(getattr(resource, "change_category", None))
        if style is None:
            continue
        label = LABEL_TEMPLATE.format(
            name=resource.name,
            short_type=str(resource.renderer_type).rsplit("/", 1)[-1],
        )
        decorate_label(label, style)
        decorated += 1
    return decorated


def test_diff_overhead_stays_below_ten_percent_of_generation_runtime(capsys, tmp_path) -> None:
    """The runtime the diff adds stays under 10 percent of the generation runtime.

    Numerator: the document build delta plus the styling and reporting phases, at
    the full 5000 entries. Denominator: one render pass, taken at a smaller
    resource count and without Graphviz layout, which under-estimates the real
    total. See the module docstring for why that makes the assertion conservative.
    """
    plan = synthetic_plan(ENTRY_COUNT, include_deletes=False)
    legacy_plan = {key: value for key, value in plan.items() if key != "resource_changes"}
    builder = TerraformTemplateBuilder()

    def build_without_diff() -> Dict[str, Any]:
        return builder._build_plan_document(legacy_plan).to_renderer_template()

    def build_with_diff() -> Dict[str, Any]:
        return builder._build_plan_document(plan, None).to_renderer_template()

    # Fairness check: both paths normalize the same resource set, so the build
    # delta is diff work rather than a different amount of building.
    legacy_template = build_without_diff()
    diff_document = builder._build_plan_document(plan, None)
    diff_template = diff_document.to_renderer_template()
    assert len(legacy_template["resources"]) == len(diff_template["resources"]) == ENTRY_COUNT
    assert all("changeCategory" in resource for resource in diff_template["resources"])

    change_model = ChangeModel.from_metadata(diff_template["metadata"]["changeModel"])
    assert sum(change_model.counts.values()) == ENTRY_COUNT

    def style_phase() -> int:
        decorated = _style_every_node(diff_document.resources)
        legend_label(change_model.present_categories(), change_model.counts)
        return decorated

    def summary_phase() -> List[str]:
        return format_change_summary(build_change_summary(change_model, diff_document))

    assert style_phase() > 0, "the synthetic plan must decorate at least one node label"
    assert summary_phase(), "the Change_Summary must produce console lines"

    build_without_diff_seconds = measure(build_without_diff)
    build_with_diff_seconds = measure(build_with_diff)
    build_delta_seconds = build_with_diff_seconds - build_without_diff_seconds
    style_seconds = measure(style_phase)
    summary_seconds = measure(summary_phase)
    added_seconds = build_delta_seconds + style_seconds + summary_seconds

    # Denominator: one full render pass, Graphviz layout faked out.
    generation_template = renderer_template(GENERATION_ENTRY_COUNT)
    assert len(generation_template["resources"]) == GENERATION_ENTRY_COUNT

    def render_pass() -> str:
        source, _, _ = run_terraform_json_generation(
            [generation_template], work_dir=str(tmp_path / "render")
        )
        return source

    generation_seconds = measure(render_pass, repeats=1)
    ratio = added_seconds / generation_seconds

    with capsys.disabled():
        print(
            f"\n[perf] {ENTRY_COUNT}-entry plan, build without diff: {build_without_diff_seconds * 1000:.1f} ms"
            f"\n[perf] {ENTRY_COUNT}-entry plan, build with diff:    {build_with_diff_seconds * 1000:.1f} ms"
            f"\n[perf]   build delta:      {build_delta_seconds * 1000:.1f} ms"
            f"\n[perf]   change styling:   {style_seconds * 1000:.1f} ms"
            f"\n[perf]   change summary:   {summary_seconds * 1000:.1f} ms"
            f"\n[perf]   added runtime:    {added_seconds * 1000:.1f} ms"
            f"\n[perf] {GENERATION_ENTRY_COUNT}-resource render pass (denominator, layout excluded): "
            f"{generation_seconds * 1000:.0f} ms"
            f"\n[perf] added runtime is {ratio * 100:.2f} % of the generation runtime"
        )

    assert added_seconds > 0, "the diff phases must be measurable"
    assert ratio < OVERHEAD_BUDGET_RATIO, (
        f"diff added {added_seconds:.3f}s on top of a {generation_seconds:.3f}s generation "
        f"({ratio * 100:.1f} %), budget is {OVERHEAD_BUDGET_RATIO * 100:.0f} %"
    )
