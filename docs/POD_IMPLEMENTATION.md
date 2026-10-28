# P9 POD images and independent storage

P9 implements the approved POD_STORAGE.md and D43 contract for webhook pod and carrier CSV pod_image. Authentication, carrier/account/reference matching, source receipts, exact event dedupe, ordinary-field guards and file lifecycle remain P8/P7. Actual S3/AWS setup remains deferred. No new dashboard endpoint or frontend DTO is introduced; existing shipment detail's nullable pod_url now reads the selected image metadata.

## Validation and preparation

The shared carrier transaction authenticates/matches and suppresses unknown/duplicate events before image preparation. Valid image preparation and deadline/route validation precede event, image, area and ordinary-field effects. Invalid image/deadline input rejects the entire request/CSV row with the existing sanitized diagnostics; other valid CSV rows continue. Missing/empty/null images preserve prior image history. The P8 image-stage gate is removed.

**Engineering dependency:** Pillow 13.0.0 is pinned and frozen in backend/uv.lock; other locked dependencies are retained. The version and validation APIs were checked against the project's official [release notes](https://pillow.readthedocs.io/en/stable/releasenotes/13.0.0.html) and [Image documentation](https://pillow.readthedocs.io/en/stable/reference/Image.html). There is no AWS SDK or image generation service.

Input accepts strict standard base64 (plain data, without data-URL prefixes or embedded wrapping). Decode only after the encoded bound, then enforce the exact 5,000,000-byte decoded ceiling. JPEG/PNG detection uses restricted Pillow plugins, verify and full decode, not a declared MIME type/extension. GIF/WebP/BMP/TIFF, corrupt/truncated data and animated/multiframe PNG are rejected. Bounds apply before full decode: at most 20,000,000 pixels and 20,000 on either side. These implementation bounds do not replace deployment CPU/memory/concurrency limits.

Apply EXIF orientation, then cap width at 900 without upscaling. Height uses proportional integer rounding with a one-pixel minimum. JPEG is encoded as RGB at quality 85; PNG preserves alpha when present. Output EXIF/ICC/comments/text metadata are stripped. Reopen/verify the prepared image, check actual dimensions/format and cap prepared bytes at 20,000,000. Persist measured input/output sizes, MIME type, dimensions and SHA-256. Preparation is deterministic for the pinned runtime and never repeated by a storage retry.

## Durable acceptance and history

Revision `0006_pod_images` adds shipment_images, tenant/event-owner composite FKs, one image per accepted event, stable unique object keys, content/readiness/counter constraints, a work index and an image link in ingestion_errors. Supporting event/shipment composite unique keys precede those FKs in the migration. No tenant/image/source/key data is seeded or backfilled.

The same transaction commits the distinct event, its permitted tracking/time/signer/route/deadline changes and a pending image row with prepared bytes. PostgreSQL BYTEA is the restricted durable prepared-content reference for local development; no public HTTP endpoint returns it. General logs/status output contain no base64/prepared bytes/signer/contact data. The request body is not copied into image metadata or logs. Image history retains event association and URL/size/dimension/hash metadata, without a legacy shipment/type uniqueness limit or a history carousel.

The object key is generated from trusted tenant/shipment/image identity: pod/TENANT/SHIPMENT/IMAGE-UUID.ext. No payload path/reference/contact text chooses a storage path. Exact event duplicates never create another image or change tie order, even if image/signer fields differ. Unknown/unmatched/unauthorized updates never prepare or enqueue an image. Missing signer is accepted; image readiness does not invent a name or independently classify delivery.

## Independent worker and storage seam

The optional ingestion Compose profile adds pod-worker, separate from file intake. It requires only PostgreSQL and runs as the backend's non-root user; it needs no sftp mount, Redis job payload or external credentials. The worker scans up to 20 due image identities per one-second tick. A per-image PostgreSQL session advisory lock serializes overlapping workers and releases on process/connection death.

Before storage I/O, commit the incremented attempt and next backoff in PostgreSQL. A crash is therefore a counted attempt. The worker verifies prepared-content hash/size and calls the injected PodStorage.upload(object_key, bytes, content_type) seam. The same object key/hash and same image row are reused after a crash, including upload success followed by checkpoint failure; a future real adapter must implement idempotent writes and bounded I/O timeouts. No event, field normalization, row checkpoint or shipment mutation is replayed for image retries.

Default DummyPodStorage performs **no network or real upload** and returns https://pod.invalid/ followed by the generated object key. A ready row means the configured adapter returned its URL; in this development adapter that URL is deliberately non-downloadable, not evidence of a stored S3 object. Existing frontend image-failure handling remains applicable. The worker validates HTTPS URL shape/length and rejects credential-bearing URLs before saving shipment_images.url. Prepared bytes are released from the row after the ready checkpoint; failed/pending bytes remain for retry/repair. Historical metadata/URLs remain.

At most five attempts run automatically; waits before subsequent attempts are 5, 30, 120 and 600 seconds. Retryable storage exceptions leave tracking committed and URL null, with a safe reason and delayed next attempt. Permanent storage/invalid URL/content-integrity failures stop immediately; exhausted attempts record a tenant/shipment/image-scoped PostgreSQL diagnostic and keep the prepared content. Neither failure nor retry erases accepted delivery time/signer/history. Database outages cannot acknowledge image readiness and retain the last durable attempt/content; independent worker health reports unsuccessful ticks.

## Current POD selection

Detail authorizes the shipper first and selects one image-bearing accepted event by greatest event_time then receipt_order, before considering readiness. This ordering applies to retained image-bearing events; later missing images preserve the previous image. Pending/failed selected image has URL null and cannot fall back to another event's ready image. Older upload completion never changes the selected event, including distinct equal-time receipt ties. Returned retains image history while the existing terminal reducer reports Undelivered; no image result overrides Void or time/name classification.

The query returns only the selected URL, with no prepared content, image list or unauthenticated image endpoint. Foreign package reads retain the same 404 as other missing/foreign detail requests. Pending becomes visible only after its storage checkpoint commits; no SSE/readiness notification is claimed here (P11).

## Local operation

Use DEVELOPMENT.md for staged rebuilding, explicit migration before optional workers and existing private local settings. No re-seeding/key provisioning is needed. Inspect images through the trusted CLI:

```sh
docker compose --profile ingestion exec pod-worker python -m app.pod.cli status
docker compose --profile ingestion exec pod-worker python -m app.pod.cli once
# Only after investigating/fixing a failed storage job:
docker compose --profile ingestion exec pod-worker python -m app.pod.cli retry --image-id IMAGE_UUID
```

Status shows the last 100 image IDs, package IDs, state/attempts/reason and size/dimensions; it never emits content or signer data. Explicit retry resets only a failed image's storage attempts when prepared bytes remain. It cannot replay an event or restore image work on an exact duplicate event. P8-era rejected images/import rows remain recorded errors and do not auto-replay after upgrade. Worker heartbeat requires successful database ticks within 120 seconds; inspect image states independently of health.

Run `sh scripts/verify-p9.sh` for the full synthetic application suite. Unit tests use generated JPEG/PNG and other-format/corrupt/size-boundary fixtures, never reference tenant contacts or image placeholders. Integration tests cover real PostgreSQL transactions, carrier CSV/webhooks, storage failure/crashes/concurrency, selected pending/failed and late-completion behavior, no-signature handling, retry privacy/CLI, tenant/event FKs and prior-slice regressions. Actual executed results are in tasks/plan.md.

Production throughput, decoder process isolation/concurrency, database asset retention/quota/backup and actual public-object storage require deployment configuration. No production security/performance certification, real AWS upload or new full real-backend browser E2E run is claimed. My Day/charts, exports/SSE and broader E2E remain P10/P11/P12.
