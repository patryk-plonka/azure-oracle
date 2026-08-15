# azure-oracle
A small, mostly-serverless service that continuously discovers, normalizes, and serves a structured database of Azure service limitations — unsupported scenarios, known issues, quotas, preview/gated behavior, deprecations, and workarounds.

## Database Operations

Use `DATABASE_URL` only for a local operator environment or the Railway service.
It is never required for the PostgreSQL test suite.

```powershell
$env:DATABASE_URL = "postgresql://..."
uv run alembic upgrade head
uv run python seed.py concept/azure_limitations_db.csv
```

The seed command reports only source and limitation counts. It is repeatable and
does not run during application startup or deployment.

## Tests

Set `TEST_DATABASE_URL` to a disposable PostgreSQL database distinct from the
operator or Railway database. The test fixture runs migrations and truncates only
that test database between import cases.

```powershell
$env:TEST_DATABASE_URL = "postgresql://..."
uv run pytest tests/test_seed_import.py -v
uv run pytest tests/ -v
uv run ruff check .
uv run mypy .
```

Railway receives only `DATABASE_URL`; do not configure `TEST_DATABASE_URL` as a
Railway production variable.

## Developer Onboarding

The onboarding flow is JSON-first. Start the service with a PostgreSQL
`DATABASE_URL` and these environment variables:

```powershell
$env:APP_URL = "http://localhost:8000"
$env:GITHUB_OAUTH_CLIENT_ID = "your-github-oauth-client-id"
$env:GITHUB_OAUTH_CLIENT_SECRET = "your-github-oauth-client-secret"
$env:TOKEN_HASH_SALT = "a-long-random-secret"
uv run alembic upgrade head
uv run uvicorn main:app --reload
```

Configure the GitHub OAuth application's callback URL as
`<APP_URL>/auth/callback`. Never commit, print, or reuse the OAuth client
secret, token hash salt, API tokens, OAuth state, onboarding credentials, or
issuance credentials. Do not put them in shell history, logs, or source
control.

1. Open `GET /auth/login` in a browser and approve the GitHub OAuth request.
2. The typed JSON callback response provides an onboarding credential and the
	next action, `accept_eula`.
3. Send that value as `Authorization: Bearer <onboarding credential>` to
	`GET /auth/eula`, then submit its returned version to
	`POST /auth/eula/accept` with the same header. Acceptance assigns the Demo
	license and returns a single-use issuance credential.
4. Send that issuance credential as a Bearer value to `POST /auth/tokens` with
	a non-empty token name. The successful response is the only time the raw
	API token is shown. Store it in a password manager or other approved secret
	store immediately; it cannot be recovered later.
5. Use the API token as `Authorization: Bearer <api token>` with
	`GET /limitations/search?q=<query>`.
6. To expire a token, retain a different active token for the same user and
	call `POST /auth/tokens/<token id>/expire` with that actor token's Bearer
	header. A token owned by another user is reported as not found.

OpenAPI at `/docs` is the source of truth for typed request and response
payloads. OAuth state, onboarding credentials, and issuance credentials are
short-lived and single-use; repeat the prior step when one has expired or was
consumed.

## Verification

Use a disposable PostgreSQL database for `TEST_DATABASE_URL`, distinct from
`DATABASE_URL` and never configured on a production Railway service.

```powershell
$env:TEST_DATABASE_URL = "postgresql://..."
uv run pytest tests/ -v
uv run ruff check .
uv run mypy .
```
