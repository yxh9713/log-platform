import { type AuthFailure } from './hooks';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api, ApiError } from '../api';
import { parseArea, type Area } from './contracts';
import { ErrorNotice, Modal } from './shared';
import { Breakdown } from './charts';
import type { AreaStats } from './dayContracts';
export default function Areas({
  areas,
  error,
  administrator,
  refresh,
  onExpired,
  statistics,
  dashboard = false,
}: {
  areas?: Area[];
  error?: string;
  administrator: boolean;
  refresh: () => void;
  onExpired: AuthFailure;
  statistics?: AreaStats[];
  dashboard?: boolean;
}) {
  const statsById = new Map(statistics?.map((item) => [item.id, item]));
  const [enabled, setEnabled] = useState(false);
  const [dialog, setDialog] = useState<{
    kind: 'add' | 'edit' | 'delete';
    area?: Area;
  } | null>(null);
  const [name, setName] = useState('');
  const [failure, setFailure] = useState('');
  const [notice, setNotice] = useState('');
  const [pending, setPending] = useState(false);
  const busy = useRef(false);
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  function open(kind: 'add' | 'edit' | 'delete', area?: Area) {
    setDialog({ kind, area });
    setName(area?.name ?? '');
    setFailure('');
    setNotice('');
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!dialog || busy.current || !administrator) return;
    busy.current = true;
    setPending(true);
    setFailure('');
    try {
      const path = dialog.kind === 'add' ? 'area' : `area/${dialog.area!.id}`;
      const value = await api(
        path,
        dialog.kind === 'delete' ? undefined : { name },
        {
          method:
            dialog.kind === 'add'
              ? 'POST'
              : dialog.kind === 'edit'
                ? 'PUT'
                : 'DELETE',
        },
      );
      if (!active.current) return;
      if (dialog.kind === 'delete') {
        if (
          !value ||
          typeof value !== 'object' ||
          !('message' in value) ||
          value.message !== 'Area deleted'
        )
          throw new Error(
            'Unexpected area response. Refresh areas before retrying.',
          );
        setNotice('Area deleted');
      } else {
        const saved = parseArea(value);
        setNotice(`Area saved: ${saved.name}`);
      }
      setDialog(null);
      refresh();
    } catch (error) {
      if (!active.current) return;
      if (error instanceof ApiError && error.status === 401) onExpired();
      else
        setFailure(
          error instanceof Error ? error.message : 'Unable to save area.',
        );
    } finally {
      busy.current = false;
      if (active.current) setPending(false);
    }
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">YOUR COMPANY</p>
          {dashboard ? <h2>Areas</h2> : <h1>Areas</h1>}
          <p className="muted">Shared labels for your team’s shipments.</p>
        </div>
        {administrator && <button onClick={() => open('add')}>Add area</button>}
      </div>
      {administrator ? (
        <label className="enable-areas">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(event) => setEnabled(event.target.checked)}
          />
          Enable editing
        </label>
      ) : (
        <p className="muted">
          Company administrators manage areas. Everyone can use them to filter
          shipments.
        </p>
      )}
      {notice && (
        <p role="status" className="success-notice">
          {notice}
        </p>
      )}
      {error && !dashboard && <ErrorNotice message={error} retry={refresh} />}
      {!areas && !error && <p role="status">Loading areas…</p>}
      {areas && (
        <div className="area-grid">
          {areas.map((area) => (
            <section className="panel area-card" key={area.id}>
              {dashboard ? <h3>{area.name}</h3> : <h2>{area.name}</h2>}
              {statsById.has(area.id) && (
                <>
                  <Breakdown
                    value={statsById.get(area.id)!}
                    label={`${area.name} shipment status`}
                  />
                  <p className="area-otp">
                    <strong>{statsById.get(area.id)!.otp.toFixed(2)}%</strong>{' '}
                    On time
                  </p>
                </>
              )}
              {administrator && enabled && (
                <div>
                  <button
                    className="button-quiet"
                    aria-label={`Edit ${area.name}`}
                    onClick={() => open('edit', area)}
                  >
                    ✎ Edit
                  </button>
                  <button
                    className="button-quiet"
                    aria-label={`Delete ${area.name}`}
                    onClick={() => open('delete', area)}
                  >
                    ⌫ Delete
                  </button>
                </div>
              )}
            </section>
          ))}
          {areas.length === 0 && (
            <p className="empty-state">
              No active areas.{' '}
              {administrator &&
                'Add a name to create an area or restore a deleted one.'}
            </p>
          )}
        </div>
      )}
      {dialog && administrator && (
        <Modal
          title={
            dialog.kind === 'delete'
              ? 'Delete area'
              : dialog.kind === 'edit'
                ? 'Edit area'
                : 'Add area'
          }
          close={() => {
            if (!busy.current) setDialog(null);
          }}
        >
          <form
            onSubmit={(event) => {
              void save(event);
            }}
            aria-busy={pending}
          >
            {dialog.kind === 'delete' ? (
              <p>
                Hide {dialog.area!.name} from active areas? Its shipments and
                area links are preserved.
              </p>
            ) : (
              <>
                <label>
                  Area name
                  <input
                    required
                    maxLength={64}
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    disabled={pending}
                  />
                </label>
                <p className="field-hint">
                  Letters, numbers, spaces, hyphens and underscores. Adding a
                  deleted name restores its area.
                </p>
              </>
            )}
            {failure && <ErrorNotice message={failure} />}
            <div className="dialog-actions">
              <button
                type="button"
                className="button-quiet"
                disabled={pending}
                onClick={() => setDialog(null)}
              >
                Cancel
              </button>
              <button
                disabled={pending || (dialog.kind !== 'delete' && !name.trim())}
              >
                {pending
                  ? 'Saving…'
                  : dialog.kind === 'delete'
                    ? 'Delete area'
                    : 'Save area'}
              </button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}
