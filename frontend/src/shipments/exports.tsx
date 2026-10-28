import { useEffect, useRef, useState } from 'react';
import { api, ApiError } from '../api';
import type { Filters } from './contracts';
import { trackingPath } from './contracts';
import type { AuthFailure } from './hooks';

import { parseExports, type ExportJob } from './exportContracts';

export function ExportButton({
  filters,
  onExpired,
}: {
  filters: Filters;
  onExpired: AuthFailure;
}) {
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const active = useRef(false);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  async function submit() {
    if (active.current) return;
    active.current = true;
    setPending(true);
    setError('');
    setMessage('');
    const abort = new AbortController();
    controller.current = abort;
    const url = new URL(trackingPath(filters), 'http://local/');
    url.searchParams.delete('page');
    url.searchParams.delete('length');
    url.searchParams.set('export', '1');
    try {
      const result = await api(url.pathname.slice(1) + url.search, undefined, {
        signal: abort.signal,
      });
      if (
        !result ||
        typeof result !== 'object' ||
        !('message' in result) ||
        result.message !== 'we start to process data'
      )
        throw new Error(
          'The export response was unexpected. Check export updates before trying again.',
        );
      if (!abort.signal.aborted) {
        setMessage(result.message);
        window.dispatchEvent(new Event('exports-requested'));
      }
    } catch (failure) {
      if (!abort.signal.aborted) {
        if (failure instanceof ApiError && failure.status === 401) onExpired();
        else
          setError(
            failure instanceof Error
              ? failure.message
              : 'Unable to request export.',
          );
      }
    } finally {
      active.current = false;
      if (!abort.signal.aborted) setPending(false);
    }
  }
  return (
    <div className="export-request">
      <button
        className="button-quiet"
        disabled={pending}
        onClick={() => void submit()}
      >
        {pending ? 'Requesting export…' : 'Export CSV'}
      </button>
      {message && <p role="status">{message}</p>}
      {error && <p role="alert">{error}</p>}
    </div>
  );
}

export function ExportCenter({ onExpired }: { onExpired: AuthFailure }) {
  const [items, setItems] = useState<ExportJob[]>([]);
  const [error, setError] = useState('');
  const [offline, setOffline] = useState(false);
  const [revision, setRevision] = useState(0);
  const [pending, setPending] = useState<string | null>(null);
  const dismissed = useRef(new Set<string>());
  const dismissAbort = useRef<AbortController | null>(null);
  useEffect(() => () => dismissAbort.current?.abort(), []);
  useEffect(() => {
    const controller = new AbortController();
    let generation = 0;
    let lastFrame = Date.now();
    const apply = (value: unknown) => {
      if (!controller.signal.aborted) {
        setItems(
          parseExports(value).filter((item) => !dismissed.current.has(item.id)),
        );
        setError('');
      }
    };
    const recover = () => {
      const request = ++generation;
      void api('exports', undefined, { signal: controller.signal })
        .then((value) => {
          if (request === generation) apply(value);
        })
        .catch((failure) => {
          if (controller.signal.aborted || request !== generation) return;
          if (failure instanceof ApiError && failure.status === 401)
            onExpired();
          else
            setError(
              'Export updates are unavailable. Refresh exports to recover your files.',
            );
        });
    };
    recover();
    const source =
      typeof EventSource === 'undefined'
        ? null
        : new EventSource('/v1/exports/events');
    if (source) {
      source.addEventListener('exports', (event) => {
        if (controller.signal.aborted) return;
        lastFrame = Date.now();
        try {
          ++generation;
          apply(JSON.parse((event as MessageEvent<string>).data));
          setOffline(false);
        } catch {
          if (!controller.signal.aborted)
            setError('Unable to read export updates. Please refresh exports.');
        }
      });
      source.addEventListener('heartbeat', () => {
        lastFrame = Date.now();
      });
      source.addEventListener('session-expired', () => {
        if (!controller.signal.aborted) {
          source.close();
          onExpired();
        }
      });
      source.addEventListener('unavailable', () => {
        if (!controller.signal.aborted) setOffline(true);
      });
      source.onopen = () => {
        if (!controller.signal.aborted) {
          lastFrame = Date.now();
          setOffline(false);
          recover();
        }
      };
      source.onerror = () => {
        if (!controller.signal.aborted) setOffline(true);
      };
    }
    const watchdog = source
      ? window.setInterval(() => {
          if (!controller.signal.aborted && Date.now() - lastFrame >= 15000) {
            source.close();
            setOffline(true);
            setRevision((value) => value + 1);
          }
        }, 5000)
      : undefined;
    const visible = () => {
      if (document.visibilityState === 'visible') recover();
    };
    window.addEventListener('exports-requested', recover);
    window.addEventListener('focus', recover);
    document.addEventListener('visibilitychange', visible);
    return () => {
      controller.abort();
      window.clearInterval(watchdog);
      source?.close();
      window.removeEventListener('exports-requested', recover);
      window.removeEventListener('focus', recover);
      document.removeEventListener('visibilitychange', visible);
    };
  }, [onExpired, revision]);
  async function dismiss(id: string) {
    if (dismissAbort.current) return;
    const controller = new AbortController();
    dismissAbort.current = controller;
    setPending(id);
    try {
      await api(`exports/${id}/dismiss`, {}, { signal: controller.signal });
      if (!controller.signal.aborted) {
        dismissed.current.add(id);
        setItems((value) => value.filter((item) => item.id !== id));
      }
    } catch (failure) {
      if (!controller.signal.aborted) {
        if (failure instanceof ApiError && failure.status === 401) onExpired();
        else setError('Unable to dismiss export. Please try again.');
      }
    } finally {
      if (!controller.signal.aborted) setPending(null);
      dismissAbort.current = null;
    }
  }
  return (
    <aside className="export-center" aria-label="Export updates">
      {(error || offline) && (
        <p>
          {error || 'Live export updates disconnected. Your jobs are saved.'}
        </p>
      )}
      {(error || offline || items.length > 0) && (
        <button
          className="button-quiet"
          onClick={() => setRevision((value) => value + 1)}
        >
          Refresh exports
        </button>
      )}
      <div aria-live="polite" aria-relevant="additions text">
        {items.map((item) => (
          <div className={`export-toast export-${item.state}`} key={item.id}>
            {item.state === 'ready' ? (
              <>
                <a href={item.url!} download>
                  Click here to download
                </a>
                <span>
                  {item.row_count} packages ·{' '}
                  {new Date(item.created_at).toLocaleString()}
                </span>
              </>
            ) : item.state === 'failed' ? (
              <p>Export failed. Request it again from Tracking.</p>
            ) : (
              <p>
                {item.state === 'retry_wait'
                  ? 'Export delayed; retrying automatically.'
                  : 'Preparing your CSV export…'}
              </p>
            )}
            {(item.state === 'ready' || item.state === 'failed') && (
              <button
                className="button-quiet"
                disabled={pending !== null}
                onClick={() => void dismiss(item.id)}
                aria-label={`Dismiss export from ${item.created_at}`}
              >
                {pending === item.id ? 'Dismissing…' : 'Dismiss'}
              </button>
            )}
          </div>
        ))}
      </div>
    </aside>
  );
}
