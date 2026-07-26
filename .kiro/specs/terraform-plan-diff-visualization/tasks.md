# Implementation Plan: Terraform Plan Diff Visualization

## Overview

Implementation follows the design's additive strategy, in Python 3 against the existing CloudHorus stack: build the pure `src/core/plan_diff.py` module first (classification, change model, filtering), then extend the renderer contract with an optional `change_category`, then make `TerraformTemplateBuilder` plan-aware (delete reconstruction, sensitive redaction, metadata), then add label-level change styling plus legend and Change_Summary in the graph pipeline, and finally wire the CLI, service layer, and WebUI. Every new parameter is trailing and defaulted so Legacy_Modes keep byte-identical output.

Property-based tests use Hypothesis and share the strategy module `tests/strategies/plan_json.py`. Each correctness property from the design gets exactly one property test.

## Tasks

- [x] 1. Build the change extraction core
  - [x] 1.1 Create `src/core/plan_diff.py` with the change model foundations
    - Define `CHANGE_CATEGORIES`, `KNOWN_ACTIONS`, `SUPPORTED_PROVIDER_NAMES` (mirroring `terraform_builder._SUPPORTED_PROVIDER_NAMES`)
    - Add frozen `ChangeRecord` dataclass (`address`, `category`, `actions`, `terraform_type`, `provider_name`)
    - Add `ChangeModel` dataclass with `records`, `counts`, `warnings` and the methods `category_for`, `has_changes`, `present_categories`, `to_metadata`, `from_metadata`
    - Enforce the invariant that `counts` has exactly one entry per Change_Category, absent categories at `0`
    - _Requirements: 2.2, 2.9, 2.11, 4.4_

  - [x] 1.2 Implement `ChangeExtractor.classify`
    - Apply the decision table in order: `replace` when `actions` contains both `create` and `delete`, then `["create"]`, `["update"]`, `["delete"]`, `["no-op"]`/`["read"]`
    - Return `unchanged` plus a warning for unknown action values, a missing `change` object, and a missing or non-list `actions`
    - Return the raw actions tuple alongside the category so the record retains the original array
    - _Requirements: 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 9.6_

  - [x] 1.3 Implement `ChangeExtractor.extract`
    - Single pass over `resource_changes`, skipping entries whose `mode != "managed"`, whose `address` is missing, or whose `provider_name` is unsupported, each with a warning
    - Key records by the full Terraform address including module prefixes; keep the first record on a duplicate address and warn
    - Derive `counts` from the retained records; return an empty model plus a type-mismatch warning when `resource_changes` is not a list
    - Hold at most one record per managed entry in memory
    - _Requirements: 2.1, 2.9, 2.10, 2.11, 9.4, 9.7, 9.8, 11.4_

  - [x] 1.4 Add Hypothesis and the shared plan JSON strategies
    - Add `hypothesis>=6.100` to the `dev` extra in `pyproject.toml`
    - Create `tests/strategies/plan_json.py` with `terraform_addresses`, `action_arrays`, `resource_change_entries`, `azurerm_resource_values`, `sensitive_masks`, `plan_documents`, `change_filters`, and a recursive arbitrary-JSON strategy
    - _Requirements: 12.1, 12.2, 12.3, 12.8_

  - [x] 1.5 Write property test for classification totality
    - **Property 1: Classification totality and closure**
    - **Validates: Requirements 2.2, 2.8, 9.6, 12.1**
    - File `tests/test_plan_diff_extractor.py`

  - [x] 1.6 Write property test for the action decision table
    - **Property 2: Classification follows the action decision table**
    - **Validates: Requirements 2.3, 2.4, 2.5, 2.6, 2.7**
    - File `tests/test_plan_diff_extractor.py`

  - [x] 1.7 Write property test for count conservation
    - **Property 3: Count conservation**
    - **Validates: Requirements 2.11, 12.2**
    - File `tests/test_plan_diff_extractor.py`

  - [x] 1.8 Write property test for extraction membership and address keying
    - **Property 4: Extraction membership and address keying**
    - **Validates: Requirements 2.1, 2.9, 2.10, 9.4, 9.7, 9.8, 11.4**
    - File `tests/test_plan_diff_extractor.py`

- [x] 2. Checkpoint - change extraction
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Implement the change filter as a pure document transform
  - [x] 3.1 Implement `parse_change_types`
    - Return every category for `None`, validate values against `CHANGE_CATEGORIES`, raise a `ValueError` naming the accepted values for anything else
    - _Requirements: 6.10, 8.3_

  - [x] 3.2 Implement `ChangeFilter.apply` direct selection and container retention
    - Return a new `LocalTemplateDocument`, leaving inputs untouched; identity transform when the selection is every category
    - Keep resources whose `change_category` is in the selection and resources whose `change_category` is `None`
    - Re-admit dropped virtual networks and subnets referenced by a kept resource through `dependsOn` resource-id expressions, subnet-id-bearing properties (`virtualNetworkSubnetId`, `subnet.id`, `agentPoolProfiles[].vnetSubnetID`, `ipConfigurations[].properties.subnet.id`, `gatewayIPConfigurations[].properties.subnet.id`), or the `"<vnet>/<subnet>"` name relation; a retained subnet re-admits its parent VNet
    - _Requirements: 6.3, 6.6, 6.11_

  - [x] 3.3 Implement embedded-subnet pruning and edge pruning
    - Remove dropped subnets from every VNet's `properties["subnets"]` list so no orphan cluster renders
    - Drop `dependsOn` entries whose target is outside the kept set and subnet-id-bearing property keys pointing at dropped subnets
    - Keep both passes dependent only on the kept set so the transform is a fixpoint and order-independent
    - _Requirements: 6.4, 6.5, 6.7_

  - [x] 3.4 Write property test for filter completeness
    - **Property 13: Filter completeness**
    - **Validates: Requirements 6.3, 6.6, 12.3**
    - File `tests/test_plan_diff_filter.py`

  - [x] 3.5 Write property test for filter idempotence
    - **Property 14: Filter idempotence**
    - **Validates: Requirements 6.4, 12.4**
    - File `tests/test_plan_diff_filter.py`

  - [x] 3.6 Write property test for filter order independence
    - **Property 15: Filter order independence**
    - **Validates: Requirements 6.5, 12.5**
    - File `tests/test_plan_diff_filter.py`

  - [x] 3.7 Write property test for filter monotonicity
    - **Property 16: Filter monotonicity**
    - **Validates: Requirements 12.9**
    - File `tests/test_plan_diff_filter.py`

  - [x] 3.8 Write property test for edge and container integrity after filtering
    - **Property 17: Edge and container integrity after filtering**
    - **Validates: Requirements 6.7, 6.11**
    - File `tests/test_plan_diff_filter.py`

- [x] 4. Extend the renderer contract additively
  - [x] 4.1 Add the optional `change_category` field to `LocalTemplateResource`
    - Trailing, defaulted to `None`, in `src/cloudhorus/models/local_template_document.py`
    - Emit `changeCategory` from `to_renderer_resource()` only when the field is set, after `dependsOn` and `extra_fields`
    - Leave `to_renderer_template()` untouched so `metadata` forwarding stays as is
    - _Requirements: 4.1, 4.2, 4.3_

  - [x] 4.2 Write property test for the Change_Model round trip
    - **Property 8: Change_Model round trip through the Renderer_Template**
    - **Validates: Requirements 4.1, 4.2, 4.4, 12.7**
    - File `tests/test_plan_diff_resources.py`

  - [x] 4.3 Write property test for legacy renderer template parity
    - **Property 9: Legacy inputs produce an unchanged Renderer_Template**
    - **Validates: Requirements 4.3, 8.1**
    - File `tests/test_plan_diff_legacy_parity.py`

- [x] 5. Make the Terraform builder plan-aware
  - [x] 5.1 Add sensitive redaction helpers to `src/core/terraform_builder.py`
    - `_sensitive_mask_for(terraform_json, address, phase)` resolving `after_sensitive`, `before_sensitive`, and the planned resource's `sensitive_values`
    - `_redact_sensitive(values, mask)` walking the value tree in parallel with the mask, replacing flagged leaves with the literal `(sensitive)` and preserving every other leaf
    - _Requirements: 10.1_

  - [x] 5.2 Implement `_reconstruct_deleted_resources`
    - For every `delete` record whose address is absent from `planned_values`, build `{address, mode: "managed", type, name, provider_name, values: change.before}` so `_normalize_resource` applies the existing type mapping and property normalization
    - Pass the address so `_build_resource_name` falls back to it when `before` carries no `name`
    - _Requirements: 3.1, 3.2, 3.4_

  - [x] 5.3 Add `change_model` support to `build_document_from_json`
    - Append reconstructed delete resources to the collected `planned_values` resources, deduplicating by address before normalization and preferring `planned_values` values for `replace` addresses
    - Redact sensitive leaves before normalization, using `after_sensitive` for planned resources and `before_sensitive` for reconstructed deletes
    - Set `change_category` per resource, defaulting to `unchanged` for planned resources absent from `resource_changes`
    - Extend `metadata` with `changeCounts`, `changeModel`, and `changesNotDisplayed`; keep dependency edges flowing through the existing configuration-driven mechanism so references to removed addresses drop out
    - _Requirements: 3.3, 3.5, 4.1, 4.4, 10.1_

  - [x] 5.4 Add `change_types` orchestration to `build_terraform_template`
    - Keep the exact legacy path when `resource_changes` is absent
    - Otherwise extract the Change_Model, build the document with it, apply `ChangeFilter(parse_change_types(change_types))`, and write the same temp-file renderer template
    - Report `Plan contains no resource changes` for an empty `resource_changes` array; keep the existing exception guard returning `None`
    - _Requirements: 1.1, 1.2, 6.9, 9.1, 9.3, 9.5_

  - [x] 5.5 Write property test for delete reconstruction completeness
    - **Property 5: Delete reconstruction completeness and address uniqueness**
    - **Validates: Requirements 3.1, 3.3, 3.4**
    - File `tests/test_plan_diff_resources.py`

  - [x] 5.6 Write property test for normalization equivalence of reconstructed resources
    - **Property 6: Reconstruction uses the same normalization as planned values**
    - **Validates: Requirements 3.2**
    - File `tests/test_plan_diff_resources.py`

  - [x] 5.7 Write property test for dependency preservation on deleted resources
    - **Property 7: Dependency references of deleted resources are preserved**
    - **Validates: Requirements 3.5**
    - File `tests/test_plan_diff_resources.py`

  - [x] 5.8 Write property test for sensitive leaf masking
    - **Property 19: Sensitive leaves are masked and non-sensitive leaves are untouched**
    - **Validates: Requirements 10.1**
    - File `tests/test_plan_diff_resources.py`

  - [x] 5.9 Write property test for no unhandled failure on arbitrary JSON plans
    - **Property 22: No unhandled failure for any JSON plan input**
    - **Validates: Requirements 9.1, 9.9, 12.8**
    - File `tests/test_plan_diff_extractor.py`

  - [x] 5.10 Write unit tests for malformed plan input
    - Truncated JSON reporting the file path and parse position, document lacking both `planned_values` and `values`, empty `resource_changes` emitting `Plan contains no resource changes`
    - File `tests/test_plan_diff_cli.py`
    - _Requirements: 9.2, 9.3, 9.5_

- [x] 6. Checkpoint - plan parsing and filtering
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Encode change state in the diagram
  - [x] 7.1 Create `src/utils/change_style.py`
    - `ChangeStyle` holder plus the `CHANGE_STYLES` table (`create` `#107C10` `+`, `update` `#0078D4` `~`, `replace` `#D13438` `±`, `delete` `#D13438` `-`, `unchanged` none)
    - `resolve_style` returning `None` for `None`/`unchanged` and warning once for out-of-set values
    - `decorate_label` wrapping the existing HTML table label with a coloured border and prepending the Flag_Token; `legend_label` building the Legend HTML table
    - _Requirements: 4.6, 5.1, 5.2, 5.3, 5.4, 5.9, 10.2_

  - [x] 7.2 Add `change_category` to `add_node_in_subgraph`
    - Trailing optional parameter in `src/utils/graph_utils.py` and the mirrored `src/cloudhorus/utils/graph_utils.py`
    - Decorate only `node_label` through `resolve_style`/`decorate_label`; never touch `shape`, `image`, `imagescale`, `imagepos`, `width`, `height`, `margin`, `fontsize`, or `group`
    - _Requirements: 4.5, 4.6, 5.5, 5.6, 8.6_

  - [x] 7.3 Plumb change state through `src/core/graph_generator.py`
    - Add trailing `change_types=None` to `generate_resource_graph` and `_generate_resource_graph_inner`, forwarded to `build_terraform_template`
    - Build the per-template `change_index` keyed by `(resource_name, resource_type)` from the registered template dict, and accumulate aggregate counts and summary entries across templates
    - Pass the category at the resource-group node call site and the subnet-placed node call site
    - _Requirements: 1.1, 4.5, 5.1, 5.2, 5.3, 5.4, 5.5, 6.9_

  - [x] 7.4 Render the Legend cluster
    - Add a `cluster_change_legend` subgraph with one HTML-label node listing each present category with its colour swatch, Flag_Token, and count
    - Guard the whole block on Plan_Diff_Mode with at least one non-`unchanged` category so Legacy_Modes and all-unchanged plans emit no legend
    - _Requirements: 5.7, 5.8_

  - [x] 7.5 Build the Change_Summary in `src/core/plan_diff.py`
    - `ChangeSummary` holder, `build_change_summary(model, document, unmapped, skipped)` classifying undisplayed changes with reasons `skip-filter`, `unmapped-type`, `no-resource-entry` (reusing `should_skip` for the Skip_Filter), and `format_change_summary` producing the console lines
    - Exclude sensitive values from the summary payload
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 10.3_

  - [x] 7.6 Log the Change_Summary and write the sidecar JSON
    - Log the formatted lines through `logger.info` in the Plan_Diff_Mode guarded block only
    - Write `azure_resources_<timestamp>.change-summary.json` beside the PNG with `counts`, `presentCategories`, `notDisplayed`, and `changeStyles`; downgrade a write failure to a warning
    - _Requirements: 7.1, 7.5, 7.6_

  - [x] 7.7 Write property test for node attribute preservation
    - **Property 10: Node attributes outside the label are never modified**
    - **Validates: Requirements 4.5, 4.6, 5.5, 5.6, 8.6**
    - File `tests/test_plan_diff_rendering.py`

  - [x] 7.8 Write property test for change styling inside the label
    - **Property 11: Change styling maps categories to colour and flag inside the label**
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.9**
    - File `tests/test_plan_diff_rendering.py`

  - [x] 7.9 Write property test for legend presence and content
    - **Property 12: Legend presence and content follow the Change_Model**
    - **Validates: Requirements 5.7, 5.8**
    - File `tests/test_plan_diff_rendering.py`

  - [x] 7.10 Write property test for sensitive values never reaching an output surface
    - **Property 20: Sensitive values never reach an output surface**
    - **Validates: Requirements 10.2, 10.3, 10.4, 10.5**
    - File `tests/test_plan_diff_rendering.py`

  - [x] 7.11 Write property test for DOT parity on all-unchanged plans
    - **Property 21: Unchanged plans render byte-identical DOT**
    - **Validates: Requirements 12.6**
    - File `tests/test_plan_diff_rendering.py`

  - [x] 7.12 Write property test for rendered-or-reported changes
    - **Property 18: Every change is either rendered or reported**
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.6**
    - File `tests/test_plan_diff_reporting.py`

  - [x] 7.13 Write property test for plan diff activation and scope parity
    - **Property 23: Plan diff activation and scope resolution parity**
    - **Validates: Requirements 1.1, 1.2, 1.7**
    - File `tests/test_plan_diff_reporting.py`

- [x] 8. Checkpoint - rendering and reporting
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Wire the service layer and the CLI
  - [x] 9.1 Add `change_types` to the configuration and service layer
    - Trailing `change_types: Optional[List[str]] = None` on `VisualizationConfig` in `src/cloudhorus/models/configuration.py`
    - Trailing `change_types` parameter on `GraphGeneratorService.generate_graph`, forwarded to `generate_resource_graph`
    - _Requirements: 8.2, 8.3_

  - [x] 9.2 Add `--changeTypes` and plan input validation to `src/main.py`
    - `--changeTypes` with `nargs="+"` and `default=None`, forwarded into the visualization config
    - Fail with `Choose exactly one Terraform input: plan JSON or source directories` and a non-zero exit when plan JSON and Terraform source are both selected, checked before the existing generic multi-mode message
    - Validate values through `parse_change_types`, logging the accepted values and exiting non-zero on an invalid value; warn when `--changeTypes` is supplied outside Terraform JSON mode
    - Leave the existing path-existence loop, `--scopeMetadataFiles` handling, and output path pattern untouched
    - _Requirements: 1.1, 1.5, 1.6, 1.7, 6.9, 6.10, 8.2, 8.3, 8.5_

  - [x] 9.3 Write CLI example tests
    - Mutual-exclusion message and exit code, missing plan path, invalid `--changeTypes` value listing accepted values, `--changeTypes` default, argparse inventory snapshot over name/`nargs`/`default` for every pre-existing argument, PNG output path pattern
    - File `tests/test_plan_diff_cli.py`
    - _Requirements: 1.5, 1.6, 6.10, 8.2, 8.3, 8.5_

  - [x] 9.4 Write integration test for a filtered CLI run
    - End-to-end run with `--changeTypes delete` against a fixture plan, asserting through `DotAnalyzer` that only delete resources and their retained containers appear
    - _Requirements: 6.9, 6.11_

- [x] 10. Expose plan diff in the WebUI
  - [x] 10.1 Extend `cloudhorus_webui.py`
    - `pick_files` branch `"terraform-plan"` with `.json` file types
    - `_build_command` marshalling `--terraformJsonFiles` when a plan is selected, keeping `--terraformRootDirs`/`--terraformVarFiles` otherwise, and appending `--changeTypes` for a strict subset
    - `read_change_summary(png_path)` reading the sidecar beside the PNG, and `rerun_with_change_types(args_json, change_types)`
    - _Requirements: 1.3, 1.4, 6.9, 7.5, 8.8_

  - [x] 10.2 Extend `webui/index.html`
    - Third drop zone `#drop-terraform-plan` with `#file-list-terraform-plan` inside `#section-terraform-files`, leaving the `main.tf` and `.tfvars` zones untouched
    - Hidden-by-default `#change-filter-panel` in the viewer header with chip container and an undisplayed-changes badge
    - _Requirements: 1.3, 1.4, 6.1, 7.5, 8.8_

  - [x] 10.3 Extend `webui/app.js`
    - `state.terraformPlanFiles`, `state.changeTypes`, `state.changeSummary`; `pickTerraformPlanFiles()` filtered to `.json`
    - `validate()` rejecting plan JSON plus `main.tf` in the same run with the Requirement 1.5 message before the subprocess starts
    - `buildCommandArgs()`/`buildCommandString()` emitting `--terraformJsonFiles` and `--changeTypes`; `selectMode()` hiding the filter panel for live, bicep, and Terraform source selections
    - Populate chips from the change summary with every present category selected; chip toggle shows the progress indicator and re-runs generation; empty selection shows `No resources match the selected change types` and keeps the current `#viewer-img`
    - _Requirements: 6.1, 6.2, 6.3, 6.8, 7.5, 8.4, 11.3_

  - [x] 10.4 Write WebUI marshalling and DOM tests
    - `_build_command` argument emission, source-only behaviour, `read_change_summary`, chip rendering and initial selection, all-deselected message, undisplayed badge, filter panel hidden in Live/Bicep/Terraform-source modes, progress indicator during a filtered re-run
    - File `tests/test_plan_diff_webui.py`
    - _Requirements: 1.3, 6.1, 6.2, 6.8, 7.5, 8.4, 8.8, 11.3_

- [x] 11. Verify performance and export compatibility
  - [x] 11.1 Write performance benchmarks for large plans
    - Extraction of 5000 managed change entries under 5 seconds; diff-enabled versus diff-disabled generation keeping added runtime under 10 percent of total generation runtime
    - _Requirements: 11.1, 11.2_

  - [x] 11.2 Write Draw.io export test for a plan diff diagram
    - Assert the export completes and writes a non-empty `.drawio` file with change-decorated labels present, and that sensitive values are absent
    - _Requirements: 8.6, 8.7, 10.5_

- [x] 12. Final checkpoint - full suite regression
  - Ensure all tests pass, including the pre-existing suite under `tests/`, ask the user if questions arise.
  - _Requirements: 8.9_

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate the universal correctness properties from the design; unit and example tests cover the criteria classified as example or edge case
- All new parameters are trailing and defaulted, which is what keeps Legacy_Mode output identical

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.4"] },
    { "id": 1, "tasks": ["1.2", "4.1"] },
    { "id": 2, "tasks": ["1.3", "7.1"] },
    { "id": 3, "tasks": ["3.1", "1.5", "7.2"] },
    { "id": 4, "tasks": ["3.2", "1.6", "5.1"] },
    { "id": 5, "tasks": ["3.3", "1.7", "5.2", "4.3"] },
    { "id": 6, "tasks": ["7.5", "1.8", "5.3", "3.4"] },
    { "id": 7, "tasks": ["5.4", "3.5", "7.3", "4.2"] },
    { "id": 8, "tasks": ["5.9", "3.6", "7.4", "5.5", "9.1"] },
    { "id": 9, "tasks": ["3.7", "7.6", "5.6", "9.2", "7.7"] },
    { "id": 10, "tasks": ["3.8", "5.7", "7.8", "5.10", "10.1"] },
    { "id": 11, "tasks": ["5.8", "7.9", "9.3", "10.2", "7.12"] },
    { "id": 12, "tasks": ["7.10", "10.3", "7.13", "11.1"] },
    { "id": 13, "tasks": ["7.11", "10.4", "9.4", "11.2"] }
  ]
}
```
