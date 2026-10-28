import { useEffect, useState, useSyncExternalStore } from 'react';
import { api, ApiError } from '../api';

export function navigate(href: string, replace = false) {
  window.history[replace ? 'replaceState' : 'pushState'](null, '', href);
  window.dispatchEvent(new PopStateEvent('popstate'));
}
function subscribe(callback: () => void) {
  window.addEventListener('popstate', callback);
  return () => window.removeEventListener('popstate', callback);
}
export function useLocation() {
  return useSyncExternalStore(
    subscribe,
    () => window.location.pathname + window.location.search,
  );
}
export type AuthFailure = () => void;
export function useResource<T>(
  path: string | null,
  parse: (value: unknown) => T,
  onExpired: AuthFailure,
  revision = 0,
): { data?: T; error?: string } {
  const key = `${path}:${revision}`;
  const [state, setState] = useState<{ key: string; data?: T; error?: string }>(
    { key: '' },
  );
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    void api(path, undefined, { signal: controller.signal })
      .then(parse)
      .then((data) => {
        if (!controller.signal.aborted) setState({ key, data });
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && error.status === 401) onExpired();
        else
          setState({
            key,
            error:
              error instanceof Error
                ? error.message
                : 'Unable to load shipments.',
          });
      });
    return () => controller.abort();
  }, [path, key, parse, onExpired]);
  return state.key === key ? state : {};
}
