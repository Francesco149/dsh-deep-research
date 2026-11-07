# Layouts: servers, lanes, concurrency

The wizard renders everything from one `layout.json`. Examples: `wizard/layouts/single-server.json`,
`reference-lab.json` (two servers, the author's), `three-servers.json` (three local boxes plus a cloud route).

## The file

```jsonc
{
  "profile": "research",              // the dsh profile the wizard creates (keep it separate from your daily one)
  "dsh_home": "~/.dsh",               // $DSH_HOME
  "dsh_install": "~/.local/share/dsh",// the npm prefix with node_modules/@deepseek-ai/dsh (the plugin goes in <it>/plugins)
  "port": 3080,                       // web UI port for the generated systemd unit
  "search": "helper",                 // "helper" (skill/deep-research/scripts/search) or "web_search" (dsh's provider)
  "worker_compaction_ratio": 0.2,     // workers compact at this share of their window (see "Sizing" below)
  "servers": [
    {
      "name": "lame",                 // a-z0-9-; becomes the route name and the tool research_<name>
      "displayName": "...",           // shown in dsh's model picker
      "baseURL": "http://host:8080/v1",
      "model": "qwen3.8-flash-next",  // the id sent in requests (llama-server serves its one model whatever it is)
      "contextWindow": 262144,        // what the SERVER holds (-c), not what the model could
      "maxTokens": 16384,             // output cap per answer, thinking included
      "lanes": 2,                     // subagents on this server at once
      "vision": true,                 // the server reads pictures (frames, page images)
      "thinking": "qwen-chat-template", // or "none" (see below)
      "reasoningEffort": "medium",    // default effort; reasoningEfforts lists the template's levels
      "apiKeyEnv": "OPENROUTER_API_KEY", // optional: a cloud route's key, read from the dsh process environment
      "primary": true,                // orchestrator, critic, writer, compaction summaries (default: longest context)
      "timeoutMs": 1800000,           // a queued request gets no byte until the slot frees: keep these long
      "streamIdleTimeoutMs": 900000,
      "note": "about 70 tokens/s; keeps idle conversations in RAM" // one line the orchestrator reads
    }
  ],
  "laptop": { "enabled": false }      // or {"enabled": true, "transport": "http", "url": "...", "tokenEnv": "CU_TOKEN"}
                                      // or {"enabled": true, "transport": "stdio", "repo": ".../laptop-mcp",
                                      //     "env": {"CU_HOST": "laptop", "CU_AGENT_USER": "agent"}}
}
```

`thinking`:
- `qwen-chat-template`: Qwen 3.x-style reasoning models whose template takes `enable_thinking` and
  `reasoning_effort` in `chat_template_kwargs` (llama.cpp `--jinja`). The wizard also writes a `<name>-nothink`
  twin route for compaction summaries.
- `none`: plain OpenAI-compatible chat with no thinking control (a non-reasoning model, or a cloud API that
  manages reasoning itself). Other reasoning models need a route edited by hand (AGENTS.md step 4).

## Sizing lanes

A lane is one subagent allowed on the server at once. Pick per server:

| the server | lanes |
|---|---|
| one slot (`--parallel 1`), **no** conversation cache | **1**. A second subagent would make every turn switch re-read its whole context |
| one slot **with** a RAM conversation cache (llama.cpp `--cache-ram`, Speedy's `--conversation-cache-mib`) big enough for 2 worker contexts | **2**. The orchestrator gets two tool-call-heavy workers interleaving almost for free |
| N slots, each with KV for a full worker context (e.g. `--parallel 2 -c 2×window`, or vLLM) | **N**, but only if more slots give more total throughput. On a sparse MoE they usually don't (docs/HOW-IT-WORKS.md) |
| a cloud API | what you are willing to pay for at once (3–4 is plenty) |

Rules:
- **Lanes in all ≤ 8.** dsh refuses a 9th live subagent per session, and the wizard refuses such a layout.
- **Workers spend much of their time in tools** (fetching pages, searching), not generating. That is why 2 lanes on
  one slot gain something even without batching: while one worker waits on a page, the other generates.
- **Conversation cache size**: lanes × (worker compaction threshold + headroom) must fit it. On the reference
  boxes: 8 GiB of cache, 2 lanes, workers compact at ~49K tokens. If yours is smaller, lower
  `worker_compaction_ratio` (and the worker budget in `presets/personas/dr-worker.md`) or use 1 lane.

## Common layouts

**One server.** Everything goes through `research_<name>`, including the orchestrator, which is idle while it
waits. Use 2 lanes with a conversation cache, else 1. Expect a run to take about twice as long as on two servers.
The ROCm run in the README ran entirely on one box: 9 subagents, 2.2 h, a 3,281-word report.

**Two servers** (the reference). Primary = the longer context. 2 + 2 lanes with conversation caches. A typical
exhaustive run is 35–40 subagents in 4–8 hours.

**Three or more servers.** One tool per server, with the lanes summing to ≤ 8. Write each server's limits in its
`note`: a server without vision must not get frame-heavy sub-questions, and a small-context one should get fact
checks, not broad research. The orchestrator follows those notes. Critic and writer still go to the primary.

**Mixed local + cloud.** A cloud route is just another server with `apiKeyEnv`. Keep the primary local if you want
the orchestrator, critic and writer (most of the reading) free. Mention the cost in its `note`, so the
orchestrator uses it when the queue is long rather than first. Check the provider: some cloud hosts serve
open-weight models quantized or with tool calling degraded, so pin a provider you trust.

**Different models per server.** Allowed. Every route carries its own model id. Keep the primary on the strongest
model: critic and writer quality decides the report.

## Harder concurrency

**Sharing servers with other work.** The lanes only coordinate *one* orchestrator. Two deep-research runs at once,
or a run plus someone's coding session on the same server, simply queue at the server: correct, but slower and
cache-hostile. Options, from simplest:
1. Run one deep research at a time, and tell the other users.
2. Give each concurrent user their own profile with fewer lanes (e.g. 1 per server each).
3. Put a sticky, queue-aware proxy in front of the servers. Route by conversation: hash the system prompt plus the
   first user message, since dsh sends no session id. Limit queue depth per backend, and place new conversations
   on the least-loaded backend. Point every route at the proxy and keep lanes as the per-session limit. This is
   the only option that scales to many unrelated sessions. It is not included here.

**Exact lanes instead of model-kept lanes.** If your model keeps starting more subagents than the lanes allow, the
fallback is a dsh `workflow` script with deterministic lanes (docs/HOW-IT-WORKS.md "Alternatives"). Flash-Next class
models kept the lanes in every reference run.

**Raising the 8-subagent cap.** `maxActiveSubagents` is a dsh setting of the subagent subsystem. Raising it only
helps if your servers really gain throughput from more concurrent streams. Measure first (llama-bench, or two and
then three concurrent streams with fixed lengths).
