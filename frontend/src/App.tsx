import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowUp,
  BookOpen,
  Check,
  ChevronRight,
  Cloud,
  Database,
  FileText,
  Library,
  LoaderCircle,
  PanelRightClose,
  PanelRightOpen,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  Upload,
  WifiOff,
  X,
} from 'lucide-react'
import { api, streamChat } from './api'
import type { ChatItem, Citation, Document, SourceKind, StreamEvent } from './types'

const prompts = [
  'What is the Sev-1 response process?',
  'How much is the home-office allowance?',
  'When can production releases happen?',
  'How long are support exports retained?',
]

const sourceLabels: Record<SourceKind, string> = {
  demo: 'Demo library',
  local_pdf: 'Local PDFs',
  clickup: 'ClickUp',
  hubspot: 'HubSpot',
  stonly: 'Stonly',
  microsoft_graph: 'Microsoft Graph',
}

const welcome: ChatItem = {
  id: 'welcome',
  role: 'assistant',
  text: 'I search the library before I answer, and I show exactly where each claim came from. Try one of the questions below.',
  grounded: true,
}

export function App() {
  const queryClient = useQueryClient()
  const status = useQuery({ queryKey: ['status'], queryFn: api.status })
  const sources = useQuery({ queryKey: ['sources'], queryFn: api.sources })
  const documents = useQuery({ queryKey: ['documents'], queryFn: api.documents })
  const [messages, setMessages] = useState<ChatItem[]>([welcome])
  const [question, setQuestion] = useState('')
  const [stage, setStage] = useState('')
  const [panelOpen, setPanelOpen] = useState(() => window.innerWidth > 1020)
  const [selected, setSelected] = useState<Document | null>(null)
  const [selectedCitation, setSelectedCitation] = useState<Citation | null>(null)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [error, setError] = useState('')
  const conversationId = useRef(crypto.randomUUID())
  const scrollAnchor = useRef<HTMLDivElement>(null)

  const refreshLibrary = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['sources'] }),
      queryClient.invalidateQueries({ queryKey: ['documents'] }),
    ])
  }

  const syncMutation = useMutation({ mutationFn: api.syncDemo, onSuccess: refreshLibrary })
  const uploadMutation = useMutation({
    mutationFn: api.uploadPdf,
    onSuccess: async () => {
      setUploadOpen(false)
      await refreshLibrary()
    },
  })

  useEffect(() => {
    scrollAnchor.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, stage])

  const updateAssistant = (id: string, updater: (item: ChatItem) => ChatItem) => {
    setMessages((current) => current.map((item) => (item.id === id ? updater(item) : item)))
  }

  const ask = async (raw: string) => {
    const value = raw.trim()
    if (!value || stage) return
    setQuestion('')
    setError('')
    setStage('Searching sources')
    const answerId = crypto.randomUUID()
    setMessages((current) => [
      ...current,
      { id: crypto.randomUUID(), role: 'user', text: value },
      { id: answerId, role: 'assistant', text: '', citations: [], pending: true },
    ])
    try {
      const history = messages
        .filter((item) => item.id !== 'welcome' && item.text && !item.pending)
        .slice(-10)
        .map((item) => ({ role: item.role, content: item.text }))
      await streamChat(value, conversationId.current, (event: StreamEvent) => {
        if (event.type === 'status') {
          const eventStage = typeof event.data.stage === 'string' ? event.data.stage : ''
          setStage(eventStage === 'answering' ? 'Writing a grounded answer' : 'Searching sources')
        }
        if (event.type === 'delta') {
          updateAssistant(answerId, (item) => ({ ...item, text: item.text + String(event.data.text) }))
        }
        if (event.type === 'citation') {
          updateAssistant(answerId, (item) => ({
            ...item,
            citations: [...(item.citations ?? []), event.data as unknown as Citation],
          }))
        }
        if (event.type === 'done') {
          updateAssistant(answerId, (item) => ({
            ...item,
            pending: false,
            grounded: Boolean(event.data.grounded),
          }))
        }
        if (event.type === 'error') {
          const message = typeof event.data.message === 'string' ? event.data.message : 'Chat failed'
          throw new Error(message)
        }
      }, history)
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : 'The answer could not be completed.'
      setError(message)
      updateAssistant(answerId, (item) => ({ ...item, text: message, pending: false, grounded: false }))
    } finally {
      setStage('')
    }
  }

  const mode = status.data?.mode ?? 'offline'

  return (
    <div className="app-shell">
      <aside className="rail" aria-label="Primary navigation">
        <div className="brand-mark"><Library size={20} aria-hidden="true" /></div>
        <nav>
          <button className="rail-button active" aria-label="Chat"><Sparkles size={19} /></button>
          <button className="rail-button" aria-label="Library" onClick={() => { setPanelOpen(true) }}><BookOpen size={19} /></button>
        </nav>
        <button className="rail-button" aria-label="Add a PDF" onClick={() => { setUploadOpen(true) }}><Plus size={20} /></button>
      </aside>

      <main className="chat-column">
        <header className="topbar">
          <div>
            <div className="eyebrow">Knowledge workspace</div>
            <h1>Ask the Librarian</h1>
          </div>
          <div className="topbar-actions">
            <div className={`mode-pill ${mode}`}>
              {mode === 'live' ? <Cloud size={14} /> : <WifiOff size={14} />}
              {mode === 'live' ? 'Live AI' : 'Offline demo'}
            </div>
            <button className="icon-button desktop-panel-toggle" onClick={() => { setPanelOpen(!panelOpen) }} aria-label={panelOpen ? 'Hide source panel' : 'Show source panel'}>
              {panelOpen ? <PanelRightClose size={19} /> : <PanelRightOpen size={19} />}
            </button>
          </div>
        </header>

        <section className="conversation" aria-live="polite">
          <div className="conversation-inner">
            <div className="intro-card">
              <div className="intro-icon"><ShieldCheck size={24} /></div>
              <div>
                <p className="intro-kicker">Answers you can verify</p>
                <p>Every response is grounded in the indexed library. Source text is treated as untrusted data, never as instructions.</p>
              </div>
            </div>

            {messages.map((message) => (
              <article key={message.id} className={`message ${message.role}`}>
                <div className="message-label">{message.role === 'user' ? 'You' : 'Librarian'}</div>
                <div className="message-bubble">
                  {message.text ? <p>{message.text}</p> : <div className="thinking"><span /><span /><span /></div>}
                  {message.citations && message.citations.length > 0 && (
                    <div className="citation-list" aria-label="Sources">
                      {message.citations.map((citation) => (
                        <button key={citation.chunk_id} className="citation-chip" onClick={() => {
                          const document = documents.data?.find((item) => item.id === citation.document_id) ?? null
                          setSelected(document)
                          setSelectedCitation(citation)
                          setPanelOpen(true)
                        }}>
                          <span>{citation.id}</span>{citation.title}<ChevronRight size={13} />
                        </button>
                      ))}
                    </div>
                  )}
                  {!message.pending && message.role === 'assistant' && message.id !== 'welcome' && (
                    <div className={`grounding ${message.grounded ? '' : 'warning'}`}>
                      {message.grounded ? <><Check size={13} /> Citation check passed</> : 'No supported answer found'}
                    </div>
                  )}
                </div>
              </article>
            ))}

            {messages.length === 1 && (
              <div className="prompt-grid">
                {prompts.map((prompt) => (
                  <button key={prompt} onClick={() => void ask(prompt)}>
                    <span>{prompt}</span><ArrowUp size={16} />
                  </button>
                ))}
              </div>
            )}
            {stage && <div className="stage"><LoaderCircle className="spin" size={15} />{stage}</div>}
            {error && <div className="error-banner" role="alert">{error}</div>}
            <div ref={scrollAnchor} />
          </div>
        </section>

        <form className="composer-wrap" onSubmit={(event) => { event.preventDefault(); void ask(question) }}>
          <div className="composer">
            <textarea value={question} onChange={(event) => { setQuestion(event.target.value) }} onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void ask(question) }
            }} placeholder="Ask about policy, process, or product knowledge…" aria-label="Question" rows={1} maxLength={4000} />
            <button type="submit" disabled={!question.trim() || Boolean(stage)} aria-label="Send question"><ArrowUp size={18} /></button>
          </div>
          <p>Answers are limited to indexed sources. Check citations before acting.</p>
        </form>
      </main>

      {panelOpen && (
        <aside className="source-panel" aria-label="Source library">
          <header>
            <div><div className="eyebrow">Ground truth</div><h2>Source library</h2></div>
            <button className="icon-button mobile-close" onClick={() => { setPanelOpen(false) }} aria-label="Close source panel"><X size={18} /></button>
          </header>
          <div className="library-summary">
            <div><strong>{documents.data?.length ?? '—'}</strong><span>documents</span></div>
            <div><strong>{documents.data?.reduce((total, item) => total + item.chunk_count, 0) ?? '—'}</strong><span>searchable sections</span></div>
          </div>
          <div className="panel-actions">
            <button onClick={() => { setUploadOpen(true) }}><Upload size={15} /> Add PDF</button>
            <button aria-label="Refresh demo library" onClick={() => { syncMutation.mutate() }} disabled={syncMutation.isPending}><RefreshCw size={15} className={syncMutation.isPending ? 'spin' : ''} /></button>
          </div>
          <div className="search-box"><Search size={15} /><span>Browse indexed content</span></div>

          {documents.isLoading && <PanelSkeleton />}
          {documents.isError && <div className="panel-error">The source library is unavailable.</div>}
          {documents.data?.length === 0 && <div className="empty-state"><Database size={24} /><p>No documents indexed yet.</p></div>}
          <div className="document-list">
            {documents.data?.map((document) => (
              <button key={document.id} className={`document-card ${selected?.id === document.id ? 'selected' : ''}`} onClick={() => { setSelected(document); setSelectedCitation(null) }}>
                <div className="document-icon"><FileText size={16} /></div>
                <div><strong>{document.title}</strong><span>{sourceLabels[document.source]} · {document.chunk_count} sections</span></div>
                <ChevronRight size={15} />
              </button>
            ))}
          </div>
          {selected && (
            <div className="document-detail">
              <button className="detail-close" onClick={() => { setSelected(null); setSelectedCitation(null) }} aria-label="Close document details"><X size={15} /></button>
              <div className="eyebrow">Selected source</div>
              <h3>{selected.title}</h3>
              <p>{sourceLabels[selected.source]} · {selected.chunk_count} indexed sections</p>
              {selectedCitation?.document_id === selected.id && (
                <div className="evidence-excerpt">
                  <div className="eyebrow">Supporting excerpt</div>
                  <blockquote>{selectedCitation.excerpt}</blockquote>
                </div>
              )}
              <code>{selected.content_hash.slice(0, 12)}…</code>
            </div>
          )}
          <div className="connection-list">
            <h3>Connections</h3>
            {sources.data?.map((source) => (
              <div key={source.source}>
                <span className={`connection-dot ${source.enabled && source.configured ? 'ready' : ''}`} />
                <span>{sourceLabels[source.source]}</span>
                <small>{source.source === 'demo' && syncMutation.isPending
                  ? 'Syncing…'
                  : source.last_synced_at
                    ? `${String(source.document_count)} docs · Synced`
                    : source.document_count || (source.configured ? 'Ready' : 'Not configured')}</small>
              </div>
            ))}
          </div>
        </aside>
      )}

      {uploadOpen && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setUploadOpen(false) }}>
          <section className="modal" role="dialog" aria-modal="true" aria-labelledby="upload-title">
            <button className="modal-close" onClick={() => { setUploadOpen(false) }} aria-label="Close"><X size={18} /></button>
            <div className="upload-icon"><Upload size={22} /></div>
            <h2 id="upload-title">Add a PDF source</h2>
            <p>The file is read in memory and is not retained. Text PDFs up to 10 MB are supported.</p>
            <label className="file-drop">
              <input type="file" accept="application/pdf,.pdf" onChange={(event) => {
                const file = event.target.files?.[0]
                if (file) uploadMutation.mutate(file)
              }} />
              {uploadMutation.isPending ? <LoaderCircle className="spin" /> : <FileText />}
              <strong>{uploadMutation.isPending ? 'Indexing PDF…' : 'Choose a PDF'}</strong>
              <span>or drag it onto this control</span>
            </label>
            {uploadMutation.isError && <div className="error-banner" role="alert">{uploadMutation.error.message}</div>}
          </section>
        </div>
      )}
    </div>
  )
}

function PanelSkeleton() {
  return <div className="panel-skeleton" aria-label="Loading sources"><span /><span /><span /></div>
}
