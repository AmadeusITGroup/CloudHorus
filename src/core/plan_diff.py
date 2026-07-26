"""Terraform plan diff change model for CloudHorus.

Pure, dependency-light module: no Graphviz, no Azure, no file I/O. It owns the
change model that carries the planned action of every managed Terraform resource
through the existing local-template renderer contract.
"""

import copy
import re
from collections import abc
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Set, Tuple

from cloudhorus.models.local_template_document import LocalTemplateDocument, LocalTemplateResource
from utils.logger import SingletonLogger

logger = SingletonLogger().get_logger()

#: Closed set of change categories, in canonical display order.
CHANGE_CATEGORIES: Tuple[str, ...] = ("create", "update", "replace", "delete", "unchanged")

#: The category assigned to every resource that the plan leaves alone.
UNCHANGED_CATEGORY: str = "unchanged"

#: Action values understood by the Change_Extractor decision table.
KNOWN_ACTIONS: frozenset = frozenset({"create", "update", "delete", "no-op", "read"})

#: Provider names accepted for change extraction, mirroring
#: ``terraform_builder._SUPPORTED_PROVIDER_NAMES``.
SUPPORTED_PROVIDER_NAMES: frozenset = frozenset({"azurerm", "registry.terraform.io/hashicorp/azurerm"})


@dataclass(frozen=True)
class ChangeRecord:
    """One normalized planned change for a managed Terraform resource."""

    address: str
    category: str
    actions: Tuple[str, ...] = ()
    terraform_type: str = ""
    provider_name: str = ""

    def to_payload(self) -> Dict[str, Any]:
        """Return the JSON-serializable form used inside the Renderer_Template."""
        return {
            "address": self.address,
            "category": self.category,
            "actions": list(self.actions),
            "terraformType": self.terraform_type,
            "providerName": self.provider_name,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ChangeRecord":
        """Rebuild a record from its serialized form."""
        raw_actions = payload.get("actions") or ()
        if isinstance(raw_actions, (str, bytes)):
            raw_actions = (raw_actions,)
        return cls(
            address=str(payload.get("address", "")),
            category=str(payload.get("category", UNCHANGED_CATEGORY)),
            actions=tuple(str(action) for action in raw_actions),
            terraform_type=str(payload.get("terraformType", "") or ""),
            provider_name=str(payload.get("providerName", "") or ""),
        )


def normalize_counts(counts: Optional[Mapping[str, Any]]) -> Dict[str, int]:
    """Return a count mapping holding exactly one entry per Change_Category.

    Categories absent from ``counts`` carry ``0``; values outside the closed
    category set are dropped with a warning.
    """
    source: Mapping[str, Any] = counts or {}
    for category in source:
        if category not in CHANGE_CATEGORIES:
            logger.warning("Ignoring unknown change category '%s' in change counts", category)
    normalized: Dict[str, int] = {}
    for category in CHANGE_CATEGORIES:
        value = source.get(category, 0)
        try:
            normalized[category] = int(value)
        except (TypeError, ValueError):
            logger.warning("Ignoring non-numeric count '%s' for change category '%s'", value, category)
            normalized[category] = 0
    return normalized


def counts_from_records(records: Mapping[str, ChangeRecord]) -> Dict[str, int]:
    """Derive per-category counts from records so the counts always conserve."""
    counts = {category: 0 for category in CHANGE_CATEGORIES}
    for record in records.values():
        if record.category in counts:
            counts[record.category] += 1
        else:
            logger.warning(
                "Change record %s carries unknown category '%s'; counting it as '%s'",
                record.address,
                record.category,
                UNCHANGED_CATEGORY,
            )
            counts[UNCHANGED_CATEGORY] += 1
    return counts


@dataclass
class ChangeModel:
    """All Change_Records of one plan, keyed by Terraform address, plus counts."""

    records: Dict[str, ChangeRecord] = field(default_factory=dict)
    counts: Dict[str, int] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Enforce the count invariant: one entry per category, absent ones at zero."""
        self.counts = normalize_counts(self.counts)

    @classmethod
    def from_records(
        cls,
        records: Mapping[str, ChangeRecord],
        warnings: Optional[Sequence[str]] = None,
    ) -> "ChangeModel":
        """Build a model whose counts are derived from the retained records."""
        retained = dict(records)
        return cls(
            records=retained,
            counts=counts_from_records(retained),
            warnings=list(warnings or []),
        )

    def category_for(self, address: str) -> Optional[str]:
        """Return the Change_Category recorded for an address, or None when absent."""
        record = self.records.get(address)
        return record.category if record is not None else None

    def has_changes(self) -> bool:
        """Return True when at least one record carries a category other than unchanged."""
        return any(record.category != UNCHANGED_CATEGORY for record in self.records.values())

    def present_categories(self) -> List[str]:
        """Return the categories with a non-zero count, in canonical order."""
        return [category for category in CHANGE_CATEGORIES if self.counts.get(category, 0) > 0]

    def to_metadata(self) -> Dict[str, Any]:
        """Return the round-trippable payload carried under the template metadata."""
        payload: Dict[str, Any] = {
            "counts": dict(self.counts),
            "records": [self.records[address].to_payload() for address in self.records],
        }
        if self.warnings:
            payload["warnings"] = list(self.warnings)
        return payload

    @classmethod
    def from_metadata(cls, payload: Optional[Mapping[str, Any]]) -> "ChangeModel":
        """Rebuild a model from the payload produced by :meth:`to_metadata`."""
        source: Mapping[str, Any] = payload or {}
        records: Dict[str, ChangeRecord] = {}
        raw_records = source.get("records") or []
        if isinstance(raw_records, dict):
            raw_records = list(raw_records.values())
        if not isinstance(raw_records, list):
            logger.warning("Ignoring change model records of unsupported type %s", type(raw_records).__name__)
            raw_records = []
        for entry in raw_records:
            if not isinstance(entry, dict):
                logger.warning("Ignoring malformed change record entry of type %s", type(entry).__name__)
                continue
            record = ChangeRecord.from_payload(entry)
            if not record.address:
                logger.warning("Ignoring change record entry without an address")
                continue
            records.setdefault(record.address, record)

        raw_counts = source.get("counts")
        counts = normalize_counts(raw_counts) if isinstance(raw_counts, dict) else counts_from_records(records)

        raw_warnings = source.get("warnings") or []
        warnings = [str(warning) for warning in raw_warnings] if isinstance(raw_warnings, list) else []

        return cls(records=records, counts=counts, warnings=warnings)


def parse_change_types(raw: Optional[Sequence[str]]) -> List[str]:
    """Validate a ``--changeTypes`` value and return the selected categories.

    ``None`` selects every Change_Category (Requirement 8.3), so the CLI default
    behaves exactly like a Legacy_Mode run. Any other input is validated against
    :data:`CHANGE_CATEGORIES`; the first invalid value raises a ``ValueError``
    whose message names the accepted values (Requirement 6.10)::

        Invalid --changeTypes value 'foo'. Accepted values: create update replace delete unchanged

    The returned list holds each selected category once, in canonical order, so
    two selections differing only in order or repetition are indistinguishable.
    """
    if raw is None:
        return list(CHANGE_CATEGORIES)

    if isinstance(raw, (str, bytes)):
        values: Sequence[Any] = [raw]
    elif isinstance(raw, abc.Sequence) or isinstance(raw, (set, frozenset)):
        values = list(raw)
    else:
        raise ValueError(_invalid_change_type_message(raw))

    selected = set()
    for value in values:
        if not isinstance(value, str) or value not in CHANGE_CATEGORIES:
            raise ValueError(_invalid_change_type_message(value))
        selected.add(value)

    return [category for category in CHANGE_CATEGORIES if category in selected]


def _invalid_change_type_message(value: Any) -> str:
    """Return the Requirement 6.10 error message for an invalid selection value."""
    if isinstance(value, bytes):
        rendered = value.decode("utf-8", "replace")
    else:
        rendered = str(value)
    return f"Invalid --changeTypes value '{rendered}'. Accepted values: {' '.join(CHANGE_CATEGORIES)}"


class ChangeExtractor:
    """Turns the ``resource_changes`` array of a plan into a :class:`ChangeModel`."""

    def classify(self, actions: Any, address: str = "") -> Tuple[str, Tuple[str, ...]]:
        """Resolve a Change_Category from a plan ``change.actions`` value.

        Returns the category together with the raw action tuple, so the caller can
        keep the plan's original array on the Change_Record (Requirement 2.8).

        The decision table is applied in this order:

        ==========================================  ==========
        Condition on ``actions``                    Category
        ==========================================  ==========
        contains both ``create`` and ``delete``     ``replace``
        ``["create"]``                              ``create``
        ``["update"]``                              ``update``
        ``["delete"]``                              ``delete``
        ``["no-op"]`` or ``["read"]``               ``unchanged``
        holds a value outside :data:`KNOWN_ACTIONS` ``unchanged`` + warning
        missing, not a list, or unsupported combo   ``unchanged`` + warning
        ==========================================  ==========

        ``actions`` of ``None`` covers both a missing ``change`` object and a
        missing ``actions`` key (Requirements 9.6, 9.8).
        """
        context = f" for {address}" if address else ""

        if actions is None:
            logger.warning("Plan change entry%s carries no actions array; treating it as unchanged", context)
            return UNCHANGED_CATEGORY, ()

        if isinstance(actions, (str, bytes)) or not isinstance(actions, (list, tuple)):
            logger.warning(
                "Plan change entry%s carries an actions value of unsupported type %s; treating it as unchanged",
                context,
                type(actions).__name__,
            )
            return UNCHANGED_CATEGORY, ()

        raw_actions = tuple(str(action) for action in actions)
        distinct = set(raw_actions)
        unknown = [action for action in raw_actions if action not in KNOWN_ACTIONS]

        if unknown:
            logger.warning(
                "Plan change entry%s carries unrecognized action value(s) %s",
                context,
                ", ".join(f"'{action}'" for action in sorted(set(unknown))),
            )

        if "create" in distinct and "delete" in distinct:
            return "replace", raw_actions
        if unknown:
            return UNCHANGED_CATEGORY, raw_actions
        if distinct == {"create"}:
            return "create", raw_actions
        if distinct == {"update"}:
            return "update", raw_actions
        if distinct == {"delete"}:
            return "delete", raw_actions
        if distinct in ({"no-op"}, {"read"}):
            return UNCHANGED_CATEGORY, raw_actions

        logger.warning(
            "Plan change entry%s carries an unsupported action combination %s; treating it as unchanged",
            context,
            list(raw_actions),
        )
        return UNCHANGED_CATEGORY, raw_actions
    def extract(self, resource_changes: Any) -> ChangeModel:
        """Turn a plan ``resource_changes`` array into a :class:`ChangeModel`.

        One single pass over the array, holding at most one Change_Record per
        managed entry (Requirement 11.4). Entries are excluded, each with a
        warning, when they are not objects, when ``mode`` differs from
        ``managed`` (Requirement 2.1), when ``address`` is missing
        (Requirement 9.7), or when ``provider_name`` falls outside
        :data:`SUPPORTED_PROVIDER_NAMES` (Requirement 9.4). Records are keyed by
        the full Terraform address, module prefixes included (Requirement 2.9),
        and the first entry wins on a duplicate address (Requirement 2.10).

        A ``resource_changes`` value that is not a list yields an empty model
        plus a type-mismatch warning (Requirement 9.8). Counts are always
        derived from the retained records, so they conserve (Requirement 2.11).
        """
        warnings: List[str] = []

        if not isinstance(resource_changes, list):
            self._warn(
                warnings,
                "Plan 'resource_changes' carries an unsupported type %s; producing an empty change model",
                type(resource_changes).__name__,
            )
            return ChangeModel.from_records({}, warnings)

        records: Dict[str, ChangeRecord] = {}

        for index, entry in enumerate(resource_changes):
            if not isinstance(entry, dict):
                self._warn(
                    warnings,
                    "Skipping plan change entry at index %s: expected an object, found %s",
                    index,
                    type(entry).__name__,
                )
                continue

            mode = entry.get("mode")
            if mode != "managed":
                self._warn(
                    warnings,
                    "Skipping plan change entry at index %s: mode '%s' is not 'managed'",
                    index,
                    mode,
                )
                continue

            address = entry.get("address")
            if not isinstance(address, str) or not address:
                self._warn(warnings, "Skipping plan change entry at index %s: no address declared", index)
                continue

            provider_name = entry.get("provider_name")
            if provider_name not in SUPPORTED_PROVIDER_NAMES:
                self._warn(
                    warnings,
                    "Skipping plan change entry %s: unsupported provider name '%s'",
                    address,
                    provider_name,
                )
                continue

            if address in records:
                self._warn(
                    warnings,
                    "Duplicate plan change entry for address %s; keeping the first entry",
                    address,
                )
                continue

            change = entry.get("change")
            if change is not None and not isinstance(change, dict):
                self._warn(
                    warnings,
                    "Plan change entry %s carries a change object of unsupported type %s",
                    address,
                    type(change).__name__,
                )
            actions = change.get("actions") if isinstance(change, dict) else None
            category, raw_actions = self.classify(actions, address=address)

            records[address] = ChangeRecord(
                address=address,
                category=category,
                actions=raw_actions,
                terraform_type=str(entry.get("type", "") or ""),
                provider_name=str(provider_name),
            )

        return ChangeModel.from_records(records, warnings)

    @staticmethod
    def _warn(warnings: List[str], message: str, *args: Any) -> None:
        """Log a warning and retain it on the Change_Model for later reporting."""
        logger.warning(message, *args)
        warnings.append(message % args if args else message)


#: Renderer type of a virtual network, the outer container of the Diagram.
VIRTUAL_NETWORK_TYPE: str = "Microsoft.Network/virtualNetworks"

#: Renderer type of a subnet, rendered as a cluster inside its virtual network.
SUBNET_TYPE: str = "Microsoft.Network/virtualNetworks/subnets"

#: Renderer types that act as containers and therefore survive a filter pass
#: whenever a displayed resource resides inside them (Requirement 6.11).
CONTAINER_RENDERER_TYPES: frozenset = frozenset({VIRTUAL_NETWORK_TYPE, SUBNET_TYPE})

#: Property paths that carry a subnet id, as produced by
#: ``TerraformTemplateBuilder._build_resource_properties`` and
#: ``_populate_reference_backed_properties``. ``"*"`` walks a list level.
SUBNET_ID_PROPERTY_PATHS: Tuple[Tuple[str, ...], ...] = (
    ("virtualNetworkSubnetId",),
    ("subnet", "id"),
    ("agentPoolProfiles", "*", "vnetSubnetID"),
    ("ipConfigurations", "*", "properties", "subnet", "id"),
    ("gatewayIPConfigurations", "*", "properties", "subnet", "id"),
)

_RESOURCE_ID_EXPRESSION = re.compile(r"^\s*\[\s*resourceId\s*\((?P<args>.*)\)\s*\]\s*$", re.IGNORECASE | re.DOTALL)
_QUOTED_ARGUMENT = re.compile(r"'((?:[^']|'')*)'")
_AZURE_SUBNET_ID = re.compile(r"/virtualNetworks/(?P<vnet>[^/]+)/subnets/(?P<subnet>[^/?#]+)", re.IGNORECASE)
_AZURE_VIRTUAL_NETWORK_ID = re.compile(r"/virtualNetworks/(?P<vnet>[^/?#]+)\s*$", re.IGNORECASE)

#: Identity of one container resource: its renderer type and name, folded to
#: lower case because Azure resource names compare case-insensitively.
ContainerKey = Tuple[str, str]


@dataclass(frozen=True)
class PropertySlot:
    """One subnet-id-bearing property, with the dict that owns it.

    Keeping the owning dict and key alongside the value lets the edge-pruning
    pass drop the entry without walking the property tree a second time.
    """

    owner: Dict[str, Any]
    key: str
    value: Any


def container_key(renderer_type: Optional[str], name: Optional[str]) -> ContainerKey:
    """Return the case-insensitive identity of a container resource."""
    return (str(renderer_type or "").strip().lower(), str(name or "").strip().strip("/").lower())


def virtual_network_key(vnet_name: str) -> ContainerKey:
    """Return the container key of a virtual network by name."""
    return container_key(VIRTUAL_NETWORK_TYPE, vnet_name)


def subnet_key(vnet_name: str, subnet_name: str) -> ContainerKey:
    """Return the container key of a subnet, named ``"<vnet>/<subnet>"``."""
    return container_key(SUBNET_TYPE, f"{vnet_name}/{subnet_name}")


def parse_resource_id_expression(value: Any) -> Optional[Tuple[str, str]]:
    """Split a ``[resourceId('type', 'a', 'b')]`` expression into type and name.

    Mirrors ``TerraformTemplateBuilder._resource_id_expression``, including its
    ``''`` escaping of single quotes. Returns ``None`` for anything that is not
    such an expression.
    """
    if not isinstance(value, str):
        return None
    match = _RESOURCE_ID_EXPRESSION.match(value)
    if not match:
        return None
    arguments = [group.replace("''", "'") for group in _QUOTED_ARGUMENT.findall(match.group("args"))]
    if not arguments:
        return None
    renderer_type = arguments[0]
    name = "/".join(segment for segment in arguments[1:] if segment)
    return renderer_type, name


def container_keys_in_value(value: Any) -> Set[ContainerKey]:
    """Return every container referenced by one string value.

    Three shapes are recognized, covering what a plan can put in a subnet-id
    property or a ``dependsOn`` entry:

    * a ``[resourceId(...)]`` expression produced by the Terraform builder,
    * a full Azure resource id ending in ``/virtualNetworks/<vnet>[/subnets/<subnet>]``,
    * the bare ``"<vnet>/<subnet>"`` name relation used for subnet resources.

    A subnet reference always yields its parent virtual network as well, so a
    retained subnet never renders without its container.
    """
    if not isinstance(value, str):
        return set()

    text = value.strip()
    if not text:
        return set()

    parsed = parse_resource_id_expression(text)
    if parsed is not None:
        renderer_type, name = parsed
        normalized_type = renderer_type.strip().lower()
        if normalized_type == SUBNET_TYPE.lower():
            vnet_name, _, subnet_name = name.partition("/")
            if vnet_name and subnet_name:
                return {subnet_key(vnet_name, subnet_name), virtual_network_key(vnet_name)}
            return set()
        if normalized_type == VIRTUAL_NETWORK_TYPE.lower():
            return {virtual_network_key(name)} if name else set()
        return set()

    subnet_match = _AZURE_SUBNET_ID.search(text)
    if subnet_match:
        vnet_name = subnet_match.group("vnet")
        subnet_name = subnet_match.group("subnet")
        return {subnet_key(vnet_name, subnet_name), virtual_network_key(vnet_name)}

    vnet_match = _AZURE_VIRTUAL_NETWORK_ID.search(text)
    if vnet_match:
        return {virtual_network_key(vnet_match.group("vnet"))}

    if text.startswith("[") or text.startswith("/"):
        return set()

    vnet_name, separator, subnet_name = text.partition("/")
    if separator and vnet_name and subnet_name and "/" not in subnet_name:
        return {subnet_key(vnet_name, subnet_name), virtual_network_key(vnet_name)}

    return set()


def iter_subnet_id_slots(properties: Any) -> Iterator[PropertySlot]:
    """Yield every subnet-id-bearing property slot of a resource."""
    for path in SUBNET_ID_PROPERTY_PATHS:
        yield from _iter_slots(properties, path)


def _iter_slots(node: Any, path: Sequence[str]) -> Iterator[PropertySlot]:
    """Walk ``path`` through a property tree, yielding the leaf slots it hits."""
    if not path:
        return

    key = path[0]
    rest = path[1:]

    if key == "*":
        if isinstance(node, list):
            for item in node:
                yield from _iter_slots(item, rest)
        elif isinstance(node, dict):
            yield from _iter_slots(node, rest)
        return

    if not isinstance(node, dict) or key not in node:
        return

    if not rest:
        yield PropertySlot(owner=node, key=key, value=node[key])
        return

    yield from _iter_slots(node[key], rest)


class ChangeFilter:
    """Pure document transform keeping only the selected Change_Categories.

    ``apply`` never mutates its input: it returns a brand new
    :class:`LocalTemplateDocument` holding deep copies of the retained
    resources. The transform runs in deterministic passes that depend only on
    the selection as a set and on the kept set, which is what makes it
    idempotent and order-independent.
    """

    def __init__(self, selected: Optional[Iterable[str]] = None) -> None:
        """Build a filter for a selection of Change_Categories.

        ``None`` selects every category, which turns :meth:`apply` into an
        identity transform. Values outside :data:`CHANGE_CATEGORIES` are dropped
        with a warning, so a filter object always describes a subset of the
        closed category set.
        """
        if selected is None:
            resolved: Set[str] = set(CHANGE_CATEGORIES)
        elif isinstance(selected, str):
            resolved = {selected}
        else:
            resolved = {value for value in selected}

        unknown = sorted(str(value) for value in resolved if value not in CHANGE_CATEGORIES)
        if unknown:
            logger.warning(
                "Ignoring unknown change type selection value(s) %s; accepted values: %s",
                ", ".join(f"'{value}'" for value in unknown),
                " ".join(CHANGE_CATEGORIES),
            )

        self.selected: frozenset = frozenset(value for value in resolved if value in CHANGE_CATEGORIES)

    def __repr__(self) -> str:
        ordered = [category for category in CHANGE_CATEGORIES if category in self.selected]
        return f"ChangeFilter(selected={ordered})"

    def is_identity(self) -> bool:
        """Return True when the selection covers every Change_Category."""
        return self.selected == frozenset(CHANGE_CATEGORIES)

    def apply(self, document: Optional[LocalTemplateDocument]) -> Optional[LocalTemplateDocument]:
        """Return a new document restricted to the selected Change_Categories.

        Pass 1 keeps the directly selected resources, plus every resource whose
        ``change_category`` is ``None`` so a Legacy_Mode document survives
        untouched. Pass 2 re-admits the virtual networks and subnets that a kept
        resource still needs as a container (Requirement 6.11). Pass 3 removes
        the embedded ``properties["subnets"]`` entries of the subnets that were
        dropped, so no orphan cluster renders. Pass 4 drops the ``dependsOn``
        entries and subnet-id-bearing properties that point at a dropped
        resource (Requirement 6.7).

        Passes 3 and 4 read only the set of dropped resource keys, which is
        derived from the kept set, so re-applying ``apply`` to its own output
        changes nothing (Requirement 6.4) and the result depends on the
        selection as a set rather than as a sequence (Requirement 6.5).
        """
        if document is None:
            return None

        resources = list(document.resources or [])
        kept_indices = self._select_directly(resources)
        kept_indices = self._retain_containers(resources, kept_indices)

        retained = [copy.deepcopy(resources[index]) for index in sorted(kept_indices)]

        dropped_keys = self._dropped_resource_keys(resources, kept_indices)
        if dropped_keys:
            self._prune_embedded_subnets(retained, dropped_keys)
            self._prune_edges(retained, dropped_keys)

        return LocalTemplateDocument(
            source_format=document.source_format,
            provider_name=document.provider_name,
            resources=retained,
            metadata=copy.deepcopy(document.metadata),
        )

    def _select_directly(self, resources: Sequence[LocalTemplateResource]) -> Set[int]:
        """Pass 1: keep selected categories, and every uncategorized resource."""
        if self.is_identity():
            return set(range(len(resources)))
        return {
            index
            for index, resource in enumerate(resources)
            if resource.change_category is None or resource.change_category in self.selected
        }

    def _retain_containers(
        self, resources: Sequence[LocalTemplateResource], kept_indices: Set[int]
    ) -> Set[int]:
        """Pass 2: re-admit containers that a kept resource still references."""
        if self.is_identity() or len(kept_indices) == len(resources):
            return set(kept_indices)

        container_index = self._index_containers(resources)
        if not container_index:
            return set(kept_indices)

        kept = set(kept_indices)
        pending = set(kept)
        while pending:
            index = pending.pop()
            for key in self._referenced_container_keys(resources[index]):
                for candidate in container_index.get(key, ()):
                    if candidate not in kept:
                        kept.add(candidate)
                        pending.add(candidate)
        return kept

    @staticmethod
    def _index_containers(resources: Sequence[LocalTemplateResource]) -> Dict[ContainerKey, List[int]]:
        """Map every container resource to its position, keyed by type and name."""
        index: Dict[ContainerKey, List[int]] = {}
        for position, resource in enumerate(resources):
            if resource.renderer_type in CONTAINER_RENDERER_TYPES:
                index.setdefault(container_key(resource.renderer_type, resource.name), []).append(position)
        return index

    @staticmethod
    def _referenced_container_keys(resource: LocalTemplateResource) -> Set[ContainerKey]:
        """Return every container a resource needs in order to render."""
        keys: Set[ContainerKey] = set()

        for entry in resource.depends_on or []:
            keys |= container_keys_in_value(entry)

        for slot in iter_subnet_id_slots(resource.properties):
            keys |= container_keys_in_value(slot.value)

        if resource.renderer_type == SUBNET_TYPE:
            vnet_name, separator, subnet_name = str(resource.name or "").partition("/")
            if separator and vnet_name and subnet_name:
                keys.add(virtual_network_key(vnet_name))

        return keys

    @staticmethod
    def _dropped_resource_keys(
        resources: Sequence[LocalTemplateResource], kept_indices: Set[int]
    ) -> Set[ContainerKey]:
        """Return the identities present in the document but absent from the kept set.

        Two resources sharing one identity keep that identity alive as long as
        one of them survives, so pruning never removes a reference that still
        resolves to a rendered node.
        """
        all_keys = {container_key(resource.renderer_type, resource.name) for resource in resources}
        kept_keys = {
            container_key(resources[index].renderer_type, resources[index].name) for index in kept_indices
        }
        return all_keys - kept_keys

    @staticmethod
    def _prune_embedded_subnets(
        resources: Sequence[LocalTemplateResource], dropped_keys: Set[ContainerKey]
    ) -> None:
        """Pass 3: drop the embedded entries of the subnets that were dropped.

        Subnets render as clusters from the virtual network's
        ``properties["subnets"]`` list, populated by
        ``TerraformTemplateBuilder._attach_subnets_to_virtual_networks`` with
        ``{"name": <subnet name>, "properties": {...}}`` entries. An entry whose
        subnet no longer exists as a resource would still render a cluster, so
        it goes away with the subnet. Entries that never had a matching subnet
        resource, such as subnets declared inline on the virtual network, are
        left alone because the filter never dropped them.
        """
        for resource in resources:
            if resource.renderer_type != VIRTUAL_NETWORK_TYPE:
                continue
            properties = resource.properties
            if not isinstance(properties, dict):
                continue
            entries = properties.get("subnets")
            if not isinstance(entries, list) or not entries:
                continue

            vnet_name = str(resource.name or "")
            retained_entries = [
                entry
                for entry in entries
                if not ChangeFilter._is_dropped_subnet_entry(vnet_name, entry, dropped_keys)
            ]
            if len(retained_entries) != len(entries):
                properties["subnets"] = retained_entries

    @staticmethod
    def _is_dropped_subnet_entry(
        vnet_name: str, entry: Any, dropped_keys: Set[ContainerKey]
    ) -> bool:
        """Return True when an embedded subnet entry names a dropped subnet."""
        if isinstance(entry, dict):
            subnet_name = entry.get("name")
        elif isinstance(entry, str):
            subnet_name = entry
        else:
            return False

        if not isinstance(subnet_name, str) or not subnet_name or not vnet_name:
            return False

        return subnet_key(vnet_name, subnet_name) in dropped_keys

    @staticmethod
    def _prune_edges(
        resources: Sequence[LocalTemplateResource], dropped_keys: Set[ContainerKey]
    ) -> None:
        """Pass 4: drop references whose target left the document (Requirement 6.7).

        Both a ``dependsOn`` entry and a subnet-id-bearing property would make
        Graphviz materialize an orphan root-level node for a resource that is no
        longer rendered, which is the same failure mode the existing renderer
        guards against for resource groups. References that resolve to nothing
        in the document, such as a dependency on a resource the plan never
        contained, are left untouched so a Legacy_Mode document keeps its exact
        reference set.
        """
        for resource in resources:
            depends_on = resource.depends_on
            if isinstance(depends_on, list) and depends_on:
                retained = [
                    entry for entry in depends_on if not ChangeFilter._targets_dropped(entry, dropped_keys)
                ]
                if len(retained) != len(depends_on):
                    resource.depends_on = retained

            for slot in list(iter_subnet_id_slots(resource.properties)):
                if ChangeFilter._targets_dropped(slot.value, dropped_keys):
                    slot.owner.pop(slot.key, None)

    @staticmethod
    def _targets_dropped(value: Any, dropped_keys: Set[ContainerKey]) -> bool:
        """Return True when a reference value points at a dropped resource."""
        if not isinstance(value, str) or not value.strip():
            return False

        keys: Set[ContainerKey] = set(container_keys_in_value(value))
        parsed = parse_resource_id_expression(value)
        if parsed is not None:
            keys.add(container_key(parsed[0], parsed[1]))

        return any(key in dropped_keys for key in keys)


#: Reason codes for a change the Diagram does not display (Requirements 7.2, 7.3, 7.4).
SKIP_FILTER_REASON: str = "skip-filter"
UNMAPPED_TYPE_REASON: str = "unmapped-type"
NO_RESOURCE_ENTRY_REASON: str = "no-resource-entry"

#: The closed set of reasons, in reporting order.
UNDISPLAYED_REASONS: Tuple[str, ...] = (SKIP_FILTER_REASON, UNMAPPED_TYPE_REASON, NO_RESOURCE_ENTRY_REASON)

#: Console wording of each reason code.
REASON_LABELS: Dict[str, str] = {
    SKIP_FILTER_REASON: "filtered resource type",
    UNMAPPED_TYPE_REASON: "unmapped type",
    NO_RESOURCE_ENTRY_REASON: "no diagram node",
}

#: Heading of the undisplayed-change block (Requirements 7.2, 7.3, 7.4).
NOT_DISPLAYED_HEADING: str = "Changes not displayed"

#: Heading of the per-category count block (Requirement 7.1).
SUMMARY_HEADING: str = "Terraform plan change summary"


@dataclass(frozen=True)
class UndisplayedChange:
    """One planned change that the Diagram does not show, with its reason.

    Only identifying metadata is carried: the Terraform address, the Terraform
    type, the Change_Category, and the reason code. No attribute values ever
    enter this record, which is how sensitive values stay out of the
    Change_Summary and out of every log line derived from it
    (Requirements 10.3, 10.4).
    """

    address: str
    terraform_type: str
    category: str
    reason: str

    def to_payload(self) -> Dict[str, Any]:
        """Return the JSON-serializable form used by the console and the sidecar."""
        return {
            "address": self.address,
            "terraformType": self.terraform_type,
            "category": self.category,
            "reason": self.reason,
        }


@dataclass
class ChangeSummary:
    """Per-category counts plus the changes the Diagram does not display."""

    counts: Dict[str, int] = field(default_factory=dict)
    present_categories: List[str] = field(default_factory=list)
    not_displayed: List[UndisplayedChange] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Keep the count invariant: one entry per Change_Category (Requirement 7.1)."""
        self.counts = normalize_counts(self.counts)
        self.present_categories = [
            category for category in CHANGE_CATEGORIES if category in set(self.present_categories)
        ]

    @property
    def undisplayed_count(self) -> int:
        """Return how many changes the Diagram does not display (Requirement 7.5)."""
        return len(self.not_displayed)

    def has_undisplayed(self) -> bool:
        """Return True when at least one change is reported as not displayed."""
        return bool(self.not_displayed)

    def addresses_by_reason(self, reason: str) -> List[str]:
        """Return the reported addresses carrying one reason code, in report order."""
        return [entry.address for entry in self.not_displayed if entry.reason == reason]

    def to_payload(self) -> Dict[str, Any]:
        """Return the payload shared by the console log and the sidecar JSON."""
        return {
            "counts": dict(self.counts),
            "presentCategories": list(self.present_categories),
            "notDisplayed": [entry.to_payload() for entry in self.not_displayed],
        }


#: Cache of the resolved Skip_Filter predicate, filled on first use.
_SKIP_FILTER = None


def _resolve_skip_filter():
    """Return the real Skip_Filter predicate, or a pattern-based equivalent.

    The design calls for reusing ``utils.graph_utils.should_skip`` so the
    Change_Summary is honest about what the render loop omits (Requirement 7.2).
    That module imports Graphviz, so the import happens here, at call time,
    instead of at module scope: ``plan_diff`` stays importable in an environment
    without Graphviz, which is what keeps it the pure, dependency-light module
    the design describes. When the import fails, the fallback applies the very
    same ``SKIP_RESOURCE_PATTERNS`` table that ``should_skip`` matches on, so the
    predicate is identical either way.
    """
    global _SKIP_FILTER
    if _SKIP_FILTER is not None:
        return _SKIP_FILTER

    try:
        from utils.graph_utils import should_skip as graph_should_skip

        _SKIP_FILTER = graph_should_skip
    except Exception:  # pragma: no cover - only hit without Graphviz installed
        from utils.skip_patterns import SKIP_RESOURCE_PATTERNS

        def pattern_should_skip(resource_type: str) -> bool:
            return any(re.match(pattern, resource_type) for pattern in SKIP_RESOURCE_PATTERNS)

        _SKIP_FILTER = pattern_should_skip

    return _SKIP_FILTER


def is_skipped_by_skip_filter(renderer_type: Optional[str]) -> bool:
    """Return True when the Skip_Filter removes a renderer type from the Diagram."""
    if not isinstance(renderer_type, str) or not renderer_type:
        return False
    return bool(_resolve_skip_filter()(renderer_type))


def _normalize_marker_set(values: Any) -> Set[str]:
    """Return a set of comparable string markers from a caller-supplied argument.

    Callers report unmapped types and Skip_Filter removals either by Terraform
    address, by Terraform type, or by renderer type; a mapping is accepted too,
    in which case its keys and its scalar values both count as markers.
    """
    if values is None:
        return set()
    if isinstance(values, str):
        return {values}
    markers: Set[str] = set()
    if isinstance(values, abc.Mapping):
        for key, value in values.items():
            if isinstance(key, str) and key:
                markers.add(key)
            if isinstance(value, str) and value:
                markers.add(value)
        return markers
    if isinstance(values, abc.Iterable):
        for value in values:
            if isinstance(value, str) and value:
                markers.add(value)
    return markers


def build_change_summary(
    model: Optional[ChangeModel],
    document: Optional[LocalTemplateDocument] = None,
    unmapped: Any = None,
    skipped: Any = None,
) -> ChangeSummary:
    """Assemble the Change_Summary of one Plan_Diff_Mode run.

    ``model`` supplies the per-category counts (Requirement 7.1). ``document``
    is the post-filter :class:`LocalTemplateDocument` that feeds the renderer;
    membership in it decides whether a Change_Record reached a diagram node.
    ``unmapped`` names the Unmapped_Resources, by Terraform address or Terraform
    type (Requirement 7.3), and ``skipped`` names the resources the caller knows
    the Skip_Filter removed, by address or renderer type (Requirement 7.2).

    Every Change_Record that does not reach a rendered node is reported once,
    with exactly one reason from :data:`UNDISPLAYED_REASONS`, resolved in this
    order:

    * ``unmapped-type`` — the record's address or Terraform type is declared
      unmapped, so no renderer type exists for it;
    * ``no-resource-entry`` — the document holds no resource for the address,
      which covers a plan entry the Plan_Parser produced nothing for and an
      address the Change_Filter dropped (Requirement 7.4);
    * ``skip-filter`` — the document holds the resource, but its renderer type
      is removed by the Skip_Filter (Requirement 7.2).

    ``skip-filter`` entries are limited to records whose category is not
    ``unchanged``, matching Requirement 7.2; the other two reasons report every
    category, so an unchanged record without a diagram node is still visible.

    The result carries addresses, Terraform types, categories, and reasons only:
    no attribute value from the plan reaches it (Requirement 10.3).
    """
    change_model = model if model is not None else ChangeModel()
    resource_index = _index_document_addresses(document)
    unmapped_markers = _normalize_marker_set(unmapped)
    skipped_markers = _normalize_marker_set(skipped)

    not_displayed: List[UndisplayedChange] = []
    for address, record in change_model.records.items():
        reason = _undisplayed_reason(record, resource_index, unmapped_markers, skipped_markers)
        if reason is None:
            continue
        not_displayed.append(
            UndisplayedChange(
                address=address,
                terraform_type=record.terraform_type,
                category=record.category,
                reason=reason,
            )
        )

    return ChangeSummary(
        counts=dict(change_model.counts),
        present_categories=change_model.present_categories(),
        not_displayed=not_displayed,
    )


def _index_document_addresses(
    document: Optional[LocalTemplateDocument],
) -> Dict[str, List[LocalTemplateResource]]:
    """Map every Terraform address in a document to the resources built from it."""
    index: Dict[str, List[LocalTemplateResource]] = {}
    if document is None:
        return index
    for resource in document.resources or []:
        address = getattr(resource, "address", "")
        if isinstance(address, str) and address:
            index.setdefault(address, []).append(resource)
    return index


def _undisplayed_reason(
    record: ChangeRecord,
    resource_index: Mapping[str, Sequence[LocalTemplateResource]],
    unmapped_markers: Set[str],
    skipped_markers: Set[str],
) -> Optional[str]:
    """Return why a Change_Record is not displayed, or None when it is rendered."""
    if record.address in unmapped_markers or (record.terraform_type and record.terraform_type in unmapped_markers):
        return UNMAPPED_TYPE_REASON

    resources = resource_index.get(record.address) or ()
    if not resources:
        return NO_RESOURCE_ENTRY_REASON

    if record.category == UNCHANGED_CATEGORY:
        return None

    for resource in resources:
        renderer_type = getattr(resource, "renderer_type", "")
        if record.address in skipped_markers or (renderer_type and renderer_type in skipped_markers):
            continue
        if is_skipped_by_skip_filter(renderer_type):
            continue
        return None

    return SKIP_FILTER_REASON


def format_change_summary(summary: Optional[ChangeSummary]) -> List[str]:
    """Render a Change_Summary as console lines, one list entry per line.

    The per-category block lists every Change_Category with its count, so a
    reader sees the zeros too (Requirement 7.1). The ``Changes not displayed``
    block appears only when at least one change is reported, and each of its
    lines carries the Terraform address, the Terraform type, the category, and
    the reason wording (Requirements 7.2, 7.3, 7.4).
    """
    if summary is None:
        return []

    lines: List[str] = [SUMMARY_HEADING]
    category_width = max(len(category) for category in CHANGE_CATEGORIES) + 2
    for category in CHANGE_CATEGORIES:
        lines.append(f"  {category.ljust(category_width)}{summary.counts.get(category, 0)}")

    if not summary.not_displayed:
        return lines

    lines.append(f"{NOT_DISPLAYED_HEADING} ({len(summary.not_displayed)})")
    address_width = max(len(entry.address) for entry in summary.not_displayed) + 2
    type_width = max(len(entry.terraform_type) for entry in summary.not_displayed) + 2
    category_column = max(len(entry.category) for entry in summary.not_displayed) + 1
    for entry in summary.not_displayed:
        label = REASON_LABELS.get(entry.reason, entry.reason)
        lines.append(
            f"  {entry.address.ljust(address_width)}"
            f"{entry.terraform_type.ljust(type_width)}"
            f"{entry.category.ljust(category_column)}({label})"
        )
    return lines
