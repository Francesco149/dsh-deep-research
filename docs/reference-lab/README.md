# The reference lab: a setup that works

This is the author's home lab as it ran the runs in the top-level README (November 2026). It is not a
recommendation to copy it: it is something tangible to compare yours against. Host names are the lab's, and
addresses, domains and credentials are left out.

```
 desktop (Arch Linux)                        lame (NixOS)                              ampere (NixOS)
 ├─ dsh 0.2.1-rc.5, profile with the 5       RX 7800 XT 16 GB (model) + RX 570 4 GB    RTX 3080 10 GB, i5-11400F,
 │  presets, web UI on :3080 (systemd user)   (image encoder), Ryzen 5 3600 6c,         64 GB DDR4-2800 (4 sticks, no XMP),
 ├─ skill + helpers in ~/.dsh/skills/        128 GB DDR4, Crucial T700 NVMe (ZFS)      PCIe 3.0 NVMe (ext4)
 └─ the browser for the web UI               Avalon (llama.cpp fork, HIP)              Speedy (Strata fork, CUDA)
                                             Flash-Next IQ3_KS @ 262144, :8080         Flash-Next IQ3_S @ 229376, :8080
 service VM: laptop MCP (HTTP, client tokens) ──ssh──► Windows laptop: deskd + Chrome on its own profile
```

The layout file for this lab is [`wizard/layouts/reference-lab.json`](../../wizard/layouts/reference-lab.json):
two servers, lame primary, 2 + 2 lanes, workers compacting at 0.2, the laptop over HTTP.

## The model

**Qwen3.8-Flash-Next**: a 125B MoE (512 experts, 10 active, 48 layers) with native vision and MTP heads. Two
quants of it, one per box:

| | lame | ampere |
|---|---|---|
| quant | Avalon's **IQ3_KS** hybrid (2–4-bit experts), ~89.7 GiB, 33 shards + MTP head + `moe-cache-ranking.bin` | ISTA-DASLab's **IQ3_S**, ~74 GB, packed with Speedy's `iq_pack.py` + its MTP draft layer |
| engine | [Avalon](https://github.com/freriadoc/Avalon) (MIT), HIP / ROCm 7.2, plus Vulkan for the image encoder | [Speedy](https://github.com/DevDock-AI/Speedy), CUDA 13.0 for sm_86, from its own Nix devShell |
| context | 262144 (the model's native) | 229376 |
| where the experts live | dense weights + KV + ~10 GiB expert cache on the card; the rest in RAM (page cache, 52 GiB resident); the 35.8 GiB n-gram table on a ZFS dataset with 16K records | dense + KV + expert cache on the card; 43.6 GiB of experts pinned in RAM; the n-gram table streams from the SSD |
| speed (engine's own totals) | decode 67–78 tok/s at 4K, 72–74 at 16K, 57–61 at 197K; prompts 800–1060 tok/s warm | decode 51–63 tok/s; prompts 1400–1700 tok/s |
| conversation cache | llama-server `--cache-ram` 8 GiB: 4 × 32K conversations, ~1.2 s to come back | Speedy `--conversation-cache-mib 8192`: three 16K conversations switch in ~1 s |
| pictures | encoder on the RX 570 over Vulkan, 1536 tokens a picture, ~10 s | the 3080 on demand (lends 2 GiB of its expert cache for 30 s), ~5 s cold, 2.8 s warm |
| configuration | [`lame-avalon.sh`](lame-avalon.sh) (the exact command line) | [`ampere-speedy.json`](ampere-speedy.json) (the exact run config) |

## What had to change to get there

Each of these was measured (the numbers are the lab's) and each matters if your box is similar:

- **`-ub 2048`, not Avalon's upstream 9536** on a 16 GB card. 9536 OOMs past ~32K of context. 4096 squeezes the
  expert cache out at ~123K, so follow-up decode falls to 6–21 tok/s. 2048 holds 62 tok/s at 129K and 57–61 at
  197K. Cost: ~10–20% of fresh-prompt prefill at 4–16K.
- **The n-gram table on a 16K-record ZFS dataset.** It is read a few rows a token at random, and ZFS's default
  128K records turned each read into 128K of I/O. Fresh-prompt prefill went from 271 to 1075 tok/s. On ext4 or
  XFS this does not arise.
- **`--reasoning-budget 8192`**, below the clients' output caps. At 14000 the model spent three turns running
  thinking to `length`.
- **ffmpeg on the server's PATH.** One run lost its orchestrator to a WebP picture (docs/TROUBLESHOOTING.md).
- **128 GB of RAM on the 16 GB box.** It holds the whole model in page cache once warm: fresh 4K prompts at
  801–995 tok/s against 682–699 on 62 GB, and short decode at 83–87 against 75. Right after a boot the table is
  cold and prompts read at ~330–390 tok/s until it warms. More important for the swarm: on 62 GB the model was
  bigger than RAM, so llama.cpp had turned **`--cache-ram` off** by itself. No conversation cache means 1 lane on
  that box.
- **On the 10 GB card, Speedy rather than Avalon.** Avalon CUDA fits only 131072 of context with dense layers on
  the card. Its experts need writable pinned memory, because GeForce drivers refuse read-only host registration
  (a patch fixed it). It reaches 42–53 tok/s with prompts at ~500. Speedy: 229376, 51–63, prompts ~1500, plus a
  conversation cache, which is what lets ampere take 2 lanes. The cost is the slightly lossier IQ3_S quant.
- **`--parallel 1` everywhere.** 1 stream: 83 tok/s; 2 slots: 87 total; 3 slots: 79 total. More slots also
  degrade MTP drafting.

## dsh

- Installed with `npm install --prefix ~/.local/share/dsh @deepseek-ai/dsh` (0.2.1-rc.5), run as a systemd user
  service: `dsh --profile <name> --no-open --port 3080`, with `EnvironmentFile`s for the search keys and the
  laptop token.
- The profile patch is the wizard's output for `reference-lab.json`. The lab also restates dsh's Standard preset
  to put the same bounded compaction into everyday coding sessions. That is not part of this repo.
- Session permission mode **Full access** for research sessions: background subagents cannot answer prompts.
- Search: an Exa key, falling through to DuckDuckGo, Vertex (Gemini with Google Search, through gcloud ADC) and
  the free pool.

## The laptop

A Samsung Galaxy Book3 (i5-1335U, 8 GB, Windows 10 IoT Enterprise LTSC) with an agent-only local account, running
deskd and the agent Chrome on its own profile. The agent identity is a throwaway Gmail signed into that Chrome,
with its own Vaultwarden account for site passwords. The MCP server runs as a service on a small VM, in front of
one ssh tunnel to the laptop, with one queue for every agent in the lab and a client token per PC. In the runs above
it read 4 and 2 batches of bot-walled pages: TechPowerUp PCB photo threads, Reddit threads, registration-walled
forum attachments, a Google Drive folder. Setup: [`laptop-mcp/README.md`](../../laptop-mcp/README.md).

## The runs

| run | layout used | notes |
|---|---|---|
| ROCm 7.2 / Polaris support | lame only (the second route named the wrong model id, so the orchestrator re-queued its tasks on lame) | 9 subagents, 2.2 h, 3,281 words, 56 sources |
| DDR4 tuning on ampere's own B560 board, first try | 2 + 1 lanes | **aborted**: two lame workers grew to ~180K each and thrashed the 8 GiB conversation cache (207 s a turn switch). This led to the worker budget and compaction at 0.2 |
| the same, again | 2 + 2 | 11 subagents, 1 h 34 min, 5,199 words, 49 sources |
| indie mobile game niche | 2 + 2 | 37 subagents, 3 rounds, 21 fact checks, 2 laptop passes, 4.6 h, 9,173 words, 168 sources |
| ZOTAC RTX 3060 Ti board repair ([report](../../examples/zotac-rtx3060ti-repair/report.md)) | 2 + 2 | 41 subagents, 3 rounds, 12 fact checks, 4 laptop passes, 7.8 h (about 1 h of it the WebP stall), 14,560 words, 169 sources |
