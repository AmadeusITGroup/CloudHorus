"""Tests for `change_types` plumbing in the configuration model and the service layer.

Covers Requirements 8.2 (existing CLI/service surface unchanged) and 8.3
(`change_types` optional, defaulting to every Change_Category via `None`).
"""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cloudhorus.models.configuration import OptimizationConfig, VisualizationConfig  # noqa: E402
from cloudhorus.services.graph_generator_service import GraphGeneratorService  # noqa: E402

TARGET = "core.graph_generator.generate_resource_graph"


def _config(**kwargs) -> VisualizationConfig:
    return VisualizationConfig(
        tenants=["tenant-1"],
        subscriptions=["sub-1"],
        resource_groups=["rg-1"],
        optimizations=[OptimizationConfig()],
        **kwargs,
    )


# ─── VisualizationConfig ─────────────────────────────────────────────────────


def test_change_types_defaults_to_none():
    """An unspecified change_types means 'every category'."""
    assert _config().change_types is None


def test_change_types_accepts_a_supplied_selection():
    config = _config(change_types=["delete", "replace"])
    assert config.change_types == ["delete", "replace"]


def test_legacy_positional_construction_is_unaffected():
    """The new field is trailing, so positional construction keeps its meaning."""
    config = VisualizationConfig(["tenant-1"], ["sub-1"], ["rg-1"])
    assert config.tenants == ["tenant-1"]
    assert config.subscriptions == ["sub-1"]
    assert config.resource_groups == ["rg-1"]
    assert config.change_types is None


def test_existing_keyword_construction_still_validates_optimizations():
    """Pre-existing __post_init__ validation is untouched by the new field."""
    config = VisualizationConfig(subscriptions=["sub-1", "sub-2"])
    assert len(config.optimizations) == 2
    assert config.rg_edge_lengths == [4, 4]
    assert config.change_types is None


# ─── GraphGeneratorService.generate_graph ────────────────────────────────────


def test_generate_graph_forwards_change_types():
    service = GraphGeneratorService(config=_config())

    with patch(TARGET, return_value="/tmp/out.png") as mock_generate:
        png_path = service.generate_graph(
            tenants=["tenant-1"],
            subscriptions=["sub-1"],
            resource_groups=["rg-1"],
            use_bicep_templates=True,
            local_template_mode="terraform-json",
            terraform_json_files=["plan.json"],
            change_types=["delete"],
        )

    assert png_path == "/tmp/out.png"
    assert mock_generate.call_args.kwargs["change_types"] == ["delete"]


def test_generate_graph_omits_change_types_when_not_supplied():
    """Legacy call sites produce the exact same argument list as before the feature."""
    service = GraphGeneratorService(config=_config())

    with patch(TARGET, return_value="/tmp/out.png") as mock_generate:
        png_path = service.generate_graph(
            tenants=["tenant-1"],
            subscriptions=["sub-1"],
            resource_groups=["rg-1"],
        )

    assert png_path == "/tmp/out.png"
    kwargs = mock_generate.call_args.kwargs
    assert "change_types" not in kwargs
    assert kwargs["terraform_json_files"] is None
    assert kwargs["use_local_template"] is False


def test_generate_graph_accepts_change_types_positionally_last():
    """The parameter is trailing, so it is the last positional argument."""
    service = GraphGeneratorService(config=_config())

    with patch(TARGET, return_value="/tmp/out.png") as mock_generate:
        service.generate_graph(
            ["tenant-1"],
            ["sub-1"],
            ["rg-1"],
            True,
            "terraform-json",
            None,
            None,
            ["plan.json"],
            None,
            None,
            ["create", "update"],
        )

    assert mock_generate.call_args.kwargs["change_types"] == ["create", "update"]


def test_generate_graph_forwards_an_empty_selection():
    """An empty list is a real selection, not 'unset', so it must be forwarded."""
    service = GraphGeneratorService(config=_config())

    with patch(TARGET, return_value=None) as mock_generate:
        service.generate_graph(
            tenants=["tenant-1"],
            subscriptions=["sub-1"],
            resource_groups=["rg-1"],
            change_types=[],
        )

    assert mock_generate.call_args.kwargs["change_types"] == []
