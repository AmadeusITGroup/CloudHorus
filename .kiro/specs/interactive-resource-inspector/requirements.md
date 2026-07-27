# Requirements Document

## Introduction

CloudHorus renders an Azure architecture as a single Graphviz PNG. The WebUI shows that PNG in `<img id="viewer-img">`, filled by the bridge method `get_image_base64` from `showImage()`, pans it by scrolling `#viewer-canvas`, and zooms it by writing `img.style.transform = scale(...)` in `initPanZoom` / `zoomIn` / `zoomOut` / `zoomReset` (`webui/app.js`). The render itself is one call, `dot.render(output_filename, format="png")` (`src/core/graph_generator.py:3182`). A PNG carries no per-resource identity, so today nothing in the diagram can be selected and no resource configuration can be read from it.

The shipped `terraform-plan-diff-visualization` feature classifies every managed resource of a plan into `create | update | replace | delete | unchanged`, decorates each Change_Surface with a colour token, a Tint, and a Flag_Token, and writes `azure_resources_<timestamp>.change-summary.json` beside the PNG through `write_change_summary_sidecar`, which the host reads back through `CloudHorusAPI.read_change_summary(png_path)` to build the filter chips. That feature answers *which* resources change. It does not answer *what changes inside* a resource, because attribute detail stops at the builder boundary: `LocalTemplateResource.raw_values` holds the full normalized attribute map (filled by `TerraformTemplateBuilder._normalize_resource`), but `to_renderer_resource()` emits only `type`, `name`, `properties`, `dependsOn`, the extra fields, and `changeCategory` — `raw_values` never reaches the Renderer_Template.

This feature adds an **Inspector**. The Operator activates a resource in the diagram and a panel shows that resource's **full configuration**, with a colour token plus a text marker on each attribute the plan adds, removes, or changes. The colour tokens are the Change_Style tokens already taught by the diagram (`#107C10` create/added, `#D13438` delete/removed, `#0078D4` update/changed), and every colour is accompanied by a text marker so the encoding survives a monochrome screenshot and an Operator who does not perceive the colour difference, which is the same accessibility decision already taken for the Flag_Token (WCAG 2.1 SC 1.4.1).

Facts that constrain the scope, each verified in the codebase:

1. **The only visual artifact is a flat raster**, rendered once. Per-element identity must come from a new, additive artifact; the PNG contract cannot change.
2. **Both sides of a change and both sensitivity masks already exist in the plan.** `resource_changes[].change.before` / `.after` hold the pre- and post-apply attribute trees, and `change.before` is the *only* source for a resource scheduled for deletion, since `planned_values` describes post-apply state and omits it.
3. **Redaction already exists and is reused, not re-implemented.** `TerraformTemplateBuilder._sensitive_indexes` indexes change objects by address, `_sensitive_mask_for` resolves the mask of a phase (`before_sensitive`, `after_sensitive`, falling back to a planned resource's own `sensitive_values`), and `_redact_sensitive` walks a value tree in parallel with its mask, writing the literal `(sensitive)` (`_SENSITIVE_PLACEHOLDER`) at every flagged leaf.
4. **A sidecar precedent exists and works**, so the Inspector data travels the same way: files written beside the diagram, read on demand through a bridge method.
5. **Containers are clusters, not nodes.** A virtual network opens `cluster_vnet<name>` and a subnet opens `cluster_subnet<name>` (four call sites, all funnelled through `style_subnet_cluster`); resource nodes are added through `add_node_in_subgraph` with the identifier `<resource_name>-<resource_group>`. A subnet's Renderer_Template name is the compound `<vnet>/<subnet>`, which is why `resolve_subnet_change_category` exists.

**Pipeline parity is a hard constraint, not a nice-to-have.** The headless CLI path — one run that writes the PNG at the existing output path and needs no interactivity — stays a fully supported first-class mode. Inspector_Mode is off by default, every new parameter is trailing and defaulted, the disabled path executes the render call that ships today, and no failure inside the Inspector may ever cost the Operator the diagram. A pipeline that never reads an Inspector artifact is unaffected in every observable way.

## Glossary

Reused unchanged from the `terraform-plan-diff-visualization` spec: **CloudHorus**, **Plan_File**, **Change_Extractor**, **Change_Record**, **Change_Category** ({`create`, `update`, `replace`, `delete`, `unchanged`}), **Change_Model**, **Renderer_Template**, **Graph_Pipeline**, **Diagram**, **Change_Style**, **Tint**, **Change_Surface**, **Flag_Token** (`+` create, `~` update, `±` replace, `-` delete, none for unchanged), **Legend**, **Change_Summary**, **Change_Filter**, **Skip_Filter**, **Legacy_Mode**, **Plan_Diff_Mode**, **Operator**.

Introduced by this feature:

- **Inspector**: The capability comprising the Interaction_Layer, the Inspector_Payload, the Inspector_Bridge, and the Inspector_Panel.
- **Inspector_Mode**: The state in which CloudHorus produces Inspector artifacts, enabled by the CLI argument `--interactiveInspector`.
- **Headless_Mode**: A CloudHorus run driven by the CLI that produces the PNG artifact and requires no interactivity, which is the mode a pipeline uses. Headless_Mode is available with Inspector_Mode enabled and with Inspector_Mode disabled.
- **Interaction_Layer**: The additive artifact that associates each element the Diagram draws with the Inspector_Key of the resource that element represents.
- **Inspector_Key**: The identifier shared by an Interaction_Layer element and its Inspector_Record. It is the Node_Key for a resource drawn as a node and the Cluster_Key for a resource drawn as a container.
- **Node_Key**: The Graph_Pipeline node identifier `<resource_name>-<resource_group>`.
- **Cluster_Key**: The Graph_Pipeline cluster name, `cluster_vnet<name>` for a virtual network and `cluster_subnet<name>` for a subnet.
- **Config_Snapshot**: The redacted attribute tree of one resource for one phase, either the before phase or the after phase.
- **Attribute_Path**: The path of one Config_Snapshot leaf, written as its map keys and zero-based list indices joined by `.`, for example `site_config.application_stack.0.node_version`.
- **Attribute_Entry**: One row of an Inspector_Record: an Attribute_Path, a Before_Value, an After_Value, and an Attribute_State.
- **Before_Value**: The rendered value of an Attribute_Path in the before phase Config_Snapshot, absent when that Config_Snapshot holds no such path.
- **After_Value**: The rendered value of an Attribute_Path in the after phase Config_Snapshot, absent when that Config_Snapshot holds no such path.
- **Attribute_State**: Exactly one value from the closed set {`added`, `removed`, `changed`, `unchanged`}.
- **Attribute_Flag_Token**: The text marker of an Attribute_State, rendered independently of colour: `+` for `added`, `-` for `removed`, `~` for `changed`, and none for `unchanged`.
- **Attribute_Style**: The pair (colour token, Attribute_Flag_Token) of an Attribute_State: `added` uses `#107C10` and `+`, `removed` uses `#D13438` and `-`, `changed` uses `#0078D4` and `~`, `unchanged` uses the default panel text colour and no marker.
- **Inspector_Record**: The record of one Interaction_Layer element: its Inspector_Key, element kind, display name, renderer type, resource group, Terraform address when the input provides one, Change_Category when a Change_Record exists, replacement marker, ordered Attribute_Entry list, omitted attribute count, and applied truncation reasons.
- **Inspector_Index**: The lookup that gives, for each Inspector_Key, the location of its Inspector_Record inside the Inspector_Payload, plus the Attribute_Style table, the Value_Bounds, the record count, and the key collision count.
- **Inspector_Payload**: The Inspector_Index together with the set of Inspector_Records of one run, written beside the PNG in the run output folder.
- **Inspector_Bridge**: The host-process accessor that returns the Inspector_Index of a diagram, or one Inspector_Record of a diagram identified by its Inspector_Key, mirroring the `read_change_summary` accessor.
- **Inspector_Panel**: The WebUI element that displays one Inspector_Record.
- **Value_Bounds**: The three limits that cap Inspector_Payload size: Row_Bound of 500 Attribute_Entries per Inspector_Record, Scalar_Bound of 2048 characters per rendered value, and Depth_Bound of 12 levels of Config_Snapshot nesting.
- **Truncation_Marker**: The literal string `(truncated)`, written in place of a value or a subtree that a Value_Bound removed.
- **Truncation_Reason**: Exactly one value from the closed set {`value`, `depth`, `rows`}, naming the Value_Bound that a truncation applied.
- **Unknown_Marker**: The literal string `(known after apply)`, used as the After_Value of an Attribute_Path whose value the plan reports as not yet known.
- **Redaction_Literal**: The literal string `(sensitive)` that `TerraformTemplateBuilder._redact_sensitive` already writes in place of a value the plan marks as sensitive.

## Requirements

### Requirement 1: Preserve the Headless Pipeline Path

**User Story:** As a platform engineer running CloudHorus in a pipeline, I want the headless PNG path to stay exactly as it is, so that adding an inspector cannot break automation that never uses it.

#### Acceptance Criteria

1. THE CloudHorus SHALL support Headless_Mode, in which a CLI run writes the PNG artifact to the existing output path and requires no interactive display.
2. THE CloudHorus SHALL default Inspector_Mode to disabled.
3. WHILE Inspector_Mode is disabled, THE CloudHorus SHALL execute the PNG render call `dot.render(output_filename, format="png")` that the release preceding this feature executes.
4. WHILE Inspector_Mode is disabled, THE CloudHorus SHALL write the same artifacts to the same output paths that the release preceding this feature writes for the same arguments.
5. WHILE Inspector_Mode is disabled, THE CloudHorus SHALL produce a Renderer_Template whose resource entries hold the keys and values that the release preceding this feature produces for the same input.
6. WHEN Inspector_Mode is enabled, THE CloudHorus SHALL write a PNG artifact byte-identical to the PNG artifact that the same run writes with Inspector_Mode disabled, at the same output path.
7. WHEN the Operator runs CloudHorus in Headless_Mode, THE CloudHorus SHALL return the exit code that the release preceding this feature returns for the same arguments.
8. WHERE Draw.io export is enabled together with Inspector_Mode, THE CloudHorus SHALL write a Draw.io file identical to the Draw.io file that the same run writes with Inspector_Mode disabled.
9. IF any step that produces the Interaction_Layer or the Inspector_Payload raises an error, THEN THE CloudHorus SHALL log the error at warning level, SHALL omit the affected Inspector artifact, and SHALL complete the run with the PNG artifact written and its path returned.
10. WHEN the existing test suite under `tests/` runs against this feature, THE CloudHorus SHALL pass every test that passed before this feature.
11. THE CloudHorus SHALL keep the file name and the content of the Change_Summary sidecar unchanged by this feature.
12. WHERE CloudHorus runs in an environment that provides no interactive display, THE CloudHorus SHALL write the PNG artifact and, WHERE Inspector_Mode is enabled, the Inspector artifacts, without requiring an Inspector_Panel.

### Requirement 2: Enable the Inspector from the CLI and the WebUI

**User Story:** As an Operator, I want one explicit switch that turns the inspector on, so that I choose per run whether the interactive artifacts are produced.

#### Acceptance Criteria

1. WHERE the Operator supplies the CLI argument `--interactiveInspector` with the value `True`, THE CloudHorus SHALL enable Inspector_Mode for that run.
2. THE CloudHorus SHALL accept `--interactiveInspector` as an optional argument with the default value `False`, and SHALL keep the name, the arity, and the default value of every CLI argument accepted before this feature.
3. IF the Operator supplies a `--interactiveInspector` value that is neither `True` nor `False` when compared without regard to letter case, THEN THE CloudHorus SHALL report the accepted values and terminate with a non-zero exit code.
4. THE WebUI SHALL present an Inspector_Mode toggle in the options card, available in Live mode, Bicep mode, Terraform source mode, Terraform JSON mode, and Plan_Diff_Mode, and defaulted to off.
5. WHEN the Inspector_Mode toggle is on, THE WebUI SHALL append `--interactiveInspector True` to the command it runs, in every input mode.
6. WHEN the Operator changes the Inspector_Mode toggle, THE WebUI SHALL update the displayed command preview so that the preview matches the command the WebUI will run.
7. WHILE the Inspector_Mode toggle is off, THE WebUI SHALL display the Diagram with the pan, zoom, fullscreen, and Change_Filter behaviour that the release preceding this feature provides.
8. THE CloudHorus SHALL accept Inspector_Mode together with every input mode, so that the choice of input mode and the choice of Inspector_Mode stay independent.

### Requirement 3: Produce the Interaction Layer

**User Story:** As a cloud architect, I want the rendered architecture to carry per-element identity, so that the viewer can tell which resource I activated.

#### Acceptance Criteria

1. WHEN Inspector_Mode is enabled, THE CloudHorus SHALL produce the Interaction_Layer and the PNG artifact from one Graphviz layout pass.
2. THE Interaction_Layer SHALL carry one activatable element for every resource that the Graph_Pipeline draws as a node in the Diagram.
3. THE Interaction_Layer SHALL carry one activatable element for every virtual network cluster and every subnet cluster that the Graph_Pipeline draws in the Diagram.
4. THE CloudHorus SHALL set the Inspector_Key of an element that represents a resource drawn as a node to the Node_Key `<resource_name>-<resource_group>`.
5. THE CloudHorus SHALL set the Inspector_Key of an element that represents a resource drawn as a container to the Cluster_Key, which is `cluster_vnet<name>` for a virtual network and `cluster_subnet<name>` for a subnet.
6. THE CloudHorus SHALL write the Interaction_Layer into the output folder that the run already creates for the PNG artifact.
7. THE CloudHorus SHALL make every resource icon of the Interaction_Layer resolvable without reference to an absolute filesystem path of the machine that generated it.
8. IF the production of the Interaction_Layer fails, THEN THE CloudHorus SHALL log the failure at warning level, SHALL write the PNG artifact through the render path that Inspector_Mode disabled uses, and SHALL complete the run.
9. THE CloudHorus SHALL keep the geometry of the Interaction_Layer aligned with the displayed Diagram across the zoom range from 0.1 to 5 that the viewer supports, so that an activated element is the element under the pointer.
10. THE CloudHorus SHALL produce the Interaction_Layer deterministically, so that two runs over the same input produce Interaction_Layers with the same Inspector_Keys.

### Requirement 4: Identify the Inspectable Elements

**User Story:** As a maintainer, I want exactly one inspector record per element the diagram draws, so that the panel and the diagram can never disagree about what exists.

#### Acceptance Criteria

1. WHEN Inspector_Mode is enabled, THE CloudHorus SHALL emit one Inspector_Record for every element of the Interaction_Layer.
2. THE CloudHorus SHALL key every Inspector_Record by the Inspector_Key of the element it describes.
3. THE Inspector_Index SHALL hold one entry per Inspector_Key, giving the location of the corresponding Inspector_Record inside the Inspector_Payload, and SHALL report the record count.
4. THE Inspector_Record SHALL carry the display name, the renderer type, the resource group, the Terraform address when the input provides one, the Change_Category when a Change_Record exists for the resource, and the ordered Attribute_Entry list of the resource.
5. WHEN two elements produce the same Inspector_Key, THE CloudHorus SHALL retain the first Inspector_Record, SHALL log the duplicate Inspector_Key at warning level, and SHALL report the collision count in the Inspector_Index.
6. WHEN the Skip_Filter removes a resource from the Diagram, THE CloudHorus SHALL omit the Inspector_Record of that resource.
7. WHEN the Change_Filter excludes a resource from the Diagram, THE CloudHorus SHALL omit the Inspector_Record of that resource.
8. THE CloudHorus SHALL collect Inspector_Records during the render pass, at the points where the Graph_Pipeline creates nodes and clusters, so that the Inspector_Index describes the elements the Diagram draws rather than a second notion of the displayed set.
9. WHERE an Inspector_Record describes a resource whose Change_Category is `replace`, THE Inspector_Record SHALL carry a replacement marker.

### Requirement 5: Display the Full Configuration of the Activated Resource

**User Story:** As a cloud architect, I want the panel to show every configuration attribute of the resource, not only the ones the plan touches, so that I can judge a change in the context of the whole resource.

#### Acceptance Criteria

1. WHEN the Operator activates an Interaction_Layer element, THE WebUI SHALL display in the Inspector_Panel the Inspector_Record whose Inspector_Key equals the Inspector_Key of that element.
2. THE Inspector_Panel SHALL display one Attribute_Entry for every leaf present in either Config_Snapshot of the resource, subject to the Value_Bounds of Requirement 12.
3. THE CloudHorus SHALL express the Attribute_Path of an Attribute_Entry as the map keys and zero-based list indices leading from the Config_Snapshot root to that leaf, joined by `.`.
4. THE CloudHorus SHALL order the Attribute_Entry values of an Inspector_Record by Attribute_Path in ascending lexicographic order.
5. THE Inspector_Panel SHALL display the resource display name, the renderer type, the resource group, and the Terraform address of the Inspector_Record.
6. WHERE an Inspector_Record carries a Change_Category, THE Inspector_Panel SHALL display that Change_Category together with the Flag_Token that the Diagram applies to the same resource.
7. WHEN a Config_Snapshot leaf holds a value that is not a string, THE CloudHorus SHALL render that value as its JSON representation.
8. WHEN a Config_Snapshot holds an empty map or an empty list at an Attribute_Path, THE CloudHorus SHALL emit one Attribute_Entry for that Attribute_Path whose rendered value is `{}` for an empty map and `[]` for an empty list.
9. WHERE the Operator enters text in the Inspector_Panel filter control, THE Inspector_Panel SHALL display the Attribute_Entry values whose Attribute_Path or rendered value contains that text and SHALL hide the remaining Attribute_Entry values.
10. WHERE the Operator enables the changed-only control of the Inspector_Panel, THE Inspector_Panel SHALL display the Attribute_Entry values whose Attribute_State differs from `unchanged` and SHALL hide the remaining Attribute_Entry values.
11. THE Inspector_Panel SHALL display the count of Attribute_Entry values it holds per Attribute_State.
12. WHERE the Operator activates the Inspector_Panel copy control, THE WebUI SHALL place the displayed configuration on the system clipboard as text.

### Requirement 6: Resolve Before and After Configuration per Change Category

**User Story:** As a cloud architect reviewing a destructive plan, I want deleted and replaced resources to show their configuration correctly, so that the panel is trustworthy for the changes that matter most.

#### Acceptance Criteria

1. WHEN a resource carries the Change_Category `create`, THE CloudHorus SHALL treat the before phase Config_Snapshot as empty and SHALL build the after phase Config_Snapshot from the redacted `change.after` object of that resource's change entry.
2. WHEN a resource carries the Change_Category `delete`, THE CloudHorus SHALL build the before phase Config_Snapshot from the redacted `change.before` object of that resource's change entry and SHALL treat the after phase Config_Snapshot as empty, because a resource scheduled for deletion is absent from `planned_values` and `change.before` is its only source.
3. WHEN a resource carries the Change_Category `update`, THE CloudHorus SHALL build the before phase Config_Snapshot from the redacted `change.before` object and the after phase Config_Snapshot from the redacted `change.after` object of that resource's change entry.
4. WHEN a resource carries the Change_Category `replace`, THE CloudHorus SHALL build the before phase Config_Snapshot from the redacted `change.before` object and the after phase Config_Snapshot from the redacted `change.after` object of that resource's change entry.
5. WHEN a resource carries the Change_Category `unchanged`, THE CloudHorus SHALL build both Config_Snapshots from the redacted attribute map of that resource, so that every Attribute_Entry of the resource carries the Attribute_State `unchanged`.
6. WHEN a change entry reports the value of an Attribute_Path as not yet known, THE CloudHorus SHALL set the After_Value of that Attribute_Entry to the Unknown_Marker.
7. IF a change entry omits the `change.after` object for a resource whose Change_Category is `create`, `update`, or `replace`, THEN THE CloudHorus SHALL build the after phase Config_Snapshot from the redacted attribute map of that resource and SHALL log the resource address at warning level.
8. IF a change entry omits the `change.before` object for a resource whose Change_Category is `update`, `replace`, or `delete`, THEN THE CloudHorus SHALL treat the before phase Config_Snapshot as empty and SHALL log the resource address at warning level.
9. WHERE a resource has no Change_Record, THE CloudHorus SHALL build both Config_Snapshots from the redacted attribute map of that resource.
10. THE CloudHorus SHALL derive the after phase Config_Snapshot of a resource from data the run already holds, so that building an Inspector_Record adds no read of the Plan_File beyond the reads the run already performs.

### Requirement 7: Colour-Code the Attributes That the Plan Changes

**User Story:** As a cloud architect, I want each attribute marked as added, removed, changed, or unchanged with a colour and a text marker, so that I can read the intra-resource diff at a glance and still read it without colour.

#### Acceptance Criteria

1. THE CloudHorus SHALL assign exactly one Attribute_State to every Attribute_Entry, selected from {`added`, `removed`, `changed`, `unchanged`}.
2. WHEN an Attribute_Path is present in the after phase Config_Snapshot and absent from the before phase Config_Snapshot, THE CloudHorus SHALL assign the Attribute_State `added`.
3. WHEN an Attribute_Path is present in the before phase Config_Snapshot and absent from the after phase Config_Snapshot, THE CloudHorus SHALL assign the Attribute_State `removed`.
4. WHEN an Attribute_Path is present in both Config_Snapshots and the Before_Value differs from the After_Value, THE CloudHorus SHALL assign the Attribute_State `changed`.
5. WHEN an Attribute_Path is present in both Config_Snapshots and the Before_Value equals the After_Value, THE CloudHorus SHALL assign the Attribute_State `unchanged`.
6. WHEN the Inspector_Panel displays an Attribute_Entry whose Attribute_State is `added`, THE Inspector_Panel SHALL apply the colour token `#107C10` and the Attribute_Flag_Token `+` to that Attribute_Entry.
7. WHEN the Inspector_Panel displays an Attribute_Entry whose Attribute_State is `removed`, THE Inspector_Panel SHALL apply the colour token `#D13438` and the Attribute_Flag_Token `-` to that Attribute_Entry.
8. WHEN the Inspector_Panel displays an Attribute_Entry whose Attribute_State is `changed`, THE Inspector_Panel SHALL apply the colour token `#0078D4` and the Attribute_Flag_Token `~` to that Attribute_Entry.
9. WHEN the Inspector_Panel displays an Attribute_Entry whose Attribute_State is `unchanged`, THE Inspector_Panel SHALL apply the default panel text colour and no Attribute_Flag_Token.
10. THE Inspector_Panel SHALL render the Attribute_Flag_Token of every Attribute_Entry that carries a colour token as text in a cell of its own, so that the Attribute_State stays readable in a monochrome rendering of the panel and for an Operator who does not perceive the colour tokens, which is the non-colour cue that WCAG 2.1 SC 1.4.1 requires.
11. WHEN the Inspector_Panel displays an Attribute_Entry whose Attribute_State is `changed`, THE Inspector_Panel SHALL display the Before_Value and the After_Value as two separately labelled values.
12. THE Inspector_Panel SHALL display a legend that maps each Attribute_State to its colour token and its Attribute_Flag_Token.
13. THE Inspector_Index SHALL carry the Attribute_Style table, so that the Inspector_Panel reads the colour tokens and the Attribute_Flag_Tokens from the Inspector_Payload rather than from a second copy of those constants.

### Requirement 8: Operate the Viewer and the Panel

**User Story:** As a cloud architect, I want to open, read, and close the panel with either the pointer or the keyboard while the diagram stays usable, so that inspecting a resource does not cost me the view I was working in.

#### Acceptance Criteria

1. WHEN the Operator activates an Interaction_Layer element with a pointer click, THE WebUI SHALL open the Inspector_Panel displaying the Inspector_Record of that element.
2. WHEN the Operator moves keyboard focus to an Interaction_Layer element and presses Enter or Space, THE WebUI SHALL open the Inspector_Panel displaying the Inspector_Record of that element.
3. THE WebUI SHALL make every Interaction_Layer element reachable by sequential keyboard navigation.
4. WHEN the Inspector_Panel is open and the Operator presses Escape or activates the panel close control, THE WebUI SHALL close the Inspector_Panel and return keyboard focus to the element that opened it.
5. WHEN the Inspector_Panel is open and the Operator activates a different Interaction_Layer element, THE WebUI SHALL replace the displayed Inspector_Record with the Inspector_Record of the newly activated element.
6. WHILE the Inspector_Panel is open, THE WebUI SHALL keep the pan, zoom, fullscreen, and Change_Filter controls of the viewer operable.
7. WHEN the Operator activates an Interaction_Layer element, THE WebUI SHALL apply a selection indicator to that element that carries a cue other than colour.
8. THE WebUI SHALL present a control that switches the viewer between the Interaction_Layer and the PNG artifact, and SHALL keep the current zoom factor across that switch.
9. THE WebUI SHALL expose every Interaction_Layer element to assistive technology as an activatable control carrying the display name of the resource it represents.
10. WHILE the Inspector_Bridge has not returned the Inspector_Record of an activated element, THE Inspector_Panel SHALL display a loading indicator.
11. WHEN the Operator activates an Interaction_Layer element whose Inspector_Key has no Inspector_Record, THE Inspector_Panel SHALL display the message `No configuration available for this resource`.

### Requirement 9: Inspect Resources Drawn as Containers

**User Story:** As a cloud architect, I want to inspect a virtual network or a subnet, so that container resources are not a blind spot of the panel.

#### Acceptance Criteria

1. WHEN Inspector_Mode is enabled, THE CloudHorus SHALL emit one Inspector_Record for every virtual network cluster and every subnet cluster that the Graph_Pipeline draws.
2. WHEN the Operator activates a virtual network cluster, THE WebUI SHALL open the Inspector_Panel displaying the Inspector_Record of that virtual network.
3. WHEN the Operator activates a subnet cluster, THE WebUI SHALL open the Inspector_Panel displaying the Inspector_Record of that subnet.
4. WHERE a subnet cluster lies inside a virtual network cluster, THE WebUI SHALL display the Inspector_Record of the subnet when the Operator activates a point inside that subnet cluster and the Inspector_Record of the virtual network when the Operator activates a point of the virtual network cluster that lies outside every subnet cluster it contains.
5. WHEN a subnet cluster is drawn from the `subnets` list held in a virtual network's properties and the Renderer_Template holds no separate subnet resource for it, THE CloudHorus SHALL build the Inspector_Record of that subnet from that embedded entry.
6. THE CloudHorus SHALL resolve the subnet resource of a subnet cluster by matching the compound Renderer_Template name `<virtual_network_name>/<subnet_name>` first and the bare subnet name second, which is the resolution order that `resolve_subnet_change_category` already applies.
7. WHERE an Inspector_Record describes a container, THE Inspector_Panel SHALL apply the Attribute_Style of each Attribute_State that it applies to an Inspector_Record describing a node.
8. WHEN the Operator activates a node that lies inside a subnet cluster, THE WebUI SHALL display the Inspector_Record of that node rather than the Inspector_Record of the enclosing cluster.

### Requirement 10: Inspect Resources in Legacy Modes

**User Story:** As a cloud architect using Live, Bicep, or Terraform source mode, I want the panel to show configuration there too, so that the Inspector is useful outside plan review.

#### Acceptance Criteria

1. WHERE Inspector_Mode is enabled in a Legacy_Mode, THE CloudHorus SHALL produce an Interaction_Layer and an Inspector_Payload whose Inspector_Records carry the configuration available to that mode.
2. WHERE CloudHorus operates in a Legacy_Mode, THE CloudHorus SHALL assign the Attribute_State `unchanged` to every Attribute_Entry, because no plan and therefore no before phase exists.
3. WHERE CloudHorus operates in a Legacy_Mode, THE Inspector_Panel SHALL display the configuration without the Change_Category display and without the Attribute_State legend.
4. WHERE a resource carries no attribute map, THE CloudHorus SHALL build the Config_Snapshot of that resource from the `properties` map and the extra fields of its Renderer_Template entry.
5. WHERE CloudHorus operates in Live mode, THE CloudHorus SHALL build every Config_Snapshot from resource data that the run already retrieved, and SHALL issue no additional Azure request for the Inspector.
6. WHERE CloudHorus operates in Plan_Diff_Mode, THE Inspector_Panel SHALL display the Change_Category of the Inspector_Record and the Attribute_State legend.
7. WHERE CloudHorus operates in Terraform JSON mode without a `resource_changes` array, THE CloudHorus SHALL assign the Attribute_State `unchanged` to every Attribute_Entry.

### Requirement 11: Protect Sensitive Values in the New Output Surfaces

**User Story:** As a security-conscious architect, I want the panel and its payload to respect the same redaction as the diagram, so that adding an inspector does not create a leak.

#### Acceptance Criteria

1. WHEN CloudHorus builds a Config_Snapshot from a plan phase, THE CloudHorus SHALL apply the redaction that `TerraformTemplateBuilder._redact_sensitive` performs against the sensitivity mask of that phase before any value of that Config_Snapshot enters an Inspector_Record.
2. THE CloudHorus SHALL use the `before_sensitive` structure as the sensitivity mask of the before phase, and the `after_sensitive` structure with a fallback to the planned resource's own `sensitive_values` as the sensitivity mask of the after phase, which is the resolution `_sensitive_mask_for` already implements.
3. WHEN a sensitivity mask flags an Attribute_Path, THE CloudHorus SHALL write the Redaction_Literal as the value of that phase for that Attribute_Entry.
4. WHEN a sensitivity mask flags an Attribute_Path in one phase only, THE CloudHorus SHALL write the Redaction_Literal as the value of that phase and SHALL keep the value of the other phase as the redaction of that other phase produces it.
5. THE CloudHorus SHALL exclude every value that a sensitivity mask flags from the Inspector_Payload.
6. THE CloudHorus SHALL exclude every value that a sensitivity mask flags from every log record it writes while building, writing, or reading the Inspector_Payload.
7. WHEN a sensitivity mask flags an Attribute_Path in both phases, THE CloudHorus SHALL assign the Attribute_State `unchanged` to that Attribute_Entry and SHALL display the Redaction_Literal as both values, because redaction removes the information needed to compare the two phases.
8. WHERE an Inspector_Record holds at least one Attribute_Entry whose two values are the Redaction_Literal, THE Inspector_Panel SHALL display the message `Redacted attributes cannot be compared`.
9. THE CloudHorus SHALL restrict the resource labels of the Diagram and of the Interaction_Layer to the resource name, the resource type, and the Flag_Token, which is the restriction that Requirement 10.2 of the `terraform-plan-diff-visualization` spec places on **node labels only**. The Inspector_Panel and the Inspector_Payload are separate output surfaces governed by criteria 1 through 8 of this requirement, so displaying redacted configuration outside a node label does not breach that restriction.
10. THE CloudHorus SHALL exclude configuration values from the Interaction_Layer, so that the artifact that carries element identity carries no attribute value.

### Requirement 12: Bound the Payload Size and the Added Runtime

**User Story:** As a cloud architect working on a landing zone plan, I want the inspector to stay responsive on a large plan, so that full configuration for hundreds of resources does not make the tool unusable.

#### Acceptance Criteria

1. THE Inspector_Bridge SHALL return exactly one Inspector_Record per read request, identified by the diagram path and the Inspector_Key, so that displaying one resource loads neither the Inspector_Records of the other resources nor the whole Inspector_Payload.
2. WHEN an Inspector_Record holds more Attribute_Entry values than the Row_Bound of 500, THE CloudHorus SHALL retain the Attribute_Entry values whose Attribute_State differs from `unchanged` first, SHALL fill the remaining rows in ascending Attribute_Path order until the Row_Bound is reached, SHALL omit the remaining Attribute_Entry values, and SHALL report the omitted count in the Inspector_Record.
3. WHEN a rendered value exceeds the Scalar_Bound of 2048 characters, THE CloudHorus SHALL truncate that value to 2048 characters, SHALL append the Truncation_Marker, and SHALL record the Truncation_Reason `value` in the Inspector_Record.
4. WHEN a Config_Snapshot holds a subtree deeper than the Depth_Bound of 12 levels, THE CloudHorus SHALL emit the Attribute_Entry at depth 12 with the Truncation_Marker as its rendered value, SHALL omit the deeper leaves, and SHALL record the Truncation_Reason `depth` in the Inspector_Record.
5. WHEN the Row_Bound omits at least one Attribute_Entry from an Inspector_Record, THE CloudHorus SHALL record the Truncation_Reason `rows` in that Inspector_Record.
6. WHEN CloudHorus renders an input of 5000 resources with Inspector_Mode enabled, THE CloudHorus SHALL keep the added runtime of Interaction_Layer production, Inspector_Payload construction, and Inspector_Payload writing below 15 percent of the total generation runtime.
7. WHEN the Operator activates an Interaction_Layer element of a run of 500 resources, THE Inspector_Panel SHALL display the content of the corresponding Inspector_Record within 1000 milliseconds.
8. THE CloudHorus SHALL write exactly one Inspector_Payload per run into the output folder that the run already creates.
9. WHERE an Inspector_Record carries at least one Truncation_Reason or an omitted attribute count above zero, THE Inspector_Panel SHALL display the applied Truncation_Reasons and the omitted count.
10. THE Inspector_Index SHALL report the Value_Bounds that the run applied, so that the Inspector_Panel states the limits under which the displayed configuration was produced.

### Requirement 13: Handle Missing and Malformed Inspector Data

**User Story:** As a cloud architect, I want the viewer to fall back to today's behaviour when inspector data is unavailable, so that a missing artifact never costs me the diagram.

#### Acceptance Criteria

1. WHEN the WebUI displays a Diagram for which no Inspector_Payload exists, THE WebUI SHALL display the Diagram with the pan, zoom, fullscreen, and Change_Filter behaviour that the release preceding this feature provides.
2. WHEN the WebUI displays a Diagram for which no Interaction_Layer exists, THE WebUI SHALL display the PNG artifact in the `viewer-img` element with the behaviour that the release preceding this feature provides.
3. IF the Inspector_Index contains text that is not valid JSON, THEN THE Inspector_Bridge SHALL return no Inspector_Index, THE WebUI SHALL display the Diagram without element activation, and THE CloudHorus SHALL log the file path at warning level.
4. IF the Inspector_Index omits the entry of a requested Inspector_Key, THEN THE Inspector_Bridge SHALL return no Inspector_Record.
5. IF the stored form of a requested Inspector_Record is absent, incomplete, or not valid JSON, THEN THE Inspector_Bridge SHALL return no Inspector_Record and THE Inspector_Panel SHALL display the message `No configuration available for this resource`.
6. FOR ALL read requests, THE Inspector_Bridge SHALL return either one Inspector_Record or no Inspector_Record, and SHALL raise no exception.
7. WHEN a generation run completes, THE WebUI SHALL clear the Inspector_Index, the Interaction_Layer, and the Inspector_Panel content of the previous run before displaying the new Diagram.
8. WHEN an Inspector_Record carries an Attribute_State value outside the Attribute_State set, THE Inspector_Panel SHALL display that Attribute_Entry with the presentation of the Attribute_State `unchanged` and THE WebUI SHALL log the value at warning level.
9. WHEN a Config_Snapshot holds a value that the JSON serializer cannot represent, THE CloudHorus SHALL render that value through its string representation.
10. WHEN a Config_Snapshot holds a map key that is not a string, THE CloudHorus SHALL render that key through its string representation and SHALL use the result as the Attribute_Path segment.
11. WHEN a Config_Snapshot holds a reference that repeats an enclosing subtree, THE CloudHorus SHALL write the Truncation_Marker in place of the repeated subtree.
12. THE CloudHorus SHALL treat text that reaches the WebUI from an Inspector_Payload as data rather than as markup, so that a resource name or an attribute value cannot introduce executable content into the viewer.

### Requirement 14: Verifiable Correctness Properties

**User Story:** As a maintainer, I want the inspector logic guarded by properties that hold for every generated input, so that flattening, diffing, redaction, and bounding stay correct as the codebase evolves.

#### Acceptance Criteria

1. FOR ALL Config_Snapshot pairs, THE CloudHorus SHALL assign exactly one Attribute_State drawn from {`added`, `removed`, `changed`, `unchanged`} to every Attribute_Path present in either Config_Snapshot, and SHALL leave no such Attribute_Path unclassified (classification totality).
2. FOR ALL Config_Snapshot pairs within the Value_Bounds, THE CloudHorus SHALL produce an Attribute_Entry set whose Attribute_Paths equal the union of the Attribute_Paths of the two Config_Snapshots (path coverage).
3. FOR ALL attribute trees within the Value_Bounds whose map keys hold no `.` character, THE CloudHorus SHALL reconstruct the original tree from the flattened Attribute_Entry list, so that flattening followed by unflattening yields the original tree (flatten round trip).
4. FOR ALL Config_Snapshot pairs, THE CloudHorus SHALL produce the same Attribute_Entry list when the pair is diffed twice as when the pair is diffed once (diff idempotence).
5. FOR ALL runs with Inspector_Mode enabled, THE CloudHorus SHALL produce an Inspector_Index whose Inspector_Key set equals the Inspector_Key set that the Interaction_Layer carries, except for the Inspector_Keys that a reported collision dropped (element coverage).
6. FOR ALL Config_Snapshots, THE CloudHorus SHALL assign the Attribute_State `unchanged` to every Attribute_Entry of a pair whose two Config_Snapshots are equal (identity diff).
7. FOR ALL Config_Snapshot pairs, THE CloudHorus SHALL produce the Attribute_State `added` for exactly the Attribute_Paths for which the reversed pair produces the Attribute_State `removed`, and SHALL produce the same Attribute_Path sets for the Attribute_States `changed` and `unchanged` under reversal (diff antisymmetry).
8. FOR ALL attribute trees and all parallel sensitivity masks, THE CloudHorus SHALL write the Redaction_Literal for every Attribute_Path the mask flags and the unmodified rendered value for every Attribute_Path the mask does not flag (redaction fidelity).
9. FOR ALL Plan_Files holding sensitive attribute values, THE CloudHorus SHALL keep those values out of the Inspector_Payload, the Interaction_Layer, the Inspector_Panel, and every log record the run writes (sensitive containment).
10. FOR ALL Inspector_Payloads, THE CloudHorus SHALL write the payload and read it back into a set of Inspector_Records equal to the set written (payload round trip).
11. FOR ALL Inspector_Keys of an Inspector_Payload, THE Inspector_Bridge SHALL return the Inspector_Record whose Inspector_Key equals the requested Inspector_Key, and SHALL return no Inspector_Record for an Inspector_Key the payload does not hold (reader soundness).
12. FOR ALL Inspector_Payloads, THE CloudHorus SHALL keep every rendered value within the Scalar_Bound, every Attribute_Path within the Depth_Bound, and every Inspector_Record within the Row_Bound, and SHALL report every applied truncation as a Truncation_Reason or an omitted count (bound enforcement).
13. FOR ALL inputs, THE CloudHorus SHALL produce Graphviz DOT source and a PNG artifact with Inspector_Mode enabled identical to the DOT source and the PNG artifact produced with Inspector_Mode disabled (headless output parity).
14. FOR ALL attribute trees, including trees holding non-string keys, repeated subtrees, values the JSON serializer cannot represent, and nesting beyond the Depth_Bound, THE CloudHorus SHALL terminate with an Inspector_Payload or a reported error, and SHALL raise no unhandled exception (no-crash property).
