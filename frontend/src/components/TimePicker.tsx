import { useEffect, useMemo, useRef, useState } from 'react'

/**
 * A clock-dial time picker in the shape Android has used since Material 3:
 * a big HH:MM readout you tap to choose which half you are editing, a dial you
 * drag a hand around, and a keyboard toggle for people who would rather type.
 *
 * 24-hour only — the rest of the app never shows AM/PM. The dial carries two
 * rings in hour mode: 00–11 outside, 12–23 inside.
 */

const DIAL = 256 // px, the dial's box
const CENTER = DIAL / 2
const R_OUTER = 100
const R_INNER = 62
/** Anything closer to the middle than this picks the inner (12–23) ring. */
const RING_SPLIT = (R_OUTER + R_INNER) / 2

type Mode = 'hour' | 'minute'

const pad = (n: number) => String(n).padStart(2, '0')

/** "09:30" -> [9, 30]. Anything unparsable falls back to 09:00. */
function parse(value: string): [number, number] {
  const m = /^(\d{1,2}):(\d{2})$/.exec(value.trim())
  if (!m) return [9, 0]
  const h = Math.min(23, Number(m[1]))
  const min = Math.min(59, Number(m[2]))
  return [h, min]
}

/** Where a value sits on its ring, as an offset from the dial's centre. */
function polar(fraction: number, radius: number): { x: number; y: number } {
  const angle = fraction * 2 * Math.PI
  return { x: Math.sin(angle) * radius, y: -Math.cos(angle) * radius }
}

function Dial({
  mode,
  hour,
  minute,
  onPick,
  onCommit,
}: {
  mode: Mode
  hour: number
  minute: number
  /** Fires continuously while dragging. */
  onPick: (v: number) => void
  /** Fires when the finger lifts, so the caller can advance hour -> minute. */
  onCommit: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)

  const isHour = mode === 'hour'
  const inner = isHour && hour >= 12
  const handRadius = inner ? R_INNER : R_OUTER
  const fraction = isHour ? (hour % 12) / 12 : minute / 60

  function valueAt(clientX: number, clientY: number): number {
    const box = ref.current?.getBoundingClientRect()
    if (!box) return isHour ? hour : minute
    const dx = clientX - (box.left + box.width / 2)
    const dy = clientY - (box.top + box.height / 2)
    // Degrees clockwise from 12 o'clock.
    let deg = (Math.atan2(dx, -dy) * 180) / Math.PI
    if (deg < 0) deg += 360

    if (!isHour) return Math.round(deg / 6) % 60
    const slot = Math.round(deg / 30) % 12
    const ring = Math.hypot(dx, dy) < RING_SPLIT ? 12 : 0
    return slot + ring
  }

  function onPointerDown(e: React.PointerEvent) {
    dragging.current = true
    onPick(valueAt(e.clientX, e.clientY))
    // Capture keeps the drag alive past the dial's edge. Not worth failing the
    // pick over if the pointer is already gone.
    try {
      ref.current?.setPointerCapture(e.pointerId)
    } catch {
      /* no capture; moves inside the dial still work */
    }
  }

  function onPointerMove(e: React.PointerEvent) {
    if (dragging.current) onPick(valueAt(e.clientX, e.clientY))
  }

  function onPointerUp(e: React.PointerEvent) {
    if (!dragging.current) return
    dragging.current = false
    if (ref.current?.hasPointerCapture(e.pointerId)) ref.current.releasePointerCapture(e.pointerId)
    onCommit()
  }

  function onKeyDown(e: React.KeyboardEvent) {
    const span = isHour ? 24 : 60
    const step = e.key === 'ArrowUp' || e.key === 'ArrowRight' ? 1 : -1
    if (!['ArrowUp', 'ArrowRight', 'ArrowDown', 'ArrowLeft'].includes(e.key)) return
    e.preventDefault()
    onPick((((isHour ? hour : minute) + step) % span + span) % span)
  }

  // Hour mode draws both rings; minute mode labels every fifth minute.
  const labels = useMemo(() => {
    if (isHour) {
      return Array.from({ length: 24 }, (_, h) => ({
        value: h,
        text: pad(h),
        radius: h >= 12 ? R_INNER : R_OUTER,
        fraction: (h % 12) / 12,
        small: h >= 12,
      }))
    }
    return Array.from({ length: 12 }, (_, i) => ({
      value: i * 5,
      text: pad(i * 5),
      radius: R_OUTER,
      fraction: i / 12,
      small: false,
    }))
  }, [isHour])

  const selected = isHour ? hour : minute
  // A minute that is not a multiple of five gets no label, so the hand needs a
  // dot of its own to show where it landed.
  const onLabel = isHour || selected % 5 === 0

  return (
    <div
      ref={ref}
      className="clock-dial"
      style={{ width: DIAL, height: DIAL }}
      role="slider"
      tabIndex={0}
      aria-label={isHour ? 'Hour' : 'Minute'}
      aria-valuenow={selected}
      aria-valuemin={0}
      aria-valuemax={isHour ? 23 : 59}
      aria-valuetext={isHour ? `${pad(selected)} hours` : `${pad(selected)} minutes`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onKeyDown={onKeyDown}
    >
      <div
        className="clock-hand"
        style={{
          height: handRadius,
          transform: `translateX(-50%) rotate(${fraction * 360}deg)`,
        }}
      >
        <span className={`clock-knob ${onLabel ? '' : 'bare'}`} />
      </div>
      <span className="clock-pin" />
      {labels.map((l) => {
        const p = polar(l.fraction, l.radius)
        return (
          <span
            key={l.value}
            className={`clock-num ${l.small ? 'small' : ''} ${
              l.value === selected ? 'on' : ''
            }`}
            style={{ left: CENTER + p.x, top: CENTER + p.y }}
          >
            {l.text}
          </span>
        )
      })}
    </div>
  )
}

export function TimePickerDialog({
  title,
  value,
  onCancel,
  onConfirm,
}: {
  title: string
  value: string
  onCancel: () => void
  onConfirm: (value: string) => void
}) {
  const initial = parse(value)
  const [hour, setHour] = useState(initial[0])
  const [minute, setMinute] = useState(initial[1])
  const [mode, setMode] = useState<Mode>('hour')
  const [typing, setTyping] = useState(false)

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.stopPropagation()
        onCancel()
      }
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [onCancel])

  function pick(v: number) {
    if (mode === 'hour') setHour(v)
    else setMinute(v)
  }

  return (
    <div className="tp-scrim" onPointerDown={onCancel}>
      <div
        className="tp-sheet"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onPointerDown={(e) => e.stopPropagation()}
      >
        <p className="tp-title">{title}</p>

        {typing ? (
          <div className="tp-typed">
            <label>
              Hour
              <input
                type="number"
                min={0}
                max={23}
                value={pad(hour)}
                autoFocus
                onChange={(e) =>
                  setHour(Math.max(0, Math.min(23, Number(e.target.value) || 0)))
                }
              />
            </label>
            <span className="tp-colon">:</span>
            <label>
              Minute
              <input
                type="number"
                min={0}
                max={59}
                value={pad(minute)}
                onChange={(e) =>
                  setMinute(Math.max(0, Math.min(59, Number(e.target.value) || 0)))
                }
              />
            </label>
          </div>
        ) : (
          <>
            <div className="tp-readout">
              <button
                className={`tp-part ${mode === 'hour' ? 'on' : ''}`}
                onClick={() => setMode('hour')}
              >
                {pad(hour)}
              </button>
              <span className="tp-colon">:</span>
              <button
                className={`tp-part ${mode === 'minute' ? 'on' : ''}`}
                onClick={() => setMode('minute')}
              >
                {pad(minute)}
              </button>
            </div>
            <Dial
              mode={mode}
              hour={hour}
              minute={minute}
              onPick={pick}
              onCommit={() => mode === 'hour' && setMode('minute')}
            />
          </>
        )}

        <div className="tp-actions">
          <button
            className="linklike tp-toggle"
            title={typing ? 'Pick on the dial' : 'Type the time'}
            onClick={() => setTyping(!typing)}
          >
            {typing ? '◷ Dial' : '⌨ Keyboard'}
          </button>
          <span className="grow" />
          <button onClick={onCancel}>Cancel</button>
          <button className="primary" onClick={() => onConfirm(`${pad(hour)}:${pad(minute)}`)}>
            OK
          </button>
        </div>
      </div>
    </div>
  )
}

/** A read-only field showing a time; tapping it opens the dial. */
export default function TimeField({
  label,
  value,
  onChange,
}: {
  label: string
  value: string
  onChange: (value: string) => void
}) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button className="time-field" onClick={() => setOpen(true)}>
        <span className="tf-label">{label}</span>
        <span className="tf-value">{value || '--:--'}</span>
      </button>
      {open && (
        <TimePickerDialog
          title={`Select ${label.toLowerCase()}`}
          value={value}
          onCancel={() => setOpen(false)}
          onConfirm={(v) => {
            onChange(v)
            setOpen(false)
          }}
        />
      )}
    </>
  )
}
