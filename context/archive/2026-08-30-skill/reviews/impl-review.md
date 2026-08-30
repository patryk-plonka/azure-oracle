<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: AzLimits Production MCP Skill

- **Plan**: context/changes/skill/plan.md
- **Scope**: Full plan — Phases 1–3 of 3
- **Date**: 2026-08-30
- **Verdict**: NEEDS ATTENTION
- **Findings**: 0 critical, 4 warnings, 3 observations

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | WARNING |
| Scope Discipline | PASS |
| Safety & Quality | WARNING |
| Architecture | PASS |
| Pattern Consistency | WARNING |
| Success Criteria | PASS |

## Evidence gathered

- All seven planned changes verified MATCH against their stated contracts; no scope-guardrail violation found across `cd529a6`, `d2b977b`, `083bdec`, `86bb825`.
- Success criteria re-run fresh: `ruff check .` clean, `mypy .` 36 files clean, `pytest tests/` 271 passed at 88.90% coverage (88% floor), focused suites 75 passed, all three aliases mode `120000` on one shared blob.
- **Mutation test**: six semantic mutations to `SKILL.md` (invent a tool name, drop the `quote` provenance field, read the verdict before the count, soften the `unsupported` policy, drop an error class, let a zero result read as proof of support). All six were caught, each by the semantically correct test; skill restored byte-identical. The contract tests are not vacuous.
- `.gitignore` deviation verified narrow by `git check-ignore -v`: only `.github/skills/azlimits` is un-ignored; `tf-registry`, `setup-cicd`, and 29 other local-only skills remain ignored, as does all other `.github` content.

## Post-triage state

After the F1–F4, F6 and F7 fixes were applied, the mutation suite was re-run and extended with two mutations targeting the newly-closed gaps — inventing an input via a call signature (`` `search_limitations(q, max_results)` ``) and inventing a camelCase tool alias (`` `listLimitations` ``). **8/8 caught**, skill restored byte-identical. Focused suites 75 passed; `ruff check .` and `mypy .` clean.

Both forms escaped the guard before F2 was fixed, which is the direct evidence that the fix closed a real gap rather than a theoretical one.

## Findings

### F1 — Live-vocabulary test passes green on an empty MCP surface

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: tests/test_azlimits_skill.py:139-145
- **Detail**: `test_skill_uses_only_the_live_tool_and_input_vocabulary` iterates `tool_names` and `tool_inputs` from the live MCP schema. If the server ever exposed zero tools, both loops become no-ops and the test passes. Verified directly: with empty frozensets, 0 assertions execute. This is precisely the regression the test exists to catch — a tool vanishing from the surface. The same shape affects the `unknown` set at line 160.
- **Fix**: Add `assert tool_names` and `assert tool_inputs` before the loops, and `assert backticked_identifiers(BODY)` before the subset check at line 160.
- **Decision**: FIXED — assert non-empty tool/input/vocabulary sets before the loops

### F2 — Invented-vocabulary guard only sees pure snake_case backtick spans

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Safety & Quality
- **Location**: tests/test_azlimits_skill.py:109-112, 148-164
- **Detail**: `backticked_identifiers` keeps a span only if `re.fullmatch(r"[a-z][a-z0-9_]*")` matches the whole span, so anything else is silently invisible to the no-invented-vocabulary test. Probed directly: `` `listLimitations` ``, `` `azlimits.search` ``, `` `search-limitations` ``, `` `search_limitations(q, max_results)` ``, `` `AZLIMITS_MAX_RESULTS` ``, and `` `records[0].severity` `` all yield an empty set. The last of these matters most — documenting a call with its arguments is the most idiomatic way a future editor would introduce a fake parameter. Today the guard works for the right reason (26 identifiers extracted, 3 legitimate prose spans dropped), so this is a coverage gap, not a live defect.
- **Fix A ⭐ Recommended**: Tokenize inside each span (`re.findall(r"[A-Za-z_][A-Za-z0-9_]*", span)`) and filter against a small prose stoplist.
  - Strength: Catches every probe form above, including the call-with-arguments case.
  - Tradeoff: Needs a stoplist for legitimate prose spans like `Azure Kubernetes Service`, which is a small maintenance surface.
  - Confidence: MEDIUM — the tokenizing is trivial; the stoplist is judgment.
  - Blind spot: Have not checked how the stoplist behaves if the skill later adds more prose query examples.
- **Fix B**: Leave as-is and rely on the mutation test as the periodic check.
  - Strength: No new maintenance surface; the guard demonstrably works today.
  - Tradeoff: The gap reopens silently whenever someone edits the skill without re-running a mutation test.
  - Confidence: HIGH — accurately describes the status quo.
  - Blind spot: No mutation test is wired into CI, so nothing re-checks this automatically.
- **Decision**: FIXED via Fix A — tokenize inside backtick spans; stoplist consulted only for non-lowercase tokens

### F3 — Error-class contract over-attracts any lowercase `azlimits_*` symbol

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: tests/test_azlimits_skill.py:44-46 (feeding :199-203)
- **Detail**: `ERROR_CODES` scans all of `mcp_server.py` with `\bazlimits_[a-z_]+\b`. Any future lowercase symbol starting `azlimits_` — a helper named `azlimits_search_url`, a local variable, even a docstring mention — silently joins the "stable error class" set and makes the test demand that `SKILL.md` document a non-error as a failure class. Benign today: the scan yields exactly the four real codes.
- **Fix**: Anchor the regex to the emission shape — `r'"(azlimits_[a-z_]+):'` — since all four occurrences are string-literal prefixes of the form `"azlimits_x: ..."`.
- **Decision**: FIXED — regex anchored to the string-literal emission shape

### F4 — Symlink-target test loses the Windows hint the plan required

- **Severity**: ⚠️ WARNING
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: tests/test_azlimits_skill.py:293
- **Detail**: The plan's Phase 2 contract states "Failure messages must explain the common Windows `core.symlinks` checkout issue." `test_client_alias_targets_the_canonical_skill_relatively` calls `os.readlink()` with no `is_symlink()` guard, so on a checkout that materialized the alias as a plain file it raises a bare `OSError` — a test *error* carrying none of `SYMLINK_HINT`. The neighbouring test at :281-288 fails cleanly with the hint; this one does not.
- **Fix**: Guard with `if not path.is_symlink(): pytest.fail(f"{alias} is not a symlink. {SYMLINK_HINT}")` before the readlink call.
- **Decision**: FIXED — is_symlink() guard with SYMLINK_HINT before os.readlink

### F5 — Import-time file I/O turns a bad SKILL.md into a module collection error

- **Severity**: 📋 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: tests/test_azlimits_skill.py:44-46, 89
- **Detail**: `ERROR_CODES` and `FRONTMATTER, BODY` are computed at import, and `_split_skill` uses bare `assert`. A missing or malformed `SKILL.md` therefore fails collection for the entire module rather than producing one clearly-named failing test. Neither `test_mcp_server.py` nor `test_query_core.py` performs import-time I/O — this is the only substantive pattern divergence in the change.
- **Fix**: Move both reads behind `@lru_cache` accessors, the pattern already used in this file by `live_tool_contract` and `git_index_modes`.
- **Decision**: SKIPPED — ~15 call sites churned for a cosmetic failure-reporting gain

### F6 — Invalid-query clause regex over-captures to end of file

- **Severity**: 📋 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Safety & Quality
- **Location**: tests/test_azlimits_skill.py:206-212
- **Detail**: `azlimits_upstream_unavailable` is the last bullet in `## Failures`, so the lookahead `(?=\n- \`|\Z)` captures through the closing paragraph. `"correct the query"` and `"blind"` could in future be satisfied by unrelated trailing text rather than the intended clause. Correct today — neither phrase appears in the trailing paragraph.
- **Fix**: Widen the lookahead to `(?=\n- \`|\n\n|\n## |\Z)`.
- **Decision**: FIXED — lookahead widened to terminate at the end of its own bullet

### F7 — Verification record omits the client/model identifier its contract asked for

- **Severity**: 📋 OBSERVATION
- **Impact**: 🏃 LOW — quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: context/changes/skill/verification.md
- **Detail**: The Phase 3 contract lists "date, **client/model**, scenario, observed skill invocation, …". The record names clients (Claude Code; Copilot/Codex; "a client with the AzLimits MCP server already configured") but never records a model identifier for the forward-test agents or the smoke-test client, so the behavioral evidence cannot be attributed to a specific model later. Everything else in the contract is present, and the record explicitly discloses that the smoke-test rows capture a whole-checklist operator confirmation rather than transcribed tool output.
- **Fix**: Add the model identifier for the forward-test agents and the smoke-test client to the Environment table.
- **Decision**: FIXED — forward-test model (Claude Opus 5) and smoke-test client/model (Codex, GPT-5.6 Sol) recorded
