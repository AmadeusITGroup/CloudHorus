# Requirements Document

## Introduction

CloudHorus renders Azure architecture diagrams from three input families today: live Azure subscriptions, Bicep templates, and Terraform inputs. On the Terraform side, `TerraformTemplateBuilder` already accepts either local HCL source (`--terraformRootDirs` + `--terraformVarFiles`, exposed in the WebUI Terraform mode card) or a `terraform show -json` document (`--terraformJsonFiles`, CLI only). Both paths normalize into `LocalTemplateDocument` and are flattened by `to_renderer_template()` into the ARM-shaped renderer contract consumed by the graph pipeline, which renders a single PNG through Graphviz.

This feature adds a Terraform **plan diff** capability. The operator supplies a plan JSON document, and CloudHorus not only draws the resulting architecture but also encodes *what the plan will do* to every resource: delete, update, replace, create, or leave unchanged. Change state is carried as additive metadata through the existing normalization contract, rendered as a colour plus a text flag on each resource node, summarized in a legend and counters, and made filterable so the operator can isolate, for example, only the resources scheduled for deletion.

Two grounded facts drive the scope:

1. The `resource_changes` array of a plan JSON is currently ignored by the codebase (no reference exists anywhere in `src/`). All change semantics are new.
2. `planned_values` only describes post-apply state, so resources scheduled for deletion are **absent** from it. Delete nodes must be reconstructed from the plan's change records, otherwise the most business-critical part of the diff would be invisible.

The feature must extend the legacy stack additively: Live mode, Bicep mode, Terraform source mode, the existing `--terraformJsonFiles` behaviour, PNG output, and Draw.io export must keep working with unchanged results when no plan diff input is supplied.

## Glossary

- **CloudHorus**: The complete application, comprising the CLI entry point (`src/main.py`), the desktop WebUI host (`cloudhorus_webui.py`), and the rendering pipeline.
- **Plan_File**: A JSON document produced by `terraform show -json <planfile>`, containing `format_version`, `planned_values`, and optionally `resource_changes`, `prior_state`, and `configuration`.
- **Plan_Parser**: The component that loads and validates a Plan_File, extending `TerraformTemplateBuilder.load_terraform_json`.
- **Change_Extractor**: The new component that reads the `resource_changes` array of a Plan_File and produces one Change_Record per managed resource address.
- **Change_Record**: A normalized entry holding the resource address, the resolved Change_Category, and the ordered raw `actions` array from the Plan_File.
- **Change_Category**: Exactly one value from the closed set {`create`, `update`, `replace`, `delete`, `unchanged`}.
- **Change_Model**: The collection of all Change_Records for one Plan_File, plus per-category counts.
- **Renderer_Template**: The ARM-shaped dictionary returned by `LocalTemplateDocument.to_renderer_template()` and consumed by the graph pipeline.
- **Graph_Pipeline**: `GraphGeneratorService` together with `core/graph_generator.py` and `GraphBuilderService`, which convert a Renderer_Template into a Graphviz graph.
- **Diagram**: The PNG artifact produced by the Graph_Pipeline, displayed in the WebUI viewer element `viewer-img`.
- **Change_Style**: The triple (colour token, Tint, Flag_Token) applied to a Change_Surface for a given Change_Category.
- **Tint**: The colour token of a Change_Category blended 15 percent into white, used as the Change_Surface background so the resource icon stays visible on top of it.
- **Change_Surface**: The visual element a Change_Category decorates. For a resource drawn as a node it is that node, icon and label together. For a resource drawn as a container, namely a virtual network or a subnet, it is that container's cluster.
- **Flag_Token**: A short text marker rendered inside a resource node label, independent of colour: `+` for create, `~` for update, `±` for replace, `-` for delete, and no marker for unchanged.
- **Legend**: A visual block inside the Diagram that maps each Change_Category present in the Change_Model to its Change_Style.
- **Change_Summary**: A structured report listing per-category resource counts and the addresses of changes that the Diagram does not display.
- **Change_Filter**: The selection of Change_Categories that the operator wants displayed, expressed as a set.
- **Legacy_Mode**: Any pre-existing input mode: Live mode, Bicep mode, Terraform source mode, and Terraform JSON mode without plan diff.
- **Plan_Diff_Mode**: The new input mode in which a Plan_File is supplied and change encoding is active.
- **Skip_Filter**: The existing `ResourceFilter` component, which removes resource types such as `Microsoft.Network/networkSecurityGroups/*` and `Microsoft.Network/routeTables/*` from visualization.
- **Unmapped_Resource**: A Plan_File resource whose Terraform type has no entry in the `_TERRAFORM_TO_RENDERER_TYPE` mapping table.
- **Operator**: The person running CloudHorus through the CLI or the WebUI.

## Requirements

### Requirement 1: Supply a Terraform Plan File as Input

**User Story:** As a cloud architect, I want to feed a `terraform show -json` plan document into CloudHorus from both the CLI and the WebUI, so that I can review the planned architecture without running Terraform apply.

#### Acceptance Criteria

1. WHEN the Operator provides one or more Plan_File paths through the CLI argument `--terraformJsonFiles`, THE CloudHorus SHALL activate Plan_Diff_Mode for every provided Plan_File that contains a `resource_changes` array.
2. WHEN the Operator provides a Plan_File that omits the `resource_changes` array, THE CloudHorus SHALL render the Diagram with every resource assigned the Change_Category `unchanged`.
3. THE WebUI SHALL present a Terraform plan input control that accepts files with the `.json` extension and passes the selected paths to the CLI argument `--terraformJsonFiles`.
4. WHERE the Operator selects Terraform plan input in the WebUI, THE WebUI SHALL keep the existing Terraform source controls for `main.tf` and `.tfvars` available as a separate selection.
5. IF the Operator selects both Terraform plan input and Terraform source input in the same run, THEN THE CloudHorus SHALL report the message `Choose exactly one Terraform input: plan JSON or source directories` and terminate with a non-zero exit code.
6. WHEN the Operator provides a Plan_File path that does not exist, THE CloudHorus SHALL report the missing path and terminate with a non-zero exit code.
7. WHERE the Operator provides scope metadata files through `--scopeMetadataFiles`, THE CloudHorus SHALL apply the same scope resolution to Plan_Diff_Mode that Terraform JSON mode applies today.

### Requirement 2: Extract Change Records from the Plan

**User Story:** As a cloud architect, I want CloudHorus to derive the planned action of every resource from the plan, so that the diagram reflects the exact operations Terraform will perform.

#### Acceptance Criteria

1. WHEN the Change_Extractor processes a Plan_File, THE Change_Extractor SHALL produce exactly one Change_Record for each entry of `resource_changes` whose `mode` field equals `managed`.
2. THE Change_Extractor SHALL assign exactly one Change_Category to each Change_Record, selected from {`create`, `update`, `replace`, `delete`, `unchanged`}.
3. WHEN the `actions` array of a change entry equals `["create"]`, THE Change_Extractor SHALL assign the Change_Category `create`.
4. WHEN the `actions` array of a change entry equals `["update"]`, THE Change_Extractor SHALL assign the Change_Category `update`.
5. WHEN the `actions` array of a change entry equals `["delete"]`, THE Change_Extractor SHALL assign the Change_Category `delete`.
6. WHEN the `actions` array of a change entry contains both `create` and `delete` in any order, THE Change_Extractor SHALL assign the Change_Category `replace`.
7. WHEN the `actions` array of a change entry equals `["no-op"]` or `["read"]`, THE Change_Extractor SHALL assign the Change_Category `unchanged`.
8. IF the `actions` array of a change entry contains a value outside {`create`, `update`, `delete`, `no-op`, `read`}, THEN THE Change_Extractor SHALL assign the Change_Category `unchanged`, retain the raw `actions` array in the Change_Record, and log the unrecognized value at warning level.
9. THE Change_Extractor SHALL key each Change_Record by the full Terraform address of the change entry, including module prefixes such as `module.app.azurerm_linux_web_app.api`.
10. WHEN two change entries declare the same address, THE Change_Extractor SHALL retain the first entry and log the duplicate address at warning level.
11. THE Change_Extractor SHALL populate the Change_Model with one count per Change_Category, and the sum of those counts SHALL equal the number of Change_Records.

### Requirement 3: Represent Resources Scheduled for Deletion

**User Story:** As a cloud architect, I want resources that the plan will destroy to appear in the diagram, so that I can assess the blast radius of a destructive plan.

#### Acceptance Criteria

1. WHEN a Change_Record carries the Change_Category `delete` and the resource address is absent from `planned_values`, THE Plan_Parser SHALL construct a resource entry from the `change.before` object of that change entry.
2. WHEN the Plan_Parser constructs a resource entry from `change.before`, THE Plan_Parser SHALL apply the same Terraform-type-to-renderer-type mapping and the same property normalization used for `planned_values` resources.
3. WHERE a resource address appears in both `planned_values` and a Change_Record with the Change_Category `replace`, THE Plan_Parser SHALL emit exactly one resource entry for that address.
4. WHEN the `change.before` object of a delete entry lacks a `name` value, THE Plan_Parser SHALL use the Terraform resource address as the displayed resource name.
5. WHEN dependency references of a deleted resource point to addresses that remain in the Plan_File, THE Plan_Parser SHALL preserve those dependency references so the Graph_Pipeline draws the corresponding edges.

### Requirement 4: Carry Change Metadata Through the Renderer Contract

**User Story:** As a maintainer, I want change information to travel through the existing normalization contract as optional data, so that adding the diff feature does not alter the shape consumed by Legacy_Modes.

#### Acceptance Criteria

1. WHEN a LocalTemplateResource carries a Change_Category, THE Renderer_Template SHALL expose that value on the corresponding resource entry under the key `changeCategory`.
2. WHEN a LocalTemplateResource carries no Change_Category, THE Renderer_Template SHALL omit the key `changeCategory` from that resource entry.
3. THE Renderer_Template SHALL retain the keys `type`, `name`, `properties`, and `dependsOn` with the same values that Legacy_Modes produce for the same input.
4. WHEN CloudHorus operates in Plan_Diff_Mode, THE Renderer_Template SHALL expose the per-category counts of the Change_Model under the `metadata` key.
5. WHEN the Graph_Pipeline receives a Renderer_Template whose resource entries omit `changeCategory`, THE Graph_Pipeline SHALL render the Diagram using the styling that applies to Legacy_Modes.
6. WHEN the Graph_Pipeline receives a resource entry whose `changeCategory` value falls outside the Change_Category set, THE Graph_Pipeline SHALL render that resource with the styling that applies to the Change_Category `unchanged` and log the value at warning level.

### Requirement 5: Encode Change State in the Diagram

**User Story:** As a cloud architect, I want each resource in the diagram to show its planned change through colour and a text flag, so that I can read the plan at a glance and still distinguish states without relying on colour perception.

#### Acceptance Criteria

1. WHEN the Graph_Pipeline renders a resource with the Change_Category `delete`, THE Graph_Pipeline SHALL apply the colour token `#D13438` and the Flag_Token `-` to that resource's Change_Surface.
2. WHEN the Graph_Pipeline renders a resource with the Change_Category `update`, THE Graph_Pipeline SHALL apply the colour token `#0078D4` and the Flag_Token `~` to that resource's Change_Surface.
3. WHEN the Graph_Pipeline renders a resource with the Change_Category `create`, THE Graph_Pipeline SHALL apply the colour token `#107C10` and the Flag_Token `+` to that resource's Change_Surface.
4. WHEN the Graph_Pipeline renders a resource with the Change_Category `replace`, THE Graph_Pipeline SHALL apply the colour token `#D13438` and the Flag_Token `±` to that resource's Change_Surface.
5. WHEN the Graph_Pipeline renders a resource with the Change_Category `unchanged`, THE Graph_Pipeline SHALL apply the same attributes to that resource's Change_Surface that Legacy_Modes apply to it.
5a. THE Graph_Pipeline SHALL apply the colour token as a border and its Tint as a background across the whole Change_Surface, so that a change is readable from the resource icon as well as from the label.
6. THE Graph_Pipeline SHALL render each resource icon at the same path and scale in Plan_Diff_Mode and in Legacy_Modes.
7. WHERE the Change_Model contains at least one Change_Record whose Change_Category differs from `unchanged`, THE Graph_Pipeline SHALL render a Legend that lists every Change_Category present in the Change_Model together with its colour token and Flag_Token.
8. WHERE the Change_Model contains only Change_Records with the Change_Category `unchanged`, THE Graph_Pipeline SHALL omit the Legend.
9. THE Graph_Pipeline SHALL render the Flag_Token as part of the Change_Surface label so that the Change_Category remains readable in a monochrome print of the Diagram.
10. WHERE a Change_Surface label holds a cell combining an image with text, THE Graph_Pipeline SHALL place the Flag_Token in a cell that holds no image, because Graphviz rejects a label cell that mixes the two and fails the whole render.

### Requirement 6: Filter the Architecture by Change Type

**User Story:** As a cloud architect, I want to filter the architecture view by change type, so that I can isolate the deletions or the updates of a large plan.

#### Acceptance Criteria

1. WHERE CloudHorus operates in Plan_Diff_Mode, THE WebUI SHALL present one Change_Filter control per Change_Category present in the Change_Model.
2. THE WebUI SHALL initialize the Change_Filter with every Change_Category present in the Change_Model selected.
3. WHEN the Operator changes the Change_Filter selection, THE WebUI SHALL display an architecture view that contains every resource whose Change_Category belongs to the selection and excludes every resource whose Change_Category falls outside the selection.
4. WHEN the Operator applies the same Change_Filter selection twice in a row, THE CloudHorus SHALL display the same set of resources after the second application as after the first application.
5. WHEN two Change_Filter selections contain the same Change_Categories in a different order, THE CloudHorus SHALL display the same set of resources for both selections.
6. WHEN the Change_Filter selection contains every Change_Category present in the Change_Model, THE CloudHorus SHALL display the same set of resources that an unfiltered Plan_Diff_Mode run displays.
7. WHEN the Change_Filter selection excludes a Change_Category, THE CloudHorus SHALL omit every edge whose source or target resource is excluded by the selection.
8. WHEN the Change_Filter selection excludes every Change_Category, THE WebUI SHALL display the message `No resources match the selected change types` and retain the previously displayed Diagram.
9. WHERE the Operator supplies the CLI argument `--changeTypes` with a space-separated list of Change_Category values, THE CloudHorus SHALL render the Diagram restricted to the listed Change_Categories.
10. IF the Operator supplies a `--changeTypes` value outside the Change_Category set, THEN THE CloudHorus SHALL report the accepted values and terminate with a non-zero exit code.
11. WHERE a Change_Filter selection excludes a resource that acts as a container in the Diagram, such as a virtual network or a subnet, THE CloudHorus SHALL retain that container in the Diagram when at least one displayed resource resides inside it.

### Requirement 7: Report Changes That the Diagram Does Not Display

**User Story:** As a cloud architect, I want to know which planned changes are missing from the diagram, so that I do not misread a rendered diagram as a complete plan review.

#### Acceptance Criteria

1. WHEN CloudHorus completes a Plan_Diff_Mode run, THE CloudHorus SHALL write a Change_Summary to the console output that reports the resource count per Change_Category.
2. WHEN the Skip_Filter removes a resource that carries a Change_Category other than `unchanged`, THE Change_Summary SHALL list the Terraform address of that resource under the heading `Changes not displayed`.
3. WHEN a Change_Record references an Unmapped_Resource, THE Change_Summary SHALL list the Terraform address and the Terraform type of that resource under the heading `Changes not displayed`.
4. WHEN a Change_Record references an address that the Plan_Parser produced no resource entry for, THE Change_Summary SHALL list that address under the heading `Changes not displayed`.
5. WHERE the Change_Summary lists at least one address under `Changes not displayed`, THE WebUI SHALL display the count of undisplayed changes next to the Change_Filter controls.
6. WHERE CloudHorus operates in a Legacy_Mode, THE CloudHorus SHALL omit the Change_Summary from the console output.

### Requirement 8: Preserve the Behaviour of the Legacy Stack

**User Story:** As a maintainer, I want every existing input mode and export path to behave exactly as before, so that the diff feature ships without regressions.

#### Acceptance Criteria

1. WHEN the Operator runs CloudHorus in a Legacy_Mode with a given set of arguments, THE CloudHorus SHALL produce a Renderer_Template identical to the Renderer_Template produced by the release preceding this feature for the same arguments.
2. THE CloudHorus SHALL accept every CLI argument accepted before this feature with the same name, the same arity, and the same default value.
3. THE CloudHorus SHALL treat the CLI argument `--changeTypes` as optional and SHALL default it to every Change_Category.
4. WHEN the Operator selects Live mode, Bicep mode, or Terraform source mode in the WebUI, THE WebUI SHALL hide every Change_Filter control.
5. WHEN CloudHorus renders a Diagram in a Legacy_Mode, THE CloudHorus SHALL write the PNG artifact to the same output path pattern used before this feature.
6. WHERE the Operator enables Draw.io export in Plan_Diff_Mode, THE CloudHorus SHALL produce a Draw.io file in which every resource node retains the shape, icon, and container assignment that the same resource receives without Plan_Diff_Mode.
7. WHEN the Draw.io export converter encounters a node or cluster attribute introduced by Change_Style, THE CloudHorus SHALL complete the export and SHALL write the Draw.io file.
7a. WHERE the Operator enables Draw.io export in Plan_Diff_Mode, THE CloudHorus SHALL carry the Change_Style border colour, background Tint, and border width of every decorated Change_Surface into the Draw.io file. A container cell MAY therefore differ from a Legacy_Mode export in those attributes and in the Flag_Token of its label, which is the intended difference rather than a breach of criterion 6.
8. THE CloudHorus SHALL keep the existing WebUI Terraform mode card operational for `main.tf` and `.tfvars` selection without requiring a Plan_File.
9. WHEN the existing test suite under `tests/` runs against this feature, THE CloudHorus SHALL pass every test that passed before this feature.

### Requirement 9: Handle Malformed and Unsupported Plan Input

**User Story:** As a cloud architect, I want CloudHorus to fail with a clear message instead of crashing when a plan file is unusable, so that I can correct the input quickly.

#### Acceptance Criteria

1. WHEN the Plan_Parser loads a Plan_File whose `format_version` has a major component other than `1`, THE Plan_Parser SHALL raise an error naming the unsupported `format_version` value.
2. IF a Plan_File contains text that is not valid JSON, THEN THE CloudHorus SHALL report the file path and the parse position and terminate with a non-zero exit code.
3. IF a Plan_File contains neither `planned_values` nor `values`, THEN THE CloudHorus SHALL report the missing keys and terminate with a non-zero exit code.
4. WHEN a Plan_File declares a `provider_name` outside the supported azurerm provider names, THE Change_Extractor SHALL exclude the corresponding change entries from the Change_Model and log the provider name at warning level.
5. WHEN a Plan_File declares zero entries in `resource_changes`, THE CloudHorus SHALL render the Diagram with every resource assigned the Change_Category `unchanged` and SHALL report the message `Plan contains no resource changes`.
6. WHEN a change entry omits the `change` object, THE Change_Extractor SHALL assign the Change_Category `unchanged` to that entry and log the address at warning level.
7. WHEN a change entry omits the `address` field, THE Change_Extractor SHALL exclude that entry from the Change_Model and log the exclusion at warning level.
8. WHEN the Change_Extractor receives a `resource_changes` value that is not an array, THE Change_Extractor SHALL produce an empty Change_Model and log the type mismatch at warning level.
9. FOR ALL Plan_File contents that parse as JSON, THE Change_Extractor SHALL return a Change_Model or raise an error of type `ValueError`.

### Requirement 10: Protect Sensitive Values Present in the Plan

**User Story:** As a security-conscious architect, I want plan values marked as sensitive to stay out of diagrams, exports, and logs, so that sharing a diagram does not leak secrets.

#### Acceptance Criteria

1. WHEN a Plan_File marks a resource attribute as sensitive through the `before_sensitive` or `after_sensitive` structures, THE Plan_Parser SHALL replace the corresponding value with the literal string `(sensitive)` in the Renderer_Template.
2. THE Graph_Pipeline SHALL restrict resource node labels in Plan_Diff_Mode to the resource name, the resource type, and the Flag_Token.
3. THE CloudHorus SHALL exclude values marked as sensitive from the Change_Summary.
4. THE CloudHorus SHALL exclude values marked as sensitive from every log record it writes.
5. WHERE the Operator enables Draw.io export in Plan_Diff_Mode, THE CloudHorus SHALL exclude values marked as sensitive from the Draw.io file.

### Requirement 11: Sustain Large Plans

**User Story:** As a cloud architect working on a landing zone, I want large plans to render without the diff feature dominating runtime, so that plan review stays practical.

#### Acceptance Criteria

1. WHEN the Change_Extractor processes a Plan_File containing 5000 managed change entries, THE Change_Extractor SHALL produce the Change_Model within 5 seconds.
2. WHEN CloudHorus renders a Plan_File containing 5000 managed change entries, THE CloudHorus SHALL keep the added runtime of change extraction, change styling, and Change_Summary generation below 10 percent of the total generation runtime.
3. WHEN the Operator changes the Change_Filter selection in the WebUI, THE WebUI SHALL display a progress indicator until the updated architecture view is available.
4. THE Change_Extractor SHALL hold at most one Change_Record per managed change entry in memory for the duration of a run.

### Requirement 12: Verifiable Correctness Properties

**User Story:** As a maintainer, I want the diff logic guarded by properties that hold for every generated input, so that classification, filtering, and rendering stay correct as the codebase evolves.

#### Acceptance Criteria

1. FOR ALL `resource_changes` arrays whose entries contain an `address` field and an `actions` array, THE Change_Extractor SHALL assign exactly one Change_Category per managed entry and SHALL leave no managed entry unclassified (classification totality).
2. FOR ALL Change_Models, THE Change_Extractor SHALL satisfy the equality between the sum of the per-category counts and the number of Change_Records (count conservation).
3. FOR ALL Change_Models and all Change_Filter selections, THE CloudHorus SHALL produce a displayed resource set that equals the union of the resources of each selected Change_Category (filter completeness).
4. FOR ALL Change_Filter selections, THE CloudHorus SHALL produce the same displayed resource set when the selection is applied twice as when the selection is applied once (filter idempotence).
5. FOR ALL pairs of Change_Filter selections containing the same Change_Categories, THE CloudHorus SHALL produce the same displayed resource set irrespective of selection order (order independence).
6. FOR ALL Plan_Files whose change entries all resolve to the Change_Category `unchanged`, THE CloudHorus SHALL produce Graphviz DOT source identical to the DOT source produced for the same resources in Terraform JSON mode without Plan_Diff_Mode (unchanged-resource visual parity).
7. FOR ALL Change_Models, THE CloudHorus SHALL serialize the Change_Model to the Renderer_Template and parse it back into a Change_Model equal to the original Change_Model (round-trip property).
8. FOR ALL JSON documents supplied as a Plan_File, THE CloudHorus SHALL terminate with either a rendered Diagram or a reported error, and SHALL raise no unhandled exception (no-crash property).
9. FOR ALL Change_Filter selections that exclude at least one Change_Category, THE CloudHorus SHALL produce a displayed resource count less than or equal to the displayed resource count of the unfiltered run (monotonicity property).
