import { NavLink, Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import { useAuth } from './auth'
import { isoDate } from './format'
import Login from './pages/Login'
import Today from './pages/Today'
import CalendarPage from './pages/CalendarPage'
import DayEditor from './pages/DayEditor'
import Admin from './pages/Admin'
import Account from './pages/Account'

function Shell({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const now = new Date()

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          time<span>Me</span>
        </div>
        <nav>
          <NavLink to="/" end>
            Today
          </NavLink>
          <NavLink to={`/calendar/${now.getFullYear()}/${now.getMonth() + 1}`}>Calendar</NavLink>
          {user?.is_admin && <NavLink to="/admin">Admin</NavLink>}
        </nav>
        <div className="topbar-right">
          <button className="linklike" onClick={() => navigate('/account')}>
            {user?.display_name}
          </button>
          <button
            className="linklike"
            onClick={async () => {
              await logout()
              navigate('/login')
            }}
          >
            Sign out
          </button>
        </div>
      </header>
      <main>{children}</main>
    </div>
  )
}

export default function App() {
  const { user, loading } = useAuth()

  if (loading) {
    return <div className="boot">Loading…</div>
  }

  if (!user) {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    )
  }

  return (
    <Shell>
      <Routes>
        <Route path="/" element={<Today />} />
        <Route path="/login" element={<Navigate to="/" replace />} />
        <Route path="/calendar/:year/:month" element={<CalendarPage />} />
        <Route path="/day/:day" element={<DayEditor />} />
        <Route path="/account" element={<Account />} />
        <Route
          path="/admin"
          element={user.is_admin ? <Admin /> : <Navigate to="/" replace />}
        />
        <Route path="*" element={<Navigate to={`/day/${isoDate(new Date())}`} replace />} />
      </Routes>
    </Shell>
  )
}
