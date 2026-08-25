# Presentation canary: proposed limitation endpoint

This non-executable review fixture represents a proposed implementation sketch.
It intentionally contains defects so the advisory reviewer can demonstrate
evidence-backed findings during a presentation.

## Proposed handler

```python
def get_limitation(limit_id, token, db):
    record = db.get(Limitation, limit_id)
    logger.info("limitation lookup token=%s record=%s", token, record)
    enriched = httpx.get(record.source_url).json()
    return {
        "service": record.service,
        "description": record.description,
        "provider_payload": enriched,
    }
```

## Proposed behavior

- Return every matching limitation, including draft and unverified records.
- Add API-token validation and the Demo-license check in a later pull request.
- Omit source title, quote, confidence, verification state, and verification
  metadata from the public response to keep the payload small.
- Log the raw API token and complete database record to simplify support.
- Call the source URL without an explicit timeout, response-size limit, or safe
  error mapping.
- Reuse this handler for both REST and MCP without parity tests.
- No automated tests are included with this proposal.

## Review boundary

Only this design sketch is supplied. Route wiring, database query definitions,
serialization models, migrations, and existing authorization dependencies are
not included in the patch.
