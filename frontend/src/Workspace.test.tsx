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
import App from './App';
import Workspace from './Workspace';
import type { Session } from './api';
import fixture from '../tests/shipments.json';
import DateRange from './shipments/DateRange';
import { navigate } from './shipments/hooks';

const fetchMock = vi.fn<typeof fetch>();
const expired = vi.fn();
function reply(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
function urlAt(index = -1) {
  return new URL(
    String(fetchMock.mock.calls.at(index)![0]),
    'http://localhost',
  );
}
function workspace(role: 'administrator' | 'user' = 'administrator') {
  return render(
    <Workspace
      session={{ ...fixture.session, role } as Session}
      pending={false}
      signOut={() => {}}
      notice={null}
      onExpired={expired}
    />,
  );
}
beforeEach(() => {
  window.history.replaceState(null, '', '/tracking');
  vi.stubGlobal('fetch', ((input, options) =>
    String(input) === '/v1/exports'
      ? Promise.resolve(
          new Response(JSON.stringify({ items: [] }), { status: 200 }),
        )
      : fetchMock(input, options)) as typeof fetch);
  fetchMock.mockReset();
  expired.mockReset();
  fetchMock.mockImplementation(async (input) => {
    const url = new URL(String(input), 'http://localhost');
    if (url.pathname === '/v1/session')
      return reply({
        ...fixture.session,
        expires_at: new Date(Date.now() + 3600000).toISOString(),
      });
    if (url.pathname === '/v1/areas') return reply(fixture.areas);
    if (url.pathname === '/v1/shipments/search') return reply(fixture.search);
    if (/\/shipments\/\d+$/.test(url.pathname)) return reply(fixture.detail);
    return reply({
      ...fixture.tracking,
      page: Number(url.searchParams.get('page') ?? 1),
      length: Number(url.searchParams.get('length') ?? 10),
    });
  });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.history.replaceState(null, '', '/');
});

it('renders full-result metrics and preserves leading zeros and incomplete delivery time', async () => {
  workspace();
  expect(screen.getByText('Loading shipments…')).toBeInTheDocument();
  await screen.findByText('24 packages · Page 1 of 3');
  expect(screen.getByLabelText('Filtered shipment metrics')).toHaveTextContent(
    '3 Undelivered24 Total95.00% On time',
  );
  expect(screen.getAllByText('00123')).toHaveLength(2);
  expect(screen.getAllByText('2026-10-20 16:45-07:00')).toHaveLength(2);
  expect(
    screen.getByRole('option', { name: 'Void' }).parentElement,
  ).toHaveAccessibleName('Exceptions');
  fireEvent.click(screen.getByRole('button', { name: 'Next' }));
  await screen.findByText('24 packages · Page 2 of 3');
  fireEvent.change(screen.getByRole('combobox', { name: 'Status' }), {
    target: { value: 'undelivered' },
  });
  await waitFor(() =>
    expect(urlAt().searchParams.get('status')).toBe('undelivered'),
  );
  expect(urlAt().searchParams.get('page')).toBe('1');
  fireEvent.click(screen.getByText('Areas', { selector: 'summary' }));
  fireEvent.click(screen.getByLabelText('west'));
  await waitFor(() =>
    expect(urlAt().searchParams.getAll('area')).toEqual(['1']),
  );
  fireEvent.click(screen.getByLabelText('east'));
  await waitFor(() =>
    expect(urlAt().searchParams.getAll('area')).toEqual(['1', '2']),
  );
  fireEvent.click(screen.getByText('Account', { selector: 'summary' }));
  fireEvent.change(screen.getByLabelText('Exact account'), {
    target: { value: '0007' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Apply account' }));
  await waitFor(() => expect(urlAt().searchParams.get('account')).toBe('0007'));
});

it('sorts on the server, changes page size, and owns visible columns locally', async () => {
  workspace();
  await screen.findByText('24 packages · Page 1 of 3');
  fireEvent.click(screen.getByRole('button', { name: 'Reference' }));
  await waitFor(() =>
    expect(urlAt().searchParams.get('sort')).toBe('reference'),
  );
  fireEvent.click(screen.getByRole('button', { name: 'Reference' }));
  await waitFor(() =>
    expect(urlAt().searchParams.get('direction')).toBe('desc'),
  );
  fireEvent.change(screen.getByLabelText('Rows per page'), {
    target: { value: '25' },
  });
  await waitFor(() => expect(urlAt().searchParams.get('length')).toBe('25'));
  const calls = fetchMock.mock.calls.length;
  fireEvent.click(screen.getByText('Columns', { selector: 'summary' }));
  fireEvent.click(screen.getByLabelText('Route', { selector: 'input' }));
  expect(
    screen.queryByRole('button', { name: 'Route' }),
  ).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(calls);
});

it('stages a two-month range, cancels without commits, restores focus and applies complete bounds', () => {
  const apply = vi.fn();
  render(<DateRange start="2026-10-01" end="2026-10-24" apply={apply} />);
  const trigger = screen.getByRole('button', { name: /Oct 01/ });
  trigger.focus();
  fireEvent.click(trigger);
  expect(
    screen.getByRole('region', { name: 'October 2026' }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole('region', { name: 'November 2026' }),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Oct 10, 2026' }));
  expect(screen.getByRole('button', { name: 'Apply' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(trigger).toHaveFocus();
  expect(apply).not.toHaveBeenCalled();
  trigger.focus();
  fireEvent.click(trigger);
  fireEvent.change(screen.getByLabelText('Start date'), {
    target: { value: '2026-10-02' },
  });
  fireEvent.change(screen.getByLabelText('End date'), {
    target: { value: '2026-10-20' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
  expect(apply).toHaveBeenCalledWith('2026-10-02', '2026-10-20');
});

it('handles date presets, arrow focus, Escape and resets Tracking pagination on Apply', async () => {
  workspace();
  await screen.findByText('24 packages · Page 1 of 3');
  fireEvent.click(screen.getByRole('button', { name: 'Next' }));
  await screen.findByText('24 packages · Page 2 of 3');
  fireEvent.click(screen.getByRole('button', { name: /Oct 20, 2026/ }));
  const tenth = screen.getByRole('button', { name: 'Oct 10, 2026' });
  tenth.focus();
  fireEvent.keyDown(tenth, { key: 'ArrowRight' });
  expect(screen.getByRole('button', { name: 'Oct 11, 2026' })).toHaveFocus();
  fireEvent.click(screen.getByRole('button', { name: 'Last Month' }));
  const start = (screen.getByLabelText('Start date') as HTMLInputElement).value;
  const end = (screen.getByLabelText('End date') as HTMLInputElement).value;
  fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
  await waitFor(() =>
    expect(urlAt().searchParams.get('start_date')).toBe(start),
  );
  expect(urlAt().searchParams.get('end_date')).toBe(end);
  expect(urlAt().searchParams.get('page')).toBe('1');
  fireEvent.click(screen.getByRole('button', { name: / – / }));
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

it('uses only the selected Search namespace and the clicked stable ID among duplicate numbers', async () => {
  window.history.replaceState(null, '', '/tracking/search');
  workspace();
  expect(screen.getByLabelText('Search by')).toHaveValue('reference');
  expect(fetchMock).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText('Search by'), {
    target: { value: 'shipment_number' },
  });
  fireEvent.change(screen.getByLabelText('Identifier'), {
    target: { value: ' 000DUP ' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Search' }));
  await screen.findByRole('heading', { name: 'Choose a shipment' });
  expect(urlAt().searchParams.get('field')).toBe('shipment_number');
  expect(urlAt().searchParams.get('identifier')).toBe('000DUP');
  expect(urlAt().searchParams.has('start_date')).toBe(false);
  expect(
    screen.getAllByRole('columnheader').map((cell) => cell.textContent),
  ).toEqual([
    'Shipment',
    'Reference',
    'Route',
    'Address',
    'City',
    'State',
    'Zip',
  ]);
  fireEvent.click(screen.getAllByRole('link', { name: '000DUP' })[1]);
  await screen.findByRole('heading', { name: 'Shipment 000DUP' });
  expect(window.location.pathname).toBe('/tracking/detail/000DUP');
  expect(new URLSearchParams(window.location.search).get('shipment_id')).toBe(
    '102',
  );
  expect(
    fetchMock.mock.calls.some(([url]) => url === '/v1/shipments/102'),
  ).toBe(true);
  expect(screen.getByText('No POD image available.')).toBeInTheDocument();
  expect(screen.getAllByText('attempted')).toHaveLength(2);
});

it('renders exact no-match text safely and singleton lookup redirects with escaped identifiers', async () => {
  window.history.replaceState(null, '', '/tracking/search');
  workspace();
  const identifier = '<img src=x onerror=alert(1)>';
  fetchMock.mockResolvedValueOnce(
    reply({ ...fixture.search, identifier, items: [], total: 0, pages: 0 }),
  );
  fireEvent.change(screen.getByLabelText('Identifier'), {
    target: { value: identifier },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Search' }));
  expect(
    await screen.findByText(`The ${identifier} does not exist`),
  ).toBeInTheDocument();
  expect(document.querySelector('img')).toBeNull();
  fetchMock.mockResolvedValueOnce(
    reply({
      ...fixture.search,
      identifier: '000/A?#',
      field: 'reference',
      total: 1,
      items: [{ ...fixture.search.items[0], reference: '000/A?#' }],
    }),
  );
  fireEvent.change(screen.getByLabelText('Identifier'), {
    target: { value: '000/A?#' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Search' }));
  await screen.findByRole('heading', { name: 'Shipment 000DUP' });
  expect(window.location.pathname).toBe('/tracking/detail/000%2FA%3F%23');
});

it('resolves direct ambiguous URLs with a selector and rejects invalid context', async () => {
  window.history.replaceState(
    null,
    '',
    '/tracking/detail/000DUP?field=shipment_number',
  );
  workspace();
  await screen.findByRole('heading', { name: 'Choose a shipment' });
  expect(
    fetchMock.mock.calls.every(([path]) => String(path).includes('/search?')),
  ).toBe(true);
  fireEvent.click(screen.getAllByRole('link', { name: '000DUP' })[0]);
  await screen.findByRole('heading', { name: 'Shipment 000DUP' });
  expect(new URLSearchParams(window.location.search).get('shipment_id')).toBe(
    '101',
  );
  act(() => navigate('/tracking/detail/test?field=both&shipment_id=102'));
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Invalid shipment link',
  );
});

it('preserves Void and incomplete delivery, original addresses and offset times with failed image handling', async () => {
  window.history.replaceState(null, '', '/tracking/detail/x?shipment_id=102');
  fetchMock.mockResolvedValueOnce(
    reply({
      ...fixture.detail,
      status: 'Void',
      pod_name: null,
      pod_url: 'https://example.test/pod.png',
    }),
  );
  workspace();
  await screen.findByRole('heading', { name: 'Shipment 000DUP' });
  expect(screen.getByText('Void')).toBeInTheDocument();
  expect(
    screen.getByRole('heading', { name: 'Pickup address' }),
  ).toBeInTheDocument();
  expect(screen.getAllByText('Test City, TS 00123')).toHaveLength(2);
  expect(screen.getAllByText('2026-10-20 16:45-07:00')).toHaveLength(2);
  fireEvent.error(
    screen.getByRole('img', { name: 'Latest proof of delivery' }),
  );
  expect(screen.getByText('POD image is unavailable.')).toBeInTheDocument();
  expect(screen.queryByText(/Map|Favorite/)).not.toBeInTheDocument();
});

it('shows retry/empty states, rejects malformed DTOs and ignores late request completions', async () => {
  let rows = 0;
  let finish!: (response: Response) => void;
  fetchMock.mockImplementation(async (input) => {
    if (String(input).endsWith('/areas')) return reply(fixture.areas);
    rows += 1;
    if (rows === 1) return reply({ message: 'Queries unavailable' }, 503);
    if (rows === 2)
      return reply({ ...fixture.tracking, items: [], total: 0, pages: 0 });
    if (rows === 3)
      return new Promise((resolve) => {
        finish = resolve;
      });
    return reply({ bogus: true });
  });
  workspace();
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Queries unavailable',
  );
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
  await screen.findByRole('heading', { name: 'No shipments found' });
  fireEvent.change(screen.getByRole('combobox', { name: 'Status' }), {
    target: { value: 'delivered' },
  });
  await waitFor(() => expect(rows).toBe(3));
  fireEvent.change(screen.getByLabelText('Exceptions'), {
    target: { value: 'returned' },
  });
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'unexpected shipment data',
  );
  await act(async () => {
    finish(reply(fixture.tracking));
  });
  expect(screen.getByRole('alert')).toHaveTextContent(
    'unexpected shipment data',
  );
  expect(screen.queryByText('000REF1')).not.toBeInTheDocument();
});

it('hides administrator mutations for users and resets Enable on remount', async () => {
  window.history.replaceState(null, '', '/areas');
  const mounted = workspace('user');
  await screen.findByRole('heading', { name: 'west' });
  expect(
    screen.queryByRole('button', { name: 'Add area' }),
  ).not.toBeInTheDocument();
  expect(screen.queryByLabelText('Enable editing')).not.toBeInTheDocument();
  mounted.unmount();
  const admin = workspace();
  await screen.findByRole('heading', { name: 'west' });
  expect(screen.getByLabelText('Enable editing')).not.toBeChecked();
  fireEvent.click(screen.getByLabelText('Enable editing'));
  expect(screen.getByRole('button', { name: 'Edit west' })).toBeInTheDocument();
  admin.unmount();
  workspace();
  await screen.findByRole('heading', { name: 'west' });
  expect(screen.getByLabelText('Enable editing')).not.toBeChecked();
});

it('creates/restores, renames/no-ops, deletes and refreshes shared areas with guarded mutations', async () => {
  window.history.replaceState(null, '', '/areas');
  workspace();
  await screen.findByRole('heading', { name: 'west' });
  fireEvent.click(screen.getByRole('button', { name: 'Add area' }));
  fireEvent.change(screen.getByLabelText('Area name'), {
    target: { value: 'WEST' },
  });
  fetchMock.mockResolvedValueOnce(
    reply({ message: 'west already exist' }, 400),
  );
  fireEvent.click(screen.getByRole('button', { name: 'Save area' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'west already exist',
  );
  fetchMock.mockResolvedValueOnce(reply({ id: 1, name: 'west' }));
  fireEvent.click(screen.getByRole('button', { name: 'Save area' }));
  await screen.findByText('Area saved: west');
  await screen.findByRole('heading', { name: 'west' });
  expect(
    fetchMock.mock.calls.some(
      ([url, options]) => url === '/v1/area' && options?.method === 'POST',
    ),
  ).toBe(true);
  fireEvent.click(screen.getByLabelText('Enable editing'));
  fireEvent.click(screen.getByRole('button', { name: 'Edit west' }));
  expect(screen.getByLabelText('Area name')).toHaveValue('west');
  fetchMock.mockResolvedValueOnce(reply({ id: 1, name: 'west' }));
  fireEvent.click(screen.getByRole('button', { name: 'Save area' }));
  await waitFor(() =>
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument(),
  );
  await screen.findByRole('button', { name: 'Delete west' });
  expect(
    fetchMock.mock.calls.some(
      ([url, options]) =>
        url === '/v1/area/1' &&
        options?.method === 'PUT' &&
        options.headers &&
        'X-Requested-With' in options.headers,
    ),
  ).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Delete west' }));
  fetchMock.mockResolvedValueOnce(reply({ message: 'Area deleted' }));
  fireEvent.click(
    within(screen.getByRole('dialog')).getByRole('button', {
      name: 'Delete area',
    }),
  );
  await screen.findByText('Area deleted');
  expect(
    fetchMock.mock.calls.some(
      ([url, options]) => url === '/v1/area/1' && options?.method === 'DELETE',
    ),
  ).toBe(true);
});

it('leaves a failed area mutation retryable and prevents repeated submits or closing while pending', async () => {
  window.history.replaceState(null, '', '/areas');
  workspace();
  await screen.findByRole('heading', { name: 'west' });
  fireEvent.click(screen.getByRole('button', { name: 'Add area' }));
  fireEvent.change(screen.getByLabelText('Area name'), {
    target: { value: 'new' },
  });
  let finish!: (response: Response) => void;
  fetchMock.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const form = screen
    .getByRole('button', { name: 'Save area' })
    .closest('form')!;
  fireEvent.submit(form);
  fireEvent.submit(form);
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(screen.getByRole('button', { name: 'Saving…' })).toBeDisabled();
  expect(screen.getByRole('dialog')).toBeInTheDocument();
  expect(
    fetchMock.mock.calls.filter(([url]) => url === '/v1/area'),
  ).toHaveLength(1);
  finish(reply({ message: 'Administrator required' }, 403));
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Administrator required',
  );
  expect(screen.getByRole('button', { name: 'Save area' })).not.toBeDisabled();
});

it('clears protected content immediately on query 401', async () => {
  fetchMock.mockImplementation(async (input) =>
    String(input).endsWith('/session')
      ? reply({
          ...fixture.session,
          expires_at: new Date(Date.now() + 3600000).toISOString(),
        })
      : reply({ message: 'Authentication required' }, 401),
  );
  render(<App />);
  expect(
    await screen.findByRole('button', { name: 'Sign in' }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole('heading', { name: 'Tracking' }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole('alert')).toHaveTextContent(
    'Your session has expired',
  );
});

it('clears old company data on a verified membership switch and ignores late responses', async () => {
  let switched = false;
  let finish!: (response: Response) => void;
  fetchMock.mockImplementation(async (input) => {
    const path = String(input);
    if (path.endsWith('/session'))
      return reply({
        ...fixture.session,
        expires_at: new Date(Date.now() + 3600000).toISOString(),
        ...(switched
          ? {
              company: { id: '9', name: 'Other shipper', slug: 'other' },
              role: 'user',
            }
          : {}),
      });
    if (path.endsWith('/areas')) return reply(fixture.areas);
    if (switched)
      return new Promise((resolve) => {
        finish = resolve;
      });
    return reply(fixture.tracking);
  });
  render(<App />);
  await screen.findByText('000REF1');
  switched = true;
  fireEvent(window, new Event('focus'));
  await screen.findByText('Other shipper');
  expect(screen.queryByText('000REF1')).not.toBeInTheDocument();
  await act(async () =>
    finish(reply({ ...fixture.tracking, items: [], total: 0, pages: 0 })),
  );
  await screen.findByRole('heading', { name: 'No shipments found' });
});

it('retries failed area options and traps modal keyboard focus', async () => {
  let first = true;
  fetchMock.mockImplementation(async (input) => {
    if (String(input).endsWith('/areas')) {
      if (first) {
        first = false;
        return reply({ message: 'Area options unavailable' }, 503);
      }
      return reply(fixture.areas);
    }
    return reply(fixture.tracking);
  });
  workspace();
  await screen.findByText('000REF1');
  fireEvent.click(screen.getByText('Areas', { selector: 'summary' }));
  fireEvent.click(screen.getByRole('button', { name: 'Reload areas' }));
  await screen.findByLabelText('west');
  fireEvent.click(screen.getByRole('button', { name: /Oct 20, 2026/ }));
  const dialog = screen.getByRole('dialog');
  const apply = within(dialog).getByRole('button', { name: 'Apply' });
  apply.focus();
  fireEvent.keyDown(apply, { key: 'Tab' });
  expect(within(dialog).getByRole('button', { name: 'Today' })).toHaveFocus();
  fireEvent.keyDown(document.activeElement!, { key: 'Tab', shiftKey: true });
  expect(apply).toHaveFocus();
});

it('retains Tracking filters across navigation and handles browser history', async () => {
  workspace();
  await screen.findByText('000REF1');
  fireEvent.change(screen.getByLabelText('Exceptions'), {
    target: { value: 'attempted' },
  });
  await waitFor(() =>
    expect(urlAt().searchParams.get('exception')).toBe('attempted'),
  );
  fireEvent.click(screen.getByRole('link', { name: 'Search' }));
  expect(
    await screen.findByRole('heading', { name: 'Search' }),
  ).toBeInTheDocument();
  act(() => {
    window.history.replaceState(null, '', '/tracking');
    window.dispatchEvent(new PopStateEvent('popstate'));
  });
  await screen.findByText('000REF1');
  expect(screen.getByLabelText('Exceptions')).toHaveValue('attempted');
});

it('preserves dot-only identifiers instead of allowing URL path normalization', async () => {
  window.history.replaceState(null, '', '/tracking/search');
  workspace();
  fetchMock.mockResolvedValueOnce(
    reply({
      ...fixture.search,
      identifier: '..',
      field: 'reference',
      total: 1,
      items: [{ ...fixture.search.items[0], reference: '..' }],
    }),
  );
  fireEvent.change(screen.getByLabelText('Identifier'), {
    target: { value: '..' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Search' }));
  await screen.findByRole('heading', { name: 'Shipment 000DUP' });
  expect(window.location.pathname).toBe('/tracking/detail/%252E%252E');
  expect(new URLSearchParams(window.location.search).get('encoding')).toBe(
    'dot',
  );
  act(() =>
    navigate('/tracking/detail/%252E%252E?field=reference&encoding=dot'),
  );
  await screen.findByRole('heading', { name: 'Choose a shipment' });
  expect(urlAt().searchParams.get('identifier')).toBe('..');
});
