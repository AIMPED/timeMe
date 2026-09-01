import type { EffectiveType } from './types'

/** 435 -> "7:15". Negative values keep the sign in front. */
export function hm(minutes: number): string {
  const sign = minutes < 0 ? '-' : ''
  const abs = Math.abs(Math.round(minutes))
  return `${sign}${Math.floor(abs / 60)}:${String(abs % 60).padStart(2, '0')}`
}

/** Deviations always show their sign, so +0:15 reads differently from 0:15. */
export function signedHm(minutes: number): string {
  const rounded = Math.round(minutes)
  return `${rounded > 0 ? '+' : ''}${hm(rounded)}`
}

export function hhmm(iso: string | null): string {
  if (!iso) return ''
  return iso.slice(11, 16)
}

export function isoDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(
    d.getDate(),
  ).padStart(2, '0')}`
}

export function parseIsoDate(s: string): Date {
  const [y, m, d] = s.split('-').map(Number)
  return new Date(y, m - 1, d)
}

/** The ISO date one day after the given one. */
export function nextIsoDay(iso: string): string {
  const d = parseIsoDate(iso)
  d.setDate(d.getDate() + 1)
  return isoDate(d)
}

/** Minutes from one "HH:MM" to a later one on the same day. */
export function minutesBetween(start: string, end: string): number {
  const mins = (s: string) => Number(s.slice(0, 2)) * 60 + Number(s.slice(3, 5))
  return mins(end) - mins(start)
}

/**
 * Which day an end time falls on, given the start. An end at or before the
 * start means the period ran past midnight.
 */
export function endIsoDay(startDay: string, startTime: string, endTime: string): string {
  return endTime <= startTime ? nextIsoDay(startDay) : startDay
}

export const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

export const WEEKDAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

export const DAY_TYPE_LABELS: Record<EffectiveType, string> = {
  workday: 'Workday',
  weekend: 'Weekend',
  half_day: 'Half day',
  vacation: 'Vacation',
  sick: 'Sick',
  holiday: 'Public holiday',
  off: 'Off',
}

export function longDate(iso: string): string {
  const d = parseIsoDate(iso)
  return `${WEEKDAY_NAMES[(d.getDay() + 6) % 7]}, ${d.getDate()} ${MONTH_NAMES[d.getMonth()]} ${d.getFullYear()}`
}
