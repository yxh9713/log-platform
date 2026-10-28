export type ExportJob = {
  id: string;
  state: 'pending' | 'retry_wait' | 'ready' | 'failed';
  created_at: string;
  url: string | null;
  row_count: number | null;
  reason_code: string | null;
};
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
export function parseExports(value: unknown): ExportJob[] {
  if (
    !value ||
    typeof value !== 'object' ||
    !('items' in value) ||
    !Array.isArray(value.items) ||
    value.items.length > 50
  )
    throw new Error('Unable to read export updates. Please refresh exports.');
  const identities = new Set<string>();
  for (const item of value.items) {
    if (
      !item ||
      typeof item !== 'object' ||
      typeof item.id !== 'string' ||
      !uuid.test(item.id) ||
      identities.has(item.id) ||
      !['pending', 'retry_wait', 'ready', 'failed'].includes(item.state) ||
      typeof item.created_at !== 'string' ||
      !Number.isFinite(Date.parse(item.created_at)) ||
      !(
        item.row_count === null ||
        (Number.isSafeInteger(item.row_count) && item.row_count >= 0)
      ) ||
      !(item.reason_code === null || typeof item.reason_code === 'string') ||
      (item.state === 'ready'
        ? item.url !== `/v1/exports/${item.id}/download` ||
          item.row_count === null
        : item.url !== null)
    )
      throw new Error('Unable to read export updates. Please refresh exports.');
    identities.add(item.id);
  }
  return value.items as ExportJob[];
}
