import { useState } from 'react'

export default function Contact() {
  const [sent, setSent] = useState(false)

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setSent(true)
    setTimeout(() => setSent(false), 5000)
  }

  return (
    <div className="contact-page">
      <h2>◈ CONTACT</h2>
      <p>
        This demo form is local UI only. For production, connect it to your own
        support inbox or coordinated disclosure workflow.
      </p>

      {sent && (
        <div className="toast success" style={{ position: 'static', transform: 'none', marginBottom: '16px' }}>
          ✓ MESSAGE QUEUED LOCALLY
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <textarea
          className="pixel-input"
          placeholder="YOUR MESSAGE"
          required
          style={{ minHeight: '150px', resize: 'vertical' }}
        />
        <input
          className="pixel-input"
          placeholder="CONTACT HANDLE (OPTIONAL)"
        />
        <button type="submit" className="pixel-btn primary" style={{ width: '100%', fontSize: '0.6rem' }}>
          ◉ SEND
        </button>
      </form>

      <div style={{ marginTop: '40px', padding: '16px', border: '1px solid var(--border)' }}>
        <p style={{ fontFamily: "'Press Start 2P', monospace", fontSize: '0.45rem', color: 'var(--green)', marginBottom: '12px' }}>
          DISCLOSURE INFO
        </p>
        <p style={{ fontSize: '0.8rem', color: 'var(--text-dim)' }}>
          Configure a real contact channel before production use.
        </p>
        <p style={{ fontSize: '0.7rem', color: '#555577', marginTop: '8px' }}>
          Security reports should include impact, reproduction steps, affected version,
          and safe validation details.
        </p>
      </div>
    </div>
  )
}
