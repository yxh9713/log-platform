import { useResource, type AuthFailure } from './hooks';
import { useState } from 'react';
import { parseDetail, type Address } from './contracts';
import { DateTime, ErrorNotice, Link, Status } from './shared';
function AddressCard({ title, address }: { title: string; address: Address }) {
  return (
    <section className="panel address-card">
      <h2>{title}</h2>
      <address>
        <strong>{address.name}</strong>
        <span>{address.address_one}</span>
        {address.address_two && <span>{address.address_two}</span>}
        <span>
          {address.city}, {address.state} {address.zip}
        </span>
        {address.phone && <span>{address.phone}</span>}
        {address.email && <span>{address.email}</span>}
        {address.note && <p>{address.note}</p>}
      </address>
    </section>
  );
}
function PodImage({ url }: { url: string }) {
  const [failed, setFailed] = useState(false);
  let safe = false;
  try {
    safe = ['http:', 'https:'].includes(
      new URL(url, window.location.origin).protocol,
    );
  } catch {
    /* Invalid URLs have no usable image. */
  }
  return !safe || failed ? (
    <p className="muted">POD image is unavailable.</p>
  ) : (
    <img
      className="pod-image"
      src={url}
      alt="Latest proof of delivery"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
    />
  );
}
export default function ShipmentDetail({
  id,
  onExpired,
}: {
  id: string;
  onExpired: AuthFailure;
}) {
  const [retry, setRetry] = useState(0);
  const result = useResource(
    `shipments/${encodeURIComponent(id)}`,
    parseDetail,
    onExpired,
    retry,
  );
  const detail = result.data;
  return (
    <>
      <Link className="text-link" href="/tracking">
        ← Tracking
      </Link>
      {!detail && !result.error && <p role="status">Loading shipment…</p>}
      {result.error && (
        <ErrorNotice
          message={result.error}
          retry={() => setRetry((value) => value + 1)}
        />
      )}
      {detail && (
        <>
          <h1 className="detail-heading">Shipment {detail.shipment_number}</h1>
          <div className="detail-grid">
            <div>
              <section className="panel">
                <h2>Shipment detail</h2>
                <p className="current-status">
                  <Status status={detail.status} />
                  <span className="muted">Current Status</span>
                </p>
                <dl>
                  {[
                    ['Vendor', detail.carrier],
                    ['Reference 1', detail.reference],
                    ['Reference 2', detail.reference_two],
                    ['Account', detail.account],
                    ['Service Type', detail.service_name],
                    ['Route', detail.route],
                    ['Expected Delivery', <DateTime value={detail.due_time} />],
                    ['Weight', detail.weight],
                    ['Order date', detail.order_date],
                  ].map(([label, value]) => (
                    <div key={String(label)}>
                      <dt>{label}</dt>
                      <dd>{value}</dd>
                    </div>
                  ))}
                </dl>
              </section>
              <section className="panel">
                <h2>Shipment progress</h2>
                <ol className="timeline">
                  {detail.history.map((event) => (
                    <li key={event.id}>
                      <strong>{event.action}</strong>
                      <DateTime value={event.event_time} />
                    </li>
                  ))}
                </ol>
                {detail.history.length === 0 && (
                  <p>No event history available.</p>
                )}
              </section>
            </div>
            <div>
              <AddressCard
                title="Delivery address"
                address={detail.recipient}
              />
              <AddressCard title="Pickup address" address={detail.sender} />
              <section className="panel">
                <h2>Proof of delivery</h2>
                <dl>
                  <div>
                    <dt>Signed by</dt>
                    <dd>{detail.pod_name}</dd>
                  </div>
                  <div>
                    <dt>Delivery time</dt>
                    <dd>
                      <DateTime value={detail.deliver_time} />
                    </dd>
                  </div>
                  <div>
                    <dt>Notes</dt>
                    <dd>{detail.notes}</dd>
                  </div>
                </dl>
                {detail.pod_url ? (
                  <PodImage key={detail.pod_url} url={detail.pod_url} />
                ) : (
                  <p className="image-empty">No POD image available.</p>
                )}
              </section>
            </div>
          </div>
        </>
      )}
    </>
  );
}
