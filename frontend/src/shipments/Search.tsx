import { navigate, useResource, type AuthFailure } from './hooks';
import { useEffect, useState, type FormEvent } from 'react';
import { detailHref, parseSearch, type Lookup } from './contracts';
import { ErrorNotice, Link, Pagination } from './shared';

export default function Search({
  onExpired,
  direct,
}: {
  onExpired: AuthFailure;
  direct?: { identifier: string; field: Lookup };
}) {
  const [field, setField] = useState<Lookup>(direct?.field ?? 'reference');
  const [identifier, setIdentifier] = useState(direct?.identifier ?? '');
  const [submitted, setSubmitted] = useState(
    direct ? { ...direct, page: 1, length: 10 } : null,
  );
  const [retry, setRetry] = useState(0);
  const result = useResource(
    submitted
      ? `shipments/search?${new URLSearchParams({ identifier: submitted.identifier, field: submitted.field, page: String(submitted.page), length: String(submitted.length) })}`
      : null,
    parseSearch,
    onExpired,
    retry,
  );
  useEffect(() => {
    if (result.data?.total === 1 && result.data.items.length === 1)
      navigate(detailHref(result.data.items[0], result.data.field), !!direct);
  }, [result.data, direct]);
  function submit(event: FormEvent) {
    event.preventDefault();
    if (identifier.trim()) {
      setSubmitted({
        identifier: identifier.trim(),
        field,
        page: 1,
        length: 10,
      });
      setRetry((value) => value + 1);
    }
  }
  return (
    <>
      <p className="eyebrow">SHIPMENTS</p>
      <h1>Search</h1>
      <p className="muted">
        Find an exact reference or shipment number across your company’s
        history.
      </p>
      <form className="search-form panel" onSubmit={submit}>
        <label>
          Search by
          <select
            value={field}
            onChange={(event) => setField(event.target.value as Lookup)}
          >
            <option value="reference">Reference</option>
            <option value="shipment_number">Shipment number</option>
          </select>
        </label>
        <label>
          Identifier
          <input
            required
            maxLength={255}
            value={identifier}
            autoCapitalize="none"
            spellCheck={false}
            onChange={(event) => setIdentifier(event.target.value)}
          />
        </label>
        <button disabled={!identifier.trim()}>Search</button>
      </form>
      {submitted && !result.data && !result.error && (
        <p role="status">Searching…</p>
      )}
      {result.error && (
        <ErrorNotice
          message={result.error}
          retry={() => setRetry((value) => value + 1)}
        />
      )}
      {result.data?.total === 0 && (
        <p role="status" className="empty-state">
          The {result.data.identifier} does not exist
        </p>
      )}
      {result.data && result.data.total > 0 && (
        <>
          <h2>
            {result.data.total === 1
              ? 'Opening shipment…'
              : 'Choose a shipment'}
          </h2>
          <div
            className="table-scroll"
            role="region"
            aria-label="Matching shipments"
            tabIndex={0}
          >
            <table>
              <caption className="sr-only">
                Exact matches for {result.data.identifier}
              </caption>
              <thead>
                <tr>
                  {[
                    'Shipment',
                    'Reference',
                    'Route',
                    'Address',
                    'City',
                    'State',
                    'Zip',
                  ].map((label) => (
                    <th key={label} scope="col">
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.data.items.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <Link href={detailHref(row, result.data!.field)}>
                        {row.shipment_number}
                      </Link>
                    </td>
                    <td>{row.reference}</td>
                    <td>{row.route}</td>
                    <td>{row.address_one}</td>
                    <td>{row.city}</td>
                    <td>{row.state}</td>
                    <td>{row.zip}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination
            result={result.data}
            change={(page, length) =>
              setSubmitted((current) => current && { ...current, page, length })
            }
          />
        </>
      )}
    </>
  );
}
