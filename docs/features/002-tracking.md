# Tracking

## Purpose and layout
Display the verified shipper's packages across carriers with filters, full-result metrics, table and pagination. Use [tracking-page.png](../reference/tracking-page.png) for overall layout and [date-range.png](../reference/date-range.png) for the date picker. Sidebar items visible in a reference are not automatically MVP features.

## Filters
| Filter | Contract |
|---|---|
| Date | Default date_type=due_date; both absent→today UTC; otherwise both inclusive bounds required |
| Account | Exact account_id string match via account |
| Status | One Delivered or Undelivered, via status=delivered/undelivered |
| Areas | Multiple active company IDs, area=1&area=2, OR within selection |
| Exceptions | One Attempted, Void or Returned; existing approved exception predicates |

Combine filter groups with AND and reset page to 1 after a committed change. Omitted filters add no restriction. NULL/deleted-area shipments remain when no area filter is selected; selected areas exclude NULL and deleted explicit IDs are rejected. Do not force My Day due-today on an explicit list range. See [DATE_FILTERS.md](../DATE_FILTERS.md).

Delivered dot is green; Undelivered dot is orange. Void belongs to Exceptions, not the Status chooser, while detail/header/metric Void rules remain intact. Keep visible status text so color is not the only signal.

## Table and preferences
Reference columns include Shipment, Reference, Driver, Route, Company, City, Zip, POD Name and POD Time; supported extra columns are implementation DTO configuration. Preserve string identifiers/ZIP, render optional values cleanly and display available delivery time even when POD name is missing.

Frontend owns selected columns and sort UI state; server defines/validates supported fields and applies actual requested sort. Do not persist the old isClicked/isSelected schema flags as server preferences. Use typed pagination values rather than historical string per_page. Page starts at 1 with default length 10; size limits, stable sorting and out-of-range handling are implementation contracts.

## Metrics
Show Total, Undelivered and OTP for the full filtered result, not the current page. Formula, non-Void special cases and two-decimal rounding are in STATUS_RULES.md. Account/area/status/exception filters must affect list and metrics consistently without multiplying rows through joins.

## Search, detail and export
Shipment links open the authorized detail; selected-row identity must prevent duplicate numbers from opening an arbitrary package. Typed identifier Search and multiple-match selection are in [003-search.md](003-search.md).

Export submits all filters with export=1 and no pagination. Queue generation, return the exact acceptance message and show Click here to download after SSE readiness. See [006-shipment-export.md](006-shipment-export.md).

## Acceptance criteria
Tenant-safe list/counts/detail; inclusive date/preset behavior; exact account and single status/exception; repeated area OR; optional route visibility; all-filter metric consistency; deterministic pagination/sort; preserved leading zeros; accessible popovers and meaningful loading/error/empty states.
