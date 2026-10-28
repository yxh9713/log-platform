# CSV File Lifecycle

## Sources and finalization
Local intake is sftp/{slug}/upload/. Register trusted source company and adapter independently of file contents. Paychex is a manifest source; OnTrac is a carrier source that may serve several shippers.

Upload as .part, then rename to finalized .csv. Ignore .part. Poll every 60 seconds by default, configurable independently per source. Claim finalized input safely so overlapping scans/workers cannot process it concurrently.

**Recommendation:** separate ingestion_source table with id, company_id, source_type (manifest/carrier_status), poll_interval_seconds (positive, default 60), enabled. Adapter/folder binding is trusted configuration. This is distinct from webhook integrations and account_mapping. Exact schema and manual configuration reload are implementation design; no management UI is required.

## Outcomes and archive paths
| Outcome | PostgreSQL state | Archive | Valid rows |
|---|---|---|---|
| Fully processed with no rejected rows | completed | sftp/{slug}/done/YYYY/MM/DD/filename.csv | Kept |
| Some rows rejected | completed_with_errors | sftp/{slug}/failed/YYYY/MM/DD/filename.csv | Kept |
| Unreadable/invalid file structure or headers | failed | sftp/{slug}/failed/YYYY/MM/DD/filename.csv | Previously committed valid rows are not rolled back |

YYYY/MM/DD uses UTC processing date, not the filename or source order date. **Engineering choice:** capture it at initial claim and keep it on retry. Preserve mainfest filename spelling in examples. A file named mainfest-20261021.csv processed on 2026-10-24 archives under 2026/10/24.

Finalize archive moves after durable outcomes/error records. Track archive completion separately so a move failure does not reapply committed ordinary-field updates. Do not treat failed/ as another auto-polled upload source.

## Identity and collisions
Never overwrite archived files; add an import-ID suffix on filename collision. Retain original filename/path/checksum/source identity in audit.

Skip identical already-finished content from the same trusted source, even if renamed. Filename alone is not identity. Changed content under the same filename is a new import and still obeys package/event dedupe. Never dedupe content globally across tenants/sources.

Resume/recover a crashed in-progress import instead of calling it completed or assigning new receipt order to every row. Use durable per-row processing state and transactional guards as engineering design.

## Errors and retries
Store import counters and rejected-row diagnostics durably in PostgreSQL. Retry transient database/storage/archive infrastructure failures with bounded backoff. Invalid files/business rows do not loop indefinitely. Partial files retain committed valid rows and finish as completed_with_errors in failed/.

Unknown event codes are ignored, not rejected solely for being unknown. Unmatched shipments are error-only without delayed automatic event retry. Corrected re-uploaded content can be a new import; manual replay tooling is not an additional required UI.

## Verification
Test final rename, source polling isolation, concurrent claims, mixed valid/invalid rows, invalid headers, UTC archive dates, filename collisions, content identity across rename/change, row recovery, archive failure and bounded infrastructure retry.
