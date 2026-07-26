"""Configuration models for CloudHorus visualization."""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class Direction(Enum):
    """Graph layout direction."""

    TOP_TO_BOTTOM = "TB"
    BOTTOM_TO_TOP = "BT"
    LEFT_TO_RIGHT = "LR"
    RIGHT_TO_LEFT = "RL"


class RankDebugMode(Enum):
    """Rank debug visibility mode."""

    VISIBLE = "solid"
    INVISIBLE = "invis"


@dataclass
class OptimizationConfig:
    """Configuration for visualization optimizations per subscription."""

    subnet_optimization: bool = False
    pe_optimization: bool = True
    cross_pe_optimization: bool = False
    private_dns_zones_optimization: bool = True


@dataclass
class LayoutConfig:
    """Configuration for graph layout."""

    edge_direction: Direction = Direction.TOP_TO_BOTTOM
    tenant_direction: Direction = Direction.LEFT_TO_RIGHT
    max_subnet_per_line: int = 4
    resources_edge_length: int = 1
    resource_groups_edge_length: int = 4
    rank_debug: RankDebugMode = RankDebugMode.INVISIBLE

    @property
    def tenant_minlen(self) -> str:
        """Calculate tenant minimum length based on direction."""
        return "5" if self.tenant_direction == Direction.TOP_TO_BOTTOM else "0"


@dataclass
class VisualizationConfig:
    """Main configuration for CloudHorus visualization."""

    # Azure scope
    tenants: List[str] = field(default_factory=list)
    subscriptions: List[str] = field(default_factory=list)
    resource_groups: List[str] = field(default_factory=list)

    # Optimization settings per subscription
    optimizations: List[OptimizationConfig] = field(default_factory=list)

    # Layout settings
    layout: LayoutConfig = field(default_factory=LayoutConfig)

    # Resource groups edge lengths per subscription
    rg_edge_lengths: List[int] = field(default_factory=list)

    # Features — list of RG names with discovery enabled (empty list = disabled)
    discover_resource_groups: List[str] = field(default_factory=list)
    export_drawio: bool = False

    # Template mode
    use_local_template: bool = False
    local_template_mode: Optional[str] = None
    bicep_files: Optional[List[str]] = None
    parameters_files: Optional[List[str]] = None
    terraform_json_files: Optional[List[str]] = None
    terraform_root_dirs: Optional[List[str]] = None
    terraform_var_files: Optional[List[str]] = None
    scope_metadata_files: Optional[List[str]] = None

    # Terraform plan diff: Change_Categories to display (None = every category)
    change_types: Optional[List[str]] = None

    def __post_init__(self):
        """Validate and initialize default values."""
        # Ensure optimizations list matches subscriptions
        if not self.optimizations:
            self.optimizations = [OptimizationConfig() for _ in self.subscriptions]
        elif len(self.optimizations) != len(self.subscriptions):
            raise ValueError(
                f"Optimizations count ({len(self.optimizations)}) must match "
                f"subscriptions count ({len(self.subscriptions)})"
            )

        # Ensure RG edge lengths list matches subscriptions
        if not self.rg_edge_lengths:
            self.rg_edge_lengths = [4] * len(self.subscriptions)
        elif len(self.rg_edge_lengths) != len(self.subscriptions):
            raise ValueError(
                f"Resource group edge lengths count ({len(self.rg_edge_lengths)}) "
                f"must match subscriptions count ({len(self.subscriptions)})"
            )

    @property
    def subscription_count(self) -> int:
        """Get the number of subscriptions."""
        return len(self.subscriptions)

    def get_optimization_for_subscription(self, index: int) -> OptimizationConfig:
        """Get optimization config for a specific subscription by index."""
        if 0 <= index < len(self.optimizations):
            return self.optimizations[index]
        return OptimizationConfig()

    def get_rg_edge_length_for_subscription(self, index: int) -> int:
        """Get resource group edge length for a specific subscription by index."""
        if 0 <= index < len(self.rg_edge_lengths):
            return self.rg_edge_lengths[index]
        return 4
