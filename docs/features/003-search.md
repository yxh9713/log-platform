# Identifier Search

## Form
Provide a select input with shipment_number and reference, defaulting to reference; a text input; and Search button. Match only the selected field exactly. reference maps to shipments.shipper_ref. Trim surrounding input whitespace and preserve case/leading zeros.

Search is tenant-scoped identifier lookup across the shipper's history. Do not apply hidden today/account/area list restrictions or add fuzzy/name/address search to MVP. Void/deleted-area packages remain accessible under normal detail authorization.

## Results
| Matches | Behavior |
|---|---|
| None | Display The {identifier} does not exist with entered text safely interpolated |
| One distinct package | Redirect to /tracking/detail/{identifier} with typed/stable context |
| Multiple | Stay on page and show the selection table beneath the form |

The table columns are exactly:
```text
shipment_number,reference,route,address_one,city,state,zip
```

Reference displays shipper_ref; address fields come from recipient_id→customers; route displays its label when available, including a matched deleted-area label. NULL optional values render empty. Do not add a carrier column by default.

## Selected-row navigation
Shipment number is clickable. Because numbers can repeat, carry the chosen package's stable identity and lookup type through navigation and recheck tenant scope in backend retrieval. The frontend route remains /tracking/detail/{identifier}; exact query/state keys are engineering wiring. Never take the first number match or merge packages with different references.

A direct ambiguous detail URL without selected-row context uses the same selection flow. The selector separates number/reference namespaces; do not search both with an undocumented priority. One package matching both fields is not multiple packages.

## Acceptance criteria
Reference default, explicit number lookup, exact chosen-field behavior, no-match text, singleton redirect, seven-column multi-match table below form, correct clicked package under duplicate numbers, old package lookup independent of today, URL escaping/safe rendering, tenant isolation and keyboard access.
