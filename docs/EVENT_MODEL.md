# Shipment Events and Current Outcome

## Tables
shipment_actions is a shared system catalog: id, action VARCHAR(64). Required labels are:
```text
created
picked up
possession
out for delivery
delivered
attempted
returned
```
No user catalog editing/deletion is required. shipment_events has id, action_id, shipment_id, event_time, created_at, plus implementation receipt metadata as needed. Preserve repeated actions at different times. Do not create a parallel tracking_events history or the legacy shipment_status summary table.

Shipments hold due_date, due_time, one final actual deliver_time and pod_name. Attempts retain separate event timestamps; they never populate delivery time.

## Creation event
Insert one Created event on the first successful manifest/API shipment creation. event_time is initial system processing UTC time, not source order date. Existing-reference upsert/retry emits no extra Created. The same initial processing timestamp anchors missing-deadline defaults.

## Dedupe
Canonical unique key: (shipment_id, action_id, normalized event_time). An existing key causes the entire duplicate event update to be ignored, even if signer/POD/notes/deadline/route differ. No new upload, image row, mutation or receipt tie refresh. Different times/actions are distinct accepted events.

Authenticate/resolve shipment before canonical mutation. Use database/concurrency enforcement; raw receipts may record ignored duplicates without business effects. Incomplete signer later supplied on that same exact tuple does not bypass dedupe.

## Ordering
Order accepted distinct events by greatest event_time, then last received for equal times. Receipt order is durable source acceptance order, not worker completion or created_at. An older event arriving later remains history without replacing a newer-time result.

## Delivery outcome
Choose the latest terminal event among delivered/returned using that order. Nonterminal pickup/attempt events do not undo an established delivery outcome.

- Selected Returned → Undelivered, including after a prior delivery.
- Selected Delivered with final delivery time and POD name → Delivered.
- No selected delivery or incomplete time/POD → Undelivered.
- A newer Delivered after Returned can restore Delivered once required fields are present.
- Shipments.deleted_at overrides all outcomes as Void.

Retain historical events and POD. Derive current outcome or use a rebuildable summary/pointer; do not erase delivery history to force a NULL predicate. Final delivery time comes from the selected delivery, not MAX across all actions.

## Independent ordering rules
Permitted ordinary-field/deadline corrections use last received valid authorized updates; lifecycle outcome remains event-time-first. Duplicate/unknown event updates have no ordinary-field side effects. Image retry continues already-accepted image work and must not replay a duplicate event.

## Verification
One Created, repeated attempts, exact concurrent duplicate suppression, changed auxiliary duplicate payload ignored, distinct equal-time tie, delayed older event, Delivered→Returned→Delivered, retained history, final delivery later than deadline, no address mutation and tenant/carrier/account isolation.
