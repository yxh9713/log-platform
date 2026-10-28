import { useEffect, useRef, type ReactNode } from 'react';
import type { Paging, Row } from './contracts';
import { navigate } from './hooks';

export function Link({
  href,
  children,
  ...props
}: {
  href: string;
  children: ReactNode;
  className?: string;
  'aria-current'?: 'page';
}) {
  return (
    <a
      href={href}
      {...props}
      onClick={(event) => {
        if (
          event.button === 0 &&
          !event.ctrlKey &&
          !event.metaKey &&
          !event.shiftKey &&
          !event.altKey
        ) {
          event.preventDefault();
          navigate(href);
        }
      }}
    >
      {children}
    </a>
  );
}
export function ErrorNotice({
  message,
  retry,
}: {
  message: string;
  retry?: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.focus();
  }, [message]);
  return (
    <div className="notice" role="alert" ref={ref} tabIndex={-1}>
      {message}{' '}
      {retry && (
        <button className="button-quiet" onClick={retry}>
          Try again
        </button>
      )}
    </div>
  );
}
export function Status({ status }: { status: Row['status'] }) {
  return (
    <span className={`shipment-status ${status.toLowerCase()}`}>
      <span aria-hidden="true" />
      {status}
    </span>
  );
}
export function DateTime({ value }: { value: string | null }) {
  // Preserve the API's recipient-local wall time and actual offset, not browser time.
  return value ? (
    <time dateTime={value}>
      {value
        .replace('T', ' ')
        .replace(/(\d{2}:\d{2}):\d{2}(\.\d+)?/, '$1')}{' '}
    </time>
  ) : null;
}
export function Pagination({
  result,
  change,
  disabled = false,
}: {
  result: Paging;
  change: (page: number, length: number) => void;
  disabled?: boolean;
}) {
  return (
    <div className="pagination">
      <label>
        Rows per page{' '}
        <select
          value={result.length}
          disabled={disabled}
          onChange={(event) => change(1, Number(event.target.value))}
        >
          {[10, 25, 50, 100].map((size) => (
            <option key={size}>{size}</option>
          ))}
        </select>
      </label>
      <span aria-live="polite">
        {result.total} packages · Page {result.page} of{' '}
        {Math.max(1, result.pages)}
      </span>
      <button
        className="button-quiet"
        disabled={disabled || result.page <= 1}
        onClick={() => change(result.page - 1, result.length)}
      >
        Previous
      </button>
      <button
        className="button-quiet"
        disabled={disabled || result.page >= result.pages}
        onClick={() => change(result.page + 1, result.length)}
      >
        Next
      </button>
      {result.page > result.pages && result.page > 1 && (
        <button onClick={() => change(1, result.length)}>First page</button>
      )}
    </div>
  );
}
export function Modal({
  title,
  children,
  close,
}: {
  title: string;
  children: ReactNode;
  close: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef(close);
  useEffect(() => {
    closeRef.current = close;
  }, [close]);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const root = ref.current!;
    const focusable = () =>
      Array.from(root.querySelectorAll<HTMLElement>('*')).filter(
        (element) =>
          element.matches('button, input, select, a[href], [tabindex="0"]') &&
          !element.matches(':disabled'),
      );
    focusable()[0]?.focus();
    function keyboard(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault();
        closeRef.current();
      }
      if (event.key === 'Tab') {
        const elements = focusable();
        if (!elements.length) {
          event.preventDefault();
          root.focus();
          return;
        }
        const first = elements[0],
          last = elements.at(-1);
        if (
          event.shiftKey &&
          (document.activeElement === first ||
            !root.contains(document.activeElement))
        ) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    }
    document.addEventListener('keydown', keyboard);
    return () => {
      document.removeEventListener('keydown', keyboard);
      previous?.focus();
    };
  }, []);
  return (
    <div className="modal-backdrop">
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        ref={ref}
      >
        <h2>{title}</h2>
        {children}
      </div>
    </div>
  );
}
