# Troubleshooting: what cost whole runs

Each entry is something that happened on the reference lab, with the fix that shipped.

## A picture the server refuses (WebP)

**Symptom:** a subagent dies with "failed, no closing message". Or the orchestrator's every turn fails with
`400 Failed to load image or audio file`, and keeps failing.

**Cause:** dsh re-encodes a picture bigger than the route's request byte budget (1 MiB) and picks **WebP when the
picture has transparency**. llama-server decodes WebP only through an `ffmpeg` on its `PATH`. Without one it
answers 400. The picture stays in the conversation and is resent with every turn, so **every later turn fails
too**. In one run that took out the orchestrator for an hour (the gap in the README's timeline) and three workers.

**Fix:** put `ffmpeg` on the model server's `PATH` (and ignore SIGPIPE in its service, since the ffmpeg feeder can
hit it). `wizard/setup.py check` sends a PNG and a WebP with alpha to every vision server and fails on a refusal.
The skill also tells the orchestrator to read a failed subagent's real error before re-queueing it, to convert the
offending picture (`magick f.png -background white -flatten f.jpg`), and to never open the original itself.

## Compaction deadlock (the session never shrinks again)

**Symptom:** compactions fail with "summarization truncated at the token cap", "summarization produced no text
summary content" or "summary is not smaller than the shadowed content", then
`400: prompt (N tokens) leaves no room to answer in the context`.

**Causes and fixes** (all in the generated profile):
- The stock engine's checkpoint grows forever on models that merge by copying forward. Fix:
  `plugin/bounded-compaction.mjs` (docs/HOW-IT-WORKS.md).
- The summarizer inherited the route's thinking and spent its output budget on reasoning. Fix: summaries go
  through a **no-thinking route** (`<primary>-nothink`).
- dsh's shipped defaults assume a ≥256K window: `headroomTokens` 65536 makes small windows compact every couple of
  minutes on tiny spans that cannot be summarised profitably. Fix: `headroomTokens: 16384`, `thresholdRatio: 0.9`
  (0.2 for workers).

This only covers the presets the wizard writes. dsh's own **Standard** preset in the same profile still has stock
compaction. Use the Deep research preset for research.

## Turn switches take minutes (cache thrash)

**Symptom:** two workers on one server, and each turn starts with a long prompt read (e.g. 207 s for 176K tokens).

**Cause:** their contexts outgrew the server's conversation cache, so it evicts one on every switch.

**Fix:** the workers' budget plus early compaction (`worker_compaction_ratio`, docs/LAYOUT.md). If the server has
no conversation cache at all (llama.cpp turns `--cache-ram` off when the model is bigger than RAM: look for
`prompt cache disabled` in its log), give it **1 lane**.

## Thinking to `length`

**Symptom:** turns end with finish reason `length` and no tool call, several turns in a row.

**Fix:** a server-side reasoning budget **below** the client's output cap (`--reasoning-budget 8192` against dsh's
`maxTokens` 16384).

## A run stalls with nothing happening

- **Permission prompts:** background subagents cannot answer an approval prompt that nobody sees. Run the
  orchestrator session in a permission mode that does not ask per tool call. Subagents inherit the delegation
  policy.
- **A queued request timed out:** a request waits for the server's slot without receiving a byte. The routes use
  `timeoutMs` 30 min and `streamIdleTimeoutMs` 15 min. A reverse proxy in between with a shorter timeout kills the
  request.
- **A silent subagent:** the skill checks it after 45 minutes with `list_agents` and `send_message`, and gives up on
  it after 15 more.

## The presets don't show up

- **Headless dsh** (`dsh` without the web UI, ACP) composes no agent presets: use the web UI.
- A preset that fails to load is shown as failed, and the others still load: read dsh's log.
- `dsh --profile research --dump-config | grep preset-dr-` shows whether the patch composed at all, without
  starting a server.

## Plugin cannot resolve imports

`bounded-compaction.mjs` imports `@deepseek-ai/dsh-*` by bare specifier, so it must live inside the dsh install
prefix (`<prefix>/plugins/`), next to that prefix's `node_modules`. With `npx` or a global install there is no
stable prefix. Install dsh with `npm install --prefix ~/.local/share/dsh @deepseek-ai/dsh@<version>` and point
`dsh_install` there.

## The Web settings editor ate a preset

The settings editor rewrites the profile patch by entry id. Resetting a row to "inherited" deletes rows left with
only `id` and `name`, and a patch row cannot change an entry's `name`, so the bounded compaction row can silently
revert to stock. **Edit the patch file, or re-run the wizard. Not the UI.**

## Subagent results that aren't JSON

Mid-size models sometimes wrap the final JSON in prose or code fences. The skill accepts that and falls back to
the notes file. Long `write` calls (a whole report in one tool call) are the usual failure point for tool-call
formats, which is why the writer appends one section at a time.

## Laptop clicks miss

Qwen-VL-family and Gemini models may point in normalised 0–1000 coordinates while the laptop expects screenshot
pixels. The laptop-reader persona prefers the text tools (`browser_read`, `browser_find`, `browser_click(i)`).
For a model that points on the 0–1000 grid, set `CU_COORDS=norm1000` (laptop-mcp/README.md).

## After a dsh upgrade

The setup leans on dsh preview APIs: agent presets, `dsh-tool-subagent`'s config (0.2.1 refuses
`persona`/`toolFilter` on the tool itself), `BasicCompactionEngine.summarize()`, and the session file layout
the orchestrator reads errors from (`session.v4.jsonl.zstd`). After upgrading:
1. `dsh --profile research --dump-config` composes;
2. the web UI lists the five presets;
3. a 1-round smoke run completes, and a worker's compaction succeeds (its session shows a compacted summary);
4. `zstdcat <a session>/session.v4.jsonl.zstd | grep '"turn/end"'` still works (else update the path in
   `SKILL.md.tmpl`).
