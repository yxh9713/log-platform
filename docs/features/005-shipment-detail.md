# Shipment Detail

## Scope and reference
Use [shipment-detail-page.png](../reference/shipment-detail-page.png) for the two-column layout: current status/shipment attributes/history, sender/recipient addresses and POD. Map and favorite/star are deferred; do not implement their visible screenshot behavior in MVP.

Frontend route is /tracking/detail/{identifier}. Search may supply shipment number or reference; carry typed/selected-row identity and recheck tenant authorization. Backend detail DTO/path is implementation interface design, not the frontend URL itself.

## Content
Show current status, shipment identifiers, carrier/vendor, service description, expected delivery, weight without inferred unit, original pickup/delivery addresses, repeated event history and one latest relevant POD image. Optional/null values render cleanly. Map supplied labels to approved model fields in the final DTO; screenshot content is not live seed data.

## Status and incomplete delivery
If shipments.deleted_at is set, top Current Status is Void regardless of retained delivery/POD. Otherwise use the approved current terminal/time/POD rules. Preserve history and available deliver_time even when missing POD name keeps a package Undelivered, so the shipper can investigate with the carrier.

Returning never erases historical delivery/POD; image upload failure does not erase valid time/signer. No address/deadline editing or outbound carrier messaging is added by this page.

## Time and images
Display recipient-local datetime with actual offset; missing zone uses UTC. History ordering must follow event_time/receipt ties rather than worker insertion time. The detail receives one latest relevant POD URL; pending/failed image has no false ready link. Retain old image records internally without adding a history carousel/endpoint.

## Acceptance criteria
Tenant-safe direct/selected-row navigation; Void header precedence; complete/incomplete delivery and return behavior; repeated history without duplicates; available time displayed; accurate offsets; latest-image selection despite late upload completion; optional fields/image failures; keyboard/responsive layout; no map/star.
