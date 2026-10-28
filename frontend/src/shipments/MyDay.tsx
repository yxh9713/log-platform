import { useEffect } from 'react';
import type { Session } from '../api';
import Areas from './Areas';
import { Breakdown, ExceptionChart } from './charts';
import { parseDay } from './dayContracts';
import { useResource, type AuthFailure } from './hooks';
import { ErrorNotice } from './shared';

export default function MyDay({
  session,
  onExpired,
  revision,
  refresh,
}: {
  session: Session;
  onExpired: AuthFailure;
  revision: number;
  refresh: () => void;
}) {
  const result = useResource('my-day', parseDay, onExpired, revision);
  useEffect(() => {
    let timer: number;
    const schedule = () => {
      const now = new Date();
      const next = Date.UTC(
        now.getUTCFullYear(),
        now.getUTCMonth(),
        now.getUTCDate() + 1,
      );
      timer = window.setTimeout(
        () => {
          refresh();
          schedule();
        },
        Math.max(1000, next - Date.now() + 1000),
      );
    };
    const visible = () => {
      if (document.visibilityState === 'visible') refresh();
    };
    schedule();
    window.addEventListener('focus', refresh);
    document.addEventListener('visibilitychange', visible);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener('focus', refresh);
      document.removeEventListener('visibilitychange', visible);
    };
  }, [refresh]);
  const report = result.data;
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">
            {session.company.name} ·{' '}
            <span>
              {session.role === 'administrator' ? 'Administrator' : 'User'}
            </span>
          </p>
          <h1>My Day</h1>
          <p className="muted">
            Packages due today
            {report && (
              <>
                {' '}
                ·{' '}
                <time dateTime={report.report_date}>
                  {report.report_date}
                </time>{' '}
                UTC
              </>
            )}
          </p>
        </div>
        <button className="button-quiet" onClick={refresh}>
          Refresh dashboard
        </button>
      </div>
      {result.error && <ErrorNotice message={result.error} retry={refresh} />}
      {!report && !result.error && <p role="status">Loading My Day…</p>}
      {report && (
        <>
          <div
            className="day-metrics"
            role="group"
            aria-label="My Day shipment metrics"
          >
            <section className="panel">
              <span>Total</span>
              <strong>{report.stats.total}</strong>
              <p className="muted">Includes {report.stats.void} Void</p>
            </section>
            <section className="panel">
              <span>Undelivered</span>
              <strong>{report.stats.undelivered}</strong>
              <p className="muted">Awaiting completed delivery</p>
            </section>
            <section className="panel">
              <span>On time</span>
              <strong>{report.stats.otp.toFixed(2)}%</strong>
              <p className="muted">
                {report.stats.total === report.stats.void
                  ? 'No eligible packages'
                  : report.stats.delivered === 0
                    ? 'No completed deliveries yet'
                    : 'Delivered before the deadline'}
              </p>
            </section>
          </div>
          {report.stats.total === 0 && (
            <p className="empty-state">No packages due today.</p>
          )}
          <div className="day-charts">
            <section className="panel" aria-labelledby="delivery-heading">
              <h2 id="delivery-heading">Shipment status</h2>
              <Breakdown value={report.stats} label="Today's shipment status" />
            </section>
            <ExceptionChart value={report.exceptions} />
          </div>
        </>
      )}
      <Areas
        dashboard
        areas={report?.areas.map((area) => ({ id: area.id, name: area.area }))}
        statistics={report?.areas}
        error={result.error}
        administrator={session.role === 'administrator'}
        refresh={refresh}
        onExpired={onExpired}
      />
      {report && (
        <p className="muted area-note">
          Area cards show active areas only. Unassigned packages and packages in
          deleted areas remain in the totals above.
        </p>
      )}
    </>
  );
}
