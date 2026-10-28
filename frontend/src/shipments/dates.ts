export const dayKey = (day: Date) => day.toISOString().slice(0, 10);
export const utcToday = () => dayKey(new Date());
export function dateOf(key: string) {
  return new Date(`${key}T00:00:00Z`);
}
export function addDays(key: string, amount: number) {
  const day = dateOf(key);
  day.setUTCDate(day.getUTCDate() + amount);
  return dayKey(day);
}
export function monthStart(key: string, delta = 0) {
  const day = dateOf(key);
  day.setUTCDate(1);
  day.setUTCMonth(day.getUTCMonth() + delta);
  return dayKey(day);
}
export function prettyDate(key: string) {
  return dateOf(key).toLocaleDateString('en-US', {
    month: 'short',
    day: '2-digit',
    year: 'numeric',
    timeZone: 'UTC',
  });
}
export const presets = [
  'Today',
  'Yesterday',
  'Last 7 Days',
  'Last 30 Days',
  'This Month',
  'Last Month',
] as const;
export function presetRange(
  name: (typeof presets)[number],
  today = utcToday(),
): [string, string] {
  switch (name) {
    case 'Today':
      return [today, today];
    case 'Yesterday':
      return [addDays(today, -1), addDays(today, -1)];
    case 'Last 7 Days':
      return [addDays(today, -6), today];
    case 'Last 30 Days':
      return [addDays(today, -29), today];
    case 'This Month':
      return [monthStart(today), today];
    case 'Last Month':
      return [monthStart(today, -1), addDays(monthStart(today), -1)];
  }
}
export function validRange(start: string, end: string) {
  return (
    /^\d{4}-\d{2}-\d{2}$/.test(start) &&
    /^\d{4}-\d{2}-\d{2}$/.test(end) &&
    Number.isFinite(dateOf(start).getTime()) &&
    Number.isFinite(dateOf(end).getTime()) &&
    dayKey(dateOf(start)) === start &&
    dayKey(dateOf(end)) === end &&
    start >= '0001-01-01' &&
    start <= end
  );
}
