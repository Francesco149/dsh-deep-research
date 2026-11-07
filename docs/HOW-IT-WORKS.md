# How it works

## The pipeline

The user picks the **Deep research** preset for a new session and types `/deep-research <question>`. The skill
(`skill/deep-research/SKILL.md`, rendered for the layout) turns the session's agent into the orchestrator:

1. **Scope.** It restates the question and asks at most three clarifying questions, only those whose answer
   changes the research. "Exhaustive" means 3 rounds, otherwise 2.
2. **Reconnoitre and plan.** A few searches of its own, then `plan.md`: a self-contained brief and 5–10
   non-overlapping sub-questions. There is always one on criticism and counter-evidence and one on the latest
   developments.
3. **Rounds.** One worker per sub-question, run through the lanes (below). Each worker does about 8 searches,
   reads about 8 pages in full, writes `notes/r<round>-<id>.md` as it goes, and returns one JSON object.
   - Pages it could not fetch go into `blocked`. With the laptop configured, a **laptop pass** reads them in a real
     Chrome, in batches of 6, one pass at a time.
   - The orchestrator writes `digest-r<round>.md`.
   - A **critic** reviews the gaps and proposes follow-ups (the next round's sub-questions) and up to 12 key claims.
4. **Fact checks.** One worker per key claim, in fact-check mode: find the primary source and an independent one,
   search for evidence against it, and return a verdict (`confirmed`, `partly` with corrected wording,
   `contradicted`, or `unverifiable`). The verdicts go into `verification.md`.
5. **Report.** A **writer** builds `report.md` a section at a time. The critic reviews it against the notes and
   the verdicts, and the orchestrator sends the issues back to the writer, at most twice.
6. **Hand over.** The orchestrator re-reads the report, checks citations and numbers, and answers with bullets,
   the path, and what remains uncertain.

Everything lands in `<project>/research/<date>-<slug>/`: `plan.md`, `progress.md` (the orchestrator's own state,
which is how it resumes after compaction), `notes/`, `frames/`, `digest-r*.md`, `verification.md`, `report.md`.

## The five agent presets

A dsh agent preset is a persona plus exactly the tool plugins one role needs
(`@deepseek-ai/dsh-agent-preset` rows in the profile patch).

| preset | role | tools | notes |
|---|---|---|---|
| `deep-research` | orchestrator: what the user picks | bash, fs, fs-search, jobs, skills, ask-user, todo, web (search only), compaction, **one delegation tool per server**, `send_message`, `list_agents` | compaction at 0.9 of the window |
| `dr-worker` | one sub-question, or one fact check | bash (the helpers), fs, jobs, web (search only) | **compaction at 0.2** (see below); budget ~30 tool calls in research mode, ~15 in fact-check mode |
| `dr-critic` | gap review; report review | bash, fs **read-only**, web (search only) | runs on the primary server |
| `dr-writer` | writes and revises `report.md` | bash, fs | runs on the primary server; writes in ≤2000-word appends (an answer is capped at 16384 tokens, thinking included) |
| `dr-laptop` | reads a batch of blocked pages in a real Chrome | fs (no edit), **the laptop MCP** | only present when the laptop is configured; the MCP row lives inside this preset, so nobody else pays for ~30 tool schemas |

dsh has no "hidden" flag for presets, so the four `dr-*` presets also appear in the mode picker, labelled
"(subagent)". Picking one for a session gives a crippled agent and does no other harm.

All subagents report with their **final message**: one JSON object, no prose. dsh delivers a child's final text to
the parent as a settlement notice that wakes it. The child does not call a send tool. The orchestrator can
`send_message` a finished child (the writer, for revisions), and the child resumes with its own context.

## Lanes: per-server concurrency the model keeps

dsh's `dsh-tool-subagent` binds one model-facing tool to one LLM route (`agentOptions.provider`). The profile
mounts **one tool per server**, `research_<server>`. Each takes `description`, `prompt` and `agent_preset` (the
child type, limited by `allowedAgentPresets`), and returns `started subagent <id>` at once. Since every call
returns immediately, even one call per turn fans out.

dsh itself caps live children at 8 per session (`maxActiveSubagents`). It has no per-route concurrency, no
load balancing, and no failover between routes. So the **skill** states the lanes: "at most 2 of your subagents
on `research_lame` at once, 2 on `research_ampere`; keep a queue; refill a lane when its notice arrives." Critic
and writer always go to the primary server.

Why lanes and not "start everything":

- A llama.cpp-style server with `--parallel 1` answers one request at a time; the rest wait in its queue. On a
  sparse MoE (10 of 512 experts per token), `--parallel 2+` adds no throughput: the streams almost never share
  experts, so batching saves no expert work. Measured on the reference box: 83 tok/s with one stream, 87 total
  with two, 79 total with three.
- What makes 2 lanes on one slot cheap is the **conversation cache**. When a request for another conversation
  arrives, the idle conversation's KV state is saved to RAM and restored when it comes back. Switching costs about
  1 s instead of re-reading 50K tokens (3 × 16K conversations: 1.0–1.4 s to come back, 99.8% reused). Without it,
  every turn switch re-reads the whole context. A second lane is then pure loss, unless the server has a second
  slot with its own KV.
- Over-subscribing a server does not break anything. It only makes everyone slower, and above 8 live children
  starts fail with `ACTIVATION_LIMIT_REACHED`, which the skill tells the orchestrator to handle.

The orchestrator's own conversation lives on the primary server too, but it is idle while it waits for notices.

### Alternatives that were considered

- **A load-balancing proxy in front of all servers.** A naive one sends one conversation's turns to different
  servers, so every switch re-reads the context. A correct one needs sticky routing by conversation (dsh sends no
  session id, so hash the system prompt plus the first user message), per-backend queues and least-loaded
  assignment: another service in the request path for what two routes and a lane rule already give. Worth it only
  when many unrelated sessions share the servers (docs/LAYOUT.md "Sharing servers").
- **A dsh `workflow` script with deterministic lanes** (`parallel([lane('a'), lane('a'), lane('b')])`, each lane
  looping over a shared queue). This gives exact concurrency without trusting the model. But the workflow
  engine's `agent()` cannot pick a preset (in 0.2.1), so workers would run the orchestrator's persona and tools.
  Worth revisiting if a later dsh adds that.

## Worker compaction

Two workers share each server, and each one's context should fit the server's conversation cache **together with
the other's**. In the first runs the workers grew to ~180K tokens each. A llama.cpp 8 GiB cache cannot hold two of
those, so it evicted one, and every turn switch re-read ~176K tokens (207 s a turn). The fix that shipped has two
parts:

- the worker persona's **budget**: about 30 tool calls in research mode and 15 in fact-check mode, never fetching
  a URL twice;
- **compaction at `thresholdRatio` 0.2**: about 49K tokens on a 256K window, about 43K on 224K.

Findings are on disk in the notes file, so compacting early loses little. Re-tune it for your servers
(`worker_compaction_ratio` in the layout): the target is `lanes × compaction threshold` comfortably below the
cache size.

Compaction summaries for **every** preset go through the primary server's **no-thinking route**. Presets cannot
vary the summarizer by route. A summarizer that thinks spends its output budget on reasoning: one measured session
lost 56 of 64 compactions that way.

## The bounded compaction engine

`plugin/bounded-compaction.mjs` subclasses dsh's `BasicCompactionEngine` and replaces only the summarization call.
The stock engine makes the checkpoint an accumulator: every compaction re-summarizes the previous checkpoint plus
the new history and asks the model to merge them. A model that merges by copying forward grows the checkpoint
until it no longer fits the summarizer's output cap, and from then on **every** compaction fails. Measured: the
checkpoint grew from 9.6k to 94.8k characters over 62 compactions, then the session locked. The plugin gives the
summarizer a hard size budget, accepts a summary cut at the token cap instead of throwing, and trims any
checkpoint deterministically to 24,000 characters, dropping the least load-bearing sections first. The bound holds
whatever the model does.

The plugin must live **inside the dsh install prefix** (`<prefix>/plugins/`). It imports `@deepseek-ai/dsh-*` by
bare specifier, and a profile directory has no `node_modules` to resolve them from.

## The helpers

Workers reach the web through bash, not through dsh's `web_fetch`, which rejects PDFs and cannot say "blocked".
Each helper is a POSIX `sh` wrapper that runs a uv script with PEP 723 inline dependencies. There is no venv to
build: uv makes and caches one on first use.

| helper | does | exit codes |
|---|---|---|
| `fetch URL [--offset N] [--max-chars N] [--full-page]` | a page or PDF as markdown with title, date and final URL (trafilatura, pypdf); pages through long documents | 0 ok, 2 error, **3 `BLOCKED:`** (bot check, 401/403/429, JavaScript-only, login wall, image-only PDF) |
| `frames sheet\|strip ... --out DIR` | what a YouTube video *shows*: storyboard frames as labelled contact sheets, without downloading the video (yt-dlp, Pillow; deno for YouTube's JS) | 3 `BLOCKED:` when there is no storyboard |
| `search QUERY [--engine E] [--timelimit d\|w\|m\|y]` | web search, engines in the order of a blind evaluation, falling through on errors (docs/SEARCH.md) | 1 no results, 2 every engine failed |

When YouTube changes and yt-dlp breaks: `uv cache clean yt-dlp` (the next run fetches the newest release).

## The evidence rules

The personas carry rules that keep a mid-size local model honest:

- A claim without a source the agent actually read is not a finding, and a page it could not load is not a
  source. Quote verbatim. `high` confidence needs the primary source's own words.
- What a video or image **shows** needs frames the agent looked at, cited with their times. A title, description
  or thumbnail only says what the video is *about*. The critic flags such claims, and fact checks look at the
  frames.
- No number without a citation whose source states that number. No estimated percentages.
- Contradicted fact checks never appear as fact. `partly` verdicts use the corrected wording.
- The writer checks that every `[n]` in the body is in the source list and vice versa before reporting back.
