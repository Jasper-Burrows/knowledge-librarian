# Security policy

## Reporting

Please report a suspected vulnerability privately to the repository owner through GitHub's
security-advisory workflow. Do not include secrets or sensitive documents in a public issue.

## Data and credential boundary

The checked-in demo is entirely synthetic. The application never needs an employer credential,
and any credential found in historical internship material must be treated as compromised and
rotated rather than reused here.

- Secrets are read server-side from environment variables and represented as `SecretStr` values.
- Empty copied `.env` credential values normalize to `None`; they cannot accidentally activate live mode.
- Uploaded PDFs are size/type/page validated, parsed in memory, and not saved.
- Logs contain operation names and exception classes, never prompts, documents, tokens, or keys.
- Configurable connector origins require HTTPS; redirects are disabled.
- Retrieved text is enclosed as untrusted data and cannot override the answer instructions.
- Live output is withheld until all citation markers validate; invalid output fails closed to abstention.
- Live Responses requests disable storage and send only a SHA-256 conversation safety identifier.

This reference implementation has no authentication layer because it binds to localhost by
default. Add identity, authorization, tenant isolation, encryption-key management, audit logging,
rate limiting, malware scanning, and an approved data-retention policy before any shared or public
deployment.

## Supported versions

Security updates target the latest tagged release. Dependency and CodeQL checks run on every pull
request and weekly thereafter.
