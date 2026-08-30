# AzLimits Production MCP Skill — Plan Brief

> Full plan: `context/changes/skill/plan.md`

## What & Why

Add a portable agent skill that makes AzLimits part of production Azure architecture and IaC generation/review. The skill closes the gap between having an MCP tool and using it safely at the decision point, where an unsupported Azure choice is still cheap to change.

## Starting Point

AzLimits already provides one protected, source-backed MCP tool: `search_limitations(q, region?, sku?)`. The repository documents setup but has no agent playbook for when to call the tool, how to query multi-service designs, or how to interpret incomplete results conservatively.

## Desired End State

GitHub Copilot, Codex, and Claude automatically discover the same canonical `azlimits` skill when working on production Azure architecture or IaC. Agents query each relevant service, preserve source evidence, stop on unsupported outcomes, adapt or warn on constrained outcomes, and never treat zero matches or tool failures as proof of support. The skill assumes onboarding and MCP configuration are complete and contains no repository-development, server-setup, token-creation, or credential-handling workflow.

## Key Decisions Made

| Decision | Choice | Why |
| --- | --- | --- |
| Canonical location | `.agents/skills/azlimits/` | Uses the shared Agent Skills project convention and gives one maintained source. |
| Client exposure | Relative symlinks under `.github`, `.codex`, and `.claude` | All requested clients see identical content without copy drift. |
| Invocation | Automatic for production Azure architecture and IaC generation/review | Limitations should be checked before design decisions become expensive. |
| Scope | Configured MCP usage only, after onboarding | Keeps operational guidance focused and avoids duplicating setup documentation. |
| Query strategy | One concise query per relevant service or feature | The current search is service-oriented, not semantic architecture analysis. |
| Unsupported result | Stop final generation/approval and present evidence | Prevents an agent from knowingly approving an unsupported design. |
| Constrained result | Warn and adapt or seek user direction | Keeps the human in control while using known limitations constructively. |
| Zero records or tool failure | Inconclusive; never “AzLimits-validated” | The curated dataset is incomplete and empty aggregation currently reads `supported`. |
| Verification | Static contract tests, independent scenarios, and production MCP smoke | Checks packaging, instruction behavior, and real client/tool integration. |

## Scope

**In scope:**

- One concise, portable `SKILL.md` with service inventory and focused MCP queries.
- Conservative result, provenance, freshness, and error interpretation.
- Automatic invocation for Azure IaC generation, modification, review, and approval.
- Cross-client symlinks, concise ownership documentation, contract tests, behavioral scenarios, and a production smoke test.

**Out of scope:**

- API/MCP/query/auth/database changes, new tools, or copied client variants.
- Onboarding, token creation, server setup, or repository development in the skill.
- Filtering, semantic search, exhaustive coverage, automatic remediation, or separate publication.

## Architecture / Approach

```text
.agents/skills/azlimits/        canonical SKILL.md
          ▲
          ├── .github/skills/azlimits  (symlink)
          ├── .codex/skills/azlimits   (symlink)
          └── .claude/skills/azlimits  (symlink)
Agent → inventory Azure services → search_limitations per service
      → inspect record_count first → assess evidence/status
      → block, adapt/warn, or label validation inconclusive
```

## Phases at a Glance

| Phase | What it delivers | Key risk |
| --- | --- | --- |
| 1. Canonical Production MCP Skill | Portable workflow and semantic contract tests | Guidance could overstate empty or scoped results. |
| 2. Cross-Client Discovery | Relative aliases and repository handoff | Windows checkout may materialize links incorrectly. |
| 3. Behavioral and Production Verification | Independent scenarios plus real configured-client smoke evidence | Tests could pass while an agent still makes unsafe claims. |

**Prerequisites:** Onboarding completed; each production client has a configured AzLimits MCP server; Git checkout preserves symlinks.
**Estimated effort:** ~2–3 focused sessions across three phases, including human checks in each client.

## Open Risks & Assumptions

- The `.codex/skills` project alias is included as explicitly requested; client discovery must be confirmed manually because shared `.agents/skills` support may already make it redundant.
- Git symlink behavior depends on OS permissions and checkout configuration; copied fallback directories are intentionally rejected.
- The production smoke test requires an existing secret-store-backed token, but no test or verification artifact may expose it.

## Success Criteria (Summary)

- All three clients automatically discover one byte-identical `azlimits` skill and apply it to production Azure IaC work.
- Agents use only the implemented tool contract, retain complete provenance, and never turn zero records, unfiltered region/SKU context, or tool failure into false approval.
- Unsupported designs stop before approval, constrained designs require an evidence-backed response, and all verification layers pass without exposing credentials.
