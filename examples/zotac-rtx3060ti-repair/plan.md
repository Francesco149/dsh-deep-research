# Research plan — ZOTAC RTX 3060 Ti Twin Edge OC LHR board-level repair

## Brief
The user owns a **ZOTAC Gaming GeForce RTX 3060 Ti Twin Edge OC LHR** that died with
**artifacting and crashes that got progressively worse even when underclocked** — a classic
hardware degradation signature (failing GDDR6 module, GPU core BGA/interconnect, or power
delivery). They want an **exhaustive** reference for repairing it board-level:

- Board identification (PCB/PG numbers, GA104 variant, VRAM chip markings, vBIOS).
- **Where to find schematics and boardviews** for this exact board (paid and free sources).
- **Diagnostic tooling**: software tests to isolate VRAM vs core vs VRM faults, and
  hardware bench tools (meters, thermal, BGA rework).
- **Memory chip swap** procedure and **core reball** procedure for this card family,
  including parts (GDDR6 chips, stencils, solder balls) and thermal profiles.
- What **GPU repair content creators — especially NorthWest Repair — have published about
  this card/family**, as clues and references to tools/schematics.

Audience: technically capable DIY repairer deciding whether to attempt the repair, what to
buy, and what the realistic odds are. Deliverable: a comprehensive, cited repair reference
guide with a diagnostic decision tree and a tool/parts list. Date: 2026-11-06.
Search: helper `/home/headpats/.dsh/skills/deep-research/scripts/search` (Exa → DDG → Vertex → free engines → LangSearch).

Assumptions: card still displays (artifacts, not dead-no-display); user has soldering
experience; budget-conscious; US/EU parts sourcing both in scope.

## Sub-questions (round 1)

1. **board-ids** — Identify the exact board: ZOTAC PCB number (ZT-T306…), NVIDIA PG board
   number (PG152 SKU?), GA104-200-A1 vs GA104-300, VRAM chips (Samsung/Micron/SK hynix
   part numbers), vBIOS. Angles: TechPowerUp GPU database + forum "PCB image" thread
   (https://www.techpowerup.com/forums/threads/332878/), ZOTAC product page, TechPowerUp BIOS
   library, GPU-Z. Why: everything else keys off the exact board revision and memory vendor.
2. **schematics-sources** — Where to get schematic/boardview for this board:
   schematic-expert.com (RTX 3050/3060/Ti page), Badcaps boardview archive, PGTBoardView
   (pgtboardview.com), masterschematics.com, indiafix collection, boardsheet.net, Reddit
   r/GPURepair, Discord repair servers. Formats (.brd/.fdx/.txtl/PDF), prices, whether the
   ZOTAC Twin Edge LHR specifically is covered or only reference PG152. Why: user explicitly
   asked for schematics.
3. **failure-modes** — Documented common failure modes of RTX 3060 Ti / GA104 cards,
   especially LHR Twin Edge: SK hynix GDDR6 bad batches (X005?), Samsung/Micron rates, core
   degradation vs cold-joint, VRM/short failures, no-display vs artifact signatures. Reddit
   r/GPURepair threads on 3060 Ti artifacting; badcaps Zotac 3060 Ti LHR thread
   (…/3821485-zotac-rtx-3060-ti-lhr-8-go). Why: decides memory-swap vs reball vs VRM repair.
4. **nw-repair** — NorthWest Repair content about this card/family: videos, their Google
   Drive resource hub, schematics/boardviews they use or sell, tools they name (preheater,
   hot air, stencils, PGO/Pete's "GPU repair" resources). Also other creators who worked on
   Zotac 3060 Ti / GA104: BitForge Repairs (Zotac 3060 Ti video), Kiki Hobby Repair, RadPaw,
   NW Repair's Gigabyte 3060 Ti VRAM swap video (Or83oiWeyJU), artifact diagnosis video
   (0lkXeV4V8KU). Why: user explicitly asked for these clues.
5. **vram-swap** — GDDR6 module replacement on RTX 30-series: exact chips (Samsung
   K4ZG0836BC, Micron MT51K256M32 etc.), package/pitch, donor vs new chips, compatibility
   across vendors on the same board, stencil + temperature profile, why VRAM needs no
   firmware, pad-lift and underfill pitfalls, post-swap testing. Why: likely needed fix #1.
6. **reball-core** — GA104 core reball: ball size/pitch, stencil sources, leaded vs lead-free
   balls, preheater + hot-air profiles, direct-heat vs IR, success/durability rates, when
   reball is the WRONG fix (degraded silicon, cracked die), reflow-vs-reball debate. Why:
   likely needed fix #2.
7. **diagnostic-tools** — Software: memtest_vulkan (github GpuZelenograd), OCCT VRAM/3D+VRAM
   tests, FurMark/3DMark, GPU-Z/HWiNFO logging, nvidia-smi/ECC-style error counting, DDU
   clean + driver isolation, vBIOS reflash (nvflash/Technik's GPU BIOS tools, TechPowerUp
   BIOS DB), artifact pattern taxonomy (checkerboard/smear per-memory vs full-screen = core).
   Hardware: multimeter resistance/shorts on rails, 12V/0.9V/VRAM rails (1.35/1.5V), thermal
   camera, freeze spray, microscope, programmer. Why: user explicitly asked for diagnostic tooling.
8. **bench-equipment** — BGA rework bench for DIY GPU repair: hot-air stations (Quick 861DW,
   Puhui, Aoyue), preheaters (ZD/KFR series, BGA heaters), IR stations, microscopes, stencils
   + solder balls (0.4/0.45mm) vendors, flux, solder paste, kapton, syringes; realistic cost
   tiers; where creators buy. Why: user must know what to buy for either fix.
9. **criticism** — Counter-evidence: "reball fixes artifacts" skepticism; core degradation is
   often terminal; BGA repair durability stats; economics (used 3060 Ti value vs repair cost
   / service cost ~$?); professional repair services' take (TrilexFix etc.); risks of DIY
   (pad lift, warping, killed card). Why: user must not sink $500 of gear into a dead core.
10. **latest** — Latest developments 2024–2026: PGTBoardView launch/coverage, GA104 core &
    GDDR6 chip availability/prices, new repair videos on this exact Zotac card, LHR-era
    failure retrospectives, repair service pricing, any recalls/batch discussions. Why:
    freshness; the ecosystem moved since 2021.

## Round plan
- Round 1: all 10 sub-questions above (2 lame + 2 ampere at a time, refilled on notices).
- Laptop pass for blocked pages (YouTube pages, paywalled schematic sites, Discord/Reddit
  login walls) after round 1 collection.
- Gap review → round 2 follow-ups → maybe round 3 (user wants exhaustive: 3 rounds).
- Fact checks (≤12 key claims) → writer → critic review → report.

## Round 2 sub-questions (from critic gap review, 2026-11-06)
R2-1 channel-disable-salvage — 8GB→6GB channel-disable as cheap repair path (vlab GA104 channel-disable VBIOS, TPU 316166/331799, badcaps 3832009, VideoCardz Paulo Gomes 3070 mods, signing/nvflash reality, hardware changes, perf penalty, cost vs 8-chip swap).
R2-2 zotac-strap-locations — physical RAMCFG strap location on Zotac Twin Edge or prove undocumented (vlab t=138116, CG142S/V390 nets → TPU high-res photos mapping, DMM continuity method). (Partly overlapped by vlab-straps worker.)
R2-3 nw-drive-archive-content — enumerate NW Drive All.zip (1.17GB, unzip -l), straps.png, Power Sequence.jpg, GDDR6 GDDR6X.jpg, compatibility list Nvidia.pdf, Disable Memory Channel 30 series.zip contents.
R2-4 warranty-rma-route — Zotac warranty term/registration, EU statutory, void-by-opening, RMA outcomes 2024-26, any X005 service program, Warranty Week surge effect.
R2-5 zotac-memory-population — which memory the ZT-A30610H-10MLHR actually shipped with (dated photos/GPU-Z reports/TPU 296633, marking/date-code reading).
R2-6 artifact-pattern-map — evidence-backed artifact pattern → fault map (2020-2026 tech sources, captured photos with confirmed diagnoses, mark unproven mappings).

## Fact-check queue (critic key claims; verdicts → verification.md)
C1 straps-not-bios (fold with laptop-2 TPU 342007 + check worker) | C2 RAMCFG table transfers to Zotac (local PDFs + vlab) | C3 tweezers-strap frames (orchestrator frames check) | C4 X005 CS-status doctrine | C5 replace-all-8 durability | C6 badcaps bridged-balls/0.05mm | C7 FBGA-180/0.45mm numbers | C8 LCSC $8.93 price | C9 £70 flat-rate repair | C10 used 3060 Ti value conflict | C11 MATS min-clock claim | C12 no-Zotac-schematic negative (fold with laptop-2 badcaps search + R2-3 All.zip).
