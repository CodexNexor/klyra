import { Link } from 'react-router-dom'

export default function Pricing() {
  return (
    <div className="pricing-container">
      <div className="pixel-card pricing-card featured">
        <h2 style={{ color: 'var(--gold)', marginBottom: '8px', fontSize: '0.65rem' }}>
          ⟐ SELF-HOSTED ACCESS
        </h2>
        <p style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>
          Klyra is open source. Access is controlled by your own instance admin.
        </p>

        <div className="price">OSS</div>
        <div className="price-label">Local-first security lab</div>

        <ul className="perks">
          <li>Fresh LXD workspaces per operator</li>
          <li>OpenCode-powered chat inside isolated containers</li>
          <li>Admin dashboard for users and containers</li>
          <li>Encrypted SQLite metadata</li>
          <li>Cloudflare quick tunnel for demos</li>
          <li>Authorized testing policy included</li>
        </ul>

        <Link
          to="/login"
          className="pixel-btn gold"
          style={{ width: '100%', fontSize: '0.6rem', textDecoration: 'none', display: 'inline-block', textAlign: 'center' }}
        >
          ◈ LOGIN TO YOUR INSTANCE
        </Link>

        <div style={{
          marginTop: '16px',
          padding: '8px 16px',
          background: 'rgba(0,255,65,0.05)',
          border: '1px solid var(--green-dim)',
          fontSize: '0.5rem',
          fontFamily: "'Press Start 2P', monospace",
          color: 'var(--green-dim)',
        }}>
          USE ONLY ON SYSTEMS YOU OWN OR ARE AUTHORIZED TO TEST
        </div>
      </div>
    </div>
  )
}
