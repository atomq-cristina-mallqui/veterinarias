import { useMemo, useState } from 'react'
import type { FormEvent } from 'react'

type ChatRole = 'user' | 'assistant' | 'system'

type UiMessage = {
  id: string
  role: ChatRole
  text: string
}

type AdkEvent = {
  author?: string
  content?: {
    role?: string
    parts?: Array<{
      text?: string
      functionResponse?: {
        response?: {
          result?: string
        }
      }
    }>
  }
}

const ADK_BASE_URL = import.meta.env.VITE_ADK_BASE_URL ?? '/adk'
const ADK_APP_NAME = import.meta.env.VITE_ADK_APP_NAME ?? 'vet_assistant'
const DEFAULT_EXISTING_USERS = [
  { userId: 'user_demo_1', clientName: 'Cristina Ramos' },
  { userId: 'user_demo_2', clientName: 'Carlos Pérez' },
  { userId: 'user_demo_3', clientName: 'María Quispe' },
]

const randomId = () =>
  (globalThis.crypto?.randomUUID?.() ?? `id_${Math.random().toString(16).slice(2)}`).replaceAll('-', '')

const createAnonUserId = () => `anon_${randomId().slice(0, 8)}`

const asNaturalDate = (value: string) => {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return new Intl.DateTimeFormat('es-PE', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    hour: 'numeric',
    minute: '2-digit',
  }).format(parsed)
}

const extractAssistantText = (events: AdkEvent[]) => {
  const chunks: string[] = []
  for (const event of events) {
    const isAssistant = event.content?.role === 'model'
    if (!isAssistant) continue
    const parts = event.content?.parts ?? []
    for (const part of parts) {
      if (typeof part.text === 'string' && part.text.trim()) {
        chunks.push(part.text.trim())
      }
      const nested = part.functionResponse?.response?.result
      if (typeof nested === 'string' && nested.trim()) {
        chunks.push(nested.trim())
      }
    }
  }
  return chunks.length ? chunks[chunks.length - 1] : 'No recibí respuesta del agente.'
}

function App() {
  const [theme, setTheme] = useState<'dark' | 'light'>('dark')
  const [showExistingPicker, setShowExistingPicker] = useState(false)
  const [selectedExistingUser, setSelectedExistingUser] = useState(DEFAULT_EXISTING_USERS[0].userId)
  const [userId, setUserId] = useState('')
  const [sessionId, setSessionId] = useState('')
  const [messages, setMessages] = useState<UiMessage[]>([])
  const [draft, setDraft] = useState('')
  const [isBusy, setIsBusy] = useState(false)

  const connected = Boolean(userId && sessionId)

  const chatTitle = useMemo(() => {
    if (!connected) return 'Asistente de veterinaria Patitas Felices'
    return `Sesión activa: ${userId}`
  }, [connected, userId])

  const pushSystem = (text: string) => {
    setMessages((prev) => [...prev, { id: randomId(), role: 'system', text }])
  }

  const createSession = async (nextUserId: string) => {
    const trimmed = nextUserId.trim()
    if (!trimmed) return
    setIsBusy(true)
    try {
      const response = await fetch(
        `${ADK_BASE_URL}/apps/${ADK_APP_NAME}/users/${encodeURIComponent(trimmed)}/sessions`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({}),
        },
      )
      if (!response.ok) {
        throw new Error(`No se pudo crear sesión (${response.status})`)
      }
      const data = (await response.json()) as { id: string }
      setUserId(trimmed)
      setSessionId(data.id)
      setMessages([
        {
          id: randomId(),
          role: 'system',
          text: `Sesión iniciada para ${trimmed}.`,
        },
      ])
      setDraft('')
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Error desconocido al crear sesión.'
      pushSystem(`Error de sesión: ${message}`)
      pushSystem('Verifica que `adk web` esté corriendo en http://127.0.0.1:8000 y recarga la página.')
    } finally {
      setIsBusy(false)
    }
  }

  const sendMessage = async (event: FormEvent) => {
    event.preventDefault()
    if (!connected || isBusy) return
    const text = draft.trim()
    if (!text) return

    setDraft('')
    setMessages((prev) => [...prev, { id: randomId(), role: 'user', text }])
    setIsBusy(true)

    try {
      const response = await fetch(`${ADK_BASE_URL}/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          app_name: ADK_APP_NAME,
          user_id: userId,
          session_id: sessionId,
          new_message: {
            role: 'user',
            parts: [{ text }],
          },
        }),
      })
      if (!response.ok) {
        throw new Error(`No se pudo enviar mensaje (${response.status})`)
      }
      const events = (await response.json()) as AdkEvent[]
      const assistantText = extractAssistantText(events)
      setMessages((prev) => [...prev, { id: randomId(), role: 'assistant', text: assistantText }])
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Error desconocido en el chat.'
      pushSystem(`Error de chat: ${message}`)
      pushSystem('No pude conectar con el backend ADK. Revisa que `adk web` esté activo.')
    } finally {
      setIsBusy(false)
    }
  }

  return (
    <main className={`app theme-${theme}`}>
      <header className="topbar">
        <div className="brand">
          <span className="paw-logo" aria-hidden="true">
            <svg viewBox="0 0 24 24" role="img">
              <circle cx="6.5" cy="8" r="2.2" />
              <circle cx="11" cy="5.2" r="2.2" />
              <circle cx="15.5" cy="8" r="2.2" />
              <circle cx="18.2" cy="12.4" r="2.2" />
              <ellipse cx="10.8" cy="14.5" rx="4.8" ry="3.6" />
            </svg>
          </span>
          <h1>Patitas Chat</h1>
          <p>{chatTitle}</p>
        </div>
        <button
          type="button"
          className="ghost"
          onClick={() => setTheme((prev) => (prev === 'dark' ? 'light' : 'dark'))}
        >
          {theme === 'dark' ? 'Modo claro' : 'Modo oscuro'}
        </button>
      </header>

      <section className="session-panel">
        <div className="mode-switch">
          <button
            type="button"
            onClick={() => {
              setShowExistingPicker(false)
              createSession(createAnonUserId())
            }}
            disabled={isBusy}
          >
            Crear nueva sesión
          </button>
          <button
            type="button"
            onClick={() => setShowExistingPicker((prev) => !prev)}
            disabled={isBusy}
          >
            Elegir existente
          </button>
        </div>

        {showExistingPicker ? (
          <div className="existing-user">
            <select
              id="existing-user-select"
              value={selectedExistingUser}
              onChange={(e) => {
                const value = e.target.value
                setSelectedExistingUser(value)
                createSession(value)
              }}
              disabled={isBusy}
            >
              {DEFAULT_EXISTING_USERS.map((entry) => (
                <option key={entry.userId} value={entry.userId}>
                  {entry.clientName} ({entry.userId})
                </option>
              ))}
            </select>
          </div>
        ) : null}
        {connected ? (
          <small>
            user_id: <strong>{userId}</strong> · session_id: <strong>{sessionId}</strong>
          </small>
        ) : null}
      </section>

      <section className="chat-box">
        {messages.length === 0 ? (
          <div className="empty">No hay mensajes aún.</div>
        ) : (
          messages.map((message) => (
            <article key={message.id} className={`bubble ${message.role}`}>
              {message.text}
            </article>
          ))
        )}
      </section>

      <form className="composer" onSubmit={sendMessage}>
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={connected ? 'Escribe tu mensaje...' : 'Conecta una sesión para escribir'}
          disabled={!connected || isBusy}
        />
        <button type="submit" disabled={!connected || isBusy || !draft.trim()}>
          {isBusy ? 'Enviando...' : 'Enviar'}
        </button>
      </form>

      <footer className="footnote">Fecha actual: {asNaturalDate(new Date().toISOString())}</footer>
    </main>
  )
}

export default App
