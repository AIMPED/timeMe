import type {
  CalendarMonth,
  ClockStatus,
  DayDetail,
  DayTypeMark,
  NominalRate,
  User,
} from './types'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    credentials: 'same-origin',
    headers: init.body ? { 'Content-Type': 'application/json' } : undefined,
    ...init,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') detail = body.detail
      else if (Array.isArray(body.detail) && body.detail[0]?.msg) detail = body.detail[0].msg
    } catch {
      /* a non-JSON error body is not worth reporting verbatim */
    }
    throw new ApiError(res.status, detail)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

export const api = {
  login: (username: string, password: string) =>
    post<User>('/api/auth/login', { username, password }),
  logout: () => post<void>('/api/auth/logout'),
  me: () => request<User>('/api/auth/me'),
  changePassword: (current_password: string, new_password: string) =>
    post<void>('/api/auth/password', { current_password, new_password }),

  status: () => request<ClockStatus>('/api/clock/status'),
  clockIn: () => post<ClockStatus>('/api/clock/in'),
  clockOut: (force = false) => post<ClockStatus>(`/api/clock/out${force ? '?force=true' : ''}`),

  calendar: (year: number, month: number) =>
    request<CalendarMonth>(`/api/calendar?year=${year}&month=${month}`),
  day: (day: string) => request<DayDetail>(`/api/days/${day}`),
  addPeriod: (day: string, start: string, end: string | null, note: string) =>
    post<DayDetail>(`/api/days/${day}/periods`, { start, end, note }),
  updatePeriod: (
    id: number,
    body: { start?: string; end?: string | null; clear_end?: boolean; note?: string },
  ) => request<DayDetail>(`/api/periods/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deletePeriod: (id: number) => request<void>(`/api/periods/${id}`, { method: 'DELETE' }),
  setMark: (day: string, day_type: DayTypeMark | null, note = '') =>
    request<DayDetail>(`/api/days/${day}/mark`, {
      method: 'PUT',
      body: JSON.stringify({ day_type, note }),
    }),

  exportUrl: (year: number, month: number, detail: 'days' | 'periods') =>
    `/api/export/month.csv?year=${year}&month=${month}&detail=${detail}`,

  users: () => request<User[]>('/api/admin/users'),
  createUser: (body: {
    username: string
    password: string
    display_name: string
    is_admin: boolean
    nominal_minutes: number
  }) => post<User>('/api/admin/users', body),
  updateUser: (id: number, body: { display_name?: string; is_admin?: boolean; is_active?: boolean }) =>
    request<User>(`/api/admin/users/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  resetPassword: (id: number, new_password: string) =>
    post<void>(`/api/admin/users/${id}/password`, { new_password }),
  nominalRates: (id: number) => request<NominalRate[]>(`/api/admin/users/${id}/nominal`),
  setNominal: (id: number, minutes: number, effective_from: string) =>
    request<User>(`/api/admin/users/${id}/nominal`, {
      method: 'PUT',
      body: JSON.stringify({ minutes, effective_from }),
    }),
}
