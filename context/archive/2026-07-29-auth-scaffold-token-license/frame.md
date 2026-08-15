# Frame Brief: F-03 Auth Scaffold — Architectural Decisions

> Framing step before /10x-plan. This document captures what is *actually*
> at issue, separated from what was initially assumed.

## Reported Observation

The codebase has zero auth — no users, tokens, licenses, OAuth, or middleware
beyond `TrustedHostMiddleware`. The PRD mandates FR-001 through FR-006 as
must-have (GitHub OAuth, EULA, Demo license, token hashing, token expiration,
per-request validation). The roadmap scopes all six FRs into a single
foundation: F-03 `auth-scaffold-token-license`.

## Initial Framing (preserved)

- **User's stated cause or approach**: F-03 is one change — ship all auth
  must-haves together as "the smallest auth contract that lets a protected
  endpoint proceed."
- **User's proposed direction**: Plan F-03 as scoped in the roadmap, then
  implement.
- **Pre-dispatch narrowing**: Architecture — Depends() vs middleware is the
  leading concern.

## Dimension Map

The observation could originate at any of these dimensions:

1. **Auth boundary pattern** — `Depends()` (route-level, selective) vs
   middleware (blanket, with exclusions). The research recommends `Depends()`
   to keep `/health` and OAuth routes public. ← initial framing
2. **Token+license coupling** — Single combined `Depends()` vs two separate
   checks. The research recommends one combined check. But the PRD's "or"
   language and the 401/403 status code split favor separation.
3. **Session strategy** — Starlette `SessionMiddleware` (requires new dep:
   `itsdangerous`) vs HMAC-signed hidden form field (stdlib only) for the
   transient OAuth→EULA→token flow.
4. **Route organization** — Inline routes in `main.py` vs `APIRouter` module.
   The research recommends inline for a scaffold.
5. **EULA tracking** — Separate `eula_acceptances` table vs inline
   `eula_accepted_at` column on `users`. The research flags this as an open
   question.

## Hypothesis Investigation

| Hypothesis | Evidence | Verdict |
| --- | --- | --- |
| **Auth boundary: Depends()** | Both research docs recommend it (`auth-scaffold-token-license/research.md` §4, `testing-auth-license-gate/research.md` Architecture Insights). `BaseHTTPMiddleware` has known `TestClient` issues. `TrustedHostMiddleware` is a pure ASGI middleware for a different concern. | **STRONG** |
| **Auth boundary: middleware** | No evidence in codebase. Roadmap uses "middleware" loosely but research resolves to `Depends()`. | NONE |
| **Token+license: combined** | One Architecture Insight in `auth-scaffold-token-license/research.md` recommends it. | WEAK |
| **Token+license: separated** | PRD Access Control: "unauthenticated **or** unlicensed" (`prd.md:178`). Test-plan Risk #3 lists token and license as distinct scenarios; anti-pattern warns against coupling (`test-plan.md:74-80`). F-03 research's own test oracle assigns 401 vs 403 (`research.md` §5). Discriminating regression test becomes strictly easier with separation (assert `403` specifically). | **STRONG** |
| **Session: SessionMiddleware** | `itsdangerous` is NOT a transitive dependency of Starlette 1.3.1 (`uv.lock` — absent). Would require a new package, violating "zero new packages." PRD FR-004 Socrates note says OAuth sessions don't serve the agent path — architecture is token-based, not session-based. | NONE |
| **Session: HMAC signed form field** | Python stdlib `hmac` — zero new dependencies. Transient OAuth→EULA→token flow only needs to carry user identity across one redirect. `deploy-plan.md` has no session/JWT secret — HMAC reuses `SECRET_KEY` (already needed for other signing). | **STRONG** |
| **Routes: inline** | App is 18 lines; 5 routes make it ~80 — still readable. Research recommends inline for scaffold. | WEAK |
| **Routes: router module** | 5 routes share `/auth` prefix and a shared `Depends()` — textbook `APIRouter(dependencies=[...])` use case. S-01 adds a second route group (search). Safest path: inline for F-03, extract during S-01. | WEAK |
| **EULA: inline column** | PRD never mentions EULA versioning. FR-015 audit trail is parked. F-03 research already concluded inline is sufficient (`research.md:148-150`). | WEAK |
| **EULA: separate table** | Existing `Source`/`Limitation` pattern is for 1:N entities, not 1:1 state gates. No versioning evidence in PRD. YAGNI applies. | NONE |

## Narrowing Signals

Decisive observations from the investigation that narrowed the hypothesis space:

- **`itsdangerous` is NOT installed** — `uv.lock` confirms Starlette 1.3.1 dropped it as a hard dependency. `SessionMiddleware` would require a new package, contradicting the research's "zero new packages" claim. The HMAC alternative preserves the zero-new-packages goal.
- **PRD says "or"** — "unauthenticated **or** unlicensed" (`prd.md:178`) linguistically separates the two failure modes. Combined with the 401/403 status code split in the F-03 research's own test oracle, separation is better supported than combination.
- **`Depends()` is the consensus** — both research documents, the test plan's architecture insights, and the `BaseHTTPMiddleware`/`TestClient` technical limitation all point to `Depends()`. No counter-evidence exists.

## Cross-System Convention

FastAPI's documented best practice is `Depends()` for per-route authorization
gates and pure ASGI middleware for cross-cutting infrastructure concerns
(host validation, CORS, logging). The existing `TrustedHostMiddleware` follows
this convention — it's infrastructure, not auth. Adding auth as `Depends()`
keeps the convention clean: middleware = infrastructure, dependencies = auth.

For the transient OAuth→EULA→token flow, the convention in minimal FastAPI
apps is to avoid session infrastructure entirely — sign the user identity
into a hidden form field or a short-lived signed cookie using stdlib `hmac`
or `itsdangerous` directly (not `SessionMiddleware`). The PRD's own design
(FR-004 Socrates note) confirms this: OAuth is for human login; API tokens
are for agent access. There is no persistent browser session to maintain.

## Reframed (or Confirmed) Problem Statement

> **The actual problem to plan around is**: F-03 is the right scope (one
> change, all six FRs), but three architectural decisions in the research
> need correction before planning.

1. **Session strategy**: Replace `SessionMiddleware` (requires new dep:
   `itsdangerous`) with HMAC-signed hidden form field (stdlib `hmac`, zero
   new packages). The OAuth→EULA→token flow is transient — no persistent
   session needed.

2. **Token+license validation**: Separate into two chained `Depends()` —
   `get_current_user` (401 on bad/missing/expired token) and
   `require_active_license` (403 on inactive license). This matches the
   PRD's "or" language, the 401/403 status code split, and makes the
   discriminating regression test strictly easier.

3. **Route organization and EULA tracking**: The research's recommendations
   (inline routes, inline `eula_accepted_at` column) hold. No reframe needed
   on these dimensions.

The scope (one change, all six FRs) is confirmed. The architectural pattern
(`Depends()`) is confirmed. The "zero new packages" goal is preserved by
switching from `SessionMiddleware` to HMAC.

## Confidence

- **HIGH** — strong evidence from multiple sources (PRD, test-plan, uv.lock,
  both research docs) converges on the same three corrections. No
  contradictory evidence exists for any of the three reframes.

## What Changes for /10x-plan

The plan should still cover all six FRs in one change, but with three
architectural corrections:

1. **Session**: HMAC-signed form field, not `SessionMiddleware`. No new
   dependency. `SECRET_KEY` env var (already identified as missing from
   deploy-plan) serves double duty for HMAC signing.
2. **Validation**: Two chained `Depends()` (token → 401, license → 403),
   not one combined check. The discriminating regression test asserts
   `response.status_code == 403` after license deactivation.
3. **Everything else**: The research's other recommendations (inline routes,
   inline EULA column, `httpx` promotion, stdlib hashing) stand unchanged.

## References

- Source files: `main.py:1-18`, `models.py:1-57`, `database.py:1-40`,
  `tests/conftest.py:1-32`, `uv.lock` (itsdangerous absent)
- Research: `context/changes/auth-scaffold-token-license/research.md`
- Prior research: `context/changes/testing-auth-license-gate/research.md`
- PRD: `context/foundation/prd.md` §FR-001–FR-006, §Access Control
- Test plan: `context/foundation/test-plan.md` Risk #3, Phase 2
- Roadmap: `context/foundation/roadmap.md` F-03
- Deploy plan: `context/deployment/deploy-plan.md` §3 Secrets