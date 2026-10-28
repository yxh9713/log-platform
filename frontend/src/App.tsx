import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from 'react';
import { api, ApiError, parseSession, type Session } from './api';
import Workspace from './Workspace';

function Brand() {
  return (
    <a className="brand" href="/" aria-label="Logistics Platform home">
      <span className="brand-mark" aria-hidden="true">
        ↗
      </span>
      Logistics<span className="brand-light">Platform</span>
    </a>
  );
}

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [phase, setPhase] = useState<
    'checking' | 'anonymous' | 'authenticated' | 'unavailable'
  >('checking');
  const [email, setEmail] = useState('');
  const [slug, setSlug] = useState('');
  const [password, setPassword] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const errorRef = useRef<HTMLParagraphElement>(null);
  const inFlight = useRef(false);
  const revision = useRef(0);

  const restore = useCallback(async () => {
    if (inFlight.current) return;
    const requestId = ++revision.current;
    try {
      const current = parseSession(await api('session'));
      if (requestId !== revision.current) return;
      setSession(current);
      setPhase('authenticated');
    } catch (failure) {
      if (requestId !== revision.current) return;
      setSession(null);
      if (failure instanceof ApiError && failure.status === 401) {
        setPhase('anonymous');
      } else {
        setPhase('unavailable');
        setError(
          failure instanceof Error
            ? failure.message
            : 'Unable to check your session.',
        );
      }
    }
  }, []);

  useEffect(() => {
    void restore();
    const check = () => {
      void restore();
    };
    window.addEventListener('focus', check);
    return () => window.removeEventListener('focus', check);
  }, [restore]);

  useEffect(() => {
    if (!session) return;
    const timer = window.setTimeout(
      () => {
        setSession(null);
        setPhase('anonymous');
        setError('Your session has expired. Please sign in again.');
      },
      Math.max(0, Date.parse(session.expires_at) - Date.now()),
    );
    return () => window.clearTimeout(timer);
  }, [session]);

  useEffect(() => {
    errorRef.current?.focus();
  }, [error]);

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (inFlight.current) return;
    if (!email.trim() || !slug.trim() || !password.trim()) {
      setError('Enter your email, password and company slug.');
      return;
    }
    inFlight.current = true;
    revision.current += 1;
    setPending(true);
    setError('');
    try {
      // The token in the approved response is intentionally not persisted by JS.
      await api('login', { email: email.trim(), password, slug: slug.trim() });
      const current = parseSession(await api('session'));
      setSession(current);
      setPhase('authenticated');
    } catch (failure) {
      setError(
        failure instanceof Error ? failure.message : 'Unable to sign in.',
      );
    } finally {
      setPassword('');
      setPending(false);
      inFlight.current = false;
    }
  }

  async function signOut() {
    if (inFlight.current) return;
    inFlight.current = true;
    revision.current += 1;
    setPending(true);
    setError('');
    try {
      await api('logout', {});
      setSession(null);
      setPhase('anonymous');
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 401) {
        setSession(null);
        setPhase('anonymous');
      } else {
        setError(
          failure instanceof Error
            ? failure.message
            : 'Unable to sign out. Please try again.',
        );
      }
    } finally {
      inFlight.current = false;
      setPending(false);
    }
  }

  const expireWorkspace = useCallback(() => {
    revision.current += 1;
    setSession(null);
    setPhase('anonymous');
    setError('Your session has expired. Please sign in again.');
  }, []);

  const notice = error ? (
    <p className="notice" role="alert" tabIndex={-1} ref={errorRef}>
      {error}
    </p>
  ) : null;

  if (phase === 'checking' || phase === 'unavailable') {
    return (
      <main className="connection">
        <Brand />
        <h1>
          {phase === 'checking'
            ? 'Opening your workspace…'
            : 'Connection interrupted'}
        </h1>
        {phase === 'checking' ? (
          <p role="status">Checking your session.</p>
        ) : (
          <>
            {notice}
            <button
              onClick={() => {
                setError('');
                setPhase('checking');
                void restore();
              }}
            >
              Try again
            </button>
          </>
        )}
      </main>
    );
  }

  if (phase === 'authenticated' && session) {
    return (
      <Workspace
        key={`${session.company.id}:${session.id}:${session.role}`}
        session={session}
        pending={pending}
        signOut={() => {
          void signOut();
        }}
        notice={notice}
        onExpired={expireWorkspace}
      />
    );
  }

  return (
    <div className="login-page">
      <a className="skip-link" href="#sign-in">
        Skip to sign in
      </a>
      <section className="login-story" aria-label="Logistics Platform">
        <Brand />
        <div className="story-content">
          <span className="story-kicker">THE SHIPPER WORKSPACE</span>
          <h1>
            Every package.
            <br />
            One clear view.
          </h1>
          <p>
            A single place for your team to follow shipments across your
            carriers.
          </p>
          <div className="route-art" aria-hidden="true">
            <span />
            <i />
            <span />
            <i />
            <span />
          </div>
        </div>
        <p className="story-footer">
          Built around your company. Connected across carriers.
        </p>
      </section>
      <main className="login-panel" id="sign-in">
        <div className="login-form-wrap">
          <p className="eyebrow">WELCOME BACK</p>
          <h2>Sign in to your workspace</h2>
          <p className="muted">
            Use the account provided by your administrator.
          </p>
          <form
            onSubmit={(event) => {
              void signIn(event);
            }}
            aria-busy={pending}
          >
            <label htmlFor="email">Email</label>
            <input
              id="email"
              name="email"
              type="email"
              autoComplete="username"
              required
              maxLength={320}
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              disabled={pending}
            />
            <label htmlFor="password">Password</label>
            <input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              maxLength={1024}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              disabled={pending}
            />
            <label htmlFor="slug">Company slug</label>
            <input
              id="slug"
              name="slug"
              type="text"
              autoComplete="organization"
              autoCapitalize="none"
              spellCheck={false}
              required
              maxLength={64}
              aria-describedby="slug-help"
              value={slug}
              onChange={(event) => setSlug(event.target.value)}
              disabled={pending}
            />
            <p className="field-hint" id="slug-help">
              Your company’s short name, such as paychex.
            </p>
            {notice}
            <button className="submit-button" type="submit" disabled={pending}>
              {pending ? 'Signing in…' : 'Sign in'}
              <span aria-hidden="true">→</span>
            </button>
          </form>
          <p className="access-note">
            Need access? Contact your company administrator.
          </p>
        </div>
        <footer>
          Logistics Platform <span>Shipper portal</span>
        </footer>
      </main>
    </div>
  );
}
