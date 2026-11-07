# Design

How the laptop MCP works, why it is built this way, and what was measured when it was built (2026-10).
Setup and configuration are in [README.md](README.md); this file is the reasoning behind it.

## Pieces

| Piece | Where | Job |
|---|---|---|
| `bootstrap/` | the driving machine → laptop, once | `serve.py` serves a two-stage PowerShell script: stage 1 as the agent account (per-user settings, facts), stage 2 behind UAC (OpenSSH Server, keys, firewall, power), reports back the host keys |
| `laptop/deskd.py` | laptop, the agent account's session | screenshots (mss), SendInput mouse (curved paths) and Unicode keyboard, windows, clipboard, Chrome launcher, keep-awake, the lease. HTTP on 127.0.0.1:8770, bearer token in `state\token` |
| `laptop/install.ps1` | laptop | `uv sync` + the `computer-use-deskd` scheduled task (interactive, at the agent account's logon and every minute while it is signed in, one instance, no time limit): a deskd that died is back within a minute, and deskd starts the agent Chrome when it starts |
| `cu/laptop.py` | the driving machine | the ssh tunnel (deskd + DevTools ports) and deskd's client |
| `cu/browser.py`, `cu/page.js` | the driving machine → Chrome | read-only page access over DevTools in an isolated world (open shadow roots included) |
| `cu/vault.py` | the driving machine | the agent identity's vault: the Bitwarden CLI on its own profile, against a self-hosted Vaultwarden |
| `cu/mcp_server.py` | the driving machine | the MCP tools, the run record, the browser-only guard |
| `cu/report.py`, `cu/cli.py` | the driving machine | `bin/cu`: operate deskd, list runs, render a run, list escalations |

## Why each choice

**deskd in the agent account's session, reached through ssh.** sshd's sessions are session 0, which has no
desktop: screenshots and input from there do nothing. A per-user interactive scheduled task puts
deskd into the agent account's console session without admin rights or a stored password, and ssh's port
forwarding gives it authentication and encryption for free; nothing but sshd listens on the LAN.

**Our own small executor instead of Windows-MCP.** Windows-MCP (MIT, active) was the research's
first pick. deskd is about 640 lines with two dependencies, has no telemetry, needs no Python
3.14, and exposes only what the MCP layer uses. Windows-MCP's accessibility snapshots of desktop
apps are worth borrowing if desktop tasks become common.

**Chrome stable, launched plainly, on its own profile.** Launched with only
`--user-data-dir` and `--remote-debugging-port`, Chrome leaves `navigator.webdriver` false and shows
no automation bar. deskd starts it once (at logon, and whenever the service finds the port
dead) and ends a Chrome that holds the profile without answering on the port, since a second start would only hand
its arguments to that process. The service follows its ssh tunnel to the port: the tunnel reopens on new
local ports after every reboot of the laptop. Chrome 136+ refuses the debugging port on the default profile, hence the own
profile, which also keeps the agent away from anything of the operator's. Firefox is out: every remote
start sets `navigator.webdriver`. Frameworks are out: Playwright, Puppeteer, Selenium and Chrome
DevTools MCP add switches or call `Runtime.enable` on every tab.

**Read through DevTools, act through the OS.** Page reading runs in an isolated world
(`Page.createIsolatedWorld` + `Runtime.evaluate` with its context id): it shares the DOM, the page
cannot see it, and no `*.enable` call is ever made, which is the classic tell. Clicks and keys are
real `SendInput` events at screen coordinates computed from element boxes and the window geometry,
so the page sees trusted, hardware-shaped input. In 2026 behaviour separates agents from people
better than fingerprints do (a May 2026 study: F1 0.9993 on behaviour, 0.80 on fingerprint), so
the mouse moves on curved, eased paths and text is typed at about 9 keys a second, never pasted.

**Points on a 0–1000 grid for Gemini.** Gemini models point natively on a 0–1000 grid; `CU_COORDS=norm1000`
converts. Other models (Qwen-VL included) are safest with screenshot pixels, and with the text tools first.

**A lease, not a queue.** deskd grants one lease; every action needs it and renews it, and it lapses
10 minutes after the last action. Queueing research sessions is the harness's job; the lease only
makes sure two sessions can never interleave input.

## Using it

An MCP client starts `bin/cu-mcp` over stdio. Environment:

| Variable | Meaning |
|---|---|
| `CU_OWNER`, `CU_PURPOSE` | who holds the lease and why (shown to others, written to the run) |
| `CU_COORDS` | `pixels` (default: latest screenshot's pixels) or `norm1000` (Gemini) |
| `CU_TOOLS` | `browser` (default: input only reaches the agent's Chrome) or `all` |
| `CU_SHOT_WIDTH` | screenshot width sent to the model (default 1280; the Gemini agent uses 1440) |
| `CU_RUN` | the run directory's name (default: timestamp + owner) |
| `CU_TYPE_CPS` | typing speed, keys per second (default 9) |
| `CU_IDENTITY` | the identity file (default `~/.config/computer-use/identity.env`; without it the account tools are off and agents are told to escalate login walls) |
| `CU_SESSION_MINUTES` | the server takes the laptop itself at its first action, for this many minutes, waiting in line up to `CU_QUEUE_WAIT` seconds (default 3600): one-task clients (scripts, tests) |
| `CU_LEASE` | work under a lease another process holds (the research harness reading the tab of a researcher who holds the laptop) |
| neither | the agent takes the laptop itself: `laptop_acquire` / `laptop_release`, and a `lease` parameter on every laptop tool (Claude Code sessions, server `laptop`) |

Tools: `laptop_acquire`, `laptop_release`, `laptop_status` (the queue), `browser_open`, `browser_new_tab`, `browser_switch_tab`, `browser_read`, `browser_elements`,
`browser_find`, `browser_click`, `browser_type`, `browser_scroll`, `browser_back`, `browser_tabs`,
`browser_pdf_text`, `escalate`, the account set `account_lookup`, `account_create`,
`account_new_password`, `account_fill`, `account_update`, and the desktop set `screenshot`, `click`,
`type_text`, `press_keys`, `scroll`, `drag`, `wait`. The server's instructions tell the agent to
prefer text, never solve a check, sign up and sign in only through the account tools, and escalate
what only the operator can do.


## The laptop queue

The operator's rule (2026-10-17), when the laptop became available to every Claude session: an agent marks the laptop
busy for the time it asks for, the others wait in line, and when the time is up the laptop goes to the next in line and
the late holder's task fails. `cu/queue.py` keeps it in plain files under `state/laptop/` (an flock around every
change), so every process on the driving machine takes part: the per-session MCP servers (subagents of one Claude session share
one, so the lease is a token passed on every call, not the process), scripts and tests.

- `laptop_acquire(purpose, minutes=15, ticket, wait_minutes=30)`: FIFO; answers GRANTED with a lease, or WAITING
  with a ticket to ask again with (each ask keeps the place; a ticket not asked about for 6 minutes, or whose process
  died, is dropped). Minutes are fixed at the start, at most 30: no extensions, so the line moves.
- Every laptop tool checks the lease first. Past its deadline the lease is gone (the next waiter takes over even if
  the holder is idle) and every call answers `TIME UP: ... your task has failed`. A holder whose process dies frees
  the laptop at once; a server that ends gives back the leases it took.
- `laptop_release(lease)` closes the holder's tabs and frees deskd's lease; a grant also tidies the tabs the last
  holder left. deskd's own lease (sliding 10 minutes) is taken under the holder's name and its id kept with the
  lease, so a second process working under the same lease (the harness capturing a page) shares it; a deskd lease
  left by an earlier holder is taken over, the operator's live view never.
- The operator's live view still takes deskd's lease by force; the holder's calls then fail with "the operator has the
  laptop" and its time keeps running.

Measured 2026-10-17: a second session waiting in line got the laptop 9 s after the first released it; a call 65 s
into a one-minute lease answered TIME UP and the laptop showed free; the harness captured a researcher's open tab
(MobyGames search, refused to scripts by robots.txt) inside the researcher's lease.

## Honest browsing

The operator's line (2026-10-16): look like a real browser by being one, and do not game the system;
and the point of the service is information plain fetching cannot get, so try hard. In practice:

- no fingerprint spoofing, no stealth forks, no automation flags, no CAPTCHA solvers;
- no Web Bot Auth signature or agent user-agent: for one person's research at a person's pace it
  identifies nobody useful, and since 2026-09-15 new Cloudflare zones block self-identified agents
  on ad pages by default;
- **trying hard** (`outcome` in cu/mcp_server.py): automatic checks get 30 s to clear on their own
  (Cloudflare's JavaScript challenge and Reddit's `js_challenge` pass because the browser is real),
  then one reload, then the site's front page and back to the page with it as referrer, the way a
  person would get in. The agent is told to look for the same facts elsewhere (other pages, archived
  copies) while a page is parked;
- **agents never answer a human check**, neither a puzzle nor a lone "Verify you are human"
  checkbox: passing one is a claim that a person is there. (The operator asked on 2026-10-16 for agents
  to try interactively for up to 15 minutes; Claude declined that part and built the hand-off
  below instead.) A page still behind a check after the retries is **parked**: written to
  `state/escalations.jsonl` with a screenshot, and the agent moves on;
- **the operator clears parked checks in batches** from `bin/cu live` (the laptop's screen in a web
  page on the LAN, from the driving machine or a phone): take control, load the URL, pass the check. The
  clearance cookie stays in the agent profile, so one pass usually covers the site for hours or
  days; the next clean load of the site closes its escalations, and the harness retries the parked
  URLs (`bin/cu escalations --urls`);
- the operator also signs the agent profile into sites that keep showing up as login walls.

## Accounts

The operator gave the agent browser its own identity on 2026-10-16: a throwaway Gmail, signed in in the
agent Chrome, and a throwaway account on a self-hosted Vaultwarden. Agents may sign that identity up for
sites a task needs, once per site, and the design keeps passwords out of everything an agent or a
reviewer reads:

- **The vault makes and keeps the password.** `account_create(site, url, username, …options)`
  generates it with the password manager's generator (`bw generate`, 20 characters of all kinds by
  default; the options are the agent's way to meet a site's rules: length, kinds, up to 4 appended
  characters) and saves the item (status `pending`) before the form is filled.
  `account_new_password` replaces it while the sign-up is still pending, never afterwards.
- **The tools type it.** `account_fill(item, "password", index)` types the value through deskd at a
  person's pace, flagged secret: deskd logs its length only, the run record has the item id, and
  page.js never reads a password field's value back (labels, matches, read-backs). `browser_type`
  and `type_text` refuse password fields.
- **Only on its own site, only into the right field.** `account_fill` refuses unless the page's
  registrable domain is the account's, and puts a password only into a password field and a
  username never into one. A page that talks the agent into "re-entering" a password elsewhere
  gets a refusal. Before typing, the field must hold the focus (or have been swapped by the page
  for its own field of the same kind); a click that lands on a popup instead types nothing. That
  check came from the first live sign-up, where Chrome's address-autofill popup took the click and
  opened Chrome's settings; the domain check stopped the retry there, and the popup is now off.
- **One account per site.** `account_create` refuses while a non-failed account for that domain
  exists; the instructions forbid accounts made to get around a limit, ban or trial.
- **The Google account is the identity.** Its item is protected (no new password, no edits), and on
  Google's account-security pages (passkeys, sign-in options, recovery, speedbumps) only a decline
  (Not now, Skip, Non ora, Annulla) gets through `browser_click`; typing and other keys are refused.
  The operator's rule: never a passkey on it (a passkey would tie it to this laptop's Windows Hello).
- **No second password manager in the browser.** The Bitwarden extension the operator first installed
  was removed (its inline menus and save bars only got in the agent's way), and Chrome's own password
  saving and address/card autofill are off by user policy, so the vault is the one place passwords
  live and no browser popup sits over a form.
- **The username is what the site signs in with** (often the email); a public screen name goes in
  the item's notes.
- **What stays with the operator:** human checks on sign-up forms (parked as before), phone numbers
  (`escalate(kind="phone")`), payment, ID. Email confirmation the agent does itself in Gmail
  (`browser_new_tab`), which is also why the identity must stay a throwaway: a page that injects
  instructions could have the agent read that mailbox.

## Safety

the agent account is an administrator and web pages can carry instructions aimed at the agent (measured
injection success against computer-use agents: 40–90 % in 2025–26 papers). The layers:

- **Browser-only sessions by default**: desktop input is refused unless the agent's Chrome is in
  front and the point is inside it; Win, Alt+Tab and Ctrl(+Shift)+Esc are refused. An agent cannot
  open a terminal or another app.
- **UAC prompts** appear on the secure desktop, which SendInput cannot reach: an agent cannot
  approve an elevation.
- **The agent profile holds nothing of the operator's**: it is signed into the agent identity only; no
  password manager extension, Chrome's password saving off, no saved cards. The vault's master
  password stays on the driving machine, read by the MCP server; the laptop never has it.
- **Everything is recorded** (`state/runs/`), and the supervisor reviews findings, not just answers.

Not covered yet: downloads (an agent could save a file; opening it is outside the browser and
refused, but Chrome's own download bubble is inside it), and the screenshot injection screening
that Anthropic's and Google's native computer-use tools do and a custom loop does not.

## Measured on 2026-10-16

| Check | Result |
|---|---|
| Bootstrap | one Win+R line + one UAC click; sshd up, host key pinned, ~30 s |
| deskd round trip | screenshot in 39 ms on the laptop; from the driving machine ~1 s cold (tunnel + token), then ~90 ms a call and ~150 ms for a 1280-wide JPEG screenshot |
| Plain-browser tells | Chrome 155 UA without "Headless", no automation bar, `webdriver` false |
| Pages | Google search (after the consent was refused once), PriceCharting, eBay.it, MobyGames search, Wikipedia, Redump: full text. Reddit: reCAPTCHA once on a fresh profile, then its JavaScript challenge passed on its own. Wikipedia answered one 429 to the first visit, then normal. nowsecure.nl shows Cloudflare's always-interactive *test* widget, so it measures nothing |
| Guard | a browser-only agent asked for the Calculator: Start click and Win key refused, reported "failed" |
| Escalation | a stand-in "Just a moment..." page: the agent escalated (kind challenge) and finished "blocked" without clicking |
| Account sign-up | one prompt: Internet Archive account for the identity: lookup, create (vault password), form (email, newsletters unticked), submit (no visible check), confirmation mail read in a Gmail tab, verify link, sign in, marked active. 50 steps, ~8 min, status done; the password in no run record or log (deskd logged 3 redacted fills). Found: Chrome's autofill popup over the form (now off), the screen name stored as the username (now fixed in the instructions) |
| Park and clear | the same page on a deep path: waited, reloaded, front page, parked, BLOCKED returned (93 s); taken over in `bin/cu live` (lease moved to the operator, F5 forwarded, released); the next agent load was clean (2 s) and closed the escalation |
