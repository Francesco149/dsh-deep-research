# Setting up dsh-deep-research: guide for the installing agent

You are setting up the `/deep-research` swarm for DeepSeek Harness (dsh) in **someone else's home lab**. Your job is
to adapt it to their machines rather than copy the author's. This file is the procedure. The reasoning behind each
piece is in `docs/` (read `docs/HOW-IT-WORKS.md` before changing anything structural), and a complete working
example is `docs/reference-lab/README.md`.

## Ground rules

- **Do not touch the user's existing dsh profiles, sessions or skills.** The wizard writes a profile of its own
  (`research` by default) and refuses to overwrite a profile it did not write. Keep it that way. Never edit
  `$DSH_HOME/sessions/`.
- **Secrets never go into a file in this repo or into a profile patch.** API keys and tokens belong in
  `~/.config/dsh/search.env` / `~/.config/computer-use/client.env` (mode 600). Service environments load them,
  and patches reference them by environment variable (`apiKeyEnv`, `!!js process.env.X`).
- **Do not restart, wake, reconfigure or reload a model server without asking.** Inference boxes are often shared
  and slow to load (a 90 GB model takes minutes). Probing them (`/v1/models`, one short chat) is fine.
- **Ask before restarting a dsh instance the user already runs**, and before enabling any systemd unit.
- Builds on small boxes: if you compile anything (an engine, a quant tool), cap its memory (`systemd-run --user
  --scope -p MemoryMax=16G -p MemorySwapMax=0 -- <cmd>` on Linux). A swapless box freezes before the OOM killer acts.
- Tell the user plainly what you could not verify. The wizard's output was checked against dsh 0.2.1-rc.5 by
  composing and booting it, but no install script can be tested on every lab.

## 1. Survey (read-only)

Find out, and write down for the user:

1. **OS and init system.** systemd user services or not (macOS: launchd; WSL: often no systemd).
2. **dsh**: installed where, and which version? The usual install is `npm install --prefix ~/.local/share/dsh
   @deepseek-ai/dsh@0.2.1-rc.5`, so check for `node_modules/.bin/dsh` under that prefix. A global npm install or `npx`
   works for running dsh, but the compaction plugin must sit inside a prefix whose `node_modules` has
   `@deepseek-ai/dsh-compaction-basic` (docs/TROUBLESHOOTING.md "Plugin cannot resolve imports"). If dsh is not
   installed, install it into a prefix, with the user's OK. Note `DSH_HOME` (default `~/.dsh`) and the profiles
   already there.
3. **Local tools**: `uv` (required: the helpers are uv scripts), `zstdcat` (required: the orchestrator reads failed
   subagents' errors with it), `deno` (optional: YouTube frames), ImageMagick `magick` (optional: converting refused
   pictures). Install missing ones with the distro's package manager (Arch: `pacman -S uv zstd deno imagemagick`;
   Debian/Ubuntu: `apt install zstd imagemagick` plus uv's and deno's own installers; Fedora: `dnf`; macOS: `brew`;
   Nix: add them to the environment the dsh service runs in).
4. **Model servers.** For each one: base URL, served model id (`GET <base>/models`), context it actually holds
   (llama.cpp: `GET <host>/props` → `n_ctx`), whether it keeps idle conversations (llama.cpp `--cache-ram`, on by
   default when the model fits in RAM; some forks have a "conversation cache"), how many slots (`--parallel`), and
   whether it has vision (an mmproj). If the user has none yet, stop here and go through `docs/INFERENCE.md` with
   them first. The swarm needs a model that calls tools reliably and holds ≥ 64K context.
5. Whether they want the **laptop MCP** (a spare Windows PC with Chrome for bot-walled pages:
   `laptop-mcp/README.md`). It is optional, and most of the value comes without it.

## 2. Choose the layout with the user

Read `docs/LAYOUT.md`, then propose a layout in a few lines and confirm it with the user. The decisions:

- **Which servers take part**, and which is **primary**: it runs the orchestrator, the critic and the writer. Pick
  the one with the longest context, since critic and writer read every notes file.
- **Lanes per server**: how many subagents may use it at once. 1 for a server with one slot and no conversation
  cache. 2 for one slot plus a RAM conversation cache. N for N slots each with enough KV for a ~50K-token worker.
  Lanes in all must stay ≤ 8 (dsh's live-subagent cap).
- **Worker compaction ratio** (default 0.2 of the window): low enough that `lanes` worker contexts fit the server's
  conversation cache.
- **Search**: the helper (default; Exa if they have a key, else free engines), or dsh's own `web_search` if
  they configured a dsh search provider.
- **Laptop**: off, `stdio` (this machine drives the Windows PC over ssh), or `http` (a shared service with a token).

Write it as `layout.json` (examples: `wizard/layouts/*.json`; field reference: `docs/LAYOUT.md`), either by hand or
with `python3 wizard/setup.py init`.

## 3. Check, render, review

```sh
python3 wizard/setup.py check layout.json        # every server: models, context, chat, tool call, PNG + WebP pictures
python3 wizard/setup.py render layout.json -o /tmp/dr-render
```

Fix every FAIL before installing. A failed **tool call** usually means the server's chat template is not applied
(llama.cpp needs `--jinja`) or the model is too weak for agentic use. A failed **WebP** picture means the server
will reject pictures dsh re-encodes, and that ends whole runs (docs/TROUBLESHOOTING.md). Either fix the server
(llama.cpp: `ffmpeg` on its PATH) or set `"vision": false` for it.

Read the rendered `cordis.patch.yml` and `skills/deep-research/SKILL.md`. Check that the lane rules in the skill
say what the user agreed to.

## 4. Adapt what the wizard does not cover

The wizard covers OpenAI-compatible servers with either Qwen-style chat-template thinking or no thinking control.
Edit the **rendered output**, or better the templates (`skill/deep-research/SKILL.md.tmpl`,
`presets/personas/*.md`, `wizard/setup.py`), when the lab differs:

- **A different reasoning model** (DeepSeek, GLM, gpt-oss, ...): the route's `compat` block decides how thinking
  is switched. Look at dsh's `llm-pi-ai` docs for the model's `thinkingFormat` and adjust `route_yaml()`. Keep a
  no-thinking twin route for the compaction summarizer: a summarizer that thinks spends its whole output budget
  on reasoning (docs/TROUBLESHOOTING.md).
- **Merging into an existing profile** instead of a separate one: copy the `- insert:` block (presets) and the
  routes into that profile's `cordis.patch.yml` by hand. Do not add a second `- id: llm-pi-ai` row; add the routes
  to the existing row's `providers`.
- **No systemd**: run `DSH_HOME=... <prefix>/node_modules/.bin/dsh --profile research --port 3080` under whatever
  supervisor the user has. The service environment must contain `uv` on `PATH` and the search keys.
- **Many users or many unrelated sessions sharing the same servers**: the lane rules only coordinate one
  orchestrator. See docs/LAYOUT.md "Sharing servers".
- **Windows hosts for dsh**: untested. The helpers are POSIX `sh` wrappers around uv scripts, so run dsh in WSL.

Record anything you changed by hand in a short `LOCAL-CHANGES.md` beside the layout file, so a later re-install
does not silently undo it.

## 5. Install

```sh
python3 wizard/setup.py install layout.json [--systemd]
```

It writes the profile (seeding `package.json`, `cordis.yml` and `pnpm-workspace.yaml` only when absent), the
rendered skill into `$DSH_HOME/skills/deep-research/`, the compaction plugin into the dsh install prefix, and
optionally a systemd **user** unit (not enabled: it prints the commands). Whatever it replaces is moved to
`$DSH_HOME/dsh-deep-research-backups/<timestamp>/`, outside the folders dsh scans.

Secrets, if any: `EXA_API_KEY=...` (and other search keys, docs/SEARCH.md) in `~/.config/dsh/search.env`; the
laptop's `CU_TOKEN=...` in `~/.config/computer-use/client.env`; cloud routes' keys under the names in `apiKeyEnv`.
All of them mode 600. Make sure the dsh process actually gets them: the generated unit loads the two files.

## 6. Verify

1. Start dsh on the profile. Its log prints a first-visit URL with a token. Look for preset or plugin load
   errors: a preset that fails to load shows as failed, and the others keep working.
2. In the web UI, open the mode picker of a new session. It must list **Deep research** and the four
   `Deep research: ... (subagent)` presets. Headless/ACP dsh composes no agent presets, so use the web UI.
3. Smoke run, with the user watching: a session on **Deep research**, then `/deep-research <a narrow question the
   user cares about>. 1 round, 3 sub-questions, no laptop pass.` Check that subagents appear under each server's
   tool, their notices arrive, and `research/<date>-<slug>/notes/` fills. Set the session's permission mode to one
   that does not prompt per tool call. Background subagents cannot answer prompts, and a run stalls on them.
4. After it finishes: `uv run tools/run_stats.py $DSH_HOME/sessions/<workspace folder>/ --timeline swarm.png` shows
   whether the lanes were kept and how busy each server was. Tune lanes and the compaction ratio from that.
5. Laptop, if set up: run `laptop-mcp/tests/smoke_mcp.py` first, then one run with a laptop pass.

## 7. Hand over

Tell the user: what was installed and where, how to start and stop it, the layout in one line, what you changed by
hand, what failed or was not verified, and how to re-run the wizard after changing servers.
