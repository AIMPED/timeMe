import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import {
  DAY_TYPE_LABELS,
  endIsoDay,
  hm,
  isoDate,
  longDate,
  minutesBetween,
  parseIsoDate,
  signedHm,
} from '../format'
import TimeField from '../components/TimePicker'
import type { DayDetail, DayTypeMark, PeriodOut } from '../types'

const MARK_OPTIONS: { value: DayTypeMark | ''; label: string }[] = [
  { value: '', label: 'Default (weekday / weekend)' },
  { value: 'workday', label: 'Workday' },
  { value: 'half_day', label: 'Half day' },
  { value: 'vacation', label: 'Vacation' },
  { value: 'sick', label: 'Sick' },
  { value: 'holiday', label: 'Public holiday' },
  { value: 'off', label: 'Off (no target)' },
]

/** "2026-08-06T09:00:00" -> "09:00". */
const timeOf = (iso: string) => iso.slice(11, 16)

function PeriodRow({
  period,
  onChanged,
  onError,
}: {
  period: PeriodOut
  onChanged: (d: DayDetail) => void
  onError: (m: string) => void
}) {
  const savedEnd = period.full_end ? timeOf(period.full_end) : ''
  // The dates come from the period itself, never from the picker: a shift that
  // began yesterday keeps yesterday's date when only its time is edited.
  const startDay = period.full_start.slice(0, 10)

  const [start, setStart] = useState(timeOf(period.full_start))
  const [end, setEnd] = useState(savedEnd)
  const [note, setNote] = useState(period.note)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setStart(timeOf(period.full_start))
    setEnd(period.full_end ? timeOf(period.full_end) : '')
    setNote(period.note)
  }, [period.full_start, period.full_end, period.note])

  const dirty = start !== timeOf(period.full_start) || end !== savedEnd || note !== period.note

  async function save() {
    setBusy(true)
    onError('')
    try {
      onChanged(
        await api.updatePeriod(period.period_id, {
          start: `${startDay}T${start}:00`,
          end: end ? `${endIsoDay(startDay, start, end)}T${end}:00` : undefined,
          clear_end: end === '',
          note,
        }),
      )
    } catch (err) {
      onError(err instanceof Error ? err.message : 'Could not save the period')
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    if (!confirm('Delete this period?')) return
    setBusy(true)
    onError('')
    try {
      await api.deletePeriod(period.period_id)
      onChanged(await api.day(period.full_start.slice(0, 10)))
    } catch (err) {
      onError(err instanceof Error ? err.message : 'Could not delete the period')
    } finally {
      setBusy(false)
    }
  }

  return (
    <tr className={period.open ? 'open-period' : undefined}>
      <td>
        <div className="time-cell">
          <TimeField label="Start" value={start} onChange={setStart} />
          {period.continues_from_previous_day && <span className="pill">prev. day</span>}
        </div>
      </td>
      <td>
        <div className="time-cell">
          <TimeField label="End" value={end} onChange={setEnd} />
          <button
            className="linklike"
            title={end ? 'Leave it open instead' : 'Give it an end time'}
            onClick={() => setEnd(end ? '' : start)}
          >
            {end ? 'no end' : 'set end'}
          </button>
          {period.open && <span className="pill">open</span>}
          {period.continues_to_next_day && <span className="pill">next day</span>}
        </div>
      </td>
      {/* The label only shows once the table stacks into cards on a phone. */}
      <td className="num" data-label="On this day">
        {hm(period.minutes)}
      </td>
      <td>
        <input
          type="text"
          placeholder="note"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
      </td>
      <td className="actions">
        <button className="primary" disabled={busy || !dirty} onClick={save}>
          Save
        </button>
        <button className="danger" disabled={busy} onClick={remove}>
          Delete
        </button>
      </td>
    </tr>
  )
}

export default function DayEditor() {
  const { day = '' } = useParams()
  const navigate = useNavigate()
  const [detail, setDetail] = useState<DayDetail | null>(null)
  const [error, setError] = useState('')
  const [newStart, setNewStart] = useState('09:00')
  const [newEnd, setNewEnd] = useState('17:00')
  const [newNote, setNewNote] = useState('')
  const [markNote, setMarkNote] = useState('')

  const load = useCallback(async () => {
    try {
      const d = await api.day(day)
      setDetail(d)
      setMarkNote(d.day.note)
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load the day')
    }
  }, [day])

  useEffect(() => {
    void load()
  }, [load])

  const backToCalendar = useCallback(() => {
    const d = parseIsoDate(day)
    navigate(`/calendar/${d.getFullYear()}/${d.getMonth() + 1}`)
  }, [day, navigate])

  // Escape is the way out of the day, the same as closing a dialog.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') backToCalendar()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [backToCalendar])

  async function addPeriod(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    try {
      setDetail(
        await api.addPeriod(
          day,
          `${day}T${newStart}:00`,
          newEnd ? `${endIsoDay(day, newStart, newEnd)}T${newEnd}:00` : null,
          newNote,
        ),
      )
      setNewNote('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not add the period')
    }
  }

  async function setMark(value: string) {
    setError('')
    try {
      setDetail(await api.setMark(day, value === '' ? null : (value as DayTypeMark), markNote))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not change the day type')
    }
  }

  function shiftDay(delta: number) {
    const d = parseIsoDate(day)
    d.setDate(d.getDate() + delta)
    navigate(`/day/${isoDate(d)}`)
  }

  if (error && !detail) return <div className="boot error">{error}</div>
  if (!detail) return <div className="boot">Loading…</div>

  const d = detail.day
  const monthDate = parseIsoDate(day)

  return (
    <div className="page">
      <div className="card">
        <div className="month-head">
          <div className="month-nav">
            <button onClick={() => shiftDay(-1)} aria-label="Previous day">
              ‹
            </button>
            <h2>{longDate(day)}</h2>
            <button onClick={() => shiftDay(1)} aria-label="Next day">
              ›
            </button>
          </div>
          <Link
            className="button"
            title="Or press Esc"
            to={`/calendar/${monthDate.getFullYear()}/${monthDate.getMonth() + 1}`}
          >
            Back to calendar <span className="kbd">Esc</span>
          </Link>
        </div>

        {d.incomplete && (
          <div className="banner warn">
            <strong>This day has an unclosed period.</strong> It counts as zero until you give it an
            end time below.
          </div>
        )}

        <div className="stat-row">
          <div className="stat">
            <span className="stat-label">Worked</span>
            <span className="stat-value">{hm(d.worked_minutes)}</span>
          </div>
          <div className="stat">
            <span className="stat-label">Target</span>
            <span className="stat-value">{hm(d.target_minutes)}</span>
          </div>
          <div className="stat">
            <span className="stat-label">Deviation</span>
            <span className={`stat-value ${d.deviation_minutes < 0 ? 'neg' : 'pos'}`}>
              {d.is_future ? '—' : signedHm(d.deviation_minutes)}
            </span>
          </div>
          <div className="stat">
            <span className="stat-label">Nominal</span>
            <span className="stat-value">{hm(detail.nominal_minutes)}</span>
          </div>
        </div>
      </div>

      <div className="card">
        <h2>Day type</h2>
        <div className="mark-row">
          <select value={d.day_type ?? ''} onChange={(e) => setMark(e.target.value)}>
            {MARK_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <input
            type="text"
            placeholder="note (optional)"
            value={markNote}
            onChange={(e) => setMarkNote(e.target.value)}
            onBlur={() => d.day_type && setMark(d.day_type)}
          />
          <span className="muted">
            Currently counted as <strong>{DAY_TYPE_LABELS[d.effective_type]}</strong>
          </span>
        </div>
      </div>

      <div className="card">
        <h2>Periods</h2>
        {error && <p className="error">{error}</p>}
        {d.periods.length === 0 ? (
          <p className="muted">Nothing recorded for this day.</p>
        ) : (
          <table className="periods editable">
            <thead>
              <tr>
                <th>Start</th>
                <th>End</th>
                <th className="num">On this day</th>
                <th>Note</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {d.periods.map((p, i) => (
                <PeriodRow
                  key={`${p.period_id}-${i}`}
                  period={p}
                  onChanged={(x) => {
                    setDetail(x)
                    void load()
                  }}
                  onError={setError}
                />
              ))}
            </tbody>
          </table>
        )}

        <form className="add-period" onSubmit={addPeriod}>
          <h3>Add a period</h3>
          <div className="row">
            <TimeField label="Start" value={newStart} onChange={setNewStart} />
            <span className="dm-dash">→</span>
            <TimeField label="End" value={newEnd} onChange={setNewEnd} />
            <button
              type="button"
              className="linklike"
              title={newEnd ? 'Record an open period instead' : 'Give it an end time'}
              onClick={() => setNewEnd(newEnd ? '' : '17:00')}
            >
              {newEnd ? 'no end' : 'set end'}
            </button>
            <label className="grow">
              Note
              <input
                type="text"
                value={newNote}
                onChange={(e) => setNewNote(e.target.value)}
                placeholder="optional"
              />
            </label>
            <button className="primary" type="submit">
              Add
            </button>
          </div>
          <p className="muted small">
            {newEnd === ''
              ? 'No end: an open period, counted as zero until you close it.'
              : newEnd <= newStart
                ? 'Runs past midnight — its minutes are split between the two days.'
                : `${hm(minutesBetween(newStart, newEnd))} on this day.`}
          </p>
        </form>
      </div>
    </div>
  )
}
