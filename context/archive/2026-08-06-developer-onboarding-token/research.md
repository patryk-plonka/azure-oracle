---
date: 2026-08-07T13:20:57+02:00
researcher: GitHub Copilot
git_commit: f5516351da8bb975e942afa3331bee1ec7721472
branch: main
repository: patryk-plonka/azure-oracle
topic: "Resolve pre-identity OAuth state ownership in Phase 2"
tags: [research, codebase, oauth, onboarding, migrations, auth-grants]
status: complete
last_updated: 2026-08-07
last_updated_by: GitHub Copilot
---

# Research: Resolve pre-identity OAuth state ownership in Phase 2

**Date**: 2026-08-07T13:20:57+02:00  
**Researcher**: GitHub Copilot  
**Git Commit**: `f5516351da8bb975e942afa3331bee1ec7721472`  
**Branch**: `main`  
**Repository**: `patryk-plonka/azure-oracle`

## Research Question

The approved Phase 2 design requires `GET /auth/login` to persist one-time OAuth state before GitHub identifies a user. The completed Phase 1 schema makes `AuthGrant.user_id` non-nullable. How should the plan and persistence design change while retaining mandatory ownership for onboarding and token-issuance grants?

## Summary

The mismatch is real: `AuthGrant` cannot represent OAuth state at login because its `user_id` is a required foreign key, yet identity is resolved only later in the callback. Do not fabricate a placeholder `User` and do not modify the completed `20260806_01` migration.

**Recommendation: add a dedicated `OAuthState` table in a new forward Alembic revision, and restrict `AuthGrant` to the two post-identity purposes: `onboarding` and `token_issuance`.** This preserves the clear invariant that every `AuthGrant` belongs to a known user, avoids a purpose-dependent nullable foreign key, and gives the pre-identity CSRF handoff its own bounded lifecycle.

A smaller alternative is to make `AuthGrant.user_id` nullable only for `oauth_state`, protected by a database check constraint. That meets the immediate requirement but weakens the model and makes downgrade handling destructive whenever outstanding ownerless state exists.

## Detailed Findings

### The completed schema cannot persist pre-identity state

- [`AuthGrant`](https://github.com/patryk-plonka/azure-oracle/blob/f5516351da8bb975e942afa3331bee1ec7721472/models.py#L135-L152) declares `user_id` as `Mapped[UUID]` with a non-null foreign key. Its relationship also assumes a grant always has a `User` owner.
- The completed lifecycle migration creates the same non-null column in [`20260806_01_create_onboarding_lifecycle_state.py`](https://github.com/patryk-plonka/azure-oracle/blob/f5516351da8bb975e942afa3331bee1ec7721472/migrations/versions/20260806_01_create_onboarding_lifecycle_state.py#L44-L62).
- That table currently permits `oauth_state`, `onboarding`, and `token_issuance` under one purpose constraint, so its allowed values and ownership requirements conflict.

### Current and intended OAuth ordering prove the mismatch

- The live `GET /auth/login` creates only a stateless HMAC value; it has no database session and writes no row in [`main.py`](https://github.com/patryk-plonka/azure-oracle/blob/f5516351da8bb975e942afa3331bee1ec7721472/main.py#L169-L191).
- The callback verifies state, contacts GitHub, and only then creates or updates the local `User` in [`main.py`](https://github.com/patryk-plonka/azure-oracle/blob/f5516351da8bb975e942afa3331bee1ec7721472/main.py#L193-L252).
- The active plan correctly requires persisted, single-use state at login and a user upsert after GitHub identity verification, but its Phase 1 wording states that every auth grant has a user foreign key. The two statements cannot both hold.

### Separate `OAuthState` preserves the correct security boundary

The proposed table is intentionally minimal:

| Column | Role |
| --- | --- |
| `id` (UUID) | Primary key |
| `state_hash` / `credential_hash` | Unique, hash-only lookup value |
| `expires_at` | Indexed short-lived expiry |
| `consumed_at` | Replay prevention |
| `created_at` | Server-generated cleanup/audit timestamp |

It deliberately has no `user_id`, token, license, EULA, lifecycle-event, or raw-state field. `AuthGrant` remains user-owned and should only allow `onboarding` and `token_issuance`.

The corrected callback transaction is:

1. Login generates a random opaque state, stores only its hash in `oauth_states`, and sends the raw state to GitHub.
2. Callback finds an unexpired, unconsumed state by its hash.
3. Callback exchanges the code and fetches GitHub identity.
4. In the same database transaction, it upserts the user, creates an owned onboarding `AuthGrant`, and marks that `OAuthState` consumed.
5. It commits only after all state changes are valid, then returns the raw onboarding credential in the typed JSON body.

Invalid, expired, wrong, or replayed state must not create a user, EULA acceptance, license, lifecycle event, or onboarding grant. A failed GitHub exchange must leave the state usable until expiry because consumption occurs only with the downstream commit.

### Migration and test impact

- Phase 1 is marked complete and tied to `f551635` in the active plan. Create a new revision depending on `20260806_01`; never alter that historical migration.
- Upgrade should create `oauth_states` and indexes, then replace the `AuthGrant` purpose constraint so `oauth_state` is no longer a legal grant purpose.
- Downgrade should restore the prior `AuthGrant` purpose constraint before dropping `oauth_states`. This is isolated from users and owned grants; outstanding OAuth starts naturally become invalid after rollback.
- Add `oauth_states` to the child-first test truncate in [`tests/conftest.py`](https://github.com/patryk-plonka/azure-oracle/blob/f5516351da8bb975e942afa3331bee1ec7721472/tests/conftest.py#L49-L58), and add valid, expired, and consumed OAuth-state fixtures that require no user.
- Existing OAuth coverage only checks the redirect in [`tests/test_auth_oauth.py`](https://github.com/patryk-plonka/azure-oracle/blob/f5516351da8bb975e942afa3331bee1ec7721472/tests/test_auth_oauth.py#L1-L12). Expand it to assert hash-only persistence, expiry, one-time consumption, no entitlement effects, and creation of an owned onboarding grant after a mocked successful callback.
- Retain the existing owned onboarding-grant fixture in [`tests/conftest.py`](https://github.com/patryk-plonka/azure-oracle/blob/f5516351da8bb975e942afa3331bee1ec7721472/tests/conftest.py#L160-L172) for EULA and issuance behavior.

### Alternative: purpose-dependent nullable `AuthGrant.user_id`

The user-suggested alternative is valid but less cohesive:

```sql
CHECK (
  (purpose = 'oauth_state' AND user_id IS NULL)
  OR
  (purpose IN ('onboarding', 'token_issuance') AND user_id IS NOT NULL)
)
```

It would require a forward migration to make `auth_grants.user_id` nullable, add this check, and change ORM annotations to `UUID | None`. Its downgrade must delete outstanding ownerless OAuth-state rows before restoring `NOT NULL`, because that prior schema cannot represent them. This is acceptable only if minimizing schema objects is more important than keeping `AuthGrant` exclusively user-owned.

## Recommended Plan Updates

1. Add a Phase 2 prerequisite before OAuth route work: **Persist pre-identity OAuth state separately.** Name `models.py`, a new revision such as `*_create_oauth_states.py`, `tests/conftest.py`, and `tests/test_auth_oauth.py`.
2. Revise Phase 1/2 wording so `AuthGrant` represents only user-owned onboarding and issuance credentials; `OAuthState` is the distinct unowned pre-identity handoff.
3. Replace the callback implementation contract with the transaction sequence above, explicitly requiring state consumption and onboarding-grant creation to commit together after GitHub identity validation.
4. Add automated criteria for: opaque hash-only state at login, malformed/expired/replayed rejection, no entitlement mutation on callback failure, exact one-time consumption, and owned onboarding-grant creation after success.
5. Add migration verification for `20260806_01 -> new revision -> 20260806_01 -> head` and a fixture cleanup check covering `oauth_states`.
6. State Phase 3's dependency explicitly: an OAuth state can never be used as an onboarding or issuance credential, because it is stored outside `auth_grants`.

## Code References

- [`models.py:66-82`](https://github.com/patryk-plonka/azure-oracle/blob/f5516351da8bb975e942afa3331bee1ec7721472/models.py#L66-L82) — `User` owns every current `AuthGrant`.
- [`models.py:135-152`](https://github.com/patryk-plonka/azure-oracle/blob/f5516351da8bb975e942afa3331bee1ec7721472/models.py#L135-L152) — required `AuthGrant.user_id` and mixed purpose set.
- [`migrations/versions/20260806_01_create_onboarding_lifecycle_state.py:44-80`](https://github.com/patryk-plonka/azure-oracle/blob/f5516351da8bb975e942afa3331bee1ec7721472/migrations/versions/20260806_01_create_onboarding_lifecycle_state.py#L44-L80) — deployed auth-grant schema.
- [`main.py:169-275`](https://github.com/patryk-plonka/azure-oracle/blob/f5516351da8bb975e942afa3331bee1ec7721472/main.py#L169-L275) — legacy OAuth state/callback ordering to replace.
- [`tests/conftest.py:49-58`](https://github.com/patryk-plonka/azure-oracle/blob/f5516351da8bb975e942afa3331bee1ec7721472/tests/conftest.py#L49-L58) — child-first database cleanup.
- [`tests/test_auth_oauth.py:1-12`](https://github.com/patryk-plonka/azure-oracle/blob/f5516351da8bb975e942afa3331bee1ec7721472/tests/test_auth_oauth.py#L1-L12) — inadequate legacy OAuth test coverage.

## Architecture Insights

The system already uses hash-only persistence for bearer-like values through `hash_token`; reuse that primitive for OAuth state while keeping raw state exclusively in the GitHub redirect. The database—not a signed self-contained value—is the replay-prevention authority. Lifecycle rows remain reserved for consent, license assignment, and token creation; starting or consuming an OAuth state should not create an entitlement event.

The separate table makes the security boundary visible in the schema: a pre-authentication CSRF token is not an authorization grant. The callback is the boundary where a verified external identity turns into a local user-owned onboarding credential.

## Historical Context

- [`context/archive/2026-07-29-auth-scaffold-token-license/plan.md`](../archive/2026-07-29-auth-scaffold-token-license/plan.md) selected self-validating HMAC OAuth state with no database storage for the scaffold.
- [`context/archive/2026-07-29-auth-scaffold-token-license/reviews/impl-review.md`](../archive/2026-07-29-auth-scaffold-token-license/reviews/impl-review.md) identified that server-HMAC handoffs were not developer-completable.
- [`context/changes/developer-onboarding-token/plan.md`](plan.md) advances to database-backed one-time credentials but carries the ownership contradiction from Phase 1 into Phase 2.

## Related Research

No prior `research.md` artifact exists for this change.

## Open Questions

- Should OAuth state be bound to an additional non-secret browser context (for example, a SameSite callback cookie)? The current MVP plan does not require it; it would need a separate threat-model decision.
- Should expired OAuth-state records be periodically deleted? Existing plan guidance allows temporary credential retention; cleanup is not required on the request path.
