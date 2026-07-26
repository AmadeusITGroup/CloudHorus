# Terraform plan diff sample

`landing-zone.plan.json` is a hand-written `terraform show -json` document for manually
testing Plan_Diff_Mode. It needs no Azure access and no Terraform CLI.

```bash
python src/main.py --terraformJsonFiles samples/terraform-plan-diff/landing-zone.plan.json
```

Scope comes from the synthesized default (`cloudhorus-tenant` / `cloudhorus-subscription` /
`cloudhorus-rg-1`), which is also what the subnet resource IDs inside the plan reference.

## What the plan exercises

| Change_Category | Resources |
| --- | --- |
| create | `snet-data`, `app-api` (module-prefixed address, placed in `snet-app`), `stassetsnew` |
| update | `vnet-hub` (container), `plan-app`, `rt-egress` (Skip_Filter), `kv-platform` (unmapped type) |
| replace | `aks-platform` (`["delete","create"]`, placed in `snet-app`) |
| delete | `stassetslegacy`, `pe-legacy-storage` (in `snet-app`), `sql-reporting` |
| unchanged | `snet-app`, `redis-session` |

Also covered:

- **Delete reconstruction** — the three deleted resources are absent from `planned_values`
  and exist only in `resource_changes[].change.before`.
- **Sensitive redaction** — `site_credential`, `kube_admin_config_raw`, `primary_access_key`
  and `administrator_login_password` are flagged in `after_sensitive` / `before_sensitive` /
  `sensitive_values`; none of their values may appear in the diagram, the logs, the summary
  or a Draw.io export.
- **Excluded entries** — a `data` mode entry and a `hashicorp/random` resource, both dropped
  with a warning.
- **Container retention** — `vnet-hub` (`update`) and `snet-app` (`unchanged`) survive a
  `--changeTypes delete` run because deleted resources sit inside them.

## Things to look at

```bash
# only the destructive changes, containers retained
python src/main.py --terraformJsonFiles samples/terraform-plan-diff/landing-zone.plan.json \
  --changeTypes delete replace

# invalid value: reports the accepted values and exits non-zero
python src/main.py --terraformJsonFiles samples/terraform-plan-diff/landing-zone.plan.json \
  --changeTypes destroy
```

Each run writes `azure_resources_<timestamp>.change-summary.json` next to the PNG, which is
what the WebUI change-filter chips read.
