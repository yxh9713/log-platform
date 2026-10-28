import type { DayMetrics, Exceptions } from './dayContracts';

export function Breakdown({
  value,
  label,
}: {
  value: DayMetrics;
  label: string;
}) {
  const parts = [
    { name: 'Delivered', count: value.delivered, color: '#21866d' },
    { name: 'Undelivered', count: value.undelivered, color: '#c47722' },
    { name: 'Void', count: value.void, color: '#7a8391' },
  ];
  let offset = 0;
  return (
    <div className="breakdown">
      <svg
        className="shipment-ring"
        viewBox="0 0 128 128"
        role="img"
        aria-label={`${label}: ${value.delivered} delivered, ${value.undelivered} undelivered, ${value.void} void`}
      >
        <circle
          cx="64"
          cy="64"
          r="49"
          fill="none"
          stroke="#edf0f4"
          strokeWidth="13"
        />
        {parts.map((part) => {
          const percent = value.total ? (part.count / value.total) * 100 : 0;
          const start = offset;
          offset += percent;
          return percent > 0 ? (
            <circle
              key={part.name}
              cx="64"
              cy="64"
              r="49"
              fill="none"
              pathLength="100"
              stroke={part.color}
              strokeWidth="13"
              strokeDasharray={`${percent} ${100 - percent}`}
              strokeDashoffset={-start}
              transform="rotate(-90 64 64)"
            />
          ) : null;
        })}
        <text x="64" y="63" textAnchor="middle" className="ring-number">
          {value.total}
        </text>
        <text x="64" y="81" textAnchor="middle" className="ring-caption">
          packages
        </text>
      </svg>
      <dl className="breakdown-legend">
        {parts.map((part) => (
          <div key={part.name}>
            <dt>
              <span style={{ background: part.color }} aria-hidden="true" />
              {part.name}
            </dt>
            <dd>{part.count}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export function ExceptionChart({ value }: { value: Exceptions }) {
  const rows = [
    ['Attempted', value.attempted],
    ['Returned', value.returned],
    ['Void', value.void],
    ['Consolidated', value.consolidated],
    ['No package', value.no_package],
    ['Held', value.held],
  ] as const;
  const maximum = Math.max(1, ...rows.map(([, count]) => count));
  return (
    <section
      className="panel exceptions-panel"
      aria-labelledby="exceptions-heading"
    >
      <h2 id="exceptions-heading">Exceptions</h2>
      <p className="muted">
        Latest exceptions for undelivered packages, with Void counted
        separately.
      </p>
      {!rows.some(([, count]) => count > 0) && <p>No exceptions for today.</p>}
      <ul className="exception-bars">
        {rows.map(([label, count]) => (
          <li key={label}>
            <span>{label}</span>
            <svg
              viewBox="0 0 100 10"
              preserveAspectRatio="none"
              aria-hidden="true"
            >
              <rect width="100" height="10" rx="3" fill="#edf0f4" />
              <rect
                width={(count / maximum) * 100}
                height="10"
                rx="3"
                fill={label === 'Void' ? '#7a8391' : '#c47722'}
              />
            </svg>
            <strong>{count}</strong>
          </li>
        ))}
      </ul>
    </section>
  );
}
