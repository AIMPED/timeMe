import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import { hm, isoDate } from '../format'
import type { NominalRate, User } from '../types'

function NominalPanel({ user }: { user: User }) {
  const [rates, setRates] = useState<NominalRate[]>([])
  const [hours, setHours] = useState(String(user.nominal_minutes / 60))
  const [from, setFrom] = useState(isoDate(new Date()))
  const [msg, setMsg] = useState('')

  const load = useCallback(async () => {
    setRates(await api.nominalRates(user.id))
  }, [user.id])

  useEffect(() => {
    void load()
  }, [load])

  async function save() {
    setMsg('')
    try {
      await api.setNominal(user.id, Math.round(Number(hours) * 60), from)
      await load()
      setMsg('Saved. Days before this date keep their old target.')
    } catch (err) {
      setMsg(err instanceof Error ? err.message : 'Could not save')
    }
  }

  return (
    <div className="nominal-panel">
      <div className="row">
        <label>
          Hours/day
          <input
            type="number"
            step="0.25"
            min="0"
            max="24"
            value={hours}
            onChange={(e) => setHours(e.target.value)}
          />
        </label>
        <label>
          From
          <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <button onClick={save}>Set</button>
      </div>
      {msg && <p className="muted small">{msg}</p>}
      <p className="muted small">
        History:{' '}
        {rates.length === 0
          ? 'none'
          : rates.map((r) => `${r.effective_from} → ${hm(r.minutes)}`).join(' · ')}
      </p>
    </div>
  )
}

function UserRow({ user, onChanged }: { user: User; onChanged: () => void }) {
  const [expanded, setExpanded] = useState(false)
  const [name, setName] = useState(user.display_name)
  const [pw, setPw] = useState('')
  const [msg, setMsg] = useState('')

  async function patch(body: Parameters<typeof api.updateUser>[1]) {
    setMsg('')
    try {
      await api.updateUser(user.id, body)
      onChanged()
    } catch (err) {
      setMsg(err instanceof Error ? err.message : 'Could not update')
    }
  }

  async function resetPassword() {
    setMsg('')
    try {
      await api.resetPassword(user.id, pw)
      setPw('')
      setMsg('Password reset.')
    } catch (err) {
      setMsg(err instanceof Error ? err.message : 'Could not reset the password')
    }
  }

  return (
    <>
      <tr className={user.is_active ? undefined : 'disabled-row'}>
        <td>
          <button className="linklike" onClick={() => setExpanded(!expanded)}>
            {expanded ? '▾' : '▸'} {user.username}
          </button>
        </td>
        <td>{user.display_name}</td>
        <td className="num">{hm(user.nominal_minutes)}</td>
        <td>{user.is_admin ? 'admin' : 'user'}</td>
        <td>{user.is_active ? 'active' : 'disabled'}</td>
        <td className="actions">
          <button onClick={() => patch({ is_active: !user.is_active })}>
            {user.is_active ? 'Disable' : 'Enable'}
          </button>
          <button onClick={() => patch({ is_admin: !user.is_admin })}>
            {user.is_admin ? 'Revoke admin' : 'Make admin'}
          </button>
        </td>
      </tr>
      {expanded && (
        <tr className="expanded">
          <td colSpan={6}>
            {msg && <p className="muted small">{msg}</p>}
            <div className="row">
              <label>
                Display name
                <input value={name} onChange={(e) => setName(e.target.value)} />
              </label>
              <button disabled={name === user.display_name} onClick={() => patch({ display_name: name })}>
                Rename
              </button>
              <label>
                New password
                <input
                  type="password"
                  value={pw}
                  onChange={(e) => setPw(e.target.value)}
                  autoComplete="new-password"
                />
              </label>
              <button className="danger" disabled={pw.length < 8} onClick={resetPassword}>
                Reset password
              </button>
            </div>
            <NominalPanel user={user} />
          </td>
        </tr>
      )}
    </>
  )
}

export default function Admin() {
  const [users, setUsers] = useState<User[]>([])
  const [error, setError] = useState('')
  const [form, setForm] = useState({
    username: '',
    password: '',
    display_name: '',
    is_admin: false,
    hours: '7',
  })

  const load = useCallback(async () => {
    try {
      setUsers(await api.users())
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load users')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function create(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    try {
      await api.createUser({
        username: form.username,
        password: form.password,
        display_name: form.display_name,
        is_admin: form.is_admin,
        nominal_minutes: Math.round(Number(form.hours) * 60),
      })
      setForm({ username: '', password: '', display_name: '', is_admin: false, hours: '7' })
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create the user')
    }
  }

  return (
    <div className="page">
      <div className="card">
        <h2>Users</h2>
        {error && <p className="error">{error}</p>}
        <table className="periods">
          <thead>
            <tr>
              <th>Username</th>
              <th>Name</th>
              <th className="num">Nominal</th>
              <th>Role</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <UserRow key={u.id} user={u} onChanged={load} />
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h2>Add a user</h2>
        <form className="row" onSubmit={create}>
          <label>
            Username
            <input
              value={form.username}
              onChange={(e) => setForm({ ...form, username: e.target.value })}
              pattern="[A-Za-z0-9._\-]+"
              required
            />
          </label>
          <label>
            Display name
            <input
              value={form.display_name}
              onChange={(e) => setForm({ ...form, display_name: e.target.value })}
            />
          </label>
          <label>
            Password
            <input
              type="password"
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              minLength={8}
              autoComplete="new-password"
              required
            />
          </label>
          <label>
            Hours/day
            <input
              type="number"
              step="0.25"
              min="0"
              max="24"
              value={form.hours}
              onChange={(e) => setForm({ ...form, hours: e.target.value })}
            />
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={form.is_admin}
              onChange={(e) => setForm({ ...form, is_admin: e.target.checked })}
            />
            Admin
          </label>
          <button className="primary" type="submit">
            Create
          </button>
        </form>
      </div>
    </div>
  )
}
