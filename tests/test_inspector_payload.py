"""Payload-layer tests: the Inspector_Payload on disk and the Interaction_Layer icons.

Feature: interactive-resource-inspector

This file owns the write half of the Inspector: `write_inspector_payload` (the
JSONL plus its byte-offset index), the collector that feeds it, and
`embed_svg_icons` / `write_svg_with_embedded_icons`, which strip the absolute
filesystem paths Graphviz writes into the Interaction_Layer.

- Property 10 (task 3.4) asserts the payload round trip over `inspector_records()`.
- Property 14 (task 3.5) asserts that no attribute tree and no payload byte
  sequence produces an unhandled failure, over `hostile_trees()` and
  `payload_bytes()`.
- The edge-case and SVG units of task 3.6 pin Requirements 3.7, 5.8, 13.3 and
  13.8 at this layer, asserted with plain `xml.etree`, no Node involved.

Requirements: 3.7, 5.8, 12.8, 13.3, 13.6, 13.8, 13.9, 13.10, 13.11, 14.10, 14.14
"""

import json
import logging
import os
import sys
import tempfile
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from typing import Any, Dict, List, Tuple

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _path in (PROJECT_ROOT, os.path.join(PROJECT_ROOT, "src"), os.path.dirname(os.path.abspath(__file__))):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import cloudhorus_webui  # noqa: E402
from cloudhorus_webui import CloudHorusAPI  # noqa: E402
from core.inspector import (  # noqa: E402
    ATTRIBUTE_STYLES,
    ICON_ID_PREFIX,
    INSPECTOR_INDEX_SUFFIX,
    INSPECTOR_RECORDS_SUFFIX,
    INSPECTOR_SCHEMA_VERSION,
    SVG_NAMESPACE,
    UNCHANGED_STATE,
    VNET_KIND,
    XLINK_NAMESPACE,
    AttributeEntry,
    InspectorCollector,
    InspectorIdentity,
    InspectorPayload,
    InspectorRecord,
    attribute_styles_payload,
    bounds_payload,
    build_record,
    embed_svg_icons,
    write_inspector_payload,
    write_svg_with_embedded_icons,
)
from strategies.inspector_trees import (  # noqa: E402
    hostile_trees,
    inspector_records,
    payload_bytes,
    svg_documents,
)

DIAGRAM_STEM = "azure_resources_20260726_145233"

#: Bytes the fake icon reader returns, so every data URI in a test is deterministic.
ICON_BYTES = b"\x89PNG\r\n\x1a\ncloudhorus-icon"


# ─── Helpers ──────────────────────────────────────────────────────────────────


class _RecordCollector(logging.Handler):
    """Collect the messages the singleton logger emits, which does not propagate."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: List[Tuple[int, str]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append((record.levelno, record.getMessage()))

    def warnings(self) -> List[str]:
        return [message for levelno, message in self.records if levelno == logging.WARNING]


@contextmanager
def captured_logs():
    """Attach a collecting handler to the singleton logger for the block."""
    logger = logging.getLogger("SingletonLogger")
    handler = _RecordCollector()
    previous_level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


def _write(payload: InspectorPayload, folder: str, stem: str = DIAGRAM_STEM):
    """Write one payload into ``folder`` and return ``(index, index_path, blob)``."""
    output_filename = os.path.join(folder, stem)
    index_path = write_inspector_payload(payload, output_filename)
    if index_path is None:
        return None, None, b""
    with open(index_path, "r", encoding="utf-8") as handle:
        index = json.load(handle)
    with open(f"{output_filename}{INSPECTOR_RECORDS_SUFFIX}", "rb") as handle:
        blob = handle.read()
    return index, index_path, blob


def _line_offsets(blob: bytes) -> Dict[int, bytes]:
    """Map the byte offset of every JSONL line to the line without its newline."""
    offsets: Dict[int, bytes] = {}
    cursor = 0
    for line in blob.split(b"\n")[:-1]:
        offsets[cursor] = line
        cursor += len(line) + 1
    return offsets


def _fake_icon_reader(_href: str) -> bytes:
    """Return fixed icon bytes for any href, so no test touches the icons folder."""
    return ICON_BYTES


def _images(root: ET.Element) -> List[ET.Element]:
    return [element for element in root.iter() if element.tag == f"{{{SVG_NAMESPACE}}}image"]


def _elements(root: ET.Element, local_name: str) -> List[ET.Element]:
    return [
        element
        for element in root.iter()
        if isinstance(element.tag, str) and element.tag.rsplit("}", 1)[-1] == local_name
    ]


def _icon_group(element: ET.Element) -> Tuple[str, ...]:
    """The ``(href, width, height, preserveAspectRatio)`` group key of one ``<image>``."""
    href = element.get(f"{{{XLINK_NAMESPACE}}}href") or element.get("href") or ""
    return (href,) + tuple(element.get(name) or "" for name in ("width", "height", "preserveAspectRatio"))


def _titles(svg_text: str) -> List[str]:
    """Every ``<title>`` text of an SVG, in document order: the Inspector_Keys."""
    return [(element.text or "") for element in _elements(ET.fromstring(svg_text), "title")]


def _write_reader_payload(folder: str, records_bytes: bytes, index: Dict[str, Any]) -> str:
    """Write a PNG plus a (possibly damaged) payload beside it, returning the PNG path."""
    png_path = os.path.join(folder, "diagram.png")
    with open(png_path, "wb") as handle:
        handle.write(b"")
    with open(os.path.join(folder, f"diagram{INSPECTOR_RECORDS_SUFFIX}"), "wb") as handle:
        handle.write(records_bytes)
    with open(os.path.join(folder, f"diagram{INSPECTOR_INDEX_SUFFIX}"), "w", encoding="utf-8") as handle:
        json.dump(index, handle, ensure_ascii=False)
    return png_path


# ─── Property 10: Payload round trip ──────────────────────────────────────────
# Feature: interactive-resource-inspector, Property 10: For any set of
# Inspector_Records, writing the Inspector_Payload and reading every record back
# through the Inspector_Index yields a record set equal to the set written,
# including records whose values hold multi-byte characters, embedded newlines
# and quotation marks, and the recorded byte offsets and lengths address exactly
# the line of their key.
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
@given(
    records=st.lists(
        inspector_records(),
        min_size=1,
        max_size=6,
        unique_by=lambda record: record.key,
    )
)
def test_property_payload_round_trip(records):
    """Property 10: Payload round trip.

    The JSONL plus its offset index is a lossless carrier: every record written
    comes back equal through its indexed offset and length, and each indexed
    location addresses exactly the line of its key — which is what makes the
    single-record read of Requirement 12.1 a seek rather than a scan
    (Requirement 12.8).

    **Validates: Requirements 12.8, 14.10**
    """
    with tempfile.TemporaryDirectory() as folder:
        index, index_path, blob = _write(InspectorPayload(records=list(records)), folder)

        assert index_path == os.path.join(folder, f"{DIAGRAM_STEM}{INSPECTOR_INDEX_SUFFIX}")
        assert index["schemaVersion"] == INSPECTOR_SCHEMA_VERSION
        assert index["records"] == f"{DIAGRAM_STEM}{INSPECTOR_RECORDS_SUFFIX}"
        assert index["diagram"] == f"{DIAGRAM_STEM}.png"
        assert index["recordCount"] == len(records)
        assert index["keyCollisions"] == 0
        assert index["attributeStyles"] == attribute_styles_payload()
        assert index["bounds"] == bounds_payload()

        # The index describes exactly the records written, no more and no fewer.
        assert set(index["keys"]) == {record.key for record in records}

        line_at = _line_offsets(blob)
        assert len(line_at) == len(records)

        for record in records:
            entry = index["keys"][record.key]
            offset, length = entry["offset"], entry["length"]

            # The indexed location addresses exactly one whole line, newline excluded.
            assert offset in line_at
            raw = blob[offset : offset + length]
            assert raw == line_at[offset]
            assert blob[offset + length : offset + length + 1] == b"\n"
            assert b"\n" not in raw
            assert entry["kind"] == record.kind

            # The round trip: the record read back equals the record written.
            assert InspectorRecord.from_payload(json.loads(raw.decode("utf-8"))) == record


# ─── Property 14: No unhandled failure for any attribute tree ─────────────────
# Feature: interactive-resource-inspector, Property 14: For any value supplied as
# an attribute tree — including non-string map keys, subtrees that repeat an
# enclosing subtree, values the JSON serializer cannot represent, nesting beyond
# the Depth_Bound, and values that are not containers at all — the Inspector
# either produces an Inspector_Payload or reports the failure as a logged
# warning, and raises no unhandled exception; and for any byte sequence supplied
# as an Inspector_Payload file and any string supplied as an Inspector_Key, the
# Inspector_Bridge returns one Inspector_Record or nothing and raises no
# exception.
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
@given(tree=hostile_trees(), payload=payload_bytes(), stray_key=st.text(max_size=12))
def test_property_no_unhandled_failure(tree, payload, stray_key):
    """Property 14: No unhandled failure for any attribute tree.

    The write half: a hostile Config_Snapshot either becomes an Inspector_Record
    or costs that one record a logged warning, and the payload is still written
    (Requirements 13.9, 13.10, 13.11, 14.14). The read half: any byte sequence
    supplied as a payload and any string supplied as an Inspector_Key yields one
    record or nothing, never an exception (Requirement 13.6).

    **Validates: Requirements 13.6, 13.9, 13.10, 13.11, 14.14**
    """
    # ── write half ────────────────────────────────────────────────────────────
    collector = InspectorCollector()
    collector.record_node(
        "hostile-rg-app",
        {
            "name": "hostile",
            "type": "Microsoft.Web/sites",
            "inspectorValues": {"before": tree, "after": tree, "afterUnknown": None},
        },
        "rg-app",
    )
    collector.record_cluster("cluster_vnetcore", VNET_KIND, tree, "rg-net")

    with captured_logs() as logs:
        built = collector.build_payload()
        with tempfile.TemporaryDirectory() as folder:
            index, index_path, blob = _write(built, folder)

    assert isinstance(built, InspectorPayload)
    # Every collected element either produced a record or was reported as a warning.
    assert built.record_count <= collector.element_count
    assert len(logs.warnings()) >= collector.element_count - built.record_count

    if index_path is None:
        assert logs.warnings()
    else:
        assert index["recordCount"] == built.record_count
        assert set(index["keys"]) <= {record.key for record in built.records}
        for entry in index["keys"].values():
            raw = blob[entry["offset"] : entry["offset"] + entry["length"]]
            assert isinstance(json.loads(raw.decode("utf-8")), dict)

    # ── read half ─────────────────────────────────────────────────────────────
    records_bytes, damaged_index = payload
    with tempfile.TemporaryDirectory() as folder:
        png_path = _write_reader_payload(folder, records_bytes, damaged_index)
        api = CloudHorusAPI()

        read_index = api.read_inspector_index(png_path)
        assert read_index is None or isinstance(read_index, dict)

        for key in list(damaged_index.get("keys", {})) + [stray_key, ""]:
            record = api.read_inspector_record(png_path, key)
            assert record is None or isinstance(record, dict)
            if record is not None:
                assert record.get("key") == key


# ─── Edge case: a corrupt Inspector_Index (Requirement 13.3) ──────────────────


def test_a_corrupt_index_reads_as_none_with_the_path_logged_at_warning_level(tmp_path, caplog):
    """Requirement 13.3: a written payload whose index is damaged is a warning, not a raise."""
    record = InspectorRecord(key="api-web-rg-app", kind="node", name="api-web")
    index, index_path, _ = _write(InspectorPayload(records=[record]), str(tmp_path))
    assert index["recordCount"] == 1

    png_path = os.path.join(str(tmp_path), f"{DIAGRAM_STEM}.png")
    with open(png_path, "wb") as handle:
        handle.write(b"")
    with open(index_path, "w", encoding="utf-8") as handle:
        handle.write("{ not json")

    api = CloudHorusAPI()
    with caplog.at_level(logging.WARNING, logger="cloudhorus.webui"):
        assert api.read_inspector_index(png_path) is None
        assert api.read_inspector_record(png_path, "api-web-rg-app") is None

    assert any(index_path in entry.getMessage() for entry in caplog.records)
    assert {entry.levelno for entry in caplog.records} == {logging.WARNING}


# ─── Edge case: an out-of-set Attribute_State (Requirement 13.8) ──────────────


def test_an_out_of_set_attribute_state_survives_the_payload_with_no_style_of_its_own(tmp_path):
    """Requirement 13.8: the state `exploded` reaches the panel with the `unchanged` presentation.

    The payload layer carries the state verbatim rather than rewriting it, and the
    Attribute_Style table it ships offers no entry for it — which is exactly the
    `unchanged` presentation, because `unchanged` has no entry either. The panel's
    accompanying warning is asserted in the WebUI tests, where the row formatter
    lives.
    """
    record = InspectorRecord(
        key="api-web-rg-app",
        kind="node",
        name="api-web",
        attributes=[AttributeEntry(path="https_only", state="exploded", before="false", after="true")],
    )

    index, _, blob = _write(InspectorPayload(records=[record]), str(tmp_path))

    entry = index["keys"]["api-web-rg-app"]
    line = json.loads(blob[entry["offset"] : entry["offset"] + entry["length"]].decode("utf-8"))
    assert line["attributes"][0]["state"] == "exploded"
    assert InspectorRecord.from_payload(line) == record

    # No style of its own, and no style for `unchanged` either: one presentation.
    assert "exploded" not in index["attributeStyles"]
    assert UNCHANGED_STATE not in index["attributeStyles"]
    assert ATTRIBUTE_STYLES.get("exploded") is None
    assert ATTRIBUTE_STYLES[UNCHANGED_STATE] is None


# ─── Edge case: empty containers (Requirement 5.8) ────────────────────────────


def test_an_empty_map_and_an_empty_list_reach_the_payload_as_braces_and_brackets(tmp_path):
    """Requirement 5.8: `{}` and `[]` are Attribute_Entry values of their own path."""
    identity = InspectorIdentity(key="api-web-rg-app", kind="node", name="api-web")
    record = build_record(
        identity,
        {"tags": {}, "zones": [], "regions": ["west"]},
        {"tags": {}, "zones": ["1"], "regions": []},
    )

    index, _, blob = _write(InspectorPayload(records=[record]), str(tmp_path))

    entry = index["keys"]["api-web-rg-app"]
    line = json.loads(blob[entry["offset"] : entry["offset"] + entry["length"]].decode("utf-8"))
    by_path = {attribute["path"]: attribute for attribute in line["attributes"]}

    assert by_path["tags"]["before"] == "{}"
    assert by_path["tags"]["after"] == "{}"
    assert by_path["tags"]["state"] == UNCHANGED_STATE
    # The empty list is a leaf of the before snapshot only: filling it removes the
    # `zones` path itself and adds `zones.0`.
    assert by_path["zones"]["before"] == "[]"
    assert "after" not in by_path["zones"]
    assert by_path["zones"]["state"] == "removed"
    assert by_path["zones.0"]["state"] == "added"
    assert by_path["zones.0"]["after"] == "1"

    # And the mirror case: emptying a list makes `[]` the After_Value of that path.
    assert by_path["regions"]["state"] == "added"
    assert by_path["regions"]["after"] == "[]"
    assert by_path["regions.0"]["state"] == "removed"
    assert by_path["regions.0"]["before"] == "west"


# ─── Interaction_Layer icons: embed_svg_icons (Requirement 3.7) ───────────────


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(svg=svg_documents())
def test_embed_svg_icons_hoists_one_image_per_group_and_leaves_no_icon_path(svg):
    """Requirement 3.7: one `<defs><image>` per group, every occurrence a `<use>`, no filesystem path."""
    original = ET.fromstring(svg)
    groups = {_icon_group(image) for image in _images(original)}
    occurrences = len(_images(original))

    rewritten = embed_svg_icons(svg, read_icon=_fake_icon_reader)
    root = ET.fromstring(rewritten)

    defs = _elements(root, "defs")
    assert len(defs) == 1
    hoisted = _images(defs[0])
    assert len(hoisted) == len(groups)

    # Every `<image>` that remains sits inside `<defs>`; every occurrence is a `<use>`.
    assert len(_images(root)) == len(hoisted)
    uses = _elements(root, "use")
    assert len(uses) == occurrences

    icon_ids = [image.get("id") for image in hoisted]
    assert icon_ids == [f"{ICON_ID_PREFIX}{index}" for index in range(len(groups))]
    for image in hoisted:
        href = image.get(f"{{{XLINK_NAMESPACE}}}href")
        assert href.startswith("data:image/png;base64,")

    referenced = {use.get(f"{{{XLINK_NAMESPACE}}}href") for use in uses}
    assert referenced == {f"#{icon_id}" for icon_id in icon_ids}

    # No href of the generating machine survives, and every occurrence keeps its place.
    original_hrefs = {group[0] for group in groups}
    for href in original_hrefs:
        assert f'"{href}"' not in rewritten
    assert [use.get("x") for use in uses] == [image.get("x") for image in _images(original)]
    assert [use.get("y") for use in uses] == [image.get("y") for image in _images(original)]


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(svg=svg_documents())
def test_the_title_inspector_keys_survive_the_icon_rewrite(svg):
    """The `<title>` texts the Inspector_Key lookup reads are untouched (Requirement 11.10)."""
    before = _titles(svg)
    assert before  # the fixture always draws at least one node and one cluster

    after = _titles(embed_svg_icons(svg, read_icon=_fake_icon_reader))

    assert after == before
    assert any(title.startswith("cluster_vnet") for title in before)


def test_embed_svg_icons_returns_a_layer_carrying_no_image_unchanged():
    """An SVG with no `<image>` needs no rewrite, so it is returned byte for byte."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<g class="node"><title>api-web-rg-app</title></g></svg>'
    )

    assert embed_svg_icons(svg, read_icon=_fake_icon_reader) == svg


def test_embed_svg_icons_rejects_text_that_is_not_well_formed_xml():
    """A malformed layer raises rather than shipping half a rewrite (Requirement 3.7)."""
    with pytest.raises(ValueError):
        embed_svg_icons('<svg><g class="node"><title>api</g></svg>', read_icon=_fake_icon_reader)


def test_embed_svg_icons_rejects_an_unreadable_icon():
    """An icon the reader cannot read raises, so no absolute path is ever shipped."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
        '<g class="node"><title>api-web-rg-app</title>'
        '<image xlink:href="/build/machine/icons/webapp.png" width="24" height="24" x="1" y="2"/>'
        "</g></svg>"
    )

    def _unreadable(_href: str) -> bytes:
        raise OSError("no such icon")

    with pytest.raises(ValueError):
        embed_svg_icons(svg, read_icon=_unreadable)


def test_write_svg_with_embedded_icons_rewrites_in_place_and_keeps_the_keys(tmp_path):
    """The layer beside the PNG is rewritten in place, titles and geometry intact."""
    svg_path = os.path.join(str(tmp_path), f"{DIAGRAM_STEM}.svg")
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
        '<g class="node"><title>api-web-rg-app</title>'
        '<image xlink:href="icons/webapp.png" width="24" height="24" x="1" y="2"/></g>'
        '<g class="node"><title>db-rg-data</title>'
        '<image xlink:href="icons/webapp.png" width="24" height="24" x="9" y="2"/></g></svg>'
    )
    with open(svg_path, "w", encoding="utf-8") as handle:
        handle.write(svg)

    assert write_svg_with_embedded_icons(svg_path, read_icon=_fake_icon_reader) == svg_path

    with open(svg_path, "r", encoding="utf-8") as handle:
        rewritten = handle.read()

    assert _titles(rewritten) == ["api-web-rg-app", "db-rg-data"]
    assert "icons/webapp.png" not in rewritten
    root = ET.fromstring(rewritten)
    assert len(_images(root)) == 1  # one group, two occurrences
    assert len(_elements(root, "use")) == 2


def test_write_svg_with_embedded_icons_discards_a_layer_it_cannot_rewrite(tmp_path):
    """A layer whose icons are unreadable is removed rather than shipped (Requirement 3.7)."""
    svg_path = os.path.join(str(tmp_path), f"{DIAGRAM_STEM}.svg")
    with open(svg_path, "w", encoding="utf-8") as handle:
        handle.write(
            '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
            '<g class="node"><title>api-web-rg-app</title>'
            '<image xlink:href="/build/machine/icons/webapp.png" width="24" height="24"/></g></svg>'
        )

    def _unreadable(_href: str) -> bytes:
        raise OSError("no such icon")

    with captured_logs() as logs:
        assert write_svg_with_embedded_icons(svg_path, read_icon=_unreadable) is None

    assert not os.path.exists(svg_path)
    assert any(svg_path in message for message in logs.warnings())
    assert cloudhorus_webui.CloudHorusAPI().get_interaction_layer(
        os.path.join(str(tmp_path), f"{DIAGRAM_STEM}.png")
    ) is None


# ─── Property 11: Reader soundness ────────────────────────────────────────────


class _SpyHandle:
    """A file object that records every ``read`` it serves, delegating the rest."""

    def __init__(self, handle: Any, path: str, reads: List[Tuple[str, Any, int]]) -> None:
        self._handle = handle
        self._path = path
        self._reads = reads

    def read(self, *args: Any) -> Any:
        data = self._handle.read(*args)
        self._reads.append((self._path, args[0] if args else None, len(data)))
        return data

    def __enter__(self) -> "_SpyHandle":
        self._handle.__enter__()
        return self

    def __exit__(self, *exc_info: Any) -> Any:
        return self._handle.__exit__(*exc_info)

    def __iter__(self) -> Any:  # pragma: no cover - the bridge never iterates
        return iter(self._handle)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._handle, name)


@contextmanager
def bridge_open_spy():
    """Record every path the Inspector_Bridge opens and every read it performs.

    The spy is installed as a module global of ``cloudhorus_webui``, so a name
    lookup inside a bridge body finds it before the builtin and nothing else in
    the process is affected. Yields ``(opened, reads)`` where ``opened`` holds the
    paths and ``reads`` holds ``(path, requested_bytes, returned_bytes)`` triples.
    """
    opened: List[str] = []
    reads: List[Tuple[str, Any, int]] = []
    real_open = open

    def spy(file: Any, *args: Any, **kwargs: Any) -> Any:
        path = str(file)
        opened.append(path)
        return _SpyHandle(real_open(file, *args, **kwargs), path, reads)

    cloudhorus_webui.open = spy  # type: ignore[attr-defined]
    try:
        yield opened, reads
    finally:
        del cloudhorus_webui.open  # type: ignore[attr-defined]


def _record_reads(reads: List[Tuple[str, Any, int]]) -> List[Tuple[str, Any, int]]:
    """The subset of a spy's reads that touched the Inspector_Record JSONL."""
    return [entry for entry in reads if entry[0].endswith(INSPECTOR_RECORDS_SUFFIX)]


def _assert_reads_stay_in_folder(opened: List[str], folder: str) -> None:
    """Every path a bridge read opened resolves inside the diagram's own folder."""
    root = os.path.realpath(folder) + os.sep
    for path in opened:
        assert os.path.realpath(path).startswith(root), f"the bridge read outside the run folder: {path}"


# Feature: interactive-resource-inspector, Property 11: For any Inspector_Payload
# and any requested Inspector_Key, the Inspector_Bridge returns the
# Inspector_Record whose key equals the requested key when the payload holds it,
# returns nothing when the payload does not hold it or when the indexed offset
# addresses absent, truncated or invalid JSON, and reads no more bytes than the
# length the index records for that key.
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
@given(
    records=st.lists(
        inspector_records(),
        min_size=1,
        max_size=5,
        unique_by=lambda record: record.key,
    ),
    damaged=payload_bytes(),
    stray_keys=st.lists(st.text(max_size=10), max_size=3),
    escape=st.sampled_from(("none", "traversal", "absolute", "renamed_absolute")),
)
def test_property_reader_soundness(records, damaged, stray_keys, escape):
    """Property 11: Reader soundness.

    Three claims over one payload, in the three states a payload on disk can be
    in. Intact: every key the Inspector_Index carries reads back as its own
    record, through a read of exactly the indexed length and never more
    (Requirements 12.1, 13.5). Absent: a key the index does not carry reads as
    nothing, with no file read attempted (Requirement 13.4). Damaged or hostile:
    the reader returns a dict or `None`, never raises, never returns bytes it did
    not find at the indexed location, and never opens a file outside the
    diagram's own folder — the payload is attacker-influenceable JSON sitting
    next to the PNG, so the `records` entry of the index is untrusted input.

    **Validates: Requirements 12.1, 13.4, 13.5, 14.11**
    """
    with tempfile.TemporaryDirectory() as root:
        folder = os.path.join(root, "run")
        os.makedirs(folder)
        index, _, blob = _write(InspectorPayload(records=list(records)), folder)
        png_path = os.path.join(folder, f"{DIAGRAM_STEM}.png")
        with open(png_path, "wb") as handle:
            handle.write(b"")

        api = CloudHorusAPI()

        # ── the payload holds the key ─────────────────────────────────────────
        for record in records:
            entry = index["keys"][record.key]
            with bridge_open_spy() as (opened, reads):
                read_back = api.read_inspector_record(png_path, record.key)

            assert read_back is not None
            assert read_back["key"] == record.key
            assert InspectorRecord.from_payload(read_back) == record

            # Exactly the indexed length is requested, and no more is returned.
            record_reads = _record_reads(reads)
            assert record_reads
            for _, requested, returned in record_reads:
                assert requested == entry["length"]
                assert returned <= entry["length"]
            assert sum(returned for _, _, returned in record_reads) <= entry["length"]
            _assert_reads_stay_in_folder(opened, folder)

        # ── the payload does not hold the key ─────────────────────────────────
        for key in [candidate for candidate in stray_keys if candidate not in index["keys"]] + [
            "",
            "cluster_vnetabsent",
        ]:
            with bridge_open_spy() as (opened, reads):
                assert api.read_inspector_record(png_path, key) is None
            # Requirement 13.4: an unknown key costs no read of the JSONL at all.
            assert _record_reads(reads) == []
            _assert_reads_stay_in_folder(opened, folder)

        # ── a hostile `records` entry may not escape the run folder ───────────
        outside = os.path.join(root, "outside")
        os.makedirs(outside)
        planted_name = f"diagram{INSPECTOR_RECORDS_SUFFIX}" if escape != "renamed_absolute" else "secrets.jsonl"
        planted_path = os.path.join(outside, planted_name)
        planted_line = json.dumps(
            {"key": records[0].key, "kind": "node", "name": "planted-outside"}, ensure_ascii=False
        )
        with open(planted_path, "wb") as handle:
            handle.write((planted_line + "\n").encode("utf-8"))

        index_path = os.path.join(folder, f"{DIAGRAM_STEM}{INSPECTOR_INDEX_SUFFIX}")
        hostile_index = dict(index)
        if escape == "traversal":
            hostile_index["records"] = os.path.join("..", "outside", planted_name)
        elif escape in {"absolute", "renamed_absolute"}:
            hostile_index["records"] = planted_path
        with open(index_path, "w", encoding="utf-8") as handle:
            json.dump(hostile_index, handle, ensure_ascii=False)

        hostile_api = CloudHorusAPI()
        with bridge_open_spy() as (opened, reads):
            read_back = hostile_api.read_inspector_record(png_path, records[0].key)

        assert read_back is None or isinstance(read_back, dict)
        if read_back is not None:
            # Whatever came back was found in this run's own JSONL, not outside it.
            entry = index["keys"][records[0].key]
            assert read_back == json.loads(
                blob[entry["offset"] : entry["offset"] + entry["length"]].decode("utf-8")
            )
        _assert_reads_stay_in_folder(opened, folder)

    # ── a damaged payload: a dict from the indexed location, or nothing ───────
    records_bytes, damaged_index = damaged
    with tempfile.TemporaryDirectory() as folder:
        damaged_png = _write_reader_payload(folder, records_bytes, damaged_index)
        damaged_api = CloudHorusAPI()

        for key, entry in damaged_index.get("keys", {}).items():
            with bridge_open_spy() as (opened, reads):
                read_back = damaged_api.read_inspector_record(damaged_png, key)

            assert read_back is None or isinstance(read_back, dict)
            if read_back is not None:
                offset, length = entry["offset"], entry["length"]
                assert read_back == json.loads(records_bytes[offset : offset + length].decode("utf-8"))
                assert read_back.get("key") == key
                for _, requested, returned in _record_reads(reads):
                    assert requested == length
                    assert returned <= length
            _assert_reads_stay_in_folder(opened, folder)

        for key in stray_keys:
            if key not in damaged_index.get("keys", {}):
                assert damaged_api.read_inspector_record(damaged_png, key) is None
