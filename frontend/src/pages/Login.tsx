import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { API } from '../api'

export default function Login() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      const endpoint = mode === 'login' ? '/api/login' : '/api/register'
      const res = await fetch(`${API}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      })
      const data = await res.json()

      if (!res.ok) {
        setError(data.detail || 'Authentication failed')
        return
      }

      localStorage.setItem('ai_hacker_token', data.token)
      navigate('/dashboard')
    } catch (err) {
      setError('Connection failed — is the server running?')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-container">
      <div className="pixel-card login-box">
        <h2>◈ {mode === 'login' ? 'ACCESS TERMINAL' : 'REGISTER'}</h2>

        {error && (
          <div style={{ color: '#ff4444', fontSize: '0.7rem', textAlign: 'center', marginBottom: '12px' }}>
            ⚠ {error}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <input
            className="pixel-input"
            placeholder="USERNAME"
            value={username}
            onChange={e => setUsername(e.target.value)}
            required
            minLength={3}
          />
          <input
            className="pixel-input"
            type="password"
            placeholder="PASSWORD"
            value={password}
            onChange={e => setPassword(e.target.value)}
            required
            minLength={8}
          />
          <button type="submit" className="pixel-btn primary" disabled={loading}>
            ◉ {loading ? 'CONNECTING...' : mode === 'login' ? 'AUTHENTICATE' : 'CREATE ACCOUNT'}
          </button>
        </form>

        <div className="login-divider">━━━━━━━━━━━━━━━</div>

        <p style={{ textAlign: 'center', fontSize: '0.8rem', color: '#555577' }}>
          {mode === 'login' ? (
            <>No account?{' '}<a href="#" onClick={e => { e.preventDefault(); setMode('register'); setError('') }} style={{ cursor: 'pointer' }}>Register</a></>
          ) : (
            <>Already have an account?{' '}<a href="#" onClick={e => { e.preventDefault(); setMode('login'); setError('') }} style={{ cursor: 'pointer' }}>Login</a></>
          )}
        </p>

        <div style={{ marginTop: '20px', padding: '12px', background: '#0a0a1a', border: '1px solid #2a2a4a', textAlign: 'center' }}>
          <p style={{ fontSize: '0.65rem', color: '#555577', fontFamily: "'Press Start 2P', monospace" }}>
            NO KYC • NO EMAIL • NO TRACE
          </p>
          <p style={{ fontSize: '0.6rem', color: '#333366', marginTop: '8px', fontFamily: "'Press Start 2P', monospace" }}>
            ALL DATA ENCRYPTED END-TO-END
          </p>
        </div>
      </div>
    </div>
  )
}
