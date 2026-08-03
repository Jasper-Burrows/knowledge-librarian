import type { Document, Source, Status, StreamEvent } from './types'

const jsonHeaders = { 'Content-Type': 'application/json', Accept: 'application/json' }

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as { detail?: string }
    throw new Error(payload.detail ?? `Request failed (${String(response.status)})`)
  }
  return (await response.json()) as T
}

export const api = {
  status: () => requestJson<Status>('/healthz'),
  sources: () => requestJson<Source[]>('/api/v1/sources'),
  documents: () => requestJson<Document[]>('/api/v1/documents'),
  syncDemo: () => requestJson('/api/v1/sources/demo/sync', { method: 'POST' }),
  uploadPdf: async (file: File) => {
    const body = new FormData()
    body.append('file', file)
    return requestJson('/api/v1/sources/local-pdf', { method: 'POST', body })
  },
}

export async function streamChat(
  message: string,
  conversationId: string,
  onEvent: (event: StreamEvent) => void,
  history: Array<{ role: 'user' | 'assistant'; content: string }> = [],
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch('/api/v1/chat', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ message, conversation_id: conversationId, history: history.slice(-10) }),
    signal,
  })
  if (!response.ok || !response.body) {
    throw new Error(`Chat request failed (${String(response.status)})`)
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const parseFrame = (frame: string) => {
    let eventType = 'message'
    const data: string[] = []
    for (const line of frame.split('\n')) {
      if (line.startsWith('event:')) eventType = line.slice(6).trim()
      if (line.startsWith('data:')) data.push(line.slice(5).trim())
    }
    if (data.length && eventType !== 'message') {
      const parsed = JSON.parse(data.join('\n')) as unknown
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        throw new Error('The server returned an invalid stream event')
      }
      const validTypes: StreamEvent['type'][] = ['status', 'delta', 'citation', 'done', 'error']
      if (!validTypes.includes(eventType as StreamEvent['type'])) return
      onEvent({ type: eventType as StreamEvent['type'], data: parsed as Record<string, unknown> })
    }
  }

  let streamDone = false
  while (!streamDone) {
    const result = await reader.read()
    streamDone = result.done
    buffer += decoder.decode(result.value, { stream: !streamDone }).replace(/\r\n/g, '\n')
    const frames = buffer.split('\n\n')
    buffer = frames.pop() ?? ''
    frames.filter(Boolean).forEach(parseFrame)
  }
  if (buffer.trim()) parseFrame(buffer)
}
