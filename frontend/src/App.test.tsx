import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import axe from 'axe-core'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from './App'
import { api, streamChat } from './api'

vi.mock('./api', () => ({
  api: {
    status: vi.fn(),
    sources: vi.fn(),
    documents: vi.fn(),
    syncDemo: vi.fn(),
    uploadPdf: vi.fn(),
  },
  streamChat: vi.fn(),
}))

const document = {
  id: 'doc-1',
  source: 'demo' as const,
  source_uri: 'kb://incident',
  title: 'Customer Incident Playbook',
  updated_at: '2026-01-01T00:00:00Z',
  content_hash: 'a'.repeat(64),
  chunk_count: 2,
}

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.mocked(api.status).mockResolvedValue({
    status: 'ok', mode: 'offline', requested_mode: 'offline', live_ready: false, version: '1.0.0',
  })
  vi.mocked(api.sources).mockResolvedValue([
    {
      source: 'demo', enabled: true, configured: true, document_count: 1,
      last_synced_at: '2026-08-03T00:00:00Z',
    },
  ])
  vi.mocked(api.documents).mockResolvedValue([document])
  vi.mocked(api.syncDemo).mockResolvedValue({})
  vi.mocked(api.uploadPdf).mockResolvedValue({})
  vi.mocked(streamChat).mockImplementation((_message, _conversation, onEvent) => {
    onEvent({ type: 'status', data: { stage: 'answering' } })
    onEvent({ type: 'delta', data: { text: 'Acknowledge within ten minutes. [1]' } })
    onEvent({
      type: 'citation',
      data: {
        id: '1', document_id: document.id, chunk_id: 'chunk-1', title: document.title,
        source: 'demo', source_uri: document.source_uri, excerpt: 'Acknowledge within ten minutes.',
      },
    })
    onEvent({ type: 'done', data: { grounded: true } })
    return Promise.resolve()
  })
})

describe('App', () => {
  it('renders an accessible offline workspace', async () => {
    const { container } = renderApp()
    expect(await screen.findByText('Offline demo')).toBeInTheDocument()
    expect(await screen.findByText('Customer Incident Playbook')).toBeInTheDocument()
    expect(await screen.findByText('1 docs · Synced')).toBeInTheDocument()
    const results = await axe.run(container, { rules: { 'color-contrast': { enabled: false } } })
    expect(results.violations).toEqual([])
  })

  it('completes a grounded chat journey and opens its cited source', async () => {
    const user = userEvent.setup()
    renderApp()
    await screen.findByText('Customer Incident Playbook')
    await user.click(screen.getByRole('button', { name: 'What is the Sev-1 response process?' }))
    expect(await screen.findByText(/Acknowledge within ten minutes/)).toBeInTheDocument()
    expect(screen.getByText('Citation check passed')).toBeInTheDocument()
    await user.click(
      within(screen.getByLabelText('Sources')).getByRole('button', {
        name: /Customer Incident Playbook/,
      }),
    )
    expect(screen.getByText('Selected source')).toBeInTheDocument()
    expect(screen.getByText('Acknowledge within ten minutes.')).toBeInTheDocument()
    expect(vi.mocked(streamChat)).toHaveBeenCalledOnce()
  })

  it('opens the PDF dialog and refreshes the synthetic library', async () => {
    const user = userEvent.setup()
    renderApp()
    await screen.findByText('Customer Incident Playbook')
    await user.click(screen.getByRole('button', { name: 'Add a PDF' }))
    expect(screen.getByRole('dialog', { name: 'Add a PDF source' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Close' }))
    await user.click(screen.getByRole('button', { name: 'Refresh demo library' }))
    await waitFor(() => { expect(api.syncDemo).toHaveBeenCalledOnce() })
  })
})
