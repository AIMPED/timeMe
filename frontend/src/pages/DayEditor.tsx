import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { DAY_TYPE_LABELS, hm, longDate, parseIsoDate, isoDate, signedHm } from '../format'
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

/** "2026-08-06T09:00:00" -> "2026-08-06T09:00", the shape a datetime-local wants. */
const forInput = (iso: string) => iso.slice(0, 16)

function PeriodRow({
  period,
  onChanged,
  onError,
}: {
  period: PeriodOut
  onChanged: (d: DayDetail) => void
  onError: (m: string) => void
}) {
  const [start, setStart] = useState(forInput(period.full_start))
  const [end, setEnd] = useState(period.full_end ? forInput(period.full_end) : '')
  const [note, setNote] = useState(period.note)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setStart(forInput(period.full_start))
    setEnd(period.full_end ? forInput(period.full_end) : '')
    setNote(period.note)
  }, [period.full_start, period.full_end, period.note])

  const dirty =
    start !== forInput(period.full_start) ||
    end !== (period.full_end ? forInput(period.full_end) : '') ||
    note !== period.note

  async function save() {
    setBusy(true)
    onError('')
    try {
      onChanged(
        await api.updatePeriod(period.period_id, {
          start: `${start}:00`,
          end: end ? `${end}:00` : undefined,
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
        <input type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} />
      </td>
      <td>
        <input type="datetime-local" value={end} onChange={(e) => setEnd(e.target.value)} />
        {period.open && <span className="pill">open</span>}
      </td>
      <td className="num">{hm(period.minutes)}</td>
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
  const [newStart, setNewStart] = useState('')
  const [newEnd, setNewEnd] = useState('')
  const [newNote, setNewNote] = useState('')
  const [markNote, setMarkNote] = useState('')

  const load = useCallback(async () => {
    try {
      const d = await api.day(day)
      setDetail(d)
      setMarkNote(d.day.note)
      setNewStart(`${day}T09:00`)
      setNewEnd(`${day}T17:00`)
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load the day')
    }
  }, [day])

  useEffect(() => {
    void load()
  }, [load])

  async function addPeriod(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    try {
      setDetail(
        await api.addPeriod(day, `${newStart}:00`, newEnd ? `${newEnd}:00` : null, newNote),
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
            to={`/calendar/${monthDate.getFullYear()}/${monthDate.getMonth() + 1}`}
          >
            Back to calendar
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
            <label>
              Start
              <input
                type="datetime-local"
                value={newStart}
                onChange={(e) => setNewStart(e.target.value)}
                required
              />
            </label>
            <label>
              End
              <input
                type="datetime-local"
                value={newEnd}
                onChange={(e) => setNewEnd(e.target.value)}
              />
            </label>
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
            Leaving the end empty records an open period. A period may run past midnight; its minutes
            are split between the two days.
          </p>
        </form>
      </div>
    </div>
  )
}
