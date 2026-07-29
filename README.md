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
