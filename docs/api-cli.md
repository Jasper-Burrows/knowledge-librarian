# API and CLI reference

The FastAPI server binds to `127.0.0.1:8000` by default. Interactive OpenAPI documentation is at
`/api/docs`; the machine-readable schema is `/api/openapi.json`. This portfolio app has no user
authentication layer and must remain loopback-only unless an external identity and authorization
layer is added.

## Chat

### `POST /api/v1/chat`

Streams typed Server-Sent Events. Request body:

```json
{
  "message": "How quickly must a severity-one incident be acknowledged?",
  "conversation_id": "browser-3f6f",
  "history": [
    {"role": "user", "content": "Tell me about incident response."},
    {"role": "assistant", "content": "What would you like to know?"}
  ]
}
```

`message` is 1–4,000 characters after trimming, `conversation_id` is 1–100 characters, and history
is limited to 20 messages of at most 12,000 characters each. The web client sends only its last ten
messages. Events are separated by a blank line:

```text
event: status
data: {"stage":"retrieving","mode":"offline"}

event: delta
data: {"text":"The on-call engineer must acknowledge… [2]"}

event: citation
data: {"id":"2","document_id":"doc_…","chunk_id":"chk_…","title":"Customer Incident Playbook","source":"demo","source_uri":"kb://support/incidents","excerpt":"A severity-one incident…"}

event: done
data: {"grounded":true}
```

Event contracts:

| Event | Data | Meaning |
| --- | --- | --- |
| `status` | `stage`, plus mode or match count | Retrieval/generation progress |
| `delta` | `text` | Approved answer text fragment |
| `citation` | citation ID, document/chunk IDs, title, source, URI, excerpt | Evidence for a used `[n]` marker |
| `done` | `grounded` boolean | Terminal validation result |
| `error` | sanitized `message` | Terminal stream failure |

Live model output is buffered until all citation markers validate. An invalid live answer produces
only the standard no-context abstention and `grounded: false`; unsupported model text is never
released as a delta.

Example:

```bash
curl -N http://127.0.0.1:8000/api/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"What is the Sev-1 response process?","conversation_id":"curl-demo"}'
```

### `POST /api/v1/chat/answer`

Accepts the same request and returns one JSON `Answer` for automation:

```json
{
  "text": "The on-call engineer must acknowledge a Sev-1 alert within 10 minutes. [2]",
  "citations": [{"id": "2", "title": "Customer Incident Playbook", "excerpt": "…"}],
  "grounded": true,
  "mode": "offline"
}
```

## Library and operations

| Method and path | Response/purpose |
| --- | --- |
| `GET /healthz` | Process status, actual/requested mode, live readiness, version |
| `GET /readyz` | Storage readiness; returns 503 when SQLite is unavailable |
| `GET /api/v1/sources` | Source enablement, configuration, document counts, last successful sync |
| `GET /api/v1/documents` | Document IDs, safe source URIs, titles, hashes, timestamps, chunk counts |
| `GET /api/v1/sync-jobs` | Most recent persisted synchronization jobs |
| `GET /api/v1/sync-jobs/{job_id}` | One job, or 404 |
| `POST /api/v1/sources/demo/sync` | Idempotently refresh the fictional demo library |
| `POST /api/v1/sources/{source}/sync` | Refresh `demo`, `clickup`, `hubspot`, `stonly`, or `microsoft_graph` |
| `POST /api/v1/sources/local-pdf` | Multipart `file` upload; text PDF only, memory-only, configured size/page limits |

Source sync returns a persisted job such as:

```json
{
  "id": "sync_…",
  "source": "demo",
  "status": "complete",
  "discovered": 5,
  "created": 0,
  "updated": 0,
  "unchanged": 5,
  "deleted": 0,
  "error": null
}
```

Only explicitly enabled/configured SaaS adapters can sync. For
`POST /api/v1/sources/{source}/sync`, loopback clients are allowed directly. A non-loopback client
must send `X-Sync-Token` matching server-only `LIBRARIAN_SYNC_TOKEN`; comparison is constant-time.
That token is not browser authentication and does not make the rest of the app safe for public
network exposure.

Common errors are 403 (remote sync token missing/invalid), 404 (unknown job), 409 (adapter disabled
or incomplete configuration), 413 (upload too large), 422 (request/PDF validation), 502 (provider
sync failure), 503 (storage not ready), and a sanitized 500 for unexpected failures. Provider
payloads, prompts, credentials, and stack traces are never returned.

## CLI

All commands use typed settings from environment variables or an untracked `.env` file:

| Command | Options/arguments | Purpose |
| --- | --- | --- |
| `uv run librarian serve` | `--host` (default `127.0.0.1`), `--port` (8000), `--reload` | Run HTTP/API and configured production UI |
| `uv run librarian demo [QUESTION]` | Optional question | Credential-free synthetic answer with citations |
| `uv run librarian sync-demo` | None | Idempotent synthetic refresh |
| `uv run librarian sync SOURCE` | Required source name | Refresh one enabled adapter |
| `uv run librarian import-pdf PATH` | Required local PDF path | Validate/index a text PDF without retaining the file |
| `uv run librarian slack` | None | Run Slack Socket Mode; requires explicit enablement and all Slack credentials |
| `uv run librarian live-estimate` | None | Print deterministic calls, tokens, prices, retry ceiling, cap, and approval phrase; makes no provider call |
| `uv run librarian live-validate` | None | Run one fixed OpenAI validation only after budget, exact approval, fresh-key, and rotation gates pass |

Use `uv run librarian COMMAND --help` for generated option details. `make dev` starts the API and
Vite UI together; `make check`, `make test-e2e`, `make security`, and `make test-live` expose the
corresponding quality and opt-in workflows.
