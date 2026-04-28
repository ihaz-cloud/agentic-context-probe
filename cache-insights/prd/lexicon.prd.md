# Lexicon

## Document Scope

**This document is a vendor reference, not a product specification.** It documents the external command-line tools that the framework drives — Claude Code, Gemini CLI, and OpenAI Codex CLI — by enumerating their commands, flags, slash commands, key sequences, authentication methods, file layouts, and other operator-visible behaviors. It does not define what the framework itself does; that is the responsibility of `DESIGN.prd.md`.

The relationship between the two documents is asymmetric and one-directional:

- **`DESIGN.prd.md`** specifies the framework's required behavior in tool-agnostic terms ("the framework must create a durable, addressable checkpoint after each tier loads"). It is the product specification. It changes when the framework's design changes.
- **`lexicon.prd.md`** specifies what each external tool offers, in tool-specific terms ("Claude Code creates a checkpoint via `claude --resume <name> --fork-session` followed by an in-session `/rename`"). It is a vendor reference. It changes when vendors release new versions of their CLI tools, independently of any change to our product.

When `DESIGN.prd.md` describes a behavior in abstract terms, this document maps that behavior to the concrete primitives each tool exposes. An implementer satisfying a requirement in `DESIGN.prd.md` consults this lexicon to determine which vendor command, flag, or in-session operation to use for each target tool.

This document is descriptive about what each command *does*; it does not prescribe how an implementer must use it. Implementers may select whichever combination of these primitives best satisfies the invariants in `DESIGN.prd.md`.

Where a target tool does not expose an equivalent for a framework concept, this document records the absence as a capability gap rather than describing a workaround. Workarounds are an implementer's choice and belong in implementation notes, not in this lexicon.

The only section of this lexicon that touches the framework's own vocabulary is Section 1, which defines the abstract terms (target tool, checkpoint, tier, run, and so on) shared between this document and `DESIGN.prd.md`. Sections 2 through 6 are pure vendor documentation; Section 7 explains how the two documents are intended to be used together.

## Pinned Tool Versions

This lexicon was authored against the following target tool versions. Vendors evolve their CLIs continuously; commands, flags, and behaviors may differ in versions other than those listed here. An implementer working from this document must verify the current syntax of any command against the version of the target tool actually installed in the implementation environment.

| Target tool | Pinned version | Last verified |
|---|---|---|
| Claude Code | `2.1.92` | 2026-04-06 |
| Gemini CLI | `0.36.0` | 2026-04-06 |
| OpenAI Codex CLI | `codex-cli 0.118.0` | 2026-04-06 |

When a vendor releases a new version that introduces, removes, or changes a command relevant to the framework, this lexicon must be updated and the pinned version (and "last verified" date) advanced accordingly. Updates that introduce new capabilities should also be reflected in `DESIGN.prd.md`'s per-tool capability matrix and capability gap summary, because changes in vendor capabilities may close or open gaps that affect the framework's tool support claims.

When updating, the maintainer should re-verify *all* commands listed in this lexicon against the new version, not only those known to have changed, because vendor releases can introduce silent behavior changes (timing, output format, key sequence handling) that this lexicon depends upon.

---

## 1. Framework Abstract Terms

These terms have a single normative definition across the entire project. They are tool-agnostic by construction.

**Target tool.** An interactive AI coding assistant that the framework drives. Currently the framework treats Claude Code, Gemini CLI, and OpenAI Codex CLI as supported target tools. Adding a new target tool requires extending this lexicon with a per-tool section satisfying the same level of detail.

**Tool process.** A single running invocation of a target tool's command-line program. A tool process holds the live context state for an interactive session and terminates when the operator or framework exits the program.

**Tool process identifier.** Whatever the tool itself uses to refer to a particular conversation: a session ID, a session name, a save tag, or any combination thereof. This document maps the framework's checkpoint identifiers to the tool process identifiers each tool exposes.

**Context state.** The full body of information the underlying language model can reference at a given moment within a tool process. Includes loaded source files, prior conversation turns, system prompts, tool outputs not yet pruned by the tool's own context management, and any auto-loaded memory the tool injects.

**Context occupancy.** A vendor-reported numeric measurement of how much of the available context window is currently filled. The unit and granularity of this measurement vary across tools; the per-tool sections below specify each tool's reporting format.

**Probe session.** A single experimental unit containing one operator-defined sequence of tier loads, the checkpoints captured along that sequence, and the runs executed against those checkpoints. A probe session is owned by the framework, not by any particular tool process; a single probe session may correspond to many tool processes over its lifetime.

**Tier.** A named, ordered position in a progressive content-loading sequence. Tier N is the cumulative content of all tiers from 1 through N inclusive.

**Checkpoint.** A durable, addressable reference to the context state at the moment a specific tier finished loading. Checkpoints are created by the framework using whichever vendor primitive each tool exposes for capturing such state.

**Run.** A single execution of one question against one checkpoint, producing one captured response.

**Question.** A natural language instruction asking the target tool to recall information from context state without consulting any new source. Each question is identified within a corpus by a unique identifier.

**Captured response.** A file containing the model's complete answer to a single run, written by the model itself in response to a framework instruction that specified the file path. The framework detects completion by observing the file's appearance and stabilization. Captured responses are the framework's primary measurement artifact.

**Verification probe.** A short factual question whose answer can only come from the source material loaded at a specific tier, used by the framework to confirm that the loaded content is actually present in context state before any measurement-bearing question is asked.

**Corpus.** A self-contained, single-file specification of an experiment, including pinned source repository identity, tier definitions, questions with ground truth, verification probes, and evidence thresholds. A corpus file is publishable and shareable; running the same corpus on different machines must produce structurally comparable results.

**Corpus file.** The serialized form of a corpus, located under the framework's `configs/` directory or distributed by an operator. The format may be YAML, environment-style key-value, or any other human-editable, machine-parseable format the implementation supports.

**Corpus generator.** A tool-driven script that scans a target source repository and produces a draft corpus file. The generator may use any of the supported target tools to perform the analysis. Generation is not required to be reproducible across runs; the resulting corpus file is the artifact that must be reproducible.

**Root configuration.** Per-installation settings that apply across all corpora: authentication credentials, default tool, default model, runtime parameters. Lives at the framework root and never appears inside a corpus file.

**Corpus configuration.** Per-experiment settings that ship with a corpus file: questions, ground truth, tier definitions, source repository identity, model preference (optional override of the root default). Never contains secrets.

**Evidence threshold.** For each question, the lowest tier at which the source material containing the answer is loaded. A question asked below its evidence threshold is testing honesty; a question asked at or above is testing recall.

**Failure mode category.** One of the five question types defined in the framework's corpus specification: documentation–implementation agreement, documentation–implementation conflict, implementation-only knowledge, cross-source synthesis, exact recall. Each corpus must include at least one question per category, or explicitly report which categories the source repository did not support.

**Forking.** The general framework capability of returning to a previously captured context state, optionally to operate on it in parallel with the original loading sequence. Forking is satisfied by Claude Code's `--resume` flag combined with `--fork-session` (cross-process), by Gemini CLI's `/resume save` and `/resume resume` commands (in-process), and by OpenAI Codex CLI's `codex fork` and `codex resume` top-level subcommands (cross-process).

**Rewinding.** A distinct concept from forking. Rewinding is the in-place undoing of the most recent conversation turn within a live tool process, returning the same process to its state before the last turn. Rewinding is offered by Claude Code through a keyboard sequence and is not relied upon by the framework's checkpoint architecture, because checkpointing provides stronger isolation guarantees. Rewinding remains useful for ad-hoc operator interactions outside the framework.

**Pause.** A condition in which a probe session has stopped issuing operations to its target tool because the tool has reported a quota or rate limit. A paused session is recoverable: when the limit resets, the operator may resume the session and continue from the operation that triggered the pause.

**Compaction.** A target-tool-native operation that condenses the current context state into a smaller representation, intended to free room for further work. Each tool exposes its own compaction command. The framework treats compaction as a measurement event: it captures responses immediately after compaction and tags them as post-compaction so analysis can distinguish them from pre-compaction responses.

---

## 2. Per-Tool Lexicon — Claude Code

### 2.1 Tool Process Lifecycle

**Launch.** The command `claude` starts a new interactive tool process in the current working directory. With no flags, Claude Code begins a fresh conversation and assigns the new session a freshly generated UUID identifier internally.

**Launch with display name.** The flag `-n <name>` (long form `--name <name>`) sets a human-readable display name for the session at launch time. The display name is shown in the resume picker and the terminal title. It is not the session's authoritative identifier.

**Launch with explicit session ID.** The flag `--session-id <uuid>` instructs Claude Code to use a specific UUID as the session identifier. The UUID must be valid; arbitrary strings are not accepted.

**Launch with model selection.** The flag `--model <name>` sets the model for the session. Valid values are short aliases (for example, `opus`, `sonnet`, `haiku`) or a model's full name (for example, `claude-sonnet-4-6`, `claude-opus-4-6`, `claude-haiku-4-5`). The bracketed suffix `[1m]` selects the 1-million-token context variant of a model that has one (for example, `claude-opus-4-6[1m]`); without the suffix the model uses its standard context window (typically 200,000 tokens).

**Launch with elevated permissions.** The flag `--dangerously-skip-permissions` bypasses Claude Code's per-tool-call confirmation prompts. The flag is required for any non-interactive automation that issues file writes, shell commands, or other side-effect-producing operations. The flag `--allow-dangerously-skip-permissions` enables the *option* of bypassing permissions without enabling it by default.

**Launch with directory access.** The flag `--add-dir <path...>` grants the tool process access to additional directories outside the current working directory. The flag accepts multiple paths.

**Launch in non-interactive print mode.** The flag `-p` (long form `--print`) causes Claude Code to print one response and exit. The framework does not use this mode because it is incompatible with multi-turn interaction.

**Launch in worktree mode.** The flag `-w` (long form `--worktree [name]`) creates a fresh git worktree for the session. Optional name argument controls the worktree directory name.

**Launch in bare mode.** The flag `--bare` skips hooks, LSP, plugin sync, attribution, auto-memory, background prefetches, keychain reads, and CLAUDE.md auto-discovery. Useful for deterministic automation. Authentication in bare mode is restricted to `ANTHROPIC_API_KEY` or an `apiKeyHelper` declared in `--settings`.

### 2.2 Cross-Process State Restoration

**Resume most recent session in current directory.** The flag `-c` (long form `--continue`) launches a new tool process and restores the most recent session previously created in the current working directory. Session-scoped permissions from the prior session are not inherited; the operator must reapprove any permissions the resumed session needs.

**Resume specific session by identifier.** The flag `-r <value>` (long form `--resume <value>`) launches a new tool process and restores a specific session. The value may be a session UUID, a session display name (matched via the resume picker), or empty to launch an interactive picker. Multiple sessions sharing a display name will be disambiguated by the picker.

**Fork on resume.** The flag `--fork-session`, used together with either `--continue` or `--resume`, causes the resumed session to be branched into a new session with a freshly generated identifier. The original session remains unchanged on disk; the fork is a separate session that begins with a copy of the original's full conversation history. Forking is the mechanism the framework uses to derive new tier-checkpointed sessions from a parent loader session.

### 2.3 In-Session Slash Commands

These commands are issued from within a running Claude Code tool process by typing them into the prompt field.

**`/rename <name>`.** Renames the current session to the given name. The new name appears in the resume picker. The framework uses `/rename` immediately after creating a forked session so that the fork can be addressed by name later, replacing whatever auto-generated name the fork inherited from the launch.

**`/exit`.** Cleanly exits the tool process, persisting the session to disk. After `/exit`, the session can be resumed by name or UUID using `--resume`.

**`/resume`.** Opens an in-session resume picker, allowing the operator to switch to a different session without exiting. Less commonly used by automation than the `--resume` launch flag.

**`/context`.** Reports the current context window occupancy. Output is rendered in the status bar in the form `Used: <N>k/<M>k` where `N` is current usage in thousands of tokens and `M` is the model's context window size in thousands of tokens. The framework treats this as the authoritative context occupancy measurement for Claude Code.

**`/compact [focus]`.** Triggers Claude Code's native compaction operation. With no argument, the entire conversation is compacted using the default strategy. With a `focus` string, the compaction is biased to preserve content related to that focus. Compaction is asynchronous; the framework detects readiness via a verification probe issued after compaction.

**`/model <name>`.** Switches the model for the current session. Permitted names match the launch-time `--model` values.

**`/init`.** Walks the operator through creating a `CLAUDE.md` file for the current project. Not used by the framework.

**`/agents`.** Configures custom subagents. Not used by the framework's measurement loop, though the framework's load instructions explicitly tell the model not to use sub agents.

**`/doctor`.** Diagnoses common installation issues. The framework's reference implementation does not currently invoke `/doctor`; pre-flight validation uses `claude --version` instead. Implementers may choose to incorporate `/doctor` output into their pre-flight validation.

**`/help`.** Displays help.

### 2.4 Key Sequences

**`Esc` then `Esc`.** Opens the rewind picker, which allows the operator to roll the conversation back to a previous turn. After the picker opens, pressing `Enter` selects the highlighted entry, and pressing `Enter` again confirms the rewind. This is the in-place rewind operation; it is not used by the framework's checkpoint architecture.

**`Shift+Tab`.** Cycles between permission modes (default, auto-accept edits, plan mode, auto mode).

**`Ctrl+B d`** (when running inside a tmux session driving Claude Code). Detaches from the tmux session. This is a tmux key sequence, not a Claude Code key sequence; included here because operators frequently confuse the two.

### 2.5 Authentication

Claude Code authenticates against Anthropic's API using one of: an environment variable `ANTHROPIC_API_KEY`, an OAuth flow initiated on first launch, a credential helper declared via `--settings`, or third-party provider credentials (Bedrock, Vertex, Foundry) when the tool is configured to use them. The framework's root configuration may provide whichever of these the operator's environment requires; the corpus configuration may not contain authentication material.

### 2.6 File Writing Behavior

Claude Code uses a built-in `Write` tool to create files. The framework's instructions to write captured responses to specific file paths are reliably honored: Claude Code uses its native file writer rather than constructing shell commands. No special hint is required in the instruction text for Claude Code to write files reliably.

### 2.7 Status and Quota Reporting

The status bar at the bottom of the Claude Code interface shows the model name, the context window variant, working state (`HEAD` for the main branch), the `/context` reading, the percentage of context remaining until compaction, and a token-input rate indicator. Claude Code's display of rate-limit windows in its primary interface, and the existence of a dedicated status slash command in the pinned version, have not been independently verified for this lexicon. Operators commonly observe rate-limit conditions by detecting that Claude Code has stopped responding or by reading vendor messages that appear in the conversation stream when a limit is hit. Implementers should verify the existence and output format of any quota-reporting slash command against the pinned version before relying on it for the framework's pause-on-quota requirement.

### 2.8 Caching Behavior

The Anthropic API supports prompt caching at the API level (cache markers, reduced cache-read pricing, short default TTL with an optional extended TTL). The lexicon does not document the API mechanism in detail; it documents only what Claude Code, the CLI tool, exposes to the operator. The framework's reference implementation has not measured Claude Code's caching behavior — neither the cost it incurs nor the cache hit rates it achieves. Everything in this section is either documentation of operator-visible CLI surfaces or operator hearsay attributed to its source; nothing in this section has been measured by `probe.py` or by the framework's test scripts.

**Operator-visible signals.** Claude Code's `/context` slash command displays a single combined token usage figure in its status bar (for example, `Used: 91k/1000k`). The framework has not observed Claude Code distinguishing cached input tokens from uncached input tokens in any operator-facing surface. Whether `/context` includes cached tokens in the displayed total, excludes them, or weights them differently is unverified for the pinned version.

**Whether Claude Code applies caching automatically.** Whether the Claude Code CLI adds cache markers to its API requests on the operator's behalf is not documented in operator-facing material and has not been independently verified by the framework.

**Operator-reported behavior: forks may not inherit the parent's cache.** Operator experience reported during the framework's design discussions suggests that forked sessions created via `claude --resume <name> --fork-session` do not behave as cached continuations of their parent: the first request issued in a fork has been observed (by the operator, not by the framework's measurement code) to incur a cost more consistent with a fresh load than with a cache hit. This observation is not from a controlled measurement, and it has not been reproduced by the framework's reference implementation, which does not yet read any cached-token statistics from any source. The mechanism that would explain such a behavior — whether it is rooted in cache marker handling, in routing that does not preserve the parent's cache locality, or in something else entirely — is not documented and is left as speculation.

If the operator-reported behavior holds, it has a direct consequence for the framework's pre-run cost estimation when forks are used as checkpoints: each tier's checkpoint may carry the full cumulative token cost up to that tier rather than only the marginal cost of the new tier's content. An implementer doing cost estimation against Claude Code should treat fork-based checkpointing as cache-cold by default (the conservative assumption) until the cache behavior is measured directly.

**What an implementer should verify.** Whether Claude Code adds cache markers to its API requests automatically; whether `/context` distinguishes cached from uncached tokens; whether resuming a session via `--resume` (without `--fork-session`) within the cache TTL window benefits from cache hits; whether the operator-reported "fork is cache-cold" behavior reproduces under controlled measurement; whether any operator-facing surface exposes cached-token counts at all.

### 2.9 Subagent Behavior

By default, Claude Code may use the `Agent` tool to spawn subagents that handle parts of a task. The framework's load instructions explicitly include the directive "Do not use sub agents" because subagents do not contribute to the parent session's context occupancy; if loading were delegated to a subagent, the parent session's context would not actually contain the loaded files.

### 2.10 Capability Mapping

| Framework concept | Claude Code mechanism |
|---|---|
| Tool process | A `claude` invocation |
| Tool process identifier | Session UUID or display name |
| Send instruction | Type text into the prompt and submit |
| Captured response | A file the model writes via its `Write` tool, named by the framework |
| Checkpoint creation | `claude --resume <name> --fork-session`, then `/rename <new-name>`, then `/exit` |
| Checkpoint restoration | `claude --resume <checkpoint-name>` in a fresh tool process |
| Checkpoint addressability | The session display name set via `/rename` |
| Context occupancy report | `/context` |
| Compaction | `/compact` |
| In-place undo (not used by framework) | `Esc Esc Enter Enter` |
| Pause on quota | Detected by repeated unresponsiveness; no quota-reporting slash command verified for the pinned version |

### 2.11 Verification Status of Claude Code Items

The items in this section have the following verification statuses against Claude Code `2.1.92`:

**Verified via `claude --help`:** all launch flags listed in Section 2.1 (`-n`, `--name`, `--session-id`, `--model`, `--dangerously-skip-permissions`, `--allow-dangerously-skip-permissions`, `--add-dir`, `-p`, `--print`, `-w`, `--worktree`, `--bare`), and all cross-process restoration flags in Section 2.2 (`-c`, `--continue`, `-r`, `--resume`, `--fork-session`).

**Verified empirically by the framework's reference implementation:** the slash commands `/rename`, `/exit`, `/context`, `/compact`, the rewind key sequence `Esc Esc Enter Enter`, and the `Write`-tool-based file writing behavior. These are exercised by `probe.py` and `test-checkpoint.py` against the pinned version and observed to behave as documented.

**Documented but not exercised by the framework:** the slash commands `/resume` (in-session), `/model`, `/init`, `/agents`, `/doctor`, `/help`, and the `Shift+Tab` key sequence. These are included for completeness based on the tool's general user-facing documentation; an implementer relying on any of them should verify the behavior against the installed version.

**Not verified for the pinned version:** the existence of a quota-reporting slash command (such as `/status`), the format of any rate-limit display Claude Code may surface in its interface, and any in-session command to delete a stored session by name. Implementers requiring quota visibility should verify what the pinned version exposes before implementing pause-on-quota detection for Claude Code.

---

## 3. Per-Tool Lexicon — Gemini CLI

Gemini CLI defaults to interactive mode. It exposes a small set of named subcommands for managing MCP servers, extensions, skills, and hooks, alongside its main interactive launch mode.

### 3.1 Top-Level Subcommands

**`gemini`** (with no subcommand). Launches the interactive Gemini CLI in the current working directory. This is the default behavior.

**`gemini [query..]`** (positional argument). Launches the interactive Gemini CLI and submits the supplied query as the first user prompt. Equivalent to launching the tool and immediately typing the query.

**`gemini mcp`.** Manages MCP (Model Context Protocol) servers configured for Gemini CLI.

**`gemini extensions <command>`** (alias **`gemini extension <command>`**). Manages Gemini CLI extensions.

**`gemini skills <command>`** (alias **`gemini skill <command>`**). Manages agent skills.

**`gemini hooks <command>`** (alias **`gemini hook <command>`**). Manages Gemini CLI hooks.

### 3.2 Tool Process Lifecycle

**Launch with model selection.** The flag `-m <name>` (long form `--model <name>`) sets the model. The framework's default for Gemini is `gemini-3.1-pro-preview` (and other observed values include `gemini-3.1-pro`, `gemini-3-flash-preview`, `gemini-3-flash`, `gemini-2.5-pro`, `gemini-2.5-flash`); the set of valid model identifiers may evolve between Gemini CLI releases. The default model when no flag is provided varies with the installed version.

**Launch with non-interactive (headless) prompt.** The flag `-p <prompt>` (long form `--prompt <prompt>`) runs Gemini CLI in non-interactive mode with the supplied prompt. The prompt is appended to any input on stdin. The tool exits after producing its response. The framework does not use this mode because it is incompatible with multi-turn interaction.

**Launch with prompt then continue interactively.** The flag `-i <prompt>` (long form `--prompt-interactive <prompt>`) executes the supplied prompt and then continues in interactive mode. Distinct from `-p`, which exits after producing the response.

**Launch in debug mode.** The flag `-d` (long form `--debug`) runs Gemini CLI in debug mode, enabling a debug console accessible via the F12 key.

**Launch with elevated permissions, shorthand.** The flag `-y` (long form `--yolo`) is a boolean shortcut that automatically accepts all actions, equivalent to `--approval-mode yolo`.

**Launch with explicit approval mode.** The flag `--approval-mode <mode>` sets the approval mode for tool calls. Valid values are:
- `default`: prompt the operator for approval before each tool call
- `auto_edit`: auto-approve edit tools, prompt for others
- `yolo`: auto-approve all tools (equivalent to `-y`)
- `plan`: read-only mode

**Launch with sandbox mode.** The flag `-s` (long form `--sandbox`) runs the tool in a sandboxed environment.

**Launch with directory access.** The flag `--include-directories <paths>` grants access to additional directories. Accepts comma-separated paths or repeated flag instances.

**Launch in worktree mode.** The flag `-w [name]` (long form `--worktree [name]`) starts Gemini in a new git worktree. If no name is provided, one is generated automatically.

**Launch with policy files.** The flag `--policy <paths>` loads additional policy files or directories. Accepts comma-separated paths or repeated flag instances. The flag `--admin-policy <paths>` loads admin-specific policy files.

**Launch in ACP mode.** The flag `--acp` starts Gemini CLI in ACP (Agent Communication Protocol) mode. The flag `--experimental-acp` is a deprecated alias.

**Launch with allowed MCP servers.** The flag `--allowed-mcp-server-names <names>` restricts the set of MCP servers Gemini CLI may use during the session.

**Launch with allowed tools (deprecated).** The flag `--allowed-tools <tools>` lists tools allowed to run without confirmation. The vendor documentation marks this flag as deprecated in favor of the Policy Engine.

**Launch with specific extensions.** The flag `-e <extensions>` (long form `--extensions <extensions>`) selects which extensions to load. If not provided, all available extensions are used.

**Launch listing extensions.** The flag `-l` (long form `--list-extensions`) lists all available extensions and exits.

**Launch with output format.** The flag `-o <format>` (long form `--output-format <format>`) controls the format of CLI output. Valid values are `text`, `json`, and `stream-json`.

**Launch with raw output enabled.** The flag `--raw-output` disables sanitization of model output, allowing ANSI escape sequences and other raw content. Vendor documentation flags this as a security risk for untrusted model output. The flag `--accept-raw-output-risk` suppresses the security warning.

**Launch with screen reader support.** The flag `--screen-reader` enables accessibility mode.

### 3.3 Cross-Process State Restoration

**Resume by index.** The flag `-r <value>` (long form `--resume <value>`) restores a previously created session by index number. The special value `latest` selects the most recently created session in the current directory.

**List available sessions.** The flag `--list-sessions` prints the list of resumable sessions in the current project and exits.

**Delete a session.** The flag `--delete-session <index>` deletes a session by index number. Use `--list-sessions` to determine the index.

Cross-process persistence is supported by Gemini CLI as a first-class feature. The vendor session-management documentation at `geminicli.com/docs/cli/session-management/` states explicitly: "Sessions are stored in `~/.gemini/tmp/<project_hash>/chats/`, where `<project_hash>` is a unique identifier based on your project's root directory." It further states: "Your session history is recorded automatically as you interact with the model," ensuring "your work is preserved even if you interrupt a session," and that resuming a session restores "the conversation with all prior context restored." Save tags created via `/resume save` are part of this persisted session state and are therefore expected to survive a tool process restart along with the rest of the session.

The framework's reference implementation has not yet exercised the specific scenario of capturing a save tag in one Gemini tool process, terminating the process, launching a fresh `gemini` invocation in the same project directory, restoring the original session via `--resume`, and then restoring the previously saved tag via `/resume resume` to confirm that the in-process save tag survives the cross-process boundary intact. The vendor documentation makes this expected to work, but a single empirical test would close the verification gap. Implementers adding the test should document the result here.

The relationship between Gemini CLI's session index numbers (used by `--resume`) and the in-session save tags (used by `/resume save` / `/resume resume`, described in Section 3.4) is also worth verifying as part of the same test: specifically, whether resuming by index restores not only the conversation history but also the set of save tags that were defined within that session.

### 3.4 In-Session Slash Commands

These commands are issued from within a running Gemini CLI tool process. The framework's reference implementation has empirically verified the behavior of `/resume save`, `/resume resume`, `/resume delete`, and `/compress` against the pinned version of Gemini CLI. Other slash commands listed below are documented based on vendor reference material and have not been independently exercised by the framework.

**`/resume save <tag>`.** Captures the current conversation state as a tagged checkpoint. The tag is an arbitrary string chosen by the operator or framework. When the supplied tag already exists, the behavior depends on the Gemini CLI version:

- **In the pinned version (`0.36.0`)**, `/resume save <tag>` against an existing tag prompts the operator interactively to confirm the overwrite. The prompt blocks until the operator responds. No flag exists to suppress the prompt or to auto-accept. Because automation cannot reliably respond to an interactive blocking prompt, the framework's reference implementation deletes the existing tag with `/resume delete <tag>` before re-saving whenever an overwrite is required. This delete-first pattern is the correct automation approach against `0.36.0`.

- **In earlier versions of Gemini CLI** the behavior was different: `/resume save` (or its `/chat save` alias) silently overwrote an existing tag with no prompt. The Gemini CLI tips and tricks reference, written against an earlier release, states: "Save often if you want, it will overwrite the tag if it exists." Implementers working with an older Gemini CLI version may not need the delete-first pattern; implementers working with `0.36.0` or later (until and unless the vendor adds an `--overwrite` flag) do need it.

When the pinned version of this lexicon is advanced, the maintainer should re-verify whether the interactive overwrite prompt still blocks automation, and update this section if the vendor introduces a flag to suppress it.

**`/resume resume <tag>`** (alias **`/resume load <tag>`**). Restores a previously saved checkpoint, branching the live conversation back to the saved state. Subsequent interactions occur in a branch from the restored state; the original branch (the one that was active before the restore) is not affected and can itself be returned to via its own save tag if one was created.

**`/resume list`.** Lists all available save tags in the current session.

**`/resume delete <tag>`.** Deletes a save tag. The framework uses this command immediately before `/resume save <tag>` whenever it needs to overwrite an existing tag, because `/resume save` against an existing tag triggers an interactive overwrite prompt that automation cannot reliably answer. No `--overwrite` (or equivalent) flag exists in the pinned version; delete-first is the correct automation pattern.

**`/resume share [filename]`.** Exports the current conversation to a file in Markdown or JSON format.

**`/resume debug`.** Exports the most recent API request as JSON. Documented as available in nightly builds.

**`/chat`.** Compatibility alias for parts of `/resume`. Not used by the framework.

**`/compress`.** Triggers Gemini CLI's native compaction operation, equivalent to Claude Code's `/compact`.

**`/stats session`.** Reports session statistics including session ID, account identity, account tier, tool call counts and success rate, wall time, agent active time, API time, tool time, and per-model rate-limit usage with reset timers. The framework's reference implementation does not currently parse this output programmatically; the command is documented for operator use and as the most likely target for an implementer adding programmatic quota monitoring for Gemini CLI.

**`/exit`** or **`/quit`.** Exits the tool process.

**`/help`.** Displays help.

### 3.5 Key Sequences

**`Ctrl+Y`.** Toggles YOLO mode (equivalent of `--approval-mode yolo` or `-y` at launch) on or off mid-session. Documented based on vendor material; not exercised by the framework.

**`Esc` then `Esc`** (pressed twice in quick succession). Opens Gemini CLI's rewind picker, which allows the operator to roll back the conversation. The vendor reference describes options to rewind conversation history only, revert code changes only, or both simultaneously. This is the in-place per-turn (and multi-turn) undo primitive for Gemini CLI, equivalent in role to Claude Code's `Esc Esc Enter Enter` sequence and Codex CLI's per-turn undo (whichever the pinned version of Codex exposes). Documented based on the vendor reference at `geminicli.com/docs/reference/commands`; not exercised by the framework's reference implementation, because the framework's checkpoint architecture provides stronger isolation than rewind.

**`F12`** (when `--debug` was supplied at launch). Opens the debug console.

### 3.6 Authentication

Gemini CLI authenticates against Google's API using one of: an environment variable `GEMINI_API_KEY`, a Google Cloud project identifier passed via `GOOGLE_CLOUD_PROJECT` or `GOOGLE_CLOUD_PROJECT_ID`, or a Google account OAuth flow initiated on first launch. The framework's root configuration may provide any of these (the framework's reference implementation supports passing all three through the tmux environment); the corpus configuration may not contain them.

### 3.7 File Writing Behavior

Gemini CLI does not have a single uniform file-writing mechanism. The model may choose to write files using its built-in `WriteFile` tool, or by constructing a shell command (such as `cat <<EOF`, `echo > file`, or `python3 -c`). When the model selects shell-based heredoc syntax, the constructed command has been observed to fail in Gemini CLI's shell execution environment with an `ENAMETOOLONG` error or a malformed heredoc warning, because Gemini CLI's shell wrapper concatenates input in ways that interact poorly with heredoc delimiters.

The framework's reference implementation appends the directive "When writing files, use python3 -c with open/write, not shell heredocs." to its prompt suffix. Empirical testing against the pinned version has confirmed that this hint reliably biases Gemini CLI to use a `python3 -c` invocation on its first attempt rather than a heredoc, eliminating the failure mode.

### 3.8 Status and Quota Reporting

The `/stats session` slash command produces structured output including per-model rate-limit usage bars, percentage remaining, and reset timers for each model the operator's account is provisioned to use. Models that have hit their limit are marked `Limit`. Reset times are displayed as wall-clock times with countdown durations. The status bar at the bottom of the Gemini CLI interface displays the workspace, branch, sandbox state, and current model.

**Configurable footer (the framework's primary Gemini cache evidence source).** Gemini CLI exposes a configurable footer at the bottom of the TUI, distinct from the always-on status bar. The configuration lives in the operator's settings file at `~/.gemini/settings.json` (user-level) or `<cwd>/.gemini/settings.json` (project-level, takes precedence over user-level). The relevant key is `ui.footer.items`, an array of item ID strings. Each ID renders as a column in the footer with a header label and a value, in the order specified by the array. Operators may configure items via Gemini CLI's interactive footer-configuration menu or by editing the settings file directly.

The valid item IDs (verified against `0.36.0`):

| ID | Header label | Rendered value example | Notes |
|---|---|---|---|
| `workspace` | `workspace (/directory)` | `/opt/.../gastown` | Current working directory |
| `git-branch` | `branch` | `9f962c4a` | Current git branch name; not shown when unavailable |
| `sandbox` | `sandbox` | `no sandbox` | Sandbox type and trust indicator |
| `model-name` | `/model` | `gemini-3.1-pro-preview` | Current model identifier |
| `quota` | `quota` | `100%` | Remaining usage on daily limit; not shown when unavailable |
| `context-used` | `context` | `1% used` | Percentage of context window used |
| `memory-usage` | `memory` | `297.2 MB` | Memory used by the application |
| `session-id` | `session` | `f6988455` | Unique identifier for the current session (8-char) |
| `code-changes` | `changes` | `+12 -3` | Lines added/removed in the session; not shown when zero |
| `token-count` | `tokens` | `9k tokens` | Total tokens used in the session; **not shown when zero** |

The footer also has a `ui.footer.hideContextPercentage` boolean that toggles whether the `context-used` column shows `1% used` or just `1%`. The framework's parser handles both forms.

The framework's Gemini cache test script reads `ui.footer.items` at startup and refuses to run if the required items (`token-count`, `context-used`, `model-name`, `session-id`, `memory-usage`) are not present. The script does **not** modify the operator's settings file under any condition. See Section 8.6.2 for the integration details.

**Why the configurable footer matters for cache verification.** Google does not expose a programmatic admin or usage API for Gemini cache statistics (Section 8.2.6 capability gap). Without the configurable footer, the framework's strongest available cache evidence for Gemini would be wall-clock latency comparison — a weak signal subject to network jitter, model-side variability, and TUI warmup confounders. With `token-count` enabled in the footer, the framework can capture per-operation token deltas via `tmux capture-pane`, producing a measured input+output token consumption figure that is materially stronger than latency-only inference. The footer is therefore the primary cache evidence source for Gemini, despite being weaker than the admin API path that Claude and Codex have. Section 8.2.5 documents the evidence source priority order across all five tiers.

### 3.9 Caching Behavior

The Gemini API supports caching at the API level (implicit caching automatic on supported models with no cost-savings guarantee, plus explicit cached-content objects with developer-managed TTL and reduced cached pricing). The lexicon does not document the API mechanism in detail; it documents only what Gemini CLI, the CLI tool, exposes to the operator. The framework's reference implementation has not measured Gemini CLI's caching behavior — neither the cost it incurs nor the cache hit rates it achieves. Everything in this section is either documentation of operator-visible CLI surfaces or operator hearsay attributed to its source; nothing in this section has been measured by `probe.py` or by the framework's test scripts.

**Operator-visible signals.** Gemini CLI's `/stats session` slash command reports per-model rate-limit usage, tool call counts, success rate, and timing statistics. The framework has not verified whether `/stats session` distinguishes cached input tokens from uncached input tokens in its output. The status bar at the bottom of the Gemini CLI interface displays workspace and model state but does not surface caching information.

**Configurable footer (the framework's primary Gemini cache evidence source).** Beyond `/stats session`, Gemini CLI exposes a configurable footer (Section 3.8) that, when the operator enables the `token-count` item in `~/.gemini/settings.json`, renders a session-cumulative input+output token count at the bottom of the TUI as `<N>k tokens`. The framework's Gemini test script captures this footer via `tmux capture-pane` immediately before and after every measurement operation, parses out the `tokens` value, and computes a per-operation `tokens_delta = post − pre`. The aggregated per-scenario sum is the framework's measured token consumption for that scenario. This evidence path is **stronger than wall-clock latency comparison** because it directly measures token consumption rather than inferring it from request timing. It is **weaker than admin API polling** (the Claude/Codex path) because the footer's `token-count` is a single combined input+output total — it does not distinguish cached from uncached input tokens. For Gemini specifically, it is the strongest available evidence source given Google's admin API capability gap. The script reads `ui.footer.items` at startup and fails fast if the required items are missing; it never modifies the operator's settings file.

**Whether Gemini CLI uses caching automatically.** Implicit caching is described as on by default at the API level for supported models, so Gemini CLI sessions against those models are presumed to benefit from it without operator intervention. The vendor explicitly offers no cost-savings guarantee for implicit caching. Whether Gemini CLI ever creates explicit cached-content objects on the operator's behalf is not documented in operator-facing material and has not been independently verified by the framework.

**Operator-reported behavior: save points may be cache-friendly.** Operator experience reported during the framework's design discussions suggests that Gemini CLI's `/resume save` and `/resume resume` operations preserve the underlying session's eligibility for cache hits: restoring a save point and asking a question against the restored state has not been observed (by the operator) to incur the cost of a fresh load. This observation is not from a controlled measurement, and it has not been reproduced by the framework's reference implementation, which does not yet read any cached-token statistics from any source.

If the operator-reported behavior holds, it would mean Gemini CLI's checkpointing model is more cost-efficient than Claude Code's fork-based model for the framework's purposes — but this comparison rests on two operator observations, neither controlled, and the vendor's own documentation explicitly disclaims any cost-savings guarantee for implicit caching. An implementer doing cost estimation against Gemini CLI should treat save-point checkpointing as conservatively cache-cold (matching the explicit vendor disclaimer) until the cache behavior is measured directly, even though optimistic cost models may turn out to be correct in practice.

**What an implementer should verify.** Whether `/stats session` reports cache hit rates or cached-token counts; whether the implicit caching savings materialize at all for typical probe-session prompts; whether `/resume save` / `/resume resume` preserves cache eligibility across the branch operation; whether `gemini --resume <index>` across a process boundary preserves cache eligibility; whether explicit cached-content creation is exposed anywhere in the CLI surface; whether the operator-reported "save points are warm" behavior reproduces under controlled measurement.

### 3.10 Subagent Behavior

Gemini CLI may delegate parts of a task to its own internal subagent mechanisms. As with Claude Code, the framework's load instructions explicitly direct the model to "Do not use sub agents" so that the loaded files actually appear in the parent session's context and consume the parent session's tokens. Empirical testing against the pinned version has confirmed that Gemini CLI honors this directive.

### 3.11 Capability Mapping

| Framework concept | Gemini CLI mechanism |
|---|---|
| Tool process | A `gemini` invocation |
| Tool process identifier | Session index (cross-process) and save tag (in-process) |
| Send instruction | Type text into the prompt and submit |
| Captured response | A file the model writes via its `WriteFile` tool or via a `python3 -c` shell command directed by the framework's prompt suffix |
| Checkpoint creation | `/resume save <tag>` (in-process), with `/resume delete <tag>` first if overwriting |
| Checkpoint restoration | `/resume resume <tag>` (in-process) |
| Checkpoint addressability | The save tag chosen at save time |
| Cross-process restoration | `gemini --resume <index>`, where the relationship between the index and prior save tags is empirically unverified |
| Context occupancy report | `/stats session` (per-model rate limits) and the status bar (current model and workspace state) |
| Compaction | `/compress` |
| In-place undo | `Esc Esc` opens the rewind picker (rewind conversation, revert code, or both); not exercised by the framework because checkpointing provides stronger isolation |
| Pause on quota | Visible to the operator via `/stats session`; programmatic detection by the framework not yet implemented for Gemini CLI |

### 3.12 Verification Status of Gemini CLI Items

The items in this section have the following verification statuses against Gemini CLI `0.36.0`:

**Verified via `gemini --help`:** all top-level subcommands listed in Section 3.1 (`mcp`, `extensions`, `skills`, `hooks`, default interactive launch with positional `query`), and all launch flags listed in Section 3.2 (`-m`, `--model`, `-p`, `--prompt`, `-i`, `--prompt-interactive`, `-d`, `--debug`, `-y`, `--yolo`, `--approval-mode`, `-s`, `--sandbox`, `--include-directories`, `-w`, `--worktree`, `--policy`, `--admin-policy`, `--acp`, `--experimental-acp`, `--allowed-mcp-server-names`, `--allowed-tools`, `-e`, `--extensions`, `-l`, `--list-extensions`, `-o`, `--output-format`, `--raw-output`, `--accept-raw-output-risk`, `--screen-reader`), and all cross-process restoration flags in Section 3.3 (`-r`, `--resume`, `--list-sessions`, `--delete-session`).

**Verified empirically by the framework's reference implementation:** the slash commands `/resume save`, `/resume resume`, `/resume delete`, `/compress`; the heredoc-avoidance prompt suffix's effect on file writing behavior; honoring of the "do not use sub agents" directive. These are exercised by `probe.py` and `test-checkpoint.py` against the pinned version and observed to behave as documented.

**Documented but not exercised by the framework:** the slash commands `/resume list`, `/resume share`, `/resume debug`, `/chat`, `/stats session`, `/exit`, `/quit`, `/help`, and the `Ctrl+Y`, `Esc Esc` (rewind picker), and `F12` key sequences. These are included for completeness based on vendor reference material; an implementer relying on any of them should verify the behavior against the installed version.

**Vendor-documented but not yet empirically confirmed by the framework:** cross-process persistence of save tags. The Gemini CLI session-management documentation at `geminicli.com/docs/cli/session-management/` explicitly states that sessions are auto-saved to `~/.gemini/tmp/<project_hash>/chats/`, that session history is recorded automatically, that interrupting a session preserves the work, and that resuming via `--resume` or `/resume` restores "all prior context." Save tags created via `/resume save` are part of this persisted session state and are therefore expected to survive process restarts. The framework's reference implementation has not yet run the specific test that captures a tag in one process, terminates the process, and restores both the session and the tag in a fresh process. This is the open question recorded in `DESIGN.prd.md` Section 13 and in this lexicon's Section 6 capability gap summary; it can be closed by running a single empirical test.

---

## 4. Per-Tool Lexicon — OpenAI Codex CLI

OpenAI Codex CLI exposes a richer set of native subcommands than the other two target tools. Operations the framework treats as conceptually separate — launching, resuming, forking, executing non-interactively — are surfaced by Codex as distinct top-level commands rather than as flags on a single launch command. This section documents each subcommand and the in-session experience.

### 4.1 Tool Process Lifecycle

**Launch.** The command `codex` with no subcommand starts a new interactive tool process in the current working directory. Any additional arguments or flags following `codex` (without a recognized subcommand) are forwarded to the interactive CLI.

**Launch with an inline initial prompt.** The command `codex "<prompt text>"` starts a new interactive session and submits the supplied prompt as the first user instruction. The session remains interactive after the initial prompt is processed.

**Launch with model selection.** The flag `-m <model>` (long form `--model <model>`) sets the model the agent should use. Model identifiers observed in the pinned version include strings like `gpt-5.4`. Reasoning configuration (none, low, medium, high) and summary configuration (auto, on, off) are exposed through model-specific configuration rather than through a single flag.

**Note on context window sizes.** The full context window a model exposes through Codex CLI is not always equal to the model's maximum capability. As of the pinned Codex CLI version, GPT-5.4 reports a 258K-token context window in `/status` by default, even though the OpenAI API documentation states the model supports up to 1,050,000 tokens. The discrepancy is a Codex CLI client default rather than a hard model limit; operators who want the full window must override `model_context_window` in `~/.codex/config.toml` (and scale `model_auto_compact_token_limit` correspondingly). See Section 4.5 for the configuration mechanism. Whether the 258K default varies by account tier (Plus, Pro, API) has not been confirmed by the framework and is unclear from the available vendor documentation; an operator running on a non-Plus account should expect to verify the default against `/status` rather than assuming the documented model maximum is in effect.

**Note on extended-context pricing.** Per the OpenAI model documentation for GPT-5.4, prompts that exceed 272K input tokens are priced at 2× input and 1.5× output for the entire session, not just for the over-threshold portion. This is relevant to the framework's pre-run cost estimation: a probe session that would push GPT-5.4 above 272K input tokens carries a session-wide pricing multiplier, and any cost estimate the framework presents to the operator should account for it.

**Launch with sandbox mode.** The flag `-s <mode>` (long form `--sandbox <mode>`) selects the sandbox policy for model-generated shell commands. Valid modes are `read-only`, `workspace-write`, and `danger-full-access`. The sandbox policy is enforced by Codex CLI itself; commands that would violate the policy are intercepted before execution.

**Launch with approval policy.** The flag `-a <policy>` (long form `--ask-for-approval <policy>`) configures when the model must ask the operator for approval before executing a command. Valid policies are:
- `untrusted`: only run a curated set of "trusted" commands without approval; escalate anything else.
- `on-failure` (deprecated): run all commands without approval, only escalate on execution failure.
- `on-request`: the model decides when to ask the operator for approval.
- `never`: never ask for approval; execution failures are returned to the model directly.

**Launch in low-friction automation mode.** The flag `--full-auto` is a convenience alias equivalent to `-a on-request --sandbox workspace-write`. Suitable for non-interactive workflows where the operator wants the agent to make progress without per-command approval prompts.

**Launch with elevated permissions.** The flag `--dangerously-bypass-approvals-and-sandbox` skips all confirmation prompts and executes commands without sandboxing. The flag is the operational equivalent of Claude Code's `--dangerously-skip-permissions` and Gemini CLI's `--approval-mode yolo`. The vendor documentation explicitly marks this flag as intended only for environments that are externally sandboxed.

**Launch with working directory override.** The flag `-C <dir>` (long form `--cd <dir>`) tells the agent to use a specific directory as its working root, instead of the directory from which `codex` was invoked.

**Launch with additional writable directories.** The flag `--add-dir <dir>` grants write access to additional directories alongside the primary workspace.

**Launch with web search enabled.** The flag `--search` enables the native Responses `web_search` tool. When enabled, the model can perform web searches without per-call approval.

**Launch with image attachments.** The flag `-i <file>` (long form `--image <file>`, repeatable) attaches one or more images to the initial prompt.

**Launch with a configuration profile.** The flag `-p <profile>` (long form `--profile <profile>`) selects a named configuration profile from `~/.codex/config.toml`. Profiles allow operators to define groups of default options that can be selected at launch.

**Launch with TOML configuration overrides.** The flag `-c <key=value>` (long form `--config <key=value>`, repeatable) overrides any configuration value loaded from `~/.codex/config.toml`. Dotted paths address nested values (`-c shell_environment_policy.inherit=all`). The value is parsed as TOML; if parsing fails, the raw string is used as a literal. This is the most general configuration override mechanism Codex CLI exposes.

**Launch with feature flag overrides.** The flag `--enable <feature>` (repeatable) is shorthand for `-c features.<name>=true`. The flag `--disable <feature>` is the inverse.

**Launch with inline (no alternate-screen) TUI.** The flag `--no-alt-screen` disables alternate screen mode. The TUI runs in inline mode, preserving terminal scrollback history. Useful in terminal multiplexers like Zellij that follow the xterm spec strictly.

**Launch against a remote app server.** The flag `--remote <ws-or-wss-addr>` connects the TUI to a remote app server websocket endpoint. The flag `--remote-auth-token-env <env-var>` names an environment variable containing the bearer token for authenticating against the remote endpoint. This is the native mechanism for driving Codex from a control plane that does not share a terminal with the operator.

**Launch with an open-source local model.** The flag `--oss` is a convenience for `-c model_provider=oss`. Codex verifies that a local LM Studio or Ollama server is running. The flag `--local-provider <provider>` (with values `lmstudio` or `ollama`) selects which local provider to use.

### 4.2 Top-Level Subcommands

In addition to the bare `codex` launch, Codex CLI exposes a number of named subcommands. Each subcommand has its own flags, most of which mirror the bare-launch flags described above.

**`codex exec [PROMPT]`** (alias **`codex e`**). Runs Codex non-interactively. The supplied prompt is processed and the agent runs to completion without an interactive TUI. If no prompt is provided as an argument and stdin is piped, instructions are read from stdin. If both a prompt argument and piped stdin are present, the stdin content is appended as a `<stdin>` block. `exec` has its own `resume` and `review` sub-subcommands for non-interactive resume/review workflows. This is the native mechanism for batch operation; it is not used by the framework's interactive driver but may be relevant for analysis-side workflows that want a single-shot Codex invocation.

**`codex review`.** Runs a code review against the current repository non-interactively. Equivalent to a specialized `exec` mode focused on review output.

**`codex resume [SESSION_ID] [PROMPT]`.** Resumes a previous interactive session. The session may be addressed by UUID (which takes precedence if the supplied value parses as a UUID) or by thread name. Without a session argument, Codex shows an interactive picker; with the `--last` flag, Codex resumes the most recent recorded session without showing the picker. The `--all` flag disables current-working-directory filtering and shows sessions from any directory, with a CWD column added to the picker. The `--include-non-interactive` flag adds non-interactive sessions (created by `codex exec`) to the picker and `--last` selection. An optional prompt can be supplied to be processed immediately after resumption. **This subcommand is the foundation of Codex's checkpoint restoration capability.**

**`codex fork [SESSION_ID] [PROMPT]`.** Forks a previous interactive session. The original session remains unchanged on disk; the fork is a new session that begins with a copy of the original's full conversation history and is assigned its own session identifier. As with `codex resume`, the session is addressed by UUID, and `--last` forks the most recent session, and `--all` disables cwd filtering. **This subcommand is Codex's native equivalent of Claude Code's `--fork-session` flag.**

**`codex login`.** Manages credential storage. The subcommand `codex login status` shows the current login state. The flag `--with-api-key` reads an API key from stdin (typically piped from `printenv OPENAI_API_KEY`). The flag `--device-auth` initiates device authentication.

**`codex logout`.** Removes stored authentication credentials.

**`codex mcp`.** Manages external MCP (Model Context Protocol) servers configured for Codex.

**`codex mcp-server`.** Starts Codex itself as an MCP server speaking over stdio. This makes Codex addressable from other tools that speak MCP.

**`codex app-server`** (experimental). Runs the Codex app server or related tooling. The experimental marker indicates this surface may change.

**`codex completion`.** Generates shell completion scripts for the operator's shell.

**`codex sandbox`.** Runs an arbitrary command within a Codex-provided sandbox, independent of any model interaction. This is a standalone sandboxing facility and is not used by the framework's measurement loop.

**`codex debug`.** Debugging tools whose specific contents depend on the installed version.

**`codex apply`** (alias **`codex a`**). Applies the latest diff produced by the Codex agent as a `git apply` to the local working tree.

**`codex cloud`** (experimental). Browses tasks from Codex Cloud and applies changes locally.

**`codex features`.** Inspects feature flags currently in effect.

**`codex help [SUBCOMMAND]`.** Prints help for the top-level command or for a specified subcommand.

### 4.3 In-Session Slash Commands

Slash commands are issued from within a running Codex CLI tool process by typing them into the prompt field.

**`/status`.** Reports the OpenAI Codex version, a vendor URL for current rate-limit and credit information, the model name and reasoning/summary configuration, the working directory, the permissions mode (which may be a named mode like `workspace-write` or a custom configuration), the `AGENTS.md` discovery state, the account identity (email and account tier such as `Plus`), the collaboration mode, the session UUID, the context window occupancy as both a percentage remaining and an absolute used/total ratio, the 5-hour rate limit window with a percentage remaining bar and a wall-clock reset time, and the weekly rate limit window with a percentage remaining bar and a wall-clock reset time and date. The framework's reference implementation does not yet drive Codex CLI; an implementer adding Codex support should treat `/status` as the most likely authoritative source for context occupancy and rate-limit data, and verify the precise output format against the pinned version before parsing it programmatically.

**`/compact`.** Triggers Codex CLI's native compaction operation, equivalent in role to Claude Code's `/compact` and Gemini CLI's `/compress`. Codex CLI's vendor documentation describes context compaction as a feature that "automatically summarizes the session" at context-limit thresholds; the same primitive is available on demand via the `/compact` slash command. The exact prompt-side behavior, summarization granularity, and post-compaction context occupancy reading have not been empirically verified by the framework's reference implementation against the pinned Codex version, because the framework does not yet drive Codex CLI; an implementer should validate the operation end-to-end before relying on it for the framework's compaction-measurement requirement.

Other in-session slash commands supported by the pinned version of Codex CLI must be discovered empirically by the implementer or by consulting the operator-facing help inside a running Codex session. Notably, Codex CLI does not expose a `/rewind` slash command; per-turn undo is provided through a key sequence rather than a slash command, as documented in Section 4.4.

The vendor documentation also describes a `/fork` slash command which, combined with the Esc-based rewind walk described in Section 4.4, provides interactive forking from a chosen point in the conversation transcript. This in-session `/fork` is conceptually distinct from the top-level `codex fork <session-id>` subcommand documented in Section 4.2: the subcommand operates on a stored session by identifier from outside any tool process, while the in-session `/fork` operates on the live transcript at the operator's current rewind position. The framework's reference implementation does not yet exercise either form of fork against Codex.

### 4.4 Key Sequences

**`Esc` then `Esc`** (pressed twice while the composer is empty). Edits the previous user message in place. Continuing to press `Esc` after the first two presses walks further back through the transcript, one user message at a time. Pressing `Enter` while positioned at a previous message forks the conversation from that point, creating a new branch that begins with the selected message and discards everything after it. The vendor documentation at `developers.openai.com/codex/cli/features` describes this verbatim: "Tap Esc twice while the composer is empty to edit your previous user message. Continue pressing Esc to walk further back in the transcript, then hit Enter to fork from that point."

This is Codex CLI's in-place undo and per-turn fork primitive. It is operationally distinct from the top-level `codex fork <session-id>` subcommand (Section 4.2) in two important ways: it operates on the live transcript inside a running tool process rather than on a stored session, and it allows the operator to walk to an arbitrary prior turn before forking, whereas the top-level subcommand always forks from the entirety of the stored session's history. Both are valid forking primitives for different purposes.

The Esc-based rewind walk is documented based on the vendor reference; the framework's reference implementation has not exercised it because the framework does not yet drive Codex CLI.

### 4.5 Configuration File

Codex CLI reads `~/.codex/config.toml` at launch. The file contains per-project trust levels (each project directory may be marked as `trusted` or otherwise), plugin configuration, and any persistent overrides the operator has set. The framework's root configuration may direct Codex CLI to a specific config file via the `-c` override mechanism, but the framework does not require modification of the operator's own `config.toml`.

**Context window override.** Codex CLI displays a per-model context window in `/status` that may be smaller than the model's maximum supported window. For GPT-5.4 in particular, the default display is 258K tokens, but the model itself supports approximately 1,050,000 tokens per the OpenAI API documentation. Operators who want to use the full window must set `model_context_window=1000000` (or whatever value they intend to use, up to the model's documented maximum) in `~/.codex/config.toml`, and should also scale `model_auto_compact_token_limit` accordingly so that automatic compaction does not fire prematurely against the new window size. The mechanism is documented in Codex GitHub issue #13738. The framework's pre-run cost estimation should treat any session that overrides `model_context_window` as a candidate for the extended-context pricing surcharge described in Section 4.1.

The directory `~/.codex/` also contains:
- `auth.json`: stored authentication credentials.
- `sessions/`: persisted session state used by `codex resume` and `codex fork`.
- `history.jsonl`: command history.
- `memories/`: persistent operator memory loaded into context at session start.
- `cache/`, `plugins/`, `shell_snapshots/`, `skills/`, `tmp/`, `log/`: various supporting state.
- `state_*.sqlite` and `logs_*.sqlite`: structured state and log databases whose schemas may evolve across versions.

The framework treats `~/.codex/sessions/` as the durable storage backing Codex's checkpointing mechanism — the persistence required by `DESIGN.prd.md` Section 4.3 is satisfied by the existence of this directory and the operability of `codex resume` and `codex fork` against the sessions stored there.

### 4.6 Authentication

Codex CLI authenticates against OpenAI's API using one of three mechanisms:
- A stored OAuth login obtained through `codex login` (with optional `--device-auth` for environments without a browser). The login state is persisted in `~/.codex/auth.json` and surfaced via `codex login status`.
- An API key supplied at login time via `codex login --with-api-key`, which reads the key from stdin. This is the mechanism the framework's root configuration uses when an `OPENAI_API_KEY` is provided.
- A configuration profile in `~/.codex/config.toml` that selects a named credential set.

The framework's root configuration may carry the API key as `OPENAI_API_KEY` (or whatever name the operator chooses) and pipe it through `codex login --with-api-key` during pre-flight validation. The corpus configuration may not contain credentials.

### 4.7 File Writing Behavior

Codex CLI's interactive agent writes files through its sandboxed shell execution and through native tool calls. Whether the framework's "write your answer to this file" instruction is honored under each sandbox mode has not been empirically verified, because the framework's reference implementation does not yet drive Codex CLI. An implementer adding Codex support must determine the following before claiming reliable file-writing behavior: which sandbox modes permit writes to a framework-controlled file path, whether the agent's choice of writing mechanism (native tool versus shell command) varies with sandbox mode, whether any version-specific quirks (such as the heredoc concatenation issue documented for Gemini CLI in Section 3.7) affect Codex CLI's shell-mediated file writes, and whether a prompt-suffix hint similar to Gemini CLI's `python3 -c` directive is required.

The most permissive sandbox modes for file writing are `workspace-write` (writes confined to the workspace directory) and `danger-full-access` (no sandbox restrictions). The `--dangerously-bypass-approvals-and-sandbox` launch flag applies the most permissive mode together with skipping all approval prompts.

### 4.8 Status and Quota Reporting

The `/status` slash command produces structured output suitable for cost and quota tracking. The framework's reference implementation does not currently parse this output programmatically, because it does not yet drive Codex CLI; the format documented here was observed by an operator running `/status` interactively against the pinned version, and is recorded for an implementer adding Codex support. The output includes:
- **Context window**: a percentage of remaining context, alongside the absolute used and total token counts (for example, `81% left (59.8K used / 258K)`).
- **5-hour rate limit**: a textual progress bar, a percentage remaining, and a wall-clock reset time (for example, `[████████████████████] 100% left (resets 21:38)`).
- **Weekly rate limit**: a textual progress bar, a percentage remaining, and a wall-clock reset time with date (for example, `[████████████████████] 99% left (resets 09:56 on 11 Apr)`).

These three readings together would give an implementation a complete view of Codex CLI's quota state, suitable for the pre-run cost estimation and pause-on-quota requirements from `DESIGN.prd.md`. The exact parsing rules (whitespace handling, bar character counts, date formatting locale) must be verified against the pinned version before being relied upon.

### 4.9 Caching Behavior

The OpenAI API supports automatic prompt caching at the API level (no developer opt-in, reduced cached-token billing, model-dependent minimum cacheable prefix size, model-dependent TTL with newer models offering extended TTL windows). The lexicon does not document the API mechanism in detail; it documents only what Codex CLI, the CLI tool, exposes to the operator. The framework's reference implementation has not measured Codex CLI's caching behavior at all — `probe.py` does not yet drive Codex CLI in any capacity. Everything in this section is either documentation of operator-visible CLI surfaces (observed by reading `--help` and an operator's interactive `/status` capture) or extrapolation from API-level documentation; nothing in this section has been measured against a running Codex session by the framework.

**Operator-visible signals.** Codex CLI's `/status` slash command displays context window occupancy, account information, model configuration, and rate-limit windows. The framework has not verified whether `/status` distinguishes cached input tokens from uncached input tokens in its output. The format documented in Section 4.8 was observed by an operator running `/status` interactively against the pinned version and does not include any explicit cache statistics.

**Whether Codex CLI benefits from caching automatically.** OpenAI's prompt caching is described as automatic at the API level, so any Codex CLI session against a supported model is presumed to benefit from cache hits when prompt prefixes match recent prior requests. Codex CLI does not need to opt in. Whether the operator can observe the resulting cost savings through any CLI surface is unverified for the pinned version.

**Checkpoint and fork cache effects are unverified.** When an operator runs `codex resume <session-id>` or `codex fork <session-id>`, the resumed or forked tool process re-sends the conversation history to the API. Whether the resumed prompt benefits from a cache hit on the previously-processed prefix is uncertain: it depends on the cache TTL for the model in use, on whether the resumed prompt is byte-identical to the cached prefix, and on whatever routing logic OpenAI uses to associate requests with cached prefixes. None of these factors are documented from an operator-facing surface, and none have been measured by the framework against the pinned Codex version. An implementer doing cost estimation against Codex CLI should treat `codex resume` and `codex fork` cache behavior as unknown and use the conservative assumption (cache miss) until measurement is done.

**What an implementer should verify.** Whether `/status` reports cached-token counts or cache hit rates; whether `codex resume` against a recently-active session noticeably reduces wall-clock time on the first turn (an indirect cache-hit signal); whether `codex fork` produces a session whose first turn is faster than a fresh `codex` session loaded with equivalent content; whether the `model_context_window` override (Section 4.5) interacts with caching in any observable way; whether the extended-TTL cache option for newer models survives `codex resume` across the full TTL window or is invalidated earlier by Codex CLI's request shape.

### 4.10 Subagent and Memory Behavior

Codex CLI may load operator memories from `~/.codex/memories/` at session start, which contributes to the parent session's context occupancy. Codex CLI's behavior around delegating work to internal subagents has not been verified against the pinned version; implementers should determine whether the framework's "do not use sub agents" directive (used for the other two target tools) is necessary or sufficient for Codex.

### 4.11 Capability Mapping

| Framework concept | OpenAI Codex CLI mechanism |
|---|---|
| Tool process | A `codex` invocation (or `codex resume <id>` / `codex fork <id>`) |
| Tool process identifier | Session UUID, persisted in `~/.codex/sessions/`, surfaced via `/status` |
| Send instruction | Type text into the prompt and submit (interactive); `codex exec [PROMPT]` (non-interactive) |
| Captured response | A file the model writes via its sandboxed shell or native tools, named by the framework |
| Checkpoint creation | `codex fork <session-id>` (creates a new branched session with the parent's full history) |
| Checkpoint restoration | `codex resume <session-id>` (resumes the named session in a fresh tool process) |
| Checkpoint addressability | Session UUID assigned by Codex; thread-name addressing also accepted by `codex resume` |
| Cross-process persistence | Satisfied by `~/.codex/sessions/` storage |
| Resume most recent session | `codex resume --last` |
| List sessions | `codex resume` with no argument (interactive picker); `--all` shows sessions from any directory |
| Resume specific session | `codex resume <uuid>` or `codex resume <thread-name>` |
| Fork specific session | `codex fork <uuid>` |
| Context occupancy report | `/status` (the displayed window size may be smaller than the model's maximum capability; see Sections 4.1 and 4.5 for the `model_context_window` override) |
| Compaction | `/compact` (vendor-documented; auto-triggered at context limits, also available on demand); end-to-end behavior not yet exercised by the framework |
| In-place per-turn undo | `Esc Esc` (composer-empty) edits the previous user message; continued `Esc` walks further back through the transcript; `Enter` at any prior position forks from that point. Vendor-documented; not exercised by the framework |
| In-session fork from prior turn | `Esc`-walk + `Enter` (Section 4.4); also a `/fork` slash command exists and is conceptually distinct from the top-level `codex fork <session-id>` subcommand |
| Pause on quota | Detected via `/status` rate limit windows (5-hour and weekly) |
| Elevated permissions | `--dangerously-bypass-approvals-and-sandbox` (or `--full-auto` for sandboxed automation) |
| Auth via API key | `codex login --with-api-key` reading from stdin |
| Auth via OAuth | `codex login` (interactive) or `codex login --device-auth` (headless) |
| Working directory override | `-C <dir>` or `--cd <dir>` |
| Configuration overrides | `-c key=value` (TOML-parsed) or named `--profile <name>` from `~/.codex/config.toml` |
| Remote control | `--remote <ws-addr>` plus `--remote-auth-token-env <env-var>` |
| Non-interactive single-shot | `codex exec [PROMPT]` |
| Native MCP server mode | `codex mcp-server` (Codex itself becomes an MCP server) |

### 4.12 Verification Status of OpenAI Codex CLI Items

The items in this section have the following verification statuses against `codex-cli 0.118.0`:

**Verified via `codex --help`, `codex resume --help`, and `codex fork --help`:** the existence and flag set of all top-level subcommands listed in Section 4.2 (`exec`, `review`, `resume`, `fork`, `login`, `logout`, `mcp`, `mcp-server`, `app-server`, `completion`, `sandbox`, `debug`, `apply`, `cloud`, `features`, `help`), all bare-launch flags listed in Section 4.1 (`-c`/`--config`, `--enable`, `--disable`, `--remote`, `--remote-auth-token-env`, `-i`/`--image`, `-m`/`--model`, `--oss`, `--local-provider`, `-p`/`--profile`, `-s`/`--sandbox`, `-a`/`--ask-for-approval`, `--full-auto`, `--dangerously-bypass-approvals-and-sandbox`, `-C`/`--cd`, `--search`, `--add-dir`, `--no-alt-screen`), and the `codex resume` and `codex fork` flags (`--last`, `--all`, `--include-non-interactive`).

**Verified via filesystem inspection:** the contents and structure of `~/.codex/` (`auth.json`, `sessions/`, `history.jsonl`, `memories/`, `cache/`, `plugins/`, `shell_snapshots/`, `skills/`, `tmp/`, `log/`, `state_*.sqlite`, `logs_*.sqlite`, `config.toml`).

**Documented based on operator observation against the pinned version:** the format of `/status` slash command output in Section 4.7 (context window percentage, used/total ratios, 5-hour and weekly rate limit windows with reset times). The documented format is taken from a single operator capture and should be re-verified before being parsed programmatically.

**Documented based on the vendor reference at `developers.openai.com/codex/cli/features` and `developers.openai.com/codex/cli/slash-commands`:** the `/compact` slash command and its automatic-trigger behavior at context-limit thresholds; the `/fork` slash command for in-session forking from a chosen rewind position; the `Esc Esc` composer-empty key sequence for editing the previous user message; the continued-`Esc` walk further back through the transcript; the `Enter`-from-prior-position fork-from-point operation. These items are not exercised by the framework's reference implementation but are documented in vendor sources.

**Documented based on the OpenAI API documentation and Codex GitHub issue #13738:** the GPT-5.4 1,050,000-token context window capability; the `model_context_window` and `model_auto_compact_token_limit` settings in `~/.codex/config.toml` for overriding Codex CLI's default 258K display; the 272K input-token threshold above which session pricing shifts to 2× input and 1.5× output for the entire session. The framework's reference implementation does not yet drive Codex CLI and has not validated these claims against the pinned version. An operator running on a non-Plus account should re-verify the default `/status` context window display and the effect of any `model_context_window` override against their specific account configuration before relying on these values for the framework's pre-run cost estimation.

**Not yet exercised by the framework's reference implementation:** all interactive driving of Codex CLI. The framework's `probe.py` currently supports only Claude Code and Gemini CLI. Adding Codex support requires empirical verification of every behavioral claim in this section against a real Codex session, including: file writing under each sandbox mode, the model's response to the "do not use sub agents" directive, the precise on-demand and automatic-trigger behavior of `/compact`, the precise output format of `/status`, the empirical lossless-restoration property of `codex resume <id>` and `codex fork <id>` against checkpoints created in earlier processes, and the timing characteristics of the `Esc`-walk rewind sequence (how long the operator must wait between presses, whether the walk skips over agent turns, whether forking from a deep prior turn triggers any confirmation).

**Empirically unverified for the pinned version:** the existence of in-session slash commands beyond `/status`, `/compact`, and `/fork`. Implementers should enumerate the available slash commands by typing `/help` or equivalent inside a running Codex session and update this lexicon with their findings.

---

## 5. Cross-Tool Capability Map

This table provides the canonical mapping from each framework concept to its per-tool implementation. It is the document `DESIGN.prd.md` and other framework documentation should reference when describing tool-specific behavior.

| Framework concept | Claude Code | Gemini CLI | OpenAI Codex CLI |
|---|---|---|---|
| Launch tool process | `claude` | `gemini` | `codex` |
| Select model | `--model <name>` | `--model <name>` | `-m <model>` / `--model <model>` |
| Elevated permissions | `--dangerously-skip-permissions` | `--approval-mode yolo` | `--dangerously-bypass-approvals-and-sandbox` |
| Sandboxed automation alias | (no equivalent) | (no equivalent) | `--full-auto` (= `-a on-request --sandbox workspace-write`) |
| Working directory override | Current directory by default | Current directory by default | `-C <dir>` / `--cd <dir>` |
| Additional writable directories | `--add-dir <path>` | `--include-directories <paths>` | `--add-dir <dir>` |
| Auth via API key | `ANTHROPIC_API_KEY` env var | `GEMINI_API_KEY` env var | `codex login --with-api-key` reading from stdin |
| Auth via cloud project | Bedrock/Vertex configuration | `GOOGLE_CLOUD_PROJECT` or `GOOGLE_CLOUD_PROJECT_ID` | Not applicable |
| Auth via OAuth | Initiated on first launch | Initiated on first launch | `codex login` (or `--device-auth` for headless) |
| Auth status check | (no equivalent) | (no equivalent) | `codex login status` |
| Auth removal | (no equivalent) | `--delete-session` clears local session | `codex logout` |
| Resume most recent session | `--continue` | `--resume latest` | `codex resume --last` |
| Resume specific session | `--resume <id-or-name>` | `--resume <index>` | `codex resume <uuid-or-thread-name>` |
| List sessions | Resume picker via `--resume` with no value | `--list-sessions` | `codex resume` with no argument (interactive picker) |
| Show sessions from any directory | (no equivalent) | (no equivalent) | `codex resume --all` |
| Delete session | No flag; manual cleanup | `--delete-session <index>` | Manual cleanup of `~/.codex/sessions/` |
| Create checkpoint | `claude --resume <name> --fork-session`, then `/rename`, then `/exit` | `/resume save <tag>` (in-process) | `codex fork <session-id>` (creates new branched session with parent's history) |
| Restore checkpoint | `claude --resume <name>` in fresh process | `/resume resume <tag>` in same process | `codex resume <session-id>` in fresh process |
| Delete checkpoint | Manual cleanup of session storage | `/resume delete <tag>` | Manual cleanup of `~/.codex/sessions/` |
| Rename session in-place | `/rename <name>` | Not documented | Thread-name addressing accepted by `codex resume`, but in-session rename not yet verified |
| Context occupancy report | `/context` | `/stats session` | `/status` |
| Compaction | `/compact [focus]` | `/compress` | `/compact` (vendor-documented; auto-triggered at context limits, also on demand) |
| In-place per-turn undo | `Esc Esc Enter Enter` | `Esc Esc` (rewind picker: history, code, or both) | `Esc Esc` (composer-empty) edits previous user message; continued `Esc` walks further back; `Enter` forks from selected point |
| Quit cleanly, persist session | `/exit` | `/exit` or `/quit` | Standard interrupt or close (TUI-specific; persistence is automatic via `~/.codex/sessions/`) |
| Status with rate limits | Not in main interface (varies by version) | `/stats session` | `/status` (5-hour and weekly windows with reset times) |
| File writing primitive | Native `Write` tool | `WriteFile` tool or shell, requires hint | Sandboxed shell + native tool calls (sandbox mode dependent) |
| "Do not use sub agents" instruction | Honored | Honored | Not yet verified for the pinned version |
| Non-interactive single-shot | `--print` / `-p` | `-p <prompt>` / `--prompt <prompt>` | `codex exec [PROMPT]` (alias `codex e`) |
| Prompt then continue interactively | (no equivalent) | `-i <prompt>` / `--prompt-interactive <prompt>` | (no equivalent: bare `codex "<prompt>"` always continues) |
| Inline initial prompt at launch | (no equivalent) | `gemini [query..]` (positional argument) | `codex "<prompt>"` (positional argument) |
| Code review subcommand | (no equivalent) | (no equivalent) | `codex review` |
| MCP server mode | (no equivalent) | (no equivalent) | `codex mcp-server` (Codex itself becomes an MCP server) |
| Apply latest agent diff | (no equivalent) | (no equivalent) | `codex apply` (alias `codex a`) |
| Configuration overrides at launch | `--settings` | (no equivalent) | `-c key=value` (TOML-parsed, dotted paths for nested values) |
| Configuration profiles | (no equivalent) | (no equivalent) | `-p <profile>` from `~/.codex/config.toml` |
| Feature flag overrides | (no equivalent) | (no equivalent) | `--enable <feature>` / `--disable <feature>` |
| Remote app server connection | (no equivalent) | (no equivalent) | `--remote <ws-addr>` + `--remote-auth-token-env <env-var>` |
| Inline (non-altscreen) TUI | (no equivalent) | (no equivalent) | `--no-alt-screen` |
| Local OSS model provider | (no equivalent) | (no equivalent) | `--oss` (LM Studio or Ollama) |
| Image attachments | (no equivalent) | (no equivalent) | `-i <file>` / `--image <file>` (repeatable) |
| Web search tool enable | (Anthropic-managed) | (Google-managed) | `--search` (enables native `web_search` tool) |
| Debug mode | (no flag; use `--debug` settings) | `-d` / `--debug` (F12 console) | `codex debug` subcommand |
| Output format selection | (no equivalent) | `-o <format>` / `--output-format <format>` (text, json, stream-json) | (no equivalent) |
| List extensions / plugins | (no equivalent) | `-l` / `--list-extensions` | `codex features` |
| MCP server management | `--mcp-config <files>`, `--strict-mcp-config` | `gemini mcp` subcommand | `codex mcp` subcommand |
| Sandbox mode | (no equivalent at launch) | `-s` / `--sandbox` | `-s <mode>` / `--sandbox <mode>` (read-only, workspace-write, danger-full-access) |
| Approval policy granularity | Permission modes via `Shift+Tab` (in-session) | `--approval-mode` (default, auto_edit, yolo, plan) | `-a` / `--ask-for-approval` (untrusted, on-request, never) |
| Underlying API caching mechanism | Explicit cache markers (`cache_control`); reduced cache-read pricing; short default TTL with optional extended TTL | Implicit caching (automatic on Gemini 2.5+, no cost guarantee) plus explicit cached-content objects | Automatic prefix caching for sufficiently long shared prefixes; extended TTL on newer models |
| Operator-visible cache statistics in CLI | None observed (`/context` shows total occupancy only) | None verified (`/stats session` does not document cache statistics) | None observed (`/status` does not document cache statistics) |
| Vendor admin API for cached-token measurement | **Available** (Anthropic Admin API usage reporting endpoint, returns `cache_read_input_tokens` and `cache_creation_input_tokens`; requires separate Admin API key) | **Capability gap** (no programmatic admin API; AI Studio Dashboard is web-only) | **Available** (OpenAI Admin API `/v1/organization/usage/completions`, returns `input_cached_tokens`; requires separate `sk-admin-` key) |
| Checkpoint/fork cache behavior (framework-relevant) | Operator-reported cache-cold: forks reported by an operator to incur fresh-load cost on the first operation; not measured by the framework; conservative assumption is cache-cold | Operator-reported cache-friendly: save-point restoration reported by an operator to avoid fresh-load cost; not measured by the framework; vendor offers no implicit-caching cost-savings guarantee, so the conservative assumption remains cache-cold | Unverified: framework has not driven Codex CLI; cache hit on resume/fork depends on TTL, byte-identity, and routing; conservative assumption is cache-cold |

### 5.1 On-Disk Conversation History Storage

The three target tools persist conversation history to disk in three structurally different ways. The differences are not cosmetic — they determine what an external reader can and cannot rely on when inspecting these files between or after tool runs. This subsection documents the layout, the write semantics, and the delta across vendors.

**Claude Code — file-per-session, append-only.**
- **Root.** `~/.claude/projects/<project-slug>/`. The slug is a transformation of the working directory path the session was launched in (slashes replaced with dashes, leading dash preserved). One subdirectory per project.
- **Per-session file.** `~/.claude/projects/<project-slug>/<session-uuid>.jsonl`. One file per session. The filename is the session UUID; the file extension is `.jsonl` (newline-delimited JSON, one record per turn or event).
- **Write pattern.** Strictly append-only during the lifetime of a session. New turns are appended at the end of the file. Existing bytes are not rewritten. The file grows monotonically; byte offset N within the file refers to the same record forever once written.
- **Lifecycle.** A session file is created on first turn and persists indefinitely. There is no built-in compaction or eviction; the file grows until the operator removes it manually. Multiple sessions in the same project produce multiple files side by side; sessions never share a file.
- **Identity.** The session UUID embedded in the filename is the canonical session identifier and matches the UUID Claude Code displays in its resume picker.

**Gemini CLI — file-per-session under a workspace-keyed directory, append-only.**
- **Root.** `~/.gemini/tmp/<project-hash>/`. The hash is a 64-character hex digest derived from the working directory the session was launched in. One subdirectory per workspace, matching the vendor session-management documentation cited in §3.3.
- **Per-session file.** `~/.gemini/tmp/<project-hash>/chats/session-<iso-timestamp>-<short-id>.json`. Each session is a single JSON document (not JSONL) under the workspace's `chats/` subdirectory. The filename encodes the session creation timestamp (ISO-like, with `:` replaced by `-`) followed by an 8-character suffix that is the first 8 characters of the session UUID. The file's top-level keys are `sessionId` (the full UUID), `projectHash` (matching the workspace directory), `startTime`, `lastUpdated`, and `messages` (an ordered array of conversation events).
- **Workspace-level sidecars.** `~/.gemini/tmp/<project-hash>/logs.json` and `~/.gemini/tmp/<project-hash>/beads_output.json` exist alongside `chats/` and hold workspace-level state shared across sessions in that workspace. They are not per-session.
- **Write pattern.** Each per-session JSON file is written by Gemini as the session progresses; the workspace-level sidecars are rewritten in place by Gemini as workspace state changes. The framework treats the per-session file as the durable transcript.
- **Lifecycle.** Per-session files persist until the operator deletes them (via `--delete-session <index>`, by removing the file, or by removing the workspace directory). There is no built-in compaction or aging-out across sessions; the `chats/` directory grows monotonically in number of files.
- **Identity.** The session is addressable by the index assigned by `--list-sessions` (1-based, ordered by recency). The filename's timestamp and suffix together form the on-disk identifier; the framework's reference implementation does not parse the suffix and instead resolves sessions through Gemini CLI's own indexing.

**OpenAI Codex CLI — single shared file across all sessions, mutable in place.**

Codex's history layout is the most operationally distinct of the three and the one most likely to surprise an external reader.

- **Root.** `~/.codex/`. There is **one** history file at this level: `~/.codex/history.jsonl`. Unlike Claude (file-per-session) and Gemini (directory-per-session), Codex concatenates events from **every session** into this single file.
- **File format.** Newline-delimited JSON, one record per event. Each record carries a session identifier so a reader can demultiplex which session a given line belongs to, but the lines are interleaved chronologically across all sessions, not grouped by session.
- **Write patterns.** Two distinct patterns coexist:
  1. **Append on new activity.** The default write path is the same as Claude/Gemini: when a session emits a new turn, a new line is appended at the end of `history.jsonl` and the file grows.
  2. **In-place compaction.** When the file size exceeds `[history] max_bytes` in `~/.codex/config.toml` (default on the order of 100 MB), Codex prunes the oldest records and rewrites the file in place. The file gets *shorter*. The byte at offset N before compaction is not necessarily the same byte at offset N after compaction; it may be a record from a different session, or it may be past the end of the new file entirely. Compaction is triggered by Codex itself, not by the operator.
- **Lifecycle of an individual session within `history.jsonl`.** A session's records are appended over time as the session progresses. Once `max_bytes` triggers compaction, older sessions can be partially or fully evicted from `history.jsonl`. The session may still exist (and be resumable) via `~/.codex/sessions/`, which is a separate storage mechanism — see below.
- **`~/.codex/sessions/` is a separate system.** The persistent session state used by `codex resume` and `codex fork` lives under `~/.codex/sessions/`, organized as one persisted record per session UUID. This directory is **not** the same as `history.jsonl` and follows different lifecycle rules. The framework's checkpoint architecture relies on `~/.codex/sessions/`, not on `history.jsonl`. An eviction from `history.jsonl` does not necessarily evict the corresponding entry from `~/.codex/sessions/`, and vice versa. Treat them as two parallel views of session history with different durability and mutability guarantees.

**Cross-tool delta — quick comparison.**

| Property | Claude Code | Gemini CLI | Codex CLI |
|---|---|---|---|
| Storage unit per session | One file | One file | Shared lines in a single file |
| Path | `~/.claude/projects/<slug>/<uuid>.jsonl` | `~/.gemini/tmp/<hash>/chats/session-<ts>-<suffix>.json` | `~/.codex/history.jsonl` (events) + `~/.codex/sessions/<uuid>` (resumable state) |
| File format | JSONL (one event per line) | JSON (whole-document) | JSONL (one event per line) |
| Sessions per file | 1 | 1 | All sessions interleaved |
| Workspace-keyed root directory | Yes (`projects/<slug>`) | Yes (`tmp/<hash>`) | No (single global file at `~/.codex/history.jsonl`) |
| Workspace-level sidecar files alongside sessions | None | `logs.json`, `beads_output.json` | None |
| Write pattern | Append-only | Per-session file rewritten as JSON document; workspace sidecars rewritten in place | Append + in-place compaction |
| Byte-offset stability across time | Stable forever | Not applicable (whole-document JSON, not byte-addressed) | **Unstable after compaction** |
| File can shrink | No | Yes (whole-document rewrite may shrink) | Yes (when `[history] max_bytes` exceeded) |
| Built-in eviction policy | None | None | Size-bounded; oldest events dropped |
| Session disappearance from history file | Operator action only | Operator action only | Automatic on compaction; the resumable copy in `~/.codex/sessions/` may still exist independently |
| Canonical session identifier visible in path | Yes (filename = UUID) | Partial (filename encodes timestamp + first 8 chars of UUID; full UUID lives in the file's `sessionId` field) | No (must be parsed from each line's record) |

**Implications for understanding the delta.**

The vendors have made three different bets about how conversation history should be stored:

- **Claude treats history as immutable evidence.** Once written, never rewritten; grows without bound; the operator is responsible for any cleanup. This favors auditability and forensic analysis at the cost of unbounded disk usage.
- **Gemini treats history as one workspace's collection of session documents.** Each session is a single JSON document under that workspace's `chats/` directory; sessions are independent files that can be deleted or inspected without affecting other sessions, and the workspace itself owns shared sidecars (`logs.json`, `beads_output.json`) for state that spans sessions. This favors per-workspace organization (one operator switching between workspaces sees a clean per-workspace separation) at the cost of holding the entire transcript as a single rewritable document rather than as an append-only log.
- **Codex treats history as a bounded rolling log.** A single shared file is automatically pruned to stay under a size cap; older sessions silently age out of the event log even though their resumable state may persist separately under `~/.codex/sessions/`. This favors predictable disk footprint at the cost of byte-offset stability and at the cost of the dual-storage model (events vs. sessions stored in two different places with two different lifecycles).

A reader working against any of these three layouts must understand which model that tool follows; assumptions that hold for Claude (filenames are session IDs, files grow monotonically) and Gemini (directories are session boundaries) silently fail against Codex (filenames are not session IDs, the file can shrink, the same byte offset can refer to different content over time, and the resumable session state lives in a different directory than the event log).

**Verification status of this subsection.** Claude and Gemini layouts described here are observed against the framework's pinned versions and exercised by the reference implementation. Codex's `history.jsonl` compaction behavior, the precise default value of `[history] max_bytes`, and the relationship between `history.jsonl` eviction and `~/.codex/sessions/` retention are documented from vendor sources and from filesystem inspection of `~/.codex/`; an implementer who depends on the eviction-retention coupling for their own logic should verify it end-to-end against the pinned Codex version before relying on it.

---

## 6. Capability Gap Summary

The following framework capabilities have known gaps in one or more target tools. These gaps are properties of the tools, not defects in any framework implementation. An implementer's required response is documentation, not concealment.

Each cell in the table below carries one of three labels: **Verified** (the framework's reference implementation exercises this capability against the pinned version and observes it to behave correctly), **Primitive available** (the vendor exposes the necessary primitive but the framework's reference implementation has not yet exercised it), or **Unverified / Gap** (no vendor primitive is documented, or the existing primitive's behavior is unknown for the framework's purposes). A capability is only safe to depend on if it is labeled **Verified** for the target tool the implementation actually uses.

| Capability | Claude Code | Gemini CLI | OpenAI Codex CLI |
|---|---|---|---|
| Cross-process checkpoint persistence | **Verified** (named sessions on disk, restorable via `--resume <name>`) | **Primitive available** (vendor docs at `geminicli.com/docs/cli/session-management/` explicitly describe automatic persistence to `~/.gemini/tmp/<project_hash>/chats/`, automatic recording of session history, preservation across interruption, and full-context restoration via `--resume` or `/resume`; framework has not yet run the specific test that captures a `/resume save` tag, restarts the process, and restores both the session and the tag intact) | **Primitive available**: `~/.codex/sessions/` persists session state; `codex resume` restores in a fresh process; framework has not yet exercised this end-to-end |
| Lossless checkpoint restoration | **Verified** | **Verified** (in-process) | **Primitive available** (via `codex resume <id>` and `codex fork <id>`); framework has not yet exercised this end-to-end |
| Independent forking from a checkpoint | **Verified** (via `--resume <name> --fork-session`) | **Verified** (via `/resume save` + `/resume resume` branching) | **Primitive available** (via `codex fork <id>`); framework has not yet exercised this end-to-end |
| Re-question at any prior tier | **Verified** | **Verified** | **Primitive available**; framework has not yet exercised this end-to-end |
| Native compaction | **Verified** (`/compact`) | **Verified** (`/compress`) | **Primitive available** (`/compact`; vendor documentation describes both on-demand invocation and automatic compaction at context-limit thresholds; framework has not exercised end-to-end) |
| In-place per-turn undo | **Verified** (`Esc Esc Enter Enter`) | **Primitive available** (`Esc Esc` opens the rewind picker per the vendor reference; not exercised by the framework because checkpointing provides stronger isolation) | **Primitive available** (`Esc Esc` while composer is empty edits the previous user message; continued `Esc` walks further back through the transcript; `Enter` forks from the selected point per the vendor reference at `developers.openai.com/codex/cli/features`; not exercised by the framework) |
| Quota and rate-limit reporting | Partial: status bar shows context occupancy via `/context`; no programmatic rate-limit slash command verified for the pinned version | **Primitive available** (`/stats session` displays per-model rate limits with reset timers); framework does not yet parse this output |  **Primitive available** (`/status` with 5-hour and weekly windows); framework does not yet parse this output |
| Reliable file writing without prompt hints | **Verified** (native `Write` tool) | Requires prompt hint to avoid heredoc errors; **Verified** that the hint resolves the issue | **Unverified** under any sandbox mode; framework has not exercised file writing against Codex |
| Operator-visible cache statistics | **Unverified / Gap**: `/context` displays total occupancy only; no cached-vs-uncached distinction observed | **Unverified**: `/stats session` documentation does not specify cache statistics; not exercised by framework | **Unverified**: `/status` format documented in this lexicon does not include cache statistics |
| Vendor-side admin API for cached-token measurement | **Available**: Anthropic Admin API exposes a usage reporting endpoint that returns `input_tokens`, `cache_read_input_tokens`, and `cache_creation_input_tokens` broken out by workspace, model, and time bucket. Requires a separate Admin API key (operator-provisioned). Aggregation lag is a few minutes. This is the framework's strongest cache verification evidence source for Claude. | **Capability gap**: Google does not expose a programmatic admin or usage API for Gemini that returns cached vs uncached token breakdowns. Usage data is accessible only through the AI Studio web Dashboard (UI-only, not scriptable). The framework's cache verification for Gemini relies on weaker evidence sources (HTTP debug capture if available, otherwise wall-clock latency) and the resulting lexicon entries will have lower evidentiary strength than the Claude and Codex equivalents. | **Available**: OpenAI Admin API exposes an organization-level completions usage endpoint at `/v1/organization/usage/completions` that returns `input_tokens` and `input_cached_tokens` (among other fields) broken out by time bucket, project, and model. Requires a separate Admin API key prefixed `sk-admin-`. Aggregation lag is a few minutes. This is the framework's strongest cache verification evidence source for Codex. |
| Checkpoint cost-efficiency (cache hit on restore) | **Operator-reported cache-cold, framework-unmeasured.** An operator has reported that forks created via `--resume <name> --fork-session` incur fresh-load cost on the first operation rather than benefiting from a cache hit on the parent's cached prefix. The framework's reference implementation has not measured Claude Code's caching cost, so this is operator hearsay, not a framework-verified observation. If the report holds under controlled measurement, the consequence for framework cost estimation is that each fork-based checkpoint may carry the full cumulative tier cost. The conservative assumption for implementers is that fork-based checkpointing is cache-cold. | **Operator-reported cache-friendly, framework-unmeasured.** An operator has reported that save-point restoration via `/resume resume <tag>` does not incur the cost of a fresh load, suggesting that the underlying implicit caching mechanism survives the branch operation. The framework's reference implementation has not measured Gemini CLI's caching cost. The vendor explicitly offers no cost-savings guarantee for implicit caching, so the conservative assumption for implementers remains cache-cold even though optimistic cost models may turn out to be correct. | **Unverified.** The framework has not driven Codex CLI in any capacity. Cache hit on `codex resume <id>` or `codex fork <id>` depends on TTL window, byte-identity of the prompt prefix, and OpenAI's request routing. The conservative assumption for implementers is cache-cold until measurement is done. |
| Non-interactive single-shot execution | **Primitive available** (`--print` / `-p`); not used by framework | **Primitive available** (`-p` / `--prompt`); not used by framework | **Primitive available** (`codex exec`); not used by framework |
| Prompt then continue interactively | (no equivalent) | **Primitive available** (`-i` / `--prompt-interactive`); not used by framework | (no equivalent) |
| Native MCP server exposure (tool itself becomes a server) | Not applicable | Not applicable | **Primitive available** (`codex mcp-server`); not used by framework |
| Remote control via websocket | Not applicable | Not applicable | **Primitive available** (`--remote <ws-addr>`); not used by framework |

Items labeled **Unverified** or **Unverified / Gap** must be tested by the implementer before being depended upon. Items labeled **Primitive available** are safer than unverified items but still require empirical confirmation of the specific behavior the framework needs (for example, the lossless property of restoration, the format of status output, or the persistence of sessions across tool process restarts). Items labeled **Verified** have been exercised by the framework's reference implementation against the pinned version of the relevant tool.

**A note on the Codex revision history:** Earlier drafts of this lexicon recorded checkpoint creation, restoration, and re-questioning at prior tiers as capability gaps for OpenAI Codex CLI. Verification of `codex --help`, `codex resume --help`, and `codex fork --help` against `codex-cli 0.118.0` shows that Codex exposes native `codex resume` and `codex fork` subcommands for these operations, with session state persisted in `~/.codex/sessions/`. The earlier "capability gap" characterization is wrong with respect to vendor support and has been corrected. The framework's reference implementation has not yet exercised these primitives end-to-end against a real Codex session, which is why the Codex column predominantly shows "Primitive available" rather than "Verified." Closing the gap to "Verified" requires extending `probe.py` with a Codex driver and validating each capability against the pinned version.

---

## 7. How `DESIGN.prd.md` Uses This Lexicon

`DESIGN.prd.md` is written in tool-agnostic terms throughout. When the PRD describes a behavior — for example, "the system must restore a checkpoint without modifying any other checkpoint" — the implementer consults this lexicon to determine which concrete vendor primitive to use for each supported tool. The framework's abstract terms (target tool, checkpoint, tier, run, context occupancy, and so on) are defined once in Section 1 of this lexicon and used identically by both documents.

When a vendor primitive does not exist for a required behavior, the implementer consults Section 6 to determine whether the gap is documented and what the acceptable response is. The PRD prohibits silently degrading the measurement; this lexicon makes the acceptable responses to each gap concrete by labeling each capability as **Verified**, **Primitive available**, or **Unverified / Gap** for each tool.

When a new target tool is added to the framework, this lexicon must be extended with a new per-tool section satisfying the same level of detail as the existing sections (lifecycle, restoration, in-session commands, key sequences, authentication, file writing, status reporting, subagent behavior, capability mapping, and verification status). A target tool may not be claimed as supported by the framework until its lexicon entry is complete and at least the capabilities the framework actually exercises are labeled **Verified**.

When a vendor changes the syntax of a command, removes a command, or introduces a new primitive, this lexicon must be updated and the "Pinned Tool Versions" table at the top of the document must record the new version and the date of last verification. Lexicon updates that close or open capability gaps must also be propagated to `DESIGN.prd.md` Sections 7.3, 7.4, and the Capability Gap Summary.

The lexicon is a living document. Its current pinned versions are recorded at the top; its current verification status for each item is recorded in the per-tool verification status sections (2.11, 3.12, 4.12) and summarized in Section 6. Section 8 specifies how an implementer can close the open caching verification questions through a combination of vendor documentation review and end-to-end test scripts.

---

## 8. Caching Verification

The caching behavior subsections (2.8, 3.9, 4.9) and the related rows in Sections 5 and 6 currently rest on a mixture of vendor-API documentation, operator hearsay, and explicit gaps. This section specifies how to close those gaps. It defines two parallel tracks for each target tool — a documentation review track that resolves what can be answered without running a tool, and an empirical test track that resolves what can only be answered by exercising a real tool process — and it specifies the structure and behavior of three vendor-specific Python test scripts that, when written and executed against the pinned tool versions, will move every caching item out of "operator-reported" or "unverified" into either "Verified" or "Verified gap" with measured evidence.

This section is a verification roadmap. It does not document caching behavior itself; it documents how to find out what the caching behavior is.

### 8.1 Purpose and Scope

The framework's pre-run cost estimation requirement (`DESIGN.prd.md` Section 4.10 "Pre-Flight Validation" and the open question on cost in Section 13 "Open Questions and Known Gaps") cannot be implemented honestly without knowing how each target tool's caching behavior interacts with the framework's checkpoint architecture. Specifically, the framework needs answers to three questions for each tool:

1. **Does the CLI tool surface any caching information to the operator** — for example, cached vs. uncached token counts, cache hit rates, or cached prefix age? Without this, the framework can never directly observe what fraction of an operation was a cache hit.

2. **Does checkpoint creation preserve cache eligibility?** When the framework creates a tier checkpoint, does the underlying cached prefix from the parent context survive into the checkpoint, or does the act of branching invalidate it? Without this, the framework cannot estimate whether a multi-tier session will pay near-cumulative cost or near-marginal cost per checkpoint.

3. **Does checkpoint restoration preserve cache eligibility?** When the framework returns to a previously captured checkpoint — possibly hours or days later, possibly in a fresh process — does the API still treat the resumed prompt as a cache hit, or as a cache miss? Without this, the framework cannot estimate the cost of `--rerun` or `--continue` operations.

The verification work in this section answers all three questions for each of the three target tools to the extent that operator-visible CLI surfaces and indirect measurements permit. Until the work is done, the framework's cost estimation must assume the conservative case (everything is a cache miss).

### 8.2 Test Methodology

This subsection defines the methodology used by all three vendor-specific test scripts: the canonical fixture, the test scenarios, the statistical approach, the threats to validity, and the evidence sources.

#### 8.2.1 Canonical Test Fixture

All three test scripts read the same fixed source material and ask the same fixed question, so that measurements across tools are directly comparable. The canonical fixture is defined as:

- **Source content:** the value of `TIER_1_PROMPT` from `/opt/git/ihaz_cloud/agentic-context-probe/config.env`. This is the framework's tier-1 load instruction (12 documentation files from the Gastown test repository, totaling approximately 90,000 tokens against Claude). The corpus's pinning is satisfied by the framework's existing pinning of the Gastown repository (commit `9f962c4af068fe9da9f4bd3624e7b66351121fdf`).
- **Fixed question:** the value of `QUESTION_A` from the same `config.env`. This is the framework's Q-A escalation-protocol question, chosen because it has unambiguous ground truth and because its answer comes entirely from documentation present at tier 1.
- **Variable question (used in Scenario B to defeat model-side response caching):** the value of `QUESTION_B` from the same `config.env`. This is a structurally similar question with a different correct answer, used as the second ask in scenarios that need to break prompt-prefix identity without changing prompt size meaningfully.
- **Output file path injection:** prompts must be rewritten to instruct the model to write its answer to a script-specified file path (the framework's standard file-based completion-detection pattern). The original `OUTFILE` placeholder in `QUESTION_A` and `QUESTION_B` is replaced by the script with an absolute path under the script's output directory.

The three test scripts must read these values from the same `config.env` file rather than embedding them. If `config.env` changes, the next script run produces measurements against the new fixture and the comparison.md output records which fixture version was used (the script captures the SHA-256 of the relevant `config.env` lines at run start).

If a separate dedicated fixture file is preferred over reusing `config.env`, that fixture file must be checked into the framework repository at a stable path and the test scripts updated to read from it. The choice between "reuse `config.env`" and "create a dedicated `tests/fixtures/cache.env`" is left to the implementer, but the choice must be consistent across all three scripts.

#### 8.2.2 Common Test Scenarios

The framework defines five test scenarios, labeled A through E. They are designed to produce comparable measurements across tools so that an analyst can directly contrast caching behavior. Each scenario is run as a *measurement series* of N≥5 repetitions (see Section 8.2.3 on statistics) rather than as a single shot.

The earlier draft of this section included a sixth scenario "F: operator-report reproduction" which has been folded into Scenario E because the operator-report verification is structurally identical to the cross-process roundtrip measurement at zero wait — there is no need for a separate scenario. The earlier draft also defined a "Scenario C: same-process branch" and a "Scenario D: cross-process restoration" as distinct steps; this distinction has been dropped because two of the three target tools (Claude and Codex) have only cross-process branch primitives, so a "same-process branch" scenario was not achievable for them.

**Scenario A — Cold-load baseline.** A single measurement series of: launch fresh tool process, load the canonical source content, ask the canonical fixed question, record metrics, terminate. Each repetition uses a fresh process; no state is shared between repetitions.

*What it measures:* the cost the framework currently assumes for every operation. Scenarios B and C are interpreted relative to this baseline.

**Scenario B — In-process repeat with state reset.** A single measurement series of: launch fresh tool process, load the canonical source content, ask the canonical fixed question (`QUESTION_A`), reset the tool's conversation state to the post-load state (using the tool's per-turn undo or save-point-restore primitive — see per-tool subsections), ask the canonical fixed question a second time, record metrics for both asks, terminate.

*What it measures:* whether the tool's underlying API benefits from any in-process prompt caching at all. The state reset before the second ask is critical: without it, the second ask's prompt prefix would include the first ask's response, defeating prefix-identity-based caching. The reset mechanism is per-tool and is specified in each per-tool subsection. If the tool has no clean reset mechanism, the alternative is to use `QUESTION_B` (structurally similar but different content) as the second ask, accepting that the prefix is then non-identical and that the measurement reflects "API cache hit on the source-content portion of the prefix" rather than "API cache hit on the whole prefix."

**Scenario C — Cross-process checkpoint roundtrip (no wait).** A single measurement series of: launch fresh tool process, load the canonical source content, create a checkpoint using the tool's native primitive (per-tool details below), terminate the original tool process, immediately launch a fresh tool process that restores the checkpoint, ask the canonical fixed question against the restored state, record metrics, terminate.

*What it measures:* whether checkpoint creation and restoration together preserve cache eligibility across a process boundary, with no time for cache TTL to expire. Difference between C and A (relative to N repetitions) is the net checkpoint cache benefit — the framework-relevant number for cost estimation.

**Scenario D — TTL boundary mapping.** Repeat Scenario C with a deliberate wait inserted between checkpoint creation and checkpoint restoration. The wait values are: 1 minute, 6 minutes, 65 minutes, 25 hours. These bracket the documented Anthropic 5-minute and 1-hour TTLs and the OpenAI extended 24-hour TTL. (Gemini's TTL boundaries are not as well documented; for Gemini, additional bucket values may be added once Section 8.6.1's documentation review identifies the relevant boundaries.)

Scenario D is run as four separate sub-scenarios (D1=1min, D2=6min, D3=65min, D4=25hr), each with its own measurement series. Each sub-scenario is invocation-driven rather than wait-blocking inside a single script run: the script supports being invoked multiple times, persists scenario state between invocations (Section 8.3.5), and aggregates results into the same `results.json`. An operator schedules the invocations externally (via `at`, cron, manual, or any other scheduler).

**Scenario D uses a single shared checkpoint across all sub-scenarios and all repetitions within a sub-scenario.** This is the critical structural distinction from Scenarios A, B, C, and E. The single checkpoint is created once during the `--setup` phase and is then restored N times (the configured `--repetitions`) per sub-scenario, with each restoration measured as one repetition. The same checkpoint is reused across all four sub-scenarios (D1, D2, D3, D4); only the wait between the checkpoint's creation timestamp and the restoration is varied. The reason for sharing the checkpoint is that Scenario D is measuring "how long does the cache benefit on a given checkpoint persist"; if each repetition or sub-scenario created a fresh checkpoint, the question becomes "how long does the cache benefit on freshly-created checkpoints persist," which is a different and less useful measurement.

In contrast, **Scenarios A, B, C, and E create fresh state per repetition.** Each of their N repetitions launches a fresh tool process (Scenario A), or a fresh load + reset cycle (Scenario B), or a fresh load + checkpoint + restore cycle (Scenarios C and E). This is the right approach for those scenarios because they are measuring per-operation cost, not the persistence of a single checkpoint over time.

*What Scenario D measures:* the wall-clock decay of the cache benefit on a single checkpoint as time passes. The boundary at which sub-scenario median latency converges with Scenario A's baseline tells the framework the effective TTL operators can rely on for resumed checkpoints.

**Scenario E — Operator-report reproduction.** A single measurement series identical to Scenario C but explicitly compared side-by-side with Scenario A as a confirm/refute test of the lexicon's existing operator hearsay. For Claude Code: tests whether forks are cache-cold (lexicon Section 2.8). For Gemini CLI: tests whether save points are cache-friendly (lexicon Section 3.9). For Codex CLI: establishes a baseline because no operator report exists yet (lexicon Section 4.9).

*What it measures:* directly resolves the "operator-reported, framework-unmeasured" rows in Section 6 into measured truth, regardless of whether the truth confirms or refutes the report.

#### 8.2.3 Statistical Methodology

Each measurement series consists of N≥5 repetitions (configurable via `--repetitions`, default 5). For each repetition, the script records the question-step latency (defined in Section 8.4.3) and the captured state outputs.

Per-scenario statistics computed and recorded in `results.json`:
- **N**: the number of repetitions actually run (may be less than the configured N if the script encountered a rate-limit or error mid-series).
- **median**: the median question-step latency in seconds.
- **iqr** (inter-quartile range): the difference between the 75th and 25th percentile latencies, used as a robust dispersion measure.
- **min**, **max**: the fastest and slowest individual repetitions.
- **mean** and **stdev**: the arithmetic mean and standard deviation, included for completeness but not used as the primary comparison statistic (median+IQR is preferred because of the long-tailed distribution typical of LLM API latency).

**Effect-size threshold for declaring a cache hit.** Two scenarios A and X are considered to differ in a way consistent with caching only if X's median is at least 30% lower than A's median *and* the IQR ranges of A and X do not overlap. If either condition fails, the difference is reported as "not distinguishable from noise" rather than as evidence of caching. The 30% threshold is conservative and chosen to be robust against the inherent variability of LLM API latency; an implementer with reason to use a different threshold may override it via `--effect-threshold`, with the chosen value recorded in `results.json`.

The script records all individual measurements in `results.json` so that an analyst can recompute statistics with different thresholds or different statistical tests after the fact.

#### 8.2.4 Threats to Validity

A wall-clock latency reduction in scenarios that should benefit from caching is consistent with cache hits but does not prove cache hits. Three confounders can produce the same observable effect:

1. **Model-side response caching.** If a model has cached its own response to an identical prompt (some inference servers do this), the second observation of the same prompt may return faster than the first regardless of whether the API-level prompt cache is involved. Mitigation: Scenario B's `QUESTION_B` variant (different content, similar size) defeats response caching while preserving most of the prompt-prefix-cache opportunity.

2. **TUI / connection warmup.** A freshly-launched tool process pays a one-time cost for TCP connection establishment, TLS handshake, DNS resolution, model loading on the inference side, and any per-process initialization. Subsequent operations within the same process do not pay these costs and are faster for reasons unrelated to prompt caching. Mitigation: Scenario A always uses a fresh process per repetition, so the warmup cost is measured uniformly. Scenarios B, C, D, E that compare against A are comparing fresh-process-to-fresh-process and the warmup cost cancels out.

3. **Network and inference-side jitter.** Even with everything else held constant, LLM API latency varies repetition-to-repetition due to load-balancing, queue depth, and sampling. Mitigation: N≥5 repetitions and the IQR-non-overlap rule from Section 8.2.3.

A wall-clock latency reduction that survives all three of these mitigations is the best evidence the framework can produce without admin-API or HTTP-level capture (Section 8.2.5). It is not proof of caching, but it is sufficient evidence to update the lexicon's operator-reported rows to "measured cache-friendly" or "measured cache-cold."

The scripts should explicitly record, for each scenario, the threats-to-validity considerations that apply and any mitigations the script implemented. This helps a future analyst interpret the results.

#### 8.2.5 Evidence Sources

The scripts pursue evidence of caching through five sources, listed in order of evidentiary strength. The strongest available source for each scenario determines the value of the `evidence_source_used` field in `results.json`. Scripts should attempt every source they can; the lexicon's operator-reported rows are closed when the strongest source produces a clear verdict.

1. **Vendor admin API polling (strongest, when available and authorized).** Both Anthropic and OpenAI expose admin-level usage reporting endpoints that return time-bucketed token counts broken down by token category — including cached versus uncached input tokens. These endpoints are documented in Section 8.2.6. They are the strongest evidence source because they read directly from the vendor's billing-grade usage records, are byte-stable JSON, and are independent of whatever the CLI tool surfaces in its TUI. Google does not expose an equivalent API for Gemini; this is a documented per-tool capability gap (see Section 6).

   The admin API approach has two structural caveats that make it complementary to wall-clock latency rather than replacement: aggregation lag (a few minutes between request execution and the data being queryable) and bucket-level granularity (typically hourly or 5-minute buckets, not per-request). The framework handles both by flanking each scenario series with before/after admin API snapshots and computing the delta in cached vs uncached input tokens at the scenario level. The delta is the ground-truth answer to "did this scenario benefit from caching." Per-request attribution remains the wall-clock latency's job.

   Authentication for this source is operator-supplied: the scripts accept an `--admin-key <key>` flag (or environment variable) and use it only for the admin API polling. If no admin key is provided, the script gracefully degrades to the next-strongest available evidence source. The admin API key is never required for the script to run; it is required only for `evidence_source_used = vendor_admin_api`.

2. **HTTP-level debug capture (good, when available).** All three target tool vendors expose debug-mode output that, on supported tools and supported version, may include the cache-related fields the API response carries (`cache_read_input_tokens`, `cache_creation_input_tokens`, `cached_tokens`, etc.) embedded in the SSE response stream from the generation endpoint. The scripts should attempt to enable debug output and capture it:
   - **Claude Code:** the `ANTHROPIC_LOG=debug` environment variable, or `claude --debug`. Whether either of these surfaces cache fields against `2.1.92` is unverified; the scripts should attempt both and record what they capture. The script's job is to look for SSE event frames (`event: message_delta`, `event: message_stop`) with `usage` blocks containing the cache fields named above.
   - **Gemini CLI:** the `--debug` flag (Section 3.2) and the F12 debug console. Whether either surfaces cache fields against `0.36.0` is unverified; the scripts should attempt to capture the debug stream.
   - **Codex CLI:** the `codex debug` subcommand and any debug-level configuration via `-c key=value` overrides. Whether these surface cache fields against `codex-cli 0.118.0` is unverified.
   If debug capture works for any tool, the JSON results include the captured cache fields directly, and that becomes the second-strongest evidence the script produces.

   An alternative for this evidence source, when neither environment variables nor flags expose the SSE bodies, is a MITM proxy approach (mitmproxy, Charles, or equivalent) intercepting the HTTPS traffic between the tool and the vendor API. The MITM approach is more invasive but produces guaranteed access to API response bodies regardless of what the tool exposes. The framework does not require implementers to use a MITM proxy; it is documented here as a fallback path.

3. **Status footer tokens — Gemini-specific (good, when configured).** Gemini CLI exposes a configurable footer at `~/.gemini/settings.json` under `ui.footer.items`. When the operator has enabled `token-count` in their footer items, Gemini renders a session-cumulative input+output token count at the bottom of the TUI. The framework captures this footer via `tmux capture-pane` immediately before and immediately after every measurement operation, parses out the `tokens` value, and computes a per-operation `tokens_delta = post − pre`. Aggregating per-operation deltas across a scenario series produces a measured input+output token total without depending on the admin API.

   This source is **weaker than admin API polling** because it does not distinguish cached from uncached input tokens — it returns a single combined session counter — but it is **substantially stronger than wall-clock latency** because it directly measures token consumption rather than inferring it from request timing. For Gemini, where no admin API exists, this is the strongest available evidence source.

   The Gemini test script reads `ui.footer.items` at startup and refuses to run if the framework's required items (`token-count`, `context-used`, `model-name`, `session-id`, `memory-usage`) are not present. The script does not modify the operator's settings file. The fail-fast error message includes a copy-paste-friendly JSON snippet for the operator to add. Section 8.6.1 documents the doc-check item; Section 8.6.2 documents the script integration.

   The same evidence source is **not currently exposed** for Claude or Codex. Claude Code's status bar shows a `Used: NNk/NNk` figure that the framework already captures via `/context`, but no operator-visible token-count counter has been verified. Codex CLI's `/status` shows context window and rate limits but no per-session token total. Implementers extending these tools may wire up an analogous mechanism if a vendor exposes one.

4. **Operator-visible status command output (weak, mostly null).** Each tool has a status command (`/context`, `/stats session`, `/status`) whose output may or may not surface caching information. The scripts capture this output before and after every measurement operation and search it for cache-related field names (the canonical keyword list in Section 8.3.1). The lexicon currently records that these surfaces do not appear to expose cache fields, so this evidence source is expected to produce null results for most or all tools — but the scripts should capture and search anyway, because a null result is itself a verified observation.

5. **Wall-clock latency comparison (fallback).** When none of the above produces direct evidence, latency comparison across scenarios with the statistical methodology in Section 8.2.3 is the framework's only remaining signal. This is the weakest evidence source and is subject to the threats-to-validity in Section 8.2.4, but it is sufficient to confirm or refute the lexicon's operator-reported rows when the effect size is large.

The scripts must produce measurements from every evidence source they can access for the operator's environment, and the `comparison.md` deliverable must explicitly identify which evidence source supported each conclusion. The five sources are not mutually exclusive; a single scenario may produce direct cache field counts from the admin API, find no matches in the status command output, surface non-zero footer token deltas, and also show a wall-clock latency reduction. All four observations are recorded; the strongest determines `evidence_source_used`.

#### 8.2.6 Vendor Admin API Specifics

The framework's primary evidence source for cache verification is admin-level usage reporting from the tool vendor. This subsection documents what each vendor exposes, the per-tool capability gap where one exists, and the implementer's responsibility for handling each tool's authentication and bucketing model. The lexicon does not document the API specifics in full (those belong in vendor reference material) but documents what the framework's test scripts need to know.

**Anthropic Admin API.** Anthropic exposes an Admin API at the platform-documented base URL with usage reporting endpoints that return cached vs uncached input token counts broken out by workspace, model, time bucket, and token category. The relevant fields the framework cares about are `input_tokens` (uncached), `cache_read_input_tokens`, and `cache_creation_input_tokens`. The endpoint accepts query parameters for the time range and bucket width; the framework uses narrow time ranges flanking each scenario series. Authentication uses a separate Admin API key (operator-provisioned at the organization level, distinct from the regular `ANTHROPIC_API_KEY`). The script accepts the key via `--anthropic-admin-key <key>` or the `ANTHROPIC_ADMIN_API_KEY` environment variable. The script must not log the key value to any captured artifact.

The Anthropic Admin API has aggregation lag, typically a few minutes between request execution and the data being queryable. The script must build in a wait between scenario completion and the post-snapshot poll. The wait duration is configurable via `--admin-api-lag-s <seconds>` with a default of 300 (5 minutes). If the post-snapshot does not show updated counts after the wait, the script retries the snapshot at increasing intervals before giving up and recording the scenario with `admin_api_status: "lag_exceeded"`.

**OpenAI Admin API.** OpenAI exposes an organization-level usage endpoint at the platform-documented base URL that returns time-bucketed completion usage broken out by token category, including `input_tokens` (uncached) and `input_cached_tokens`. The endpoint accepts `start_time`, `end_time`, `bucket_width`, `group_by`, `project_ids`, and `model` parameters. Authentication uses an Admin API key prefixed `sk-admin-...` (operator-provisioned at the organization level, distinct from the regular project API keys Codex CLI uses). The script accepts the key via `--openai-admin-key <key>` or the `OPENAI_ADMIN_API_KEY` environment variable. As with Anthropic, the key must not be logged.

The OpenAI Admin API has the same aggregation lag pattern; the same `--admin-api-lag-s` configuration applies.

**Google / Gemini admin API.** **Capability gap.** Google does not expose a programmatic admin or usage API for Gemini that returns cached vs uncached token breakdowns. The closest available sources are the AI Studio web Dashboard (UI-only, not scriptable) and the Google Cloud Billing API (returns billing-level aggregates without cache breakdown). For Gemini, the test script must rely on HTTP debug capture if it works, or fall back to wall-clock latency. Section 6's capability gap summary records this asymmetry, and the Gemini test script's `comparison.md` must explicitly note that Gemini's results have weaker evidentiary strength than the corresponding Claude and Codex results.

**Per-tool admin API responsibility for the test scripts:**
- Claude script (`test-cache/claude/test-cache-claude.py`): supports `--anthropic-admin-key`. If provided, polls the Admin API before and after each scenario series.
- Gemini script (`test-cache/gemini/test-cache-gemini.py`): does not accept any admin key flag (no admin API exists). Records `admin_api_status: "vendor_capability_gap"` in every scenario's `admin_api_snapshot` block.
- Codex script (`test-cache/codex/test-cache-codex.py`): supports `--openai-admin-key`. If provided, polls the Admin API before and after each scenario series.

The scripts must gracefully degrade when the admin key is not provided: they record `admin_api_status: "no_key_provided"` and continue with the lower-tier evidence sources. The script does not refuse to run without an admin key; the admin API is an opt-in upgrade, not a hard requirement.

**Snapshot semantics:** before starting a scenario series, the script polls the admin API for the immediately-preceding bucket and records the cached/uncached token counts. After completing the scenario series and waiting for the aggregation lag, the script polls again for the bucket(s) covering the scenario's wall-clock execution window. The delta is the scenario's measured cache behavior. Both snapshots are recorded in the scenario's `admin_api_snapshot` block in `results.json`.

### 8.3 Common Implementation Requirements

This subsection specifies cross-cutting requirements that all three vendor-specific test scripts must satisfy. Implementers building the scripts should treat these as shared contracts; differences between the per-tool scripts are confined to vendor-specific mechanics (which slash command, which key sequence, which subcommand) and are documented in the per-tool subsections.

#### 8.3.1 Output Schema and Authority

The authoritative result of running a test script is a `results.json` file written to `test-output/cache-<tool>-<timestamp>/results.json`. Any human-readable derivative (such as `comparison.md`) is generated from `results.json` and is informational. If the two disagree, `results.json` wins.

The schema is:

```json
{
  "schema_version": "1",
  "tool": "claude" | "gemini" | "codex",
  "tool_version": "2.1.92",
  "model": "claude-opus-4-6[1m]",
  "fixture": {
    "source_path": "/opt/git/ihaz_cloud/agentic-context-probe/config.env",
    "source_sha256": "abc123...",
    "tier_label": "tier1",
    "question_id": "A",
    "variant_question_id": "B"
  },
  "config": {
    "repetitions": 5,
    "effect_threshold": 0.30,
    "stability_poll_interval_s": 0.5,
    "stability_threshold_s": 2.0
  },
  "started_at": "2026-04-06T18:00:00Z",
  "scenarios": [
    {
      "name": "A",
      "description": "Cold-load baseline",
      "started_at": "2026-04-06T18:00:00Z",
      "completed_at": "2026-04-06T18:05:00Z",
      "parameters": {"wait_minutes": 0},
      "repetitions": [
        {
          "rep_index": 0,
          "operations": [
            {
              "name": "launch",
              "start_ts": "2026-04-06T18:00:00.000Z",
              "end_ts": "2026-04-06T18:00:05.123Z",
              "duration_s": 5.123,
              "pre_state": null,
              "post_state": "Used: 0k/1000k\n",
              "notes": "fresh process launch"
            },
            {
              "name": "load",
              "start_ts": "2026-04-06T18:00:05.123Z",
              "end_ts": "2026-04-06T18:01:30.456Z",
              "duration_s": 85.333,
              "pre_state": "Used: 0k/1000k\n",
              "post_state": "Used: 91k/1000k\n",
              "notes": "tier 1 load receipt received"
            },
            {
              "name": "question",
              "start_ts": "2026-04-06T18:01:30.456Z",
              "end_ts": "2026-04-06T18:01:42.789Z",
              "duration_s": 12.333,
              "pre_state": "Used: 91k/1000k\n",
              "post_state": "Used: 93k/1000k\n",
              "notes": "question A answered",
              "footer_pre": " workspace ... tokens             /model\n /opt/.../gastown ... 91k tokens   gemini-3.1-pro-preview",
              "footer_post": " workspace ... tokens             /model\n /opt/.../gastown ... 93k tokens   gemini-3.1-pro-preview",
              "tokens_delta": 2000
            }
          ],
          "primary_latency_s": 12.333,
          "cache_field_matches": []
        }
      ],
      "stats": {
        "n": 5,
        "median_s": 12.4,
        "iqr_s": 0.6,
        "min_s": 11.9,
        "max_s": 13.1,
        "mean_s": 12.5,
        "stdev_s": 0.4
      },
      "footer_token_total": 10000,
      "footer_token_per_rep_median": 2000,
      "admin_api_snapshot": {
        "status": "captured",
        "vendor": "anthropic",
        "pre_snapshot": {
          "polled_at": "2026-04-06T17:55:00.000Z",
          "bucket_start": "2026-04-06T17:00:00Z",
          "bucket_end": "2026-04-06T18:00:00Z",
          "input_tokens": 0,
          "cache_read_input_tokens": 0,
          "cache_creation_input_tokens": 0
        },
        "post_snapshot": {
          "polled_at": "2026-04-06T18:10:00.000Z",
          "bucket_start": "2026-04-06T18:00:00Z",
          "bucket_end": "2026-04-06T19:00:00Z",
          "input_tokens": 450000,
          "cache_read_input_tokens": 0,
          "cache_creation_input_tokens": 0
        },
        "delta": {
          "input_tokens": 450000,
          "cache_read_input_tokens": 0,
          "cache_creation_input_tokens": 0
        },
        "lag_waited_s": 300
      },
      "evidence_source_used": "vendor_admin_api",
      "threats_to_validity_acknowledged": ["network_jitter", "tui_warmup_cancels_out_against_A"]
    }
  ],
  "summary": {
    "scenarios_completed": ["A", "B", "C"],
    "scenarios_pending": ["D1", "D2", "D3", "D4", "E"],
    "comparisons": [
      {
        "left": "A",
        "right": "C",
        "left_median_s": 12.4,
        "right_median_s": 12.1,
        "ratio": 0.976,
        "iqr_overlap": true,
        "verdict": "not_distinguishable_from_noise"
      }
    ]
  }
}
```

**Field semantics:**

- All timestamps are ISO-8601 UTC with millisecond precision (`YYYY-MM-DDTHH:MM:SS.sssZ`).
- All durations are in seconds, floating point (`duration_s`, `latency_s`, `median_s`, etc.).
- `pre_state` and `post_state` are the raw string captured from the tool's status command (`/context`, `/stats session`, `/status`) at that moment, with ANSI escape sequences stripped. If state was not captured at a particular operation, the field is `null`.
- `notes` is free-text human-readable context for the operation.
- `primary_latency_s` is the question-step latency for that repetition (the value used in `stats`).
- `cache_field_matches` is a list of objects each with `keyword`, `surrounding_line`, `source_operation`, recording any cache-related keyword found in any captured state during that repetition.
- `footer_pre` and `footer_post` are the raw strings captured from a tool's status footer (when available) immediately before and after an operation. Currently populated only by the Gemini test script, which captures Gemini CLI's configurable footer via `tmux capture-pane`. The string is the header line followed by the value line, ANSI-stripped, joined by a newline. When footer capture is not configured or fails, the field is `null`.
- `tokens_delta` is the per-operation token delta computed from `footer_post` minus `footer_pre`'s parsed `token-count` value. Currently populated only by the Gemini test script. When footer capture is unavailable, the field is `null` rather than `0`. A value of `0` means the footer captured both endpoints but the model consumed zero tokens during the operation (rare; usually indicates a parse anomaly worth investigating).
- `footer_token_total` is the per-scenario sum of `tokens_delta` across every `question` operation in every repetition of the scenario. This is the framework's measured per-scenario input+output token consumption derived from the configurable footer. Currently populated only by the Gemini test script. When footer capture is unavailable for the scenario, the field is `0`.
- `footer_token_per_rep_median` is the median `tokens_delta` across the scenario's repetitions, computed from the question operations only. Useful for spotting outlier reps. May be `null` if no reps produced a non-zero delta.
- `admin_api_snapshot` is a per-scenario block recording the vendor admin API polling result. Its `status` field is one of `captured` (admin key was provided, snapshots were taken before and after the scenario, deltas were computed), `no_key_provided` (operator did not pass an admin key, so the script gracefully degraded), `vendor_capability_gap` (the tool's vendor does not expose an admin API; this is the only valid value for the Gemini script), `lag_exceeded` (admin key was provided and snapshots were attempted, but the post-snapshot did not show updated counts within the configured aggregation lag), or `error` (the script encountered an error contacting the admin API; the error message is recorded in a `notes` subfield). When `status == "captured"`, the block also includes `vendor` (which admin API was polled), `pre_snapshot` and `post_snapshot` (each with `polled_at`, `bucket_start`, `bucket_end`, and the cached/uncached token counts the API returned), `delta` (post minus pre, the same shape as the snapshots' token-count fields), and `lag_waited_s` (how long the script waited between scenario completion and the post-snapshot).
- `evidence_source_used` is one of `vendor_admin_api`, `http_debug_capture`, `status_footer_tokens`, `status_command_field`, `wall_clock_latency` and identifies the strongest evidence source from Section 8.2.5 that produced any non-null data for the scenario. The assignment rule is: (1) if `admin_api_snapshot.status == "captured"` and the delta block contains non-zero token counts attributable to the scenario, the scenario gets `vendor_admin_api`. (2) Otherwise, if any repetition's HTTP debug capture parsed at least one cache-related field from API response bodies, the scenario gets `http_debug_capture`. (3) Otherwise, if `footer_token_total > 0` (the configurable-footer evidence path produced non-zero per-operation token deltas), the scenario gets `status_footer_tokens`. This tier is currently Gemini-specific. (4) Otherwise, if any repetition's `cache_field_matches` array is non-empty (i.e., the keyword search found a hit in status command output), the scenario gets `status_command_field`. (5) Otherwise, the scenario gets `wall_clock_latency` (the fallback). Each scenario records exactly one value; the strongest evidence source wins.
- `threats_to_validity_acknowledged` is a list of strings naming the specific confounders the script considered for that scenario (drawn from the catalog in Section 8.2.4).

**Cache keyword list (canonical).** The `cache_field_matches` keyword search uses the following exact list of strings, case-insensitive, matched against captured state strings line by line. Implementers MUST use this list verbatim so that all three scripts produce comparable hit counts:

- `cache_read_input_tokens`
- `cache_creation_input_tokens`
- `cached_tokens`
- `cached_input_tokens`
- `cache_control`
- `cache_read`
- `cache_write`
- `cache_creation`
- `cache_hit`
- `cache_miss`
- `cache_ttl`
- `prompt_cache`
- `cached_input`
- `ephemeral` (Anthropic's `cache_control: {type: "ephemeral"}` marker)
- `cachedContent` (Gemini's explicit cache object name)
- `implicit_cache` (Gemini documentation term)
- `cache` (catch-all; matches any of the above plus any other cache-prefixed field)

When a keyword match is found, the script records the matched keyword (the exact string from the list above), the full surrounding line of text from the captured state where the keyword was found, and the operation name (`launch`, `load`, `question`, etc.) the capture came from. Multiple keywords matching on the same line each produce one entry.

**Cross-invocation merge semantics.** When a script is invoked a second time with `--scenario D2` (or similar) and the output directory already contains a `results.json` from a prior invocation, the script appends the new scenario to the existing `results.json` rather than overwriting. The append is keyed by scenario name: if the new scenario name already exists in the file, the prior entry is replaced; otherwise the new entry is added to the `scenarios` array. The script atomically rewrites the file (write to `results.json.tmp`, then rename) to avoid leaving a partial file on crash.

**Schema versioning.** The `schema_version` field is currently `"1"`. Any incompatible schema change in a future revision must increment this field; analysts reading the file should reject unknown schema versions rather than mis-parse them.

#### 8.3.2 State Capture Mechanics

Each tool exposes a status command that the scripts use as the secondary evidence source. The capture mechanics are tool-specific and must follow the established patterns from `probe.py` and the existing test scripts in the repository. An implementer must NOT re-derive these patterns; they should be reused.

**Claude Code (`/context`).** Send `/context` via `tmux send-keys` (not paste-buffer, because `/context` is a CLI command, not a model prompt). Wait 5 seconds for the dialog to render. Capture the tmux pane via `tmux capture-pane -t <session> -p` (no `-S` scrollback flag). Strip ANSI escape sequences. Find the line containing `Used: ` and extract the token figures. Dismiss the dialog if needed (typically by sending `Escape`). The reference implementation pattern is in `probe.py`'s context capture code (around line 555 of `probe.py`); the test scripts should call equivalent code or directly import the helpers if they are factored out.

**Gemini CLI (`/stats session`).** Send `/stats session` via `tmux paste-buffer` (because Gemini CLI's input field requires paste-buffer for reliable delivery, per the `test-gemini.py` validation). Wait 5 seconds for the panel to render. Capture the tmux pane. Strip ANSI escape sequences. Parse the panel for the per-model rate-limit usage rows, the session ID, and any unrecognized fields. Dismiss the panel if needed.

**Codex CLI (`/status`).** Send `/status` via the input mechanism the Codex driver (Section 8.6.0) determines is reliable for Codex CLI. Wait 5 seconds. Capture the tmux pane. Strip ANSI escape sequences. Parse the known fields (context window percentage, used/total tokens, 5-hour rate limit, weekly rate limit) and record any unrecognized fields.

For all three tools, the captured raw string is stored in the JSON `pre_state`/`post_state` fields without parsing. Parsing is done in the comparison step, so that the JSON preserves all original information for offline re-analysis.

#### 8.3.3 Latency Measurement

The "question latency" (the primary measurement) is defined as the wall-clock interval between two events:

- **Start:** the moment after the script has finished delivering the question prompt to the tool's input field. For paste-buffer delivery, this is immediately after the `tmux send-keys Enter` that submits the pasted content. For send-keys delivery, it is immediately after the corresponding `tmux send-keys` call.
- **End:** the moment when the captured-response file written by the model becomes stable. "Stable" means: the file exists, its size has not changed for at least 2.0 seconds (measured by polling at 0.5-second intervals). These thresholds match `probe.py`'s `STABLE_CHECKS` and `RESPONSE_POLL` constants.

Timestamps for both endpoints are recorded with millisecond precision using the system monotonic clock (`time.monotonic_ns()`). The system wall clock is also recorded for the JSON output, but the duration calculation uses the monotonic clock to avoid clock-skew issues.

Both endpoints are observable from outside the tool process. The framework does not depend on any "model done responding" signal from the tool's TUI, which is essential because none of the three tools surface such a signal cleanly.

#### 8.3.4 Cleanup and Crash Recovery

**On normal exit:** the script terminates every tmux session it created (matched by name prefix `cache-test-<tool>-<timestamp>-...`). Vendor session storage created by the script (Claude renamed sessions, Gemini save tags, Codex session UUIDs) is **not** automatically deleted on normal exit, because cross-invocation Scenario D depends on it. The script writes the list of created vendor session identifiers to `results.json` so that a separate cleanup pass can remove them later.

**On crash mid-scenario:** the script's `results.json` writer uses an atomic write (write to `results.json.tmp`, fsync, rename to `results.json`) on every state-change event so that a partial scenario can be detected on the next invocation. On the next invocation, if the script finds an in-progress scenario in `results.json` from a prior crash, it logs a warning, marks the scenario as `crashed: true`, and starts a new repetition series for that scenario rather than trying to resume mid-series.

**`--cleanup` flag.** Each script supports a `--cleanup` flag that does no measurement but iterates over the vendor session identifiers recorded in a specified `results.json` and removes them (per-tool: Claude does nothing automatic and warns the operator, Gemini issues `/resume delete <tag>` for each save tag, Codex deletes session UUIDs from `~/.codex/sessions/`). The `--cleanup` flag does not delete the `results.json` itself or the captured pane snapshots; those are output artifacts the operator decides when to archive.

**Tmux session naming.** All tmux sessions created by the scripts are named with the prefix `cache-test-<tool>-<timestamp>-<purpose>` so that they are easy to identify and bulk-clean if needed. The `--cleanup` flag also kills any tmux sessions matching this prefix that were left running by an earlier crashed invocation.

#### 8.3.5 Cross-Invocation Scenario State

Scenario D requires waits up to 25 hours, which exceed the practical lifetime of a single script invocation. The scripts support being invoked multiple times to accumulate Scenario D's sub-scenarios; each invocation handles one sub-scenario.

State is persisted in a file named `scenario-state.json` in the same output directory as `results.json`. The state file records:

- The output directory's identity (so the script can verify it was invoked against the correct directory).
- The vendor session identifier of the checkpoint created in Scenario D's setup phase (the checkpoint that all D sub-scenarios restore from).
- The wall-clock timestamp at which the checkpoint was created.
- A list of which sub-scenarios (D1=1min, D2=6min, D3=65min, D4=25hr) have been completed and which are still pending.
- The fixture SHA-256 from the original invocation, used to verify that subsequent invocations are working against the same fixture.

A typical Scenario D workflow:

1. Operator invokes `./test-cache-<tool>.py --scenario D --setup` once. The script creates the output directory, creates the checkpoint, records the checkpoint identifier and creation timestamp in `scenario-state.json`, and exits.
2. Operator schedules four follow-up invocations at the appropriate wait offsets, each with `--scenario D1`, `D2`, `D3`, or `D4` (or a single `--scenario D --resume` that the script translates to whichever sub-scenario the wait offset implies). Each follow-up invocation reads `scenario-state.json`, verifies it is at the correct wait point, runs the restoration and question against the original checkpoint, and updates `results.json` with the new measurements.
3. After the final follow-up, the operator may invoke `--cleanup` to remove the vendor session identifier the setup phase created.

If an operator invokes the script with a wait that has already been completed (`scenario-state.json` shows D2 already done), the script logs a warning and reruns the sub-scenario, replacing the prior measurement.

#### 8.3.6 Cost Discipline

Each scenario invocation consumes vendor quota. The scripts handle cost in two ways: pre-run estimation and runtime monitoring.

**Pre-run estimation.** Before starting a measurement series, the script computes an upper-bound token cost estimate assuming no caching (the conservative case). The estimate has two contributions:

1. **Load tokens** — the size of the source content the canonical fixture's tier-1 load instruction causes the tool to read into context. Against the framework's pinned Gastown corpus this is approximately 90,000 tokens (the "tier 1" target documented in `config.env`). The script may use this as a constant or compute it from the actual file sizes that the tier-1 load instruction's file list refers to (chars / 4 approximation).
2. **Question tokens** — the size of `QUESTION_A` and `QUESTION_B` prompt strings themselves, computed as `chars / 4`. These are small (a few hundred tokens each) compared to the load tokens.

The total upper-bound estimate is `(load_tokens + question_tokens) × repetitions × scenario_count`, expressed in input tokens, with the assumption that every request pays full input cost. If the tool exposes a per-token billing rate at the operator's account tier, the script may also print a USD upper bound; otherwise the token count alone is the estimate.

The script prints the estimate and prompts the operator to confirm before proceeding. The `--yes` flag skips the prompt for non-interactive use. The estimate is intentionally conservative (it assumes every request pays full input cost) because the script does not know the cache behavior it is trying to measure.

**Runtime monitoring.** The script does not attempt to detect rate-limit responses programmatically — none of the three tools surface rate-limit conditions through a stable, parseable interface. Instead, the script relies on the operator to monitor the tool's status command output between scenarios and to abort the script (Ctrl-C) if a rate limit is approaching. The atomic write of `results.json` ensures that a Ctrl-C does not corrupt the output file.

If a future revision of the framework adds reliable rate-limit detection for any tool, the scripts should be updated to use it; until then, manual operator monitoring is the documented expectation.

### 8.4 Scope and Standalone Status

The three test scripts in Sections 8.5, 8.6, and 8.7 are **standalone**: they do not depend on `probe.py`, are not invoked from `probe.py`, and do not share session state with `probe.py`. They share only the canonical fixture (Section 8.2.1) and the established tmux/paste-buffer/file-watching patterns (referenced from `probe.py`'s implementation). An implementer building the scripts may either copy the relevant helper functions from `probe.py` or import them as a Python module if they are refactored into one.

Each script accepts `--dangerous` (or the equivalent per-tool flag-passing) to enable the tool's permission-bypass mode, matching `probe.py`'s convention. The test scripts hit the same vendor cost surface as `probe.py` and should be treated by operators with the same caution.

### 8.5 Claude Code Caching Verification

#### 8.5.1 Documentation Review Checklist

Resolve the following by reading vendor materials. None of these require running a Claude Code session.

1. Read Claude Code release notes for `2.1.92` and surrounding versions. Look for any mention of automatic cache marker handling, cache TTL choices, or cache visibility surfaces. Record findings (including "no mention found") in the lexicon's Section 2.8.
2. Read the Claude Code slash command reference. Confirm whether `/context` is documented as displaying cached vs. uncached tokens, or only the combined total. Confirm whether any other slash command (e.g., `/cache`, `/debug`, `/stats`) surfaces caching state.
3. Read the `@anthropic-ai/sdk` documentation that Claude Code is built on. Confirm whether the SDK has an automatic-caching mode, and whether Claude Code is documented as enabling that mode.
4. **Best-effort** source inspection: if the published Claude Code source is human-readable (the npm artifact `@anthropic-ai/claude-code` may be transpiled or minified), search it for `cache_control` references. Record the result as one of: found-and-readable, found-but-minified, not-found, or source-not-available. This step is best-effort because the published artifact's readability is not guaranteed.
5. Read the Anthropic prompt caching API documentation for the cache TTL options the API supports. Record the default and extended TTL values, the cache write premium, and the cache read discount.
6. Determine whether `ANTHROPIC_LOG=debug` or `claude --debug` produces output that includes cache-related fields from API responses. This determines whether Section 8.2.5's HTTP debug capture evidence source is available for Claude. Look specifically for SSE event frames (`event: message_delta`, `event: message_stop`) with `usage` blocks containing `cache_read_input_tokens` and `cache_creation_input_tokens`.
7. **Verify Anthropic Admin API access.** Read the Anthropic Admin API documentation and identify the usage reporting endpoint that returns cached vs uncached input token counts (the framework's strongest evidence source per Section 8.2.6). Record the endpoint URL, the request shape (query parameters for time range and bucket width), the authentication header format, the response field names (`input_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`), and the typical aggregation lag. Determine how an operator provisions an Admin API key (separate from the regular `ANTHROPIC_API_KEY`).

#### 8.5.2 End-to-End Test Script: `test-cache-claude.py`

A Python script located at `test-cache/claude/test-cache-claude.py` (per the framework's per-tool folder convention) and invoked as `./test-cache/claude/test-cache-claude.py --scenario A|B|C|D|E [--wait <minutes>] [--repetitions N] [--model <name>] [--dangerous] [--yes] [--cleanup] [--setup]`. The script produces a structured output artifact under `test-output/cache-claude-<timestamp>/`.

**Reference implementations to copy from:**

- `test-fork.py` for the Claude fork-and-rename pattern (Scenarios C, D, E)
- `test-checkpoint.py` for the Claude checkpoint creation and restoration pattern
- `probe.py` (around line 197 for the paste-buffer pattern, around line 555 for the `/context` capture pattern, around line 232 for the rewind key sequence)

The implementer should not re-derive these patterns; they are fragile and have been validated against the pinned version.

**Per-tool state reset for Scenario B.** Claude Code's per-turn undo is the `Esc Esc Enter Enter` rewind key sequence (`probe.py` line 232 reference). Scenario B uses this to return the conversation to the post-load state between the two question asks. The script should verify the rewind landed correctly by capturing `/context` after the rewind and confirming the token count matches the post-load state. If the rewind cannot be confirmed, the script falls back to using `QUESTION_B` as the second ask (per Section 8.2.2's fallback) and records `notes: "rewind unverified, used variant question"` for that scenario.

**Per-tool checkpoint creation for Scenarios C, D, E.** Claude Code creates a checkpoint via the sequence: launch a new tmux session running `claude --resume <session-name> --fork-session --dangerously-skip-permissions --model <model>`, send `/rename <checkpoint-name>` via paste-buffer, send `/exit` via paste-buffer, kill the tmux session. The checkpoint persists on disk in Claude's session directory and can be resumed later by name. The reference implementation is in `test-fork.py` and `test-checkpoint.py`.

**Per-tool checkpoint restoration for Scenarios C, D, E.** Claude Code restores a checkpoint by launching a fresh tmux session running `claude --resume <checkpoint-name> --dangerously-skip-permissions --model <model>`. The first interaction with the resumed session is the question (no further setup is needed inside the resumed session).

**Admin API integration.** The script accepts `--anthropic-admin-key <key>` (or reads `ANTHROPIC_ADMIN_API_KEY` from the environment). When provided, the script uses the key only for polling the Anthropic Admin API's usage reporting endpoint per Section 8.2.6. Snapshots are taken before and after each scenario series; the script waits the configured aggregation lag (default 300 seconds, configurable via `--admin-api-lag-s`) before taking the post-snapshot. Snapshot data is recorded in each scenario's `admin_api_snapshot` block. The admin key is never logged to any captured artifact; the script must explicitly redact it from any debug output. If the admin key is not provided, the script records `admin_api_snapshot.status: "no_key_provided"` and continues with the lower-tier evidence sources.

**Scenario script flow:**

1. **Preconditions check.** Verify `claude` is on PATH; verify version is `2.1.92` (warn if different); verify the fixture file exists; verify the operator's API credentials are available (presence of `ANTHROPIC_API_KEY` env var or successful no-op `claude --version`).
2. **Output directory setup.** Create `test-output/cache-claude-<timestamp>/`. Initialize `results.json` with the schema from Section 8.3.1, populating `tool`, `tool_version`, `model`, `fixture`, `config`, `started_at`. Compute and record `fixture.source_sha256`.
3. **Cost estimate and confirmation.** Compute the upper-bound estimate per Section 8.3.6; print it; prompt for confirmation unless `--yes` is set.
4. **Run the requested scenario(s).** Each scenario runs its measurement series of N repetitions. Each repetition records its `operations` array, computes its `primary_latency_s`, runs the cache field search on its `pre_state`/`post_state` captures, and appends to the scenario's `repetitions` array in `results.json` via atomic write.
5. **Compute scenario stats.** After all repetitions complete, compute the `stats` block (median, IQR, etc.) and the cross-scenario `comparisons` in `summary`.
6. **Generate `comparison.md`.** Render a human-readable derivative of `results.json` containing per-scenario stats tables and the comparison verdicts.
7. **Cleanup tmux sessions.** Kill all tmux sessions created during the run. Record any vendor session identifiers (renamed Claude sessions) in the cleanup list.

**Pass/fail criteria (lexicon items closed):**

- **Section 2.8 "Whether `/context` distinguishes cached from uncached tokens"** is closed when the script's cache field search runs against captures from at least 5 scenarios with N≥5 repetitions each, and the search either finds a match (in which case Section 2.8 is updated to reflect the field) or reports no match (in which case Section 2.8 is updated to "Verified: `/context` does not distinguish").
- **Section 2.8 "Whether Claude Code applies caching automatically"** is closed when Section 8.5.1 doc check #3, #4, and #6 have been completed and the answers recorded, OR when the script's HTTP debug capture (Section 8.2.5 primary evidence) finds cache fields in the captured stream.
- **Section 2.8 "Operator-reported behavior: forks may not inherit the parent's cache"** is closed when Scenario E's measurements either confirm the report (Scenario A and Scenario C medians differ by less than 30% with overlapping IQR) or refute it (medians differ by more than 30% with non-overlapping IQR). The verdict is recorded in `results.json` and propagated to the lexicon.
- **Section 6 caching rows for Claude** are updated with the measured behavior, replacing the current "operator-reported, framework-unmeasured" labels.

**Expected output artifact:**

```
test-output/cache-claude-<timestamp>/
  results.json                           # Authoritative structured results
  scenario-state.json                    # Cross-invocation state (Scenario D only)
  comparison.md                          # Human-readable derivative of results.json
  panes/
    scenario-A-rep0-launch.txt           # tmux pane snapshots, one per operation
    scenario-A-rep0-load.txt
    scenario-A-rep0-question.txt
    ...
  debug/                                 # Optional, populated if HTTP debug capture worked
    scenario-A-rep0-anthropic-log.txt
    ...
```

### 8.6 Gemini CLI Caching Verification

#### 8.6.1 Documentation Review Checklist

1. Read Gemini CLI release notes for `0.36.0` and surrounding versions. Look for any mention of explicit cached-content API usage, cache statistics in `/stats session`, or save-point cache preservation guarantees. Record findings.
2. Read the Gemini CLI slash command reference for `/stats session`, `/resume save`, `/resume resume`, and any other commands that might surface caching state.
3. Read the `geminicli.com/docs/cli/session-management/` documentation for any mention of caching in connection with session persistence, save points, or cross-process restoration.
4. Read the Gemini API documentation on implicit caching to determine which models in the pinned Gemini CLI version's supported model list are eligible for implicit caching, what the documented minimum cacheable prefix size is for each, and what the documented TTL boundaries are. The TTL boundaries from this step may require adjusting Scenario D's wait buckets for Gemini specifically (the default 1min/6min/65min/25hr buckets are calibrated to Anthropic and OpenAI; Gemini's boundaries may differ).
5. Read any vendor documentation on whether `/resume save` triggers a cache invalidation event (for example, by changing the conversation hash that the implicit caching system uses for prefix matching).
6. Determine whether `gemini --debug` (Section 3.2) or the F12 debug console produces output that includes cache-related fields from API responses. This determines whether Section 8.2.5's HTTP debug capture evidence source is available for Gemini.
7. **Confirm the Gemini admin API capability gap.** Section 8.2.6 records that Google does not expose a programmatic admin or usage API for Gemini that returns cached vs uncached token breakdowns. Re-verify this against current vendor documentation: check the Gemini API reference for any new admin/usage endpoint, check the Google Cloud Billing API documentation for any new cache-related breakdown fields, and check the AI Studio API (if any) for programmatic usage queries. If a new admin-style endpoint has appeared since the lexicon was last revised, document it and update Sections 8.2.6 and 6 accordingly. If the gap remains, the Gemini test script's `comparison.md` must explicitly note that Gemini's results have weaker evidentiary strength than Claude and Codex.
8. **Verify the configurable footer's `ui.footer.items` IDs.** Section 3.8 documents the 10 known item IDs (`workspace`, `git-branch`, `sandbox`, `model-name`, `quota`, `context-used`, `memory-usage`, `session-id`, `code-changes`, `token-count`) and their rendered formats. These were verified against `0.36.0` from operator captures. Confirm against current vendor documentation that the IDs and rendered formats are still accurate, and that no new items have been added that the framework should be aware of. The framework's required-item set in `gemini_driver.REQUIRED_FOOTER_ITEMS` is `token-count`, `context-used`, `model-name`, `session-id`, `memory-usage` — confirm these are still the right items for the framework's measurement needs.
9. **Verify the settings file precedence.** Section 8.2.6 (and the vendor docs at `geminicli.com/docs/reference/configuration/`) state that project-level `.gemini/settings.json` overrides user-level `~/.gemini/settings.json`. The framework's Gemini test script reads only `~/.gemini/settings.json` and never writes to either location. Confirm the precedence model is unchanged in current Gemini CLI versions; if it has changed, the framework's startup verification path may need updating.

#### 8.6.2 End-to-End Test Script: `test-cache-gemini.py`

A Python script located at `test-cache/gemini/test-cache-gemini.py` and invoked as `./test-cache/gemini/test-cache-gemini.py --scenario A|B|C|D|E [--wait <minutes>] [--repetitions N] [--model <name>] [--dangerous] [--yes] [--cleanup] [--setup]`.

**Reference implementations to copy from:**

- `test-checkpoint.py` for the Gemini save-point pattern (`/resume save`, `/resume resume`, `/resume delete`)
- `test-gemini.py` for the Gemini paste-buffer compatibility verification pattern
- `probe.py` (around line 197 for the paste-buffer pattern; the Gemini-specific save/restore logic in `probe.py`'s `gemini_save` and `gemini_restore` methods)

**Per-tool state reset for Scenario B.** Gemini CLI's per-turn undo is the `Esc Esc` rewind picker (Section 3.5). Whether this reliably resets to a clean state for automation use is unverified by the framework; the safer Gemini-specific approach is to use `/resume save pre-question; <ask>; /resume resume pre-question; <ask>` — i.e., create a save point at the post-load state, ask the question, restore the save point (which discards the question and its answer), ask the question again. This reset mechanism is specific to Gemini and is the recommended approach for Scenario B.

**Per-tool checkpoint creation for Scenarios C, D, E.** Gemini CLI creates a checkpoint via `/resume save <tag>` (in-process). The save tag persists in the tool's session storage. The framework's reference implementation is in `probe.py`'s `gemini_save` method, which uses the delete-first pattern documented in Section 3.4 to handle overwriting existing tags.

**Per-tool checkpoint restoration for Scenarios C, D, E.** For same-process restoration: `/resume resume <tag>`. For cross-process restoration (which Scenario C explicitly tests for Gemini, since Gemini's save points were until recently believed to be in-process only): launch a fresh `gemini --resume <index>` process to resume the original session, then `/resume resume <tag>` to restore the save tag inside the resumed session.

**Choosing the `--resume <index>` value.** Gemini CLI's `--resume` flag accepts an integer index referring to a session in the current project's session list (with index `1` being the most recent). The script's default is to use the literal string `latest` (Gemini CLI's documented alias for "most recent session in this project") if it works against the pinned version, falling back to integer `1` if not. The script may accept an `--index <n>` override flag for operators who need to disambiguate against host-side session noise (other Gemini CLI sessions running in the same project directory). The chosen index value is recorded in the scenario's `parameters` block of `results.json` so that an analyst can verify which session was restored.

**Gemini-specific dependency:** Scenario C and Scenario D both depend on Gemini cross-process save tag persistence, which is currently labeled "Empirically unverified" in Sections 3.3, 3.12, and 6 — the open question of whether `/resume save` tags survive a `gemini` process restart and remain restorable in a fresh process via `gemini --resume <index>`. The script must run a fail-fast check before treating Scenario C/D measurements as meaningful: after launching a fresh `gemini --resume <index>` and issuing `/resume resume <tag>`, the script issues a verification probe (a question whose answer can only come from the originally loaded source content) and confirms the answer is correct. If the verification probe fails, the script records the failure in `results.json`, marks Scenario C/D as `verification_failed: true`, and declines to compute meaningful cache statistics for those scenarios. The success of this fail-fast check is itself the resolution of the lexicon's open question on Gemini cross-process persistence.

**Admin API integration: not applicable (capability gap).** Per Section 8.2.6, Google does not expose a programmatic admin or usage API that returns cached vs uncached token breakdowns for Gemini. The Gemini test script does not accept any admin key flag and records `admin_api_snapshot.status: "vendor_capability_gap"` in every scenario. The Gemini script's `comparison.md` deliverable must explicitly include a paragraph noting that Gemini's cache verification rests on lower-strength evidence sources compared to Claude and Codex which can use the admin API path. This asymmetry must be visible to anyone reading the cross-tool comparison.

**Configurable footer integration (the framework's primary Gemini cache evidence source).** Per Section 3.8 and Section 8.2.5 evidence tier #3, Gemini CLI exposes a configurable footer at `~/.gemini/settings.json` under `ui.footer.items`. When the operator has enabled `token-count` and the framework's other required items, the script captures the rendered footer via `tmux capture-pane` immediately before and after every operation, parses out the per-operation token deltas, and aggregates them per-scenario into `footer_token_total`. This is the framework's strongest available evidence source for Gemini, given Google's admin API capability gap.

**Footer verification (fail-fast at startup).** The script reads `~/.gemini/settings.json` at startup and verifies that `ui.footer.items` contains every entry in `gemini_driver.REQUIRED_FOOTER_ITEMS` (`token-count`, `context-used`, `model-name`, `session-id`, `memory-usage`). If any required item is missing, the script prints a copy-paste-friendly error message containing the JSON snippet the operator should add, and exits non-zero. The script does **not** modify the operator's settings file under any condition. If the settings file is missing, malformed, or has no `ui.footer.items` array, the same error path applies. The operator can include additional footer items beyond the required set; the verifier ignores extras.

**Footer capture per operation.** For every `question` operation (and potentially `load` operations in future revisions), the script calls a `safe_capture_footer()` helper that captures the tmux pane via `drv.capture_footer()`, parses it via `drv.parse_footer()` using the operator's `ui.footer.items` order (cached at startup), and stores both the raw and parsed forms on the operation record as `footer_pre` / `footer_post` plus a computed `tokens_delta`. The capture is non-fatal: if it fails for any reason, the operation still runs and the footer fields are recorded as null or empty. The aggregated per-scenario `footer_token_total` is computed in `build_scenario()` from each rep's question operation.

**Token-count hidden case.** Gemini's footer hides the `token-count` column entirely when the session token count is zero (which is the state at session start, before any model interaction). The parser detects this by comparing the number of value-line columns to the number of items in `ui.footer.items`; if it's exactly one fewer, the parser assumes `token-count` is hidden and treats its value as `0` rather than as a parse failure. This makes pre/post deltas compute correctly when the pre-snapshot was taken before any model interaction.

**Tmux pane width.** The framework's drivers all launch tmux sessions with explicit `-x 220 -y 50` geometry (per `gemini_driver.TMUX_PANE_WIDTH`). The default tmux new-session pane width of 80 columns is too narrow for Gemini's full configurable footer; 220 cols is strictly wider than the operator's typical interactive terminal (~188 cols) so the captured pane is a superset of what the operator sees in their interactive shell. If the operator has configured very long workspace paths or unusual footer content, the pane width may need to be increased.

**Scenario script flow:** identical structure to Section 8.5.2 with the per-tool mechanics above substituted in. The script writes `results.json` with the schema from Section 8.3.1, runs the requested scenarios with N≥5 repetitions, captures `/stats session` and the configurable footer before and after each operation, runs the cache field search and the footer parser, and produces `comparison.md`.

**Pass/fail criteria (lexicon items closed):**

- **Section 3.9 "Whether `/stats session` reports cache hit rates"** is closed when the script's cache field search has run against captures from at least 5 scenarios with N≥5 repetitions and either found cache field names or definitively not found them.
- **Section 3.9 "Whether Gemini CLI uses caching automatically"** is closed when Section 8.6.1 doc check #1, #2, and #6 have been completed and the answers recorded.
- **Section 3.9 "Operator-reported behavior: save points may be cache-friendly"** is closed when Scenario E's measurements confirm or refute the report under the effect-size threshold from Section 8.2.3.
- **Section 6 row "Empirically unverified" for Gemini cross-process persistence** is closed when Scenario C/D's fail-fast verification probe succeeds in a fresh process at least once. (This is a separate question from caching, but it is verified as a side effect.)
- **Section 6 caching rows for Gemini** are updated with the measured behavior.

**Expected output artifact:** same shape as Section 8.5.2's, with `panes/` containing `/stats session` captures.

### 8.7 OpenAI Codex CLI Caching Verification

#### 8.7.1 Codex Driver Prerequisite

The framework's reference implementation does not currently drive Codex CLI in any capacity. Before `test-cache-codex.py` can be built, a basic Codex driver must exist and be validated. The driver is a separate deliverable from the cache test script, and a build agent assigned to the test script must not assume the driver exists.

**Driver deliverable specification:**

The driver is a Python module (suggested location: `test-cache/codex/codex_driver.py`) exposing the same kinds of helpers that `probe.py` provides for Claude and Gemini, scoped to Codex. The driver must implement and verify the following capabilities against `codex-cli 0.118.0`:

1. **Launch.** A function that starts `codex` in a tmux session with the appropriate flags (`--dangerously-bypass-approvals-and-sandbox` for non-interactive automation, `--model <name>`, `-C <working-dir>`).
2. **Input delivery.** A function that delivers a multi-paragraph natural language instruction to the running Codex process. The function must verify byte-faithful delivery against the established framework requirement (the same property `paste-buffer` provides for Claude and Gemini). Whether `tmux paste-buffer` works for Codex is unverified — the driver must test it and either use it or document why an alternative was needed. Reference: `test-gemini.py` is the template for this verification, which originally established that `paste-buffer` works for Gemini and that `send-keys Enter` does not.
3. **Completion detection.** A function that waits for a captured-response file to appear and stabilize, matching the existing framework convention from `probe.py`'s `wait_for_file` function (file exists, size unchanged for at least 2.0 seconds at 0.5-second polling).
4. **Status capture.** A function that issues `/status` to the running Codex process, captures the rendered panel from the tmux pane, strips ANSI escapes, and returns the raw string. The function must handle whatever dismiss key sequence Codex's `/status` panel requires (this must be verified during driver development).
5. **Checkpoint creation.** A function that takes a running Codex session and produces a checkpoint identifier (the session UUID, captured from `/status`, that `codex resume` and `codex fork` accept). The function must handle the lifecycle: load content, capture the UUID, terminate the tmux session leaving the session intact in `~/.codex/sessions/`, and return the UUID.
6. **Checkpoint restoration.** A function that takes a checkpoint identifier and launches a fresh `codex resume <id>` (or `codex fork <id>` if forking is being tested) in a new tmux session, returning a handle ready for further interaction.
7. **Cleanup.** A function that takes a list of vendor session UUIDs and deletes them from `~/.codex/sessions/`.

**Driver verification.** Before the driver is considered complete, a separate small test script (suggested name: `test-cache/codex/test-codex-driver.py`, structured analogously to `test-gemini.py`) must verify each of the seven capabilities above against a real Codex session. The driver verification is its own deliverable; only after it passes can `test-cache-codex.py` be built.

**If `tmux paste-buffer` does not work for Codex:** the driver verification script will discover this, and the implementer must document the alternative delivery mechanism in this lexicon (extending Section 4 with the verified input mechanism) and in the driver. If no reliable input mechanism can be found for Codex against the pinned version, that is a capability gap and the cache test work for Codex is blocked until either (a) a future Codex CLI version exposes a reliable input mechanism, or (b) the framework adopts an alternative driving approach (for example, the `codex --remote <ws-addr>` interface from Section 4.1).

#### 8.7.2 Documentation Review Checklist

1. Read Codex CLI release notes for `codex-cli 0.118.0` and surrounding versions. Look for any mention of cache statistics in `/status`, cache-related configuration in `config.toml`, or cache behavior on `codex resume` and `codex fork`.
2. Read the Codex CLI slash command reference for `/status`, `/compact`, `/fork`, and any other commands that might surface caching state.
3. Read the `developers.openai.com/codex/cli/` documentation pages for any mention of caching in connection with sessions, resumption, or forking.
4. Read the OpenAI API model documentation for the list of models the pinned Codex CLI version supports. Record which models have automatic prompt caching, what the documented minimum cacheable prefix size is, and what the cache TTL is for each model class (in particular, which models have the extended 24-hour cache).
5. Read Codex GitHub issue #13738 and any follow-up issues for discussion of how `model_context_window` overrides interact with caching.
6. Inspect the Codex CLI source (`openai/codex` repository, which is open source) for any code paths that read or report cache-related fields from API responses. Unlike the Claude inspection in Section 8.5.1 #4, this is not best-effort: the Codex source is expected to be human-readable.
7. Determine whether `codex debug` or any `-c key=value` debug-level configuration override produces output that includes cache-related fields from API responses. This determines whether Section 8.2.5's HTTP debug capture evidence source is available for Codex.
8. **Verify OpenAI Admin API access.** Read the OpenAI Admin API documentation and identify the organization-level usage endpoint that returns cached vs uncached input token counts (the framework's strongest evidence source per Section 8.2.6). The relevant endpoint is documented as the completions usage endpoint accepting `start_time`, `end_time`, `bucket_width`, `group_by`, `project_ids`, and `model` query parameters. Record the exact URL, the response field names (`input_tokens`, `input_cached_tokens`, etc.), the authentication header format, and the typical aggregation lag. Determine how an operator provisions an OpenAI Admin API key (the `sk-admin-...` prefix indicates a separate key from regular project API keys).

#### 8.7.3 End-to-End Test Script: `test-cache-codex.py`

A Python script located at `test-cache/codex/test-cache-codex.py` and invoked as `./test-cache/codex/test-cache-codex.py --scenario A|B|C|D|E [--wait <minutes>] [--repetitions N] [--model <name>] [--dangerous] [--yes] [--cleanup] [--setup]`. **The script depends on `test-cache/codex/codex_driver.py` from Section 8.7.1; if the driver does not exist, the script must refuse to run rather than half-implement driver functionality inline.**

**Per-tool state reset for Scenario B.** Codex CLI's per-turn undo is the composer-empty `Esc Esc` mechanism with continued `Esc` walking back through the transcript and `Enter` to commit (Section 4.4). Whether this reliably resets to a clean post-load state for automation use is unverified. The safer Codex-specific approach is to use `codex fork <session-id>` to create a fresh branch from the post-load state for each measurement repetition, accepting that this is a more expensive reset than rewind would be but is reliable.

**Per-tool checkpoint creation for Scenarios C, D, E.** Codex creates a checkpoint via `codex fork <session-id>` (cross-process by definition). The session UUID of the source session is captured from `/status` before forking; the new session UUID returned by `codex fork` is the checkpoint identifier.

**Per-tool checkpoint restoration for Scenarios C, D, E.** Codex restores via `codex resume <checkpoint-id>` in a fresh tmux session.

**Admin API integration.** The script accepts `--openai-admin-key <key>` (or reads `OPENAI_ADMIN_API_KEY` from the environment). When provided, the script uses the key only for polling the OpenAI Admin API's organization-level usage endpoint per Section 8.2.6. Snapshots are taken before and after each scenario series; the script waits the configured aggregation lag (default 300 seconds, configurable via `--admin-api-lag-s`) before taking the post-snapshot. Snapshot data is recorded in each scenario's `admin_api_snapshot` block. The admin key (which must begin with `sk-admin-`) is never logged to any captured artifact; the script must explicitly redact it from any debug output. If the admin key is not provided, the script records `admin_api_snapshot.status: "no_key_provided"` and continues with the lower-tier evidence sources.

**Scenario script flow:** identical structure to Section 8.5.2 with the per-tool mechanics above substituted in, plus the explicit dependency check on the Codex driver at startup.

**Pass/fail criteria (lexicon items closed):**

- **Section 4.9 "Whether `/status` reports cached-token counts"** is closed when the script's cache field search has run against captures from at least 5 scenarios with N≥5 repetitions.
- **Section 4.9 "Checkpoint and fork cache effects are unverified"** is closed when Scenarios C and D have produced enough measurements (across runs and across TTL boundaries) to characterize the cache hit rate.
- **Section 6 row for Codex checkpoint cost-efficiency** is updated from "Unverified" to a measured value.

**Expected output artifact:** same shape as Section 8.5.2's, with `panes/` containing `/status` captures.

### 8.8 Outcomes and Lexicon Update Protocol

When all three scripts have been written, executed, and produced their `comparison.md` artifacts, the lexicon must be updated as follows:

1. **Sections 2.8, 3.9, and 4.9** — replace the current "operator-reported / unverified" framing for each tool with the measured behavior. Where the operator report was confirmed, label it as "Verified" with a citation to the test artifact path. Where it was refuted, replace the description with the measured truth and explicitly note that the prior operator report was wrong.
2. **Sections 2.11, 3.12, and 4.12 (verification status)** — move the cache-related items from the "Documented but not exercised" or "Unverified" categories into the appropriate "Verified empirically by the framework's reference implementation" category, citing the `results.json` artifact.
3. **Section 5 cross-tool capability map** — update the four caching-related rows to reflect measured rather than hearsay-based descriptions.
4. **Section 6 capability gap summary** — update the two caching-related rows similarly. Where a tool's caching behavior is now measured, replace "operator-reported" with "Verified."
5. **`DESIGN.prd.md` "Pre-Flight Validation" section and "Open Questions and Known Gaps" section** — update or remove the open question on cost estimation as appropriate based on what the test scripts revealed about how cost can be predicted. Quote the actual section titles rather than relying on numbers, since DESIGN.prd.md numbering may drift.
6. **The pinned versions table at the top of this lexicon** — advance the "Last verified" date for each tool whose caching script was executed.

The verification work in Section 8 is considered complete for a tool when its `comparison.md` exists, its lexicon entries (2.8/3.9/4.9, 2.11/3.12/4.12, the rows in 5 and 6) reflect the measurements, and the operator reports that previously appeared in the lexicon as hearsay are either confirmed or refuted with evidence.
