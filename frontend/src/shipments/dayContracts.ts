import { ApiError } from '../api';

export type DayMetrics = {
  total: number;
  delivered: number;
  undelivered: number;
  void: number;
  otp: number;
};
export type AreaStats = DayMetrics & { id: number; area: string };
export type Exceptions = {
  attempted: number;
  returned: number;
  void: number;
  consolidated: 0;
  no_package: 0;
  held: 0;
};
export type DayReport = {
  report_date: string;
  stats: DayMetrics;
  exceptions: Exceptions;
  areas: AreaStats[];
};
const record = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === 'object' && !Array.isArray(value);
const count = (value: unknown): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
function metrics(
  value: unknown,
): value is DayMetrics & Record<string, unknown> {
  return (
    record(value) &&
    count(value.total) &&
    count(value.delivered) &&
    count(value.undelivered) &&
    count(value.void) &&
    value.total === value.delivered + value.undelivered + value.void &&
    typeof value.otp === 'number' &&
    Number.isFinite(value.otp) &&
    value.otp >= 0 &&
    value.otp <= 100
  );
}
export function parseDay(value: unknown): DayReport {
  if (
    !record(value) ||
    typeof value.report_date !== 'string' ||
    !/^\d{4}-\d{2}-\d{2}$/.test(value.report_date) ||
    Number.isNaN(Date.parse(value.report_date)) ||
    new Date(value.report_date).toISOString().slice(0, 10) !==
      value.report_date ||
    !metrics(value.stats) ||
    !record(value.exceptions) ||
    !['attempted', 'returned', 'void'].every((key) =>
      count((value.exceptions as Record<string, unknown>)[key]),
    ) ||
    !['consolidated', 'no_package', 'held'].every(
      (key) => (value.exceptions as Record<string, unknown>)[key] === 0,
    ) ||
    !Array.isArray(value.areas)
  )
    return invalid();
  const totals = value.stats;
  const exceptions = value.exceptions as Exceptions;
  if (
    exceptions.void !== totals.void ||
    exceptions.attempted + exceptions.returned > totals.undelivered
  )
    return invalid();
  const ids = new Set<number>();
  for (const area of value.areas) {
    if (
      !record(area) ||
      !metrics(area) ||
      !count(area.id) ||
      area.id < 1 ||
      typeof area.area !== 'string' ||
      !area.area.trim() ||
      ids.has(area.id)
    )
      return invalid();
    ids.add(area.id);
  }
  const areas = value.areas as AreaStats[];
  if (
    ['total', 'delivered', 'undelivered', 'void'].some(
      (key) =>
        areas.reduce((sum, area) => sum + area[key as keyof DayMetrics], 0) >
        totals[key as keyof DayMetrics],
    )
  )
    return invalid();
  return value as DayReport;
}
function invalid(): never {
  throw new ApiError(
    0,
    'The service returned unexpected My Day data. Please try again.',
  );
}
