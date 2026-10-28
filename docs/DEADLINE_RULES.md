# Shipment Deadlines

## Persistence and sources
Persist due_time and derive due_date from its normalized UTC calendar date. Creation/defaulting makes both available on new shipments; missing external input is not itself an error.

| Source | Deadline field | Required surrounding flow |
|---|---|---|
| Paychex manifest | Due Date/Time | Normal package creation/upsert |
| Create API | Optional due_time | Valid creation request |
| Carrier CSV | Optional due_time | Known event and timestamp plus assigned identity |
| Carrier webhook | Optional due_time | Known event and time plus assigned identity |

Event timestamp/time/order is never a deadline. Normalize using [TIME_RULES.md](TIME_RULES.md).

## Initial default
Use the system's first creation/import processing date in UTC. If both deadline values are absent, choose the next calendar day at 17:00 UTC; if Saturday/Sunday, advance to Monday. This is not processing time plus 24 hours. Only the generated missing-both default skips weekends; do not alter a valid supplied weekend deadline or add a holiday calendar.

| Processing time UTC | Generated deadline UTC |
|---|---|
| Wednesday 2026-10-21 23:59:59 | Thursday 2026-10-22 17:00:00 |
| Thursday 2026-10-22 12:00:00 | Friday 2026-10-23 17:00:00 |
| Friday 2026-10-23 12:00:00 | Monday 2026-10-26 17:00:00 |
| Saturday or Sunday that weekend | Monday 2026-10-26 17:00:00 |

Canonical date-only input normalizes to that date at 17:00 UTC; time-only derives its UTC date. Current carrier/API input contracts expose due_time rather than an independent carrier due_date. Retry/upsert never creates a new default or moves the original processing base.

## Corrections
An authorized carrier event-bearing webhook/CSV or shipper manifest update may replace an existing deadline. Omitted/empty/null preserves it. Update time/date together and refresh affected reporting results.

Last received valid authorized correction wins, regardless of source event time or shipper/carrier priority. Persist receipt order and guard updates against reversed worker completion. File identity/row order and receipt metadata are implementation design; retries are not new correction receipts.

No deadline-only carrier messages, separate deadline endpoint or dashboard/API deadline-edit feature are required. Missing event/time with only identity/deadline is rejected without mutation. Unknown events are ignored, unmatched references are recorded as PostgreSQL errors, and exact duplicate event tuples never change deadlines even when due_time differs.

## Invalid inputs
A nonempty malformed/impossible supplied deadline rejects the whole API request/CSV row. Do not turn invalid input into a default or partially apply the remaining event/POD/area fields. Record diagnostics separately and continue valid CSV rows; partial files go to failed with completed_with_errors.

DST ambiguity, invalid zones and missing-zone fallback follow TIME_RULES.md. Initial defaults do not authorize legacy backfill; start with new data.

## Verification
Test late-night base dates, midnight/weekends/month/year boundaries, missing versus malformed input, every source field, date/time consistency, no reset on replay, invalid-row atomicity, last-received ordering, duplicate/unknown-event suppression and prohibited deadline-only updates.
