"""Tests for the Legend cluster rendered by `src/core/graph_generator.py`.

Task 7.4 of the terraform-plan-diff-visualization spec: a
`cluster_change_legend` subgraph carrying one HTML-label node that lists every
present Change_Category with its colour swatch, Flag_Token, and count, emitted
only in Plan_Diff_Mode and only when at least one non-`unchanged` category was
rendered.

Requirements covered: 5.7, 5.8.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from test_plan_diff_graph_plumbing import (  # noqa: E402
    VNET,
    plan_template,
    run_terraform_json_generation,
)

LEGEND_CLUSTER = "cluster_change_legend"


def legend(source: str) -> str:
    """Return the brace-balanced body of the Legend cluster, asserting it exists.

    Graphviz emits the cluster name unquoted because it is a plain identifier,
    unlike the resource-group and subnet clusters.
    """
    header = f"subgraph {LEGEND_CLUSTER} {{"
    start = source.find(header)
    assert start != -1, f"cluster {LEGEND_CLUSTER!r} not found in DOT source"

    depth = 0
    for index in range(source.index("{", start), len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"unbalanced braces for cluster {LEGEND_CLUSTER!r}")


# ─── Legend presence ─────────────────────────────────────────────────────────


def test_legend_lists_every_present_category_with_colour_flag_and_count(tmp_path):
    source, _, _ = run_terraform_json_generation(
        [plan_template({"planstorage": "create", "pe-storage": "delete"})],
        work_dir=str(tmp_path),
    )
    block = legend(source)

    assert "change_legend [label=" in block
    assert "shape=none" in block  # HTML label node, no drawn shape
    assert "<B>Change Legend</B>" in block
    # Colour swatch + flag + display label + count, one row per present category.
    # The swatch mirrors a decorated node: tinted fill inside a coloured border.
    assert "<TD BGCOLOR='#DBEBDB' COLOR='#107C10' BORDER='1' WIDTH='14' HEIGHT='14'></TD>" in block
    assert "<TD><FONT COLOR='#107C10'><B>+</B></FONT> Create</TD><TD>1</TD>" in block
    assert "<TD BGCOLOR='#F8E1E1' COLOR='#D13438' BORDER='1' WIDTH='14' HEIGHT='14'></TD>" in block
    assert "<TD><FONT COLOR='#D13438'><B>-</B></FONT> Delete</TD><TD>1</TD>" in block
    # Absent categories get no row.
    assert "Update" not in block
    assert "Replace" not in block
    assert "Unchanged" not in block


def test_legend_reports_the_unchanged_category_when_it_is_present(tmp_path):
    source, _, _ = run_terraform_json_generation(
        [plan_template({"planstorage": "create", "pe-storage": "unchanged", VNET: "unchanged"})],
        work_dir=str(tmp_path),
    )
    block = legend(source)

    assert "<FONT COLOR='#107C10'><B>+</B></FONT> Create</TD><TD>1</TD>" in block
    assert "<TD>Unchanged</TD><TD>2</TD>" in block


def test_legend_counts_are_aggregated_across_templates(tmp_path):
    templates = [
        plan_template({"planstorage0": "delete"}, suffix="-0", resource_group="test-rg-plan-0"),
        plan_template({"planstorage1": "delete"}, suffix="-1", resource_group="test-rg-plan-1"),
    ]
    source, _, _ = run_terraform_json_generation(templates, work_dir=str(tmp_path))

    assert "<FONT COLOR='#D13438'><B>-</B></FONT> Delete</TD><TD>2</TD>" in legend(source)


def test_legend_node_is_the_only_node_of_its_cluster(tmp_path):
    source, _, _ = run_terraform_json_generation(
        [plan_template({"planstorage": "update"})],
        work_dir=str(tmp_path),
    )
    block = legend(source)

    assert block.count("[label=") == 1  # exactly one node in the cluster
    assert "<FONT COLOR='#0078D4'><B>~</B></FONT> Update</TD><TD>1</TD>" in block


# ─── Legend absence ──────────────────────────────────────────────────────────


def test_no_legend_for_a_legacy_template(tmp_path):
    source, _, _ = run_terraform_json_generation(
        [plan_template()],
        pass_change_types=False,
        work_dir=str(tmp_path),
    )
    assert LEGEND_CLUSTER not in source
    assert "Change Legend" not in source


def test_no_legend_for_an_all_unchanged_plan(tmp_path):
    source, _, _ = run_terraform_json_generation(
        [plan_template({"planstorage": "unchanged", "pe-storage": "unchanged", VNET: "unchanged"})],
        work_dir=str(tmp_path),
    )
    assert LEGEND_CLUSTER not in source
    assert "Change Legend" not in source


def test_an_all_unchanged_plan_still_renders_byte_identical_dot(tmp_path):
    """The Legend must not perturb the Legacy_Mode DOT (Requirement 5.8)."""
    legacy_source, _, _ = run_terraform_json_generation(
        [plan_template()],
        pass_change_types=False,
        work_dir=str(tmp_path / "legacy"),
    )
    unchanged_source, _, _ = run_terraform_json_generation(
        [plan_template({"planstorage": "unchanged", "pe-storage": "unchanged", VNET: "unchanged"})],
        work_dir=str(tmp_path / "unchanged"),
    )
    assert unchanged_source == legacy_source


def test_no_legend_for_an_out_of_set_category(tmp_path):
    """An unknown category counts as nothing, so it renders no Legend."""
    source, _, _ = run_terraform_json_generation(
        [plan_template({"planstorage": "forget"})],
        work_dir=str(tmp_path),
    )
    assert LEGEND_CLUSTER not in source
