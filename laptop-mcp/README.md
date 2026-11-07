# laptop MCP (optional): a real Chrome on a spare Windows PC

Some of what a research run needs never reaches a script: Cloudflare and DataDome interstitials, JavaScript-only
apps, a forum's own search, "show more" buttons, registration-walled attachments, PDF viewers. This component turns
a spare Windows laptop into an MCP server that research agents drive **one at a time**. It is a real Chrome with
real, human-paced input: no automation flags, no fingerprint spoofing, and no CAPTCHA solving. In the deep-research
skill, the `dr-laptop` subagent reads the pages workers marked `BLOCKED`, in batches.

Without it, the swarm still works: blocked pages are listed as unread and the facts are looked for elsewhere.

## How it works

```
dsh (dr-laptop preset) ──MCP──► cu-mcp (this repo, on a Linux/macOS box) ──ssh -L──► the Windows PC:
                                 queue, run records, guards                        deskd (laptop/deskd.py) in the agent
                                                                                    account's desktop session: screenshots,
                                                                                    SendInput mouse/keyboard, windows, lease
                                                                                    Chrome's DevTools port (read-only page access)
```

- **deskd** runs as an interactive scheduled task in a dedicated Windows account's console session. sshd sessions
  cannot see the desktop. It listens on 127.0.0.1 only, and the MCP server reaches it through an ssh tunnel.
- **Pages are read through DevTools** in an isolated world, with no `*.enable` domains (the classic automation
  tell). **Clicks and keys are real `SendInput` events**: curved mouse paths, ~9 keys a second, never pasted.
- **One agent at a time**: `laptop_acquire(purpose, minutes)` (15 by default, at most 30) waits in a FIFO queue
  shared by every MCP server process on the machine. Every other tool takes the lease. When time runs out, the
  next agent gets the laptop and the late one's calls answer `TIME UP`.
- **Human checks are never answered.** The tools wait out automatic challenges, reload, and come in through the
  site's front page. A page still behind a check is **parked** for you (`bin/cu escalations`): you clear it in
  `bin/cu live`, which shows the laptop's screen in a browser on your LAN and lets you take control. The clearance
  cookie usually holds for days.
- **Browser-only by default** (`CU_TOOLS=browser`): input outside the agent's Chrome is refused, and so are Win,
  Alt+Tab and Ctrl+Esc. UAC prompts sit on the secure desktop, which SendInput cannot reach.
- **Everything is recorded** under `state/runs/<run>/` (actions + screenshots). `bin/cu report <run>` renders a run
  as an HTML timeline.

The reasoning and measurements behind each choice are in [DESIGN.md](DESIGN.md).

## Setup

You need a Windows 10/11 PC that can stay on with its lid open (or an HDMI dummy plug), Google Chrome, and a
Linux or macOS machine on the same LAN with `uv` and `ssh`. Plan for an hour.

1. **An agent account on the PC.** Create a local Windows account for the agents (the default name here is
   `agent`; set `CU_AGENT_USER` if you pick another). Give it nothing of yours: no personal browser profile, no
   saved passwords. Sign in as it once.
2. **Bootstrap ssh** from the driving machine. It serves two PowerShell stages to the LAN only: per-user settings,
   then OpenSSH Server, your public key, firewall and power settings behind one UAC prompt.
   ```sh
   CU_AGENT_USER=agent CU_BOOTSTRAP_LAN=192.168.1.0/24 python3 bootstrap/serve.py 8765
   ```
   On the PC, signed in as the agent account: Win+R → `powershell irm http://<driving machine>:8765|iex`. Add the
   PC to `~/.ssh/config` as `Host laptop` (or set `CU_HOST`). `ssh laptop` must log in with the key.
3. **uv on the PC**, as the agent account: `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`.
4. **Install deskd**: `bin/cu deploy`. It copies `laptop/`, runs `uv sync`, and registers and starts the
   `computer-use-deskd` task. Then `bin/cu health` and `bin/cu shot test.png`.
5. **Smoke test**: `uv run python tests/smoke_mcp.py` (over stdio, or the HTTP service when `CU_URL`/`CU_TOKEN`
   are set) takes the laptop for about a minute.
6. **Wire it into dsh** with the wizard's layout (`"laptop"` in `layout.json`, docs/LAYOUT.md):
   - **stdio** (one machine drives the laptop): `{"enabled": true, "transport": "stdio", "env": {"CU_HOST":
     "laptop", "CU_AGENT_USER": "agent"}}`. The dsh profile starts `bin/cu-mcp` itself. Every stdio server on that
     machine shares the queue in `state/laptop/`.
   - **http** (several PCs or harnesses share one laptop): run `bin/cu-mcp --http 127.0.0.1:8771 --clients
     /path/clients.json` as a service behind your reverse proxy (TLS). Mint a token per client with
     `CU_CLIENTS=/path/clients.json bin/cu add-client <name>`; only its hash is kept. Put `CU_TOKEN=<token>` into
     `~/.config/computer-use/client.env` (mode 600) on the dsh host, and use `{"enabled": true, "transport":
     "http", "url": "https://laptop.example.lan/mcp", "tokenEnv": "CU_TOKEN"}`.

## Configuration (environment)

| variable | meaning |
|---|---|
| `CU_HOST` | ssh host of the PC (default `laptop`) |
| `CU_SSH_OPTS` | extra ssh options (a service's own key, a pinned known_hosts) |
| `CU_AGENT_USER` / `CU_REMOTE_HOME` | the Windows account and where deskd lives (default `C:/Users/<user>/computer-use`) |
| `CU_STATE` | runs, queue and escalations (default `./state`) |
| `CU_TOOLS` | `browser` (default) or `all` (the whole desktop: never for open-ended research) |
| `CU_COORDS` | `pixels` (default: screenshot pixels) or `norm1000` (models that point on a 0–1000 grid, e.g. Gemini) |
| `CU_SHOT_WIDTH` | screenshot width sent to the model (default 1280) |
| `CU_TYPE_CPS` | typing speed (default 9 keys/s) |
| `CU_OWNER`, `CU_PURPOSE` | who holds the laptop and why, shown in the queue and the run record |
| `CU_SESSION_MINUTES` / `CU_LEASE` | for one-task scripts: take the laptop at the first action / work under someone else's lease |
| `CU_IDENTITY` | the agent identity file (below). Without it the account tools are off and agents escalate login walls |

## Optional: an agent identity with its own accounts

Off unless you create `~/.config/computer-use/identity.env` (mode 600): `AGENT_EMAIL`, `AGENT_NAME` (a
**throwaway** Gmail signed into the agent Chrome), and `BW_SERVER`, `BW_EMAIL`, `BW_PASSWORD` (a Vaultwarden or
Bitwarden account of its own, used through the `bw` CLI). With it, agents may sign the identity up for sites a
task needs, one account per site. **Passwords never pass through a model or a log.** The vault generates and keeps
them, `account_fill` types them only into a password field on the account's own domain, and `browser_type`
refuses password fields. The Google account itself is protected: no passkeys, and no changes to its password or
recovery settings. Phone numbers, payment and ID are always escalated to you.

Use a throwaway identity only. A page can carry instructions aimed at the agent, and the identity's mailbox is
readable by it. Do not make second accounts to get around a site's limits.

## Operating it

| | |
|---|---|
| who has it, who waits | `bin/cu queue` |
| deskd's view (session, lock, foreground) | `bin/cu health` |
| watch, or take control to clear checks | `bin/cu live` → open the printed URL on your LAN |
| what needs you | `bin/cu escalations` (parked checks, login and consent walls, by site) |
| review a run | `bin/cu runs`, `bin/cu report <run>` |
| a stale holder | `bin/cu lease`, then `bin/cu lease break` (leases also lapse 10 min after the last action) |

Not covered: downloads (Chrome's download bubble is inside the browser), and screenshot prompt-injection
screening. Signing in to your own account on the PC disconnects the agent account's session, so screenshots go
black until it is back on the console.

This component was built for, and runs in, the author's lab (docs/reference-lab). The generalization in this repo
(the account name, ssh host and LAN made configurable, stdio as the default mode) has not been run on a second
PC yet.
