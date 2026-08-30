---
name: azlimits
description: Check Azure service limitations with the configured AzLimits MCP tool before generating, modifying, reviewing, or approving production Azure architecture and infrastructure-as-code (IaC) such as Bicep, ARM templates, or Terraform for Azure.
---

# AzLimits — Verify Azure Limitations Before IaC Lands

Use this skill whenever you design, generate, modify, review, or approve production Azure
architecture or IaC. Check limitations at the decision point, while the design is still cheap
to change.

The AzLimits MCP server is already configured by the user. This skill is for using it, not for
setting it up: never ask the user to clone, build, launch, or reconfigure anything, and never
ask for, accept, repeat, or store an API token or any other credential.

## The Only Tool

`search_limitations`, with one required argument `q` and two optional arguments `region` and
`sku`.

- Pass nothing else. No credential, no base URL, no authorization header, no resource object,
  no template body. Credentials are process configuration, never tool input.
- Do not invent or call any other AzLimits tool, resource, or prompt. This is the whole surface.
- `region` and `sku` are echoed context only: "Region and SKU are echoed but not applied as
  filters in v1." A result therefore never justifies a region- or SKU-specific verdict on its
  own. When the user asked about a region or SKU, say this explicitly.

## Workflow

1. **Inventory.** List every Azure service and notable feature the design touches — compute,
   networking, storage, registry, management scopes, and anything a limitation could plausibly
   block.
2. **Query one at a time.** Issue a separate call per service or feature, with concise
   service-oriented terms: `Azure Kubernetes Service`, `Azure Firewall`, `Blob Storage SFTP`.
   The search matches services and features; it is not semantic architecture analysis, so one
   sentence describing the whole design finds nothing useful.
3. **Read `record_count` first.** Always. The aggregate `support_status` reports `supported`
   for an empty set, so reading the verdict before the count turns missing coverage into a
   false approval.
4. **Assess each returned record**, then decide with the policy below.
5. **Report the evidence**, never a bare verdict.

Do not repeat the same query for the same service within one decision unless new information
changes the query.

## Reading The Response

`record_count` of 0 means **no known matching record in the curated dataset**. That is not
proof of support. AzLimits is a curated, non-exhaustive advisory dataset; absence from it does
not mean absence of a limitation.

`record_count` above 0 means the aggregate `support_status` is a verdict over the known
matching records only, in the vocabulary `supported`, `constrained`, `unsupported`.

For every record you surface, keep its provenance intact: `service`, `feature`,
`support_status`, `limitation_type`, `details`, `workaround`, `source_url`, `source_title`,
`quote`, `confidence`, `verification_state`, `verified_at`, and `first_seen` / `last_seen`
where present. A limitation presented without its source URL, source title, quote, confidence,
and verification state is a defect. Use `verified_at`, `first_seen`, and `last_seen` to tell
the user how old the evidence is.

## Decision Policy

- **unsupported** — Stop. Do not emit final IaC and do not approve the reviewed IaC. Present
  the blocking records with full provenance and ask the user to change the design or explicitly
  accept the risk. Only that explicit user decision continues past a block. Do not silently
  substitute an alternative architecture; offer options and let the user pick.
- **constrained** — Warn and act. Explain the limitation and its recorded workaround, then
  either adapt the design with the evidence stated, or ask the user to decide when adapting
  would change their intent.
- **supported** — Report it as "no blocking limitation among the known matching records", along
  with the records that matched. It is not a guarantee of support.
- **zero records** — Validation is **inconclusive**. Say so.
- **tool failure** — Validation is **inconclusive**. Say so.

Never call a design "AzLimits-validated", "AzLimits-approved", or safe to deploy on the
strength of a zero-record result or a failed call. You may keep drafting after an inconclusive
check only if you label the affected part clearly as unvalidated.

## Failures

The tool returns stable, secret-free error codes. Name the class, continue where you safely
can, and mark the affected services unvalidated.

- `azlimits_configuration_error` — the server is not configured. Tell the user; do not guess
  settings and do not ask for a credential.
- `azlimits_authentication_error` — the configured credential was rejected. Tell the user to
  refresh it through their own secret store. Never ask them to paste it to you.
- `azlimits_license_error` — the account lacks an active Demo license. Tell the user; there is
  nothing here for you to fix.
- `azlimits_upstream_unavailable` — either the API is unreachable, or the request was out of
  contract. If `q` was empty, longer than 200 characters, or otherwise malformed, correct the
  query and call again. Otherwise report unavailability rather than retrying blindly.

If the tool cannot run, say the check did not happen. Do not substitute your own recollection
of Azure limits as if it were an AzLimits result.
