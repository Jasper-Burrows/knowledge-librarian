# Opt-in live validation

Live validation is intentionally separate from CI and fails closed before constructing an OpenAI
client. The normal suite reports the live case as skipped.

## Deterministic preview

Run `make live-estimate`. With the default five-document fixture and one fixed validation question,
the 2026-08-03 pricing profile produces:

| Item | Expected | Bounded maximum |
| --- | ---: | ---: |
| Embedding requests | 6 (five documents and one query) | 18 attempts |
| Responses requests | 1 | 3 attempts |
| Embedding tokens | 744 | 2,232 retry-adjusted |
| Response input tokens | 3,500 | 10,500 retry-adjusted |
| Response output tokens | 900 | 2,700 retry-adjusted |
| Estimated cost | US$0.022265 | US$0.066795 |

The maximum includes the initial attempt and both bounded SDK retries for every request. The gate
compares that maximum—not the expected cost—with `LIBRARIAN_LIVE_VALIDATION_BUDGET_USD`, which
defaults to US$10. It refuses unpriced model overrides. Rates are US$2.50/M input and US$15/M output
for [GPT-5.6 Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra), and US$0.02/M input
for [text-embedding-3-small](https://developers.openai.com/api/docs/models/text-embedding-3-small).
Review current official prices before every live run.

## Approval and execution

1. Rotate any OpenAI credential that has ever appeared in historical material.
2. Create a least-privilege sandbox key and place it only in an untracked `.env` file.
3. Run `make live-estimate`; review calls, token bounds, price date, maximum cost, and cap.
4. Set all required gates:

   ```dotenv
   OPENAI_API_KEY=<new sandbox key>
   LIBRARIAN_LIVE_VALIDATION_BUDGET_USD=10.00
   LIBRARIAN_LIVE_VALIDATION_APPROVAL=I_APPROVE_LIVE_OPENAI_COSTS
   LIBRARIAN_LIVE_VALIDATION_KEY_ROTATED=true
   ```

5. Run either `uv run librarian live-validate` or `make test-live`—not both unless two validation
   runs are intended. Each creates a temporary fresh database and performs only the calls above.
6. Revoke temporary credentials and update `docs/validation.md` from “contract verified” to “live
   verified” only for calls that actually completed.

Missing approval, rotated-key attestation, key, reviewed pricing profile, or budget headroom blocks
the run before any external call. Logs and reports record only plan values and pass/fail state, never
the credential.
