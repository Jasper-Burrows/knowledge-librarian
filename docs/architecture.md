# Architecture and design decisions

## Domain boundaries

The core depends on five small protocols:

- `DocumentSource` asynchronously yields normalized, immutable `SourceDocument` values.
- `EmbeddingProvider` turns batches of strings into vectors.
- `VectorStore` upserts, removes, and ranks chunks.
- `Reranker` narrows fused candidates without changing the application flow.
- `AnswerGenerator` provides collected and streamed answers.

Adapters import inward toward those contracts. Optional Pinecone and Slack packages are imported
only when their features are explicitly constructed, so an offline process cannot fail due to a
missing provider SDK or credential.

## Ingestion data flow

1. A source maps provider records into stable IDs derived from provider and record identifiers.
2. SHA-256 content hashes make unchanged records no-ops.
3. Paragraph-aware deterministic chunking creates stable chunk IDs and token estimates.
4. SQLite stores the canonical document, chunks, full-text index, cached vectors, and sync jobs in
   one transaction boundary per document.
5. A successfully completed full source pass removes records no longer returned. A failed pass does
   not reconcile deletions.

Sync statistics are persisted after every document and at terminal state, making refresh status
inspectable after process restart. Repeating the same demo sync reports all records unchanged.
Connector page shapes are validated before an empty page is trusted, so malformed ClickUp/Stonly
responses fail the pass and cannot trigger deletion reconciliation.

Each document also persists `pending`, `indexed`, or `deleting` state plus a fingerprint covering
the embedding provider/model/dimension and vector backend/index/namespace. Vector replacement is
delete-then-upsert, and the document is marked indexed only after both steps succeed. Startup
reconciles pending records and every fingerprint mismatch, making failure retries idempotent and
forcing an offline-256-dimension database to re-embed before a live-1536-dimension query can run.
Deleting records are excluded from local retrieval and a failed vector deletion is retried on the
next authoritative source pass.

## Retrieval and answers

SQLite FTS5 supplies lexical candidates. The local store supplies cosine-ranked cached vectors;
Pinecone can occupy the same interface when configured. Reciprocal-rank fusion avoids comparing
provider-specific raw scores. A reranker hook and token-budget packer then bound the final context.

The deterministic mode extracts short source passages and always attaches `[n]` markers. Live mode
uses the Responses API with an instruction that treats retrieved content as untrusted, requires
per-claim citations, and abstains when evidence is insufficient. The service validates markers
against the retrieved set before emitting citation records or a grounded completion state. Live
model deltas are held behind that validation boundary; invalid output is replaced with the
no-context abstention before any unsupported text can reach the web or Slack.

## Delivery

FastAPI returns typed Server-Sent Events to the React client. Slack Socket Mode consumes the same
`LibrarianService` event stream, so retrieval, abstention, citations, and safety behavior cannot
drift between channels.

The production web root is the typed `LIBRARIAN_FRONTEND_DIST` setting. Docker explicitly sets it
to `/app/frontend/dist`, so a non-editable Python install under `.venv/site-packages` cannot change
where the separately built React application is discovered.
