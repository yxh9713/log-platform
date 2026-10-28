import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import App from './App';

const current = {
  id: '1',
  email: 'admin@paychex.example',
  role: 'administrator',
  company: { id: '2', name: 'Paychex', slug: 'paychex' },
  expires_at: new Date(Date.now() + 3600_000).toISOString(),
};
const fetchMock = vi.fn<typeof fetch>();
function reply(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
function anonymous() {
  fetchMock.mockResolvedValueOnce(
    reply({ message: 'Authentication required' }, 401),
  );
}
async function form() {
  render(<App />);
  await screen.findByRole('button', { name: 'Sign in' });
}
function fill() {
  fireEvent.change(screen.getByLabelText('Email'), {
    target: { value: 'admin@paychex.example' },
  });
  fireEvent.change(screen.getByLabelText('Password'), {
    target: { value: 'synthetic test password' },
  });
  fireEvent.change(screen.getByLabelText('Company slug'), {
    target: { value: 'paychex' },
  });
}
beforeEach(() => {
  vi.stubGlobal('fetch', (input: RequestInfo | URL, options?: RequestInit) => {
    if (String(input).startsWith('/v1/my-day'))
      return Promise.resolve(
        reply({
          report_date: '2026-10-28',
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
        }),
      );
    return fetchMock(input, options);
  });
  fetchMock.mockReset();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it('requires accessible email, password and company fields', async () => {
  anonymous();
  await form();
  expect(screen.getByLabelText('Email')).toHaveAttribute('type', 'email');
  expect(screen.getByLabelText('Password')).toHaveAttribute('type', 'password');
  expect(screen.getByLabelText('Company slug')).toHaveAttribute('required');
  fireEvent.submit(
    screen.getByRole('button', { name: 'Sign in' }).closest('form')!,
  );
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Enter your email, password and company slug.',
  );
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

it('logs in, checks session, signs out and stores no browser token', async () => {
  const storage = vi.spyOn(Storage.prototype, 'setItem');
  anonymous();
  await form();
  fill();
  fetchMock
    .mockResolvedValueOnce(reply({ token: 'synthetic-token' }))
    .mockResolvedValueOnce(reply(current));
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
  expect(
    await screen.findByRole('heading', { name: 'My Day' }),
  ).toBeInTheDocument();
  expect(screen.getByText('Administrator')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Add area' })).toBeInTheDocument();
  expect(fetchMock).toHaveBeenNthCalledWith(
    2,
    '/v1/login',
    expect.objectContaining({
      method: 'POST',
      credentials: 'same-origin',
      body: JSON.stringify({
        email: 'admin@paychex.example',
        password: 'synthetic test password',
        slug: 'paychex',
      }),
    }),
  );
  expect(storage).not.toHaveBeenCalled();
  fetchMock.mockResolvedValueOnce(reply({ message: 'Signed out' }));
  fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));
  expect(
    await screen.findByRole('button', { name: 'Sign in' }),
  ).toBeInTheDocument();
  expect(screen.getByLabelText('Password')).toHaveValue('');
  storage.mockRestore();
});

it('restores a user session without administrator affordances', async () => {
  fetchMock.mockResolvedValueOnce(reply({ ...current, role: 'user' }));
  render(<App />);
  expect(await screen.findByText('User')).toBeInTheDocument();
  expect(
    screen.queryByRole('button', { name: 'Add area' }),
  ).not.toBeInTheDocument();
  expect(screen.queryByLabelText('Password')).not.toBeInTheDocument();
});

it('shows generic invalid credentials and clears the password', async () => {
  anonymous();
  await form();
  fill();
  fetchMock.mockResolvedValueOnce(
    reply({ message: 'Invalid credentials' }, 401),
  );
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Invalid credentials',
  );
  await waitFor(() =>
    expect(screen.getByLabelText('Password')).toHaveValue(''),
  );
  expect(screen.getByRole('alert')).toHaveFocus();
});

it('prevents duplicate submissions while loading', async () => {
  anonymous();
  await form();
  fill();
  let finish!: (response: Response) => void;
  fetchMock.mockReturnValueOnce(
    new Promise<Response>((resolve) => {
      finish = resolve;
    }),
  );
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
  expect(screen.getByRole('button', { name: 'Signing in…' })).toBeDisabled();
  fireEvent.submit(
    screen.getByRole('button', { name: 'Signing in…' }).closest('form')!,
  );
  expect(fetchMock).toHaveBeenCalledTimes(2);
  finish(
    reply(
      { message: 'Too many login attempts. Try again in one minute.' },
      429,
    ),
  );
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Too many login attempts',
  );
});

it('provides a retry when session restoration is offline', async () => {
  fetchMock.mockRejectedValueOnce(new Error('network'));
  render(<App />);
  expect(
    await screen.findByRole('heading', { name: 'Connection interrupted' }),
  ).toBeInTheDocument();
  anonymous();
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
  expect(
    await screen.findByRole('button', { name: 'Sign in' }),
  ).toBeInTheDocument();
});

it('retains the workspace if logout cannot reach the service', async () => {
  fetchMock.mockResolvedValueOnce(reply(current));
  render(<App />);
  await screen.findByRole('button', { name: 'Sign out' });
  fetchMock.mockRejectedValueOnce(new Error('offline'));
  fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Unable to reach the service',
  );
  expect(screen.getByRole('heading', { name: 'My Day' })).toBeInTheDocument();
});

it('returns to sign in when a focused session was revoked', async () => {
  fetchMock.mockResolvedValueOnce(reply(current));
  render(<App />);
  await screen.findByRole('button', { name: 'Sign out' });
  anonymous();
  fireEvent(window, new Event('focus'));
  expect(
    await screen.findByRole('button', { name: 'Sign in' }),
  ).toBeInTheDocument();
});

it('rejects malformed session responses', async () => {
  fetchMock.mockResolvedValueOnce(reply({ ...current, role: 'superuser' }));
  render(<App />);
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'unexpected session',
  );
  expect(
    screen.queryByRole('button', { name: 'Sign out' }),
  ).not.toBeInTheDocument();
});

it('expires the visible workspace when its session lifetime ends', async () => {
  fetchMock.mockResolvedValueOnce(
    reply({ ...current, expires_at: new Date(Date.now() + 500).toISOString() }),
  );
  render(<App />);
  await screen.findByRole('button', { name: 'Sign out' });
  expect(
    await screen.findByRole('button', { name: 'Sign in' }),
  ).toBeInTheDocument();
  expect(screen.getByRole('alert')).toHaveTextContent(
    'Your session has expired',
  );
});

it('ignores a stale session response after signing out', async () => {
  fetchMock.mockResolvedValueOnce(reply(current));
  render(<App />);
  await screen.findByRole('button', { name: 'Sign out' });
  let finish!: (response: Response) => void;
  fetchMock.mockReturnValueOnce(
    new Promise<Response>((resolve) => {
      finish = resolve;
    }),
  );
  fireEvent(window, new Event('focus'));
  fetchMock.mockResolvedValueOnce(reply({ message: 'Signed out' }));
  fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));
  await screen.findByRole('button', { name: 'Sign in' });
  finish(reply(current));
  await waitFor(() =>
    expect(
      screen.queryByRole('button', { name: 'Sign out' }),
    ).not.toBeInTheDocument(),
  );
});
