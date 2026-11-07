# The model servers

The swarm needs one or more **OpenAI-compatible chat servers** (`POST <base>/chat/completions`) that:

- **call tools reliably** with structured `tool_calls`. A worker makes 30–50 tool calls in a row, and one
  malformed call usually ends its turn. `wizard/setup.py check` sends a tool-call probe;
- hold **≥ 64K context**. 128K+ is comfortable, and the primary server (critic, writer) wants the longest;
- answer **slowly but steadily**: requests queue, so the client timeouts are long (30 min per request, 15 min
  without a byte). A server or proxy in front with a shorter timeout kills queued subagents;
- ideally keep **idle conversations in RAM** (a conversation or prompt cache), which is what makes 2 lanes per
  slot cheap (docs/LAYOUT.md);
- optionally read **pictures** (an mmproj / vision tower). Workers look at YouTube frame sheets and page images
  with it, and the critic checks claims about what a video shows. Without vision, set `"vision": false`: the
  workers then report such claims as "not seen".

## The model class that works

Everything here was developed on **Qwen3.8-Flash-Next**: a 125B-parameter MoE with 10 of 512 experts active per
token, a hybrid attention design, native vision and MTP heads. Quantized to ~3 bits it is 74–90 GB. The trick that
makes it a consumer-hardware model: **dense weights, KV cache and a cache of the hottest experts on the GPU,
every other expert in system RAM** computed by the CPU. A token touches only 10 experts, so RAM bandwidth, not
VRAM, sets decode speed.

| box | engine, quant | context | decode | prompt read |
|---|---|---|---|---|
| RX 7800 XT 16 GB + Ryzen 5 3600 + 128 GB DDR4 (2 ch) | Avalon (llama.cpp fork, HIP), IQ3_KS ~90 GB | 262144 | 67–78 tok/s at 4K, 57–61 at 197K | 800–1060 tok/s |
| same box, 62 GB RAM | same | 262144 | 62–74 | 680–970 |
| RTX 3080 10 GB + i5-11400F + 64 GB DDR4-2800 | Speedy (Strata fork, CUDA), ISTA IQ3_S ~74 GB | 229376 | 51–63 | 1400–1700 |
| same box | Avalon CUDA, IQ3_KS | 131072 | 42–53 | ~500 |

Rules of thumb from those boxes:
- **RAM ≥ the quant's expert weights** (resident, or at least in page cache), or decode collapses into disk reads.
  64 GB runs a ~74 GB quant with the rarely read tables streamed from a fast NVMe. 128 GB runs ~90 GB comfortably.
- **VRAM buys context and expert-cache hit rate**, not the ability to run at all. 10 GB holds 224K context on
  Speedy; 16 GB holds 256K plus a ~10 GiB expert cache on Avalon.
- **More parallel slots do not add throughput** on this MoE (docs/HOW-IT-WORKS.md). More boxes do.

Any other model that passes the tool-call probe and holds the context will run the swarm: a dense 27–32B on a 24 GB
card, a cloud route, etc. Expect quality to follow the primary model: it writes and reviews the report.

## Settings that matter (llama.cpp and forks)

| setting | why |
|---|---|
| `--jinja` | the model's own chat template, so tool calls come back as structured `tool_calls` |
| `-c <window>` matching the layout's `contextWindow` | dsh plans compaction from the layout's number. A server holding less answers 400 "prompt leaves no room" |
| `--parallel 1` (on a sparse MoE) | other slots keep part of the KV and add no throughput |
| `--cache-ram` on (default 8 GiB) | the conversation cache. **llama.cpp sets it to 0 when the model is bigger than RAM**, and the log says `prompt cache disabled`: then use 1 lane on that server |
| `--reasoning-budget` **below the client's output cap** | dsh caps an answer at `maxTokens` (16384 here). A model allowed to think for all of it ends turns with `length` and nothing done. 8192 worked |
| `ffmpeg` on the server's `PATH` (if it reads pictures) | llama-server decodes WebP only through ffmpeg, and dsh sends WebP for any big picture with transparency. A 400 on a picture poisons the conversation that holds it (docs/TROUBLESHOOTING.md) |
| sampling on the server | dsh sends no sampling parameters, so the server's defaults are what the swarm gets. Qwen 3.x: `--temp 0.65 --top-p 0.95 --top-k 20 --min-p 0.05`, presence penalty 0 (1.5 hurts tool arguments) |
| a host allowlist / auth that accepts your dsh host | some engines refuse unknown `Host` headers (DNS-rebinding guards): use the IP or allow the name |
| Qwen 3.8 Flash-Next: `--chat-template-kwargs '{"preserve_thinking": true, "reasoning_effort": "medium"}'` | its template raises on any effort other than low / medium / xhigh. The route sends those spellings only |

Probe before trusting a server: `python3 wizard/setup.py check layout.json`. For speed, check that a fresh 16K
prompt and a follow-up behave as you expect: the follow-up TTFT should be about 1 s when the conversation cache
works.

The complete, working configuration of two such servers is in [reference-lab/](reference-lab/README.md).
