# AzLimits Production MCP Skill Implementation Plan

## Overview

Add one portable, automatically discoverable agent skill that teaches coding agents to consult the configured AzLimits MCP tool before generating, modifying, reviewing, or approving production Azure architecture and IaC. Maintain the skill once under `.agents/skills/azlimits/` and expose it to GitHub Copilot, Codex, and Claude through relative directory symlinks.

The skill is for production use after onboarding is complete. It does not teach contributors how to develop this repository, configure the API, create tokens, run the server, or change the AzLimits implementation.

## Current State Analysis

AzLimits already exposes one local stdio MCP tool, `search_limitations(q, region?, sku?)`, backed by the protected REST endpoint. The server owns credential configuration, returns the complete typed response, and emits stable secret-safe failure codes. The missing piece is agent guidance for when to call the tool, how to decompose an Azure design into useful queries, and how to interpret incomplete or constrained results conservatively.

The repository already stores project skills under `.github/skills/`, but it has no AzLimits skill and no cross-client canonical-source convention. Git is configured with `core.symlinks=true` in the current checkout, so the requested relative directory symlinks can be represented as real Git symlinks.

## Desired End State

When an agent works on production Azure architecture or IaC, it automatically loads the `azlimits` skill and checks each relevant Azure service or feature through the configured MCP tool before finalizing the design. Its answer distinguishes unsupported, constrained, supported-with-known-records, zero-match, and tool-failure outcomes without overstating dataset completeness.

Every limitation presented to the user retains the source URL, source title, quote or excerpt, confidence, verification state, and useful age metadata. The agent never requests, accepts, repeats, stores, or troubleshoots a raw API token through conversation or tool arguments.

The canonical skill exists once at `.agents/skills/azlimits/`. Relative symlinks expose the same directory at `.github/skills/azlimits`, `.codex/skills/azlimits`, and `.claude/skills/azlimits`, and automated checks fail if any alias becomes a copy, a broken link, or resolves somewhere else.

### Key Discoveries

- The live MCP surface contains exactly `search_limitations` with required `q` and optional `region` and `sku`; credentials are process configuration, not tool inputs (`mcp_server.py:176`, `mcp_server.py:182`, `tests/test_mcp_server.py:195`).
- `region` and `sku` are echoed but not applied as v1 filters, so they cannot justify a region- or SKU-specific verdict (`schemas.py:26`, `schemas.py:30`, `tests/test_query_core.py:68`).
- Empty search results aggregate to `supported` internally, while the MCP contract explicitly says emptiness does not prove that no limitation exists (`query.py:57`, `mcp_server.py:176`).
- The product requires the agent to check before emitting or approving IaC and forbids results without provenance (`context/foundation/prd.md:44`, `context/foundation/prd.md:68`, `AGENTS.md:7`).
- AzLimits is a curated, non-exhaustive advisory dataset; it does not guarantee detection and does not perform automatic remediation or IaC generation (`context/foundation/prd.md:193`, `context/foundation/prd.md:195`, `context/foundation/prd.md:197`).
- Stable tool failures are configuration, authentication, license, and upstream availability errors (`mcp_server.py:42`, `mcp_server.py:131`, `README.md:285`).
- Existing project skills establish a minimal `SKILL.md` frontmatter convention with `name` and a discovery-oriented `description` (`.github/skills/tf-registry/SKILL.md:1`, `.github/skills/setup-cicd/SKILL.md:1`).

## What We're NOT Doing

- Changing the FastAPI application, MCP server, REST contract, query behavior, schema, database, authentication, licensing, onboarding CLI, or token lifecycle.
- Adding new MCP tools, resources, prompts, transports, retries, caching, semantic search, region filtering, or SKU filtering.
- Teaching repository setup, local development, test-database setup, API startup, MCP host configuration, OAuth onboarding, EULA acceptance, or token creation inside the skill.
- Asking a user to paste a token or putting token values in prompts, tool arguments, examples, logs, files, or shell commands.
- Claiming exhaustive Azure coverage, treating an empty result as approval, or allowing `region`/`sku` echo fields to imply filtering.
- Generating alternative IaC automatically after an unsupported result without the user making an explicit design decision.
- Publishing a marketplace package, Python distribution artifact, plugin, or separate release artifact.
- Copying the skill into client directories; the client paths remain symlinks to one canonical source.
- Cleaning up unrelated repository documentation or existing skill conventions.

## Implementation Approach

Use a compact, self-contained `SKILL.md`; the workflow and safety contract are small enough that scripts, assets, and supporting references would add indirection without reducing context. Keep the frontmatter portable across the Agent Skills implementations and rely on the description for automatic invocation.

The workflow is decision-oriented: inventory services and important features, issue concise service-focused calls, inspect `record_count` before the aggregate verdict, evaluate each returned record and its provenance, then apply a conservative production decision policy. `unsupported` blocks final generation or approval until the user explicitly changes or accepts the design; `constrained` requires evidence-backed adaptation or warning; zero records and tool failures leave validation inconclusive and block an “AzLimits-validated” claim.

Use `.agents/skills/azlimits/` as the canonical project location. Add relative directory symlinks from each requested client location so all clients load byte-identical instructions. Keep README documentation limited to skill discovery, canonical ownership, symlink portability, and the production-after-onboarding boundary.

## Critical Implementation Details

### Result sequencing

The agent must inspect `record_count` before `support_status`. The current query core returns `supported` for an empty set, so interpreting the aggregate first would turn missing coverage into a false approval.

### Symlink portability

The aliases must be repository-relative Git symlinks targeting `../../.agents/skills/azlimits`. On Windows, a checkout that does not permit symlinks may materialize link text as an ordinary file; verification must diagnose this explicitly instead of silently treating copies as equivalent.

## Phase 1: Canonical Production MCP Skill

### Overview

Create the canonical portable skill and a focused contract test that locks its behavioral and security invariants to the implemented MCP surface without testing incidental prose.

### Changes Required:

#### 1. Canonical AzLimits skill

**File**: `.agents/skills/azlimits/SKILL.md`

**Intent**: Define an automatically discoverable production workflow for checking Azure architecture and IaC with AzLimits after onboarding has already configured the MCP tool.

**Contract**: Frontmatter uses `name: azlimits` and a description that triggers for production Azure architecture and IaC generation, modification, review, and approval. The body must:

- Assume the MCP server is already configured and keep onboarding/development instructions out.
- Invoke only `search_limitations` with `q` and optional `region`/`sku`; never supply credentials, a URL, authorization headers, resource objects, or speculative tools.
- Inventory relevant Azure services/features and query them separately with concise service-oriented terms.
- State that `region` and `sku` are context echoed by v1, not applied filters.
- Inspect `record_count` before the aggregate verdict and label zero records as “no known matching record in the curated dataset,” never proof of support.
- Preserve per-record service, feature, status, limitation details/workaround, source URL/title, quote, confidence, verification state, verified date, and available first/last-seen dates when reporting a finding.
- Apply the agreed decision policy: stop final generation/approval on `unsupported`; explain and adapt or seek direction on `constrained`; present `supported` only as the verdict over known matching records; leave zero-match and failure outcomes inconclusive.
- Handle the four stable error classes without requesting or echoing secrets. Invalid-search variants of `azlimits_upstream_unavailable` should cause query correction rather than blind retry.
- Allow drafting to continue after an inconclusive check only when clearly labeled unvalidated; never describe it as AzLimits-approved.
- Keep automatic invocation enabled and avoid client-specific frontmatter that would reduce portability.

#### 2. Skill contract tests

**File**: `tests/test_azlimits_skill.py`

**Intent**: Detect drift between the skill and the real MCP/product invariants while keeping assertions semantic and resilient to prose editing.

**Contract**: Parse the canonical frontmatter and content to verify the skill name/description, exact live tool and input vocabulary, automatic production-IaC trigger, empty-result and v1 filter caveats, required provenance concepts, stable error-code coverage, and absence of credential-like examples or unsupported tool names. Tests should compare declared tool/input/error vocabulary against application constants or the MCP tool schema where practical, rather than duplicating a second hard-coded contract.

### Success Criteria:

#### Automated Verification:

- Canonical skill contract tests pass: `uv run pytest tests/test_azlimits_skill.py -v`.
- Existing MCP adapter contract remains green: `uv run pytest tests/test_mcp_server.py tests/test_query_core.py -v`.
- Ruff validates the new Python test: `uv run ruff check tests/test_azlimits_skill.py`.
- Mypy validates the new Python test within the project configuration: `uv run mypy tests/test_azlimits_skill.py`.

#### Manual Verification:

- Read `SKILL.md` from the perspective of an agent with a configured production MCP server and confirm no step asks it to clone, run, test, or modify this repository.
- Confirm the description naturally activates for both IaC generation and review, while ordinary Azure application-code development without an architecture/IaC decision does not match.
- Trace one `unsupported`, one `constrained`, and one zero-record outcome through the written decision policy; confirm none can become an unsupported “safe to deploy” statement.

**Implementation Note**: After completing Phase 1 and all automated verification passes, pause for human confirmation that the skill scope and decision language are correct before adding client aliases.

---

## Phase 2: Cross-Client Discovery and Repository Handoff

### Overview

Expose the canonical skill to GitHub Copilot, Codex, and Claude without introducing divergent copies, and document the ownership and checkout expectations.

### Changes Required:

#### 1. GitHub Copilot skill alias

**File**: `.github/skills/azlimits`

**Intent**: Make the canonical skill discoverable from GitHub Copilot’s repository skill path.

**Contract**: Relative directory symlink with target `../../.agents/skills/azlimits`; it must not contain a copied `SKILL.md`.

#### 2. Codex skill alias

**File**: `.codex/skills/azlimits`

**Intent**: Expose the same canonical skill through the requested Codex-specific project path.

**Contract**: Relative directory symlink with target `../../.agents/skills/azlimits`; it must resolve to the same canonical directory and contain no client-specific fork.

#### 3. Claude skill alias

**File**: `.claude/skills/azlimits`

**Intent**: Make the canonical skill discoverable from Claude’s repository skill path.

**Contract**: Relative directory symlink with target `../../.agents/skills/azlimits`; it must resolve to the same canonical directory and contain no client-specific fork.

#### 4. Symlink and discovery tests

**File**: `tests/test_azlimits_skill.py`

**Intent**: Extend the focused test suite to prove each requested client path is a real, unbroken symlink to the canonical skill.

**Contract**: Verify the three aliases with `Path.is_symlink()`, compare their link text to the expected repository-relative target, and compare resolved paths to `.agents/skills/azlimits`. Failure messages must explain the common Windows `core.symlinks` checkout issue.

#### 5. Skill discovery documentation

**File**: `README.md`

**Intent**: Add a concise production skill section near MCP documentation so maintainers know where the source lives, which client paths are aliases, and why edits belong only in the canonical directory.

**Contract**: Document the canonical and alias paths, automatic production Azure IaC trigger, post-onboarding prerequisite, and real-symlink checkout requirement. Link back to the existing MCP setup section for configuration; do not duplicate onboarding, token, or server-development instructions.

### Success Criteria:

#### Automated Verification:

- Canonical and alias contract tests pass: `uv run pytest tests/test_azlimits_skill.py -v`.
- Git records each client alias as a symlink (`120000` mode) and each resolves to `.agents/skills/azlimits`.
- README and test changes pass Ruff and mypy: `uv run ruff check tests/test_azlimits_skill.py` and `uv run mypy tests/test_azlimits_skill.py`.

#### Manual Verification:

- On a symlink-capable checkout, open `SKILL.md` through all four paths and confirm each displays byte-identical content.
- Start or reload GitHub Copilot, Codex, and Claude in this repository and confirm `azlimits` appears exactly once in each client’s available skills; record any client that ignores its requested alias path.
- Edit a harmless temporary character through one alias, confirm the canonical file reflects it, then revert that temporary edit before proceeding.
- Review the README section and confirm it points already-onboarded production users to the skill without teaching repository development.

**Implementation Note**: After completing Phase 2 and all automated verification passes, pause for human confirmation that all three clients discover the canonical skill and that the checkout preserves real symlinks.

---

## Phase 3: Behavioral Forward-Test and Production MCP Smoke Test

### Overview

Evaluate the skill as an agent instruction rather than only as text: run isolated realistic scenarios, then perform one human-supervised smoke test with a production-configured MCP client and an already-stored token.

### Changes Required:

#### 1. Verification record

**File**: `context/changes/skill/verification.md`

**Intent**: Record non-secret evidence from cross-client discovery, isolated forward-testing, and the production MCP smoke test so the change can be reviewed without retaining credentials or raw private configuration.

**Contract**: Capture date, client/model, scenario, observed skill invocation, tool calls by name and non-secret arguments, verdict behavior, provenance handling, pass/fail, and follow-up. Never record tokens, authorization headers, MCP environment values, private prompts/configuration, or raw responses beyond the minimal public-source evidence needed to assess behavior.

#### 2. Independent forward-testing

**Files**: `.agents/skills/azlimits/SKILL.md`, `tests/test_azlimits_skill.py`

**Intent**: Use an independent agent in an isolated temporary workspace to exercise realistic IaC generation/review requests without feeding it the desired answer, then make only evidence-backed corrections to the skill or semantic contract tests.

**Contract**: Cover at least these scenarios:

- A multi-service Azure design that requires separate service-focused searches.
- An `unsupported` record that must stop final IaC generation/approval and show provenance.
- A `constrained` record that requires an evidence-backed adjustment or user decision.
- A zero-record response whose aggregate status is `supported` but must remain inconclusive.
- A region/SKU request where the agent must state that v1 did not filter by those values.
- Each stable error class, including invalid-query correction without blind retry.
- An attempted prompt to paste a token or bypass an unavailable tool, which the skill must reject.

Forward tests must use mocked/synthetic tool outcomes unless the human explicitly authorizes a real production call. Generated artifacts belong in a disposable temporary directory and must not enter the repository.

### Success Criteria:

#### Automated Verification:

- Focused skill, MCP, and query tests pass together: `uv run pytest tests/test_azlimits_skill.py tests/test_mcp_server.py tests/test_query_core.py -v`.
- Repository quality gates pass with a disposable PostgreSQL `TEST_DATABASE_URL`: `uv run ruff check .`, `uv run mypy .`, and `uv run pytest tests/ -v --cov --cov-branch --cov-report=term-missing`.
- Independent forward-test results for all required scenarios are recorded as pass, or any observed failure has a corresponding skill/test correction and successful rerun.
- `context/changes/skill/verification.md` contains no credential-shaped values or private MCP configuration.

#### Manual Verification:

- In one already-configured production MCP client, request a review of a harmless representative Azure IaC design involving at least two services; confirm the skill invokes `search_limitations` separately for each relevant service before approval.
- Confirm the tool call exposes only `q`, optional `region`, and optional `sku`; inspect the client UI rather than printing environment variables or configuration.
- Confirm the response reports `record_count`, aggregate status, relevant record-level statuses, source URLs/titles, quotes, confidence, verification state, and dates without losing provenance.
- Exercise or simulate a zero-record response and confirm the agent says validation is inconclusive rather than supported or safe.
- Exercise one safe failure path without changing or revealing the stored token; confirm the agent names the failure class, does not request the token, and does not claim validation succeeded.
- Confirm no test transcript, screenshot, terminal output, verification note, or repository diff contains a token, authorization header, secret-store value, or private MCP configuration.
- Review the final IaC response and confirm `unsupported` blocks approval, `constrained` produces a warning/adjustment, and only an explicit user decision can continue past a blocked outcome.

**Implementation Note**: Phase 3 is complete only after the human confirms the production MCP smoke checklist. Automated and synthetic evidence cannot mark the manual rows complete.

---

## Testing Strategy

### Unit Tests

- Parse and validate canonical frontmatter and the semantic production trigger.
- Compare the skill’s declared tool/input vocabulary with the live MCP schema where practical.
- Verify zero-result, echo-only region/SKU, provenance, error, and secret-handling invariants.
- Verify all aliases are real relative symlinks resolving to the canonical directory.
- Prefer semantic sets and parsed contracts over exact paragraphs or heading snapshots.

### Integration Tests

- Retain the in-memory MCP adapter tests proving the tool schema, structured source-backed response, and safe error behavior.
- Run the skill contract tests alongside MCP/query tests to catch drift across instruction and runtime boundaries.
- Run isolated independent-agent scenarios with synthetic MCP outcomes before any production smoke call.

### Manual Testing Steps

1. Confirm all three clients discover one `azlimits` skill from the shared canonical content.
2. Use a harmless two-service production-IaC review request with an already-configured MCP client.
3. Inspect non-secret tool arguments and confirm service-by-service decomposition.
4. Verify evidence and conservative decision behavior for returned records.
5. Simulate zero-match and safe failure outcomes without exposing or modifying credentials.
6. Review the repository diff and verification record for secrets and copied skill content.

## Performance Considerations

The skill introduces no application runtime cost. Agent latency grows roughly with the number of relevant Azure services because the agreed workflow issues focused calls per service or feature; this is intentional for query precision. The skill should avoid duplicate aliases and repeated queries for the same service/context within one decision unless new information changes the query.

Keep `SKILL.md` concise and self-contained so automatic invocation does not consume unnecessary context. Do not add scripts or references unless forward-testing demonstrates a concrete need.

## Migration Notes

There is no database, API, or dependency migration. Existing `.github/skills/*` directories remain unchanged. The new AzLimits alias is additive.

Git symlink support is a checkout prerequisite. Contributors whose Windows checkout materializes symlinks as files must enable an appropriate symlink-capable Git/OS setup and re-check out the affected paths; the implementation must not replace the links with copied directories as a workaround.

Rollback is deletion of the three aliases, the canonical `.agents/skills/azlimits/` directory, the focused test, the README section, and the change verification artifact. No production service rollback is required.

## References

- Product contract: `context/foundation/prd.md:31`
- Repository safety rules: `AGENTS.md:5`
- Live MCP tool: `mcp_server.py:152`
- Search response schema: `schemas.py:6`
- Query and aggregate behavior: `query.py:3`
- MCP operator contract and safe failures: `README.md:230`
- Existing MCP contract tests: `tests/test_mcp_server.py:195`
- Region/SKU schema test: `tests/test_query_core.py:68`
- Existing project skill convention: `.github/skills/tf-registry/SKILL.md:1`
- Historical MCP design: `context/archive/2026-08-16-mcp-tool-wrapper/plan-brief.md`
- Skill authoring guidance consulted during planning: Codex `skill-creator`, GitHub Copilot agent-skills documentation, and Claude skill-authoring guidance.

## Progress

> Convention: `- [ ]` pending, `- [x]` done. Append ` — <commit sha>` when a step lands. Do not rename step titles.

### Phase 1: Canonical Production MCP Skill

#### Automated

- [x] 1.1 Canonical skill contract tests pass — cd529a6
- [x] 1.2 Existing MCP adapter contract remains green — cd529a6
- [x] 1.3 Ruff validates the new Python test — cd529a6
- [x] 1.4 Mypy validates the new Python test — cd529a6

#### Manual

- [x] 1.5 Confirm the skill excludes repository development and setup work — cd529a6
- [x] 1.6 Confirm automatic production IaC invocation boundaries — cd529a6
- [x] 1.7 Trace unsupported, constrained, and zero-record decisions — cd529a6

### Phase 2: Cross-Client Discovery and Repository Handoff

#### Automated

- [x] 2.1 Canonical and alias contract tests pass
- [x] 2.2 Git records all client aliases as resolving symlinks
- [x] 2.3 README and test changes pass Ruff and mypy

#### Manual

- [x] 2.4 Confirm byte-identical content through all four paths
- [x] 2.5 Confirm one-skill discovery in GitHub Copilot, Codex, and Claude
- [x] 2.6 Confirm edits through an alias affect only the canonical file
- [x] 2.7 Confirm README preserves the production-after-onboarding boundary

### Phase 3: Behavioral Forward-Test and Production MCP Smoke Test

#### Automated

- [ ] 3.1 Focused skill, MCP, and query tests pass together
- [ ] 3.2 Repository quality gates pass
- [ ] 3.3 Required independent forward-test scenarios pass
- [ ] 3.4 Verification record contains no credential-shaped data

#### Manual

- [ ] 3.5 Confirm service-by-service production MCP invocation
- [ ] 3.6 Confirm tool calls expose only supported non-secret arguments
- [ ] 3.7 Confirm complete source-backed result presentation
- [ ] 3.8 Confirm zero-record behavior remains inconclusive
- [ ] 3.9 Confirm safe failure handling without credential disclosure
- [ ] 3.10 Confirm no verification artifact contains secrets
- [ ] 3.11 Confirm unsupported and constrained decision policy
