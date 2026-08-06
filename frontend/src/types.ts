export type DayTypeMark = 'workday' | 'half_day' | 'vacation' | 'sick' | 'holiday' | 'off'
export type EffectiveType = DayTypeMark | 'weekend'

export interface User {
  id: number
  username: string
  display_name: string
  is_admin: boolean
  is_active: boolean
  nominal_minutes: number
}

export interface PeriodOut {
  period_id: number
  start: string | null
  end: string | null
  minutes: number
  open: boolean
  note: string
  source: string
  continues_from_previous_day: boolean
  continues_to_next_day: boolean
  full_start: string
  full_end: string | null
}

export interface DayOut {
  day: string
  in_month: boolean
  worked_minutes: number
  target_minutes: number
  deviation_minutes: number
  day_type: DayTypeMark | null
  effective_type: EffectiveType
  note: string
  incomplete: boolean
  running: boolean
  is_future: boolean
  periods: PeriodOut[]
}

export interface Totals {
  worked_minutes: number
  target_minutes: number
  deviation_minutes: number
  days_counted: number
  vacation_days: number
  sick_days: number
  holiday_days: number
  incomplete_days: number
}

export interface Week {
  iso_year: number
  iso_week: number
  start: string
  end: string
  days: DayOut[]
  totals: Totals
}

export interface CalendarMonth {
  year: number
  month: number
  weeks: Week[]
  month_totals: Totals
  month_absences: Totals
  month_target_full_minutes: number
  balance_through_month_end_minutes: number
  balance_all_time_minutes: number
  nominal_minutes: number
}

export interface DayDetail {
  day: DayOut
  nominal_minutes: number
}

export interface ClockStatus {
  now: string
  open_period: {
    period_id: number
    start: string
    elapsed_minutes: number
    dangling: boolean
  } | null
  today: DayOut
  balance_all_time_minutes: number
}

export interface NominalRate {
  effective_from: string
  minutes: number
}
