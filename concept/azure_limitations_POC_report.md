# Azure Service Limitations Database — Proof of Concept

Date: 2026-06-05
Author: Perplexity Computer (research agent)
Status: **POC successful** — the approach is viable.

## 1. Objective

Test whether it is feasible to build a simple, structured database of Azure
service limitations (unsupported scenarios, known issues, quotas, preview-only
behavior, deprecations, and workarounds) in a tabular format:
`service | limitation type | details | source`, enriched with the metadata
schema from the source inventory.

## 2. Verdict

**Yes — it is feasible and produces high-quality, citable output.** A working
sample database of **93 limitation records across 14 Azure service areas** was
built from authoritative Microsoft sources, including issue-level signal from
product GitHub repos (ACR, Container Apps) now that the GitHub connector is
authenticated. The structured-extraction pipeline
(fetch page → LLM-extract into a table → normalize into schema rows) works
reliably and is repeatable/scalable.

## 3. Deliverables

| File | Description |
|---|---|
| `azure_limitations_db.csv` | The database, 87 rows × 20 columns |
| `azure_limitations_db.xlsx` | Same data, filterable Excel workbook |
| `build_db.py` | Reproducible build script (each record traceable to a source) |
| `azure_limitations_POC_report.md` | This report |

## 4. Schema implemented

The full metadata schema from the source inventory was implemented:

`id, service, feature, support_status, limitation_type, condition, details,
environment, region, sku_tier, auth_mode, network_mode, source_type,
source_url, source_title, quote, workaround, confidence, first_seen, last_seen`

Every record keeps the **original quoted sentence** plus **provenance**
(source_url + source_title + source_type), as recommended for precision and
auditability.

### support_status enum used
`supported, not_supported, partially_supported, known_issue, preview,
deprecated, retired, support_ticket_required` (the inventory also allows
`private_preview, gated, workaround_available, unclear` — the field accepts them).
The ACR "Anonymous Pull" row is a real `support_ticket_required` / `gated`
example captured from a maintainer-triaged GitHub roadmap issue.

## 5. Coverage of the sample (93 records)

By service: Azure Firewall (18), AKS (12), Blob Storage/SFTP (11), Azure
Resource Manager (11), Azure Functions (9), Resource Groups (7),
Subscriptions (5), Azure Local (5), Site Recovery (4), Container Apps (4),
Management Groups (3), Container Registry (2), ARM Templates (1), Networking (1).

By support_status: not_supported (36), supported/quota (27), known_issue (22),
partially_supported (2), preview (2), deprecated (2), retired (1),
support_ticket_required (1).

By source type: Learn docs (48), Learn troubleshoot (34), GitHub repo issues (6),
GitHub docs repo (5).

## 6. Sources successfully harvested

All from the highest-trust tiers (Learn docs + Learn troubleshoot + open-source
docs repos):

1. [Azure subscription and service limits](https://learn.microsoft.com/en-us/azure/azure-resource-manager/management/azure-subscription-service-limits)
2. [Azure Firewall known issues and limitations](https://learn.microsoft.com/en-us/troubleshoot/azure/firewall/firewall-known-issues)
3. [SFTP in Azure Blob Storage — limitations & known issues](https://learn.microsoft.com/en-us/azure/storage/blobs/secure-file-transfer-protocol-known-issues)
4. [Common ARM deployment errors](https://learn.microsoft.com/en-us/azure/azure-resource-manager/troubleshooting/common-deployment-errors)
5. [Resource move not supported](https://learn.microsoft.com/en-us/troubleshoot/azure/virtual-machines/windows/move-resources-resource-type-not-supported)
6. [Site Recovery / Scout 8.0.1 unsupported features](https://learn.microsoft.com/en-us/troubleshoot/azure/site-recovery/getting-started/unsupported-features-and-platforms-post-upgrade)
7. [AKS quotas, SKUs, regions](https://learn.microsoft.com/en-us/azure/aks/quotas-skus-regions)
8. [Azure Functions scale and hosting](https://learn.microsoft.com/en-us/azure/azure-functions/functions-scale)
9. [Azure Local known issues](https://github.com/MicrosoftDocs/azure-stack-docs/blob/main/azure-local/known-issues.md) (fetched as raw markdown)
10. Product GitHub repo issues via `gh` CLI: [ACR](https://github.com/Azure/acr/issues) (#790 credentialSets, #381 Anonymous Pull) and [Container Apps](https://github.com/microsoft/azure-container-apps/issues) (#801, #611, #488, #1151)

## 7. Obstacles encountered (as requested, documented and worked around)

### OBSTACLE 1 — GitHub connector (RESOLVED)
The GitHub connector was initially DISCONNECTED, so the first pass relied on a
workaround: fetching public docs-source repos as **raw markdown over HTTPS**
(`raw.githubusercontent.com`), which needs no auth and captured the Azure Local
known-issues file.
- **Now resolved:** GitHub was authenticated and queried via the `gh` CLI. This
  added the **product-repo issue signal class** with maintainer labels
  (`feature-request`, `triaged`, `roadmap`, `bug`, `enhancement`): ACR
  credentialSets/UserAssigned gap, ACR Anonymous Pull (`support_ticket_required`),
  Container Apps outbound-IP/static-egress/tokenStore/OpenTelemetry limitations.
- **Confidence handling:** These rows are tagged `confidence=medium` (vs. `high`
  for Learn docs), per the ranking guidance — community/issue claims should sit
  below official docs until doc-corroborated.

### OBSTACLE 2 — "What's new" / changelog pages rarely hold limitations
The Container Apps `whats-new` page contained **no** limitations/quotas. Lifecycle
and limitation content live on *different* pages than announcement pages. A
crawler must target dedicated "known issues", "limits", and "troubleshoot"
pages, not changelogs.

### OBSTACLE 3 — Heterogeneous page structure
Limitations appear as prose, multi-column tables, footnoted matrices, and
"by design" notes. There is **no single canonical Azure limitations database** —
confirming the premise of the source inventory. LLM-based extraction handled
this heterogeneity well, but a pure-regex/HTML scraper would be brittle.

### OBSTACLE 4 — Versioned / fast-moving content
Several pages are version-pinned (e.g. Azure Local `?view=azloc-2605`) and
Firewall capacity constraints carry dated "estimated available" notes. The
`first_seen`/`last_seen` fields are essential; the DB must be re-run on a
schedule to stay accurate. Numeric limits and quota policies also change
(e.g. AKS quota rollout in Sept 2025).

### OBSTACLE 5 — Community/Q&A tiers not yet tapped
Microsoft Q&A, Tech Community, and Azure OSS blogs (medium-trust tiers) were
deferred for the POC in favor of proving the high-trust pipeline first. They
are reachable with the same `fetch_url` approach and would add edge-case and
"community-confirmed" rows (lower `confidence` value).

## 8. Recommendations to productionize

1. **Maintain a seed list** of known-issues/limits/troubleshoot URLs per service
   (the `azure-docs` GitHub org can be enumerated for filenames matching
   `known-issues|limitations|support-matrix|troubleshooting`).
2. **GitHub is now connected** — expand issue harvesting across more repos
   (Azure Policy, AKS, Storage) and pull issue *comments* for maintainer status;
   keep those rows at `confidence=medium` unless doc-corroborated.
3. **Schedule periodic re-crawls** and diff on `quote`/value to detect newly
   introduced or removed limitations; update `last_seen`.
4. **Keep source discovery separate from support-status classification** (as the
   inventory advises) and always retain the original quote + URL.
5. **Layer community sources** (Q&A, Reddit, Tech Community) as discovery-only,
   flagged low-confidence until mapped to a Microsoft-owned source.

## 9. Conclusion

The proof-of-concept confirms the hypothesis: a simple, structured, citable
database of Azure limitations **can** be assembled by crawling Microsoft Learn
docs, troubleshoot pages, and open-source docs repos, then normalizing into a
fixed schema with provenance. The main scaling levers are (a) a curated URL
seed set, (b) GitHub API access for issue-level signal, and (c) scheduled
re-crawls to handle Azure's fast-moving lifecycle.
