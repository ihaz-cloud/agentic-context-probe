# Security Blueprint

Purpose: Cache Insights is a local operator tool that drives third-party vendor CLIs. Its security surface is dominated by **vendor credentials** and **outbound API calls that bill real money**. There are no end users, no app accounts, no PII storage.

## 0. Baseline Best Practices

- **Never hardcode secrets.** API keys, admin keys, and project IDs live in `prd/config.env`, never in source.
- **`prd/config.env` MUST be gitignored.** It contains the live `OPENAI_API_KEY`, `OPENAI_ADMIN_API_KEY`, and (when populated) the Anthropic/Google equivalents. Verify the file is in `.gitignore` before any commit; treat any commit that adds it as a credential exposure incident.
- **Least privilege for vendor keys.** Use project-scoped keys (e.g. `sk-proj-*`, `OPENAI_PROJECT_ID="agentic-context-probe"`) so admin-API queries cannot pull data from unrelated projects under the same org. Anthropic admin queries must be scoped via `ANTHROPIC_WORKSPACE_ID`.
- **Cost is a security concern.** A misconfigured test that bypasses the nonce or fails to set a project filter can drive thousands of dollars of unintended spend. Treat the §4.3 cost forecast as a pre-flight check, not an after-the-fact audit.

---

## 1. Data Sensitivity Level

**This project's data is: Internal / Operational secrets.**

There is no end-user data and no PII. The sensitivity comes entirely from:

1. **Vendor API credentials** in `prd/config.env` — leaking these grants paid API access to OpenAI, Anthropic, or Google on the operator's billed account.
2. **Telemetry artifacts** at `~/.claude/projects/<slug>/<uuid>.jsonl`, `~/.gemini/telemetry.log`, and `/tmp/otel-data/codex-logs.jsonl` — these contain prompt content, model responses, and usage breakdowns. The prompts here are **synthetic nonced payloads**, so substantive content leakage is low, but the files reveal account/workspace identifiers.
3. **Result files** in `results/` — JSON test records contain nonces, model IDs, and token counts. No user data. Considered Internal.

---

## 2. Authentication & Authorization

There is no authentication *into* this system. Authentication runs *outward* from this system into the three vendors.

| Vendor | Auth Mode (preferred) | Why |
|--------|------------------------|-----|
| **OpenAI** | API key (`sk-proj-…`) via `OPENAI_API_KEY`, with `OPENAI_PROJECT_ID` filter | Required so the OpenAI Admin API can see usage emitted by Codex CLI. ChatGPT-OAuth-routed usage is invisible to the admin endpoint. |
| **Anthropic** | API key (`sk-ant-api03-…`) via `ANTHROPIC_API_KEY` + `ANTHROPIC_WORKSPACE_ID` filter | Required so the Anthropic Admin API can see usage. Claude.ai-OAuth-routed usage is invisible to the admin endpoint. |
| **Google / Gemini** | API key (`AIza…`) via `GEMINI_API_KEY`, or Vertex via `GOOGLE_CLOUD_PROJECT_ID` | Google does not expose an org-level admin/usage API for Gemini that returns cached-vs-uncached breakdowns (vendor capability gap, lexicon §8.2.6). Cache evidence falls back to local OTel telemetry + footer. |

**Authorization rules:**
- The operator is the only principal. Any process running as the operator can invoke the vendor CLIs and read the local telemetry sources.
- Vendor admin keys (`OPENAI_ADMIN_API_KEY`, `ANTHROPIC_ADMIN_API_KEY`) are **distinct from project keys** and grant read access to org-level usage. Provision separately at:
  - OpenAI: `https://platform.openai.com/settings/organization/admin-keys`
  - Anthropic: `https://console.anthropic.com/settings/admin-keys`
- This system never modifies operator CLI credentials, session state, or workspace settings beyond the one-time telemetry-enablement changes documented in `prd/DESIGN.prd.md` §5.3.

**`GOOGLE_ADMIN_API_KEY` and `GOOGLE_WORKSPACE_ID` must remain empty** — they are placeholders for cross-tool config parity. Populating them does not unlock new capability for this system.

---

## 3. Dependency & Supply Chain Security

| Surface | Practice |
|---------|----------|
| **Python deps** | Pinned via `requirements.txt` (when introduced). Run `pip audit` before each release pass. Prefer the standard library; avoid wide dependency trees. |
| **Vendor CLI versions** | Pinned in `architecture.md` (Codex 0.122.0, Claude Code 2.1.116, Gemini CLI 0.38.2). Bumping a CLI version requires re-running the prefix-warmup test — old measurements may not transfer. |
| **OTel Collector image** | Run `otel/opentelemetry-collector` as an unprivileged container with bind mounts limited to the config file and `/tmp/otel-data`. Do not expose port 4318 outside `localhost`. |
| **New dependencies** | Reviewed by the operator before adding. Justify against existing capability — the project intentionally has a small dependency footprint. |

---

## 4. Secrets Management & Best Practices

### Inventory

The complete list of secrets handled by this system, sourced from `prd/config.env`:

| Variable | Form | Purpose | Notes |
|----------|------|---------|-------|
| `OPENAI_API_KEY` | `sk-proj-…` | Codex CLI auth so admin API can attribute usage | Project-scoped |
| `OPENAI_ADMIN_API_KEY` | `sk-admin-…` | Org-level usage queries | Distinct from project key |
| `OPENAI_PROJECT_ID` | `proj_…` / project slug | Filter admin queries to this project | Prevents cross-project contamination |
| `ANTHROPIC_API_KEY` | `sk-ant-api03-…` | Claude Code auth so admin API can attribute usage | Currently empty in committed config — populate locally |
| `ANTHROPIC_ADMIN_API_KEY` | `sk-ant-admin01-…` | Org-level usage queries | Distinct from project key |
| `ANTHROPIC_WORKSPACE_ID` | `wrkspc_…` | Filter admin queries to this workspace | Prevents cross-workspace contamination |
| `GEMINI_API_KEY` | `AIza…` | AI Studio key for Gemini CLI | Optional; Vertex auth is the alternative |
| `GOOGLE_CLOUD_PROJECT_ID` | GCP project id | Vertex auth path | |
| `GOOGLE_ADMIN_API_KEY` / `GOOGLE_WORKSPACE_ID` | — | **Must remain empty** | Vendor capability gap |

### Storage

- **Where stored:** `prd/config.env` on the operator workstation. The file is sourced via `bash` + `env -0` (null-delimited) to preserve multiline values.
- **Who has access:** the operator only. There is no team or shared environment.
- **Gitignore status:** `prd/config.env` MUST be in `.gitignore`. Verify before each commit. **The current committed config contains live OpenAI keys** — this is a known exposure that must be rotated and the file gitignored before the repo is shared.

### Handling Rules

1. **Never commit `prd/config.env`.** Run `git check-ignore prd/config.env` and confirm a match before `git add`. CI hooks should hard-fail on any diff to a gitignored secrets file.
2. **Never log secret values.** Result records may include vendor IDs (project, workspace) for traceability but never raw key material.
3. **Rotate on suspected exposure.** Any commit/push that includes `prd/config.env`, any shared screenshot of the file, or any unintended log of a key triggers immediate rotation at the vendor portal.
4. **Telemetry hygiene.** `~/.claude/projects/`, `~/.gemini/telemetry.log`, and `/tmp/otel-data/codex-logs.jsonl` may contain prompt text, model responses, and account identifiers. Treat them as Internal: do not paste into bug reports, issues, or external chat without redaction.

### Operational Risks

| Risk | Mitigation |
|------|-----------|
| Live API key committed in `prd/config.env` | Rotate the OpenAI keys currently visible in `prd/config.env`; ensure `.gitignore` covers the file before next commit |
| Unbounded test run consumes paid quota | The §4.3 cost forecast must run before any large §4.1 sweep. TTL test (24h interval) terminates early on first miss to bound wall-clock and spend. |
| OTel collector exposed beyond localhost | The collector binds `0.0.0.0:4318` per the documented config — restrict to `127.0.0.1:4318` on multi-tenant or networked hosts. |
| Cross-project / cross-workspace contamination of admin-API queries | Always set `OPENAI_PROJECT_ID` and `ANTHROPIC_WORKSPACE_ID` filters; the harness should refuse to call the admin API without them. |
