"""Shared Hypothesis strategies for Terraform plan JSON documents.

Every strategy in this module is a **function returning a strategy**, so callers
can constrain the input space (a fixed category, a fixed set of addresses, a
bounded number of resources) while still reusing the realistic shapes below.

Feature: terraform-plan-diff-visualization
Covers Requirements 12.1, 12.2, 12.3 and 12.8.

Overview of the public strategies:

- :func:`terraform_addresses` - full Terraform addresses with module prefixes.
- :func:`address_parts` - ``(address, terraform_type, resource_name)`` triples
  that agree with each other, for callers that need the pieces.
- :func:`action_arrays` - the ``change.actions`` values a plan can carry,
  including replace permutations, duplicates, unknown tokens and non-list values.
- :func:`resource_change_entries` - single ``resource_changes[]`` entries.
- :func:`resource_change_arrays` - lists of entries, optionally with duplicate
  addresses injected.
- :func:`azurerm_resource_values` - the ``values`` block of a planned resource.
- :func:`planned_resources` - planned-resource entries as ``planned_values`` holds them.
- :func:`sensitive_masks` - ``(value_tree, mask)`` pairs structurally aligned.
- :func:`plan_documents` - whole plan documents (planned_values + configuration
  + resource_changes, including delete-only addresses).
- :func:`change_filters` - Change_Filter selections, including empty and full.
- :func:`json_values` / :func:`json_documents` - arbitrary JSON via
  ``hypothesis.strategies.recursive``, for the no-crash property.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

from hypothesis import strategies as st

# Allow importing the strategy module on its own, mirroring tests/conftest.py.
_SRC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from core.plan_diff import CHANGE_CATEGORIES, KNOWN_ACTIONS  # noqa: E402

# ─── Vocabularies ─────────────────────────────────────────────────────────────

#: Terraform types with an entry in ``_TERRAFORM_TO_RENDERER_TYPE``.
MAPPED_TERRAFORM_TYPES: Tuple[str, ...] = (
    "azurerm_virtual_network",
    "azurerm_subnet",
    "azurerm_linux_web_app",
    "azurerm_windows_web_app",
    "azurerm_kubernetes_cluster",
    "azurerm_private_endpoint",
    "azurerm_storage_account",
    "azurerm_bastion_host",
    "azurerm_application_gateway",
    "azurerm_private_dns_zone",
    "azurerm_route_table",
    "azurerm_network_security_group",
)

#: azurerm types without a renderer mapping (Unmapped_Resource in the spec).
UNMAPPED_TERRAFORM_TYPES: Tuple[str, ...] = (
    "azurerm_key_vault",
    "azurerm_container_registry",
    "azurerm_log_analytics_workspace",
    "azurerm_monitor_action_group",
)

#: Provider names accepted by the Change_Extractor.
SUPPORTED_PROVIDERS: Tuple[str, ...] = ("azurerm", "registry.terraform.io/hashicorp/azurerm")

#: Provider names the Change_Extractor must exclude (Requirement 9.4).
UNSUPPORTED_PROVIDERS: Tuple[str, ...] = (
    "registry.terraform.io/hashicorp/aws",
    "registry.terraform.io/hashicorp/google",
    "registry.terraform.io/hashicorp/random",
    "aws",
)

#: Action tokens outside ``KNOWN_ACTIONS`` (Requirement 2.8).
UNKNOWN_ACTIONS: Tuple[str, ...] = ("forget", "import", "move", "noop", "CREATE", "")

_NAME_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789-._éüñ漢"
_MODULE_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789-_"


# ─── Names and addresses ──────────────────────────────────────────────────────


def resource_names(min_size: int = 1, max_size: int = 12) -> st.SearchStrategy[str]:
    """Terraform resource names, including dots, dashes and non-ASCII characters."""
    return st.text(alphabet=_NAME_ALPHABET, min_size=min_size, max_size=max_size)


def module_names() -> st.SearchStrategy[str]:
    """Terraform module call names as they appear in a module address prefix."""
    return st.text(alphabet=_MODULE_ALPHABET, min_size=1, max_size=8)


def terraform_types(mapped: bool = True, unmapped: bool = True) -> st.SearchStrategy[str]:
    """azurerm resource types, mapped and/or unmapped to a renderer type."""
    pool: Tuple[str, ...] = ()
    if mapped:
        pool += MAPPED_TERRAFORM_TYPES
    if unmapped:
        pool += UNMAPPED_TERRAFORM_TYPES
    if not pool:
        raise ValueError("terraform_types() needs at least one of mapped/unmapped enabled")
    return st.sampled_from(pool)


@st.composite
def address_parts(
    draw: st.DrawFn,
    types: Optional[st.SearchStrategy[str]] = None,
    max_module_depth: int = 3,
) -> Tuple[str, str, str]:
    """Draw a consistent ``(address, terraform_type, resource_name)`` triple.

    The address carries 0 to ``max_module_depth`` ``module.<name>.`` prefixes, so
    generated plans exercise the full-address keying of Requirement 2.9.
    """
    depth = draw(st.integers(min_value=0, max_value=max_module_depth))
    prefix = "".join(f"module.{draw(module_names())}." for _ in range(depth))
    terraform_type = draw(types if types is not None else terraform_types())
    resource_name = draw(resource_names())
    return f"{prefix}{terraform_type}.{resource_name}", terraform_type, resource_name


def terraform_addresses(
    types: Optional[st.SearchStrategy[str]] = None,
    max_module_depth: int = 3,
) -> st.SearchStrategy[str]:
    """Full Terraform addresses, module prefixes included."""
    return address_parts(types=types, max_module_depth=max_module_depth).map(lambda parts: parts[0])


# ─── Action arrays ────────────────────────────────────────────────────────────


def known_action_arrays() -> st.SearchStrategy[List[str]]:
    """Single-action arrays drawn from the known Terraform action vocabulary."""
    return st.sampled_from([["create"], ["update"], ["delete"], ["no-op"], ["read"]])


def replace_action_arrays() -> st.SearchStrategy[List[str]]:
    """Arrays containing both ``create`` and ``delete``, in either order."""
    return st.sampled_from(
        [
            ["create", "delete"],
            ["delete", "create"],
            ["delete", "create", "delete"],
            ["create", "create", "delete"],
        ]
    )


def duplicate_action_arrays() -> st.SearchStrategy[List[str]]:
    """Arrays repeating the same known action."""
    return st.sampled_from(sorted(KNOWN_ACTIONS)).map(lambda action: [action, action])


def unknown_action_arrays() -> st.SearchStrategy[List[str]]:
    """Arrays holding at least one token outside ``KNOWN_ACTIONS``."""
    return st.lists(
        st.sampled_from(tuple(UNKNOWN_ACTIONS) + tuple(sorted(KNOWN_ACTIONS))),
        min_size=1,
        max_size=3,
    ).filter(lambda actions: any(action not in KNOWN_ACTIONS for action in actions))


def non_list_action_values() -> st.SearchStrategy[Any]:
    """``actions`` values that are not arrays at all."""
    return st.one_of(
        st.none(),
        st.booleans(),
        st.integers(),
        st.text(max_size=8),
        st.dictionaries(st.text(max_size=4), st.text(max_size=4), max_size=2),
    )


def action_arrays(include_unknown: bool = True, include_invalid: bool = True) -> st.SearchStrategy[Any]:
    """Every ``change.actions`` shape a plan can carry.

    Covers the decision table of Requirements 2.3 to 2.8: single known actions,
    replace permutations, duplicates, the empty array, unknown tokens
    (``include_unknown``) and non-list values (``include_invalid``).
    """
    pool: List[st.SearchStrategy[Any]] = [
        known_action_arrays(),
        replace_action_arrays(),
        duplicate_action_arrays(),
        st.just([]),
    ]
    if include_unknown:
        pool.append(unknown_action_arrays())
    if include_invalid:
        pool.append(non_list_action_values())
    return st.one_of(*pool)


def actions_for_category(category: str) -> st.SearchStrategy[List[str]]:
    """Action arrays that must classify as ``category``."""
    if category == "create":
        return st.just(["create"])
    if category == "update":
        return st.just(["update"])
    if category == "delete":
        return st.just(["delete"])
    if category == "replace":
        return st.sampled_from([["create", "delete"], ["delete", "create"]])
    if category == "unchanged":
        return st.sampled_from([["no-op"], ["read"]])
    raise ValueError(f"Unknown change category: {category}")


# ─── Resource values ──────────────────────────────────────────────────────────


def _scalars() -> st.SearchStrategy[Any]:
    return st.one_of(
        st.none(),
        st.booleans(),
        st.integers(min_value=-1000, max_value=1000),
        st.text(max_size=10),
    )


def nested_value_trees(max_leaves: int = 8) -> st.SearchStrategy[Dict[str, Any]]:
    """Nested dict/list/scalar trees shaped like a Terraform ``values`` block."""
    return st.recursive(
        _scalars(),
        lambda children: st.one_of(
            st.lists(children, max_size=3),
            st.dictionaries(st.text(alphabet=_MODULE_ALPHABET, min_size=1, max_size=8), children, max_size=3),
        ),
        max_leaves=max_leaves,
    ).flatmap(
        lambda child: st.dictionaries(
            st.text(alphabet=_MODULE_ALPHABET, min_size=1, max_size=8),
            st.just(child),
            min_size=1,
            max_size=3,
        )
    )


@st.composite
def azurerm_resource_values(
    draw: st.DrawFn,
    terraform_type: Optional[str] = None,
    resource_name: Optional[str] = None,
    subnet_ids: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """The ``values`` block of a planned resource, with type-realistic keys.

    ``subnet_ids`` lets a caller wire generated resources to generated subnets so
    the container-retention and edge-pruning behaviour has something to chew on.
    """
    terraform_type = terraform_type or draw(terraform_types())
    name = resource_name if resource_name is not None else draw(resource_names())
    subnet_id = draw(st.sampled_from(list(subnet_ids))) if subnet_ids else "/subnets/default"

    values: Dict[str, Any] = {
        "name": name,
        "location": draw(st.sampled_from(["westeurope", "francecentral", "eastus"])),
        "resource_group_name": draw(st.sampled_from(["rg-network", "rg-app", "rg-data"])),
    }

    if terraform_type == "azurerm_virtual_network":
        values["address_space"] = draw(
            st.lists(st.sampled_from(["10.0.0.0/16", "10.1.0.0/16"]), min_size=1, max_size=2)
        )
    elif terraform_type == "azurerm_subnet":
        values["virtual_network_name"] = draw(st.sampled_from(["vnet-core", "vnet-app"]))
        values["address_prefixes"] = draw(
            st.lists(st.sampled_from(["10.0.1.0/24", "10.0.2.0/24"]), min_size=1, max_size=2)
        )
    elif terraform_type in {"azurerm_linux_web_app", "azurerm_windows_web_app"}:
        values["virtual_network_subnet_id"] = subnet_id
        values["service_plan_id"] = "/serverfarms/plan-1"
    elif terraform_type == "azurerm_kubernetes_cluster":
        values["default_node_pool"] = [{"name": "nodepool1", "vnet_subnet_id": subnet_id}]
    elif terraform_type == "azurerm_private_endpoint":
        values["subnet_id"] = subnet_id
        values["private_service_connection"] = [{"private_connection_resource_id": "/storageAccounts/sa1"}]
    elif terraform_type == "azurerm_bastion_host":
        values["ip_configuration"] = [{"name": "ipconfig", "subnet_id": subnet_id}]
    elif terraform_type == "azurerm_application_gateway":
        values["gateway_ip_configuration"] = [{"name": "gateway", "subnet_id": subnet_id}]
    elif terraform_type == "azurerm_storage_account":
        values["account_tier"] = draw(st.sampled_from(["Standard", "Premium"]))

    if draw(st.booleans()):
        values["tags"] = {"env": draw(st.sampled_from(["dev", "prod"]))}
    if draw(st.booleans()):
        values["nested"] = draw(nested_value_trees(max_leaves=4))
    return values


@st.composite
def planned_resources(
    draw: st.DrawFn,
    types: Optional[st.SearchStrategy[str]] = None,
    providers: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """A single entry of ``planned_values.root_module.resources``."""
    address, terraform_type, resource_name = draw(address_parts(types=types))
    provider = draw(st.sampled_from(list(providers or SUPPORTED_PROVIDERS)))
    return {
        "address": address,
        "mode": "managed",
        "type": terraform_type,
        "name": resource_name,
        "provider_name": provider,
        "values": draw(azurerm_resource_values(terraform_type=terraform_type, resource_name=resource_name)),
    }


# ─── Sensitivity masks ────────────────────────────────────────────────────────


def _draw_mask(draw: st.DrawFn, node: Any) -> Any:
    """Build a mask structurally aligned with ``node``, marking a leaf subset."""
    if isinstance(node, dict):
        if draw(st.booleans()) and node:
            # Whole-subtree sensitivity, as Terraform emits for opaque objects.
            return True
        mask: Dict[str, Any] = {}
        for key, child in node.items():
            if draw(st.booleans()):
                mask[key] = _draw_mask(draw, child)
        return mask
    if isinstance(node, list):
        return [_draw_mask(draw, item) for item in node]
    return draw(st.booleans())


@st.composite
def sensitive_masks(
    draw: st.DrawFn,
    values: Optional[st.SearchStrategy[Dict[str, Any]]] = None,
) -> Tuple[Dict[str, Any], Any]:
    """Draw a ``(value_tree, mask)`` pair whose mask mirrors the tree's shape.

    ``True`` marks a sensitive leaf or subtree; absent keys and ``False`` mark
    values that must survive redaction untouched (Requirement 10.1). The same
    shape serves ``before_sensitive``, ``after_sensitive`` and ``sensitive_values``.
    """
    tree = draw(values if values is not None else azurerm_resource_values())
    return tree, _draw_mask(draw, tree)


# ─── Change entries and plan documents ────────────────────────────────────────


@st.composite
def resource_change_entries(
    draw: st.DrawFn,
    actions: Optional[st.SearchStrategy[Any]] = None,
    types: Optional[st.SearchStrategy[str]] = None,
    modes: Optional[Sequence[str]] = None,
    providers: Optional[Sequence[str]] = None,
    allow_missing_address: bool = True,
    allow_missing_change: bool = True,
) -> Dict[str, Any]:
    """A single ``resource_changes[]`` entry.

    Exercises the exclusion and warning paths of Requirements 2.1, 9.4, 9.6 and
    9.7: ``mode`` in {managed, data}, an optionally missing ``address``, an
    optionally missing ``change`` object, and provider names inside and outside
    the supported azurerm set.
    """
    address, terraform_type, resource_name = draw(address_parts(types=types))
    entry: Dict[str, Any] = {
        "mode": draw(st.sampled_from(list(modes or ("managed", "managed", "data")))),
        "type": terraform_type,
        "name": resource_name,
        "provider_name": draw(st.sampled_from(list(providers or (SUPPORTED_PROVIDERS + UNSUPPORTED_PROVIDERS)))),
    }
    if not allow_missing_address or draw(st.booleans()):
        entry["address"] = address
    module_address = address[: -len(f"{terraform_type}.{resource_name}")].rstrip(".")
    if module_address:
        entry["module_address"] = module_address

    if allow_missing_change and draw(st.booleans()):
        return entry

    before, before_mask = draw(sensitive_masks(values=azurerm_resource_values(terraform_type=terraform_type)))
    after, after_mask = draw(sensitive_masks(values=azurerm_resource_values(terraform_type=terraform_type)))
    entry["change"] = {
        "actions": draw(actions if actions is not None else action_arrays()),
        "before": before,
        "after": after,
        "before_sensitive": before_mask,
        "after_sensitive": after_mask,
    }
    return entry


@st.composite
def resource_change_arrays(
    draw: st.DrawFn,
    entries: Optional[st.SearchStrategy[Dict[str, Any]]] = None,
    min_size: int = 0,
    max_size: int = 6,
    inject_duplicates: bool = True,
) -> List[Dict[str, Any]]:
    """A ``resource_changes`` array, optionally with a duplicated address.

    The duplicate carries a different category so the first-wins rule of
    Requirement 2.10 is observable.
    """
    entry_strategy = entries if entries is not None else resource_change_entries()
    array = draw(st.lists(entry_strategy, min_size=min_size, max_size=max_size))
    addressed = [entry for entry in array if isinstance(entry.get("address"), str)]
    if inject_duplicates and addressed and draw(st.booleans()):
        original = draw(st.sampled_from(addressed))
        duplicate = dict(original)
        duplicate["change"] = {"actions": draw(actions_for_category(draw(st.sampled_from(CHANGE_CATEGORIES))))}
        array.append(duplicate)
    return array


@st.composite
def plan_documents(
    draw: st.DrawFn,
    min_resources: int = 1,
    max_resources: int = 5,
    categories: Optional[Sequence[str]] = None,
    with_configuration: bool = True,
    with_resource_changes: bool = True,
) -> Dict[str, Any]:
    """A whole plan document: ``planned_values`` + ``configuration`` + ``resource_changes``.

    Resources classified ``delete`` are kept out of ``planned_values`` (post-apply
    state) and appear only through ``change.before``, which is what makes the
    delete reconstruction of Requirement 3.1 observable. ``configuration``
    carries reference expressions between generated addresses so dependency edges
    can be checked.
    """
    pool = list(categories or CHANGE_CATEGORIES)
    resources = draw(
        st.lists(
            planned_resources(providers=SUPPORTED_PROVIDERS),
            min_size=min_resources,
            max_size=max_resources,
            unique_by=lambda resource: resource["address"],
        )
    )

    assigned = [(resource, draw(st.sampled_from(pool))) for resource in resources]

    planned_entries: List[Dict[str, Any]] = []
    change_entries: List[Dict[str, Any]] = []
    for resource, category in assigned:
        if category != "delete":
            planned_entries.append(resource)
        if not with_resource_changes:
            continue
        actions = draw(actions_for_category(category))
        change: Dict[str, Any] = {"actions": actions}
        if category in {"delete", "replace", "update"}:
            change["before"] = resource["values"]
        if category in {"create", "replace", "update"}:
            change["after"] = resource["values"]
        change_entries.append(
            {
                "address": resource["address"],
                "mode": "managed",
                "type": resource["type"],
                "name": resource["name"],
                "provider_name": resource["provider_name"],
                "change": change,
            }
        )

    document: Dict[str, Any] = {
        "format_version": draw(st.sampled_from(["1.0", "1.1", "1.2"])),
        "terraform_version": "1.9.5",
        "planned_values": {"root_module": {"resources": planned_entries}},
    }

    if with_configuration:
        addresses = [resource["address"] for resource, _ in assigned]
        config_resources = []
        for index, (resource, _category) in enumerate(assigned):
            targets = [address for position, address in enumerate(addresses) if position != index]
            expressions: Dict[str, Any] = {}
            if targets and draw(st.booleans()):
                expressions["subnet_id"] = {"references": [draw(st.sampled_from(targets))]}
            config_resources.append(
                {
                    "address": resource["address"],
                    "mode": "managed",
                    "type": resource["type"],
                    "name": resource["name"],
                    "provider_config_key": "azurerm",
                    "expressions": expressions,
                }
            )
        document["configuration"] = {"root_module": {"resources": config_resources}}

    if with_resource_changes:
        document["resource_changes"] = change_entries
    return document


# ─── Change filters ───────────────────────────────────────────────────────────


def change_filters(
    include_empty: bool = True,
    include_full: bool = True,
    shuffled: bool = True,
) -> st.SearchStrategy[List[str]]:
    """Change_Filter selections as sequences of Change_Category values.

    Every subset of ``CHANGE_CATEGORIES`` is reachable, including the empty and
    the full selection. With ``shuffled`` enabled the same subset can come back
    in any order, which is what Property 15 (order independence) needs.
    """
    min_size = 0 if include_empty else 1
    max_size = len(CHANGE_CATEGORIES) if include_full else len(CHANGE_CATEGORIES) - 1
    subsets = st.lists(
        st.sampled_from(CHANGE_CATEGORIES),
        min_size=min_size,
        max_size=max_size,
        unique=True,
    )
    if not shuffled:
        return subsets.map(lambda selection: [c for c in CHANGE_CATEGORIES if c in selection])
    return subsets.flatmap(lambda selection: st.permutations(selection).map(list))


# ─── Arbitrary JSON ───────────────────────────────────────────────────────────


def json_values(max_leaves: int = 12) -> st.SearchStrategy[Any]:
    """Arbitrary JSON values, including documents that are not objects at all."""
    return st.recursive(
        st.one_of(
            st.none(),
            st.booleans(),
            st.integers(min_value=-(10**6), max_value=10**6),
            st.floats(allow_nan=False, allow_infinity=False, width=32),
            st.text(max_size=12),
        ),
        lambda children: st.one_of(
            st.lists(children, max_size=4),
            st.dictionaries(st.text(max_size=8), children, max_size=4),
        ),
        max_leaves=max_leaves,
    )


def json_documents(max_leaves: int = 12) -> st.SearchStrategy[Any]:
    """Arbitrary JSON documents for the no-crash property (Requirement 12.8).

    Deliberately includes plan-shaped keys so the generator reaches the real code
    paths as well as the fully arbitrary ones.
    """
    plan_shaped = st.fixed_dictionaries(
        {
            "format_version": st.sampled_from(["1.0", "1.1", "0.9", "2.0", 1, None]),
            "planned_values": json_values(max_leaves=6),
            "resource_changes": st.one_of(json_values(max_leaves=6), resource_change_arrays()),
        }
    )
    return st.one_of(json_values(max_leaves=max_leaves), plan_shaped, plan_documents())
