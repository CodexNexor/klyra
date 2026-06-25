import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { API } from '../api'

interface AuthState {
  authed: boolean
  loading: boolean
  role: string
  subscription: string
  isPro: boolean
}

export default function AuthGuard({ children, requireSubscription = true }: { children: React.ReactNode; requireSubscription?: boolean }) {
  const navigate = useNavigate()
  const [state, setState] = useState<AuthState>({ authed: false, loading: true, role: '', subscription: '', isPro: false })

  useEffect(() => {
    const check = async () => {
      const token = localStorage.getItem('ai_hacker_token')
      if (!token) {
        navigate('/login', { replace: true })
        return
      }
      try {
        const r = await fetch(`${API}/api/user`, {
          headers: { Authorization: `Bearer ${token}` },
        })
        if (!r.ok) {
          localStorage.removeItem('ai_hacker_token')
          navigate('/login', { replace: true })
          return
        }
        const data = await r.json()
        const role = data.role || 'user'
        const hasAccessField = Object.prototype.hasOwnProperty.call(data, 'is_pro')
        const isPro = hasAccessField
          ? Boolean(data.is_pro)
          : Boolean(role === 'owner' || role === 'admin' || role === 'pro' || data.subscription === 'active')
        setState({
          authed: true,
          loading: false,
          role,
          subscription: data.subscription || 'none',
          isPro,
        })

        if (requireSubscription && !isPro) {
          navigate('/pricing', { replace: true })
          return
        }
      } catch {
        navigate('/login', { replace: true })
      }
    }
    check()
  }, [navigate, requireSubscription])

  if (state.loading) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        minHeight: 'calc(100vh - 56px)', color: 'var(--mc-text-dim)',
        fontFamily: "'Press Start 2P', monospace", fontSize: '0.5rem',
      }}>
        ◉ AUTHENTICATING...
      </div>
    )
  }

  return <>{children}</>
}
