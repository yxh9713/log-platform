# Date-Range Filtering

## Query semantics
Default date_type=due_date. Omitted start_date and end_date means today through today in UTC. If either is supplied, require both. Both explicit endpoint dates are inclusive; reject malformed/reversed ranges and one-sided input.

Use the same normalized range for list rows, counts, filtered OTP and exports. For timestamp predicates, an engineering implementation may use >= start midnight and < midnight after end date so fractional seconds are included correctly. Direct identifier Search/detail has no hidden list-date restriction.

## Date picker
Use [date-range.png](reference/date-range.png) as the visual reference: calendar trigger and formatted range, two adjacent month calendars with arrows and Sunday-first headers, range highlighting, preset panel, Cancel and Apply.

Presets are Today, Yesterday, Last 7 Days, Last 30 Days, This Month, Last Month. **Engineering interpretation:** UTC calendar dates; last seven includes today plus six prior days, last thirty includes today plus twenty-nine prior days, This Month is month-to-date, Last Month is the full prior calendar month. Display MMM dd, yyyy; send API YYYY-MM-DD dates.

Stage edits until Apply, discard on Cancel, require a complete valid range before applying and reset list pagination when committed filters change. The screenshot's October range is illustrative; initial default remains today.

## Verification
Test both omitted, one omitted, same day, inclusive endpoints, reversed/invalid dates, UTC midnight/fractional boundary, month/year/leap transitions, presets, Cancel/Apply and reuse of the effective query for export/metrics.
