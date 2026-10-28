# Writing Requirements

## Document responsibilities
| Document | Describe |
|---|---|
| Product requirements | Users, business problem, included/deferred capabilities and success |
| Feature specification | User flow, states, permission, inputs, results and acceptance criteria |
| Domain contract | Shared rules such as identity, status, money/time, defaults and duplicates |
| API contract | Method/path, request/response, validation, authorization and errors |
| Data model | Persisted entities, fields, relationships and invariants |
| Architecture | Component responsibilities and communication |
| Decision log | Alternatives, selected option and reasoning; retain history here |

Write the current requirement once in its authoritative section. Update that section when a decision changes; put the explanation/history in the decision log instead of adding another clarification section to every document.

## Feature template
```markdown
# Feature name

## Purpose and scope
What user need is served? What is explicitly outside this release?

## Actors and permissions
Who may read or change the data, and within which tenant boundary?

## User flow
Describe the trigger, inputs, successful result and visible states.

## Data and API
List fields, source-to-target mappings, route/method, and example bodies.
Label implementation proposals separately from approved business behavior.

## Business rules
Define matching, defaults, nulls, dates/timezones, uniqueness and ordering.
For metrics, specify population, numerator, denominator, exclusions and rounding.

## Errors and retries
State which work remains saved, which work is rejected, and what duplicates do.

## Acceptance criteria
Give observable happy-path, failure, permission and retry cases.
```

## Example rule
A company administrator may soft-delete an area. Set its deleted_at and retain shipment references. Exclude the area from active options/cards; keep its shipments in general tenant/date results. A carrier update matching that name reuses the same ID without restoring it.

This example answers actor, action, persistence, visibility and retry-related behavior. It does not require the writer to choose SQL syntax or index names.

## Style checklist
Use concrete field names and examples. Separate absence from invalid input. Explain whether a repeated request changes anything. Keep implementation detail only where it affects the contract. Do not embed real passwords, keys or customer data. Mark a genuinely unanswered business case explicitly; do not leave completed decisions as open questions.
