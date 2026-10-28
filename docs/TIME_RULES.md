# Timestamp Normalization

## Input interpretation
Define field formats in each registered adapter. Explicit offsets identify an instant and must not be reinterpreted as local time. For recipient-local naive carrier input, resolve:
```text
shipments.recipient_id
  → customers.id
  → customers.validated_id
  → customers_validated.id
  → customers_validated.timezone
```

Add timezone VARCHAR to the target validated-address model if absent. The address-validation worker supplies coordinates/timezone without modifying the original shipment address. **Recommendation:** IANA zone names such as America/Los_Angeles.

If timezone/validation linkage is absent, treat the supplied parseable datetime as UTC and save the matched event normally. Missing timezone never causes a valid matched event to be discarded. Invalid nonempty timezone identifiers, ambiguous/nonexistent local times and malformed datetimes are validation errors to report/reject rather than guess. Unknown shipment produces an ingestion error, not an event.

Normalize accepted instants to UTC before persistence, event ordering, dedupe and OTP comparison. Derive due_date after normalization. Canonical event field is event_time.

## Response representation
Return recipient-local datetime with the actual offset for that instant, e.g. 2026-10-20T17:05:10-07:00. When no zone is known, return UTC with +00:00. Display conversion never changes UTC reporting dates.

| Naive input | Recipient zone | UTC instant | API representation |
|---|---|---|---|
| 2026-10-20T17:05:10 | America/Los_Angeles | 2026-10-21T00:05:10+00:00 | 2026-10-20T17:05:10-07:00 |
| 2026-10-20T17:05:10 | missing | 2026-10-20T17:05:10+00:00 | 2026-10-20T17:05:10+00:00 |

The sample zone is illustrative, not a global OnTrac setting. Historical epoch-second examples do not impose compatibility on the new API.

## Stable retries
Retain raw source/normalization metadata for audit and deterministic replay. Once accepted, a retry must not become a different event because address validation later supplied a zone. Retroactive reinterpretation is not part of MVP.

## Verification
Known/missing zone, explicit offsets, UTC date rollover, summer/winter offsets, invalid/ambiguous local times, tenant-safe lookup, stable retry normalization and API offsets. No timezone-related change to approved event ordering or missing-shipment handling.
