"""Property 9: sensitive containment across every new output surface.

Feature: interactive-resource-inspector, task 7.9.

The claim is a security one, so it is asserted with a sentinel rather than by
inspecting shapes: every value a sensitivity mask flags is replaced, before the
draw, by a distinctive marker string that nothing in the codebase can produce by
accident. One generation pass then runs with Inspector_Mode enabled, and the
marker is looked for in every surface this feature adds:

* the Inspector_Payload — the JSONL records and the Inspector_Index bytes;
* the Interaction_Layer SVG, both the one the run wrote and the one the real
  `dot` binary produces from the run's own DOT source, icon rewrite included;
* the Graphviz DOT source the run saved;
* the markup the Inspector_Panel emits for every record of the run, rendered by
  the real `webui/app.js` in the Node DOM harness;
* every log record the run wrote while building, writing and reading the payload
  — the propagating records `caplog` collects and the singleton logger's own.

The marker is planted in two places at once, which is what makes the assertion
bite. It sits in the plan phases and in the resource's attribute map, so the
redaction the builder performs is what has to remove it from the Inspector_Payload;
and it sits in the `properties` map of every drawn Renderer_Template resource, so
the label restriction of Requirement 11.9 is what has to keep it out of the DOT
source and the SVG, and the collector preferring the redacted `inspectorValues`
triple over the raw `properties` map is what has to keep it out of the records.

Requirements covered: 11.5, 11.6, 11.9, 11.10, 14.9.
"""

import copy
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from typing import Any, Dict, List, Tuple

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _path in (PROJECT_ROOT, os.path.join(PROJECT_ROOT, "src"), os.path.dirname(os.path.abspath(__file__))):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from cloudhorus.models.local_template_document import LocalTemplateResource  # noqa: E402
from cloudhorus_webui import CloudHorusAPI  # noqa: E402
from core.graph_generator import DOT_BINARY  # noqa: E402
from core.inspector import (  # noqa: E402
    INSPECTOR_INDEX_SUFFIX,
    INSPECTOR_RECORDS_SUFFIX,
    INTERACTION_LAYER_SUFFIX,
    REDACTION_LITERAL,
    write_svg_with_embedded_icons,
)
from core.inspector import write_inspector_payload  # noqa: E402
from core.plan_diff import CHANGE_CATEGORIES  # noqa: E402
from core.terraform_builder import TerraformTemplateBuilder  # noqa: E402
from strategies.inspector_trees import sensitivity_masks  # noqa: E402
from test_inspector_render import run_generation  # noqa: E402
from test_inspector_webui import DUMP_HELPERS, NODE, js, run_app_js  # noqa: E402
from test_plan_diff_graph_plumbing import RG, VNET  # noqa: E402
from test_plan_diff_graph_plumbing import plan_template  # noqa: E402

#: Sentinel prefix. Deliberately unlike anything the codebase writes, so a hit is
#: a leak rather than a coincidence, and ASCII-only so a byte search over a file
#: written with or without `ensure_ascii` finds it either way.
MARKER_PREFIX = "CHSENSITIVEMARKER"

#: Terraform address of the resource whose configuration carries the markers.
ADDRESS = "azurerm_mssql_server.primary"

#: An attribute Terraform always marks sensitive, forced into every example so a
#: mask that happens to flag nothing still leaves the property something to prove.
FORCED_SENSITIVE_KEY = "administrator_login_password"

#: The `properties` key the markers are planted under in every drawn resource. It
#: is a key no handler of the Graph_Pipeline reads, so planting it changes the
#: drawing of nothing and only the label restriction keeps it out of the DOT.
MARKER_PROPERTY_KEY = "chSensitiveConfig"

DOT_AVAILABLE = shutil.which(DOT_BINARY) is not None


# ─── Marker planting ──────────────────────────────────────────────────────────


def _plant_markers(values: Any, mask: Any, markers: List[str]) -> Any:
    """Replace every value the mask flags with a fresh marker string.

    The walk mirrors the mask semantics `TerraformTemplateBuilder._redact_sensitive`
    implements: a truthy scalar mask flags the whole subtree beneath it, a
    dictionary mask matches by key and flags nothing for an absent key, a list mask
    matches by index and flags nothing past its end, and a mask whose shape does
    not match the tree flags nothing. Planting along exactly those paths is what
    makes a surviving marker a leak rather than a value that was never sensitive.
    """
    if mask is None:
        return values
    if not isinstance(mask, (dict, list)):
        if not mask:
            return values
        marker = f"{MARKER_PREFIX}{len(markers):04d}ZZ"
        markers.append(marker)
        return marker
    if isinstance(values, dict) and isinstance(mask, dict):
        return {
            key: (_plant_markers(child, mask[key], markers) if key in mask else child)
            for key, child in values.items()
        }
    if isinstance(values, list) and isinstance(mask, list):
        return [
            _plant_markers(item, mask[index] if index < len(mask) else None, markers)
            for index, item in enumerate(values)
        ]
    return values


@st.composite
def _marker_cases(draw) -> Tuple[Dict[str, Any], Any, List[str], str]:
    """A marker-bearing attribute tree, its sensitivity mask, and a Change_Category.

    The tree and the mask come from the shared `sensitivity_masks()` strategy, so
    the mask can be shallower than the tree and can flag a whole container; the
    forced sensitive attribute is added on top so at least one marker exists in
    every example.
    """
    tree, mask = draw(sensitivity_masks())
    tree = dict(tree)
    mask = dict(mask) if isinstance(mask, dict) else {}
    tree[FORCED_SENSITIVE_KEY] = "placeholder-secret"
    mask[FORCED_SENSITIVE_KEY] = True

    markers: List[str] = []
    planted = _plant_markers(tree, mask, markers)
    category = draw(st.sampled_from(list(CHANGE_CATEGORIES)))
    return planted, mask, markers, category


def _plan_document(tree: Dict[str, Any], mask: Any) -> Dict[str, Any]:
    """A plan document carrying the marker tree on both phases, with both masks.

    Every phase and every fallback of the Requirement 6 table therefore resolves
    against an aligned mask: `change.before` / `before_sensitive`, `change.after` /
    `after_sensitive`, and the planned resource's own `sensitive_values` for the
    attribute-map fallback the `unchanged` category and a missing phase take.
    """
    return {
        "format_version": "1.0",
        "planned_values": {
            "root_module": {
                "resources": [
                    {
                        "address": ADDRESS,
                        "mode": "managed",
                        "type": "azurerm_mssql_server",
                        "name": "primary",
                        "provider_name": "registry.terraform.io/hashicorp/azurerm",
                        "values": copy.deepcopy(tree),
                        "sensitive_values": copy.deepcopy(mask),
                    }
                ]
            }
        },
        "resource_changes": [
            {
                "address": ADDRESS,
                "mode": "managed",
                "type": "azurerm_mssql_server",
                "change": {
                    "before": copy.deepcopy(tree),
                    "before_sensitive": copy.deepcopy(mask),
                    "after": copy.deepcopy(tree),
                    "after_sensitive": copy.deepcopy(mask),
                },
            }
        ],
    }


def _marker_resource(tree: Dict[str, Any]) -> LocalTemplateResource:
    """The normalized resource whose attribute map holds the markers."""
    return LocalTemplateResource(
        address=ADDRESS,
        provider_name="azurerm",
        source_type="azurerm_mssql_server",
        renderer_type="Microsoft.Sql/servers",
        name="sql-primary",
        properties={},
        extra_fields={},
        raw_values=copy.deepcopy(tree),
    )


def _marker_template(
    tree: Dict[str, Any], values: Dict[str, Any], category: str
) -> Dict[str, Any]:
    """The fixture Renderer_Template with the markers and the redacted triple.

    Every drawn resource carries the raw marker tree in its `properties` map and
    the redacted `inspectorValues` triple the builder resolved. A collector that
    fell back to `properties` instead of using the triple, or a label that carried
    a property value, would put a marker on a surface this property forbids.
    """
    template = plan_template({"planstorage": category, "pe-storage": category, VNET: category})
    for resource in template["resources"]:
        properties = dict(resource.get("properties") or {})
        properties[MARKER_PROPERTY_KEY] = copy.deepcopy(tree)
        resource["properties"] = properties
        resource["inspectorValues"] = copy.deepcopy(values)
    return template


# ─── Log capture ──────────────────────────────────────────────────────────────


class _RecordSink(logging.Handler):
    """Keep the log records themselves, so the args survive the assertion."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: List[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def _singleton_log_sink():
    """Collect the singleton logger's records, which do not propagate to `caplog`."""
    logger = logging.getLogger("SingletonLogger")
    sink = _RecordSink()
    previous_level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(sink)
    try:
        yield sink
    finally:
        logger.removeHandler(sink)
        logger.setLevel(previous_level)


def _log_text(records: List[logging.LogRecord]) -> str:
    """Every part of every record a value could hide in: message, format, args."""
    parts: List[str] = []
    for record in records:
        try:
            parts.append(record.getMessage())
        except Exception:  # noqa: BLE001 - a broken format string is still searchable
            pass
        parts.append(str(record.msg))
        parts.append(repr(record.args))
    return "\n".join(parts)


# ─── Surface readers ──────────────────────────────────────────────────────────


def _read_bytes(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


def _panel_markup(png_path: str, bridge: CloudHorusAPI) -> str:
    """The markup the Inspector_Panel emits for every record of the run, as text.

    The records travel the real Inspector_Bridge reads and are rendered by the real
    `renderInspectorRecord` of `webui/app.js` on the Node DOM stub, which is the
    same level Property 20 asserts escaping at: the dumped tree carries the text
    content, the `innerHTML` the stub accumulated and every attribute the panel set.
    """
    index = bridge.read_inspector_index(png_path)
    assert index is not None, "the run wrote no Inspector_Index"
    records = [bridge.read_inspector_record(png_path, key) for key in index["keys"]]
    dumped = run_app_js(
        js(
            PANEL_SNIPPET,
            index=index,
            records=[record for record in records if record is not None],
            png=png_path,
        )
    )["value"]
    return json.dumps(dumped, ensure_ascii=False)


PANEL_SNIPPET = (
    DUMP_HELPERS
    + """
const RECORDS = %%records%%;
const INDEX = %%index%%;

state.lastGeneratedFile = %%png%%;
state.inspectorIndex = INDEX;

const dumps = [];
for (const record of RECORDS) {
  renderInspectorRecord(record);
  dumps.push({ rows: dumpRows(), panel: dumpPanel() });
}
return { dumps: dumps };
"""
)


def _real_layer_svg(dot_source_path: str, work_dir: str) -> List[str]:
    """The Interaction_Layer the real `dot` produces from the run's own DOT source.

    Returns the SVG text before and after the icon rewrite, or an empty list when
    `dot` is unavailable or cannot lay the source out, following the same
    `shutil.which` discipline the parity module uses.
    """
    if not DOT_AVAILABLE:
        return []
    svg_path = os.path.join(work_dir, "layer-from-source.svg")
    completed = subprocess.run(
        [DOT_BINARY, "-Tsvg", "-o", svg_path, dot_source_path],
        capture_output=True,
    )
    if completed.returncode != 0 or not os.path.exists(svg_path):
        return []
    with open(svg_path, "r", encoding="utf-8") as handle:
        texts = [handle.read()]
    if write_svg_with_embedded_icons(svg_path) is not None:
        with open(svg_path, "r", encoding="utf-8") as handle:
            texts.append(handle.read())
    return texts


# ─── Property 9: Sensitive containment ────────────────────────────────────────
# Feature: interactive-resource-inspector, Property 9: Sensitive containment —
# for any Plan_File holding sensitive attribute values, none of those values
# appears in the Inspector_Payload, in the Interaction_Layer SVG, in the Graphviz
# DOT source, in the markup the Inspector_Panel emits, or in any log record
# written while building, writing or reading the payload; and every
# Interaction_Layer element carries element identity only, never an attribute
# value.


@settings(
    max_examples=int(os.environ.get("CH_CONTAINMENT_EXAMPLES", "25")),
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.data_too_large,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(case=_marker_cases())
def test_property_9_sensitive_containment(case, caplog) -> None:
    """Property 9: Sensitive containment.

    Every value the sensitivity mask flags is planted as a sentinel in the plan
    phases, in the resource's attribute map and in the `properties` map of every
    drawn resource. One Inspector_Mode run later, no sentinel appears in the
    Inspector_Payload, the Interaction_Layer SVG, the DOT source, the panel markup
    or any log record the run wrote, and the payload carries the Redaction_Literal
    where the sentinels stood.

    **Validates: Requirements 11.5, 11.6, 11.9, 11.10, 14.9**
    """
    tree, mask, markers, category = case
    assert markers, "the case planted no sentinel"

    caplog.clear()
    caplog.set_level(logging.DEBUG)

    work_dir = tempfile.mkdtemp(prefix="cloudhorus_inspector_containment_")
    try:
        with _singleton_log_sink() as sink:
            # The builder resolves the phase table and performs the redaction.
            values = TerraformTemplateBuilder()._inspector_values_for(
                _plan_document(tree, mask), _marker_resource(tree), category
            )
            assert values is not None

            result = run_generation(
                _marker_template(tree, values, category),
                work_dir=work_dir,
                interactive_inspector=True,
                payload_writer=write_inspector_payload,
            )

            stem_path = result["png_path"][: -len(".png")]
            records_bytes = _read_bytes(stem_path + INSPECTOR_RECORDS_SUFFIX)
            index_bytes = _read_bytes(stem_path + INSPECTOR_INDEX_SUFFIX)
            dot_source = _read_bytes(stem_path)
            layer_texts = [_read_bytes(stem_path + INTERACTION_LAYER_SUFFIX).decode("utf-8")]
            layer_texts += _real_layer_svg(stem_path, work_dir)

            # The bridge reads happen inside the sink too: Requirement 11.6 covers
            # the read side of the payload as well as the build and the write.
            panel_markup = _panel_markup(result["png_path"], CloudHorusAPI()) if NODE else ""

        log_text = _log_text(sink.records + list(caplog.records))

        surfaces = {
            "Inspector_Payload records": records_bytes.decode("utf-8", "replace"),
            "Inspector_Index": index_bytes.decode("utf-8", "replace"),
            "DOT source": dot_source.decode("utf-8", "replace"),
            "Inspector_Panel markup": panel_markup,
            "log records": log_text,
        }
        for index, text in enumerate(layer_texts):
            surfaces[f"Interaction_Layer SVG {index}"] = text

        for marker in markers:
            for surface, text in surfaces.items():
                assert marker not in text, f"{marker} leaked into the {surface}"

        # Requirement 11.5 is an exclusion, so it needs a witness that the values
        # were carried at all: the payload holds the Redaction_Literal in their place.
        assert REDACTION_LITERAL in records_bytes.decode("utf-8")

        # ...and a witness that the surfaces were populated at all, so no assertion
        # above passed by describing an empty run.
        index_payload = json.loads(index_bytes.decode("utf-8"))
        assert index_payload["keys"], "the run indexed no element"
        assert b"digraph" in dot_source
        assert log_text.strip(), "the run wrote no log record to search"
        if NODE:
            assert "inspector-path-cell" in panel_markup, "the panel rendered no row"
        if DOT_AVAILABLE:
            assert len(layer_texts) > 1, "the real dot laid out no Interaction_Layer"
            assert all("<svg" in text for text in layer_texts[1:])
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
