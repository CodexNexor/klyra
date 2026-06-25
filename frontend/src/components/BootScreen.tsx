import { useState, useEffect } from 'react'

const bootLines = [
  'INITIALIZING KLYRA ENGINE...',
  'LOADING NEURAL NETWORKS...',
  'ESTABLISHING SECURE TUNNEL...',
  'LOADING AUTHORIZED-SCOPE POLICY...',
  'ISOLATED WORKSPACE READY.',
]

export default function BootScreen({ onDone }: { onDone: () => void }) {
  const [line, setLine] = useState(0)
  const [progress, setProgress] = useState(0)
  const [show, setShow] = useState(true)

  useEffect(() => {
    const t1 = setInterval(() => {
      setProgress(p => {
        if (p >= 100) {
          clearInterval(t1)
          return 100
        }
        return p + 2
      })
    }, 30)

    const t2 = setInterval(() => {
      setLine(l => {
        if (l >= bootLines.length - 1) {
          clearInterval(t2)
          return l
        }
        return l + 1
      })
    }, 500)

    const t3 = setTimeout(() => {
      setShow(false)
      onDone()
    }, 3500)

    return () => { clearInterval(t1); clearInterval(t2); clearTimeout(t3) }
  }, [onDone])

  if (!show) return null

  return (
    <div className="boot-screen">
      <div style={{ marginBottom: '30px' }}>
        <span style={{
          fontFamily: "'Press Start 2P', monospace",
          fontSize: '1.2rem',
          color: '#00ff41',
          textShadow: '0 0 20px #00ff41, 0 0 40px #005511',
        }}>
          KLYRA
        </span>
      </div>

      {bootLines.map((l, i) => (
        <div key={i} className="boot-text" style={{
          animationDelay: `${i * 0.02}s`,
          opacity: i <= line ? 1 : 0,
          color: i <= line ? '#00ff41' : '#0a0a1a',
        }}>
          {i <= line ? `[${'='.repeat(i + 1)}${' '.repeat(bootLines.length - i - 1)}] ${l}` : ''}
        </div>
      ))}

      <div className="boot-progress">
        <div className="boot-progress-fill" style={{ width: `${progress}%` }} />
      </div>
      <div className="boot-text" style={{ marginTop: '10px', fontSize: '0.8rem', color: '#44446a' }}>
        {progress < 100 ? `${progress}%` : 'READY.'}
      </div>
    </div>
  )
}
