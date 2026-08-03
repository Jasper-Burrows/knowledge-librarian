# Validation record

This file is updated from local and CI results before a release. A green check means the behavior
was exercised without external credentials; it does not imply a live provider call.

## Verification matrix

| Integration | Status | Evidence |
| --- | --- | --- |
| Synthetic demo + SQLite FTS/vector retrieval | Offline verified | Unit, API, and browser journey tests |
| Local text PDF | Offline verified | Valid, malformed, empty, oversized, and traversal-name tests |
| OpenAI Responses + embeddings | Contract verified | SDK request-shape tests; live suite requires a fresh key |
| ClickUp | Contract verified | Synthetic pagination/error responses |
| HubSpot | Contract verified | Synthetic cursor pagination/error responses |
| Stonly | Contract verified | Synthetic cursor pagination/error responses |
| Microsoft Graph email | Contract verified | Synthetic OAuth, pagination, and origin-rejection responses |
| Pinecone | Contract verified | Optional adapter boundary and metadata round-trip tests |
| Slack Socket Mode | Contract verified | Token validation and shared-service event tests |

## Release acceptance

- Python format/lint, strict type checking, backend coverage, frontend lint/type checks, unit tests,
  production build, Playwright journey, secret scan, dependency audits, CodeQL, and container build.
- Manual keyboard and responsive review of chat, citations, source panel, upload dialog, and errors.
- No historical cache, PDF, output, log, `.env`, credential, employer record, private URL, or Git
  history in the repository.

Live validation remains explicitly pending until the owner approves a cost preview and supplies
new sandbox credentials. The total OpenAI validation budget is capped at US$10.

## Local acceptance run — 2026-08-03

The local workspace executable reports Node.js 24.14.0. Because that app-bundled binary could not
load a signed native CSS dependency, frontend acceptance was rerun with a checksum-verified official
Node.js 24.17.0 archive; Docker independently targets Node.js 24.17.0. Python checks used 3.13.9.

| Gate | Result |
| --- | --- |
| Ruff formatting and linting | Passed |
| Strict mypy | Passed across 26 source files |
| Backend tests | 52 passed and 1 live test safely skipped; 88.42% overall coverage and 96% core-domain coverage |
| Frontend unit/accessibility tests | 6 passed; 76.51% statements, 66.90% branches, 66% functions, 82.40% lines |
| Playwright offline journeys | 2 passed (desktop and Pixel 7); 2 expected cross-project skips |
| Frontend production build | Passed; 243.13 kB JavaScript (76.26 kB gzip) |
| Python dependency audit | No known vulnerabilities |
| npm dependency audit | 0 vulnerabilities |
| Credential-pattern scan | No credential-shaped values found outside ignored generated folders |
| Third-party terms | No project license is granted; PyMuPDF AGPL-3.0/commercial terms are documented |

The tested browser run generated the README screenshot at
`frontend/public/screenshots/knowledge-librarian-offline.png`. Docker was not available in the
local execution environment, so the container is definition-reviewed locally and remains scheduled
for an actual build in the CI `container` job. Gitleaks and CodeQL likewise run in CI; no live
OpenAI, Slack, Pinecone, or SaaS provider calls were made.
