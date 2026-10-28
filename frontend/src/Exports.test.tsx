import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ExportButton, ExportCenter } from './shipments/exports';
import { parseExports } from './shipments/exportContracts';
import { initialFilters } from './shipments/contracts';

const id = '00000000-0000-4000-8000-000000000001';
const ready = {
  id,
  state: 'ready',
  created_at: '2026-10-28T12:00:00Z',
  url: `/v1/exports/${id}/download`,
  row_count: 42,
  reason_code: null,
};
const reply = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
const fetchMock = vi.fn<typeof fetch>();
const expired = vi.fn();
class Source {
  static instances: Source[] = [];
  listeners = new Map<string, EventListener>();
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn();
  constructor(public url: string) {
    Source.instances.push(this);
  }
  addEventListener(name: string, callback: EventListener) {
    this.listeners.set(name, callback);
  }
  send(name: string, value: unknown) {
    this.listeners.get(name)?.(
      new MessageEvent(name, { data: JSON.stringify(value) }),
    );
  }
}
beforeEach(() => {
  fetchMock.mockReset();
  expired.mockReset();
  Source.instances = [];
  vi.stubGlobal('fetch', fetchMock);
  vi.stubGlobal('EventSource', Source);
  fetchMock.mockResolvedValue(reply({ items: [] }));
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it('requests all committed filters with no pagination and exact acknowledgment', async () => {
  fetchMock.mockResolvedValue(
    reply({ message: 'we start to process data' }, 202),
  );
  render(
    <ExportButton
      filters={{
        ...initialFilters,
        page: 7,
        length: 100,
        account: '0007',
        status: 'undelivered',
        exception: 'attempted',
        area: [1, 2],
        start_date: '2026-10-01',
        end_date: '2026-10-28',
      }}
      onExpired={expired}
    />,
  );
  fireEvent.click(screen.getByRole('button', { name: 'Export CSV' }));
  expect(await screen.findByRole('status')).toHaveTextContent(
    'we start to process data',
  );
  const url = new URL(String(fetchMock.mock.calls[0][0]), 'http://local');
  expect(url.searchParams.get('export')).toBe('1');
  expect(url.searchParams.has('page')).toBe(false);
  expect(url.searchParams.has('length')).toBe(false);
  expect(url.searchParams.getAll('area')).toEqual(['1', '2']);
  expect(url.searchParams.get('account')).toBe('0007');
  expect(url.searchParams.get('status')).toBe('undelivered');
  expect(url.searchParams.get('exception')).toBe('attempted');
  expect(url.searchParams.get('start_date')).toBe('2026-10-01');
  expect(fetchMock.mock.calls[0][1]?.headers).toMatchObject({
    'X-Requested-With': 'logistics-web',
  });
});

it('guards duplicate clicks and never announces readiness on acceptance', async () => {
  let resolve!: (value: Response) => void;
  fetchMock.mockImplementation(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
  );
  render(<ExportButton filters={initialFilters} onExpired={expired} />);
  fireEvent.click(screen.getByRole('button', { name: 'Export CSV' }));
  fireEvent.click(screen.getByRole('button', { name: 'Requesting export…' }));
  expect(fetchMock).toHaveBeenCalledTimes(1);
  await act(async () =>
    resolve(reply({ message: 'we start to process data' }, 202)),
  );
  expect(screen.queryByText('Click here to download')).not.toBeInTheDocument();
});

it('shows request failure and expires unauthorized sessions', async () => {
  fetchMock.mockResolvedValueOnce(
    reply({ message: 'Exports unavailable' }, 503),
  );
  render(<ExportButton filters={initialFilters} onExpired={expired} />);
  fireEvent.click(screen.getByRole('button', { name: 'Export CSV' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Exports unavailable',
  );
  fetchMock.mockResolvedValueOnce(
    reply({ message: 'Authentication required' }, 401),
  );
  fireEvent.click(screen.getByRole('button', { name: 'Export CSV' }));
  await waitFor(() => expect(expired).toHaveBeenCalledTimes(1));
});

it('recovers ready jobs on reload and dismisses durably', async () => {
  fetchMock
    .mockResolvedValueOnce(reply({ items: [ready] }))
    .mockResolvedValueOnce(reply({ message: 'Export dismissed' }));
  render(<ExportCenter onExpired={expired} />);
  const link = await screen.findByRole('link', {
    name: 'Click here to download',
  });
  expect(link).toHaveAttribute('href', ready.url);
  expect(link).toHaveAttribute('download');
  expect(Source.instances[0].url).toBe('/v1/exports/events');
  fireEvent.click(screen.getByRole('button', { name: /Dismiss export/ }));
  await waitFor(() =>
    expect(screen.queryByRole('link')).not.toBeInTheDocument(),
  );
  expect(fetchMock.mock.calls[1][0]).toBe(`/v1/exports/${id}/dismiss`);
  expect(fetchMock.mock.calls[1][1]?.method).toBe('POST');
  // An older in-flight snapshot must not resurrect a dismissed toast.
  act(() => Source.instances[0].send('exports', { items: [ready] }));
  expect(screen.queryByRole('link')).not.toBeInTheDocument();
});

it('changes pending to one ready toast over SSE and deduplicates replay', async () => {
  render(<ExportCenter onExpired={expired} />);
  await waitFor(() => expect(Source.instances).toHaveLength(1));
  act(() =>
    Source.instances[0].send('exports', {
      items: [{ ...ready, state: 'pending', url: null, row_count: null }],
    }),
  );
  expect(screen.getByText('Preparing your CSV export…')).toBeInTheDocument();
  expect(screen.queryByRole('link')).not.toBeInTheDocument();
  act(() => Source.instances[0].send('exports', { items: [ready] }));
  act(() => Source.instances[0].send('exports', { items: [ready] }));
  expect(
    screen.getAllByRole('link', { name: 'Click here to download' }),
  ).toHaveLength(1);
});

it('recovers after reconnect without fabricating a ready link on failure', async () => {
  render(<ExportCenter onExpired={expired} />);
  await waitFor(() => expect(Source.instances).toHaveLength(1));
  act(() => Source.instances[0].onerror?.());
  expect(screen.getByText(/jobs are saved/)).toBeInTheDocument();
  fetchMock.mockResolvedValueOnce(reply({ items: [ready] }));
  act(() => Source.instances[0].onopen?.());
  await screen.findByRole('link');
  act(() =>
    Source.instances[0].send('exports', {
      items: [
        {
          ...ready,
          state: 'failed',
          url: null,
          row_count: null,
          reason_code: 'export_unavailable',
        },
      ],
    }),
  );
  expect(screen.getByText(/Export failed/)).toBeInTheDocument();
  expect(screen.queryByRole('link')).not.toBeInTheDocument();
});

it('handles invalid events, retry and server session expiry', async () => {
  render(<ExportCenter onExpired={expired} />);
  await waitFor(() => expect(Source.instances).toHaveLength(1));
  act(() =>
    Source.instances[0].send('exports', {
      items: [{ ...ready, url: 'https://bad.test/file' }],
    }),
  );
  expect(screen.getByText(/Unable to read export updates/)).toBeInTheDocument();
  fetchMock.mockResolvedValueOnce(reply({ items: [ready] }));
  fireEvent.click(screen.getByRole('button', { name: 'Refresh exports' }));
  await screen.findByRole('link');
  act(() => Source.instances[1].send('session-expired', {}));
  expect(expired).toHaveBeenCalledTimes(1);
  expect(Source.instances[1].close).toHaveBeenCalled();
});

it('aborts late recovery and closes streams on workspace change', async () => {
  let resolve!: (value: Response) => void;
  fetchMock.mockImplementationOnce(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
  );
  const mounted = render(<ExportCenter onExpired={expired} />);
  await waitFor(() => expect(Source.instances).toHaveLength(1));
  mounted.unmount();
  expect(Source.instances[0].close).toHaveBeenCalled();
  expect(fetchMock.mock.calls[0][1]?.signal?.aborted).toBe(true);
  await act(async () => resolve(reply({ items: [ready] })));
  expect(screen.queryByRole('link')).not.toBeInTheDocument();
});

it.each([
  { items: [{ ...ready, url: 'javascript:alert(1)' }] },
  { items: [ready, ready] },
  { items: [{ ...ready, row_count: -1 }] },
  { items: [{ ...ready, state: 'pending' }] },
  { items: [{ ...ready, id: '../outside' }] },
  { items: [{ ...ready, created_at: 'bad' }] },
])('rejects malformed or unsafe export DTOs', (value) => {
  expect(() => parseExports(value)).toThrow();
});

it('recovers durable readiness and reconnects when a proxy silently stalls SSE', async () => {
  vi.useFakeTimers();
  render(<ExportCenter onExpired={expired} />);
  await act(async () => {
    await Promise.resolve();
  });
  expect(Source.instances).toHaveLength(1);
  fetchMock.mockResolvedValueOnce(reply({ items: [ready] }));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(15000);
  });
  expect(Source.instances[0].close).toHaveBeenCalled();
  expect(Source.instances).toHaveLength(2);
  expect(
    screen.getByRole('link', { name: 'Click here to download' }),
  ).toBeInTheDocument();
});

it('keeps a healthy heartbeat stream open', async () => {
  vi.useFakeTimers();
  render(<ExportCenter onExpired={expired} />);
  await act(async () => {
    await Promise.resolve();
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10000);
  });
  act(() => Source.instances[0].send('heartbeat', {}));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10000);
  });
  expect(Source.instances).toHaveLength(1);
  expect(Source.instances[0].close).not.toHaveBeenCalled();
});
