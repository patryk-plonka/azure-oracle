<!-- PLAN-REVIEW-REPORT -->
# Plan Review: Observability Floor — Request/Error Logging Middleware with Secret-Stripping

- **Plan**: `context/changes/observability-logging-floor/plan.md`
- **Mode**: Deep
- **Date**: 2026-08-02
- **Verdict**: SOUND (after fixes)
- **Findings**: 0 critical  2 warnings  1 observation

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| End-State Alignment | PASS |
| Lean Execution | PASS |
| Architectural Fitness | WARNING |
| Blind Spots | WARNING |
| Plan Completeness | PASS |

## Grounding

10/10 paths ✓, 5/5 symbols ✓, brief↔plan ✓

## Findings

### F1 — Uvicorn error logger emits a second traceback on every 500

- **Severity**: ⚠️ WARNING
- **Impact**: 🔬 HIGH — architectural stakes; think carefully before deciding
- **Dimension**: Blind Spots
- **Location**: Phase 1 — "Critical Implementation Details" + Phase 1 §2
- **Detail**: The plan claims the custom `@app.exception_handler(Exception)` "prevents Starlette's ServerErrorMiddleware from logging the full traceback with frame locals" so "the middleware's scrubbed traceback is the sole error log." Verified against installed Starlette 1.3.1 (`errors.py:185`): ServerErrorMiddleware ALWAYS re-raises after running the custom handler. The re-raised exception propagates to uvicorn's `run_asgi` (`h11_impl.py:421`), which calls `self.logger.error(msg, exc_info=exc)` — emitting a SECOND traceback via the `"uvicorn.error"` logger. The "sole error log" Desired End State is not achieved. Mitigating factor: uvicorn's `logging.Formatter` uses standard `format_exception` WITHOUT `capture_locals=True` — frame locals do NOT leak, so the secret-stripping guardrail is not violated, but the plan's rationale misattributes the source.
- **Fix A ⭐ Recommended**: Add a logging filter on "uvicorn.error" that drops records containing tracebacks (or override uvicorn's log_config to suppress exc_info formatting on the error logger).
  - Strength: Achieves the "sole error log" goal; the middleware's scrubbed traceback is the only one emitted.
  - Tradeoff: Adds a logging config step (a `logging.Filter` subclass or a custom `LOGGING_CONFIG` dict); slightly more code.
  - Confidence: HIGH — stdlib `logging.Filter` is well-documented and testable via `caplog`.
  - Blind spot: Must verify the filter doesn't suppress non-traceback error logs (startup errors, etc.) — filter on `record.exc_info is not None` or on the message prefix "Exception in ASGI application".
- **Fix B**: Accept the double log; update the plan's rationale to reflect reality (uvicorn logs a locals-free traceback; the middleware logs the scrubbed one; both are secret-safe).
  - Strength: Zero extra code; uvicorn's traceback has no frame locals so no secret leaks.
  - Tradeoff: Two error logs per 500; the "sole error log" Desired End State is not met; the plan's rationale remains inaccurate.
  - Confidence: HIGH — verified uvicorn does not capture_locals.
  - Blind spot: Future contributors may not realize uvicorn's traceback is safe and may "fix" it by adding capture_locals.
- **Decision**: FIXED via Fix A — added `SuppressUvicornTracebackFilter` to Phase 1 §1 + `main.py` wiring + Progress step 1.4 + Phase 2 test `test_500_no_uvicorn_traceback`; updated Desired End State, Implementation Approach, and Critical Implementation Details to reflect the re-raise + filter mechanism.

### F2 — "Critical Implementation Details" hedge is unnecessary and partly wrong

- **Severity**: ⚠️ WARNING
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Architectural Fitness
- **Location**: "Critical Implementation Details" (3rd bullet)
- **Detail**: The plan's 3rd "Critical Implementation Details" bullet hedges: "For generic Exception, the handler returns a 500 response and call_next does not re-raise. The middleware should detect 500 responses (status code)..." Verified against installed Starlette 1.3.1: the custom `Exception` handler is registered in `ServerErrorMiddleware` (outermost), NOT `ExceptionMiddleware` (innermost) — `applications.py:113-117`. `ExceptionMiddleware` re-raises generic `Exception`s — `_exception_handler.py:60`. So the exception propagates to `BaseHTTPMiddleware`'s inner `coro`, which captures it in `app_exc` (`base.py:115`); no response started, so `call_next` hits `EndOfStream` and RE-RAISES `app_exc` (`base.py:138-139`). The middleware's `try/except` around `await call_next(request)` DOES catch it. The "detect 500 status code" fallback is based on a misreading of where the custom handler runs and is not needed.
- **Fix**: Remove the "detect 500 status code" fallback from the 3rd bullet. Keep the accurate part: "The implementer must verify this interaction with a test that triggers a real 500 and asserts the scrubbed traceback appears in caplog." Replace the incorrect mechanism description with: "The custom Exception handler runs in ServerErrorMiddleware (outermost, outside BaseHTTPMiddleware), so the exception propagates to the middleware's try/except via call_next's EndOfStream re-raise path (base.py:138-139). The except block fires; log the scrubbed traceback and re-raise."
  - Strength: Removes a misleading fallback; the implementer follows the correct primary path without confusion.
  - Tradeoff: None significant — the fallback was never needed for this scenario.
  - Confidence: HIGH — verified against installed Starlette 1.3.1 source.
  - Blind spot: None significant.
- **Decision**: FIXED — removed the "detect 500 status code" fallback; replaced with the accurate mechanism (handler runs in ServerErrorMiddleware outermost, exception reaches middleware via call_next's EndOfStream re-raise at base.py:138-139, the except block fires).

### F3 — _scrub_traceback should clarify: format via utility, not exc_info=

- **Severity**: 💡 OBSERVATION
- **Impact**: 🔎 MEDIUM — real tradeoff; pause to reason through it
- **Dimension**: Lean Execution
- **Location**: Phase 1 §1 — _scrub_traceback utility
- **Detail**: The middleware logs via `error_logger.error("Unhandled exception: %s\n%s", type(exc).__name__, _scrub_traceback(exc))` — it formats the traceback itself (not via `exc_info=`), so `_scrub_traceback` controls the output entirely. The plan could clarify that the middleware must NOT pass `exc_info=exc` to `logger.error` (which would trigger the formatter's default traceback — redundant with the scrubbed string and potentially double-formatting).
- **Fix**: Add a one-line note to Phase 1 §1 Contract: "The middleware must format the traceback via _scrub_traceback(exc) and pass it as a string argument to logger.error — do NOT pass exc_info=exc, which would trigger the formatter's default traceback (redundant with the scrubbed string)."
  - Strength: Prevents double-formatting; keeps the scrubbed string as the sole traceback in the middleware's log record.
  - Tradeoff: None.
  - Confidence: HIGH.
  - Blind spot: None.
- **Decision**: FIXED — the note was already added during the F1 fix (Phase 1 §1 `_scrub_traceback` contract: "The middleware must format the traceback via _scrub_traceback(exc) and pass it as a string argument to logger.error — do NOT pass exc_info=exc"). No further edit needed.
