"""Performance benchmarks for the Interactive Resource Inspector.

Task 14.1 of the interactive-resource-inspector spec, covering:

* Requirement 12.6 - at an input of 5000 resources, the runtime the Inspector
  *adds* (Interaction_Layer production, Inspector_Payload construction,
  Inspector_Payload writing) stays below 15 percent of the total generation
  runtime;
* Requirement 12.7 - the host-process work behind displaying one Inspector_Record
  of a 500-resource run completes in under 1000 milliseconds.

What is measured for 12.6, and why
----------------------------------
Requirement 12.6 is a ratio, so it needs a numerator (what the Inspector adds)
and a denominator (the total generation runtime). Timing an Inspector-enabled
generation against a disabled one and subtracting the two totals is the obvious
shape and the wrong one: both totals are dominated by Graphviz layout, which is
the same work either way, so the difference is a small number obtained by
subtracting two large noisy ones. The two sides are measured separately instead,
each in the way that makes the assertion hold for the right reason. This is the
same discipline `tests/test_plan_diff_performance.py` applies to Requirement 11.2
of the plan-diff feature.

**Numerator - everything the Inspector adds, at the full 5000 resources.**
Four parts, summed:

* the *document build delta*: the same 5000-resource plan built with and without
  `collect_inspector_values`. The enabled side additionally resolves the
  before/after snapshots per resource through the Change_Category table, redacts
  both phases and attaches the `inspectorValues` triple, so the difference is
  exactly the Inspector work inside the build. Both sides describe the same
  resource set - the benchmark asserts equal resource counts before comparing
  timings - so the delta is not a different amount of normalization;
* `InspectorCollector.build_payload()` over 5000 collected elements, which is the
  whole flatten/diff/bound transform chain for the run;
* `write_inspector_payload` of that payload, which is the JSONL and the index;
* `embed_svg_icons` over an Interaction_Layer carrying 5000 `<image>` elements,
  which is the post-processing half of Interaction_Layer production. The icon
  bytes are supplied through the injected `read_icon` hook rather than read from
  disk, so the measurement is the XML transform and not the host's page cache.

The one part of the Inspector's cost deliberately left out of both sides is the
`dot` layout pass itself: the dual-format invocation emits the SVG from the *same*
layout the PNG already pays for (Requirement 3.1), so layout is denominator work
in both branches. Excluding it from the numerator excludes only the extra
serialization `-Tsvg` performs, which is why the numerator is otherwise built to
over-state: every cheap path is the minimum of `REPEATS` runs, and every part is
measured at the full 5000 resources.

**Denominator - a deliberate under-estimate of the total generation runtime.**
One full pass through `generate_resource_graph` over a plan-diff renderer
template, with Graphviz layout faked out, at `GENERATION_RESOURCE_COUNT`
resources rather than at 5000. Both reductions shrink the denominator, and a
smaller denominator can only make the measured percentage *larger* than the real
one, so passing this assertion implies passing the requirement:

* Graphviz layout is pure denominator - `dot` does not care whether the run also
  collected Inspector records - and at 5000 nodes it costs tens of seconds of
  external-process time;
* the render pass is measured at `GENERATION_RESOURCE_COUNT` resources because its
  per-resource cost grows with the resource count (the subnet and edge passes are
  super-linear), so a pass over fewer resources is strictly cheaper than the
  5000-resource pass the requirement talks about.

What is measured for 12.7, and what is excluded
-----------------------------------------------
Requirement 12.7 is a wall-clock budget on displaying one record. The measurable
half is the host-process work: `read_inspector_index` followed by
`read_inspector_record`, over a 500-record payload written to disk by the real
writer, taking the **maximum** over all 500 keys so the budget is asserted
against the worst record rather than an average. The index read is included in
every measurement - each key is read through a fresh bridge instance, so no
measurement benefits from the per-run index cache - which is the pessimistic
reading of the requirement.

**The DOM render is excluded.** Building the panel rows happens in the WebUI's
browser context and cannot be timed from pytest; it is covered functionally by
`tests/test_inspector_webui.py` instead. What this module bounds is therefore the
payload-read half of the budget, and the bound asserted here is the full 1000 ms,
so the measurement has to fit inside the whole requirement's budget with the DOM
render's share left over.

Timing tests are sensitive to machine load: the cheap measurements are the minimum
of several repetitions, the expensive render pass runs once, and the whole module
is marked `performance` so it can be deselected with `-m "not performance"`.
"""

import os
import statistics
import sys
import time
from typing import Any, Dict, List, Optional

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from cloudhorus_webui import CloudHorusAPI  # noqa: E402
from core.inspector import (  # noqa: E402
    INSPECTOR_INDEX_SUFFIX,
    InspectorCollector,
    embed_svg_icons,
    write_inspector_payload,
)
from core.terraform_builder import TerraformTemplateBuilder  # noqa: E402
from test_plan_diff_graph_plumbing import run_terraform_json_generation  # noqa: E402
from test_plan_diff_performance import (  # noqa: E402
    RESOURCE_GROUP,
    measure,
    renderer_template,
    synthetic_plan,
)

pytestmark = pytest.mark.performance

#: Input size Requirement 12.6 is written against.
RESOURCE_COUNT = 5000

#: Resource count of the render pass used as the Requirement 12.6 denominator.
#: Deliberately below `RESOURCE_COUNT`; see the module docstring for why that keeps
#: the assertion conservative. Raise it for a stricter (and much slower) run.
GENERATION_RESOURCE_COUNT = 2000

#: Requirement 12.6 budget, as a fraction of the total generation runtime.
OVERHEAD_BUDGET_RATIO = 0.15

#: Run size Requirement 12.7 is written against.
RECORD_COUNT = 500

#: Requirement 12.7 budget for one record reaching the panel.
READ_BUDGET_SECONDS = 1.0

#: Repetitions per cheap measured path; the minimum is kept.
REPEATS = 3

#: One `<image>` element as Graphviz writes it into an SVG, absolute href and all.
_SVG_IMAGE = (
    '<g id="node{index}" class="node"><title>resource-{index}-{group}</title>'
    '<image xlink:href="/opt/cloudhorus/icons/Storage-Accounts.png" width="108px" height="108px" '
    'preserveAspectRatio="xMinYMin meet" x="{x}" y="-{y}"/></g>'
)

#: Icon bytes the embedding pass base64-encodes, supplied through `read_icon` so the
#: measurement is the XML transform rather than 5000 file reads.
_ICON_BYTES = b"\x89PNG\r\n\x1a\n" + b"icon-payload" * 32


def interaction_layer(image_count: int) -> str:
    """Return an Interaction_Layer carrying `image_count` icon `<image>` elements."""
    images = "\n".join(
        _SVG_IMAGE.format(index=index, group=RESOURCE_GROUP, x=index * 4, y=index * 2)
        for index in range(image_count)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        'width="8000pt" height="6000pt" viewBox="0 0 8000 6000">\n'
        f'<g class="graph"><title>CloudHorus</title>\n{images}\n</g></svg>\n'
    )


def collector_over(resources: List[Dict[str, Any]]) -> InspectorCollector:
    """Record one node element per renderer resource, as the render pass does.

    The Inspector_Key is the Node_Key `<resource_name>-<resource_group>`, and the
    source is the Renderer_Template resource dict the render pass already holds -
    nothing is copied, which is what keeps collection out of the numerator's
    interesting part and puts the whole cost in `build_payload`.
    """
    collector = InspectorCollector()
    for resource in resources:
        collector.record_node(f"{resource['name']}-{RESOURCE_GROUP}", resource, RESOURCE_GROUP)
    return collector


def _print(capsys, *lines: str) -> None:
    """Print measured numbers so a benchmark run reports them, not just a verdict."""
    with capsys.disabled():
        print("")
        for line in lines:
            print(line)


# ─── Requirement 12.6 - added runtime versus total generation runtime ─────────


def test_inspector_overhead_stays_below_fifteen_percent_of_generation_runtime(capsys, tmp_path) -> None:
    """The runtime the Inspector adds stays under 15 percent of the generation runtime.

    Numerator: the `collect_inspector_values` build delta, `build_payload`,
    `write_inspector_payload` and `embed_svg_icons`, all at the full 5000
    resources. Denominator: one render pass at a smaller resource count with
    Graphviz layout faked out, which under-estimates the real total. See the
    module docstring for why that makes the assertion conservative.
    """
    plan = synthetic_plan(RESOURCE_COUNT, include_deletes=False)
    builder = TerraformTemplateBuilder()

    def build_without_inspector():
        return builder._build_plan_document(plan, None, False)

    def build_with_inspector():
        return builder._build_plan_document(plan, None, True)

    # Fairness check: both paths normalize the same resource set, so the build
    # delta is Inspector work rather than a different amount of building.
    without_document = build_without_inspector()
    with_document = build_with_inspector()
    without_resources = without_document.to_renderer_template()["resources"]
    with_resources = with_document.to_renderer_template()["resources"]
    assert len(without_resources) == len(with_resources) == RESOURCE_COUNT
    assert all(resource.inspector_values is None for resource in without_document.resources)
    assert all("inspectorValues" in resource for resource in with_resources)

    collector = collector_over(with_resources)
    assert collector.element_count == RESOURCE_COUNT
    assert collector.key_collisions == 0

    payload = collector.build_payload()
    assert payload.record_count == RESOURCE_COUNT

    layer = interaction_layer(RESOURCE_COUNT)
    embedded = embed_svg_icons(layer, read_icon=lambda _path: _ICON_BYTES)
    assert embedded.count("<use") == RESOURCE_COUNT

    payload_stem = os.path.join(str(tmp_path), "azure_resources_20260101_000000")
    assert write_inspector_payload(payload, payload_stem) == f"{payload_stem}{INSPECTOR_INDEX_SUFFIX}"

    build_without_seconds = measure(build_without_inspector, repeats=REPEATS)
    build_with_seconds = measure(build_with_inspector, repeats=REPEATS)
    build_delta_seconds = build_with_seconds - build_without_seconds
    payload_seconds = measure(lambda: collector_over(with_resources).build_payload(), repeats=REPEATS)
    write_seconds = measure(lambda: write_inspector_payload(payload, payload_stem), repeats=REPEATS)
    embed_seconds = measure(lambda: embed_svg_icons(layer, read_icon=lambda _path: _ICON_BYTES), repeats=REPEATS)
    added_seconds = build_delta_seconds + payload_seconds + write_seconds + embed_seconds

    # Denominator: one full render pass, Graphviz layout faked out.
    generation_template = renderer_template(GENERATION_RESOURCE_COUNT)
    assert len(generation_template["resources"]) == GENERATION_RESOURCE_COUNT

    def render_pass() -> str:
        source, _analyzer, _calls = run_terraform_json_generation(
            [generation_template], work_dir=str(tmp_path / "render")
        )
        return source

    generation_seconds = measure(render_pass, repeats=1)
    ratio = added_seconds / generation_seconds

    _print(
        capsys,
        f"[perf] {RESOURCE_COUNT}-resource build without the Inspector: {build_without_seconds * 1000:.1f} ms",
        f"[perf] {RESOURCE_COUNT}-resource build with the Inspector:    {build_with_seconds * 1000:.1f} ms",
        f"[perf]   build delta:              {build_delta_seconds * 1000:.1f} ms",
        f"[perf]   build_payload:            {payload_seconds * 1000:.1f} ms",
        f"[perf]   write_inspector_payload:  {write_seconds * 1000:.1f} ms",
        f"[perf]   embed_svg_icons:          {embed_seconds * 1000:.1f} ms",
        f"[perf]   added runtime:            {added_seconds * 1000:.1f} ms",
        f"[perf] {GENERATION_RESOURCE_COUNT}-resource render pass (denominator, layout excluded): "
        f"{generation_seconds * 1000:.0f} ms",
        f"[perf] added runtime is {ratio * 100:.2f} % of the generation runtime",
    )

    assert added_seconds > 0, "the Inspector phases must be measurable"
    assert ratio < OVERHEAD_BUDGET_RATIO, (
        f"the Inspector added {added_seconds:.3f}s on top of a {generation_seconds:.3f}s generation "
        f"({ratio * 100:.1f} %), budget is {OVERHEAD_BUDGET_RATIO * 100:.0f} %"
    )


# ─── Requirement 12.7 - one record reaching the panel ────────────────────────


def test_reading_one_record_of_a_500_resource_run_stays_within_the_budget(capsys, tmp_path) -> None:
    """Every one of 500 records is read from disk in well under 1000 ms.

    The payload is written by the real writer, and each key is read through a
    fresh bridge instance so the index read is paid on every measurement rather
    than served from the per-run cache. The reported number is the maximum over
    all 500 keys. The DOM render is excluded; see the module docstring.
    """
    plan = synthetic_plan(RECORD_COUNT, include_deletes=False)
    resources = TerraformTemplateBuilder()._build_plan_document(plan, None, True).to_renderer_template()["resources"]
    assert len(resources) == RECORD_COUNT

    payload = collector_over(resources).build_payload()
    assert payload.record_count == RECORD_COUNT

    run_folder = tmp_path / "azure_resources_20260101_000000"
    run_folder.mkdir()
    stem = str(run_folder / "azure_resources_20260101_000000")
    png_path = f"{stem}.png"
    with open(png_path, "wb") as handle:
        handle.write(b"")
    assert write_inspector_payload(payload, stem) is not None

    index = CloudHorusAPI().read_inspector_index(png_path)
    assert index is not None and len(index["keys"]) == RECORD_COUNT

    def read(key: str) -> Optional[Dict[str, Any]]:
        """One cold read: a fresh bridge, the index, then exactly one record."""
        bridge = CloudHorusAPI()
        assert bridge.read_inspector_index(png_path) is not None
        return bridge.read_inspector_record(png_path, key)

    timings: List[float] = []
    for key in index["keys"]:
        start = time.perf_counter()
        record = read(key)
        timings.append(time.perf_counter() - start)
        assert record is not None and record["key"] == key

    slowest = max(timings)
    _print(
        capsys,
        f"[perf] {RECORD_COUNT}-record payload, cold index plus one record read:",
        f"[perf]   slowest of {len(timings)} keys: {slowest * 1000:.2f} ms",
        f"[perf]   median:                  {statistics.median(timings) * 1000:.2f} ms",
        f"[perf]   total for all keys:      {sum(timings) * 1000:.0f} ms",
        f"[perf] budget for one record reaching the panel: {READ_BUDGET_SECONDS * 1000:.0f} ms"
        " (DOM render excluded)",
    )

    assert slowest < READ_BUDGET_SECONDS, (
        f"the slowest of {RECORD_COUNT} record reads took {slowest * 1000:.1f} ms, "
        f"budget is {READ_BUDGET_SECONDS * 1000:.0f} ms"
    )

    # The reason the budget holds at scale (Requirement 12.1): one read consumes the
    # indexed length of one record, not the payload of the run.
    records_size = os.path.getsize(f"{stem}.inspector.jsonl")
    assert max(entry["length"] for entry in index["keys"].values()) < records_size
