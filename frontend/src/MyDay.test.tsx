import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import Workspace from './Workspace';
import type { Session } from './api';
import fixture from '../tests/shipments.json';
import day from '../tests/day.json';
import { parseDay } from './shipments/dayContracts';

const fetchMock = vi.fn<typeof fetch>();
const expired = vi.fn();
let report: unknown;
function reply(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
function workspace(
  role: 'administrator' | 'user' = 'administrator',
  company = fixture.session.company,
) {
  return (
    <Workspace
      key={`${company.id}:${role}`}
      session={{ ...fixture.session, role, company } as Session}
      pending={false}
      signOut={() => {}}
      notice={null}
      onExpired={expired}
    />
  );
}
beforeEach(() => {
  window.history.replaceState(null, '', '/');
  report = structuredClone(day);
  expired.mockReset();
  fetchMock.mockReset();
  vi.stubGlobal('fetch', ((input, options) =>
    String(input) === '/v1/exports'
      ? Promise.resolve(
          new Response(JSON.stringify({ items: [] }), { status: 200 }),
        )
      : fetchMock(input, options)) as typeof fetch);
  fetchMock.mockImplementation(async (input) => {
    const path = new URL(String(input), 'http://localhost').pathname;
    if (path === '/v1/my-day') return reply(report);
    if (path === '/v1/areas') return reply(fixture.areas);
    return reply({ message: 'Unexpected request' }, 500);
  });
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  window.history.replaceState(null, '', '/');
});

it('renders one server snapshot, UTC date, accessible charts and empty/all-Void area cards', async () => {
  render(workspace());
  expect(screen.getByText('Loading My Day…')).toBeInTheDocument();
  await screen.findByText('2026-10-28');
  expect(screen.getByLabelText('My Day shipment metrics')).toHaveTextContent(
    'Total8Includes 1 VoidUndelivered4',
  );
  expect(screen.getByLabelText('My Day shipment metrics')).toHaveTextContent(
    '66.67%',
  );
  expect(
    screen.getByRole('img', {
      name: "Today's shipment status: 3 delivered, 4 undelivered, 1 void",
    }),
  ).toBeInTheDocument();
  const cards = ['alpha', 'empty', 'void'].map(
    (name) =>
      screen.getByRole('heading', { name, level: 3 }).closest('section')!,
  );
  expect(cards[1]).toHaveTextContent('0.00% On time');
  expect(cards[2]).toHaveTextContent('0.00% On time');
  const exceptions = screen
    .getByRole('heading', { name: 'Exceptions' })
    .closest('section')!;
  for (const label of ['Consolidated', 'No package', 'Held'])
    expect(within(exceptions).getByText(label).closest('li')).toHaveTextContent(
      '0',
    );
  expect(
    screen.getByText(/Unassigned packages and packages in deleted areas/),
  ).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(String(fetchMock.mock.calls[0][0])).toBe('/v1/my-day');
  expect(
    screen.queryByText(/currentHour|last updated/i),
  ).not.toBeInTheDocument();
});

it('shows real zero and no-exception states without fake chart slices', async () => {
  report = {
    ...day,
    stats: { total: 0, delivered: 0, undelivered: 0, void: 0, otp: 0 },
    exceptions: {
      attempted: 0,
      returned: 0,
      void: 0,
      consolidated: 0,
      no_package: 0,
      held: 0,
    },
    areas: [],
  };
  render(workspace('user'));
  await screen.findByText('No packages due today.');
  expect(screen.getByText('No exceptions for today.')).toBeInTheDocument();
  expect(screen.getByLabelText('My Day shipment metrics')).toHaveTextContent(
    '0.00%',
  );
  expect(
    screen
      .getByRole('img', { name: /Today's shipment status/ })
      .querySelectorAll('circle'),
  ).toHaveLength(1);
  expect(
    screen.queryByRole('button', { name: 'Add area' }),
  ).not.toBeInTheDocument();
  expect(screen.queryByLabelText('Enable editing')).not.toBeInTheDocument();
});

it('displays the no-Delivered OTP case and all-Void case without changing the API percentage', async () => {
  report = {
    ...day,
    stats: { total: 2, delivered: 0, undelivered: 2, void: 0, otp: 100 },
    exceptions: { ...day.exceptions, attempted: 0, returned: 0, void: 0 },
    areas: [],
  };
  render(workspace());
  await screen.findByText('No completed deliveries yet');
  expect(screen.getByLabelText('My Day shipment metrics')).toHaveTextContent(
    '100.00%',
  );
  report = {
    ...day,
    stats: { total: 2, delivered: 0, undelivered: 0, void: 2, otp: 0 },
    exceptions: { ...day.exceptions, attempted: 0, returned: 0, void: 2 },
    areas: [],
  };
  fireEvent.click(screen.getByRole('button', { name: 'Refresh dashboard' }));
  await screen.findByText('No eligible packages');
  expect(screen.getByLabelText('My Day shipment metrics')).toHaveTextContent(
    '0.00%',
  );
});

it('recovers from an unavailable or malformed report without inventing zero totals', async () => {
  fetchMock.mockResolvedValueOnce(
    reply({ message: 'Dashboard unavailable' }, 503),
  );
  render(workspace());
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Dashboard unavailable',
  );
  expect(
    screen.queryByLabelText('My Day shipment metrics'),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
  await screen.findByRole('img', { name: /Today's shipment status/ });
  report = { ...day, stats: { ...day.stats, otp: Infinity } };
  fireEvent.click(screen.getByRole('button', { name: 'Refresh dashboard' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'unexpected My Day data',
  );
});

it('expires the verified workspace for a protected dashboard 401', async () => {
  fetchMock.mockResolvedValueOnce(
    reply({ message: 'Authentication required' }, 401),
  );
  render(workspace());
  await waitFor(() => expect(expired).toHaveBeenCalledTimes(1));
  expect(
    screen.queryByLabelText('My Day shipment metrics'),
  ).not.toBeInTheDocument();
});

it('refreshes the same snapshot after shared administrator area creation/rename/delete', async () => {
  render(workspace());
  await screen.findByRole('heading', { name: 'alpha', level: 3 });
  fireEvent.click(screen.getByLabelText('Enable editing'));
  fireEvent.click(screen.getByRole('button', { name: 'Edit alpha' }));
  fireEvent.change(screen.getByLabelText('Area name'), {
    target: { value: 'renamed' },
  });
  fetchMock.mockImplementation(async (input, options) => {
    const path = new URL(String(input), 'http://localhost').pathname;
    if (options?.method === 'PUT') {
      report = {
        ...day,
        areas: day.areas.map((area) =>
          area.id === 1 ? { ...area, area: 'renamed' } : area,
        ),
      };
      return reply({ id: 1, name: 'renamed' });
    }
    if (options?.method === 'DELETE') {
      report = { ...day, areas: day.areas.filter((area) => area.id !== 1) };
      return reply({ message: 'Area deleted' });
    }
    if (options?.method === 'POST') {
      report = day;
      return reply({ id: 1, name: 'alpha' }, 200);
    }
    if (path === '/v1/my-day') return reply(report);
    return reply({ message: 'unexpected' }, 500);
  });
  fireEvent.click(screen.getByRole('button', { name: 'Save area' }));
  await screen.findByRole('heading', { name: 'renamed', level: 3 });
  expect(screen.getByLabelText('Enable editing')).toBeChecked();
  expect(
    fetchMock.mock.calls.some(
      ([, options]) =>
        options?.method === 'PUT' &&
        options?.headers &&
        JSON.stringify(options.headers).includes('X-Requested-With'),
    ),
  ).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Delete renamed' }));
  fireEvent.click(
    within(screen.getByRole('dialog')).getByRole('button', {
      name: 'Delete area',
    }),
  );
  await waitFor(() =>
    expect(
      screen.queryByRole('heading', { name: 'renamed', level: 3 }),
    ).not.toBeInTheDocument(),
  );
  expect(
    await screen.findByLabelText('My Day shipment metrics'),
  ).toHaveTextContent('Total8');
  fireEvent.click(screen.getByRole('button', { name: 'Add area' }));
  fireEvent.change(screen.getByLabelText('Area name'), {
    target: { value: 'alpha' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Save area' }));
  await screen.findByRole('heading', { name: 'alpha', level: 3 });
  expect(
    screen.getAllByRole('img', { name: /alpha shipment status/ }),
  ).toHaveLength(1);
});

it('does not enable area editing after dashboard remount', async () => {
  const view = render(workspace());
  await screen.findByText('2026-10-28');
  fireEvent.click(screen.getByLabelText('Enable editing'));
  view.unmount();
  render(workspace());
  await screen.findByText('2026-10-28');
  expect(screen.getByLabelText('Enable editing')).not.toBeChecked();
  expect(
    screen.queryByRole('button', { name: 'Edit alpha' }),
  ).not.toBeInTheDocument();
});

it('refreshes on focus and ignores a late response after changing verified company', async () => {
  let finish!: (response: Response) => void;
  fetchMock.mockReturnValueOnce(
    new Promise<Response>((resolve) => {
      finish = resolve;
    }),
  );
  const view = render(workspace());
  view.rerender(
    workspace('user', { id: 'other', name: 'Other company', slug: 'other' }),
  );
  await screen.findByText('2026-10-28');
  finish(
    reply({
      ...day,
      stats: { total: 999, delivered: 999, undelivered: 0, void: 0, otp: 100 },
      areas: [],
      exceptions: { ...day.exceptions, attempted: 0, returned: 0, void: 0 },
    }),
  );
  await act(async () => {
    await Promise.resolve();
  });
  expect(
    screen.getByLabelText('My Day shipment metrics'),
  ).not.toHaveTextContent('999');
  const before = fetchMock.mock.calls.length;
  fireEvent(window, new Event('focus'));
  await waitFor(() => expect(fetchMock.mock.calls.length).toBe(before + 1));
  expect(
    screen.queryByRole('button', { name: 'Add area' }),
  ).not.toBeInTheDocument();
});

it('requests a new server day after UTC midnight without showing a last-updated clock', async () => {
  vi.useFakeTimers();
  vi.setSystemTime('2026-10-28T23:59:59Z');
  render(workspace('user'));
  await act(async () => {
    await Promise.resolve();
  });
  expect(fetchMock).toHaveBeenCalledTimes(1);
  report = { ...day, report_date: '2026-10-29' };
  await act(async () => {
    await vi.advanceTimersByTimeAsync(2100);
  });
  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(screen.getByText('2026-10-29')).toBeInTheDocument();
  expect(screen.queryByText(/last updated/i)).not.toBeInTheDocument();
});

it.each([
  { ...day, report_date: '2026-02-30' },
  { ...day, stats: { ...day.stats, total: 99 } },
  { ...day, stats: { ...day.stats, otp: 101 } },
  { ...day, exceptions: { ...day.exceptions, held: 1 } },
  { ...day, exceptions: { ...day.exceptions, attempted: 10 } },
  { ...day, areas: [day.areas[0], day.areas[0]] },
  { ...day, areas: [{ ...day.areas[0], id: 0 }] },
  { ...day, areas: [{ ...day.areas[0], total: 100, delivered: 98 }] },
])('rejects impossible dashboard DTOs before rendering %j', (value) => {
  expect(() => parseDay(value)).toThrow('unexpected My Day data');
});
