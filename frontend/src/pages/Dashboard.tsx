import { useState, useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { API } from '../api'

export default function Dashboard() {
  const [userData, setUserData] = useState<any>(null)
  const [config, setConfig] = useState<any>(null)
  const [sessions, setSessions] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()

  useEffect(() => {
    const token = localStorage.getItem('ai_hacker_token')
    if (!token) {
      navigate('/login')
      return
    }
    const headers = { 'Authorization': `Bearer ${token}` }
    Promise.all([
      fetch(`${API}/api/user`, { headers }).then(r => r.ok ? r.json() : null),
      fetch(`${API}/api/config`, { headers }).then(r => r.ok ? r.json() : null),
      fetch(`${API}/api/sessions`, { headers }).then(r => r.ok ? r.json() : []),
    ]).then(([user, cfg, sess]) => {
      if (user) setUserData(user)
      if (cfg) setConfig(cfg)
      setSessions(sess || [])
      setLoading(false)
    }).catch(() => {
      setLoading(false)
    })
  }, [navigate])

  if (loading) {
    return (
      <div className="dashboard">
        <h2>◉ LOADING...</h2>
      </div>
    )
  }

  const active = sessions.filter(s => {
    const age = Date.now() / 1000 - new Date(s.last_active).getTime() / 1000
    return age < 300
  }).length
  const hasAccess = Boolean(userData?.is_pro || config?.is_pro)

  return (
    <div className="dashboard">
      <h2>◉ DASHBOARD — {userData?.username || 'OPERATOR'}</h2>

      <div className="stats-grid">
        <div className="pixel-card stat-card">
          <div className="stat-value" style={{ color: 'var(--green)' }}>{active}</div>
          <div className="stat-label">Active Sessions</div>
        </div>
        <div className="pixel-card stat-card">
          <div className="stat-value" style={{ color: 'var(--blue)' }}>{sessions.reduce((a, s) => a + s.messages, 0)}</div>
          <div className="stat-label">Total Messages</div>
        </div>
        <div className="pixel-card stat-card">
          <div className="stat-value" style={{ color: 'var(--gold)' }}>{sessions.length}</div>
          <div className="stat-label">Total Sessions</div>
        </div>
        <div className="pixel-card stat-card">
          <div className="stat-value" style={{ color: hasAccess ? 'var(--green)' : 'var(--red)' }}>
            {hasAccess ? 'ACTIVE' : 'INACTIVE'}
          </div>
          <div className="stat-label">Access</div>
        </div>
      </div>

      <div className="session-list">
        <h3 style={{ fontFamily: "'Press Start 2P', monospace", fontSize: '0.6rem', color: 'var(--green)', marginBottom: '16px' }}>
          RECENT OPERATIONS
        </h3>
        {sessions.length === 0 && (
          <p style={{ color: 'var(--text-dim)', fontSize: '0.85rem', textAlign: 'center', padding: '40px' }}>
            No sessions yet. Start a new operation.
          </p>
        )}
        {sessions.map((s, i) => (
          <Link to="/playground" key={i} className="session-item" style={{ textDecoration: 'none' }}>
            <div>
              <span className="status-dot active" />
              <span className="name">{s.project?.split('/').pop() || s.id?.slice(0, 12)}</span>
            </div>
            <div className="meta">
              {s.model || 'default'} · {s.messages || 0} msgs
            </div>
          </Link>
        ))}
      </div>

      <div style={{ textAlign: 'center', marginTop: '30px' }}>
        <Link to="/playground" className="pixel-btn primary" style={{ fontSize: '0.6rem' }}>
          ▶ NEW OPERATION
        </Link>
        {config?.role === 'admin' || config?.role === 'owner' ? (
          <Link to="/admin" className="pixel-btn" style={{ fontSize: '0.6rem', marginLeft: '8px' }}>
            ⚡ ADMIN
          </Link>
        ) : null}
      </div>
    </div>
  )
}
