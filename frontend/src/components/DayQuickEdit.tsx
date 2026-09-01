import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { api } from '../api'
import { DAY_TYPE_LABELS, endIsoDay, hhmm, hm, longDate, minutesBetween } from '../format'
import type { DayOut, DayTypeMark } from '../types'
import TimeField from './TimePicker'

const MARKS: { value: DayTypeMark | ''; label: string }[] = [
  { value: '', label: 'Default' },
  { value: 'workday', label: 'Workday' },
  { value: 'half_day', label: 'Half day' },
  { value: 'vacation', label: 'Vacation' },
  { value: 'sick', label: 'Sick' },
  { value: 'holiday', label: 'Holiday' },
  { value: 'off', label: 'Off' },
]

const MARGIN = 8

export default function DayQuickEdit({
  day,
  at,
  onChanged,
  onClose,
  onOpenEditor,
}: {
  day: DayOut
  /**
   * Where the right-click happened, in viewport coordinates — or null on touch,
   * where the same content opens as a bottom sheet instead of a popover.
   */
  at: { x: number; y: number } | null
  onChanged: () => void | Promise<void>
  onClose: () => void
  onOpenEditor: () => void
}) {
  const sheet = at === null
  const ref = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState(at ?? { x: 0, y: 0 })
  const [start, setStart] = useState('09:00')
  const [end, setEnd] = useState('17:00')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  // Keep the whole popover on screen — a right-click near the bottom-right edge
  // would otherwise open it half outside the viewport.
  useLayoutEffect(() => {
    if (!at) return
    const box = ref.current?.getBoundingClientRect()
    if (!box) return
    setPos({
      x: Math.max(MARGIN, Math.min(at.x, window.innerWidth - box.width - MARGIN)),
      y: Math.max(MARGIN, Math.min(at.y, window.innerHeight - box.height - MARGIN)),
    })
  }, [at])

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  useEffect(() => {
    // The sheet has a scrim of its own; only the free-floating popover needs to
    // watch for a press landing elsewhere.
    if (sheet) return
    function onDown(e: PointerEvent) {
      if (!ref.current?.contains(e.target as Node)) onClose()
    }
    // Capture, so a press that lands on another day cell closes this first.
    window.addEventListener('pointerdown', onDown, true)
    return () => window.removeEventListener('pointerdown', onDown, true)
  }, [sheet, onClose])

  async function run(fn: () => Promise<unknown>) {
    setBusy(true)
    setError('')
    try {
      await fn()
      await onChanged()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'That did not work')
    } finally {
      setBusy(false)
    }
  }

  // An end at or before the start is read as a shift running past midnight;
  // the backend splits its minutes between the two days.
  const overnight = end !== '' && end <= start

  const addPeriod = () =>
    run(async () => {
      const endDay = endIsoDay(day.day, start, end)
      await api.addPeriod(day.day, `${day.day}T${start}:00`, end ? `${endDay}T${end}:00` : null, '')
    })

  const body = (
    <div
      ref={ref}
      className={sheet ? 'day-menu sheet' : 'day-menu'}
      style={sheet ? undefined : { left: pos.x, top: pos.y }}
      role="dialog"
      aria-modal={sheet || undefined}
      aria-label={`Edit ${longDate(day.day)}`}
    >
      {sheet && <span className="dm-grip" aria-hidden="true" />}
      <div className="dm-head">
        <strong>{longDate(day.day)}</strong>
        <span className="muted small">
          {hm(day.worked_minutes)} worked · counted as {DAY_TYPE_LABELS[day.effective_type]}
        </span>
      </div>

      <div className="dm-section">
        <span className="dm-label">Day type</span>
        <div className="dm-chips">
          {MARKS.map((m) => (
            <button
              key={m.value}
              className={`dm-chip ${(day.day_type ?? '') === m.value ? 'on' : ''}`}
              disabled={busy}
              onClick={() => run(() => api.setMark(day.day, m.value || null, day.note))}
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>

      <div className="dm-section">
        <span className="dm-label">Add a period</span>
        <div className="dm-times">
          <TimeField label="Start" value={start} onChange={setStart} />
          <span className="dm-dash">→</span>
          <TimeField label="End" value={end} onChange={setEnd} />
          <button
            className="linklike"
            title={end ? 'Record an open period instead' : 'Give it an end time'}
            onClick={() => setEnd(end ? '' : '17:00')}
          >
            {end ? 'no end' : 'set end'}
          </button>
          <button className="primary" disabled={busy} onClick={addPeriod}>
            Add
          </button>
        </div>
        <p className="muted small">
          {end === ''
            ? 'Open period — it counts as zero until you give it an end.'
            : overnight
              ? 'Runs past midnight — the minutes split across both days.'
              : `${hm(minutesBetween(start, end))} on this day.`}
        </p>
      </div>

      {day.periods.length > 0 && (
        <div className="dm-section">
          <span className="dm-label">On this day</span>
          <ul className="dm-periods">
            {day.periods.map((p, i) => (
              <li key={`${p.period_id}-${i}`}>
                <span className="dm-range">
                  {p.continues_from_previous_day ? '…' : hhmm(p.full_start)}
                  {' – '}
                  {p.open ? 'open' : p.continues_to_next_day ? '…' : hhmm(p.full_end)}
                </span>
                <span className="dm-mins">{hm(p.minutes)}</span>
                <button
                  className="linklike danger"
                  disabled={busy}
                  title="Delete this period"
                  onClick={() => run(() => api.deletePeriod(p.period_id))}
                >
                  ✕
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {error && <p className="error small">{error}</p>}

      <div className="dm-foot">
        <button className="linklike" onClick={onOpenEditor}>
          Open full day editor →
        </button>
        <button className="linklike" onClick={onClose}>
          Close
        </button>
      </div>
    </div>
  )

  if (!sheet) return body

  return (
    // Only a press on the scrim itself closes; the time picker renders its own
    // scrim inside this tree and its cancel must not bubble through to here.
    <div
      className="dm-scrim"
      onPointerDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      {body}
    </div>
  )
}
