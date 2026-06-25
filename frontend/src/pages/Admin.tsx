import { useState, useEffect } from 'react'

import { API } from '../api'

interface AdminUser {
  id: string
  username: string
  role: string
  subscription: string
  pro_expiry: number
  sub_expires_at: number
  created_at: number
  is_pro: boolean
}

interface AdminContainer {
  id: string
  lxc_name: string
  username: string
  private_ip: string
  status: string
  mem_mb: number
  cpu: number
  disk_gb: number
  created_at: number
  last_active_at: number
}

export default function AdminPage() {
  const [users, setUsers] = useState<AdminUser[]>([])
  const [containers, setContainers] = useState<AdminContainer[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [actionMsg, setActionMsg] = useState('')
  const [newUsername, setNewUsername] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [newDays, setNewDays] = useState(365)

  const token = () => localStorage.getItem('ai_hacker_token') || ''

  const fetchAdmin = async () => {
    setLoading(true)
    setError('')
    try {
      const headers = { Authorization: `Bearer ${token()}` }
      const [usersRes, containersRes] = await Promise.all([
        fetch(`${API}/api/admin/users`, { headers }),
        fetch(`${API}/api/admin/containers`, { headers }),
      ])
      if (!usersRes.ok) {
        const d = await usersRes.json()
        throw new Error(d.detail || 'Failed to load users')
      }
      const usersData = await usersRes.json()
      setUsers(usersData.users || [])
      if (containersRes.ok) {
        const containersData = await containersRes.json()
        setContainers(containersData.containers || [])
      }
    } catch (err: any) {
      setError(err.message)
    }
    setLoading(false)
  }

  useEffect(() => { fetchAdmin() }, [])

  const doAction = async (url: string, body: any, msg: string) => {
    setActionMsg(msg)
    try {
      const r = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token()}` },
        body: JSON.stringify(body),
      })
      if (!r.ok) {
        const d = await r.json()
        throw new Error(d.detail || 'Action failed')
      }
      await fetchAdmin()
      setActionMsg('Done')
    } catch (err: any) {
      setActionMsg(`Error: ${err.message}`)
    }
    setTimeout(() => setActionMsg(''), 3000)
  }

  const promote = (uid: string) => doAction(`${API}/api/admin/users/${uid}/promote`, { role: 'pro', days: 30 }, 'Promoting...')
  const restrict = (uid: string) => doAction(`${API}/api/admin/users/${uid}/unset-expiry`, {}, 'Restricting...')
  const setMonth = (uid: string) => doAction(`${API}/api/admin/users/${uid}/set-expiry`, { timestamp: 0 }, 'Setting 30 days...')
  const stopContainer = (name: string) => doAction(`${API}/api/admin/containers/${name}/stop`, {}, 'Stopping container...')
  const deleteContainer = (name: string) => doAction(`${API}/api/admin/containers/${name}/delete`, {}, 'Deleting container...')

  const createUser = async (e: React.FormEvent) => {
    e.preventDefault()
    await doAction(`${API}/api/admin/users/create`, {
      username: newUsername,
      password: newPassword,
      pro_expiry_days: newDays,
    }, 'Creating user...')
    setNewUsername('')
    setNewPassword('')
    setNewDays(365)
  }

  const fmtDate = (ts: number) => {
    if (!ts || ts <= 0) return '—'
    return new Date(ts * 1000).toLocaleDateString('en-US', {
      year: 'numeric', month: 'short', day: 'numeric',
    })
  }

  const activeUsers = users.filter(u => u.is_pro).length
  const runningContainers = containers.filter(c => c.status === 'running').length

  const fmtRole = (role: string) => {
    switch (role) {
      case 'owner': return '👑 OWNER'
      case 'admin': return '⚡ ADMIN'
      case 'pro': return '✅ PRO'
      default: return '⛔ RESTRICTED'
    }
  }

  if (loading) {
    return (
      <div className="provision-screen">
        <div style={{ fontFamily: "'Press Start 2P', monospace", fontSize: '0.55rem', color: 'var(--mc-text-dim)' }}>
          ◉ LOADING ADMIN PANEL...
        </div>
      </div>
    )
  }

  return (
    <div style={{ padding: '24px', maxWidth: '1200px', margin: '0 auto' }}>
      <div style={{
        fontFamily: "'Press Start 2P', monospace", fontSize: '0.5rem',
        color: 'var(--mc-gold)', marginBottom: '20px', textShadow: '0 0 10px rgba(255,215,0,0.3)',
      }}>
        ⚡ ADMIN DASHBOARD
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '10px', marginBottom: '18px' }}>
        <div style={statBox}><strong>{users.length}</strong><span>USERS</span></div>
        <div style={statBox}><strong>{activeUsers}</strong><span>ACTIVE PRO</span></div>
        <div style={statBox}><strong>{containers.length}</strong><span>CONTAINERS</span></div>
        <div style={statBox}><strong>{runningContainers}</strong><span>RUNNING</span></div>
      </div>

      {error && (
        <div style={{
          background: '#1a0a0a', border: '2px solid var(--mc-red)', padding: '12px',
          color: 'var(--mc-red)', fontFamily: "'Share Tech Mono', monospace", fontSize: '0.85rem',
          marginBottom: '16px',
        }}>
          ⚠ {error}
        </div>
      )}

      {actionMsg && (
        <div style={{
          background: '#0a1a0a', border: '2px solid var(--mc-green)', padding: '8px 12px',
          color: 'var(--mc-green)', fontFamily: "'Share Tech Mono', monospace", fontSize: '0.8rem',
          marginBottom: '16px', animation: 'pulse 1s infinite',
        }}>
          {actionMsg}
        </div>
      )}

      <form onSubmit={createUser} style={{ marginBottom: '18px', padding: '12px', border: '1px solid var(--mc-border)', background: '#090914', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '8px', alignItems: 'end' }}>
        <label style={formLabel}>USERNAME
          <input className="pixel-input" value={newUsername} onChange={e => setNewUsername(e.target.value)} minLength={3} maxLength={32} required />
        </label>
        <label style={formLabel}>PASSWORD
          <input className="pixel-input" type="password" value={newPassword} onChange={e => setNewPassword(e.target.value)} minLength={8} maxLength={128} required />
        </label>
        <label style={formLabel}>DAYS
          <input className="pixel-input" type="number" value={newDays} onChange={e => setNewDays(Number(e.target.value))} min={1} max={3650} required />
        </label>
        <button className="pixel-btn primary" style={{ fontSize: '0.45rem', padding: '10px 12px' }} type="submit">CREATE PRO USER</button>
      </form>

      <div style={{ fontFamily: "'Press Start 2P', monospace", fontSize: '0.4rem', color: 'var(--mc-green)', margin: '16px 0 8px' }}>
        USERS
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table style={{
          width: '100%', borderCollapse: 'collapse',
          fontFamily: "'Share Tech Mono', monospace", fontSize: '0.75rem',
        }}>
          <thead>
            <tr style={{ borderBottom: '2px solid var(--mc-border)' }}>
              <th style={thStyle}>USERNAME</th>
              <th style={thStyle}>ROLE</th>
              <th style={thStyle}>STATUS</th>
              <th style={thStyle}>EXPIRY</th>
              <th style={thStyle}>CREATED</th>
              <th style={thStyle}>ACTIONS</th>
            </tr>
          </thead>
          <tbody>
            {users.map(u => (
              <tr key={u.id} style={{
                borderBottom: '1px solid var(--mc-border)',
                background: u.role === 'owner' ? 'rgba(255,215,0,0.05)' : u.role === 'admin' ? 'rgba(0,150,255,0.05)' : 'transparent',
              }}>
                <td style={tdStyle}>
                  <span style={{ color: u.role === 'owner' ? 'var(--mc-gold)' : u.role === 'admin' ? '#66b0ff' : 'var(--mc-text)' }}>
                    {u.username}
                  </span>
                </td>
                <td style={tdStyle}>{fmtRole(u.role)}</td>
                <td style={tdStyle}>
                  <span style={{ color: u.is_pro ? 'var(--mc-green)' : 'var(--mc-red)' }}>
                    {u.is_pro ? 'ACTIVE' : 'BLOCKED'}
                  </span>
                </td>
                <td style={tdStyle}>{fmtDate(u.pro_expiry || u.sub_expires_at)}</td>
                <td style={tdStyle}>{fmtDate(u.created_at)}</td>
                <td style={tdStyle}>
                  <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                    {u.role !== 'owner' && u.role !== 'admin' && (
                      <>
                        {!u.is_pro ? (
                          <>
                            <button className="pixel-btn small" style={{ fontSize: '0.35rem', padding: '3px 6px' }} onClick={() => promote(u.id)}>⟐ PROMOTE</button>
                            <button className="pixel-btn small" style={{ fontSize: '0.35rem', padding: '3px 6px', background: '#1a3a1a' }} onClick={() => setMonth(u.id)}>📅 +30D</button>
                          </>
                        ) : (
                          <>
                            <button className="pixel-btn small" style={{ fontSize: '0.35rem', padding: '3px 6px', background: '#1a3a1a' }} onClick={() => setMonth(u.id)}>📅 +30D</button>
                            <button className="pixel-btn danger small" style={{ fontSize: '0.35rem', padding: '3px 6px' }} onClick={() => restrict(u.id)}>✕ RESTRICT</button>
                          </>
                        )}
                      </>
                    )}
                    {u.role === 'owner' && <span style={{ color: 'var(--mc-gold)', fontSize: '0.35rem' }}>—</span>}
                    {u.role === 'admin' && <span style={{ color: '#66b0ff', fontSize: '0.35rem' }}>—</span>}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {users.length === 0 && !loading && (
        <div style={{
          textAlign: 'center', padding: '40px', color: 'var(--mc-text-dim)',
          fontFamily: "'Share Tech Mono', monospace", fontSize: '0.85rem',
        }}>
          No users found.
        </div>
      )}

      <div style={{ fontFamily: "'Press Start 2P', monospace", fontSize: '0.4rem', color: 'var(--mc-green)', margin: '24px 0 8px' }}>
        CONTAINERS
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table style={{
          width: '100%', borderCollapse: 'collapse',
          fontFamily: "'Share Tech Mono', monospace", fontSize: '0.75rem',
        }}>
          <thead>
            <tr style={{ borderBottom: '2px solid var(--mc-border)' }}>
              <th style={thStyle}>NAME</th>
              <th style={thStyle}>USER</th>
              <th style={thStyle}>STATUS</th>
              <th style={thStyle}>IP</th>
              <th style={thStyle}>SIZE</th>
              <th style={thStyle}>LAST ACTIVE</th>
              <th style={thStyle}>ACTIONS</th>
            </tr>
          </thead>
          <tbody>
            {containers.map(c => (
              <tr key={c.id} style={{ borderBottom: '1px solid var(--mc-border)' }}>
                <td style={tdStyle}>{c.lxc_name}</td>
                <td style={tdStyle}>{c.username}</td>
                <td style={tdStyle}>
                  <span style={{ color: c.status === 'running' ? 'var(--mc-green)' : 'var(--mc-red)' }}>{c.status.toUpperCase()}</span>
                </td>
                <td style={tdStyle}>{c.private_ip || '—'}</td>
                <td style={tdStyle}>{c.cpu} CPU / {c.mem_mb}MB / {c.disk_gb}GB</td>
                <td style={tdStyle}>{fmtDate(c.last_active_at)}</td>
                <td style={tdStyle}>
                  <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                    {c.status === 'running' && (
                      <button className="pixel-btn small" style={{ fontSize: '0.35rem', padding: '3px 6px' }} onClick={() => stopContainer(c.lxc_name)}>STOP</button>
                    )}
                    {c.status !== 'deleted' && (
                      <button className="pixel-btn danger small" style={{ fontSize: '0.35rem', padding: '3px 6px' }} onClick={() => deleteContainer(c.lxc_name)}>DELETE</button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {containers.length === 0 && !loading && (
        <div style={{
          textAlign: 'center', padding: '24px', color: 'var(--mc-text-dim)',
          fontFamily: "'Share Tech Mono', monospace", fontSize: '0.85rem',
        }}>
          No containers found.
        </div>
      )}

      <div style={{ marginTop: '24px', padding: '12px', border: '1px solid var(--mc-border)', background: '#0d0d1a' }}>
        <div style={{
          fontFamily: "'Press Start 2P', monospace", fontSize: '0.35rem',
          color: 'var(--mc-text-dim)', marginBottom: '8px',
        }}>
          ℹ INSTANCE ACCESS
        </div>
        <div style={{ fontFamily: "'Share Tech Mono', monospace", fontSize: '0.75rem', color: 'var(--mc-text-dim)' }}>
          Access is managed locally by this instance owner.<br />
          Total users: <span style={{ color: 'var(--mc-text)' }}>{users.length}</span> &nbsp;|&nbsp;
          Active pro: <span style={{ color: 'var(--mc-green)' }}>{users.filter(u => u.is_pro).length}</span> &nbsp;|&nbsp;
          Restricted: <span style={{ color: 'var(--mc-red)' }}>{users.filter(u => !u.is_pro).length}</span>
        </div>
      </div>
    </div>
  )
}

const thStyle: React.CSSProperties = {
  padding: '10px 12px',
  textAlign: 'left',
  fontFamily: "'Press Start 2P', monospace",
  fontSize: '0.35rem',
  color: 'var(--mc-gold)',
  letterSpacing: '1px',
  whiteSpace: 'nowrap',
}

const tdStyle: React.CSSProperties = {
  padding: '8px 12px',
  whiteSpace: 'nowrap',
}

const statBox: React.CSSProperties = {
  border: '1px solid var(--mc-border)',
  background: '#090914',
  padding: '12px',
  display: 'flex',
  flexDirection: 'column',
  gap: '6px',
  fontFamily: "'Share Tech Mono', monospace",
}

const formLabel: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: '6px',
  color: 'var(--mc-text-dim)',
  fontFamily: "'Press Start 2P', monospace",
  fontSize: '0.35rem',
}
