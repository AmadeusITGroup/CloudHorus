# Implementation Plan: Interactive Resource Inspector

## Overview

Implementation follows the design's dependency chain, in Python 3 against the existing CloudHorus stack plus the vanilla-JS WebUI. The pure `src/core/inspector.py` core comes first (flattening, scalar rendering, the Attribute_Differ, the Value_Bounds, record building, the collector, the payload writers, SVG icon embedding), then the shared Hypothesis strategies, then the optional inspector-value extraction in `TerraformTemplateBuilder`, then the trailing `inspector_values` field on `LocalTemplateResource`, then the `graph_generator` plumbing with its dual-format render branch, then the CLI and service layer, then the three Inspector_Bridge methods, then the WebUI front end, and finally the performance and export verification.

Every new parameter is trailing and defaulted, and the Inspector_Mode-off branch keeps executing `dot.render(output_filename, format="png")` untouched, which is what keeps the headless pipeline path byte-identical.

Property-based tests use Hypothesis and share the new strategy module `tests/strategies/inspector_trees.py`, which imports from the existing `tests/strategies/plan_json.py` where the shapes overlap. Each of the 20 correctness properties in the design gets exactly one property test, in the file the Testing Strategy assigns it to.

## Tasks

- [x] 1. Build the pure Inspector core
  - [x] 1.1 Create `src/core/inspector.py` foundations
    - Define `ATTRIBUTE_STATES`, `ATTRIBUTE_STYLES` (`added` `#107C10` `+`, `removed` `#D13438` `-`, `changed` `#0078D4` `~`, `unchanged` `None`), `MAX_ATTRIBUTE_ROWS = 500`, `MAX_SCALAR_CHARS = 2048`, `MAX_TREE_DEPTH = 12`, `TRUNCATION_MARKER`, `UNKNOWN_MARKER`
    - Add the frozen `AttributeStyle` and `AttributeEntry` dataclasses and the `InspectorIdentity`, `InspectorRecord`, `InspectorPayload` dataclasses with the field sets from the Data Models section
    - Import no Graphviz, no Azure SDK and no pywebview, so the module stays a pure dictionary-in / dictionary-out transform chain
    - _Requirements: 4.4, 7.13, 12.10_

  - [x] 1.2 Create `tests/strategies/inspector_trees.py` with the shared generators
    - `attribute_trees()`, `bounded_trees()`, `unbounded_trees()`, `hostile_trees()`, `snapshot_pairs()`, `sensitivity_masks()`, `change_entries()`, `inspector_records()`, `payload_bytes()`, `markup_strings()`, `svg_documents()`
    - Reuse `azurerm_resource_values()`, `sensitive_masks()` and `plan_documents()` from `tests/strategies/plan_json.py` rather than duplicating those shapes
    - Emit empty maps and empty lists, keys holding `.`, dashes and non-ASCII characters, and lists of maps so index segments appear in Attribute_Paths
    - _Requirements: 14.1, 14.3, 14.8, 14.14_

  - [x] 1.3 Implement `flatten_values`
    - Join map keys with `.` and list indices as zero-based decimal segments; emit `{}` for an empty map and `[]` for an empty list at their own Attribute_Path
    - Render a non-string map key through `str(key)` and use the result verbatim as the path segment
    - Collapse a branch past `max_depth` to the Truncation_Marker at depth 12 and omit the deeper leaves, reporting the `depth` Truncation_Reason
    - Track the identity of the ancestors currently on the walk and write the Truncation_Marker in place of a subtree that repeats an enclosing subtree, so a shared or cyclic reference terminates
    - _Requirements: 5.3, 5.8, 12.4, 13.10, 13.11_

  - [x] 1.4 Implement `render_scalar`
    - Render a non-string leaf as its JSON representation; fall back to `str(value)` for a value the JSON serializer cannot represent
    - Truncate past `max_chars` at 2048 characters, append the Truncation_Marker, and report the `value` Truncation_Reason
    - _Requirements: 5.7, 12.3, 13.9_

  - [x] 1.5 Implement `diff_attributes`
    - Flatten both phases, take the union of the Attribute_Paths, and emit one `AttributeEntry` per path in ascending lexicographic order
    - Assign exactly one Attribute_State per the decision table: `added` for after-only, `removed` for before-only, `changed` for both with differing rendered values, `unchanged` for both with equal rendered values
    - Consume the `unknown` mask to set the After_Value of a not-yet-known Attribute_Path to the Unknown_Marker
    - Classify a path whose two values are both the Redaction_Literal as `unchanged`
    - _Requirements: 5.2, 5.4, 6.6, 7.1, 7.2, 7.3, 7.4, 7.5, 11.7_

  - [x] 1.6 Implement `apply_bounds` and `build_record`
    - `apply_bounds` preserves the input order untouched under the Row_Bound; over the cap it keeps every non-`unchanged` entry first, fills the remainder in ascending Attribute_Path order to 500, and returns the omitted count
    - `build_record` assembles the identity header, the bounded entry list, `omitted_attributes`, and the `truncations` list holding `value`, `depth` and `rows` exactly when the corresponding bound applied
    - Set the `replacement` marker exactly for the Change_Category `replace`
    - _Requirements: 4.9, 12.2, 12.5_

  - [x]* 1.7 Write property test for the flatten round trip
    - **Property 3: Flatten round trip**
    - **Validates: Requirements 5.3, 5.8, 14.3**
    - File `tests/test_inspector_flatten.py`, driven by `bounded_trees()`

  - [x]* 1.8 Write property test for path coverage and ordering
    - **Property 2: Path coverage and ordering**
    - **Validates: Requirements 5.2, 5.4, 14.2**
    - File `tests/test_inspector_flatten.py`

  - [x]* 1.9 Write property test for bound enforcement and reporting
    - **Property 12: Bound enforcement and reporting**
    - **Validates: Requirements 12.2, 12.3, 12.4, 12.5, 12.10, 14.12**
    - File `tests/test_inspector_flatten.py`, driven by `unbounded_trees()`

  - [x]* 1.10 Write property test for classification totality and closure
    - **Property 1: Classification totality and closure**
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 14.1**
    - File `tests/test_inspector_diff.py`

  - [x]* 1.11 Write property test for diff idempotence
    - **Property 4: Diff idempotence**
    - **Validates: Requirements 14.4**
    - File `tests/test_inspector_diff.py`

  - [x]* 1.12 Write property test for the identity diff
    - **Property 6: Identity diff**
    - **Validates: Requirements 6.5, 6.9, 10.2, 10.7, 14.6**
    - File `tests/test_inspector_diff.py`

  - [x]* 1.13 Write property test for diff antisymmetry
    - **Property 7: Diff antisymmetry**
    - **Validates: Requirements 14.7**
    - File `tests/test_inspector_diff.py`

- [x] 2. Checkpoint - Inspector core
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Collect elements and persist the payload
  - [x] 3.1 Implement `InspectorCollector` and `NullInspectorCollector`
    - `record_node(node_key, resource, resource_group)` and `record_cluster(cluster_key, kind, source, resource_group)` storing the Inspector_Key, the identity fields, and a reference to the source dict
    - On a duplicate Inspector_Key keep the first record, log the duplicate at warning level, and increment the collision counter surfaced in the index
    - `build_payload()` diffing and bounding each collected element behind a per-record guard so one failing record is a warning and the remaining records still build
    - `NullInspectorCollector` returns immediately from every method, so the Inspector_Mode-off path takes no new branching at the call sites
    - _Requirements: 4.1, 4.2, 4.3, 4.5, 4.8_

  - [x] 3.2 Implement `write_inspector_payload`
    - Write `<diagram>.inspector.jsonl` with one Inspector_Record per line, recording the UTF-8 byte offset and length of each line
    - Write `<diagram>.inspector-index.json` last, carrying `schemaVersion`, `diagram`, `records`, `recordCount`, `keyCollisions`, the `keys` offset map with each key's `kind`, the `attributeStyles` table, and the applied `bounds`
    - Return the index path, or `None` after a warning naming the path on an `OSError`, leaving no partial index behind
    - _Requirements: 3.6, 7.13, 12.8, 12.10_

  - [x] 3.3 Implement `embed_svg_icons`
    - Group every `<image>` by (`xlink:href`, `width`, `height`, `preserveAspectRatio`), hoist one `<image>` per group into `<defs>` as a data URI, and rewrite each occurrence to `<use xlink:href="#ch-icon-N" x=… y=…/>`
    - Discard the SVG with a warning when an icon file is unreadable or the SVG text is not well-formed XML, rather than shipping absolute filesystem paths
    - Carry element identity only: no attribute value enters the Interaction_Layer
    - _Requirements: 3.7, 11.10_

  - [x]* 3.4 Write property test for the payload round trip
    - **Property 10: Payload round trip**
    - **Validates: Requirements 12.8, 14.10**
    - File `tests/test_inspector_payload.py`, driven by `inspector_records()` with multi-byte characters, embedded newlines and quotation marks

  - [x]* 3.5 Write property test for no unhandled failure
    - **Property 14: No unhandled failure for any attribute tree**
    - **Validates: Requirements 13.6, 13.9, 13.10, 13.11, 14.14**
    - File `tests/test_inspector_payload.py`, driven by `hostile_trees()` and `payload_bytes()`

  - [x]* 3.6 Write edge-case and SVG unit tests for the payload layer
    - A corrupt index returning `None` with the file path logged at warning level (13.3); a record carrying the state `"exploded"` handled with the `unchanged` presentation and a logged warning (13.8); empty map and empty list rendering as `{}` and `[]` (5.8)
    - `embed_svg_icons` and the `<title>` Inspector_Key extraction asserted with plain `xml.etree`, no Node involved, over `svg_documents()` fixtures
    - File `tests/test_inspector_payload.py`
    - _Requirements: 3.7, 5.8, 13.3, 13.8_

- [x] 4. Extend the Terraform builder with optional inspector values
  - [x] 4.1 Implement `_inspector_values_for` in `src/core/terraform_builder.py`
    - Resolve the change object through the existing `_sensitive_indexes(terraform_json)` `changes_by_address` map; add no second index and no extra Plan_File read
    - Redact each phase through the existing `_redact_sensitive(values, self._sensitive_mask_for(tf, address, phase))`, using `before_sensitive` for the before phase and `after_sensitive` with the `sensitive_values` fallback for the after phase
    - Apply the Change_Category table: `create` → empty before and redacted `change.after`; `delete` → redacted `change.before` and empty after; `update` and `replace` → both redacted sides; `unchanged` and no change object → the redacted attribute map on both sides
    - Fall back to the redacted attribute map with the address logged at warning level when `change.after` is absent for `create`/`update`/`replace`, and to an empty before snapshot with the address logged when `change.before` is absent for `update`/`replace`/`delete`
    - Carry `after_unknown` through untouched as a mask, and build the snapshot from the Renderer_Template `properties` map plus the extra fields when the resource carries no attribute map
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 6.10, 10.4, 11.1, 11.2, 11.3, 11.4_

  - [x] 4.2 Add the `collect_inspector_values` keyword to the builder entry points
    - Trailing `collect_inspector_values: bool = False` on `build_document_from_json` and `build_terraform_template`, forwarded to `_inspector_values_for`
    - When `False`, never call the helper and leave `LocalTemplateResource.inspector_values` at `None`
    - _Requirements: 1.5, 10.1_

  - [x]* 4.3 Write property test for redaction fidelity
    - **Property 8: Redaction fidelity**
    - **Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.7, 14.8**
    - File `tests/test_inspector_values.py`, driven by `sensitivity_masks()`

  - [x]* 4.4 Write property test for before and after resolution
    - **Property 19: Before and after resolution follows the category table**
    - **Validates: Requirements 4.4, 4.9, 6.1, 6.2, 6.3, 6.4, 6.6, 6.7, 6.8, 6.9, 10.4**
    - File `tests/test_inspector_values.py`, driven by `change_entries()` through every fallback branch

- [x] 5. Extend the renderer contract additively
  - [x] 5.1 Add the optional `inspector_values` field to `LocalTemplateResource`
    - Trailing, defaulted to `None`, after `change_category` in `src/cloudhorus/models/local_template_document.py`
    - Emit `inspectorValues` from `to_renderer_resource()` only when the field is set, mirroring the `change_category` discipline
    - Leave `to_renderer_template()` and every existing construction site untouched
    - _Requirements: 1.5, 10.1_

  - [x]* 5.2 Write property test for the disabled-mode contract
    - **Property 15: Disabled mode leaves the pre-feature contract untouched**
    - **Validates: Requirements 1.3, 1.4, 1.5**
    - File `tests/test_inspector_parity.py`, layout faked out so the example count stays high

- [x] 6. Checkpoint - builder and renderer contract
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Thread the Inspector through the graph pipeline
  - [x] 7.1 Add the parameter and the collector to `src/core/graph_generator.py`
    - Trailing `interactive_inspector: bool = False` on `generate_resource_graph` and `_generate_resource_graph_inner`, forwarded as `build_terraform_template(..., collect_inspector_values=interactive_inspector)`
    - Construct `inspector = InspectorCollector() if interactive_inspector else NullInspectorCollector()` next to the existing `change_index` / `aggregate_counts` block
    - _Requirements: 1.5, 2.8, 10.1_

  - [x] 7.2 Collect records at the node and cluster creation sites
    - `record_node` at the resource-group level `add_node_in_subgraph` call and at the subnet-placed node call, keyed `<resource_name>-<resource_group>`
    - `record_cluster` at the `cluster_vnet<name>` subgraph and at the four `cluster_subnet<name>` sites funnelled through `style_subnet_cluster`, keyed `cluster_vnet<name>` and `cluster_subnet<name>`
    - Build a subnet's record from the parent VNet's `properties["subnets"]` entry when the Renderer_Template carries no standalone subnet resource, resolving the standalone resource by the compound name `<vnet>/<subnet>` first and the bare subnet name second, which is the order `resolve_subnet_change_category` already applies
    - In Live mode pass the Azure resource dict already in scope, so no additional Azure request is issued
    - _Requirements: 3.2, 3.3, 3.4, 3.5, 3.10, 4.6, 4.7, 4.8, 9.1, 9.5, 9.6, 10.1, 10.5_

  - [x] 7.3 Add the dual-format render branch
    - Keep `dot.render(output_filename, format="png")` as the only call in the disabled branch
    - In the enabled branch `dot.save(output_filename)`, then one `subprocess.run` with a fixed argument vector carrying `-Kdot -Tpng -o <png> -Tsvg -o <svg> <source>` and paths as separate elements, never a shell string, then `write_svg_with_embedded_icons(svg_path)`
    - Downgrade a `FileNotFoundError`, a `CalledProcessError`, an icon-read failure or a malformed SVG to a warning and fall back to `dot.render(output_filename, format="png")`, so the PNG is produced either way
    - _Requirements: 1.3, 1.6, 1.9, 1.12, 3.1, 3.6, 3.8_

  - [x] 7.4 Write the Inspector_Payload beside the Change_Summary sidecar
    - Call `write_inspector_payload(inspector.build_payload(), output_filename)` only when Inspector_Mode is enabled, wrapped so a failure is a warning and the run still returns the PNG path
    - Leave the Change_Summary sidecar file name and content untouched
    - _Requirements: 1.9, 1.11, 3.6, 12.8_

  - [x]* 7.5 Write property test for element coverage
    - **Property 5: Element coverage**
    - **Validates: Requirements 3.2, 3.3, 4.1, 4.2, 4.3, 4.6, 4.7, 9.1, 14.5**
    - File `tests/test_inspector_collector.py`; needs a render pass with Graphviz layout faked out, so it is not a pure-function property and runs at a reduced example count

  - [x]* 7.6 Write container resolution example tests
    - A subnet drawn from a VNet's embedded `subnets` list with no standalone resource (9.5) and the compound-name-first resolution order (9.6), asserted directly because a regression there produces an empty panel rather than a missing record
    - File `tests/test_inspector_collector.py`
    - _Requirements: 9.5, 9.6_

  - [x]* 7.7 Write property test for Inspector failure containment
    - **Property 16: Inspector failures never cost the diagram**
    - **Validates: Requirements 1.9, 3.8**
    - File `tests/test_inspector_parity.py`; parameterizes over `InspectorCollector.build_payload`, `write_inspector_payload`, `embed_svg_icons` and `subprocess.run`, patching each to raise, and needs no `dot`

  - [x]* 7.8 Write property test for headless output parity
    - **Property 13: Headless output parity**
    - **Validates: Requirements 1.6, 1.11, 3.1, 14.13**
    - File `tests/test_inspector_parity.py`; requires the real `dot` binary, so the module is marked `pytest.mark.skipif(shutil.which("dot") is None)` and departs from the `patch("graphviz.Digraph.render")` convention; `max_examples=5` with `deadline=None` because each example pays for two real layout passes, and a counting spy around `subprocess.run` asserts exactly one invocation carrying both `-Tpng` and `-Tsvg`

  - [x]* 7.9 Write property test for sensitive containment
    - **Property 9: Sensitive containment**
    - **Validates: Requirements 11.5, 11.6, 11.9, 11.10, 14.9**
    - File `tests/test_inspector_containment.py`; asserts absence across the payload, the Interaction_Layer SVG, the DOT source, the panel markup and every `caplog` record

- [x] 8. Checkpoint - graph pipeline and parity
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Wire the service layer and the CLI
  - [x] 9.1 Add `interactive_inspector` to the configuration and the service layer
    - Trailing `interactive_inspector: bool = False` on `VisualizationConfig` in `src/cloudhorus/models/configuration.py`
    - Trailing `interactive_inspector` parameter on `GraphGeneratorService.generate_graph`, forwarded to `generate_resource_graph`
    - _Requirements: 1.2, 2.1, 2.8_

  - [x] 9.2 Add `--interactiveInspector` and its validation to `src/main.py`
    - `type=str`, `default="False"`, matching the `--exportDrawio` argument shape, forwarded into the visualization config
    - Compare the raw value case-insensitively against `{"true", "false"}` in the existing argument-checking block; otherwise log `Invalid --interactiveInspector value '<value>'. Accepted values: True False` and exit non-zero before any generation work starts
    - Leave the name, arity and default of every pre-existing argument untouched, including `--exportDrawio`'s existing lenient `str_to_bool` behaviour
    - _Requirements: 1.7, 2.1, 2.2, 2.3, 2.8_

  - [x]* 9.3 Write property test for CLI value validation
    - **Property 17: CLI value validation is total**
    - **Validates: Requirements 2.2, 2.3**
    - File `tests/test_inspector_cli.py`

  - [x]* 9.4 Write CLI and configuration example tests
    - `--interactiveInspector True` reaching `VisualizationConfig.interactive_inspector` (2.1); the argparse inventory snapshot over option strings, `nargs` and `default` for every pre-existing argument (2.2); default `False` on both the parser and the dataclass (1.2); exit codes for a successful and a failing headless run (1.7); the SVG landing beside the PNG in the run folder (3.6); exactly one `.inspector.jsonl` and one `.inspector-index.json` per run (12.8); a run with no display available still writing every artifact (1.12); `open` on the Plan_File called the same number of times with the Inspector on and off (6.10); the mocked Azure service call count unchanged in Live mode (10.5)
    - File `tests/test_inspector_cli.py`
    - _Requirements: 1.2, 1.7, 1.12, 2.1, 2.2, 3.6, 6.10, 10.5, 12.8_

- [x] 10. Add the Inspector_Bridge to `cloudhorus_webui.py`
  - [x] 10.1 Implement the three bridge read methods
    - `get_interaction_layer(png_path)` returning the `<diagram>.svg` text, or `None` when absent or unreadable
    - `read_inspector_index(png_path)` reading `<diagram>.inspector-index.json`, cached per resolved path, returning `None` with the path logged at warning level on invalid JSON
    - `read_inspector_record(png_path, inspector_key)` opening the JSONL in binary mode, seeking the indexed offset, reading exactly the indexed length, decoding UTF-8 and parsing one object; an unknown key, an offset past EOF, a truncated line or invalid JSON returns `None` after a debug log
    - Catch `OSError`, `ValueError`, `UnicodeDecodeError` and `json.JSONDecodeError` in every body so no bridge call raises into pywebview
    - _Requirements: 12.1, 13.3, 13.4, 13.5, 13.6_

  - [x] 10.2 Marshal the toggle into the generated command
    - `_build_command` appends `--interactiveInspector True` when the toggle is on, in every input mode, changing no other argument of the payload
    - _Requirements: 2.5, 2.8_

  - [x]* 10.3 Write property test for reader soundness
    - **Property 11: Reader soundness**
    - **Validates: Requirements 12.1, 13.4, 13.5, 14.11**
    - File `tests/test_inspector_payload.py`, asserting the byte count read never exceeds the indexed length

- [x] 11. Checkpoint - CLI, service layer and bridge
  - Ensure all tests pass, ask the user if questions arise.

- [x] 12. Build the WebUI front end
  - [x] 12.1 Extend the Node stub-DOM harness with the three additions
    - A `pywebview.api` stub for `get_interaction_layer`, `read_inspector_index` and `read_inspector_record` returning fixture data from the snippet's scope, plus a deferred variant for the loading indicator and a `null`-returning variant for the missing-payload and unknown-key paths
    - `DOMParser`, `querySelectorAll` and `closest` on the stub: a small XML-ish parser producing `StubElement` trees with `tagName`, `id`, `attributes`, `children` and `textContent`, and `closest(selector)` walking `parentElement`
    - A `getBBox()` returning fixed geometry so hit-rect insertion is asserted structurally
    - File `tests/webui_dom_harness.js`, keeping the existing `showImage` / `initPanZoom` stubs and the `requires_node` skip discipline intact
    - _Requirements: 8.3, 8.9, 8.10, 9.2, 9.3, 9.4, 9.8, 13.1, 13.2, 13.12_

  - [x] 12.2 Extend `webui/index.html`
    - An Inspector_Mode toggle in the options card, visible in Live, Bicep, Terraform source, Terraform JSON and Plan_Diff_Mode, defaulted to off
    - `#viewer-stage` wrapping the existing `#viewer-img` so the SVG inlines as a sibling under one shared transform, plus the `#viewer-layer-toggle` control
    - `#inspector-panel`: identity header with name, type, resource group, address, Change_Category badge and close button; the Attribute_State legend; the changed-only toggle; the filter box; the copy button; a scrollable attribute table; a truncation notice line
    - _Requirements: 2.4, 5.5, 5.9, 5.10, 5.12, 7.12, 8.8, 12.9_

  - [x] 12.3 Add Inspector state and command marshalling to `webui/app.js`
    - `state.interactiveInspector`, `state.inspectorIndex`, `state.inspectorKey`, `state.viewerLayer`
    - `buildCommandArgs()` and `buildCommandString()` emitting `--interactiveInspector True` when the toggle is on, so the displayed preview matches the command that will run
    - _Requirements: 2.5, 2.6, 2.8_

  - [x] 12.4 Inline and sanitise the Interaction_Layer
    - `showInteractionLayer(pngPath)`: `get_interaction_layer` → `DOMParser.parseFromString(text, "image/svg+xml")` → reject on `parsererror` → remove every `<script>` element and every `on*` attribute → `document.importNode` into `#viewer-stage`, never through `innerHTML`
    - `attachHitTargets()`: per `g.node`, `getBBox()` → prepend `<rect class="ch-hit" fill="transparent" pointer-events="all">` and set `tabindex="0"` and `role="button"` with the resource display name as the accessible name; clusters keep their filled `<polygon>` as the hit area
    - Fall back to the PNG in `#viewer-img` with the layer toggle hidden when the bridge returns no layer
    - _Requirements: 3.9, 8.3, 8.9, 13.2, 13.12_

  - [x] 12.5 Wire selection, panel lifecycle and the layer toggle
    - One delegated `click` and `keydown` listener on the stage: `event.target.closest("g.node, g.cluster")` → `querySelector("title").textContent` → Inspector_Key → `read_inspector_record`; Enter and Space open the panel
    - Escape and the close control hide the panel and return focus to the opener; a second activation replaces the displayed record; the selection indicator carries a stroke change, not only a colour
    - Retarget `initPanZoom`, `zoomIn`, `zoomOut` and `zoomReset` from `#viewer-img` to `#viewer-stage` so pan, zoom, fullscreen and the Change_Filter stay operable with the panel open and the zoom factor survives the layer switch
    - Clear `state.inspectorIndex`, `state.inspectorKey`, the previous SVG and the panel content when a new generation run completes; show the loading indicator until the record resolves and `No configuration available for this resource` for a key with no record
    - _Requirements: 5.1, 8.1, 8.2, 8.4, 8.5, 8.6, 8.7, 8.8, 8.10, 8.11, 9.2, 9.3, 9.4, 9.8, 13.1, 13.7_

  - [x] 12.6 Implement `renderInspectorRecord`
    - Identity header, Change_Category badge with the diagram Flag_Token, and the Attribute_State legend read from the Inspector_Index `attributeStyles` rather than a second copy of the constants; badge and legend hidden for a record with no Change_Category
    - One row per Attribute_Entry with the Attribute_Flag_Token as text in a cell of its own and the colour token applied to the row; both values separately labelled for `changed`; the same treatment for container records as for node records
    - Escape every character of every value taken from the payload; render `(sensitive)`, `(known after apply)` and `(truncated)` verbatim; per-state counts; the filter box and changed-only toggle hiding rows; the copy control writing the displayed configuration to the clipboard as text
    - `Redacted attributes cannot be compared` when an entry holds the Redaction_Literal on both sides; the truncation notice for applied Truncation_Reasons and a non-zero omitted count; an out-of-set Attribute_State rendered with the `unchanged` presentation and logged at warning level
    - _Requirements: 5.5, 5.6, 5.9, 5.10, 5.11, 5.12, 7.6, 7.7, 7.8, 7.9, 7.10, 7.11, 7.12, 7.13, 9.7, 10.3, 10.6, 11.8, 12.9, 13.8, 13.12_

  - [x] 12.7 Extend `webui/styles.css`
    - Panel layout, attribute-row colour tokens, flag cell, legend, selection indicator stroke, hit-rect transparency
    - _Requirements: 7.10, 8.7_

  - [x]* 12.8 Write property test for panel markup
    - **Property 20: Panel markup carries the state cue as text and never as live markup**
    - **Validates: Requirements 7.6, 7.7, 7.8, 7.9, 7.10, 7.13, 9.7, 13.12**
    - File `tests/test_inspector_webui.py`, driven by `markup_strings()` against the row formatter called directly in the harness

  - [x]* 12.9 Write property test for toggle marshalling
    - **Property 18: Toggle marshalling is mode-independent**
    - **Validates: Requirements 2.5, 2.6, 2.8**
    - File `tests/test_inspector_webui.py`

  - [x]* 12.10 Write WebUI DOM example tests
    - Toggle present and defaulted off (2.4); click and Enter/Space opening the panel (8.1, 8.2); Escape and the close control returning focus (8.4); a second activation replacing the record (8.5); zoom operable with the panel open (8.6); the selection indicator adding a stroke class (8.7); the layer toggle preserving the zoom factor (8.8); the loading indicator before the deferred bridge resolves (8.10); an unknown key showing `No configuration available for this resource` (8.11); identity header and category badge with the Flag_Token (5.5, 5.6); filter box and changed-only toggle (5.9, 5.10); per-state counts (5.11); the copy control against a clipboard stub (5.12); both values labelled for a `changed` row (7.11); the legend (7.12); the truncation notice (12.9); badge and legend hidden without a category and shown with one (10.3, 10.6); `Redacted attributes cannot be compared` (11.8); missing-payload and missing-layer fallbacks (13.1, 13.2); state cleared between runs (13.7); nested resolution returning the subnet inside it, the vnet outside every subnet, and the node inside a node (9.2, 9.3, 9.4, 9.8)
    - File `tests/test_inspector_webui.py`, marked `requires_node`
    - _Requirements: 2.4, 5.5, 5.6, 5.9, 5.10, 5.11, 5.12, 7.11, 7.12, 8.1, 8.2, 8.4, 8.5, 8.6, 8.7, 8.8, 8.10, 8.11, 9.2, 9.3, 9.4, 9.8, 10.3, 10.6, 11.8, 12.9, 13.1, 13.2, 13.7_

- [x] 13. Checkpoint - WebUI front end
  - Ensure all tests pass, ask the user if questions arise.

- [x] 14. Verify performance and export compatibility
  - [x]* 14.1 Write the performance benchmarks
    - Requirement 12.6: numerator over-stating the Inspector's cost at the full 5000 resources (the `collect_inspector_values` build delta with the resource counts asserted equal first, plus `build_payload` over 5000 elements, plus `write_inspector_payload`, plus `embed_svg_icons` over 5000 `<image>` elements) against a denominator under-stating the total (one faked-layout `generate_resource_graph` pass at the documented smaller resource count), layout excluded from both sides, cheap paths at the minimum of three repetitions, percentages printed under `capsys.disabled()`
    - Requirement 12.7: a 500-record payload on disk, then `read_inspector_index` followed by `read_inspector_record`, taking the maximum over all 500 keys; the DOM render is excluded and the exclusion documented in the module docstring
    - File `tests/test_inspector_performance.py`, `pytestmark = pytest.mark.performance`
    - _Requirements: 12.6, 12.7_

  - [x]* 14.2 Write the Draw.io export parity test
    - One export with Inspector_Mode on and one with it off over the same input, comparing the `.drawio` bytes and asserting sensitive values are absent; requires the real `dot` binary and `graphviz2drawio`, so it carries the same skip marker as the parity module and stays outside the property suite
    - File `tests/test_inspector_parity.py`
    - _Requirements: 1.8_

  - [x]* 14.3 Write the end-to-end CLI integration test
    - One `--interactiveInspector True` run over a fixture plan, asserting through `DotAnalyzer` that every drawn node and cluster has an index entry and that the PNG, SVG, JSONL and index all exist; plus the sample-plan regression anchor over `samples/terraform-modular/generated/network.plan.json` and `app.plan.json`, asserting the index key set, one record's attribute rows, and the sidecar bytes matching the disabled run
    - File `tests/test_inspector_cli.py`
    - _Requirements: 1.11, 3.6, 4.1, 12.8_

- [x] 15. Final checkpoint - full suite regression
  - Ensure all tests pass, including the pre-existing suite under `tests/`, ask the user if questions arise.
  - _Requirements: 1.10_

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate the 20 universal correctness properties from the design; unit and example tests cover the criteria the prework classified as example, edge case, integration or smoke
- Property 13 and the Draw.io parity test need the real `dot` binary (and `graphviz2drawio` for the export), so their module carries a `shutil.which` skip marker; Property 5 needs a render pass with Graphviz layout faked out. Everything else runs against `src/core/inspector.py` alone
- All new parameters are trailing and defaulted, and Inspector_Mode off keeps executing `dot.render(output_filename, format="png")`, which is what keeps the headless pipeline path byte-identical

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "5.1"] },
    { "id": 1, "tasks": ["1.3", "5.2"] },
    { "id": 2, "tasks": ["1.4", "4.1"] },
    { "id": 3, "tasks": ["1.5", "1.7", "4.2"] },
    { "id": 4, "tasks": ["1.6", "1.8", "4.3"] },
    { "id": 5, "tasks": ["3.1", "1.9", "4.4"] },
    { "id": 6, "tasks": ["3.2", "1.10", "7.1", "12.1"] },
    { "id": 7, "tasks": ["3.3", "1.11", "7.2", "9.1"] },
    { "id": 8, "tasks": ["3.4", "1.12", "7.3", "9.2"] },
    { "id": 9, "tasks": ["3.5", "1.13", "7.4", "10.1"] },
    { "id": 10, "tasks": ["3.6", "7.5", "9.3", "10.2", "12.2"] },
    { "id": 11, "tasks": ["7.6", "9.4", "10.3", "12.3"] },
    { "id": 12, "tasks": ["7.7", "12.4", "14.1", "14.3"] },
    { "id": 13, "tasks": ["7.8", "12.5"] },
    { "id": 14, "tasks": ["7.9", "12.6", "14.2"] },
    { "id": 15, "tasks": ["12.7", "12.8"] },
    { "id": 16, "tasks": ["12.9"] },
    { "id": 17, "tasks": ["12.10"] }
  ]
}
```
