import { expect, it } from 'vitest';
import { presetRange, validRange } from './dates';
it.each([
  ['Today', '2026-01-01', '2026-01-01', '2026-01-01'],
  ['Yesterday', '2026-01-01', '2025-12-31', '2025-12-31'],
  ['Last 7 Days', '2026-01-01', '2025-12-26', '2026-01-01'],
  ['Last 30 Days', '2026-03-01', '2026-01-31', '2026-03-01'],
  ['This Month', '2026-03-15', '2026-03-01', '2026-03-15'],
  ['Last Month', '2026-01-15', '2025-12-01', '2025-12-31'],
  ['Last Month', '2028-03-10', '2028-02-01', '2028-02-29'],
] as const)(
  '%s uses UTC calendar bounds at %s',
  (preset, today, start, end) => {
    expect(presetRange(preset, today)).toEqual([start, end]);
  },
);
it('rejects incomplete, impossible and reversed ranges', () => {
  expect(validRange('', '2026-01-01')).toBe(false);
  expect(validRange('0000-01-01', '0001-01-01')).toBe(false);
  expect(validRange('2026-02-29', '2026-03-01')).toBe(false);
  expect(validRange('2026-03-02', '2026-03-01')).toBe(false);
  expect(validRange('2028-02-29', '2028-02-29')).toBe(true);
});
