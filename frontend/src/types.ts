export type SourceKind =
  | 'demo'
  | 'local_pdf'
  | 'clickup'
  | 'hubspot'
  | 'stonly'
  | 'microsoft_graph'

export interface Status {
  status: string
  mode: 'offline' | 'live'
  requested_mode: 'offline' | 'live'
  live_ready: boolean
  version: string
}

export interface Source {
  source: SourceKind
  enabled: boolean
  configured: boolean
  document_count: number
  last_synced_at: string | null
}

export interface Document {
  id: string
  source: SourceKind
  source_uri: string
  title: string
  updated_at: string
  content_hash: string
  chunk_count: number
}

export interface Citation {
  id: string
  document_id: string
  chunk_id: string
  title: string
  source: SourceKind
  source_uri: string
  excerpt: string
}

export interface StreamEvent {
  type: 'status' | 'delta' | 'citation' | 'done' | 'error'
  data: Record<string, unknown>
}

export interface ChatItem {
  id: string
  role: 'user' | 'assistant'
  text: string
  citations?: Citation[]
  grounded?: boolean
  pending?: boolean
}

