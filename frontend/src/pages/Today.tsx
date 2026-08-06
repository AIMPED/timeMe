import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../api'
import { DAY_TYPE_LABELS, hhmm, hm, longDate, signedHm } from '../format'
import type { ClockStatus } from '../types'

function elapsedLabel(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

export default function Today() {
  const [status, setStatus] = useState<ClockStatus | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [confirmForce, setConfirmForce] = useState('')
  const fetchedAt = useRef(Date.now())
  const [, setTick] = useState(0)

  const load = useCallback(async () => {
    try {
      const s = await api.status()
      fetchedAt.current = Date.now()
      setStatus(s)
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load status')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  // Drives the running clock without re-querying the server every second.
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 1000)
    return () => clearInterval(id)
  }, [])

  // Browsers throttle timers in background tabs, and the clock may have been
  // stopped on another device. Re-sync whenever the tab comes back.
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === 'visible') void load()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [load])

  async function act(fn: () => Promise<ClockStatus>) {
    setBusy(true)
    setError('')
    try {
      const s = await fn()
      fetchedAt.current = Date.now()
      setStatus(s)
      setConfirmForce('')
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && err.message.includes('never')) {
        setConfirmForce(err.message)
      } else {
        setError(err instanceof Error ? err.message : 'Something went wrong')
      }
    } finally {
      setBusy(false)
    }
  }

  if (!status) {
    return <div className="boot">{error || 'Loading…'}</div>
  }

  const open = status.open_period
  const running = open !== null && !open.dangling
  const driftSeconds = Math.floor((Date.now() - fetchedAt.current) / 1000)
  const liveSeconds = open ? open.elapsed_seconds + driftSeconds : 0
  const today = status.today
  // worked_minutes already contains the open period floored to whole minutes,
  // so only the minutes that have ticked over since the fetch get added.
  const liveWorked =
    today.worked_minutes +
    (running && open ? Math.floor(liveSeconds / 60) - Math.floor(open.elapsed_seconds / 60) : 0)
  const liveDeviation = liveWorked - today.target_minutes

  return (
    <div className="page today-page">
      <div className="card clock-card">
        <div className="day-label">{longDate(today.day)}</div>

        {open?.dangling && (
          <div className="banner warn">
            <strong>Unclosed period.</strong> You clocked in at {hhmm(open.start)} on{' '}
            {longDate(open.start.slice(0, 10))} and never clocked out, so nothing is being counted
            for it.{' '}
            <Link to={`/day/${open.start.slice(0, 10)}`}>Fix that day</Link> or clock out below.
          </div>
        )}

        <div className={`state ${running ? 'on' : 'off'}`}>
          {running ? (
            <>
              <span className="dot" />
              Working since {hhmm(open!.start)} · <strong>{elapsedLabel(liveSeconds)}</strong>
            </>
          ) : open?.dangling ? (
            <>Open period from {open.start.slice(0, 10)}</>
          ) : (
            <>Not clocked in</>
          )}
        </div>

        <div className="clock-buttons">
          <button
            className="big primary"
            disabled={busy || open !== null}
            onClick={() => act(() => api.clockIn())}
          >
            Clock In
          </button>
          <button
            className="big danger"
            disabled={busy || open === null}
            onClick={() => act(() => api.clockOut())}
          >
            Clock Out
          </button>
        </div>

        {confirmForce && (
          <div className="banner warn">
            <p>{confirmForce}</p>
            <div className="row">
              <button className="danger" disabled={busy} onClick={() => act(() => api.clockOut(true))}>
                Close it at the current time
              </button>
              <Link className="button" to={`/day/${open?.start.slice(0, 10)}`}>
                Edit that day instead
              </Link>
              <button className="linklike" onClick={() => setConfirmForce('')}>
                Cancel
              </button>
            </div>
          </div>
        )}

        {error && <p className="error">{error}</p>}

        <div className="stat-row">
          <div className="stat">
            <span className="stat-label">Worked today</span>
            <span className="stat-value">{hm(liveWorked)}</span>
          </div>
          <div className="stat">
            <span className="stat-label">Target</span>
            <span className="stat-value">{hm(today.target_minutes)}</span>
          </div>
          <div className="stat">
            <span className="stat-label">Deviation</span>
            <span className={`stat-value ${liveDeviation < 0 ? 'neg' : 'pos'}`}>
              {signedHm(liveDeviation)}
            </span>
          </div>
          <div className="stat">
            <span className="stat-label">Balance, all time</span>
            <span
              className={`stat-value ${status.balance_all_time_minutes < 0 ? 'neg' : 'pos'}`}
            >
              {signedHm(status.balance_all_time_minutes)}
            </span>
          </div>
        </div>

        {today.effective_type !== 'workday' && (
          <p className="muted">
            Today is marked <strong>{DAY_TYPE_LABELS[today.effective_type]}</strong>.
          </p>
        )}
      </div>

      <div className="card">
        <div className="card-head">
          <h2>Today’s periods</h2>
          <Link className="button" to={`/day/${today.day}`}>
            Edit day
          </Link>
        </div>
        {today.periods.length === 0 ? (
          <p className="muted">No periods recorded yet.</p>
        ) : (
          <table className="periods">
            <thead>
              <tr>
                <th>Start</th>
                <th>End</th>
                <th className="num">Duration</th>
                <th>Note</th>
              </tr>
            </thead>
            <tbody>
              {today.periods.map((p, i) => (
                <tr key={`${p.period_id}-${i}`}>
                  <td>{p.continues_from_previous_day ? '↳ previous day' : hhmm(p.start)}</td>
                  <td>
                    {p.open ? (
                      <em>running</em>
                    ) : p.continues_to_next_day ? (
                      'next day ↴'
                    ) : (
                      hhmm(p.end)
                    )}
                  </td>
                  <td className="num">{hm(p.open ? Math.floor(liveSeconds / 60) : p.minutes)}</td>
                  <td>{p.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
