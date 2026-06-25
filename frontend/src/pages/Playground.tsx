import { useState, useRef, useEffect, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'

import { API } from '../api'

const PROVISION_STEPS = [
  'Initializing secure environment...',
  'Allocating storage (10GB)...',
  'Deploying Kali Linux environment...',
  'Installing AI engine (OpenCode)...',
  'Configuring network isolation...',
  'Running security audit...',
  'Container ready.',
]

interface FileItem { name: string; path: string; is_dir: boolean; size: number }
interface CommandEntry { tool: string; command?: string; filePath?: string; url?: string; query?: string; status?: string; output?: string }
interface Message { id: string; role: 'user' | 'assistant'; content: string; prompt_type?: string; commands?: CommandEntry[] }
interface SessionItem { id: string; title: string; project: string; model: string; messages: number; last_active: number }

const defaultModels = ['opencode/deepseek-v4-flash-free']
const defaultVariants = ['low', 'medium', 'high', 'max']

function MarkdownContent({ content }: { content: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeRaw]}
      components={{
        table: ({ children }) => <table><tbody>{children}</tbody></table>,
        thead: ({ children }) => <thead>{children}</thead>,
        tbody: ({ children }) => <tbody>{children}</tbody>,
        tr: ({ children }) => <tr>{children}</tr>,
        th: ({ children }) => <th>{children}</th>,
        td: ({ children }) => <td>{children}</td>,
        code: ({ children, className }) => {
          if (!className) return <code>{children}</code>
          return <pre><code>{children}</code></pre>
        },
      }}
    >
      {content}
    </ReactMarkdown>
  )
}

function CollapsibleCmd({ cmd }: { cmd: CommandEntry }) {
  const [open, setOpen] = useState(false)
  const toolIcon: Record<string, string> = {
    bash: '⌘', write: '✎', webfetch: '↗', websearch: '◎',
  }
  const label = cmd.command
    ? cmd.command.slice(0, 80) + (cmd.command.length > 80 ? '...' : '')
    : cmd.url || cmd.query || cmd.filePath || cmd.tool
  return (
    <div className={`cmd-item ${open ? 'open' : ''}`}>
      <div className="cmd-header" onClick={() => setOpen(!open)}>
        <span className="cmd-icon">{toolIcon[cmd.tool] || '⚙'}</span>
        <span className="cmd-label">{label}</span>
        <span className="cmd-arrow">{open ? '▾' : '▸'}</span>
      </div>
      {open && (
        <div className="cmd-body">
          {cmd.command && <pre className="cmd-code">{cmd.command}</pre>}
          {cmd.output && (
            <details open>
              <summary>Output ({cmd.output.length} bytes)</summary>
              <pre className="cmd-output">{cmd.output}</pre>
            </details>
          )}
          <div className="cmd-meta">tool: {cmd.tool} · status: {cmd.status || 'running'}</div>
        </div>
      )}
    </div>
  )
}

function FileBrowser() {
  const [files, setFiles] = useState<FileItem[]>([])
  const [currentPath, setCurrentPath] = useState('/root/projects')
  const [loading, setLoading] = useState(false)
  const [openDirs, setOpenDirs] = useState<Record<string, boolean>>({})
  const [fileContents, setFileContents] = useState<Record<string, string>>({})

  const fetchFiles = async (path: string) => {
    setLoading(true)
    const token = localStorage.getItem('ai_hacker_token') || ''
    try {
      const r = await fetch(`${API}/api/files?path=${encodeURIComponent(path)}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!r.ok) return
      const data = await r.json()
      setFiles(data.files || [])
      setCurrentPath(data.path)
    } catch {}
    setLoading(false)
  }

  useEffect(() => { fetchFiles('/root/projects') }, [])

  const toggleDir = (item: FileItem) => {
    const key = item.path
    if (openDirs[key]) { setOpenDirs(prev => ({ ...prev, [key]: false })); return }
    setOpenDirs(prev => ({ ...prev, [key]: true }))
    fetchFiles(item.path)
    setCurrentPath(item.path)
  }

  const openFile = async (item: FileItem) => {
    if (fileContents[item.path]) { setFileContents(prev => ({ ...prev, [item.path]: '' })); return }
    setLoading(true)
    const token = localStorage.getItem('ai_hacker_token') || ''
    try {
      const r = await fetch(`${API}/api/files/read?path=${encodeURIComponent(item.path)}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!r.ok) return
      const data = await r.json()
      setFileContents(prev => ({ ...prev, [item.path]: data.content }))
    } catch {}
    setLoading(false)
  }

  const downloadFile = async (item: FileItem) => {
    const token = localStorage.getItem('ai_hacker_token') || ''
    try {
      const r = await fetch(`${API}/api/files/download?path=${encodeURIComponent(item.path)}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!r.ok) return
      const blob = await r.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = item.name; a.click()
      URL.revokeObjectURL(url)
    } catch {}
  }

  const parentPath = () => {
    const p = currentPath.replace(/\/$/, '')
    const parent = p.split('/').slice(0, -1).join('/')
    if (parent) fetchFiles(parent)
  }

  return (
    <div className="pg-file-browser">
      <div className="pg-file-path">
        <span style={{ color: 'var(--gold)', fontFamily: "'Press Start 2P', monospace", fontSize: '0.35rem' }}>PATH</span>
        <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{currentPath}</span>
        {currentPath !== '/root/projects' && (
          <span onClick={parentPath} style={{ color: 'var(--blue)', cursor: 'pointer' }}>⬆</span>
        )}
      </div>
      {loading && <div style={{ color: 'var(--text-dim)', fontSize: '0.7rem' }}>Loading...</div>}
      <div style={{ maxHeight: '200px', overflowY: 'auto' }}>
        {files.filter(f => f.name !== '.' && f.name !== '..').map(f => (
          <div key={f.path}>
            <div
              className="pg-file-item"
              style={{ borderLeft: f.is_dir ? '2px solid var(--gold)' : '2px solid var(--border)', background: openDirs[f.path] ? 'var(--green-bg)' : 'transparent' }}
              onClick={() => f.is_dir ? toggleDir(f) : openFile(f)}
            >
              <span style={{ color: f.is_dir ? 'var(--gold)' : 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {f.is_dir ? '📁' : '📄'} {f.name}
              </span>
              <span style={{ fontSize: '0.6rem', color: 'var(--text-dim)', display: 'flex', gap: '4px', flexShrink: 0 }}>
                {!f.is_dir && (
                  <span onClick={(e) => { e.stopPropagation(); downloadFile(f) }} style={{ cursor: 'pointer', color: 'var(--blue)' }}>⬇</span>
                )}
                {!f.is_dir && f.size > 0 && `${(f.size / 1024).toFixed(1)}K`}
              </span>
            </div>
            {!f.is_dir && fileContents[f.path] && (
              <pre className="pg-file-content">{fileContents[f.path].slice(0, 2000)}</pre>
            )}
          </div>
        ))}
        {files.length === 0 && !loading && <div style={{ color: 'var(--text-dim)', fontSize: '0.7rem', padding: '6px' }}>Empty folder</div>}
      </div>
    </div>
  )
}

function ProvisionScreen({ onComplete }: { onComplete: () => void }) {
  const [step, setStep] = useState(0)
  const [progress, setProgress] = useState(0)
  const [error, setError] = useState('')

  useEffect(() => {
    const doProvision = async () => {
      const token = localStorage.getItem('ai_hacker_token') || ''
      const stepTimer = setInterval(() => {
        setStep(s => Math.min(s + 1, PROVISION_STEPS.length - 1))
      }, 3000)
      const progressTimer = setInterval(() => {
        setProgress(p => Math.min(p + 2, 95))
      }, 200)

      try {
        const r = await fetch(`${API}/api/provision`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify({}),
        })
        const data = await r.json()
        if (!r.ok) {
          throw new Error(data.detail || 'Provisioning failed')
        }
        clearInterval(stepTimer)
        clearInterval(progressTimer)
        setStep(PROVISION_STEPS.length - 1)
        setProgress(100)
        setTimeout(onComplete, 800)
      } catch (err: any) {
        clearInterval(stepTimer)
        clearInterval(progressTimer)
        setError(err.message)
        setProgress(100)
      }
    }
    doProvision()
  }, [])

  return (
    <div className="provision-screen">
      <div style={{ marginBottom: '24px' }}>
        <span style={{ fontFamily: "'Press Start 2P', monospace", fontSize: '0.6rem', color: '#55FF55', textShadow: '0 0 20px #55FF55' }}>
          ◈ DEPLOYING CONTAINER
        </span>
      </div>
      <div style={{ width: '100%', maxWidth: '500px' }}>
        {PROVISION_STEPS.map((s, i) => (
          <div key={i} className={`provision-step ${i < step ? 'done' : i === step ? 'active' : ''}`}
               style={{ animationDelay: `${i * 0.05}s`, display: i <= step ? 'block' : 'none' }}>
            {i < step ? '✔' : i === step ? '⟐' : '○'} {s}
          </div>
        ))}
      </div>
      <div className="provision-progress">
        <div className="provision-progress-fill" style={{ width: `${progress}%` }} />
      </div>
      <div className="provision-progress-label">
        {error ? 'FAILED' : progress < 100 ? `${progress}%` : 'READY'}
      </div>
      {error && <div className="provision-error">⚠ {error}</div>}
    </div>
  )
}

export default function Playground() {
  const [sessions, setSessions] = useState<SessionItem[]>([])
  const [messages, setMessages] = useState<Message[]>([])
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)
  const [input, setInput] = useState('')
  const [model, setModel] = useState('')
  const [variant, setVariant] = useState('high')
  const [loading, setLoading] = useState(false)
  const [sessionLoading, setSessionLoading] = useState(false)
  const [showFiles, setShowFiles] = useState(false)
  const [availableModels, setAvailableModels] = useState(defaultModels)
  const [availableVariants, setAvailableVariants] = useState(defaultVariants)
  const [containerReady, setContainerReady] = useState(false)
  const [checkingContainer, setCheckingContainer] = useState(true)
  const fileInputRef = useRef<HTMLInputElement>(null!)
  const chatRef = useRef<HTMLDivElement>(null!)
  const sessionIdRef = useRef<string | null>(null)

  const token = () => localStorage.getItem('ai_hacker_token') || ''
  const headers = () => ({ 'Content-Type': 'application/json', 'Authorization': `Bearer ${token()}` })

  useEffect(() => {
    fetch(`${API}/api/models`)
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data && data.models && data.models.length > 0) {
          setAvailableModels(data.models)
          if (!model) setModel(data.models[0])
          if (data.variants) setAvailableVariants(data.variants)
        }
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (!model && availableModels.length > 0) setModel(availableModels[0])
  }, [availableModels, model])

  const checkContainer = useCallback(async () => {
    setCheckingContainer(true)
    const t = token()
    if (!t) { setCheckingContainer(false); return }
    try {
      const r = await fetch(`${API}/api/user`, { headers: { Authorization: `Bearer ${t}` } })
      if (!r.ok) { setCheckingContainer(false); return }
      const pr = await fetch(`${API}/api/provision`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${t}` },
        body: JSON.stringify({}),
      })
      if (pr.ok) {
        const pdata = await pr.json()
        if (pdata.status === 'running' || pdata.message === 'Container already exists') {
          setContainerReady(true)
        }
      }
      const s = await fetch(`${API}/api/sessions`, { headers: { Authorization: `Bearer ${t}` } })
      if (s.ok) {
        const data: SessionItem[] = await s.json()
        setSessions(data)
        if (data.length > 0 && !activeSessionId) {
          setActiveSessionId(data[0].id)
          sessionIdRef.current = data[0].id
        }
      }
    } catch {}
    setCheckingContainer(false)
  }, [])

  useEffect(() => { checkContainer() }, [checkContainer])

  useEffect(() => {
    if (!activeSessionId) return
    const load = async () => {
      setSessionLoading(true)
      try {
        const r = await fetch(`${API}/api/sessions/${activeSessionId}/messages`, { headers: { Authorization: `Bearer ${token()}` } })
        if (r.ok) {
          const d = await r.json()
          const msgs: Message[] = (d.messages || []).map((m: any) => {
            if (m.role === 'assistant' && m.content?.startsWith('{')) {
              try {
                const parsed = JSON.parse(m.content)
                return { ...m, content: parsed.text || '', commands: parsed.commands || [] }
              } catch { return m }
            }
            return m
          })
          setMessages(msgs)
        } else setMessages([])
      } catch { setMessages([]) }
      setSessionLoading(false)
    }
    load()
  }, [activeSessionId])

  useEffect(() => {
    if (chatRef.current) chatRef.current.scrollTop = chatRef.current.scrollHeight
  }, [messages])

  const refreshSessions = async () => {
    try {
      const r = await fetch(`${API}/api/sessions`, { headers: headers() })
      if (r.ok) { const d: SessionItem[] = await r.json(); setSessions(d) }
    } catch {}
  }

  const newSession = () => {
    setActiveSessionId(null)
    sessionIdRef.current = null
    setMessages([{ id: 'new', role: 'assistant', content: 'New session ready. Send a message to begin.' }])
  }

  const sendToApi = async (message: string, sid: string | null): Promise<any> => {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 600000)
    const res = await fetch(`${API}/api/chat`, {
      method: 'POST', headers: headers(),
      body: JSON.stringify({ message, model, variant, session_id: sid }),
      signal: controller.signal,
    })
    clearTimeout(timeout)
    if (!res.ok) {
      let errMsg = `HTTP ${res.status}`
      try { const err = await res.json(); errMsg = err.detail || errMsg } catch { errMsg = res.statusText || errMsg }
      throw new Error(errMsg)
    }

    // Read SSE stream
    const reader = res.body!.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    let responseText = ''
    let commands: CommandEntry[] = []
    let promptType = 'text'
    let resolvedSessionId = sid
    let resolvedMsgCount = 0
    let doneReceived = false
    let lastDataTs = Date.now()

    while (!doneReceived) {
      // Safety: if no data for 120s, assume server hung up
      if (Date.now() - lastDataTs > 120000 && responseText.length > 0) break

      const result = await Promise.race([
        reader.read(),
        new Promise<null>(resolve => setTimeout(() => resolve(null), 120000)),
      ])
      if (!result) continue  // safety timeout, try again if no data yet
      const { done, value } = result as ReadableStreamReadResult<Uint8Array>
      if (done) break
      lastDataTs = Date.now()
      buf += decoder.decode(value, { stream: true })

      const parts = buf.split('\n')
      buf = parts.pop() || ''

      for (const line of parts) {
        const trimmed = line.trim()
        if (!trimmed || trimmed.startsWith(':')) continue

        if (trimmed.startsWith('data: ')) {
          const data = trimmed.slice(6).trim()
          if (!data) continue
          try {
            const ev = JSON.parse(data)

            // Error event from server
            if (ev.type === 'error') {
              throw new Error(ev.detail || 'Server error')
            }

            // Final done event
            if (ev.response !== undefined) {
              responseText = ev.response || ''
              resolvedSessionId = ev.session_id || resolvedSessionId
              resolvedMsgCount = ev.message_count || 0
              commands = ev.commands || []
              promptType = ev.prompt_type || 'text'
              doneReceived = true
              break
            }

            // Regular NDJSON event
            const part = ev.part || {}
            const evtType = ev.type || ''

            if (evtType === 'text') {
              responseText += part.text || ''
            } else if (evtType === 'tool_use') {
              const tool = part.tool || ''
              const state = part.state || {}
              const inp = state.input || {}
              const status = state.status || ''

              const cmd: CommandEntry = { tool, status }
              if (tool === 'bash') {
                promptType = 'run'
                cmd.command = inp.command || ''
              } else if (tool === 'write') {
                promptType = 'always'
                cmd.filePath = inp.filePath || ''
              } else if (tool === 'webfetch') {
                cmd.url = inp.url || inp.query || ''
              } else if (tool === 'websearch') {
                cmd.query = inp.query || ''
              }
              if (status === 'completed') {
                const output = state.output || ''
                if (output.trim()) cmd.output = output.trim().slice(0, 1000)
              }
              commands.push(cmd)
            }
          } catch (e: any) {
            if (e.message && e.message !== 'Unexpected token') throw e
          }
        }
      }
    }

    return {
      response: responseText,
      session_id: resolvedSessionId,
      message_count: resolvedMsgCount,
      prompt_type: promptType,
      commands,
    }
  }

  const loadMessages = async (sid: string) => {
    try {
      const r = await fetch(`${API}/api/sessions/${sid}/messages`, { headers: { Authorization: `Bearer ${token()}` } })
      if (r.ok) {
        const d = await r.json()
        const msgs: Message[] = (d.messages || []).map((m: any) => {
          if (m.role === 'assistant' && m.content?.startsWith('{')) {
            try { const p = JSON.parse(m.content); return { ...m, content: p.text || '', commands: p.commands || [] } }
            catch { return m }
          }
          return m
        })
        setMessages(msgs)
      }
    } catch {}
  }

  const handleSend = async () => {
    const trimmed = input.trim()
    if (!trimmed || loading) return
    const userMsg: Message = { id: `u-${Date.now()}`, role: 'user', content: trimmed }
    setMessages(prev => [...prev, userMsg])
    setInput('')
    setLoading(true)
    try {
      const data = await sendToApi(trimmed, sessionIdRef.current)
      sessionIdRef.current = data.session_id
      if (data.session_id && !activeSessionId) {
        setActiveSessionId(data.session_id)
      } else if (data.session_id) {
        await loadMessages(data.session_id)
      }
      await refreshSessions()
    } catch (err: any) {
      const msg = err.name === 'AbortError' ? '⏱ Request timed out after 5 min. Click SEND to retry.' : `⚠ ${err.message}. Click SEND to retry.`
      setMessages(prev => [...prev, { id: `e-${Date.now()}`, role: 'assistant', content: msg }])
    }
    setLoading(false)
  }

  const handleFileAttach = () => fileInputRef.current?.click()

  const handleFileSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const text = await file.text()
    setInput(prev => prev + `\n\n[Attached: ${file.name}]\n\`\`\`\n${text.slice(0, 5000)}\n\`\`\``)
    e.target.value = ''
  }

  const deleteSession = async (sid: string) => {
    try {
      await fetch(`${API}/api/sessions/${sid}/delete`, { method: 'POST', headers: headers() })
      setSessions(prev => prev.filter(s => s.id !== sid))
      if (activeSessionId === sid) { setActiveSessionId(null); sessionIdRef.current = null; setMessages([]) }
    } catch {}
  }

  const selectSession = (sid: string) => { setActiveSessionId(sid); sessionIdRef.current = sid }

  if (checkingContainer) {
    return (
      <div className="provision-screen">
        <div style={{ fontFamily: "'Press Start 2P', monospace", fontSize: '0.55rem', color: 'var(--mc-text-dim)' }}>
          ◉ CHECKING ENVIRONMENT...
        </div>
      </div>
    )
  }

  if (!containerReady) {
    return <ProvisionScreen onComplete={() => { setContainerReady(true); refreshSessions() }} />
  }

  return (
    <div className="playground">
      <div className="playground-sidebar">
        <div className="model-selector">
          <label>MODEL</label>
          <select value={model} onChange={e => setModel(e.target.value)}>
            {availableModels.map(m => <option key={m} value={m}>{m}</option>)}
          </select>
        </div>
        <div className="model-selector">
          <label>VARIANT</label>
          <select value={variant} onChange={e => setVariant(e.target.value)}>
            {availableVariants.map(v => <option key={v} value={v}>{v}</option>)}
          </select>
        </div>
        <button className="pixel-btn primary small" style={{ width: '100%' }} onClick={newSession}>
          ⟐ NEW CHAT
        </button>
        <div className="pixel-toggle" style={{ marginBottom: '4px', marginTop: '4px' }}>
          <div className={`toggle-track ${showFiles ? 'active' : ''}`} onClick={() => setShowFiles(!showFiles)}>
            <div className="toggle-knob" />
          </div>
          <label>FILES</label>
        </div>
        {showFiles && <FileBrowser />}
        <h3>⟐ CHATS</h3>
        <div className="sidebar-chat-list">
          {sessions.length === 0 && (
            <div style={{ color: 'var(--text-dim)', fontSize: '0.7rem', padding: '10px' }}>No chats yet.</div>
          )}
          {sessions.map(s => (
            <div key={s.id} className={`history-item ${activeSessionId === s.id ? 'active' : ''}`} onClick={() => selectSession(s.id)}>
              <div className="h-title">{s.title || 'Untitled'}</div>
              <div className="h-meta">{s.messages} msgs</div>
              <span onClick={(e) => { e.stopPropagation(); deleteSession(s.id) }}
                style={{ position: 'absolute', right: '6px', top: '6px', color: 'var(--red)', cursor: 'pointer', fontSize: '0.65rem', opacity: 0.5, transition: 'opacity 0.15s' }}
                onMouseEnter={e => e.currentTarget.style.opacity = '1'}
                onMouseLeave={e => e.currentTarget.style.opacity = '0.5'}
              >✕</span>
            </div>
          ))}
        </div>
      </div>

      <div className="playground-main">
        <div className="playground-chat" ref={chatRef}>
          {sessionLoading && (
            <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-dim)', fontSize: '0.85rem' }}>
              Loading conversation...
            </div>
          )}
          {!sessionLoading && messages.length === 0 && (
            <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-dim)', fontSize: '0.85rem' }}>
              {activeSessionId ? 'No messages yet. Start the conversation.' : 'Select a chat or create a new one.'}
            </div>
          )}
          {messages.map(m => (
            <div key={m.id} className={`msg ${m.role === 'user' ? 'msg-right' : 'msg-left'}`}>
              <div className="msg-label">{m.role === 'user' ? '◉ YOU' : '◈ KLYRA'}</div>
              <div className="msg-bubble">
                {m.role === 'user' ? (
                  <div className="msg-content user-content">{m.content}</div>
                ) : (
                  <>
                    <div className="msg-content"><MarkdownContent content={m.content} /></div>
                    {m.commands && m.commands.length > 0 && (
                      <div className="cmd-list">
                        {m.commands.map((cmd, ci) => (
                          <CollapsibleCmd key={ci} cmd={cmd} />
                        ))}
                      </div>
                    )}
                  </>
                )}
              </div>
            </div>
          ))}
          {loading && (
            <div className="loading-indicator">
              <span className="dot-pulse"></span>
              <span>AI processing...</span>
            </div>
          )}
        </div>

        <div className="playground-input-row">
          <button className="pixel-btn small" onClick={handleFileAttach}
            disabled={loading}
            title="Attach file (text/PDF)"
            style={{ fontSize: '0.7rem', padding: '4px 8px' }}>
            📎
          </button>
          <input ref={fileInputRef} type="file" accept=".txt,.md,.py,.js,.ts,.json,.html,.css,.csv,.xml,.yaml,.yml,.sh,.pdf" style={{ display: 'none' }} onChange={handleFileSelected} />
          <input className="pixel-input" placeholder="Type a message..."
            value={input} onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() } }}
            disabled={loading} />
          {loading ? (
            <div className="btn-loading">
              <span className="dot-pulse"></span>
            </div>
          ) : (
            <button className="pixel-btn primary" onClick={handleSend}
              disabled={!input.trim()}>▶ SEND</button>
          )}
        </div>
      </div>
    </div>
  )
}
