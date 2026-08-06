import { useState } from 'react'
import { api } from '../api'
import { useAuth } from '../auth'
import { hm } from '../format'

export default function Account() {
  const { user } = useAuth()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [repeat, setRepeat] = useState('')
  const [msg, setMsg] = useState('')
  const [error, setError] = useState('')

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setMsg('')
    setError('')
    if (next !== repeat) {
      setError('The new passwords do not match')
      return
    }
    try {
      await api.changePassword(current, next)
      setCurrent('')
      setNext('')
      setRepeat('')
      setMsg('Password changed.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not change the password')
    }
  }

  return (
    <div className="page">
      <div className="card">
        <h2>Account</h2>
        <p className="muted">
          Signed in as <strong>{user?.username}</strong> · nominal{' '}
          {hm(user?.nominal_minutes ?? 0)} per workday
          {user?.is_admin && ' · administrator'}
        </p>
      </div>

      <div className="card">
        <h2>Change password</h2>
        <form className="stack" onSubmit={submit}>
          <label>
            Current password
            <input
              type="password"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              autoComplete="current-password"
              required
            />
          </label>
          <label>
            New password
            <input
              type="password"
              value={next}
              onChange={(e) => setNext(e.target.value)}
              minLength={8}
              autoComplete="new-password"
              required
            />
          </label>
          <label>
            Repeat new password
            <input
              type="password"
              value={repeat}
              onChange={(e) => setRepeat(e.target.value)}
              minLength={8}
              autoComplete="new-password"
              required
            />
          </label>
          {error && <p className="error">{error}</p>}
          {msg && <p className="muted">{msg}</p>}
          <button className="primary" type="submit">
            Change password
          </button>
        </form>
      </div>
    </div>
  )
}
