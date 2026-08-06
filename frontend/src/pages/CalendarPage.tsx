import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { DAY_TYPE_LABELS, MONTH_NAMES, WEEKDAY_NAMES, hm, isoDate, signedHm } from '../format'
import type { CalendarMonth, DayOut } from '../types'

const SHORT_TYPE: Partial<Record<string, string>> = {
  vacation: 'VAC',
  sick: 'SICK',
  holiday: 'HOL',
  half_day: '½',
  off: 'OFF',
  workday: 'WORK',
}

function DayCell({ day, onOpen }: { day: DayOut; onOpen: (d: string) => void }) {
  const classes = ['day-cell', day.effective_type]
  if (!day.in_month) classes.push('other-month')
  if (day.is_future) classes.push('future')
  if (day.incomplete) classes.push('incomplete')
  if (day.running) classes.push('running')
  if (isoDate(new Date()) === day.day) classes.push('today')

  const showDeviation = !day.is_future && (day.target_minutes > 0 || day.worked_minutes > 0)

  return (
    <button className={classes.join(' ')} onClick={() => onOpen(day.day)} title={day.note}>
      <span className="dnum">{Number(day.day.slice(8, 10))}</span>
      {day.day_type && day.day_type !== 'workday' && (
        <span className="badge">{SHORT_TYPE[day.day_type]}</span>
      )}
      {day.day_type === 'workday' && day.effective_type === 'workday' && (
        <span className="badge faint">{SHORT_TYPE.workday}</span>
      )}
      <span className="worked">{day.worked_minutes > 0 ? hm(day.worked_minutes) : ''}</span>
      {showDeviation && (
        <span className={`dev ${day.deviation_minutes < 0 ? 'neg' : 'pos'}`}>
          {signedHm(day.deviation_minutes)}
        </span>
      )}
      {day.incomplete && <span className="flag" title="Unclosed period">!</span>}
    </button>
  )
}

export default function CalendarPage() {
  const { year: yearParam, month: monthParam } = useParams()
  const navigate = useNavigate()
  const year = Number(yearParam)
  const month = Number(monthParam)
  const [data, setData] = useState<CalendarMonth | null>(null)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      setData(await api.calendar(year, month))
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load the month')
    }
  }, [year, month])

  useEffect(() => {
    void load()
  }, [load])

  function shift(delta: number) {
    const d = new Date(year, month - 1 + delta, 1)
    navigate(`/calendar/${d.getFullYear()}/${d.getMonth() + 1}`)
  }

  if (error) return <div className="boot error">{error}</div>
  if (!data) return <div className="boot">Loading…</div>

  const t = data.month_totals

  return (
    <div className="page">
      <div className="card">
        <div className="month-head">
          <div className="month-nav">
            <button onClick={() => shift(-1)} aria-label="Previous month">
              ‹
            </button>
            <h2>
              {MONTH_NAMES[month - 1]} {year}
            </h2>
            <button onClick={() => shift(1)} aria-label="Next month">
              ›
            </button>
            <button
              className="linklike"
              onClick={() => {
                const now = new Date()
                navigate(`/calendar/${now.getFullYear()}/${now.getMonth() + 1}`)
              }}
            >
              Today
            </button>
          </div>
          <div className="exports">
            <a className="button" href={api.exportUrl(year, month, 'days')}>
              CSV: days
            </a>
            <a className="button" href={api.exportUrl(year, month, 'periods')}>
              CSV: periods
            </a>
          </div>
        </div>

        <div className="stat-row">
          <div className="stat">
            <span className="stat-label">Worked</span>
            <span className="stat-value">{hm(t.worked_minutes)}</span>
          </div>
          <div className="stat">
            <span className="stat-label">Target so far</span>
            <span className="stat-value">{hm(t.target_minutes)}</span>
          </div>
          <div className="stat">
            <span className="stat-label">Month deviation</span>
            <span className={`stat-value ${t.deviation_minutes < 0 ? 'neg' : 'pos'}`}>
              {signedHm(t.deviation_minutes)}
            </span>
          </div>
          <div className="stat">
            <span className="stat-label">Balance to month end</span>
            <span
              className={`stat-value ${
                data.balance_through_month_end_minutes < 0 ? 'neg' : 'pos'
              }`}
            >
              {signedHm(data.balance_through_month_end_minutes)}
            </span>
          </div>
          <div className="stat">
            <span className="stat-label">Balance, all time</span>
            <span className={`stat-value ${data.balance_all_time_minutes < 0 ? 'neg' : 'pos'}`}>
              {signedHm(data.balance_all_time_minutes)}
            </span>
          </div>
        </div>

        <p className="muted small">
          Whole month asks for {hm(data.month_target_full_minutes)} at {hm(data.nominal_minutes)}
          /day · {data.month_absences.vacation_days} vacation ·{' '}
          {data.month_absences.sick_days} sick · {data.month_absences.holiday_days} holiday
          {t.incomplete_days > 0 && (
            <>
              {' '}
              · <span className="warn-text">{t.incomplete_days} day(s) with an unclosed period</span>
            </>
          )}
        </p>
      </div>

      <div className="card">
        <div className="calendar-grid">
          <div className="grid-head">
            {WEEKDAY_NAMES.map((w) => (
              <div key={w} className="wd">
                {w}
              </div>
            ))}
            <div className="wd week-col">Week</div>
          </div>
          {data.weeks.map((week) => (
            <div className="grid-row" key={`${week.iso_year}-${week.iso_week}`}>
              {week.days.map((day) => (
                <DayCell key={day.day} day={day} onOpen={(d) => navigate(`/day/${d}`)} />
              ))}
              <div className="week-total">
                <span className="wk">W{week.iso_week}</span>
                <span className="worked">{hm(week.totals.worked_minutes)}</span>
                <span
                  className={`dev ${week.totals.deviation_minutes < 0 ? 'neg' : 'pos'}`}
                >
                  {signedHm(week.totals.deviation_minutes)}
                </span>
              </div>
            </div>
          ))}
        </div>
        <div className="legend">
          {(['workday', 'weekend', 'half_day', 'vacation', 'sick', 'holiday', 'off'] as const).map(
            (t2) => (
              <span key={t2} className={`legend-item ${t2}`}>
                {DAY_TYPE_LABELS[t2]}
              </span>
            ),
          )}
          <span className="legend-item incomplete">Unclosed period</span>
        </div>
        <p className="muted small">
          Click any day to edit its periods or mark it. Week totals cover the whole ISO week, including
          days that fall in the neighbouring month.{' '}
          <Link to="/">Back to today</Link>
        </p>
      </div>
    </div>
  )
}
