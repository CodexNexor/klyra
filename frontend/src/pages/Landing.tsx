import { Link } from 'react-router-dom'
import ShaderBackground from '../components/ShaderBackground'
import ErrorBoundary from '../components/ErrorBoundary'

const features = [
  { icon: '⚡', title: 'Guided Security Testing', desc: 'Run authorized checks from an AI-assisted workspace with clear operator control.' },
  { icon: '🛡️', title: 'Isolated by Default', desc: 'Each operator gets a fresh LXD workspace with explicit boundaries.' },
  { icon: '⟐', title: 'Multi-Session', desc: 'Isolated environments per target. Concurrent operations. Full sandbox.' },
  { icon: '◈', title: 'Self-Hosted', desc: 'Open-source deployment with local admin access control.' },
  { icon: '◉', title: 'AI Models', desc: 'DeepSeek, Nemotron, Mimo — switch on the fly per operation.' },
  { icon: '🔗', title: 'Audit Workflow', desc: 'Capture sessions, evidence, findings, and remediation notes in one place.' },
]

const terminalLines = [
  { prompt: 'root@klyra:~$', cmd: 'system_check --all', output: '' },
  { prompt: '', cmd: '', output: '[OK] AI engine: connected' },
  { prompt: '', cmd: '', output: '[OK] Session manager: running' },
  { prompt: '', cmd: '', output: '[OK] Encryption layer: active' },
  { prompt: '', cmd: '', output: '[OK] Anonymity: established' },
  { prompt: '', cmd: '', output: '[OK] Toolchain: ready' },
  { prompt: 'root@klyra:~$', cmd: 'assess --scope authorized-lab --report', output: '' },
  { prompt: '', cmd: '', output: '⟐ Scope loaded: internal lab' },
  { prompt: '', cmd: '', output: '⟐ Evidence captured' },
  { prompt: '', cmd: '', output: '⟐ Finding drafted with remediation' },
  { prompt: '', cmd: '', output: '⟐ Report ready for review' },
  { prompt: 'root@klyra:~$', cmd: 'system_status --online', output: '', isCursor: true },
]

export default function Landing() {
  return (
    <>
      <ErrorBoundary><ShaderBackground /></ErrorBoundary>
      <section className="hero">
        <div className="hero-title hero-glitch">
          KLYRA
        </div>
        <p className="hero-sub">
          A self-hosted AI security lab for authorized testing, isolated workspaces, and clean findings.
        </p>
        <div className="hero-actions">
          <Link to="/playground" className="pixel-btn primary" style={{ fontSize: '0.65rem', padding: '16px 36px' }}>
            ▶ START
          </Link>
          <Link to="/pricing" className="pixel-btn gold" style={{ fontSize: '0.65rem', padding: '16px 36px' }}>
            ◈ OSS
          </Link>
          <Link to="/login" className="pixel-btn" style={{ fontSize: '0.65rem', padding: '16px 36px' }}>
            ◉ LOGIN
          </Link>
        </div>
      </section>

      <div className="features" style={{ position: 'relative', zIndex: 1 }}>
        {features.map((f, i) => (
          <div key={i} className="pixel-card feature-card" style={{ background: 'rgba(0,0,0,0.75)' }}>
            <span className="feature-icon">{f.icon}</span>
            <h3>{f.title}</h3>
            <p>{f.desc}</p>
          </div>
        ))}
      </div>

      <section style={{ textAlign: 'center', padding: '60px 20px 100px', position: 'relative', zIndex: 1 }}>
        <h2 style={{
          fontFamily: "'Press Start 2P', monospace",
          fontSize: '0.6rem',
          color: '#55FF55',
          marginBottom: '24px',
        }}>
          LIVE DEMO
        </h2>
        <div className="terminal-box" style={{ maxWidth: '650px', margin: '0 auto', textAlign: 'left' }}>
          {terminalLines.map((l, i) => (
            <div key={i} className="terminal-line" style={{ animationDelay: `${i * 0.08}s` }}>
              {l.prompt && <span className="prompt">{l.prompt} </span>}
              {l.cmd && <span className={`cmd ${l.isCursor ? 'terminal-cursor' : ''}`}>{l.cmd}</span>}
              {l.output && <span className="output">{l.output}</span>}
            </div>
          ))}
        </div>
      </section>
    </>
  )
}
