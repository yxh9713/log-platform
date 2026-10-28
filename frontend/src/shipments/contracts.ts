import { ApiError } from '../api';

export type Area = { id: number; name: string };
export type Lookup = 'reference' | 'shipment_number';
export type Row = {
  id: string;
  shipment_number: string;
  reference: string;
  reference_two: string | null;
  account: string;
  carrier: string;
  service_name: string | null;
  route_id: number | null;
  route: string | null;
  company: string;
  address_one: string;
  address_two: string | null;
  city: string;
  state: string;
  zip: string;
  status: 'Delivered' | 'Undelivered' | 'Void';
  pod_name: string | null;
  deliver_time: string | null;
  due_time: string;
  due_date: string;
  weight: string | null;
};
export type Paging = {
  total: number;
  page: number;
  length: number;
  pages: number;
};
export type TrackingResult = Paging & {
  items: Row[];
  start_date: string;
  end_date: string;
  date_type: string;
  metrics: {
    total: number;
    delivered: number;
    undelivered: number;
    void: number;
    otp: number;
  };
};
export type SearchRow = Pick<
  Row,
  | 'id'
  | 'shipment_number'
  | 'reference'
  | 'route'
  | 'address_one'
  | 'city'
  | 'state'
  | 'zip'
>;
export type SearchResult = Paging & {
  identifier: string;
  field: Lookup;
  items: SearchRow[];
};
export type Address = {
  name: string;
  address_one: string;
  address_two: string | null;
  city: string;
  state: string;
  zip: string;
  note: string | null;
  phone: string | null;
  email: string | null;
};
export type Detail = Row & {
  sender: Address;
  recipient: Address;
  notes: string | null;
  order_date: string | null;
  created_at: string;
  pod_url: string | null;
  history: {
    id: string;
    action: string;
    event_time: string;
    receipt_order: string;
  }[];
};
export type Filters = {
  date_type: 'due_date' | 'order_date' | 'deliver_time' | 'created_at';
  start_date?: string;
  end_date?: string;
  account: string;
  status: '' | 'delivered' | 'undelivered';
  exception: '' | 'attempted' | 'void' | 'returned';
  area: number[];
  page: number;
  length: number;
  sort: string;
  direction: 'asc' | 'desc';
};
export const initialFilters: Filters = {
  date_type: 'due_date',
  account: '',
  status: '',
  exception: '',
  area: [],
  page: 1,
  length: 10,
  sort: 'due_time',
  direction: 'asc',
};
export function trackingPath(filters: Filters) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (key === 'area') continue;
    if (value !== '' && value !== undefined) params.set(key, String(value));
  }
  for (const id of filters.area) params.append('area', String(id));
  return `shipments?${params}`;
}
export function detailHref(row: SearchRow, field: Lookup) {
  const identifier =
    field === 'reference' ? row.reference : row.shipment_number;
  const params = new URLSearchParams({ field, shipment_id: row.id });
  // URL parsers collapse even percent-encoded dot segments. Preserve these
  // identifiers with an explicit second-encoding marker.
  const dotSegment = identifier === '.' || identifier === '..';
  if (dotSegment) params.set('encoding', 'dot');
  const path = dotSegment
    ? identifier.replaceAll('.', '%252E')
    : encodeURIComponent(identifier);
  return `/tracking/detail/${path}?${params}`;
}

// Validate the fields the UI consumes before treating unknown JSON as a DTO.
type RecordValue = Record<string, unknown>;
function record(value: unknown): value is RecordValue {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}
const text = (value: unknown) => typeof value === 'string';
const nullableText = (value: unknown) => value === null || text(value);
const count = (value: unknown) =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
function strings(value: RecordValue, keys: string[], nullable: string[] = []) {
  return (
    keys.every((key) => text(value[key])) &&
    nullable.every((key) => nullableText(value[key]))
  );
}
function paging(value: RecordValue) {
  return (
    ['total', 'page', 'length', 'pages'].every((key) => count(value[key])) &&
    Number(value.page) >= 1 &&
    Number(value.length) >= 1
  );
}
function searchRow(value: unknown): boolean {
  return (
    record(value) &&
    strings(
      value,
      [
        'id',
        'shipment_number',
        'reference',
        'address_one',
        'city',
        'state',
        'zip',
      ],
      ['route'],
    )
  );
}
function row(value: unknown): boolean {
  return (
    record(value) &&
    searchRow(value) &&
    strings(
      value,
      ['account', 'carrier', 'company', 'due_time', 'due_date'],
      [
        'reference_two',
        'service_name',
        'address_two',
        'pod_name',
        'deliver_time',
        'weight',
      ],
    ) &&
    (value.route_id === null || count(value.route_id)) &&
    ['Delivered', 'Undelivered', 'Void'].includes(String(value.status))
  );
}
function address(value: unknown): boolean {
  return (
    record(value) &&
    strings(
      value,
      ['name', 'address_one', 'city', 'state', 'zip'],
      ['address_two', 'note', 'phone', 'email'],
    )
  );
}
function invalid(): never {
  throw new ApiError(
    0,
    'The service returned unexpected shipment data. Please try again.',
  );
}
export function parseAreas(value: unknown): Area[] {
  if (
    !Array.isArray(value) ||
    !value.every(
      (item) =>
        record(item) &&
        count(item.id) &&
        Number(item.id) > 0 &&
        text(item.name),
    )
  )
    return invalid();
  return value as Area[];
}
export function parseArea(value: unknown): Area {
  return parseAreas([value])[0];
}
export function parseTracking(value: unknown): TrackingResult {
  if (
    !record(value) ||
    !paging(value) ||
    !strings(value, ['start_date', 'end_date', 'date_type']) ||
    !Array.isArray(value.items) ||
    !value.items.every(row) ||
    !record(value.metrics) ||
    !['total', 'delivered', 'undelivered', 'void'].every((key) =>
      count((value.metrics as RecordValue)[key]),
    ) ||
    typeof value.metrics.otp !== 'number' ||
    !Number.isFinite(value.metrics.otp)
  )
    return invalid();
  return value as TrackingResult;
}
export function parseSearch(value: unknown): SearchResult {
  if (
    !record(value) ||
    !paging(value) ||
    !text(value.identifier) ||
    !['reference', 'shipment_number'].includes(String(value.field)) ||
    !Array.isArray(value.items) ||
    !value.items.every(searchRow)
  )
    return invalid();
  return value as SearchResult;
}
export function parseDetail(value: unknown): Detail {
  if (
    !record(value) ||
    !row(value) ||
    !address(value.sender) ||
    !address(value.recipient) ||
    !strings(value, ['created_at'], ['notes', 'order_date', 'pod_url']) ||
    !Array.isArray(value.history) ||
    !value.history.every(
      (item) =>
        record(item) &&
        strings(item, ['id', 'action', 'event_time', 'receipt_order']),
    )
  )
    return invalid();
  return value as Detail;
}
