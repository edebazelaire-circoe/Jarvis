# Task09 independent contract review

Scope: independent tests in `tests/unit/test_front_brain_hint_review.py`.
Production types, codec, consumer and fake remain owned by the implementation
agent. No provider call, runtime integration, Core mutation or task dispatch is
part of this review.

The stabilized API is `domain/front_brain_hints.py`,
`ports/front_brain.py::FrontBrainAnalyzer` and
`runtime/front_brain_hints.py::FrontBrainHintConsumer`. Independent probes cover:

| Boundary | Required observation |
|---|---|
| Strict model JSON | Duplicate keys, nonfinite numbers including exponent overflow, unknown/missing fields and wrong nested shapes are rejected. |
| App-owned binding | A model value cannot assign request identity, admission scope, deadline or source. |
| Consumption deadline | A hint received before expiry is still rejected if consumed at/after the original deadline; duplicate receipt cannot renew it. |
| Input identity | A newer revision or commit with unchanged text invalidates a provisional hint. |
| Incarnation/admission | Session or configuration changes and admission revocation reject previous hints. |
| Source distinction | Provisional B can use context from A while B's Core origin remains unknown; no invented turn/epoch. |
| Advisory authority | WAIT cannot prevent an ordinary direct answer; PREAMBLE cannot attest work; DELEGATE exposes no executor or tool call. |
| Unrelated state | A general context watermark change alone does not redefine the selected input's origin or commit it. |

## F1 — oversized integer confidence escapes validation

Status: corrected by implementation owner and independently rechecked.

`FrontBrainHintValue.__post_init__` initially evaluated `math.isfinite(value)`
before checking `[0,1]`. A valid JSON integer with 512 decimal digits fits the
8,192-byte body bound and is parsed as Python `int`, but `math.isfinite` raises
`OverflowError` while converting it to float. This bypasses the codec's normal
`ValueError` rejection boundary. The issue affects both confidence fields;
checking their range before float conversion (or checking finitude only for
floats) avoids that exception without accepting the value.

Permanent reproduction:
`test_front_brain_hint_review.py::test_huge_finite_json_integer_is_a_validation_rejection_not_overflow`.
The owner now checks the numeric range before finitude conversion. Both
`confidence` and `addressed_confidence` reject the oversized integer with
`ValueError`. No production correction was made by the reviewer.

## Initial independent gate

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_front_brain_hint_review.py -q -W error -o asyncio_default_fixture_loop_scope=function --tb=short
```

Before F1 was added: **57 passed in 0.27 s**. F1's separate reproduction failed
with `OverflowError` in 0.32 s. Extending it to both confidence fields produced
**2 failed, 57 passed in 0.34 s**. After the owner's fix, the same independent
file reports **59 passed in 0.21 s**, warnings as errors. Targeted diff check
is clean. The passing cases include duplicate/nested JSON,
NaN/infinity/exponent overflow, exact shape, app-only binding, deadline at actual
consumption, duplicate re-registration without TTL renewal, same-text commit,
session/config/admission changes, exact dependency generation, failure states,
and advisory-only WAIT/PREAMBLE/DELEGATE. The request keeps provisional B's
origin unknown while retaining A as context. Tests use only process-local
immutable values and the synchronous consumer; no provider or execution path
is invoked. No unresolved finding remains in this bounded review. Parent owns
the broader regression gate and final slice acceptance.
