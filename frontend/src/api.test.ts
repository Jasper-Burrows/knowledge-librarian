import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, streamChat } from './api'
import type { StreamEvent } from './types'

afterEach(() => {
  vi.restoreAllMocks()
})

function streamResponse(chunks: string[]): Response {
  const encoder = new TextEncoder()
  return new Response(
    new ReadableStream({
      start(controller) {
        chunks.forEach((chunk) => { controller.enqueue(encoder.encode(chunk)) })
        controller.close()
      },
    }),
    { status: 200, headers: { 'content-type': 'text/event-stream' } },
  )
}

describe('API client', () => {
  it('parses typed SSE events split across chunks and bounds history', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      streamResponse([
        'event: status\ndata: {"stage":"retrieving"}\n',
        '\nevent: delta\ndata: {"text":"Answer [1]"}\n\n',
        'event: done\ndata: {"grounded":true}\n\n',
      ]),
    )
    const events: StreamEvent[] = []
    const history = Array.from({ length: 14 }, (_, index) => ({
      role: index % 2 ? ('assistant' as const) : ('user' as const),
      content: `turn-${String(index)}`,
    }))
    await streamChat('question', 'conversation', (event) => { events.push(event) }, history)
    expect(events.map((event) => event.type)).toEqual(['status', 'delta', 'done'])
    expect(events[1]?.data.text).toBe('Answer [1]')
    const request = fetchMock.mock.calls[0]?.[1]
    if (typeof request?.body !== 'string') throw new Error('Expected a JSON request body')
    const body = JSON.parse(request.body) as { history: unknown[] }
    expect(body.history).toHaveLength(10)
  })

  it('uploads a PDF without setting an unsafe multipart content type', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      Response.json({ document_id: 'doc' }, { status: 201 }),
    )
    await api.uploadPdf(new File(['%PDF-1.7'], 'policy.pdf', { type: 'application/pdf' }))
    const request = fetchMock.mock.calls[0]?.[1]
    expect(request?.body).toBeInstanceOf(FormData)
    expect(request?.headers).toBeUndefined()
  })

  it('surfaces sanitized JSON errors and rejects broken chat streams', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      Response.json({ detail: 'Library unavailable' }, { status: 503 }),
    )
    await expect(api.documents()).rejects.toThrow('Library unavailable')
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(null, { status: 500 }))
    await expect(streamChat('question', 'conversation', () => undefined)).rejects.toThrow(
      'Chat request failed',
    )
  })
})
