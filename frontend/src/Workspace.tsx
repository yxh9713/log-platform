import { useLocation, useResource, type AuthFailure } from './shipments/hooks';
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import type { Session } from './api';
import Areas from './shipments/Areas';
import { initialFilters, parseAreas, type Lookup } from './shipments/contracts';
import Search from './shipments/Search';
import ShipmentDetail from './shipments/ShipmentDetail';
import { ErrorNotice, Link } from './shipments/shared';
import Tracking from './shipments/Tracking';
import MyDay from './shipments/MyDay';
import { ExportCenter } from './shipments/exports';

export default function Workspace({
  session,
  pending,
  signOut,
  notice,
  onExpired,
}: {
  session: Session;
  pending: boolean;
  signOut: () => void;
  notice: ReactNode;
  onExpired: AuthFailure;
}) {
  const location = useLocation();
  const [filters, setFilters] = useState(initialFilters);
  const [areaRevision, setAreaRevision] = useState(0);
  const refreshAreas = useCallback(
    () => setAreaRevision((value) => value + 1),
    [],
  );
  const pathname = location.split('?')[0];
  const areaResult = useResource(
    pathname === '/tracking' || pathname === '/areas' ? 'areas' : null,
    parseAreas,
    onExpired,
    areaRevision,
  );
  const main = useRef<HTMLElement>(null);
  useEffect(() => {
    main.current?.focus();
  }, [location]);
  useEffect(() => {
    function escape(event: KeyboardEvent) {
      if (event.key !== 'Escape' || document.querySelector('[role="dialog"]'))
        return;
      document.querySelectorAll('details[open]').forEach((node) => {
        node.removeAttribute('open');
        node.querySelector('summary')?.focus();
      });
    }
    document.addEventListener('keydown', escape);
    return () => document.removeEventListener('keydown', escape);
  }, []);
  let content: ReactNode;
  const title =
    pathname === '/'
      ? 'My Day'
      : pathname === '/areas'
        ? 'Areas'
        : pathname === '/tracking/search'
          ? 'Search'
          : 'Tracking';
  if (pathname === '/tracking')
    content = (
      <Tracking
        filters={filters}
        change={setFilters}
        areas={areaResult.data}
        areaError={areaResult.error}
        refreshAreas={refreshAreas}
        onExpired={onExpired}
        revision={areaRevision}
      />
    );
  else if (pathname === '/tracking/search')
    content = <Search key={location} onExpired={onExpired} />;
  else if (pathname === '/areas')
    content = (
      <Areas
        areas={areaResult.data}
        error={areaResult.error}
        administrator={session.role === 'administrator'}
        refresh={refreshAreas}
        onExpired={onExpired}
      />
    );
  else if (pathname.startsWith('/tracking/detail/')) {
    const params = new URLSearchParams(location.split('?')[1] ?? '');
    const field = params.get('field') ?? 'reference';
    const id = params.get('shipment_id');
    let identifier = '';
    try {
      identifier = decodeURIComponent(
        pathname.slice('/tracking/detail/'.length),
      );
      if (params.get('encoding') === 'dot')
        identifier = decodeURIComponent(identifier);
    } catch {
      /* Invalid encoded URL. */
    }
    const validId =
      id !== null &&
      /^[1-9]\d{0,18}$/.test(id) &&
      BigInt(id) <= 9223372036854775807n;
    content =
      !identifier ||
      identifier.length > 255 ||
      !['reference', 'shipment_number'].includes(field) ||
      (id !== null && !validId) ? (
        <ErrorNotice message="Invalid shipment link. Use Search to choose a shipment." />
      ) : id ? (
        <ShipmentDetail key={id} id={id} onExpired={onExpired} />
      ) : (
        <Search
          key={location}
          direct={{ identifier, field: field as Lookup }}
          onExpired={onExpired}
        />
      );
  } else if (pathname === '/')
    content = (
      <MyDay
        session={session}
        onExpired={onExpired}
        revision={areaRevision}
        refresh={refreshAreas}
      />
    );
  else
    content = (
      <>
        <h1>Page not found</h1>
        <Link href="/tracking">Open Tracking</Link>
      </>
    );
  return (
    <div className="workspace">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <aside className="sidebar">
        <Link href="/" className="brand">
          <span className="brand-mark" aria-hidden="true">
            ↗
          </span>
          Logistics<span className="brand-light">Platform</span>
        </Link>
        <p className="sidebar-label">SHIPPER WORKSPACE</p>
        <nav aria-label="Workspace">
          {[
            ['/', 'My Day', '▦'],
            ['/tracking', 'Tracking', '▤'],
            ['/tracking/search', 'Search', '⌕'],
            ['/areas', 'Areas', '▧'],
          ].map(([href, label, icon]) => {
            const selected =
              pathname === href ||
              (href === '/tracking' &&
                pathname.startsWith('/tracking/detail/'));
            return (
              <Link
                key={href}
                href={href}
                className={`nav-item ${selected ? 'selected' : ''}`}
                aria-current={selected ? 'page' : undefined}
              >
                <span aria-hidden="true">{icon}</span>
                {label}
              </Link>
            );
          })}
        </nav>
        <div className="sidebar-bottom">
          <span className="avatar" aria-hidden="true">
            {session.company.name.slice(0, 1)}
          </span>
          <div>
            <strong>{session.company.name}</strong>
            <span>Shipper account</span>
          </div>
        </div>
      </aside>
      <div className="workspace-body">
        <header className="topbar">
          <span>{title}</span>
          <button className="button-quiet" disabled={pending} onClick={signOut}>
            {pending ? 'Signing out…' : 'Sign out'}
          </button>
        </header>
        <main id="main" className="workspace-main" ref={main} tabIndex={-1}>
          {notice}
          <ExportCenter onExpired={onExpired} />
          {content}
        </main>
        <footer>Logistics Platform · Company-scoped access</footer>
      </div>
    </div>
  );
}
