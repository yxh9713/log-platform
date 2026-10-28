# POD Image Processing and Storage

## Input and validation
Webhook pod and carrier CSV pod_image contain base64 image data. sign maps to POD name, not authentication. Authenticate/match the assigned shipment before image effects. Unknown/duplicate events and unmatched shipments create no new image work.

Validate decoded content as JPEG/PNG, not merely base64 syntax or declared extension. Maximum decoded input is 5 MB per image (engineering byte interpretation: 5,000,000). Reject invalid image content/oversize input; resizing is not a substitute for input validation. Bound decoder memory/pixels and request sizes.

Resize to 900 pixels wide, preserving aspect ratio. **Engineering choice:** cap at 900 without enlarging smaller input. Validate prepared encoded output and record actual size/dimensions; resizing does not promise a specific output size. Missing/empty/null update images preserve prior state.

## Metadata and current image
Persist returned URLs in shipment_images.url; never put raw base64 there. Keep image history associated with distinct accepted events. Do not reproduce a legacy uniqueness rule that prevents multi-event history.

Shipment APIs return one latest relevant POD, not an image array. Align selection with accepted delivery/event order and receipt ties; older upload completion must not replace the current delivery image. Keep historical images internally. Pending/failed selected image has no usable URL; do not invent success or show another event's image as current. No image-history endpoint/carousel is required.

## Adapters
Development upload returns a dummy URL and performs no real S3 upload. Validation/resize still belongs in the real processing path when implemented. A dummy URL is not evidence of a downloadable object.

A future S3 adapter uploads prepared image and returns the requested public URL. Actual AWS setup/SDK/credentials/bucket configuration and retention remain deferred. POD metadata is distinct from export-file metadata.

## Independent storage retry
Save valid accepted tracking/time/signer even if storage temporarily fails. Persist a pending image record and restricted durable reference to prepared content. Retry storage independently with bounded backoff and idempotent completion of the same image record.

Do not resend the event or create shipment_events to retry an image; exact duplicate-event suppression remains unchanged. Storage retry is continuation of already-accepted image work. On success update URL/readiness; on permanent failure retain accepted tracking and diagnostics without a fabricated URL.

This exception is for transient storage failure. Invalid image/deadline/authorization inputs follow rejection rules before business effects. Delivery classification requires delivery time and POD name, not successful image upload.

## Verification
JPEG/PNG and decoded-size boundaries, malformed input, aspect/width/smaller images, prepared-content retry stability, distinct image history, current selection under late completion, tracking retained on storage failure, one image updated per retry, no extra event and tenant-safe content access.

## P9 implementation
The image validation/preparation, event-linked PostgreSQL history/content queue, independent retry worker and event-ordered detail selection are implemented. The default adapter returns a clearly dummy URL without network I/O. Physical bounds, queue/readiness semantics, operator commands and verification are documented in POD_IMPLEMENTATION.md; actual results are in tasks/plan.md. Real S3/AWS remains deferred.
