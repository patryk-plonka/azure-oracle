<!-- IMPL-REVIEW-REPORT -->
# Implementation Review: Auth Scaffold — Token & License Validation

- **Plan**: context/changes/auth-scaffold-token-license/plan.md
- **Scope**: Phases 1-5 of 5
- **Date**: 2026-08-03
- **Verdict**: APPROVED
- **Findings**: 0 critical, 3 warnings, 1 observation

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Plan Adherence | PASS |
| Scope Discipline | PASS |
| Safety & Quality | PASS |
| Architecture | PASS |
| Pattern Consistency | PASS |
| Success Criteria | PASS |

## Verification Evidence

- PASS: `uv run pytest tests/ -v` - 35 passed.
- PASS: `uv run pytest tests/test_auth_dependencies.py tests/test_auth_probe.py tests/test_auth_token.py -v` - 21 passed.
- PASS: `uv run mypy models.py main.py auth.py` and `uv run ruff check .`.
- PASS: `uv run alembic upgrade head; uv run alembic downgrade 20260729_01; uv run alembic upgrade head`.
- PASS: Direct OAuth boundary check with an allowed `localhost` TestClient host: invalid state returns 400.
- FIXED: The recorded auth-test command now names explicit test paths and passes in PowerShell (21 passed).
- FIXED: `/auth/login` now returns the plan-required 302 redirect, covered by a focused regression test.

## Findings

### F1 — OAuth users cannot obtain token-route authorization

- **Severity**: WARNING
- **Impact**: HIGH - architectural stakes; think carefully before deciding
- **Dimension**: Architecture
- **Location**: main.py:112
- **Detail**: The OAuth callback returns only `user_id`, while `/auth/token` and `/auth/token/expire` require `sig = HMAC(SECRET_KEY, user_id)`. No public response or endpoint produces that signature, and an OAuth user must not know `SECRET_KEY`. The only caller shown in the implementation is the test suite, which imports private server helper `_sign_user_id` in `tests/test_auth_token.py`. Consequently, the intended public OAuth -> token flow cannot be completed by an authenticated user; this is a limitation of the plan's stateless handoff design, not a failed database or token implementation.
- **Fix A ⭐ Recommended**: Add a short-lived, scope-limited token-issuance grant to the OAuth callback response and validate its expiry at `/auth/token` instead of accepting a permanent HMAC over `user_id`.
  - Strength: Preserves the plan's no-session-middleware constraint while giving the user an actual post-login token-creation path.
  - Tradeoff: The grant is a bearer credential during its short lifetime; one-time use would require server-side state.
  - Confidence: HIGH - the existing HMAC utilities and callback provide the necessary local primitives.
  - Blind spot: The desired onboarding UI contract has not been reviewed.
- **Fix B**: Treat token generation as an operator-only API and remove it from the public OAuth completion flow until S-02 provides a real user-authentication mechanism.
  - Strength: Does not expose a new bearer grant design prematurely.
  - Tradeoff: F-03 no longer fulfills its stated login-to-token workflow.
  - Confidence: HIGH - the current endpoint is only callable by a party that already knows the server secret.
  - Blind spot: No evidence whether an external service was intended to call this endpoint.
- **Decision**: FIXED via Fix A on 2026-08-03. `/auth/callback` now returns a five-minute signed token grant, and `/auth/token` validates the grant before issuing a token. Focused token tests pass (7 passed, including expired-grant coverage).

### F2 — Login redirect does not meet the documented status contract

- **Severity**: WARNING
- **Impact**: LOW - quick decision; fix is obvious and narrowly scoped
- **Dimension**: Plan Adherence
- **Location**: main.py:148
- **Detail**: Phase 2 requires `GET /auth/login` to return 302. `RedirectResponse` is constructed without `status_code`, so FastAPI returns its default 307. A direct TestClient check with the allowed `localhost` host observed 307 and a correct GitHub Location header.
- **Fix**: Pass `status_code=302` to `RedirectResponse`, then add a regression assertion for the exact status code.
- **Decision**: FIXED on 2026-08-03. `/auth/login` now returns 302 explicitly, covered by `tests/test_auth_oauth.py` (1 passed).

### F3 — Token hashing has two independent implementations

- **Severity**: WARNING
- **Impact**: LOW - quick decision; fix is obvious and narrowly scoped
- **Dimension**: Pattern Consistency
- **Location**: main.py:257
- **Detail**: Phase 4 defines `auth.hash_token` as the shared hashing function for downstream reuse, and Phase 5 explicitly calls for importing it into `main.py`. Instead, `main.py` defines its own `_hash_token` with the same algorithm and salt. The implementations currently agree, but future changes can make generated and validated tokens incompatible.
- **Fix**: Import `hash_token` from `auth`, use it in token creation and expiration, and remove `main.py`'s `_hash_token` and redundant salt alias.
- **Decision**: FIXED on 2026-08-03. `main.py` now imports and uses `auth.hash_token`; focused token tests pass (7 passed).

### F4 — Auth-only pytest command is not portable to PowerShell

- **Severity**: OBSERVATION
- **Impact**: LOW - quick decision; fix is obvious and narrowly scoped
- **Dimension**: Success Criteria
- **Location**: context/changes/auth-scaffold-token-license/plan.md
- **Detail**: The recorded Phase 5 command `uv run pytest tests/test_auth_*.py -v` fails on Windows PowerShell because the shell does not expand the glob. The exact three auth test files pass when named explicitly (21 passed), so this is a verification-command issue, not a code failure.
- **Fix**: Replace the glob with explicit test paths or a pytest-compatible cross-platform selection expression.
- **Decision**: FIXED on 2026-08-03. The Phase 5 command now names the explicit auth test files and passes on PowerShell (21 passed).