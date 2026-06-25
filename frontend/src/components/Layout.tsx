import { Link, useLocation } from 'react-router-dom'

const navLinks = [
  { to: '/', label: 'Home' },
  { to: '/playground', label: 'Playground' },
  { to: '/pricing', label: 'Pricing' },
  { to: '/contact', label: 'Contact' },
]

export default function Layout({ children }: { children: React.ReactNode }) {
  const location = useLocation()

  return (
    <div className="crt">
      <nav className="navbar">
        <Link to="/" className="nav-brand">
          ◢ KLYRA
        </Link>
        <div className="nav-links">
          {navLinks.map(l => (
            <Link
              key={l.to}
              to={l.to}
              className={location.pathname === l.to ? 'active' : ''}
            >
              {l.label}
            </Link>
          ))}
          <Link to="/login" className={location.pathname === '/login' ? 'active' : ''}>
            ▸ Login
          </Link>
        </div>
        <div className="nav-coins">
          ◈ <span className="glow-gold">SELF-HOSTED</span>
        </div>
      </nav>

      <div className="page-content">
        {children}
      </div>

      <div className="status-bar">
        <span className="green">◉ SYSTEM ONLINE</span>
        <span>
          <span className="gold">⟐ COINS: 0</span>
          <span className="red">♥ LIVES: ∞</span>
          <span>AUTHORIZED USE ONLY</span>
        </span>
      </div>
    </div>
  )
}
