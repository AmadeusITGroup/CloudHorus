# CloudHorus — Trust, Permissions & Execution Model

This document explains **what CloudHorus does, what it can and cannot touch, and how it
authenticates** against Azure. It is the authoritative reference for security reviews,
compliance audits, and onboarding new operators or CI/CD pipelines.

> 🖥️ **Everything runs locally.** CloudHorus is a self-contained Python process executed
> on your workstation, your CI runner, or your own server. It has **no backend service, no
> SaaS component, no hosted endpoint**. Your Azure metadata never leaves the machine that
> runs the tool — the only outbound traffic is the direct ARM API calls the tool makes to
> read your resources, and the resulting diagrams (PNG / DOT / DrawIO) are written to your
> local working directory. Nothing is uploaded, mirrored, or telemetered anywhere.

---

## 1. Trust Model — What CloudHorus Promises

### 1.1 Core guarantee
**CloudHorus is a strictly read-only visualization tool.** It is incapable of creating,
modifying, or deleting any Azure resource. This guarantee is enforced at three independent
layers (defense-in-depth):

| Layer | Mechanism | What it blocks |
|-------|-----------|----------------|
| **L1 — RBAC (recommended)** | The identity used by CloudHorus is granted only the built-in `Reader` role at the relevant scope. | Any write call rejected by Azure ARM with `AuthorizationFailed`. |
| **L2 — SDK pipeline policy** | [`ReadOnlyPolicy`](../src/core/readonly_policy.py) is registered as a `per_call_policies` entry on every Azure SDK client. | All `PUT`, `PATCH`, `DELETE`, and any `POST` whose ARM action is not on the explicit allowlist. |
| **L3 — Code review** | The codebase contains zero references to write APIs (`begin_create_or_update`, `delete`, `update`, etc.). | Accidental future regression — caught in code review. |

If you remove L1, L2 still protects you. If you bypass L2, L1 still protects you. Both
layers are active by default.

### 1.2 What the SDK pipeline policy allows
[`ReadOnlyPolicy`](../src/core/readonly_policy.py) lets through only the following:

- All `GET`, `HEAD`, `OPTIONS` requests.
- POST requests to the Microsoft identity token endpoints (`login.microsoftonline.com`, etc.)
  for credential acquisition.
- POST requests whose **last URL path segment** is:
  - `exportTemplate` — used to export a resource group's ARM template (the primary
    discovery mechanism).
  - `list` or any segment starting with `list` (e.g. `listByResourceGroup`) — generic ARM
    list actions used by the SDK enumerators (`tenants.list()`, `subscriptions.list()`,
    `resources.list_by_resource_group()`, etc.).

Anything else — including `listKeys`, `listSecrets`, `regenerateKey`, `restart`, `start`,
`stop`, `validate`, `migrate` — is **blocked at the pipeline level** and raises
`PermissionError` before the request leaves the process.

### 1.3 What CloudHorus does *not* do

- ❌ Does not call `listKeys`, `listSecrets`, or any credential-returning endpoint.
- ❌ Does not call Azure Resource Graph (no `Microsoft.ResourceGraph` traffic).
- ❌ Does not write any data back to Azure (no telemetry, no tagging, no annotations).
- ❌ Does not store credentials on disk (no secret-file mode, no caching of tokens beyond
  the SDK's in-memory cache for the lifetime of the process).
- ❌ Does not transmit Azure data to any third party. All output (PNG / DOT / DrawIO) is
  written locally to the working directory.

---

## 2. Permissions — What to Grant the CloudHorus Identity

### 2.1 Minimum required role
Grant the built-in **`Reader`** role at the smallest scope that covers what you want to
visualize.

| Visualization scope | Recommended role assignment scope |
|---------------------|------------------------------------|
| One resource group | `Reader` on the resource group |
| One subscription | `Reader` on the subscription |
| Multiple subscriptions in one tenant | `Reader` on each subscription, or on a Management Group |
| Cross-tenant (see §4) | `Reader` on each tenant's scope, granted to the same identity in each tenant |

### 2.2 Why `Reader` is sufficient
CloudHorus needs:

- `Microsoft.Resources/subscriptions/read`
- `Microsoft.Resources/subscriptions/resourceGroups/read`
- `Microsoft.Resources/subscriptions/resourceGroups/exportTemplate/action`
- `Microsoft.Resources/subscriptions/resourceGroups/resources/read`
- `Microsoft.Network/*/read` (for VNet, subnet, private endpoint, DNS zone enumeration)

All of these are included in the built-in `Reader` role. No custom role is required.

### 2.3 What you should *not* grant
- ❌ `Contributor` — gives write access; defeats the point.
- ❌ `Owner` — adds RBAC management; never needed.
- ❌ `Key Vault Secrets User` / `Storage Account Key Operator Service Role` — CloudHorus
  never reads secrets or keys.

If you accidentally grant a higher role, the L2 SDK policy still blocks any write call.

---

## 3. Execution Model — How CloudHorus Authenticates and Runs

### 3.1 Authentication methods

CloudHorus supports three authentication methods, selected via `--authMethod`:

| `--authMethod` | When to use | What happens |
|----------------|-------------|--------------|
| `device-code` *(default)* | Interactive use on a workstation. | A browser-based device-code flow prompts the operator to sign in. Token acquired, then cached in memory for the process lifetime only. |
| `service-principal` | Headless or scripted use where you control a dedicated SP. | Reads `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_CLIENT_SECRET` from environment variables. Auto-enables `--nonInteractive`. |
| `environment` | CI/CD runners where the pipeline already authenticated (GitHub Actions `azure/login`, Azure DevOps service connection, managed identity on a self-hosted runner). | Uses `DefaultAzureCredential` to detect existing credentials in this order: env vars → managed identity → `az login` session → Azure PowerShell. Auto-enables `--nonInteractive`. |

### 3.2 Non-interactive mode (`--nonInteractive`)
When set (or when `--authMethod` is `service-principal` or `environment`), CloudHorus:

- **Never prompts** for input on stdin.
- **Fails fast with exit code 1** if any code path would require interactive auth.
- **Skips** the device-code flow entirely; it will not print a code and wait.

Use this in any CI/CD context to prevent pipelines from hanging indefinitely.

### 3.3 Secret handling
CloudHorus deliberately **does not implement** a "read secret from file" mode. The only
supported way to provide a service principal secret is via the `AZURE_CLIENT_SECRET`
environment variable, which:

- Is consumed once at process start.
- Is **never logged**, **never echoed**, **never written to any file**.
- Lives only in the process's memory.

For CI/CD, use the runner's native secret store (GitHub Encrypted Secrets, Azure DevOps
Variable Groups linked to Key Vault, etc.) and inject it as an env var at job execution
time.

### 3.4 Process model — fully local execution
- CloudHorus runs as a **single Python process on your machine** (workstation, CI runner,
  or self-hosted server) — there is **no client/server split**, no daemon, no background
  worker, no hosted backend, no inbound network listener.
- The tool is distributed as **source code you run yourself** (or via the local launcher
  scripts). There is no managed service, no shared multi-tenant component, and no third
  party in the data path.
- Output files (PNG / DOT / DrawIO) are written to the **current working directory on the
  same machine**, owned by the invoking user, with default umask permissions. They are
  **never uploaded** anywhere by CloudHorus — sharing them is entirely under your control.
- **No state is persisted between runs.** No local database, no config cache containing
  resource data, no token cache on disk.

### 3.5 Network egress — what leaves your machine
CloudHorus only reaches **two Microsoft endpoints**, both required by the Azure SDK:

- `login.microsoftonline.com` (and equivalent token endpoints) — for authentication only.
- `management.azure.com` (or the sovereign-cloud equivalent) — for the read-only ARM API
  calls described in §1.2.

There are **no third-party endpoints**, **no telemetry endpoint**, **no analytics
endpoint**, and **no update-check endpoint**. CloudHorus is safe to run behind a strict
egress allowlist (see §5.3) and in air-gapped Bicep mode it makes **zero network calls**
at all.

---

## 4. CI/CD Integration Quick Reference

### 4.1 GitHub Actions (recommended pattern)
```yaml
jobs:
  visualize:
    runs-on: ubuntu-latest
    permissions:
      id-token: write   # for OIDC federated identity
      contents: read
    steps:
      - uses: actions/checkout@v4
      - uses: azure/login@v2
        with:
          client-id: ${{ secrets.AZURE_CLIENT_ID }}
          tenant-id: ${{ secrets.AZURE_TENANT_ID }}
          subscription-id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}
      - name: Generate architecture diagram
        run: |
          python3 src/main.py --authMethod environment \
            --tenants ${{ secrets.AZURE_TENANT_ID }} \
            --subscriptions ${{ secrets.AZURE_SUBSCRIPTION_ID }} \
            --resourcegroups my-rg
      - uses: actions/upload-artifact@v4
        with:
          name: architecture
          path: azure_resources*.png
```

No client secret is ever stored — `azure/login` uses OIDC federation, and CloudHorus picks
up the resulting token via `DefaultAzureCredential`.

### 4.2 Azure DevOps
```yaml
- task: AzureCLI@2
  inputs:
    azureSubscription: 'my-service-connection'   # provides az login session
    scriptType: 'bash'
    scriptLocation: 'inlineScript'
    inlineScript: |
      python3 src/main.py --authMethod environment \
        --tenants $(tenantId) \
        --subscriptions $(subscriptionId) \
        --resourcegroups my-rg
```

### 4.3 Self-hosted runner with managed identity
On any Azure VM / Container App / AKS pod with a system-assigned or user-assigned managed
identity that has `Reader` on the target scope:
```bash
python3 src/main.py --authMethod environment \
  --tenants <TENANT_ID> \
  --subscriptions <SUB_ID> \
  --resourcegroups <RG_NAME>
```
No credentials of any kind in the pipeline definition.

---

## 5. Audit & Verification

### 5.1 Verify the policy is active
The first ARM call from any CloudHorus run logs a confirmation. To independently verify,
add a temporary breakpoint or trace in `azure_cli.py` after a client is constructed:
```python
print(client._config.policies)  # ReadOnlyPolicy must appear in this list
```

### 5.2 Review activity logs
Every API call CloudHorus makes is recorded in the **Azure Activity Log**. Filter by:

- **Caller** = CloudHorus identity (UPN or SP object ID)
- **Operation** ∈ { `Microsoft.Resources/...read`, `Microsoft.Resources/.../exportTemplate/action`, `Microsoft.Network/.../read` }

You should never see any operation outside this set. If you do, file a security issue.

### 5.3 Network capture
On a constrained network, allowlist:
- `login.microsoftonline.com:443`
- `management.azure.com:443` (or the sovereign-cloud ARM endpoint)

Block everything else. CloudHorus will function with this restriction.

---

## 6. Reporting Security Issues
If you discover a vulnerability or a way to make CloudHorus perform any write operation,
please follow the disclosure process in [`SECURITY` policy](../CODE_OF_CONDUCT.md) (or
contact the maintainers directly). Do not open a public issue for security-sensitive
findings.
