"""WebUI tests for the Interactive Resource Inspector.

Feature: interactive-resource-inspector

Two layers, following the precedent `tests/test_plan_diff_webui.py` set:

- Python marshalling of the Inspector_Mode toggle through
  `CloudHorusAPI._build_command`.
- DOM behaviour of the real `webui/app.js`, executed in Node on the stub DOM of
  `tests/webui_dom_harness.js`, seeded from the real `webui/index.html` and fed
  by the harness `pywebview.api` stub for the three Inspector_Bridge reads.

- Property 20 (task 12.8) asserts the panel markup carries the Attribute_State
  cue as text and never as live markup, over `markup_strings()` injected into
  record keys, Attribute_Paths and rendered values.
- Property 18 (task 12.9) asserts the toggle marshals identically in every input
  mode and changes no other argument.
- The DOM example tests of task 12.10 pin the panel lifecycle, the filters, the
  counts, the legend, the fallbacks and the container resolution.

What only a real browser can verify, and is therefore asserted structurally here
or manually: the paint order that decides which element a pointer lands on
(Requirement 9.4 geometry), the real `getBBox()` geometry behind the hit rects
(Requirement 3.9 alignment across the zoom range), `:focus-visible` rendering,
and the operating-system clipboard behind `navigator.clipboard.writeText`
(Requirement 5.12 is asserted against a clipboard stub).

Requirements: 2.4, 2.5, 2.6, 2.8, 5.5, 5.6, 5.9, 5.10, 5.11, 5.12, 7.6, 7.7,
7.8, 7.9, 7.10, 7.11, 7.12, 7.13, 8.1, 8.2, 8.4, 8.5, 8.6, 8.7, 8.8, 8.10, 8.11,
9.2, 9.3, 9.4, 9.7, 9.8, 10.3, 10.6, 11.8, 12.9, 13.1, 13.2, 13.7, 13.12
"""

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import replace
from typing import Any, Dict, Iterator, List

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _path in (PROJECT_ROOT, os.path.join(PROJECT_ROOT, "src"), os.path.dirname(os.path.abspath(__file__))):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from cloudhorus_webui import CloudHorusAPI  # noqa: E402
from core.inspector import (  # noqa: E402
    ATTRIBUTE_STATES,
    MAX_ATTRIBUTE_ROWS,
    REDACTION_LITERAL,
    UNCHANGED_STATE,
    AttributeEntry,
    InspectorRecord,
    attribute_styles_payload,
    bounds_payload,
)
from core.plan_diff import CHANGE_CATEGORIES  # noqa: E402
from strategies.inspector_trees import inspector_records, markup_strings  # noqa: E402

HARNESS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webui_dom_harness.js")
INDEX_HTML = os.path.join(PROJECT_ROOT, "webui", "index.html")
STYLE_CSS = os.path.join(PROJECT_ROOT, "webui", "style.css")
NODE = shutil.which("node")

requires_node = pytest.mark.skipif(NODE is None, reason="node is required for the WebUI DOM harness")

#: PNG the harness pretends the run produced; every bridge read is keyed on it.
DIAGRAM_PNG = "/out/azure_resources_20260726_145233/azure_resources_20260726_145233.png"

#: Attribute_Flag_Token and colour token of each Attribute_State, as
#: `attribute_styles_payload()` writes them into the Inspector_Index.
EXPECTED_STYLES = attribute_styles_payload()

#: Element tags the panel is allowed to create. A payload string that became
#: markup would show up here as something else.
ALLOWED_ROW_TAGS = {"TR", "TD", "SPAN"}

#: Attribute names the panel sets on the elements it builds.
ALLOWED_ROW_ATTRS = {"data-state", "aria-label", "aria-hidden", "colspan", "class", "role"}


# ─── Harness plumbing ─────────────────────────────────────────────────────────


def run_app_js(snippet: str) -> Dict[str, Any]:
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


def js(template: str, **payloads: Any) -> str:
    """Inline JSON payloads into a snippet: ``%%name%%`` becomes ``json.dumps(value)``.

    The dump stays ASCII-only, so a generated string carrying non-ASCII or
    control characters reaches Node as an escape sequence rather than as a raw
    byte that depends on the locale.
    """
    snippet = template
    for name, value in payloads.items():
        snippet = snippet.replace(f"%%{name}%%", json.dumps(value))
    return snippet


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


# ─── Fixture data ─────────────────────────────────────────────────────────────


#: A Graphviz-shaped Interaction_Layer: clusters and nodes as siblings under
#: `g#graph0`, each carrying its Inspector_Key in `<title>`, which is exactly
#: what `dot -Tsvg` writes.
LAYER_SVG = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<svg width="620pt" height="400pt" viewBox="0 0 620 400"
     xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">
<g id="graph0" class="graph" transform="scale(1 1) rotate(0) translate(4 4)">
<title>azure</title>
<g id="clust1" class="cluster">
<title>cluster_vnetvnet-hub</title>
<polygon id="vnet-poly" fill="#eaf3fb" stroke="#0078d4" points="8,8 8,380 600,380 600,8 8,8"/>
<text text-anchor="middle" x="300" y="28">vnet-hub</text>
</g>
<g id="clust2" class="cluster">
<title>cluster_subnetsnet-app</title>
<polygon id="subnet-poly" fill="#f6fbff" stroke="#8a8886" points="24,48 24,340 340,340 340,48 24,48"/>
<text text-anchor="middle" x="180" y="68">snet-app</text>
</g>
<g id="node1" class="node">
<title>vm-app-rg-app</title>
<ellipse id="vm-ellipse" fill="none" stroke="#323130" cx="180" cy="200" rx="60" ry="30"/>
<text text-anchor="middle" x="180" y="204">vm-app</text>
</g>
<g id="node2" class="node">
<title>st-data-rg-data</title>
<ellipse id="st-ellipse" fill="none" stroke="#323130" cx="480" cy="200" rx="60" ry="30"/>
<text text-anchor="middle" x="480" y="204">st-data</text>
</g>
</g>
</svg>
"""

#: The same three elements nested, which is what makes `closest()` resolution
#: assertable: the innermost activatable ancestor wins (Requirements 9.4, 9.8).
NESTED_LAYER_SVG = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<svg width="620pt" height="400pt" viewBox="0 0 620 400" xmlns="http://www.w3.org/2000/svg">
<g id="graph0" class="graph">
<title>azure</title>
<g id="clust1" class="cluster">
<title>cluster_vnetvnet-hub</title>
<polygon id="vnet-poly" fill="#eaf3fb" points="8,8 8,380 600,380 600,8 8,8"/>
<g id="clust2" class="cluster">
<title>cluster_subnetsnet-app</title>
<polygon id="subnet-poly" fill="#f6fbff" points="24,48 24,340 340,340 340,48 24,48"/>
<g id="node1" class="node">
<title>vm-app-rg-app</title>
<ellipse id="vm-ellipse" fill="none" cx="180" cy="200" rx="60" ry="30"/>
<text text-anchor="middle" x="180" y="204">vm-app</text>
</g>
</g>
</g>
</g>
</svg>
"""

VM_KEY = "vm-app-rg-app"
ST_KEY = "st-data-rg-data"
VNET_KEY = "cluster_vnetvnet-hub"
SUBNET_KEY = "cluster_subnetsnet-app"


def record_payload(
    key: str,
    kind: str = "node",
    name: str = "vm-app",
    resource_type: str = "Microsoft.Compute/virtualMachines",
    resource_group: str = "rg-app",
    address: str = "azurerm_linux_virtual_machine.app",
    change_category: str = "update",
    entries: List[AttributeEntry] = None,
    omitted: int = 0,
    truncations: List[str] = None,
) -> Dict[str, Any]:
    """One Inspector_Record in the wire shape the Inspector_Bridge returns.

    Built through `InspectorRecord.to_payload()` rather than by hand, so the keys
    the panel reads are the keys the writer emits.
    """
    record = InspectorRecord(
        key=key,
        kind=kind,
        name=name,
        resource_type=resource_type,
        resource_group=resource_group,
        address=address,
        change_category=change_category,
        replacement=change_category == "replace",
        attributes=list(
            entries
            if entries is not None
            else [
                AttributeEntry(path="location", state=UNCHANGED_STATE, before="westeurope", after="westeurope"),
                AttributeEntry(path="size", state="changed", before='"Standard_B1s"', after='"Standard_B2s"'),
                AttributeEntry(path="tags.owner", state="added", after='"platform"'),
                AttributeEntry(path="tags.legacy", state="removed", before='"true"'),
            ]
        ),
        omitted_attributes=omitted,
        truncations=list(truncations or []),
    )
    return record.to_payload()


def index_payload(keys: Dict[str, str], collisions: int = 0) -> Dict[str, Any]:
    """The Inspector_Index shape `write_inspector_payload` writes.

    The offsets are irrelevant to the front end - it never reads the JSONL - but
    the `attributeStyles` and `bounds` blocks are exactly what the panel reads
    (Requirements 7.13, 12.10).
    """
    return {
        "schemaVersion": 1,
        "diagram": os.path.basename(DIAGRAM_PNG),
        "records": os.path.basename(DIAGRAM_PNG).replace(".png", ".inspector.jsonl"),
        "recordCount": len(keys),
        "keyCollisions": collisions,
        "keys": {key: {"offset": 0, "length": 1, "kind": kind} for key, kind in keys.items()},
        "attributeStyles": attribute_styles_payload(),
        "bounds": bounds_payload(),
    }


DEFAULT_KEYS = {VM_KEY: "node", ST_KEY: "node", VNET_KEY: "virtualNetwork", SUBNET_KEY: "subnet"}


def default_fixture(records: Dict[str, Any] = None, layer: str = LAYER_SVG) -> Dict[str, Any]:
    """Bridge fixture: one layer, one index, and a key -> record map."""
    return {
        "layer": layer,
        "index": index_payload(DEFAULT_KEYS),
        "records": records
        if records is not None
        else {
            VM_KEY: record_payload(VM_KEY),
            ST_KEY: record_payload(
                ST_KEY,
                name="st-data",
                resource_type="Microsoft.Storage/storageAccounts",
                resource_group="rg-data",
                address="azurerm_storage_account.data",
                change_category="create",
                entries=[AttributeEntry(path="account_tier", state="added", after='"Standard"')],
            ),
            VNET_KEY: record_payload(
                VNET_KEY,
                kind="virtualNetwork",
                name="vnet-hub",
                resource_type="Microsoft.Network/virtualNetworks",
                resource_group="rg-network",
                address="azurerm_virtual_network.hub",
                entries=[AttributeEntry(path="address_space.0", state="changed", before='"10.0.0.0/16"', after='"10.1.0.0/16"')],
            ),
            SUBNET_KEY: record_payload(
                SUBNET_KEY,
                kind="subnet",
                name="snet-app",
                resource_type="Microsoft.Network/virtualNetworks/subnets",
                resource_group="rg-network",
                address="azurerm_subnet.app",
                entries=[AttributeEntry(path="address_prefixes.0", state=UNCHANGED_STATE, before='"10.0.1.0/24"', after='"10.0.1.0/24"')],
            ),
        },
    }


# ─── Shared snippet fragments ─────────────────────────────────────────────────


#: Dump helpers every DOM snippet reuses. `dumpEl` reports the element tree the
#: panel built plus, per element, the `innerHTML` string the stub accumulates for
#: appended text nodes - which is where an escaping regression would show.
DUMP_HELPERS = """
function dumpEl(el) {
  return {
    tag: el.tagName,
    id: el.id || '',
    className: el.className || '',
    attrs: Object.assign({}, el.attributes),
    text: el.textContent || '',
    innerHTML: el.innerHTML || '',
    styleColor: (el.style && el.style.color) || '',
    hidden: !!(el.classList && el.classList.contains('hidden')),
    children: (el.children || []).map(dumpEl),
  };
}
function dumpById(id) {
  return dumpEl(document.getElementById(id));
}
function dumpRows() {
  return (document.getElementById('inspector-rows').children || []).map(dumpEl);
}
function dumpPanel() {
  return {
    panelHidden: document.getElementById('inspector-panel').classList.contains('hidden'),
    name: document.getElementById('inspector-name').textContent,
    type: document.getElementById('inspector-type').textContent,
    resourceGroup: document.getElementById('inspector-resource-group').textContent,
    address: document.getElementById('inspector-address').textContent,
    addressHidden: document.getElementById('inspector-address-row').classList.contains('hidden'),
    status: document.getElementById('inspector-status').textContent,
    counts: dumpById('inspector-counts'),
    category: dumpById('inspector-category'),
    legend: dumpById('inspector-legend'),
    truncation: dumpById('inspector-truncation'),
    rows: dumpRows(),
    inspectorKey: state.inspectorKey,
    viewerLayer: state.viewerLayer,
    viewerZoom: state.viewerZoom,
    stageClass: document.getElementById('viewer-stage').className,
    stageTransform: document.getElementById('viewer-stage').style.transform || '',
    layerToggleHidden: document.getElementById('viewer-layer-toggle').classList.contains('hidden'),
    hasLayer: !!interactionLayerRoot(),
  };
}
function flush() {
  return new Promise(function (resolve) { setTimeout(resolve, 0); });
}
function groupByKey(key) {
  const root = interactionLayerRoot();
  const groups = root ? root.querySelectorAll('g.node, g.cluster') : [];
  return Array.prototype.filter.call(groups, g => {
    const title = g.querySelectorAll('title');
    return title.length && String(title[0].textContent).trim() === key;
  })[0] || null;
}
function childById(key, childId) {
  const group = groupByKey(key);
  if (!group) return null;
  const found = group.querySelectorAll('#' + childId);
  return found.length ? found[0] : null;
}
"""


# ─────────────────────────────────────────────────────────────────────────────
# Property 20 (task 12.8): panel markup carries the state cue as text and never
# as live markup
# ─────────────────────────────────────────────────────────────────────────────


#: Control characters, which `markup_strings()` carries only as a newline. A
#: value that reaches the document through a text node keeps them; a value
#: concatenated into markup can have them swallowed by the parser, which is why
#: they belong in the hostile set.
control_strings = st.text(alphabet=st.characters(categories=("Cc", "Cf")), min_size=1, max_size=8)

#: Values long enough that a naive escaper working on a fixed-size window would
#: split an injection payload across two chunks.
long_strings = st.builds(
    lambda filler, payload, tail: filler * 512 + payload + tail * 512,
    st.sampled_from(("a", "<", "&", '"', "é")),
    st.sampled_from(
        (
            "<script>alert(1)</script>",
            '" onclick="alert(1)',
            "<img src=x onerror=alert(1)>",
            "javascript:alert(1)",
        )
    ),
    st.sampled_from(("z", ">", "'")),
)


def hostile_text() -> st.SearchStrategy[str]:
    """Every hostile payload shape Property 20 has to survive.

    `markup_strings()` supplies the markup metacharacters, the `<script>` and
    `<img src=x onerror=…>` elements, the quote-and-`on*` escapes and the
    `javascript:` URL; the two local strategies add the shapes it does not carry.
    """
    return st.one_of(markup_strings(), control_strings, long_strings)


@st.composite
def hostile_inspector_records(draw: st.DrawFn) -> InspectorRecord:
    """Inspector_Records whose keys, identity fields, paths and values hold markup."""
    record = draw(inspector_records(keys=markup_strings(), text_values=hostile_text()))
    record.name = draw(hostile_text())
    record.resource_type = draw(hostile_text())
    record.resource_group = draw(hostile_text())
    record.address = draw(st.one_of(st.none(), hostile_text()))
    entries = [replace(entry, path=draw(hostile_text())) for entry in record.attributes]
    if not entries:
        entries = [
            AttributeEntry(
                path=draw(hostile_text()),
                state="changed",
                before=draw(hostile_text()),
                after=draw(hostile_text()),
            )
        ]
    record.attributes = entries
    return record


#: An Attribute_Style table that is deliberately *not* the constant table, so a
#: panel reading its own copy of the colour tokens instead of the Inspector_Index
#: fails Property 20 (Requirement 7.13).
CUSTOM_STYLES = {
    "added": {"color": "#123456", "flag": "A", "label": "Inserted"},
    "removed": {"color": "#654321", "flag": "R", "label": "Dropped"},
    "changed": {"color": "#abcdef", "flag": "M", "label": "Modified"},
}

PANEL_MARKUP_SNIPPET = (
    DUMP_HELPERS
    + """
const RECORD = %%record%%;
const INDEX = %%index%%;
const CUSTOM = %%custom%%;

state.lastGeneratedFile = %%png%%;

state.inspectorIndex = INDEX;
renderInspectorRecord(RECORD);
const withIndex = { rows: dumpRows(), panel: dumpPanel() };

state.inspectorIndex = Object.assign({}, INDEX, { attributeStyles: CUSTOM });
renderInspectorRecord(RECORD);
const withCustomStyles = { rows: dumpRows() };

state.inspectorIndex = null;
renderInspectorRecord(RECORD);
const withoutIndex = { rows: dumpRows(), panel: dumpPanel() };

return { withIndex: withIndex, withCustomStyles: withCustomStyles, withoutIndex: withoutIndex };
"""
)


def walk(node: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    """Every element of a dumped subtree, the root included."""
    yield node
    for child in node.get("children", ()):
        yield from walk(child)


def assert_inert(node: Dict[str, Any], allowed_tags: set = None) -> None:
    """No payload text became an element, an attribute, or live markup."""
    tags = allowed_tags or ALLOWED_ROW_TAGS
    for element in walk(node):
        assert element["tag"] in tags, f"unexpected element {element['tag']}"
        assert re.fullmatch(r"[A-Za-z0-9 _-]*", element["className"]), element["className"]
        for name, value in element["attrs"].items():
            assert name in ALLOWED_ROW_ATTRS, f"unexpected attribute {name}"
            for forbidden in ("<", ">", '"'):
                assert forbidden not in value, f"{name}={value!r} carries {forbidden!r}"
        # Text reaches the document through a text node, so the stub's innerHTML
        # holds the escaped form. A raw angle bracket here means the value was
        # concatenated into markup instead.
        for forbidden in ("<", ">"):
            assert forbidden not in element["innerHTML"], f"{element['innerHTML']!r} carries {forbidden!r}"


def value_cells(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [child for child in row["children"] if child["className"] == "inspector-value-cell"]


def assert_row_matches(row: Dict[str, Any], entry: AttributeEntry, styles: Dict[str, Any]) -> None:
    """One rendered row against the Attribute_Entry and the style table in force."""
    state = entry.state
    style = styles.get(state)
    flag = style["flag"] if style else ""
    color = style["color"] if style else ""
    before = "" if entry.before is None else entry.before
    after = "" if entry.after is None else entry.after

    assert row["tag"] == "TR"
    assert row["className"] == f"attr-{state}"
    assert row["attrs"]["data-state"] == state
    # Requirements 7.6-7.9: the colour token of the state, and the default panel
    # colour for `unchanged`.
    assert row["styleColor"] == color

    flag_cell = row["children"][0]
    assert flag_cell["className"] == "inspector-flag-cell"
    # Requirement 7.10: the flag is text in a cell of its own, not a colour.
    assert flag_cell["text"] == flag
    assert flag_cell["children"] == []
    if flag:
        assert flag_cell["attrs"]["aria-label"] == style["label"]

    path_cell = row["children"][1]
    assert path_cell["className"] == "inspector-path-cell"
    assert path_cell["text"] == entry.path

    cells = value_cells(row)
    if state == "changed":
        # Requirement 7.11: two separately labelled values.
        assert len(cells) == 2
        assert [child["text"] for child in cells[0]["children"]] == ["Before"]
        assert [child["text"] for child in cells[1]["children"]] == ["After"]
        assert cells[0]["text"] == before
        assert cells[1]["text"] == after
    elif state == "added":
        assert [cell["text"] for cell in cells] == ["", after]
        assert all(cell["children"] == [] for cell in cells)
    elif state == "removed":
        assert [cell["text"] for cell in cells] == [before, ""]
        assert all(cell["children"] == [] for cell in cells)
    else:
        assert len(cells) == 1
        assert cells[0]["attrs"]["colspan"] == "2"
        assert cells[0]["text"] == (before if before != "" else after)


# Feature: interactive-resource-inspector, Property 20: Panel markup carries the
# state cue as text and never as live markup - for any Inspector_Record, including
# records whose keys, paths and values hold markup metacharacters and complete
# <script> elements, every Attribute_Entry carries the colour token and the
# Attribute_Flag_Token of its Attribute_State with the flag as text content in a
# cell of its own, container records get the same treatment as node records, every
# payload character is escaped so no payload text becomes an element or an
# attribute, and the Attribute_Style table comes from the Inspector_Index.
@requires_node
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(record=hostile_inspector_records())
def test_panel_markup_carries_the_state_cue_as_text_and_never_as_live_markup(record):
    """**Validates: Requirements 7.6, 7.7, 7.8, 7.9, 7.10, 7.13, 9.7, 13.12**"""
    payload = record.to_payload()
    result = run_app_js(
        js(
            PANEL_MARKUP_SNIPPET,
            record=payload,
            index=index_payload({record.key: record.kind}),
            custom=CUSTOM_STYLES,
            png=DIAGRAM_PNG,
        )
    )["value"]

    with_index = result["withIndex"]
    assert len(with_index["rows"]) == len(record.attributes)

    for row, entry in zip(with_index["rows"], record.attributes):
        assert_inert(row)
        # Requirement 9.7: a container record is rendered exactly as a node record
        # is, so the assertion is the same one for every `kind`.
        assert_row_matches(row, entry, EXPECTED_STYLES)

    # Requirement 13.12: the identity header carries the payload text as text.
    panel = with_index["panel"]
    assert panel["name"] == (record.name or record.key)
    assert panel["type"] == record.resource_type
    assert panel["resourceGroup"] == record.resource_group
    for section in ("counts", "category", "legend", "truncation"):
        # The section containers come from index.html; only their content is built
        # from the payload.
        assert_inert(panel[section], allowed_tags=ALLOWED_ROW_TAGS | {"DIV", "P"})

    # Requirement 7.13: the tokens follow the index, not a second copy of the
    # constants - a different table produces different rows...
    for row, entry in zip(result["withCustomStyles"]["rows"], record.attributes):
        assert_inert(row)
        assert_row_matches(row, entry, CUSTOM_STYLES)

    # ...and no table at all leaves every row styleless rather than reviving one.
    for row, entry in zip(result["withoutIndex"]["rows"], record.attributes):
        assert_inert(row)
        assert row["styleColor"] == ""
        assert row["children"][0]["text"] == ""


# ─────────────────────────────────────────────────────────────────────────────
# Property 18 (task 12.9): toggle marshalling is mode-independent
# ─────────────────────────────────────────────────────────────────────────────


INSPECTOR_FLAG = "--interactiveInspector"

#: One node run enumerating every input mode with the toggle off and on. The JS
#: half of Property 18 is a fixed matrix - the front end has five selections, not
#: an input space - so it is measured once and cross-checked per example.
TOGGLE_MATRIX_SNIPPET = """
const cases = [
  { label: 'live', setup: function () { state.mode = 'live'; } },
  { label: 'bicep', setup: function () {
      state.mode = 'bicep';
      state.bicepFiles = ['/tpl/main.bicep'];
      state.paramFiles = ['/tpl/main.parameters.json'];
    } },
  { label: 'terraform-source', setup: function () {
      state.mode = 'terraform';
      state.terraformPlanFiles = [];
      state.terraformMainFiles = ['/stacks/app/main.tf'];
      state.terraformVarFiles = ['/stacks/app/app.tfvars'];
    } },
  { label: 'terraform-json', setup: function () {
      state.mode = 'terraform';
      state.terraformMainFiles = [];
      state.terraformVarFiles = [];
      state.terraformPlanFiles = ['/plans/app.plan.json'];
      state.changeTypes = [];
    } },
  { label: 'plan-diff', setup: function () {
      state.mode = 'terraform';
      state.terraformMainFiles = [];
      state.terraformPlanFiles = ['/plans/network.plan.json'];
      state.changeTypes = ['create', 'delete'];
    } },
];

const results = {};
for (const testCase of cases) {
  for (const toggle of [false, true]) {
    testCase.setup();
    document.getElementById('chk-interactive-inspector').checked = toggle;
    const args = buildCommandArgs();
    const command = buildCommandString();
    refreshPreview();
    results[testCase.label + '|' + toggle] = {
      args: args,
      argsFlag: args.interactiveInspector,
      stateFlag: state.interactiveInspector,
      command: command,
      preview: document.getElementById('command-preview').innerHTML,
    };
  }
}
return results;
"""

MODE_LABELS = ("live", "bicep", "terraform-source", "terraform-json", "plan-diff")


@pytest.fixture(scope="module")
def api():
    return CloudHorusAPI()


@pytest.fixture(scope="module")
def js_toggle_matrix():
    """`buildCommandArgs()` / `buildCommandString()` per input mode, toggle off and on."""
    if NODE is None:
        pytest.skip("node is required for the WebUI DOM harness")
    return run_app_js(TOGGLE_MATRIX_SNIPPET)["value"]


def paths(prefix: str) -> st.SearchStrategy[List[str]]:
    name = st.text(alphabet="abcdefgh-_", min_size=1, max_size=8)
    return st.lists(name.map(lambda part: f"{prefix}/{part}"), min_size=1, max_size=3, unique=True)


@st.composite
def webui_arg_payloads(draw: st.DrawFn) -> Dict[str, Any]:
    """One argument payload as `webui/app.js` posts it, in one of the five selections.

    The Inspector_Mode key is deliberately absent: the property adds it.
    """
    label = draw(st.sampled_from(MODE_LABELS))
    args: Dict[str, Any] = {
        "mode": "terraform" if label.startswith("terraform") or label == "plan-diff" else label,
        "authMethod": draw(st.sampled_from(("device-code", "service-principal"))),
        "edgeDirection": draw(st.sampled_from(("TB", "LR"))),
        "tenantDirection": draw(st.sampled_from(("TB", "LR"))),
        "maxSubnetPerline": draw(st.integers(min_value=1, max_value=8)),
        "resourcesEdgeLength": draw(st.integers(min_value=1, max_value=4)),
        "rankDebug": draw(st.booleans()),
        "privateDnsZonesOptimization": draw(st.booleans()),
        "exportDrawio": draw(st.booleans()),
    }
    if label == "live":
        args["tenants"] = draw(st.sampled_from(("", "tenant-a", "tenant-a tenant-b")))
        args["subscriptions"] = draw(st.sampled_from(("", "sub-a", "sub-a sub-b")))
        args["resourcegroups"] = draw(st.sampled_from(("", "rg-app")))
        args["discoverResourceGroups"] = draw(st.lists(st.sampled_from(("rg-app", "rg-net")), max_size=2, unique=True))
        subscription_count = len(args["subscriptions"].split())
        if subscription_count:
            args["subnetOptimization"] = draw(st.lists(st.booleans(), min_size=subscription_count, max_size=subscription_count))
            args["peOptimization"] = draw(st.lists(st.booleans(), min_size=subscription_count, max_size=subscription_count))
    elif label == "bicep":
        args["bicepFiles"] = draw(paths("/tpl"))
        args["parametersFiles"] = draw(st.one_of(st.just([]), paths("/tpl")))
    elif label == "terraform-source":
        args["terraformRootDirs"] = draw(paths("/stacks"))
        args["terraformVarFiles"] = draw(st.one_of(st.just([]), paths("/stacks")))
    else:
        args["terraformJsonFiles"] = draw(paths("/plans"))
        args["changeTypes"] = draw(
            st.lists(st.sampled_from(list(CHANGE_CATEGORIES)), max_size=len(CHANGE_CATEGORIES), unique=True)
        )
    if label != "live":
        args["scopeMetadataFiles"] = draw(st.one_of(st.just([]), paths("/plans")))
    return {"label": label, "args": args}


def without_inspector_flag(command: List[str]) -> List[str]:
    """The command with the Inspector_Mode flag and its value removed."""
    if INSPECTOR_FLAG not in command:
        return list(command)
    index = command.index(INSPECTOR_FLAG)
    return command[:index] + command[index + 2 :]


# Feature: interactive-resource-inspector, Property 18: Toggle marshalling is
# mode-independent - for any input mode and any argument payload, the command the
# WebUI builds contains `--interactiveInspector True` exactly when the toggle is
# on, the displayed command preview contains the same flag as the command that
# will run, and the presence of the flag changes no other argument of the payload.
@settings(max_examples=100, deadline=None)
@given(payload=webui_arg_payloads(), toggle=st.booleans())
def test_toggle_marshalling_is_mode_independent(payload, toggle, api, js_toggle_matrix):
    """**Validates: Requirements 2.5, 2.6, 2.8**"""
    args = payload["args"]
    label = payload["label"]

    built = api._build_command({**args, "interactiveInspector": toggle})
    baseline = api._build_command({**args, "interactiveInspector": False})
    absent = api._build_command(dict(args))

    # The flag is on the command line exactly when the toggle is on...
    assert (INSPECTOR_FLAG in built) is toggle
    if toggle:
        assert built[built.index(INSPECTOR_FLAG) + 1] == "True"
        assert built.count(INSPECTOR_FLAG) == 1
    # ...and it is the only difference: an off run and an omitted key marshal the
    # same command as the on run with the flag removed (Requirement 2.5).
    assert without_inspector_flag(built) == baseline == absent

    # The same holds for every input mode the WebUI offers, and the preview the
    # Operator reads carries the same flag as the command that runs
    # (Requirements 2.6, 2.8).
    for mode_label in MODE_LABELS:
        for js_toggle in (False, True):
            entry = js_toggle_matrix[f"{mode_label}|{str(js_toggle).lower()}"]
            assert entry["argsFlag"] is js_toggle
            assert entry["stateFlag"] is js_toggle
            assert (f"{INSPECTOR_FLAG} True" in entry["command"]) is js_toggle
            assert (f"{INSPECTOR_FLAG} True" in entry["preview"]) is js_toggle
            # What the front end posts and what the backend builds agree
            assert (INSPECTOR_FLAG in api._build_command(entry["args"])) is js_toggle

    # Turning the toggle on changes no other argument of the posted payload
    on_args = dict(js_toggle_matrix[f"{label}|true"]["args"])
    off_args = dict(js_toggle_matrix[f"{label}|false"]["args"])
    on_args.pop("interactiveInspector")
    off_args.pop("interactiveInspector")
    assert on_args == off_args


# ─────────────────────────────────────────────────────────────────────────────
# DOM example tests (task 12.10)
# ─────────────────────────────────────────────────────────────────────────────


#: Every DOM snippet starts from a finished run: the bridge stub installed, the
#: PNG recorded, and the Interaction_Layer inlined.
LOADED = (
    DUMP_HELPERS
    + """
state.lastGeneratedFile = %%png%%;
__installInspectorBridge(%%fixture%%);
"""
)


def dom_snippet(body: str, fixture: Dict[str, Any] = None, **payloads: Any) -> str:
    """A snippet that starts from a loaded run and then executes *body*."""
    return js(LOADED + body, png=DIAGRAM_PNG, fixture=fixture or default_fixture(), **payloads)


# ─── The toggle in index.html (Requirement 2.4) ───────────────────────────────


def test_index_html_ships_the_inspector_toggle_defaulted_off():
    """Requirement 2.4: one mode-independent Inspector_Mode toggle, off by default."""
    html = read_text(INDEX_HTML)

    start = html.index('id="chk-interactive-inspector"')
    tag = html[html.rindex("<input", 0, start) : html.index(">", start)]
    assert "checked" not in tag

    # It sits in the Optimizations card beside --exportDrawio, which is the card
    # every input mode shows, rather than inside a mode-specific file section.
    section_start = html.index('id="section-optimizations"')
    section_end = html.index("</section>", section_start)
    assert section_start < html.index('id="chk-export-drawio"') < start < section_end
    for mode_section in ('id="section-terraform-files"', 'id="section-bicep-files"'):
        if mode_section in html:
            mode_start = html.index(mode_section)
            assert not mode_start < start < html.index("</section>", mode_start)


@requires_node
def test_inspector_toggle_defaults_off_in_every_mode(js_toggle_matrix):
    """Requirement 2.4: the front end reads the toggle as off until it is set."""
    for label in MODE_LABELS:
        assert js_toggle_matrix[f"{label}|false"]["argsFlag"] is False

    payload = run_app_js("return { toggle: inspectorToggleOn(), stateField: state.interactiveInspector };")
    assert payload["value"] == {"toggle": False, "stateField": False}


# ─── Activation, replacement and close (Requirements 8.1, 8.2, 8.4, 8.5) ──────


@requires_node
def test_click_and_keyboard_activation_open_the_panel_with_the_record():
    """Requirements 8.1, 8.2: a pointer click and Enter/Space open the panel."""
    payload = run_app_js(
        dom_snippet(
            """
await loadInspector(state.lastGeneratedFile);
const stage = document.getElementById('viewer-stage');
const results = {};

stage.dispatchEvent({ type: 'click', target: childById(%%vm%%, 'vm-ellipse') });
await flush();
results.click = dumpPanel();

closeInspectorPanel();
stage.dispatchEvent({ type: 'keydown', key: 'Enter', target: childById(%%st%%, 'st-ellipse') });
await flush();
results.enter = dumpPanel();

closeInspectorPanel();
stage.dispatchEvent({ type: 'keydown', key: ' ', target: childById(%%vm%%, 'vm-ellipse') });
await flush();
results.space = dumpPanel();

closeInspectorPanel();
stage.dispatchEvent({ type: 'keydown', key: 'Tab', target: childById(%%vm%%, 'vm-ellipse') });
await flush();
results.tab = dumpPanel();
return results;
""",
            vm=VM_KEY,
            st=ST_KEY,
        )
    )
    value = payload["value"]

    assert value["click"]["panelHidden"] is False
    assert value["click"]["inspectorKey"] == VM_KEY
    assert value["click"]["name"] == "vm-app"
    assert len(value["click"]["rows"]) == 4

    assert value["enter"]["inspectorKey"] == ST_KEY
    assert value["enter"]["name"] == "st-data"
    assert value["space"]["inspectorKey"] == VM_KEY
    # A key that is neither Enter nor Space leaves the panel closed
    assert value["tab"]["panelHidden"] is True


@requires_node
def test_escape_and_the_close_control_return_focus_to_the_opener():
    """Requirement 8.4: both close paths hide the panel and hand focus back."""
    payload = run_app_js(
        dom_snippet(
            """
await loadInspector(state.lastGeneratedFile);
const stage = document.getElementById('viewer-stage');
const group = groupByKey(%%vm%%);
let focusCount = 0;
group.focus = function () { focusCount += 1; };

stage.dispatchEvent({ type: 'click', target: childById(%%vm%%, 'vm-ellipse') });
await flush();
const opened = dumpPanel();
document.dispatchEvent({ type: 'keydown', key: 'Escape' });
const afterEscape = { panel: dumpPanel(), focusCount: focusCount };

stage.dispatchEvent({ type: 'click', target: childById(%%vm%%, 'vm-ellipse') });
await flush();
closeInspectorPanel();
const afterClose = { panel: dumpPanel(), focusCount: focusCount };
return { opened: opened, afterEscape: afterEscape, afterClose: afterClose };
""",
            vm=VM_KEY,
        )
    )
    value = payload["value"]

    assert value["opened"]["panelHidden"] is False
    assert value["afterEscape"]["panel"]["panelHidden"] is True
    assert value["afterEscape"]["panel"]["inspectorKey"] is None
    assert value["afterEscape"]["focusCount"] == 1
    assert value["afterClose"]["panel"]["panelHidden"] is True
    assert value["afterClose"]["focusCount"] == 2


@requires_node
def test_a_second_activation_replaces_the_displayed_record():
    """Requirement 8.5: activating another element replaces the record on screen."""
    payload = run_app_js(
        dom_snippet(
            """
await loadInspector(state.lastGeneratedFile);
const stage = document.getElementById('viewer-stage');
stage.dispatchEvent({ type: 'click', target: childById(%%vm%%, 'vm-ellipse') });
await flush();
const first = dumpPanel();
stage.dispatchEvent({ type: 'click', target: childById(%%st%%, 'st-ellipse') });
await flush();
const second = dumpPanel();
const selected = Array.prototype.map.call(
  interactionLayerRoot().querySelectorAll('.ch-selected'),
  function (el) { return el.id; }
);
return { first: first, second: second, selected: selected };
""",
            vm=VM_KEY,
            st=ST_KEY,
        )
    )
    value = payload["value"]

    assert value["first"]["inspectorKey"] == VM_KEY
    assert len(value["first"]["rows"]) == 4
    assert value["second"]["inspectorKey"] == ST_KEY
    assert value["second"]["name"] == "st-data"
    # The record is replaced, not appended to
    assert len(value["second"]["rows"]) == 1
    # Requirement 8.7: exactly one element carries the selection indicator
    assert value["selected"] == ["node2"]


@requires_node
def test_selection_indicator_carries_a_cue_other_than_colour():
    """Requirement 8.7: the activated element gets a class whose rule changes the stroke."""
    payload = run_app_js(
        dom_snippet(
            """
await loadInspector(state.lastGeneratedFile);
const stage = document.getElementById('viewer-stage');
stage.dispatchEvent({ type: 'click', target: childById(%%vm%%, 'vm-ellipse') });
await flush();
const group = groupByKey(%%vm%%);
return { className: group.className, panelHidden: dumpPanel().panelHidden };
""",
            vm=VM_KEY,
        )
    )
    assert "ch-selected" in payload["value"]["className"]

    # The stroke change itself lives in the stylesheet
    css = read_text(STYLE_CSS)
    rule_start = css.index(".ch-selected")
    rule = css[rule_start : css.index("}", rule_start)]
    assert "stroke" in rule


# ─── Viewer controls with the panel open (Requirements 8.6, 8.8) ──────────────


@requires_node
def test_zoom_and_change_filter_stay_operable_while_the_panel_is_open():
    """Requirement 8.6: opening the panel costs neither zoom nor the Change_Filter."""
    payload = run_app_js(
        dom_snippet(
            """
state.mode = 'terraform';
state.terraformPlanFiles = ['/plans/network.plan.json'];
await loadInspector(state.lastGeneratedFile);
const stage = document.getElementById('viewer-stage');
stage.dispatchEvent({ type: 'click', target: childById(%%vm%%, 'vm-ellipse') });
await flush();
const results = { opened: dumpPanel() };
zoomIn();
results.zoomedIn = dumpPanel();
zoomOut();
zoomReset();
results.reset = dumpPanel();
applyChangeSummary({
  counts: { create: 1, update: 2 },
  presentCategories: ['create', 'update'],
  notDisplayed: []
});
results.filtered = {
  panel: dumpPanel(),
  chipsHtml: document.getElementById('change-filter-chips').innerHTML,
  filterPanelHidden: document.getElementById('change-filter-panel').classList.contains('hidden')
};
return results;
""",
            vm=VM_KEY,
        )
    )
    value = payload["value"]

    assert value["opened"]["viewerZoom"] == 1
    assert value["zoomedIn"]["viewerZoom"] == 1.25
    assert value["zoomedIn"]["stageTransform"] == "scale(1.25)"
    assert value["reset"]["viewerZoom"] == 1
    # The panel stays open across every viewer operation
    assert all(value[step]["panelHidden"] is False for step in ("opened", "zoomedIn", "reset"))
    assert value["filtered"]["panel"]["panelHidden"] is False
    assert value["filtered"]["filterPanelHidden"] is False
    assert 'id="change-chip-create"' in value["filtered"]["chipsHtml"]


@requires_node
def test_layer_toggle_switches_the_layer_and_keeps_the_zoom_factor():
    """Requirement 8.8: the switch preserves the zoom factor across both layers."""
    payload = run_app_js(
        dom_snippet(
            """
await loadInspector(state.lastGeneratedFile);
zoomIn();
zoomIn();
const results = { svg: dumpPanel() };
results.toPng = { layer: toggleViewerLayer(), panel: dumpPanel() };
results.backToSvg = { layer: toggleViewerLayer(), panel: dumpPanel() };
return results;
"""
        )
    )
    value = payload["value"]
    zoom = value["svg"]["viewerZoom"]

    assert value["svg"]["viewerLayer"] == "svg"
    assert value["svg"]["layerToggleHidden"] is False
    assert "layer-active" in value["svg"]["stageClass"]

    assert value["toPng"]["layer"] == "png"
    assert "image-active" in value["toPng"]["panel"]["stageClass"]
    assert value["toPng"]["panel"]["viewerZoom"] == zoom
    assert value["toPng"]["panel"]["stageTransform"] == f"scale({zoom})"

    assert value["backToSvg"]["layer"] == "svg"
    assert value["backToSvg"]["panel"]["viewerZoom"] == zoom
    # The layer stays inlined across the switch, so switching back costs no read
    assert value["backToSvg"]["panel"]["hasLayer"] is True

# ─── Loading indicator and the unknown key (Requirements 8.10, 8.11) ──────────


#: The three panel messages, as `webui/app.js` spells them.
LOADING_MESSAGE = "Loading configuration…"
NO_RECORD_MESSAGE = "No configuration available for this resource"
REDACTED_MESSAGE = "Redacted attributes cannot be compared"


@requires_node
def test_loading_indicator_shows_until_the_record_resolves():
    """Requirement 8.10: the panel reports the read in flight, then the record."""
    payload = run_app_js(
        js(
            DUMP_HELPERS
            + """
state.lastGeneratedFile = %%png%%;
__installInspectorBridge(%%fixture%%);
await loadInspector(state.lastGeneratedFile);

// From here the bridge answers only when the test says so
__installDeferredInspectorBridge(%%fixture%%);
const stage = document.getElementById('viewer-stage');
stage.dispatchEvent({ type: 'click', target: childById(%%vm%%, 'vm-ellipse') });
await flush();
const pending = dumpPanel();
const resolved = __resolveInspectorBridge();
await flush();
return { pending: pending, loaded: dumpPanel(), resolved: resolved };
""",
            png=DIAGRAM_PNG,
            fixture=default_fixture(),
            vm=VM_KEY,
        )
    )
    value = payload["value"]

    # The panel is open and says so while the read is in flight
    assert value["pending"]["panelHidden"] is False
    assert value["pending"]["status"] == LOADING_MESSAGE
    assert value["pending"]["rows"] == []
    assert value["resolved"] == 1

    assert value["loaded"]["status"] == ""
    assert value["loaded"]["name"] == "vm-app"
    assert len(value["loaded"]["rows"]) == 4


@requires_node
def test_a_key_with_no_record_shows_the_documented_message():
    """Requirement 8.11: an unanswerable key gets the message, not an empty panel."""
    payload = run_app_js(
        dom_snippet(
            """
await loadInspector(state.lastGeneratedFile);
const stage = document.getElementById('viewer-stage');
stage.dispatchEvent({ type: 'click', target: childById(%%vm%%, 'vm-ellipse') });
await flush();
return dumpPanel();
""",
            fixture=default_fixture(records={}),
            vm=VM_KEY,
        )
    )
    value = payload["value"]

    assert value["panelHidden"] is False
    assert value["status"] == NO_RECORD_MESSAGE
    assert value["rows"] == []
    # The key is still on screen, so the Operator knows which element answered
    assert value["name"] == VM_KEY


# ─── Identity header, badge, legend and counts (5.5, 5.6, 5.11, 7.11, 7.12) ───


@requires_node
def test_identity_header_badge_and_legend_carry_the_flag_tokens():
    """Requirements 5.5, 5.6, 5.11, 7.11, 7.12: header, badge, legend and counts."""
    payload = run_app_js(
        dom_snippet(
            """
await loadInspector(state.lastGeneratedFile);
const stage = document.getElementById('viewer-stage');
stage.dispatchEvent({ type: 'click', target: childById(%%vm%%, 'vm-ellipse') });
await flush();
return dumpPanel();
""",
            vm=VM_KEY,
        )
    )
    value = payload["value"]

    # Requirement 5.5: name, type, resource group and address
    assert value["name"] == "vm-app"
    assert value["type"] == "Microsoft.Compute/virtualMachines"
    assert value["resourceGroup"] == "rg-app"
    assert value["address"] == "azurerm_linux_virtual_machine.app"
    assert value["addressHidden"] is False

    # Requirement 5.6: the Change_Category with the Flag_Token the diagram draws
    category = value["category"]
    assert category["hidden"] is False
    assert category["text"].strip() == "Update"
    assert [child["text"] for child in category["children"]] == ["~"]

    # Requirement 7.12: one legend entry per styled Attribute_State, flag included
    legend = value["legend"]
    assert legend["hidden"] is False
    assert [item["text"] for item in legend["children"]] == ["Added", "Removed", "Changed"]
    flags = [
        [child["text"] for child in item["children"] if child["className"] == "inspector-legend-flag"]
        for item in legend["children"]
    ]
    assert flags == [["+"], ["-"], ["~"]]

    # Requirement 5.11: per-state counts of the displayed rows
    counts = [item["text"].strip() for item in value["counts"]["children"]]
    assert counts == ["Added 1", "Removed 1", "Changed 1", "Unchanged 1"]

    # Requirement 7.11: the `changed` row labels both values
    changed = [row for row in value["rows"] if row["attrs"]["data-state"] == "changed"][0]
    cells = value_cells(changed)
    assert [child["text"] for child in cells[0]["children"]] == ["Before"]
    assert [child["text"] for child in cells[1]["children"]] == ["After"]
    assert [cells[0]["text"], cells[1]["text"]] == ['"Standard_B1s"', '"Standard_B2s"']


@requires_node
def test_badge_and_legend_are_hidden_for_a_record_without_a_change_category():
    """Requirements 10.3, 10.6: a Legacy_Mode record shows the configuration alone."""
    legacy = record_payload(VM_KEY, change_category=None)
    payload = run_app_js(
        dom_snippet(
            """
await loadInspector(state.lastGeneratedFile);
const stage = document.getElementById('viewer-stage');
stage.dispatchEvent({ type: 'click', target: childById(%%vm%%, 'vm-ellipse') });
await flush();
const legacy = dumpPanel();
renderInspectorRecord(%%diffRecord%%);
return { legacy: legacy, withCategory: dumpPanel() };
""",
            fixture=default_fixture(records={VM_KEY: legacy}),
            vm=VM_KEY,
            diffRecord=record_payload(VM_KEY),
        )
    )
    value = payload["value"]

    # No Change_Category: no badge, no legend, but every attribute row
    assert value["legacy"]["category"]["hidden"] is True
    assert value["legacy"]["category"]["text"] == ""
    assert value["legacy"]["legend"]["hidden"] is True
    assert len(value["legacy"]["rows"]) == 4
    # The same panel with a category shows both again
    assert value["withCategory"]["category"]["hidden"] is False
    assert value["withCategory"]["legend"]["hidden"] is False


# ─── Filters, counts and the copy control (5.9, 5.10, 5.11, 5.12) ─────────────


@requires_node
def test_filter_box_and_changed_only_toggle_hide_rows_and_update_the_counts():
    """Requirements 5.9, 5.10, 5.11: both controls hide rows and recount."""
    payload = run_app_js(
        dom_snippet(
            """
await loadInspector(state.lastGeneratedFile);
const stage = document.getElementById('viewer-stage');
stage.dispatchEvent({ type: 'click', target: childById(%%vm%%, 'vm-ellipse') });
await flush();
const results = { all: dumpPanel() };

document.getElementById('inspector-filter').value = 'tags';
results.filteredVisible = applyInspectorFilters();
results.filtered = dumpPanel();

document.getElementById('inspector-filter').value = '';
document.getElementById('chk-inspector-changed-only').checked = true;
results.changedOnlyVisible = applyInspectorFilters();
results.changedOnly = dumpPanel();

document.getElementById('inspector-filter').value = 'no-such-attribute';
results.emptyVisible = applyInspectorFilters();
results.empty = dumpPanel();
return results;
""",
            vm=VM_KEY,
        )
    )
    value = payload["value"]

    def visible_paths(panel):
        return [
            row["children"][1]["text"] for row in panel["rows"] if not row["hidden"]
        ]

    assert visible_paths(value["all"]) == ["location", "size", "tags.owner", "tags.legacy"]

    # Requirement 5.9: the filter box matches the Attribute_Path substring
    assert value["filteredVisible"] == 2
    assert visible_paths(value["filtered"]) == ["tags.owner", "tags.legacy"]
    assert [item["text"].strip() for item in value["filtered"]["counts"]["children"]] == [
        "Added 1",
        "Removed 1",
    ]

    # Requirement 5.10: the changed-only toggle drops the `unchanged` rows
    assert value["changedOnlyVisible"] == 3
    assert visible_paths(value["changedOnly"]) == ["size", "tags.owner", "tags.legacy"]
    assert [item["text"].strip() for item in value["changedOnly"]["counts"]["children"]] == [
        "Added 1",
        "Removed 1",
        "Changed 1",
    ]

    # Both filters compose, and no row surviving means no count either
    assert value["emptyVisible"] == 0
    assert visible_paths(value["empty"]) == []
    assert value["empty"]["counts"]["children"] == []
    # Rows are hidden, never dropped, so clearing a filter costs no second read
    assert len(value["empty"]["rows"]) == 4


@requires_node
def test_copy_control_writes_the_displayed_configuration_as_text():
    """Requirement 5.12: the copy control hands the visible configuration to the clipboard."""
    payload = run_app_js(
        dom_snippet(
            """
const copied = [];
navigator.clipboard = { writeText: function (text) { copied.push(text); return Promise.resolve(); } };

await loadInspector(state.lastGeneratedFile);
const stage = document.getElementById('viewer-stage');
stage.dispatchEvent({ type: 'click', target: childById(%%vm%%, 'vm-ellipse') });
await flush();
await copyInspectorConfiguration();

document.getElementById('chk-inspector-changed-only').checked = true;
applyInspectorFilters();
await copyInspectorConfiguration();
return { copied: copied };
""",
            vm=VM_KEY,
        )
    )
    full, changed_only = payload["value"]["copied"]

    assert full.splitlines() == [
        "vm-app",
        "Type: Microsoft.Compute/virtualMachines",
        "Resource group: rg-app",
        "Address: azurerm_linux_virtual_machine.app",
        "",
        "  location: westeurope",
        '~ size: "Standard_B1s" -> "Standard_B2s"',
        '+ tags.owner: "platform"',
        '- tags.legacy: "true"',
    ]
    # Only what is on screen is copied
    assert "location" not in changed_only
    assert '~ size: "Standard_B1s" -> "Standard_B2s"' in changed_only

    # A copy reports itself through the toast, so a failure is visible
    assert any(call.get("fn") == "showToast" for call in payload["calls"])


# ─── Truncation notice and redaction (Requirements 12.9, 11.8) ────────────────


@requires_node
def test_truncation_notice_reports_the_reasons_the_omitted_count_and_the_bounds():
    """Requirement 12.9: the panel says what was cut, how much, and against which bound."""
    truncated = record_payload(VM_KEY, omitted=7, truncations=["value", "rows"])
    payload = run_app_js(
        dom_snippet(
            """
await loadInspector(state.lastGeneratedFile);
const stage = document.getElementById('viewer-stage');
stage.dispatchEvent({ type: 'click', target: childById(%%vm%%, 'vm-ellipse') });
await flush();
const truncated = dumpPanel();
renderInspectorRecord(%%whole%%);
return { truncated: truncated, whole: dumpPanel() };
""",
            fixture=default_fixture(records={VM_KEY: truncated}),
            vm=VM_KEY,
            whole=record_payload(VM_KEY),
        )
    )
    value = payload["value"]

    notice = value["truncated"]["truncation"]
    assert notice["hidden"] is False
    assert "Truncated by: value, rows." in notice["text"]
    assert "7 attributes omitted." in notice["text"]
    bounds = bounds_payload()
    assert (
        f"Limits: {bounds['maxRows']} rows, {bounds['maxScalarChars']} characters, "
        f"depth {bounds['maxDepth']}." in notice["text"]
    )
    assert bounds["maxRows"] == MAX_ATTRIBUTE_ROWS

    # A record inside every bound shows no notice at all
    assert value["whole"]["truncation"]["hidden"] is True
    assert value["whole"]["truncation"]["text"] == ""


@requires_node
def test_a_doubly_redacted_entry_reports_that_it_cannot_be_compared():
    """Requirement 11.8: the panel says why the two phases cannot be compared."""
    redacted = record_payload(
        VM_KEY,
        entries=[
            AttributeEntry(
                path="admin_password",
                state=UNCHANGED_STATE,
                before=REDACTION_LITERAL,
                after=REDACTION_LITERAL,
            ),
            AttributeEntry(path="location", state=UNCHANGED_STATE, before="westeurope", after="westeurope"),
        ],
    )
    payload = run_app_js(
        dom_snippet(
            """
await loadInspector(state.lastGeneratedFile);
const stage = document.getElementById('viewer-stage');
stage.dispatchEvent({ type: 'click', target: childById(%%vm%%, 'vm-ellipse') });
await flush();
const redacted = dumpPanel();
renderInspectorRecord(%%plain%%);
return { redacted: redacted, plain: dumpPanel() };
""",
            fixture=default_fixture(records={VM_KEY: redacted}),
            vm=VM_KEY,
            plain=record_payload(VM_KEY),
        )
    )
    value = payload["value"]

    assert value["redacted"]["status"] == REDACTED_MESSAGE
    # The row is still shown, with the Redaction_Literal verbatim on both sides
    row = value["redacted"]["rows"][0]
    assert row["children"][1]["text"] == "admin_password"
    assert value_cells(row)[0]["text"] == REDACTION_LITERAL
    # A record with nothing redacted carries no notice
    assert value["plain"]["status"] == ""


# ─── Missing payload and missing layer (Requirements 13.1, 13.2) ──────────────


@requires_node
def test_a_run_without_inspector_artifacts_keeps_the_plain_png_viewer():
    """Requirements 13.1, 13.2: no payload and no layer cost the viewer nothing."""
    payload = run_app_js(
        js(
            DUMP_HELPERS
            + """
state.lastGeneratedFile = %%png%%;

// Neither artifact beside the diagram (Requirement 13.1)
__installNullInspectorBridge();
const index = await loadInspector(state.lastGeneratedFile);
const missingBoth = dumpPanel();
zoomIn();
const zoomed = dumpPanel();
zoomReset();

// A payload but no Interaction_Layer (Requirement 13.2)
__installInspectorBridge(%%layerless%%);
await loadInspector(state.lastGeneratedFile);
const missingLayer = dumpPanel();
// The layer toggle stays inert without a layer to switch to
const toggled = toggleViewerLayer();
return {
  index: index,
  missingBoth: missingBoth,
  zoomed: zoomed,
  missingLayer: missingLayer,
  toggled: toggled,
  layerRoot: !!interactionLayerRoot(),
};
""",
            png=DIAGRAM_PNG,
            layerless={"layer": None, "index": index_payload(DEFAULT_KEYS), "records": {}},
        )
    )
    value = payload["value"]

    assert value["index"] is None
    for step in ("missingBoth", "missingLayer"):
        assert value[step]["hasLayer"] is False
        assert value[step]["layerToggleHidden"] is True
        assert value[step]["viewerLayer"] == "png"
        assert "image-active" in value[step]["stageClass"]
        # No element activation is offered, and the panel stays shut
        assert value[step]["panelHidden"] is True

    # Pan, zoom and the Change_Filter keep the behaviour of the preceding release
    assert value["zoomed"]["viewerZoom"] == 1.25
    assert value["zoomed"]["stageTransform"] == "scale(1.25)"
    assert value["toggled"] == "png"
    assert value["layerRoot"] is False


# ─── State cleared between runs (Requirement 13.7) ────────────────────────────


SECOND_PNG = "/out/azure_resources_20260726_150011/azure_resources_20260726_150011.png"


@requires_node
def test_a_new_generation_run_clears_the_previous_inspector_state():
    """Requirement 13.7: index, key, layer, panel and filters go with the old diagram."""
    payload = run_app_js(
        js(
            DUMP_HELPERS
            + """
state.mode = 'terraform';
state.terraformMainFiles = [];
state.terraformVarFiles = [];
state.terraformPlanFiles = ['/plans/network.plan.json'];

__installInspectorBridge(%%fixture%%);
window.pywebview.api.start_generation = function () {
  return Promise.resolve({ success: true, file: %%first%% });
};
await generate();
const stage = document.getElementById('viewer-stage');
stage.dispatchEvent({ type: 'click', target: childById(%%vm%%, 'vm-ellipse') });
await flush();
document.getElementById('inspector-filter').value = 'tags';
document.getElementById('chk-inspector-changed-only').checked = true;
applyInspectorFilters();
const afterFirst = { panel: dumpPanel(), hasIndex: !!state.inspectorIndex };

// The second run draws a different element set and ships no Inspector artifacts
__installNullInspectorBridge();
window.pywebview.api.start_generation = function () {
  return Promise.resolve({ success: true, file: %%second%% });
};
await generate();
const afterSecond = {
  panel: dumpPanel(),
  hasIndex: !!state.inspectorIndex,
  filter: document.getElementById('inspector-filter').value,
  changedOnly: document.getElementById('chk-inspector-changed-only').checked,
  file: state.lastGeneratedFile,
};
return { afterFirst: afterFirst, afterSecond: afterSecond };
""",
            fixture=default_fixture(),
            first=DIAGRAM_PNG,
            second=SECOND_PNG,
            vm=VM_KEY,
        )
    )
    value = payload["value"]

    assert value["afterFirst"]["hasIndex"] is True
    assert value["afterFirst"]["panel"]["inspectorKey"] == VM_KEY
    assert value["afterFirst"]["panel"]["hasLayer"] is True

    second = value["afterSecond"]
    assert second["file"] == SECOND_PNG
    assert second["hasIndex"] is False
    assert second["panel"]["panelHidden"] is True
    assert second["panel"]["inspectorKey"] is None
    assert second["panel"]["rows"] == []
    assert second["panel"]["name"] == ""
    assert second["panel"]["hasLayer"] is False
    assert second["panel"]["layerToggleHidden"] is True
    # The filters describe a record that is gone, so they reset with it
    assert second["filter"] == ""
    assert second["changedOnly"] is False


# ─── Nested container resolution (Requirements 9.2, 9.3, 9.4, 9.8) ────────────


@requires_node
def test_nested_activation_resolves_to_the_innermost_element():
    """Requirements 9.2, 9.3, 9.4, 9.8: subnet inside vnet, node inside subnet."""
    payload = run_app_js(
        dom_snippet(
            """
await loadInspector(state.lastGeneratedFile);
const stage = document.getElementById('viewer-stage');
const results = {};

// A point of the vnet cluster outside every subnet it contains
stage.dispatchEvent({ type: 'click', target: childById(%%vnet%%, 'vnet-poly') });
await flush();
results.vnet = dumpPanel();

// A point inside the subnet cluster, which lies inside the vnet
closeInspectorPanel();
stage.dispatchEvent({ type: 'click', target: childById(%%subnet%%, 'subnet-poly') });
await flush();
results.subnet = dumpPanel();

// A node inside the subnet, which lies inside the vnet
closeInspectorPanel();
stage.dispatchEvent({ type: 'click', target: childById(%%vm%%, 'vm-ellipse') });
await flush();
results.node = dumpPanel();

// The <title> of every activatable element, in document order
results.keys = Array.prototype.map.call(
  interactionLayerRoot().querySelectorAll('g.node, g.cluster'),
  function (g) { return g.querySelectorAll('title')[0].textContent; }
);
results.hitRects = interactionLayerRoot().querySelectorAll('rect.ch-hit').length;
return results;
""",
            fixture=default_fixture(layer=NESTED_LAYER_SVG),
            vnet=VNET_KEY,
            subnet=SUBNET_KEY,
            vm=VM_KEY,
        )
    )
    value = payload["value"]

    # Requirement 9.2: the vnet cluster answers with the vnet
    assert value["vnet"]["inspectorKey"] == VNET_KEY
    assert value["vnet"]["name"] == "vnet-hub"
    # Requirements 9.3, 9.4: the enclosed subnet answers with the subnet
    assert value["subnet"]["inspectorKey"] == SUBNET_KEY
    assert value["subnet"]["name"] == "snet-app"
    # Requirement 9.8: the node inside the subnet answers with the node
    assert value["node"]["inspectorKey"] == VM_KEY
    assert value["node"]["name"] == "vm-app"

    assert value["keys"] == [VNET_KEY, SUBNET_KEY, VM_KEY]
    # One transparent hit rect per node; a cluster relies on its filled polygon
    assert value["hitRects"] == 1
