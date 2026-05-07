version: 1.0

Always avoid to give solutions to resolve static problems and think about generic soltion and dynamic the files you rely on specifically the templates will be always changing
# Project configuration
project:
  name: Azure Resource Visualizer
  description: A Python tool for visualizing Azure resources and their dependencies
  language: python
  rootDir: src/

# Copilot suggestions configuration
suggestions:
  enabled: true
  contexts:
    - azure-cli
    - graphviz
    - python-best-practices

# Documentation patterns
documentation:
  includes:
    - "**/*.py"
    - "**/*.md"
  excludes:
    - "**/test_*.py"
    - "**/.*"
    - "**/__pycache__"

# Code patterns for better suggestions
These practices ensure:

Type safety
Proper error handling
Consistent logging
Maintainable code structure
Testable components
Configuration management
Documentation standards
Remember to:

Use virtual environments
Write tests for new functionality
Document public APIs
Handle errors gracefully
Use type hints consistently
Follow PEP 8 style guide

patterns:
  azure_resources:
    - "Microsoft.*/.*"
    - "*NetworkSecurityGroups*"
    - "*RouteTable*"
    - "*PrivateEndpoint*"

  graph_elements:
    - "*.dot"
    - "*Digraph*"
    - "*subgraph*"

# File organization hints
structure:
  core:
    - "graph_generator.py"
    - "azure_cli.py"
    - "resource_processor.py"
  utils:
    - "graph_utils.py"
    - "skip_patterns.py"
    - "logger.py"

# Type hints and completion
typeHints:
  enforce: true
  paths:
    - "src/**/*.py"

# Custom prompts for common tasks
snippets:
  azure_cli:
    prefix: "az-"
    body: |
      try:
          cmd = f"az {1} {2}"
          result = subprocess.run(cmd, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
          return json.loads(result.stdout)
      except subprocess.CalledProcessError as e:
          logger.error(f"Error executing Azure CLI command: {e.stderr.decode()}")
          return None

  graphviz_node:
    prefix: "node-"
    body: |
      dot.node('${1:node_id}',
              label=f"<<TABLE border='0' cellborder='0' cellspacing='0'><TR><TD>${2:label}</TD></TR></TABLE>>",
              image='${3:icon_path}',
              shape='none',
              imagepos='tc',
              labelloc='b')

# Testing suggestions
testing:
  frameworks:
    - pytest
  patterns:
    - "test_*.py"
    - "*_test.py"

# Dependencies
dependencies:
  required:
    - graphviz>=0.20
    - dash>=2.0.0
    - dash-interactive-graphviz>=0.3.0
    - colorama>=0.4.6

ALWAYS USE PYTHON3 in exmaples


# Interactive Chat / Guided Mode Instructions

Goal: Provide a conversational, step-by-step assistant flow that gathers only the necessary inputs, validates them, recommends optimization flags, then invokes graph generation to produce `azure_resources.png`.

## 1. Initial Prompt
Ask user for high-level use case first:
1) Live Azure Scan Mode (real subscriptions / tenants / resource groups)
2) Bicep Template Mode (local multi-template blueprint analysis)
3) Help (prints brief mode comparison & parameter tips)

If user selects Help, display:
- Live Mode Needs: --tenants, --subscriptions, --resourcegroups (lists; lengths may differ). No Bicep files.
- Bicep Mode Needs: --bicepFiles + --parametersFiles (aligned index), all Azure scope args auto-synthesized (cloudhorus-*) and NOT accepted from user.
Then re-ask for mode.

## 2. Core Questions (Branch by Mode)
Live Mode sequence:
- Tenants (space separated IDs)
- Subscriptions (space separated IDs)
- Resource Groups (space separated names)
Validate: non-empty, each is unique list. Warn if counts differ drastically (possible misalignment).

Bicep Mode sequence:
- Bicep files (paths)
- Parameter files (paths) -> must match count & order of Bicep files
Validate: each path exists. If mismatch, re-prompt only the failing list.

## 3. Optimization & Layout Tuning (ask with defaults + recommendations summary)
ALWAYS RECOMMEND DEFAULT VALUES THEN WHEN THE RESULTS ARE NOT GOOD RECOMMEND ON YOU OWN
when asking to choose default values of parameters Explain the rationale behind each default value and when to deviate from it for each parameter in each line
show each parameter in each line with its default value and a short description of what it does
For each yes/no ask provide rationale & default:
- edgeDirection (TB default) -> Suggest LR for many peer resources per tier.
- tenantDirection (LR default) -> TB only if vertical layering preferred.
- maxSubnetPerline (default 4) -> Lower to reduce horizontal scroll, higher to compress Vnet diagram and so the Digram overall.
- subnetOptimization (default False) -> True hides subnets That doesn't have a vnet Intergration (useful to avoid plotting all sunbets in the amacp landing zone Vnet for example and only keep the ones linked to the used Private endpoints).
- peOptimization (default True) -> Groups/moves Private Endpoints by subnet context.
- crossPeOptimization (default False) -> True hides PEs without cross-tenant dependencies with resources not the vnet integraion (performance/clarity).
- privateDnsZonesOptimization (default True) -> Aggregates DNS zones per VNet (toggle off for troubleshooting detailed DNS linking).
- resourcesEdgeLength (default 1) -> Increase (2-3) if edges overlap dense around hubs.
- resourceGroupsEdgeLengthListBySubscription (auto recommend per subscription) -> Derived from heuristics below.
- highlight that for arrays parameters they are applied at subscription level so they have to provide array length of subscription number.

## 4. Heuristics for Recommendations (Generic & Dynamic)
Use dynamic inspection of counts once lists entered:
- If total RGs > 6 per subscription, recommend tenantDirection=TB to stack tenants, edgeDirection=LR.
- If any VNet > 12 subnets, recommend subnetOptimization=True and maxSubnetPerline=5 or 6.
- For resourceGroupsEdgeLengthListBySubscription: base = 4; add +1 if (RG count > 8), +2 if (>15). Cap at 8.
- For resourcesEdgeLength: start 1; if average dependencies per resource > 3, bump to 2; if > 6, bump to 3.

## 5. Validation Checklist Before Generation
Ensure (abort with actionable message if any fail):
- Mode-specific required arguments present.
- In Bicep Mode: len(bicepFiles) == len(parametersFiles), all files exist & readable.
- In Live Mode: each list non-empty; optionally warn if obvious ID format issues (simple regex pass e.g. GUID pattern for subscriptions if desired, but do not hard fail unless strictly invalid for CLI calls).
- Optimization lists (subnetOptimization, peOptimization, crossPeOptimization) expanded to length == number of subscriptions.
- resourceGroupsEdgeLengthListBySubscription length matches subscriptions.

## 6. Summary Confirmation
Print structured summary (JSON-like) so user can copy/paste:
{
  "mode": "live"|"bicep",
  "tenants": [...],
  "subscriptions": [...],
  "resourceGroups": [...],
  "bicepFiles": [...],
  "parametersFiles": [...],
  "edgeDirection": "TB",
  "tenantDirection": "LR",
  "maxSubnetPerline": 4,
  "optimizations": {
      "subnetOptimization": [...],
      "peOptimization": [...],
      "crossPeOptimization": [...],
      "privateDnsZonesOptimization": true
  },
  "resourcesEdgeLength": 1,
  "resourceGroupsEdgeLengthListBySubscription": [4,4,...]
}
Ask: Proceed? (Y/n). If No -> offer targeted edit menu (1 change single value, 2 restart, 3 abort).

## 7. Invocation Strategy
UPDATED: Always invoke via a synthesized terminal command that runs the main entrypoint (no in-process direct import). The assistant must:

1. Collect & validate inputs (modes + optimization flags) per prior sections.
2. Normalize values:
   - Lists: (--tenants, --subscriptions, --resourcegroups, --bicepFiles, --parametersFiles, per-subscription optimization flags)
   - Booleans: render as true/false lowercase strings (consistent with argparse str_to_bool logic).
3. Build an argument token list in this order (omit any not applicable to selected mode):
   Live Mode: ["python3", "src/main.py", "--tenants", <tenants...>, "--subscriptions", <subs...>, "--resourcegroups", <rgs...>, optimization flags...]
   Bicep Mode: ["python3", "src/main.py", "--bicepFiles", <files...>, "--parametersFiles", <files...>, optimization + layout flags]
4. Optimization flags that are per-subscription lists (e.g. --subnetOptimization, --peOptimization, --crossPeOptimization, --resourceGroupsEdgeLengthListBySubscription) are appended as: --flagName <val1> <val2> ... only if user changed from defaults OR defaults must be explicit for reproducibility. Keep logic dynamic: if future flags added, iterate a descriptors array.
5. Quote each token only if it contains shell special chars or whitespace. Use single quotes by default; escape any embedded single quote by closing/opening: 'abc'"'"'def'.
6. Present two views:
   - Masked preview (IDs shortened first 6 chars + '...')
   - Full command (on user confirmation FULL)
7. If command exceeds 2000 characters, offer multi-line form with backslashes at line breaks after logical groups (mode args, layout, optimizations). Example:
```
python3 src/main.py \
  --tenants 7d7761c0-... f0f45244-... \
  --subscriptions b32d2aa3-... 0daacffa-... \
  --resourcegroups rg-a rg-b rg-c \
  --edgeDirection TB --tenantDirection LR --maxSubnetPerline 4 \
  --subnetOptimization false false --peOptimization true true \
  --crossPeOptimization false false --privateDnsZonesOptimization true \
  --resourcesEdgeLength 1 --resourceGroupsEdgeLengthListBySubscription 4 4
```
8. Execution: After user answers Y to proceed, run exactly the constructed command in the terminal (WSL shell). Avoid Python inline heredocs for generation; rely solely on CLI argument parsing in main.py.
9. Retry flow: On error, display concise cause, then offer (r)erun same command, (e)dit parameters (return to targeted prompt), or (a)bort.
10. Extensibility: Maintain PARAM_SCHEMA (see section 10) and AUTO_FLAGS list of dicts describing how to serialize future flags (name, is_list, default_provider, include_if_default bool) so new flags auto-emit into command without manual edit to strategy.
11. Security: Never echo full IDs unless user explicitly requests FULL. Never fabricate values.
12. Logging: Log final unmasked command (if user consent) at INFO with prefix [CHAT] CMD=. Masked version always logged regardless.

Fallback: Only consider direct in-process import if executing in environment where spawning a terminal is impossible; otherwise the terminal command path is authoritative.

## 8. Output & Post-Generation Guidance
- Expect `azure_resources.png` in project root (do not hardcode alternative paths—allow future configuration).
- After generation, display elapsed time & counts (tenants/subscriptions/RGs/resources edges) if available from logger stats.
- Recommend: open PNG in appropriate viewer or embed in docs.

## 9. Error Handling Guidelines
- Never silently continue on missing file; prompt user to re-enter.
- Wrap generation in try/except; on exception show short cause + suggestion: (e.g. "Consider disabling crossPeOptimization if PEs missing subnet data").
- Offer retry without re-entering unchanged previous answers (cache last valid state).

## 10. Extensibility Notes
Design the chat helper so new flags can be added by appending a descriptor list:
PARAM_SCHEMA = [
  {"name": "edgeDirection", "type": "choice", "choices": ["TB","BT","LR","RL"], "default": "TB", "help": "Graph orientation."},
  ...
]
Iterate schema to auto-generate prompts and validations → keeps logic dynamic when new parameters appear.

## 11. Minimal Pseudocode Flow (Generic)
```
mode = ask_mode()
inputs = collect_mode_specific_inputs(mode)
metrics = analyze_inputs(inputs)
recommendations = derive_recommendations(metrics)
choices = prompt_optimizations(recommendations)
config = assemble_config(mode, inputs, choices)
if confirm(config):
    generate_resource_graph(**config)
    print_success()
else:
    edit_or_abort()
```

## 12. Accessibility & UX
- Provide concise prompts; show default in brackets.
- Color usage optional; fall back gracefully if COLORAMA not available.
- Accept ENTER for defaults; accept short forms (y/n, t/f, yes/no).

## 13. Logging Conventions
- Prefix interaction logs with [CHAT] to separate from generation logs.
- Log configuration snapshot at INFO; avoid secrets (none expected here).

## 14. Testing Recommendations
- Unit test recommendation heuristics (pure functions) with synthetic counts.
- Test validation rejects mismatched bicep/parameters lengths.
- Test boolean list expansion for single flag vs per-subscription arrays.

## 15. Future Ideas (Document, not implement now)
- Add history persistence (last N runs) for quick reuse.
- Add optional JSON export of config for CI reproducibility.
- Add adaptive suggestions based on previous failures (e.g. if layout too dense, auto-increase edge lengths).

## 16. Branding & Response Style Guidelines (CloudHorus Theme)
Use these when generating explanations, help text, or interactive prompts.
- Name Consistency: Always refer to the tool as "CloudHorus" (capitalize C & H). Optional epithet: "Azure Cloud Architecture Guardian" in first mention only.
- Tone: Empowering, concise, observant; avoid hype beyond one short metaphor per answer.
- Allowed Emojis (sparingly at section starts ONLY): 🦅 (guardian/action), 👁️ (insight), ⚡ (performance), ☁️ (cloud context), 📜 (template/blueprint), 🛡️ (protection). Max 2 per answer unless user explicitly requests more.
- Disallowed: Overly playful or unrelated emojis; never stack more than 3 lines of emojis.
- Branding Phrases (optional, rotate): "Divine insight", "Falcon view", "Guardian sweep". Use at most one per response.
- Logging References: When citing logs remind prefix should appear as `[CHAT]` for interaction messages; avoid quoting internal module paths unless debugging.
- ASCII Art: Provide only on explicit user request; keep within 80 columns unless user opts into wide mode.
- Color Guidance: When suggesting CLI output, do not assume color support; mention colorama fallback gracefully.
- Security & Compliance: Never fabricate subscription IDs. Mask potentially sensitive IDs by default (e.g. show first 6 + '...'). Ask user consent before printing full IDs.
- Parameter Recommendation Style: Present adjustment advice as "If <condition>, consider <param>=<value> (reason)".
- Brevity Rule: Lead with direct answer, then optional optimization tips.
- Error Style: Start with concise cause, then one actionable remediation. Example: `❌ Missing --subscriptions. Add at least one ID or switch to Bicep Mode.`
- Consistency: Use American English spelling.
- Avoid Hardcoding: Phrase examples generically; do not promise internal template names.

# End of Interactive Chat Instructions
