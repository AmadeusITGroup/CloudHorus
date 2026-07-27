"""Inspector_Bridge tests: the three payload readers and the toggle marshalling.

The readers are the host-process half of the Inspector: they derive the sidecar
paths from the PNG path of a run, read the Inspector_Index once per run, and seek
one Inspector_Record out of the JSONL without reading its neighbours. Every body
returns a value or `None` and raises nothing, because a raise crosses into
pywebview and takes the viewer with it.

Requirements: 2.5, 2.8, 12.1, 13.1, 13.2, 13.3, 13.4, 13.5, 13.6
"""

import json
import logging
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import cloudhorus_webui  # noqa: E402
from cloudhorus_webui import CloudHorusAPI  # noqa: E402

DIAGRAM = "azure_resources_20260726_145233.png"

RECORDS = [
    {
        "key": "api-web-rg-app",
        "kind": "node",
        "name": "api-web",
        "resourceType": "Microsoft.Web/sites",
        "resourceGroup": "rg-app",
        "address": "module.app.azurerm_linux_web_app.api",
        "changeCategory": "update",
        "replacement": False,
        "attributes": [
            {"path": "https_only", "state": "changed", "before": "false", "after": "true"},
            {"path": "tags.owner", "state": "removed", "before": "platförm ✓"},
        ],
        "omittedAttributes": 0,
        "truncations": [],
    },
    {
        "key": "cluster_vnetcore-vnet",
        "kind": "virtualNetwork",
        "name": "core-vnet",
        "resourceType": "Microsoft.Network/virtualNetworks",
        "resourceGroup": "rg-net",
        "address": None,
        "changeCategory": None,
        "replacement": False,
        "attributes": [
            {"path": "address_space.0", "state": "unchanged", "before": "10.0.0.0/16", "after": "10.0.0.0/16"},
        ],
        "omittedAttributes": 0,
        "truncations": [],
    },
]


@pytest.fixture
def api():
    return CloudHorusAPI()


def write_payload(tmp_path, records=RECORDS, png_name=DIAGRAM, records_name=None):
    """Write a PNG plus a valid Inspector_Payload beside it, returning the paths."""
    png_path = tmp_path / png_name
    png_path.write_bytes(b"")
    stem = png_path.stem

    jsonl_name = records_name or (stem + cloudhorus_webui._inspector_records_suffix())
    jsonl_path = tmp_path / jsonl_name

    keys = {}
    blob = b""
    for record in records:
        line = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
        keys[record["key"]] = {
            "offset": len(blob),
            "length": len(line) - 1,  # the newline is a separator, not payload
            "kind": record["kind"],
        }
        blob += line
    jsonl_path.write_bytes(blob)

    index = {
        "schemaVersion": 1,
        "diagram": png_name,
        "records": jsonl_name,
        "recordCount": len(records),
        "keyCollisions": 0,
        "keys": keys,
        "attributeStyles": {
            "added": {"color": "#107C10", "flag": "+", "label": "Added"},
            "removed": {"color": "#D13438", "flag": "-", "label": "Removed"},
            "changed": {"color": "#0078D4", "flag": "~", "label": "Changed"},
        },
        "bounds": {"maxRows": 500, "maxScalarChars": 2048, "maxDepth": 12},
    }
    index_path = tmp_path / (stem + cloudhorus_webui._inspector_index_suffix())
    index_path.write_text(json.dumps(index), encoding="utf-8")
    return str(png_path), index_path, jsonl_path


# ─── get_interaction_layer ────────────────────────────────────────────────


def test_get_interaction_layer_returns_the_svg_beside_the_png(api, tmp_path):
    """Requirement 13.2 (positive side): the layer is `<diagram>.svg` in the run folder."""
    png_path = tmp_path / DIAGRAM
    png_path.write_bytes(b"")
    svg = '<svg xmlns="http://www.w3.org/2000/svg"><g class="node"><title>api-web-rg-app</title></g></svg>'
    (tmp_path / (png_path.stem + cloudhorus_webui._interaction_layer_suffix())).write_text(svg, encoding="utf-8")

    assert api.get_interaction_layer(str(png_path)) == svg


def test_get_interaction_layer_returns_none_without_a_layer(api, tmp_path):
    """Requirement 13.2: an Inspector_Mode-off run writes no layer, which is not an error."""
    png_path = tmp_path / DIAGRAM
    png_path.write_bytes(b"")

    assert api.get_interaction_layer(str(png_path)) is None


def test_get_interaction_layer_returns_none_for_undecodable_text(api, tmp_path):
    """Requirement 13.6: a UnicodeDecodeError is contained, not raised into pywebview."""
    png_path = tmp_path / DIAGRAM
    png_path.write_bytes(b"")
    (tmp_path / (png_path.stem + cloudhorus_webui._interaction_layer_suffix())).write_bytes(b"<svg>\xff\xfe</svg>")

    assert api.get_interaction_layer(str(png_path)) is None


def test_get_interaction_layer_returns_none_for_a_directory_in_the_layer_slot(api, tmp_path):
    """An OSError from the read path is contained the same way (Requirement 13.6)."""
    png_path = tmp_path / DIAGRAM
    png_path.write_bytes(b"")
    (tmp_path / (png_path.stem + cloudhorus_webui._interaction_layer_suffix())).mkdir()

    assert api.get_interaction_layer(str(png_path)) is None


# ─── read_inspector_index ─────────────────────────────────────────────────


def test_read_inspector_index_reads_the_index_beside_the_png(api, tmp_path):
    """Requirement 12.1: the index carries the key locations a record read seeks with."""
    png_path, _, _ = write_payload(tmp_path)

    index = api.read_inspector_index(png_path)

    assert index["recordCount"] == 2
    assert index["keys"]["api-web-rg-app"]["kind"] == "node"
    assert index["attributeStyles"]["changed"]["flag"] == "~"
    assert index["bounds"]["maxRows"] == 500


def test_read_inspector_index_returns_none_without_a_payload(api, tmp_path):
    """Requirement 13.1: no payload beside the diagram is a normal outcome."""
    png_path = tmp_path / DIAGRAM
    png_path.write_bytes(b"")

    assert api.read_inspector_index(str(png_path)) is None


def test_read_inspector_index_logs_the_path_at_warning_level_for_invalid_json(api, tmp_path, caplog):
    """Requirement 13.3: invalid JSON returns None with the file path logged as a warning."""
    png_path, index_path, _ = write_payload(tmp_path)
    index_path.write_text("{ not json", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="cloudhorus.webui"):
        assert api.read_inspector_index(png_path) is None

    assert any(str(index_path) in record.getMessage() for record in caplog.records)
    assert {record.levelno for record in caplog.records} == {logging.WARNING}


def test_read_inspector_index_returns_none_for_a_non_object_payload(api, tmp_path):
    png_path, index_path, _ = write_payload(tmp_path)
    index_path.write_text("[1, 2, 3]", encoding="utf-8")

    assert api.read_inspector_index(png_path) is None


def test_read_inspector_index_is_cached_per_resolved_path(api, tmp_path):
    """Requirement 12.1: activating many elements of one run reads the index once."""
    png_path, index_path, _ = write_payload(tmp_path)

    first = api.read_inspector_index(png_path)
    index_path.unlink()
    second = api.read_inspector_index(png_path)

    assert second is first


# ─── read_inspector_record ────────────────────────────────────────────────


def test_read_inspector_record_returns_exactly_the_requested_record(api, tmp_path):
    """Requirement 12.1: one read yields one record, not the whole payload."""
    png_path, _, _ = write_payload(tmp_path)

    node = api.read_inspector_record(png_path, "api-web-rg-app")
    cluster = api.read_inspector_record(png_path, "cluster_vnetcore-vnet")

    assert node == RECORDS[0]
    assert cluster == RECORDS[1]
    # Multi-byte characters survive the byte-offset seek intact
    assert node["attributes"][1]["before"] == "platförm ✓"


def test_read_inspector_record_never_reads_past_the_indexed_length(api, tmp_path, monkeypatch):
    """Requirement 13.5: the reader asks for exactly the indexed byte count."""
    png_path, index_path, _ = write_payload(tmp_path)
    index = json.loads(index_path.read_text(encoding="utf-8"))
    expected = index["keys"]["api-web-rg-app"]["length"]

    requested = []
    real_open = open

    def spy_open(path, mode="r", *args, **kwargs):
        handle = real_open(path, mode, *args, **kwargs)
        if "b" in mode:
            real_read = handle.read

            def read(size=-1):
                requested.append(size)
                return real_read(size)

            handle.read = read  # type: ignore[method-assign]
        return handle

    monkeypatch.setattr("builtins.open", spy_open)

    assert api.read_inspector_record(png_path, "api-web-rg-app") == RECORDS[0]
    assert requested == [expected]


def test_read_inspector_record_returns_none_for_an_unknown_key(api, tmp_path):
    """Requirement 13.4: no index entry, so no record and no file read."""
    png_path, _, _ = write_payload(tmp_path)

    assert api.read_inspector_record(png_path, "cluster_subnetghost") is None


def test_read_inspector_record_returns_none_for_an_offset_past_eof(api, tmp_path, caplog):
    """Requirement 13.5: an offset beyond the file is a debug log and no record."""
    png_path, index_path, jsonl_path = write_payload(tmp_path)
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["keys"]["api-web-rg-app"]["offset"] = jsonl_path.stat().st_size + 4096
    index_path.write_text(json.dumps(index), encoding="utf-8")

    with caplog.at_level(logging.DEBUG, logger="cloudhorus.webui"):
        assert api.read_inspector_record(png_path, "api-web-rg-app") is None

    assert caplog.records
    assert max(record.levelno for record in caplog.records) <= logging.DEBUG


def test_read_inspector_record_returns_none_for_a_truncated_line(api, tmp_path):
    """Requirement 13.5: a line the writer never finished yields no record."""
    png_path, index_path, jsonl_path = write_payload(tmp_path)
    index = json.loads(index_path.read_text(encoding="utf-8"))
    entry = index["keys"]["api-web-rg-app"]
    blob = jsonl_path.read_bytes()
    # Keep the indexed length, cut the stored bytes in half
    jsonl_path.write_bytes(blob[: entry["offset"] + entry["length"] // 2])

    assert api.read_inspector_record(png_path, "api-web-rg-app") is None


def test_read_inspector_record_returns_none_for_invalid_record_json(api, tmp_path):
    png_path, index_path, jsonl_path = write_payload(tmp_path)
    index = json.loads(index_path.read_text(encoding="utf-8"))
    entry = index["keys"]["api-web-rg-app"]
    blob = bytearray(jsonl_path.read_bytes())
    blob[entry["offset"] : entry["offset"] + entry["length"]] = b"{" + b"x" * (entry["length"] - 1)
    jsonl_path.write_bytes(bytes(blob))

    assert api.read_inspector_record(png_path, "api-web-rg-app") is None


def test_read_inspector_record_returns_none_for_non_utf8_bytes(api, tmp_path):
    """Requirement 13.6: a UnicodeDecodeError inside the record read is contained."""
    png_path, index_path, jsonl_path = write_payload(tmp_path)
    index = json.loads(index_path.read_text(encoding="utf-8"))
    entry = index["keys"]["api-web-rg-app"]
    blob = bytearray(jsonl_path.read_bytes())
    blob[entry["offset"] : entry["offset"] + entry["length"]] = b"\xff\xfe" * (entry["length"] // 2)
    jsonl_path.write_bytes(bytes(blob))

    assert api.read_inspector_record(png_path, "api-web-rg-app") is None


def test_read_inspector_record_returns_none_without_a_payload(api, tmp_path):
    """Requirement 13.1: no index, so no record, and no exception."""
    png_path = tmp_path / DIAGRAM
    png_path.write_bytes(b"")

    assert api.read_inspector_record(str(png_path), "api-web-rg-app") is None


def test_read_inspector_record_returns_none_when_the_jsonl_is_missing(api, tmp_path):
    png_path, _, jsonl_path = write_payload(tmp_path)
    jsonl_path.unlink()

    assert api.read_inspector_record(png_path, "api-web-rg-app") is None


def test_read_inspector_record_returns_none_for_a_malformed_index_entry(api, tmp_path):
    """A location the index cannot describe is no record, not an exception."""
    png_path, index_path, _ = write_payload(tmp_path)
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["keys"]["api-web-rg-app"] = {"offset": "start", "length": None, "kind": "node"}
    index_path.write_text(json.dumps(index), encoding="utf-8")

    assert api.read_inspector_record(png_path, "api-web-rg-app") is None


def test_read_inspector_record_rejects_an_index_naming_a_file_outside_the_run_folder(api, tmp_path, caplog):
    """An absolute `records` entry is untrusted input, not a path to honour.

    The Inspector_Index sits next to the PNG, so its `records` entry can name any
    file the user can read. Honouring it would decode those bytes into the panel,
    an arbitrary-file read. The reader stays in the diagram's own folder, logs the
    rejection with the path, and returns `None` (Requirement 13.6).
    """
    folder = tmp_path / "run"
    folder.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / ("diagram" + cloudhorus_webui._inspector_records_suffix())
    planted = json.dumps({"key": "api-web-rg-app", "kind": "node", "name": "planted-outside"})
    secret.write_text(planted + "\n", encoding="utf-8")

    png_path, index_path, _ = write_payload(folder)
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["records"] = str(secret)
    index["keys"]["api-web-rg-app"] = {"offset": 0, "length": len(planted), "kind": "node"}
    index_path.write_text(json.dumps(index), encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="cloudhorus.webui"):
        assert api.read_inspector_record(png_path, "api-web-rg-app") is None

    assert any(str(secret) in record.getMessage() for record in caplog.records)
    assert any(record.levelno == logging.WARNING for record in caplog.records)


def test_read_inspector_record_still_reads_a_same_folder_records_entry(api, tmp_path):
    """The legitimate case is untouched: the writer records a basename beside the PNG."""
    png_path, index_path, _ = write_payload(tmp_path, records_name="renamed.inspector.jsonl")

    assert json.loads(index_path.read_text(encoding="utf-8"))["records"] == "renamed.inspector.jsonl"
    assert api.read_inspector_record(png_path, "api-web-rg-app") == RECORDS[0]


def test_read_inspector_record_rejects_a_records_symlink_pointing_out_of_the_folder(api, tmp_path, caplog):
    """A name inside the folder that links out of it resolves outside and is refused."""
    folder = tmp_path / "run"
    folder.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secrets.jsonl"
    planted = json.dumps({"key": "api-web-rg-app", "kind": "node", "name": "planted-outside"})
    secret.write_text(planted + "\n", encoding="utf-8")

    png_path, index_path, jsonl_path = write_payload(folder)
    jsonl_path.unlink()
    jsonl_path.symlink_to(secret)
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["keys"]["api-web-rg-app"] = {"offset": 0, "length": len(planted), "kind": "node"}
    index_path.write_text(json.dumps(index), encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="cloudhorus.webui"):
        assert api.read_inspector_record(png_path, "api-web-rg-app") is None

    assert any(str(jsonl_path) in record.getMessage() for record in caplog.records)


def test_bridge_reads_tolerate_a_nonsense_diagram_path(api):
    """Requirement 13.6: no read raises, whatever the front end hands over."""
    for png_path in ("", "   ", None, 17):
        assert api.get_interaction_layer(png_path) is None
        assert api.read_inspector_index(png_path) is None
        assert api.read_inspector_record(png_path, "api-web-rg-app") is None


# ─── _build_command toggle marshalling ────────────────────────────────────


def base_args(**overrides):
    """Argument payload shaped like the one webui/app.js posts."""
    args = {
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


MODE_PAYLOADS = {
    "live": base_args(mode="live", tenants="t1", subscriptions="s1", resourcegroups="rg-app"),
    "bicep": base_args(mode="bicep", bicepFiles=["/stacks/main.bicep"], parametersFiles=["/stacks/main.params.json"]),
    "terraform-source": base_args(
        mode="terraform",
        terraformRootDirs=["/stacks/app"],
        terraformVarFiles=["/stacks/app/app.tfvars"],
    ),
    "terraform-json": base_args(mode="terraform", terraformJsonFiles=["/plans/app.plan.json"]),
    "plan-diff": base_args(
        mode="terraform",
        terraformJsonFiles=["/plans/app.plan.json"],
        changeTypes=["create", "delete"],
    ),
}


@pytest.mark.parametrize("mode", sorted(MODE_PAYLOADS))
def test_build_command_appends_the_inspector_flag_in_every_mode(api, mode):
    """Requirements 2.5, 2.8: the toggle marshals the same way in every input mode."""
    args = MODE_PAYLOADS[mode]
    off = api._build_command(args)
    on = api._build_command(dict(args, interactiveInspector=True))

    assert "--interactiveInspector" not in off
    assert on[on.index("--interactiveInspector") + 1] == "True"
    # The flag is the only difference: no other argument of the payload changes
    assert on == off + ["--interactiveInspector", "True"]


@pytest.mark.parametrize("mode", sorted(MODE_PAYLOADS))
def test_build_command_omits_the_inspector_flag_when_the_toggle_is_off(api, mode):
    """The CLI default is False, so an off toggle keeps the flag off the line."""
    args = MODE_PAYLOADS[mode]
    baseline = api._build_command(args)

    for value in (False, None, ""):
        assert api._build_command(dict(args, interactiveInspector=value)) == baseline


def test_build_command_inspector_flag_leaves_change_type_marshalling_intact(api):
    """Requirement 2.8: Inspector_Mode and the Change_Filter stay independent."""
    cmd = api._build_command(dict(MODE_PAYLOADS["plan-diff"], interactiveInspector=True))

    assert cmd[cmd.index("--changeTypes") + 1 : cmd.index("--changeTypes") + 3] == ["create", "delete"]
    assert cmd[cmd.index("--terraformJsonFiles") + 1] == "/plans/app.plan.json"
    assert "--interactiveInspector" in cmd
