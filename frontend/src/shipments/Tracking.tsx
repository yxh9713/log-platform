import { ExportButton } from './exports';
import { useResource, type AuthFailure } from './hooks';
import { useState, type FormEvent } from 'react';
import {
  detailHref,
  parseTracking,
  trackingPath,
  type Area,
  type Filters,
  type Row,
} from './contracts';
import DateRange from './DateRange';
import { DateTime, ErrorNotice, Link, Pagination, Status } from './shared';

const columns = [
  ['shipment_number', 'Shipment'],
  ['reference', 'Reference'],
  ['route', 'Route'],
  ['company', 'Company'],
  ['city', 'City'],
  ['zip', 'Zip'],
  ['pod_name', 'POD Name'],
  ['deliver_time', 'POD Time'],
  ['status', 'Status'],
  ['due_time', 'Expected delivery'],
  ['account', 'Account'],
] as const;
export default function Tracking({
  filters,
  change,
  areas,
  areaError,
  refreshAreas,
  onExpired,
  revision,
}: {
  filters: Filters;
  change: (value: Filters) => void;
  areas?: Area[];
  areaError?: string;
  refreshAreas: () => void;
  onExpired: AuthFailure;
  revision: number;
}) {
  const [reload, setReload] = useState(0);
  const result = useResource(
    trackingPath(filters),
    parseTracking,
    onExpired,
    revision + reload,
  );
  const [visible, setVisible] = useState<string[]>(
    columns.slice(0, 9).map(([key]) => key),
  );
  const [account, setAccount] = useState(filters.account);
  const commit = (changes: Partial<Filters>) =>
    change({ ...filters, ...changes, page: 1 });
  function accountSubmit(event: FormEvent) {
    event.preventDefault();
    commit({ account });
  }
  function sort(key: string) {
    commit({
      sort: key,
      direction:
        filters.sort === key && filters.direction === 'asc' ? 'desc' : 'asc',
    });
  }
  function cell(row: Row, key: (typeof columns)[number][0]) {
    if (key === 'shipment_number')
      return (
        <Link href={detailHref(row, 'shipment_number')}>
          {row.shipment_number}
        </Link>
      );
    if (key === 'status') return <Status status={row.status} />;
    if (key === 'deliver_time' || key === 'due_time')
      return <DateTime value={row[key]} />;
    return row[key] ?? '';
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">SHIPMENTS</p>
          <h1>Tracking</h1>
          <p className="muted">Every package across your carriers.</p>
        </div>
        <Link href="/tracking/search" className="text-link">
          Find a shipment →
        </Link>
      </div>
      <div className="filter-bar">
        <DateRange
          start={filters.start_date}
          end={filters.end_date}
          effective={
            result.data
              ? [result.data.start_date, result.data.end_date]
              : undefined
          }
          apply={(start_date, end_date) => commit({ start_date, end_date })}
        />
        <label>
          Date field
          <select
            value={filters.date_type}
            onChange={(event) =>
              commit({ date_type: event.target.value as Filters['date_type'] })
            }
          >
            <option value="due_date">Due date</option>
            <option value="order_date">Order date</option>
            <option value="deliver_time">Delivery time</option>
            <option value="created_at">Created time</option>
          </select>
        </label>
        <details className="filter-popover">
          <summary>
            Account{filters.account ? `: ${filters.account}` : ''}
          </summary>
          <form onSubmit={accountSubmit}>
            <label>
              Exact account
              <input
                maxLength={255}
                value={account}
                onChange={(event) => setAccount(event.target.value)}
              />
            </label>
            <button>Apply account</button>
            <button
              type="button"
              className="button-quiet"
              onClick={() => {
                setAccount('');
                commit({ account: '' });
              }}
            >
              Clear account
            </button>
          </form>
        </details>
        <label>
          Status
          <select
            value={filters.status}
            onChange={(event) =>
              commit({ status: event.target.value as Filters['status'] })
            }
          >
            <option value="">All statuses</option>
            <option value="delivered">Delivered</option>
            <option value="undelivered">Undelivered</option>
          </select>
        </label>
        <details className="filter-popover">
          <summary>
            Areas{filters.area.length ? ` (${filters.area.length})` : ''}
          </summary>
          <fieldset>
            <legend>Match any selected area</legend>
            {!areas && !areaError && <p role="status">Loading areas…</p>}
            {areaError && (
              <div role="alert">
                {areaError}
                <button className="button-quiet" onClick={refreshAreas}>
                  Reload areas
                </button>
              </div>
            )}
            {areas?.length === 0 && <p>No active areas.</p>}
            {areas?.map((area) => (
              <label key={area.id}>
                <input
                  type="checkbox"
                  checked={filters.area.includes(area.id)}
                  onChange={(event) =>
                    commit({
                      area: event.target.checked
                        ? [...filters.area, area.id]
                        : filters.area.filter((id) => id !== area.id),
                    })
                  }
                />
                {area.name}
              </label>
            ))}
            {filters.area.some(
              (id) => !areas?.some((area) => area.id === id),
            ) && (
              <p role="status">
                A selected area is unavailable. Clear the selection to change
                the filter.
              </p>
            )}
            <button
              className="button-quiet"
              onClick={() => commit({ area: [] })}
            >
              Clear areas
            </button>
          </fieldset>
        </details>
        <label>
          Exceptions
          <select
            value={filters.exception}
            onChange={(event) =>
              commit({ exception: event.target.value as Filters['exception'] })
            }
          >
            <option value="">All exceptions</option>
            <option value="attempted">Attempted</option>
            <option value="void">Void</option>
            <option value="returned">Returned</option>
          </select>
        </label>
      </div>
      <div className="results-toolbar">
        <ExportButton filters={filters} onExpired={onExpired} />
        <div className="metrics" aria-label="Filtered shipment metrics">
          {result.data ? (
            <>
              <span>
                <strong>{result.data.metrics.undelivered}</strong> Undelivered
              </span>
              <span>
                <strong>{result.data.metrics.total}</strong> Total
              </span>
              <span>
                <strong>{result.data.metrics.otp.toFixed(2)}%</strong> On time
              </span>
            </>
          ) : (
            <span>Metrics {result.error ? 'unavailable' : 'loading…'}</span>
          )}
        </div>
        <details className="filter-popover columns">
          <summary>Columns</summary>
          <fieldset>
            <legend>Visible columns</legend>
            {columns.map(([key, label]) => (
              <label key={key}>
                <input
                  type="checkbox"
                  checked={visible.includes(key)}
                  disabled={key === 'shipment_number'}
                  onChange={(event) =>
                    setVisible(
                      event.target.checked
                        ? [...visible, key]
                        : visible.filter((item) => item !== key),
                    )
                  }
                />
                {label}
              </label>
            ))}
          </fieldset>
        </details>
        <button
          className="button-quiet"
          onClick={() => {
            setAccount('');
            change({
              date_type: 'due_date',
              account: '',
              status: '',
              exception: '',
              area: [],
              page: 1,
              length: filters.length,
              sort: 'due_time',
              direction: 'asc',
            });
          }}
        >
          Reset filters
        </button>
      </div>
      {result.error && (
        <ErrorNotice
          message={result.error}
          retry={() => setReload((value) => value + 1)}
        />
      )}
      {!result.data && !result.error && (
        <p className="loading" role="status">
          Loading shipments…
        </p>
      )}
      {result.data && (
        <>
          <div
            className="table-scroll"
            role="region"
            aria-label="Tracking results"
            tabIndex={0}
          >
            <table>
              <caption className="sr-only">Filtered shipments</caption>
              <thead>
                <tr>
                  {columns
                    .filter(([key]) => visible.includes(key))
                    .map(([key, label]) => (
                      <th
                        key={key}
                        scope="col"
                        aria-sort={
                          key === 'account'
                            ? undefined
                            : filters.sort === key
                              ? filters.direction === 'asc'
                                ? 'ascending'
                                : 'descending'
                              : 'none'
                        }
                      >
                        {key === 'account' ? (
                          label
                        ) : (
                          <button onClick={() => sort(key)}>
                            {label}
                            {filters.sort === key && (
                              <span aria-hidden="true">
                                {' '}
                                {filters.direction === 'asc' ? '↑' : '↓'}
                              </span>
                            )}
                          </button>
                        )}
                      </th>
                    ))}
                </tr>
              </thead>
              <tbody>
                {result.data.items.map((row) => (
                  <tr key={row.id}>
                    {columns
                      .filter(([key]) => visible.includes(key))
                      .map(([key]) => (
                        <td key={key}>{cell(row, key)}</td>
                      ))}
                  </tr>
                ))}
              </tbody>
            </table>
            {result.data.items.length === 0 && (
              <div className="empty-state">
                <h2>No shipments found</h2>
                <p>Try another date range or change your filters.</p>
              </div>
            )}
          </div>
          <Pagination
            result={result.data}
            change={(page, length) => change({ ...filters, page, length })}
          />
        </>
      )}
    </>
  );
}
