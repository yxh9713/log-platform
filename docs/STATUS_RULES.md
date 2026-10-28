# Status, Exceptions and OTP

## Current shipment classification
Apply once per shipment, never once per event row:
1. deleted_at not NULL → **Void**.
2. Otherwise selected terminal Returned → **Undelivered**.
3. Otherwise final deliver_time and pod_name both present → **Delivered**.
4. Otherwise → **Undelivered**.

A nonempty POD name is required; missing/empty signer never counts as completed POD. Accept and display received delivery time even when the missing name leaves a package Undelivered. Image upload readiness is not a delivery-classification requirement.

Status chooser offers Delivered/Undelivered only, with green/orange dots. Exceptions chooser offers Attempted/Void/Returned. Shipment detail still shows Void for deleted_at. Do not relabel Void merely to fit the two-option Status chooser.

## Reporting populations
My Day global/area statistics use verified shipper_company_id and due_date=today UTC. Use database time consistently within a response. The frontend display timezone does not change the report day.

Tracking metrics cover all matching packages in the selected date/filter window, not only a page or an extra due-today window. Count each package once after reducing event history. Direct identifier Search opens detail and has no separate aggregate page.

## Counts and area visibility
Total=delivered+undelivered+void. Void remains visible and countable. NULL/deleted-area shipments remain in general company/date results and global totals. Active area cards/options/statistics exclude deleted/unassigned areas, so card sums may be lower than global total. A selected area filter never matches NULL route.

Area deletion is a visibility preference, not shipment deletion; only shipment.deleted_at produces Void.

## OTP
First exclude all Void shipments from the OTP-eligible population.

| Quantity | Definition |
|---|---|
| Eligible total | Non-Void packages in the applicable reporting population |
| Denominator | Currently Delivered packages in that population |
| Numerator | Those Delivered packages whose final deliver_time is strictly before due_time |

Apply special cases in order: eligible total=0 → OTP0; eligible total>0 and denominator=0 → OTP100; otherwise OTP=100×numerator/denominator. Return percentages rounded to two decimals, e.g. 96.67; JSON need not retain trailing zeroes.

Equality to the deadline is late. Use actual final delivery, not an earlier attempt. My Day requires due_date=today, not deliver_time today. An all-Void population can have displayed total>0 and OTP0.

## Exception selection
Count Void once as void, regardless of retained history; do not also count it as attempted/returned. Exclude other currently Delivered packages. For each remaining package, select one latest event across all actions/history, using event_time then receipt tie order. Do not filter events to today or exception actions before selecting.

Latest attempted contributes one attempted; latest returned contributes one returned. Repeated/older occurrences do not accumulate. Latest non-exception/no event contributes neither. Attempted→out for delivery contributes zero attempted; delivered→returned contributes returned if that return is latest; attempts→delivered contributes no exception.

Keep consolidated, no_package and held response categories with value **0** in MVP. Do not create or infer catalog actions for them. Future activation requires explicit source mapping.

## Removed field
The new API/UI has no currentHour or replacement last-updated indicator. Preserve historical reference files without treating their old fields as current requirements.

## Verification
Test every status combination, missing POD, retained delivery after return, latest non-exception suppression, one-package counts, zero placeholders, Void priority, final-time strictness, non-Void zero cases, filtered OTP and route-independent global totals.
