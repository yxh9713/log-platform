import { useState } from 'react';
import { Modal } from './shared';
import {
  addDays,
  dateOf,
  monthStart,
  presetRange,
  presets,
  prettyDate,
  utcToday,
  validRange,
} from './dates';

function Calendar({
  month,
  start,
  end,
  select,
}: {
  month: string;
  start: string;
  end: string;
  select: (day: string) => void;
}) {
  const first = dateOf(month),
    next = dateOf(month);
  next.setUTCMonth(next.getUTCMonth() + 1);
  const days = Array.from(
    { length: (next.getTime() - first.getTime()) / 86400000 },
    (_, index) => addDays(month, index),
  );
  return (
    <section
      className="calendar"
      aria-label={first.toLocaleDateString('en-US', {
        month: 'long',
        year: 'numeric',
        timeZone: 'UTC',
      })}
    >
      <h3>
        {first.toLocaleDateString('en-US', {
          month: 'long',
          year: 'numeric',
          timeZone: 'UTC',
        })}
      </h3>
      <div className="calendar-grid">
        {['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'].map((label) => (
          <span key={label} aria-hidden="true">
            {label}
          </span>
        ))}
        {Array.from({ length: first.getUTCDay() }, (_, index) => (
          <span key={`empty-${index}`} />
        ))}
        {days.map((day) => (
          <button
            type="button"
            key={day}
            data-day={day}
            aria-label={prettyDate(day)}
            aria-pressed={day === start || day === end}
            className={`${day === start || day === end ? 'range-edge' : ''} ${start && end && day >= start && day <= end ? 'in-range' : ''}`}
            onClick={() => select(day)}
            onKeyDown={(event) => {
              const offset = (
                {
                  ArrowLeft: -1,
                  ArrowRight: 1,
                  ArrowUp: -7,
                  ArrowDown: 7,
                } as Record<string, number>
              )[event.key];
              if (offset) {
                const target = event.currentTarget
                  .closest('[role="dialog"]')
                  ?.querySelector<HTMLButtonElement>(
                    `[data-day="${addDays(day, offset)}"]`,
                  );
                if (target) {
                  event.preventDefault();
                  target.focus();
                }
              }
            }}
          >
            {dateOf(day).getUTCDate()}
          </button>
        ))}
      </div>
    </section>
  );
}
export default function DateRange({
  start,
  end,
  effective,
  apply,
}: {
  start?: string;
  end?: string;
  effective?: [string, string];
  apply: (start: string, end: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [draftStart, setStart] = useState('');
  const [draftEnd, setEnd] = useState('');
  const [month, setMonth] = useState(monthStart(utcToday()));
  const committed = start && end ? [start, end] : effective;
  function show() {
    const first = committed?.[0] ?? utcToday();
    setStart(first);
    setEnd(committed?.[1] ?? first);
    setMonth(
      monthStart(first) > '9999-11-01' ? '9999-11-01' : monthStart(first),
    );
    setOpen(true);
  }
  function select(day: string) {
    if (!draftStart || draftEnd) {
      setStart(day);
      setEnd('');
    } else if (day < draftStart) {
      setStart(day);
      setEnd(draftStart);
    } else setEnd(day);
  }
  return (
    <>
      <button
        className="button-quiet date-trigger"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={show}
      >
        <span aria-hidden="true">▦</span>{' '}
        {committed
          ? `${prettyDate(committed[0])} – ${prettyDate(committed[1])}`
          : 'Today (UTC)'}
      </button>
      {open && (
        <Modal title="Choose date range" close={() => setOpen(false)}>
          <p className="muted">Inclusive calendar dates · UTC</p>
          <div className="date-picker">
            <div className="presets">
              {presets.map((name) => (
                <button
                  className="button-quiet"
                  key={name}
                  onClick={() => {
                    const [first, last] = presetRange(name);
                    setStart(first);
                    setEnd(last);
                    setMonth(
                      monthStart(first) > '9999-11-01'
                        ? '9999-11-01'
                        : monthStart(first),
                    );
                  }}
                >
                  {name}
                </button>
              ))}
            </div>
            <div className="calendars">
              <div className="calendar-navigation">
                <button
                  className="button-quiet"
                  aria-label="Previous month"
                  disabled={month <= '0001-01-01'}
                  onClick={() => setMonth(monthStart(month, -1))}
                >
                  ←
                </button>
                <button
                  className="button-quiet"
                  aria-label="Next month"
                  disabled={month >= '9999-11-01'}
                  onClick={() => setMonth(monthStart(month, 1))}
                >
                  →
                </button>
              </div>
              <div className="calendar-pair">
                <Calendar
                  month={month}
                  start={draftStart}
                  end={draftEnd}
                  select={select}
                />
                <Calendar
                  month={monthStart(month, 1)}
                  start={draftStart}
                  end={draftEnd}
                  select={select}
                />
              </div>
            </div>
          </div>
          <div className="date-inputs">
            <label>
              Start date
              <input
                type="date"
                value={draftStart}
                onChange={(event) => {
                  setStart(event.target.value);
                  if (
                    event.target.value &&
                    Number.isFinite(dateOf(event.target.value).getTime())
                  )
                    setMonth(
                      monthStart(event.target.value) > '9999-11-01'
                        ? '9999-11-01'
                        : monthStart(event.target.value),
                    );
                }}
              />
            </label>
            <label>
              End date
              <input
                type="date"
                value={draftEnd}
                onChange={(event) => setEnd(event.target.value)}
              />
            </label>
          </div>
          {!validRange(draftStart, draftEnd) && (
            <p role="status">Choose a complete, ordered range.</p>
          )}
          <div className="dialog-actions">
            <button className="button-quiet" onClick={() => setOpen(false)}>
              Cancel
            </button>
            <button
              disabled={!validRange(draftStart, draftEnd)}
              onClick={() => {
                apply(draftStart, draftEnd);
                setOpen(false);
              }}
            >
              Apply
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}
