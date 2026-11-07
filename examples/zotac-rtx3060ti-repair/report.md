# ZOTAC Gaming GeForce RTX 3060 Ti Twin Edge OC LHR — Board-Level Repair Reference

**Date:** 2026-11-06 · **Scope:** board identification, schematics/boardview availability, diagnostic tooling (software + MATS/MODS), the GDDR6 strap/vendor-swap procedure, memory-chip swap and core reball, equipment and parts (Nov-2026 prices), channel-disable salvage, economics, and what GPU-repair creators (NorthWest Repair et al.) actually published about this card family. Written for a competent DIYer with soldering/BGA-adjacent experience. All prices are Nov-2026 snapshots; stock is thin because of the 2026 DRAM crisis.

---

## 1. Executive summary — the diagnosis call

Your symptom — **artifacting + crashes that got progressively worse even while you were underclocking** — is the textbook signature of progressive physical degradation, not a driver problem: downclocking only masks marginal memory cells, and the working underclock window shrinks until the card is unusable (a documented case went from −1000 MHz offset to −330 MHz before dying [97]; a Zotac 3060 Ti owner's "stretched texture and polygon line artifacts… freeze + driver crash" thread is nearly identical to your description [181]). On the RTX 3060 Ti specifically, bench technicians put **degrading GDDR6 first** in failure frequency — "By far the most common… early Hynix X005 memory that naturally degrades over time" — with dead cores "incredibly rare" [5].

**But the population of your exact card is unconfirmed.** The Twin Edge shipped with Samsung K4Z80325BC-HC14 at launch [6][130], and Hynix-equipped Zotac 3060 Ti variants existed from mid/late 2021 [123], yet no readable chip-marking photo of a Twin Edge OC **LHR** exists anywhere public, and the TPU spec pages carry no vendor note [123][157]. So the call is: **probable progressive GDDR6 (X005-class) degradation, to be confirmed by measurement — not assumed.** If your chips turn out to be Samsung or benign Hynix (H56C8H24A1R-S2C), the diagnosis reopens toward the GPU core/IMC, the LHR-only auxiliary LDO, or the memory rail.

**10-line decision path for this card:**

1. **Step 0 (no soldering):** warranty check (EMEAI 3+2 registration can still be alive), GPU-Z memory-vendor field, macro photos of all 8 chips (they are all on the front side [6]), temps/logs [39][40][6].
2. Confirm hardware: artifacts in BIOS/pre-OS = hardware; run memtest_vulkan + OCCT Combined 3D+VRAM [22][23].
3. Discriminate by clock: memory −300…−500 MHz fixes it → GDDR6-side; core/temp-dependence → core/VRM/thermal [22].
4. Get the go/no-go instrument: **MODS 455** boot stick (GA104 row = 455 in the version table) [19][86].
5. Run MATS (≤256 MB — bigger results are non-informative [28]) then **MODS stress: `-test 178 -dramclk_percent 110 -loops 20`** (fallbacks 118/94/242) [27].
6. One bank faulty → that chip (but public tools **cannot** name the single dead X005 chip — the shop-proven path is replace **all 8**) [19][27][5].
7. Two chips of one channel weak → channel periphery: termination/strap resistors, bridged balls under the core, or IMC — measure the channel's peripheral resistor network before condemning anything [10][20].
8. All channels → memory rail or core/IMC; card is usually not worth repairing [19].
9. If Hynix −005 confirmed → **8× Samsung K4Z80325BC-HC14 (~$90/set) + strap change (measure straps first!)** [44][13][2].
10. Economics: pro repair ≤ ~$190 → do it; > ~$270 → replace; DIY gear ($400–700) is only rational if you value the skill/bench for other cards [73][78][56].

**Do this first (step-0 checklist):**

- [ ] **Warranty:** Zotac US = 3 yr max for 30-series (2+1, registration within 30 days) — expired by 2025 for a 2021/2022 card; **EMEAI = 3+2 yr (5 total) with product registration** — Zotac "strongly recommends" registering for the full 5 years; the exact EMEAI registration deadline is not stated on the policy page (the 30-day rule is the US text) — if you registered, coverage can still run into 2027; check your zotac.com account [39][40][183]. Opening the card is explicitly *not* a void in the USA; reflow/BIOS mods/third-party repair void everywhere [39][40].
- [ ] **GPU-Z → Memory Vendor** (Samsung / SK hynix / Micron). Vendor yes, batch no [98].
- [ ] **Macro photos of chip markings** (front side only): line 1 `H56G32CS4D` + line 2 `X005`/`005` = the bad batch; benign Hynix is `H56C8H24A1R S2C`; Samsung reads `K4Z80325BC-HC14` [98][123].
- [ ] **Photograph your PCB back side** (backplate off) around the die at 2–4× with the die orientation arrow visible — no public back-side photo of the LHR Twin Edge exists, and the strap resistors live there [157].
- [ ] **Temps:** HWiNFO core/hotspot; note VRAM temperature is *not* software-readable on desktop GDDR6 30-series — use an IR thermometer on the chips [95][96].
- [ ] **Visual under magnification:** check the GS7155NV LDO's legs (one forum member found blobbed solder shorting pins on this exact board), caps near the PCIe edge, 8-pin burn [7][8].
- [ ] **Back up your vBIOS** (`nvflashk --protectoff` then `--save backup.rom`); there is no dual-BIOS switch on this card [38][37].

---

## 2. Know your card

| Item | Fact | Source |
|---|---|---|
| SKU | ZT-A30610H-10MLHR (OC LHR); non-OC LHR = ZT-A30610E-10MLHR; AMP White LHR = ZT-A30610F-10PLHR | [1] |
| Die | **GA104-202-A1** (LHR); non-LHR 3060 Ti = GA104-200-A1 (read from a die photo: "NVIDIA / TW 2039A1 / … A104-200-A1" on the review board) | [1][6] |
| PCI ID | **10DE:2489** = RTX 3060 Ti LHR (2486 = non-LHR; 248E = GA103-based variant) | [4] |
| Memory | 8 GB = 8 × 8 Gbit GDDR6, 256-bit, 14 Gbps / 448 GB/s; **all 8 chips on the FRONT (component) side** around the die (3 left / 3 right / 2 bottom per the TPU forum PCB photo) — designators M1–M8 largely legible at native resolution in that photo (left column M1/M3/M4, right column M2/M5 + one label not legible, bottom row M8/M7 + one reading M6-or-M9); back side = MLCC decoupling only | [1][6][157] |
| Power | 200 W TDP (max ~220 W), **single 8-pin** on the retail card — the 12VHPWR melt problem does not apply to this card (the documented 3060 Ti melt was a China-only ASUS variant shipped with the wrong cable). Note: TPU's DB entry lists "1x 12-pin, 1x 8-pin" connectors for this SKU — treat that as a database quirk of the reference-design entry, not the retail reality [1][8][157] |
| PCB / board number | **PG190 SKU 10** per the TechPowerUp database for both LHR SKUs (b9024 non-OC, b9025 OC) — the NVIDIA RTX 3060 Ti reference design shared by 213 listed retail boards; Zotac's layout is nonetheless a custom AIC implementation, and **no board-code silkscreen exists on the bare board** — identity comes from the TPU DB + QR/serial stickers only (0U94017664 / T9N630510Z8 read on the LHR PCB photo). 2-slot; 242 mm length (222 mm without bracket), 112/116 mm height, 38 mm | [157][1][7] |
| Core VRM | 6-phase, uPI **uP9512R** PWM + **AOZ5311** DrMOS (TechPowerUp's own circuit analysis; earlier snippets saying "Sinopower for core" are wrong — Sinopower is the memory side) | [6] |
| Memory VRM | 2-phase, uPI **uP1666Q** + Sinopower **SM7342EKKP** DrMOS | [6] |
| LHR-only part | A **Gstek GS7155NV** 3 A ultra-low-dropout LDO present on the LHR PCB and absent from non-LHR photos (identified in the TPU PCB-image thread: "Guys it's Gstek 7155 chip"), on the **front side in the small-signal strip near the PCIe edge** (neighbours: R6150 + a `000` jumper, C81/C80, U6/U8, JT3, C150/C160); one forum member reported a board with blobbed solder shorting its legs. It is a power part, not a hash limiter — the LHR limiter was a vBIOS/driver handshake, removed in driver 522.25 (Nov 2022) | [7][8][126] |
| Strap location | **No strap-resistor cluster exists on the front side** — all four die-to-memory gaps in the only public LHR PCB photo (TPU attachment 385854, 3024×4032, inspected at native resolution) contain only MLCC decoupling; GA104 convention puts the RAMCFG straps on the **back side** around the die, and **no public back-side PCB photo of a Twin Edge LHR exists anywhere** — you must photograph your own card's back side (see §6.3) | [7][157] |
| Dual BIOS | **None** — a bad flash is a hard brick without a programmer/SOIC8 clip recovery path | [38][37] |
| vBIOS | Verified TPU entry 94.04.46.40.0E, subsystem 19DA:6630, listed with multi-vendor (Hynix/Micron/Samsung) memory tables; the b9024/b9025 spec pages carry **no memory-vendor note** — LHR boards shipped with several vendors | [36][157] |
| Layout (frames seen) | CmdrSoyo's Twin Edge PCB overview: die centre-left, ~6-choke core-VRM row left of the die, memory right of the die + underside | [9] |

**Board-family truth (corrected late in this run):** the Twin Edge OC LHR's board number is **PG190 SKU 10** (TechPowerUp gpu-specs b9025; non-OC LHR b9024) — **PG190 is the RTX 3060 Ti reference family; PG142 is the RTX 3070 (GA104-300) reference**, so the earlier working assumption "PG142 = the 3060 Ti platform" was wrong and the proxy priority in §5 is reordered accordingly [157]. **PG152 is the Blackwell RTX 5060 board** — any "PG152" for this card is a mis-citation [2]. (One loose end: the waterblock compatibility list in NorthWest Repair's Drive folder groups the FE 3060 Ti under PCB family "1G142" [86]; where sources disagree, the TPU database entry for the actual Zotac SKU governs [157].) Also beware GA103-based Zotac 3060 Ti "-X" China variants when reading markings [12]. TechPowerUp never reviewed the Twin Edge **LHR** (the review URL 404s) — only the non-LHR Twin Edge review exists, and that board shows **Samsung K4Z80325BC-HC14** chips, which matters for the population question in §3 [157][6].

---

## 3. Is it memory or the core?

### 3.1 The X005 failure doctrine — what is solid, what is folklore

**Solid (multiple independent shops, 2022→2026):** the 3060 Ti failure wave is consistently attributed by CIS, German (gpufix/KrisFix) and US (GPU Solutions) repair shops to SK hynix GDDR6 of the **-005 / "X005" batch** — a real, orderable part (H56G32CS4DX-005, 8 Gb ×32, 180-ball FCBGA) [5][15][123]. GPU Solutions (2023): "SK Hynix memory with the manufacturing code X005 have been found to have a defect … They have since resolved this issue in the later batches" [15]. Field behaviour: "the video memory malfunction mimics the video chip malfunction. The memory even passes special technological tests… after a while another chip fails. A radical solution — replace all Hynix memory with memory from another manufacturer, such as Samsung" (LTT repair-shop report, ~30 cards/month, 2022) [6]. Sustained 90–100 °C VRAM temps on weak coolers (the Twin Edge is one) are a co-factor even the doctrine's own origin source admits [14][6]. The batch window (Sep 2021 – Dec 2022 per an MSI forum moderator) covers essentially all Twin Edge OC LHR production after ~mid-2021 [125][123].

**Folklore (corrected per fact-check C4):** the popular "CS = pre-release customer sample, MP = the fixed revision" layer is **not supported** — SK hynix's own distributor catalog tables list H56G32CS4DX005 as **MP** status, and "CS" inside that OPN decodes as die-gen C + speed code S4, not a status field; the story traces to one 2022 CIS blog post [127][14]. What you can actually read on a chip is line 1 `H56G32CS4D` and line 2 `X005`/`005` — there is no CS/MP marking on the package [14]. No X005 recall or service program exists from hynix, NVIDIA or Zotac [14][41][42].

**Population of *your* card is unconfirmed.** Launch Twin Edge/Twin Edge OC (Dec 2020, non-LHR) = Samsung K4Z80325BC-HC14 (named in two reviews — the TPU review board's die reads GA104-200-A1) [6][130]; Hynix-equipped Zotac 3060 Ti variants existed from mid/late 2021 (mining-community threads) [123]; no readable Twin Edge OC LHR chip-marking photo and no GPU-Z vendor screenshot was found anywhere public [123]. The badcaps log of this exact card class never states chip markings [10]. **If your card is Micron, the X005 doctrine does not apply and the diagnosis reopens (core/IMC more likely)** — non-Hynix 3060 Ti cards do also fail [129].

### 3.2 Symptom-profile match for your card

- Progressive artifacts + crashes that keep worsening *under underclocking* = permanent cell/silicon decline; the underclock band-aid shrinks (−1000 → −330 MHz case) [97], and r/GPURepair's standing line is "underclocking is rarely a permanent fix and the degradation usually progresses" [182]. A Zotac 3060 Ti with exactly your story (stretched texture/polygon-line artifacts, clean benchmarks, stable again after memory downclock) is documented on LTT [181].
- Counter-signals to keep honest: the same symptom family also appears from GPU-side faults. On vlab, a Palit RTX 3070 with texture/geometric-extrusion artifacts whose memory was replaced and **MATS/MODS passed even at `dramclk_percent 100`** was diagnosed by two named engineers as *core*, not VRAM ("Such artifacts have nothing to do with video memory. It's a GPU problem") [105]. And the closest published Zotac 3060 Ti LHR case (vlab t=153411 / badcaps 3821485) had channel-B-only errors that survived both a B0/B1 chip swap and a full GPU reball — read as signal-integrity/termination, with IMC damage still possible [10].

### 3.3 Artifact-pattern mapping — folklore-grade, use with care

There is **no manufacturer or peer-reviewed artifact-shape → fault taxonomy**; practitioners themselves call the visual patterns "very conditional" [109][104]. What survives checking:

- **Artifact *colour* is a myth** ("red for overheating, green for the driver… the colour depends mainly on the image being displayed"); shape and timing carry the signal [104].
- **Timing:** artifacts in BIOS/pre-OS = hardware; Windows-only-on-desktop = driver/settings; games-only-after-minutes = thermal/VRAM/power [104].
- **Shape (weak prior):** random bit-flies/localized corruption or fixed blocks tied to one MATS bank → memory-side (a green-lines card with >1K errors on a single MATS bank was fixed by replacing that chip) [107]. **Geometric/stretched/repeating extrusions with clean MATS/MODS at full DRAM clock → GPU-side** [105]. Fixed lines can even be a shorted decoupling MLCC on the memory rail, not the chip at all [108].
- **Screen-region ↔ channel mapping is unsupported folklore** — the framebuffer interleaves across channels; treat any "quadrant = channel" rule as a guess [109].
- The only trustworthy discriminators are **test-based**: MATS/MODS pattern + clock-dependence + rail measurements [105][19]. **No quantitative DIY success-rate data exists anywhere** for any of this.

### 3.4 Differential list (this board family)

| Candidate | Evidence for | How it shows / how to test |
|---|---|---|
| **Degrading GDDR6 (Hynix −005)** | #1 frequency on 3060 Ti per bench techs [5]; matches your progressive-worse-under-underclock profile [97][98] | MATS/MODS per-channel pattern; mem-clock dependence; chip marking [10][22] |
| **GPU core / IMC** | vlab t=156010 (geometric artifacts, clean MATS @100% = GPU) [105]; vlab t=135249 (channel-C1 errors unchanged by chip swap *and* GPU reball = GPU-side) [33]; Gainward case where >250 MB MATS "all-channel errors" were bogus and memtest_vulkan was clean → driver-init/GSP side [28] | MATS/MODS at dramclk 100–110%; memtest_vulkan clean-but-crashing points away from cells [28] |
| **Channel periphery (termination/strap resistors, bridged balls under core)** | The exact-card badcaps/vlab case: both B-chips weak, WCK offsets 2/16 pattern; ruzalit: "Check the resistor values in the channel-B memory peripheral network"; DynaxSC: two joined balls under the GPU shorted two lines of one channel [10] | NVMT WCK/DQ margins; DMM on channel-B obvyazka; inspect under-GPU balls if the core comes off [10] |
| **Aux LDO GS7155NV (1.8 V-class IOVDD_PROT rail)** | LHR-only part on this PCB; a forum member saw botched solder shorting its legs on an LHR Twin Edge; PG142-family schematics have an "IOVDD_PROT LDO (NV3V3 OR 1V8 JUMPER)" page; a failing 1.8 V-class rail can stall the boot sequence or mimic instability [7][16][8] | Visual/solder inspection first; then OUT ≈ set rail, IN−OUT ≥ dropout, POK high; ~$1 part [16]. **Exact Zotac rail mapping is low-confidence** — treat as "check while open", not a diagnosis |
| **Power rails / VRM** | Zotac 3060 Tis also die of VRM burns: BitForge's Zotac 3060 Ti repair was a burnt 1R0 inductor/shorted 12V rail (frames seen) [17]; graphiccardrepairing's Zotac Twin Edge case = blown 12V PCIe fuse + shorted DrMOS [5] | Rail resistance-to-GND table + diode-mode each 12V input separately (see §4) [22][5] |
| **Thermal paste/pads, contact** | Repaste/repad alone does **not** fix degraded-cell artifacts (shop consensus) but does fix contact-driven instability; one LTT case restored stock clocks after repaste [97] | Hotspot−core delta, artifact threshold vs temperature [97] |
| **Sag → cracked BGA joints** | IPC-9704A physics; documented on 30/40-series boards; the Twin Edge is a light ~650 g board (unofficial figure, not a spec) so risk is lower, but real after repeated opening | Push/flex test during stress [65][22] |

### 3.5 Step-0 checklist (before any rework)

1. Warranty/EMEAI 3+2 registration check (zotac.com account); EMEAI extended claims go directly to Zotac, and mining use / third-party interference voids it [39][40].
2. GPU-Z memory vendor; chip-marking macro photos (front side only — swap is front-side work) [6][123].
3. Temps: HWiNFO core/hotspot + IR thermometer on VRAM (no software VRAM sensor on desktop GDDR6) [95][96].
4. Reseat; separate 8-pin cable (not a daisy-chain); another output/monitor; check BIOS-screen artifacts (pre-OS = hardware) [104].
5. Event Viewer timeline: Display 4101 / nvlddmkm 153; bugcheck 0x116/0x117 = GPU actually faulting [22]. Linux: Xid 119 (GSP timeout)/63/79 — note Xid 48/63/64 ECC/row-remap codes are datacentre features and their absence on a GeForce means nothing [28][106].
6. GS7155NV leg inspection under a microscope [7][8].

---

## 4. Diagnostic tooling

### 4.1 Software tier (do this before opening the card)

| Tool | What it does / how to use | Verdict rules |
|---|---|---|
| **GPU-Z / HWiNFO** | Memory **vendor** (not batch); core/hotspot/fan/clock logging. VRAM temp is not exposed on desktop GDDR6 — per-module readouts exist only for mobile GDDR6 and desktop GDDR6X as of mid-2026 [95]. Twin Edge undervolt reference point: 200→147 W, hotspot 90→82 °C via curve-lock [96]. | Vendor = Samsung → X005 doctrine probably N/A [123] |
| **memtest_vulkan** | Open-source Vulkan VRAM stress; 6-min standard test, log next to the .exe [21]. | Author's own rule: "If some errors are reported… the PC has hardware problems" — but VRAM-IC vs GPU chip is **not** separable in software [21]. `NEXT_RE_READ` endless errors = storage-cell failure, clock-independent; 12–20 of 32 bits flipped = data-bus style [21]. |
| **OCCT (admin)** | Combined tab: 3D Standard (shader 3, 100%, error detection ON) + VRAM at 95–100% allocation — stresses core+memory+PCIe together; error **count** is the metric, not visuals [23]. | OCCT VRAM fails within minutes while MODS/MATS pass = classic X005 signature [27]. |
| **FurMark / 3DMark / Superposition** | Validation & stress. FurMark **barely loads memory** — a clean FurMark run proves nothing about VRAM [99]. | Use post-repair, not for diagnosis. |
| **Event Viewer / Xid** | Windows: Display 4101, nvlddmkm 153, bugcheck 0x116/0x117 [22]. Linux: Xid 119 GSP-timeout / 62 PMU-halt seen on a dying 3060 Ti [28]; Xid codes 48/63/64 (ECC/row-remap) are datacentre features — their absence on GeForce is expected, not exoneration [106]. | Correlate with temps/load via Reliability Monitor [22]. |
| **nvflashk (backup)** | Ampere flashing needs the **nvflashk** fork (official nvflash 5.867 can't override internal board ID); Windows Core Isolation/HVCI must be off; `--protectoff` → **`--save backup.rom`** before any work; "you cannot permanently damage an NVIDIA GPU from a BIOS flash" — but with **no dual-BIOS switch** on Twin Edge, recovery is via iGPU/programmer [38][37]. | Backup = your identity card for later repair/flash decisions [38]. |

Clock discrimination: artifacts gone at memory −300…−500 MHz → weak GDDR6; changes with core voltage/temperature → core/VRM/thermal [22]. Bench hardware note: use an **Intel** test bench — a dead first PCIe lane shows on Intel but a Ryzen board "will start the card as fully working" [26].

### 4.2 MATS / MODS — the go/no-go instrument

MATS and MODS are NVIDIA's internal factory diagnostics; everything in the wild is a leaked community mirror, shared free inside repair communities [20][86][30]. **GA104 = MODS/MATS 455** per the compatibility table "by tony from NWR" in repair.wiki [19].

**Where to get it (all live-checked in this run):**
- NorthWest Repair's public Google Drive: `NVIDIA/MATS-MODS/Mods 455 RTX30.iso` (412 MB) plus 367/520 images; folder owner "T Tonycstech"; note in the folder: "If you paid for these files, you are an idiot. They are absolutely free." [86]
- GitHub mirror `YTEC-info/MATS-Nvidia-VRAM-test` — 4 RAR parts ~86 MB, raw download verified working 2026-11-06 [29].
- corex-service.ru/mats — Russian shop manual + Drive images (MATS 400 = RTX 20-era, **MATS 455 = RTX 30**) [26].
- levirepair.eu stick (mats367/400/455 + `nvmt_2020aug`) [30]; universal MATS binary for Maxwell–Ada via yadi (galkinvv) with the mods kernel-driver repack [118].

**Boot procedure:** Rufus, **MBR/FAT32**, BIOS **CSM/Legacy** on, display driven by an **iGPU** (or second card) when testing a display-less card [19][26][30].

**Commands (verbatim from repair.wiki / shops):**
```
./mods gputest.js -skip_rm_state_init -mfg      # boot MODS (repair.wiki) [19]
./mats -n 1 -e 50                               # memory-only; ≥5 MB, 50 recommended;
                                                # with display attached use ./mats -b 60 -e 70
                                                # to skip the reserved region (else false-positive
                                                # 32/33/40-64-72-96 write errors) [19]
./mods gputest.js -oqa -test 178 -dramclk_percent 110 -loops 20   # the stress recipe that pins
                                                                   # errors to 1–2 chips;
                                                                   # if 178 fails, try 118, 94, 242 [27]
```
Then read `mats.log` / `report.txt` / `mods.log`; in MODS logs, `NV_PFB_FBPA_training_cmd`: FBPA_0→channel A … last digit 2 = bank 0 faulty, 8 = bank 1, A = both (article notation; the same shop's video overlay prints 0/1/2/3 instead — notation differs by tool, same idea) [26][93][173]. NVMT (`./nvmt ts > log.txt`) gives WCK training offsets and DQ IB/OB margins per channel [30][173].

**Result interpretation (doctrine, consistent across repair.wiki, corex, GPU Solutions):**
- Channel numbering: for an N-GB card there are N/2 channels (8 GB → 4 channels A–D, 2 chips each, x1 = high byte / x0 = low byte); **modules are counted counter-clockwise from the corner OPPOSITE the golden arrow on the die** [19][26]. Channel-disable masks: A:0x01, B:0x02, C:0x04, D:0x08 [30].
- **One bank faulty → that chip** (or its pads) [19].
- **Both chips of one channel weak → IMC inside the core, pads under the core, channel termination/strap resistors, or bridged balls under the GPU** — the RTX 2060 example in repair.wiki (errors on D1+C0) was fixed by resoldering the chips back; the exact-card Zotac case says: measure the channel-B peripheral resistor network first [19][20].
- **All channels → memory rail/power or the core/controller**; card usually not worth repairing [19].

**Honest caveats (all load-bearing):**
- **MATS tests at the memory's minimum clock (~150–300 MHz, single-source figure from corex) and never loads the GPU** — that is why X005 cards "pass MATS, fail OCCT"; stress with `-dramclk_percent` (bounds ~50–150%) instead [26][27].
- **MATS results above 256 MB are garbage** — "mats results over 256MB are random, should be discarded as non-informative" (the memtest_vulkan author) [28].
- **MATS/MODS cannot name the single bad X005 chip**: "With available tools to the public, it is not possible to determine which X005 chip is dead… Only way… is to replace all X005 with samsung or micron and adjust the strap" (ssateneth2); NVIDIA RMA centers do single-chip swaps under NDA with an undisclosed method [27]. MODS also cannot distinguish chip-pads from core-pads — "that part you only discover during the actual repair" [173].
- Boot-stick behaviour: on a hard fault the stick may print patterns, show a red FAIL banner, and power the box off — that is a result, not a crash [93][19].

### 4.3 Bench-electronics tier (once the card is open)

- **Rail resistance-to-GND, unpowered, each 12 V input measured separately** (slot 12 V, 3.3 V, 8-pin are separate planes): VCore 0.2–3 Ω (low is normal); **Mem rail 20–120 Ω — unusually low ⇒ suspect VRAM**; PEX 10–80 Ω; 1.8 V several hundred Ω+; 12 V in kΩ (<100 Ω = input short) [22][24]. Boot sequence 12V→5V→1.8V→PEX→VRAM→NVVDD; a dead 1.8 V-class rail halts everything after it [5][24].
- **Power injection 0.5–1.0 V / 0.5–1.5 A current-limited + thermal camera** finds a shorted chip in seconds; a phase >20 °C hotter than its twin is suspect [22][153].
- **Push/flex test** during stress: transient fix = cracked joint [22]. **Freeze spray** on suspect areas for intermittent joints [22].
- MOSFET diode checks: S-D/G-D <1 Ω = dead; erratic/missing gate drive = driver/bootstrap, not the MOSFET [22].
- GS7155NV LDO check (§3.4): OUT at set rail, IN−OUT ≥ dropout, POK high, no droop under load; visual leg inspection first [16][7].

---

## 5. Schematics & boardviews — the key negative, and the usable proxy set

### 5.1 THE KEY NEGATIVE: no Zotac Twin Edge schematic or boardview exists publicly

Fact-check C12 graded this "strongly-supported negative for free/public sources." Evidence gathered:

- **badcaps.net file archive search: "Twin Edge" → 0 hits; "GA104" → 28 hits, none Zotac; "PG142" → 8 hits, all Gigabyte (3070 Gaming OC V1/V2/V3, Eagle OC, Vision OC)** [11]. Two live public requests for exactly this board remain unanswered: badcaps 3563068 ("Zotac Gaming GeForce RTX 3060 Ti Twin Edge OC", 2023) and a 2025-02-01 request; the laptechinfo.com request thread (2023-11-28) shows the request only — no replies visible to guests [103][11].
- **GPU Doctor** catalogue: "Boardview for the NVIDIA GeForce RTX 3060 Ti: 3 boards from ASUS and Gigabyte" — no Zotac [131].
- **schematic-expert.com**: the page *advertises* "ZOTAC Series: Twin Edge, AMP" but the actual download table contains only ASUS (CG142S, CG190P, TUF PG190-A02) and Gigabyte/MSI (PG142-B00 "V390 Decrypt", V397_*.cod) files — the Zotac line is SEO bait [102].
- **r/ZOTAC**: "Official public schematic diagrams directly from Zotac for the Twin Edge series are generally not released… by the manufacturer" [138].
- Broad EN/RU searches naming a Zotac 3060 Ti Twin Edge boardview/schematic file: zero hits [11].

**And no free PG190-family boardview exists publicly** — boardviews for this reference family are paid-only: PGTBoardView (subscription; catalog not statically verifiable; prices read in-browser: Individual **$9.99/mo, $28.49/3 mo, $53.99/6 mo, $99.99/12 mo**, Business $199.99/yr, 7-day trial) [132], GPU Doctor (exactly 3 RTX 3060 Ti boardviews — ASUS Dual/TUF, Gigabyte AORUS — browser viewing from $3, no Zotac) [131], realschematic's TUF bundle (51-pp PDF + .fz viewer + repair guide) [180]. Remaining unenumerated corners (honest limits): a **paid** Russian forum resource (сервискомп-анна.рф, 2025-12-10) sells "Zotac / Manli RTX 3060 Ti / 3070 Ti GA104 **DN651 N651** Схема + BoardView PDF" — paywalled, and DN651/N651 are Palit-family PCB codes whose mapping to ZT-A30610H is **unverified** (a possible few-USD lead, verify before trusting) [134]. Paid Telegram boardview libraries: not enumerated [134]. NorthWest Repair's 1.17 GB `All.zip` boardview folder was re-checked: **HTTP 404 — deleted**, permanently unenumerable [139].

### 5.2 The usable proxy set (GA104-family partner boards)

Repair proceeds with these as **net-name aids + your own high-res board photos**; expect designator mismatch vs the Zotac silkscreen (Zotac uses its own R61xx/R62xx/C1xx families — e.g. R6150 by the LDO, R232+`000` by the memory-rail inductor L46) [157][7]. Because the card's board number is **PG190 SKU 10** [157], the tiers are:

**Tier 1 — PG190 / PG190-A02 (the actual RTX 3060 Ti reference family, GA104-GA106):**

| Proxy | What it is | Where |
|---|---|---|
| **ASUS TUF RTX3060TI-O8G, PG190-A02 schematic (51 pp)** | PG190-A02 schematic of the same reference family; **p26 = "MISC: ROM, XTAL, Straps"** with the RAMCFG table and L=0 V / H=1.8 V / M=0.9 V definitions — the fact-check confirmed this table verbatim, so **this local copy is the right strap-code reference for this board family**. Local: `files/TUF_3060ti.pdf`, table crop `files/TUF_p26_tables.png` | free via schematic-expert (Drive links; PDF password = `www.schematic-expert.com`) [102][135] |
| **Gigabyte GV-N3060VISION OC-**12GD** PG190-A02 Rev 1.01 schematic (~1.5 MB)** | same PG190-A02 reference family but **GA106/12 GB (RTX 3060)** — useful for PG190-A02 net names, not GA104 pad positions | free at laptechinfo (download behind a JS "click spoiler 3 times" password) [174]; registration-gated at eletronicabr/pkbiosfix [135][176] |
| **EVGA232 PG190-A02 GA104-GA106 schematic (12.3 MB, 52 pp)** — the canonical PG190-A02 doc | covers GA104-200/-300 + GA106; title mixes an RTX 2070 name (mislabeled re-upload) — EVGA never officially published GPU schematics, so this is a leaked/second-source document | **paywalled/gated everywhere**: badcaps Premium [11], pc6.ca free-registration mirror [175], devicedb ~100 RUB, bioshelp non-refundable [175] |
| **Gigabyte GV-N306TGAMING OC rev 3.0 = LHR, 54-pp PDF + .fz** | the closest *purchasable* LHR-era doc (~€5.25) | realschematic.com [133] |

**Tier 2 — GA104-300 / 3070-family docs (strap CODE TABLE still valid — same GA104 ballout, FCBGA-2713 — physical layout not):**

| Proxy | What it is | Where |
|---|---|---|
| **MSI V390 / PG142-B00 schematic (54 pp)** | 3070-era GA104-300 board; p26 strap page incl. RAMCFG table + strap resistor pairs (R265/R722 etc.) + ball pins BM5/BN5/BP3/BP4/BR3/BR4. Local copy: `files/V390_PG142.pdf` | free via schematic-expert / pkbiosfix thread 10444 [102][135] |
| **ASUS CG142S (Strix 3060 Ti / 3070) BV (.fz) + SCH (57 pp)** | same GA104 platform; identical RAMCFG table; "IOVDD_PROT LDO" page. Local copies: `files/CG142S.pdf` | free via schematic-expert / pkbiosfix [102][135] |
| **ASUS CG142PL "SAM-HC14" boardview (.fz)** | boardview naming the Samsung strap config | badcaps attachment (login) [135] |
| **Gigabyte PG142-B00 (V390 decrypt), V397_*.cod** | Gigabyte 3060 Ti LHR-era boardviews | schematic-expert / badcaps [102][135] |

Two honesty notes: the pkbiosfix "V397_*.cad" boardview set uses MSI's V397 board code loosely for "3060/3060 Ti/3070 related variants" — verify before trusting on a PG190 board [135]; and the free gadget-manual.com NVIDIA Drive archive has **no PG190/30-series entries** on its index [179]. A useful trick from the PG190 finding: PG190 SKU 10 has **213 sibling retail boards** (TPU lists them, several LHR) — pick a sibling whose review has bare-PCB front **and back** photos and use its back-side photo as the strap-cluster proxy [157]. vlab doctrine (ruzalit) treats the GA104 strap **pad layout** as common across vendors ("такое же расположение") — only the resistor population/polarity differs per board [13]. Viewers: **FlexBV5** decodes .fz/.cad/.tvw with schematic-PDF sync [170]; OpenBoardView reads .brd only [137]; free web viewers: boardviewtrace.com / wrenchboard.cloud [118]. IndiaFix maintains a curated GA10x boardview/schematic collection (Telegram) [136]. The r/GPURepair megathread "Useful tools, resources & guides for GPU repair" is the standing community index [118].

### 5.3 The vlab.su path — where the Zotac-specific strap photo actually lives

vlab.su is the Russian-language repair forum where this card family is actively worked; its master strap-reference thread is **t=104925 ("Идея - справочник СТРАПов для видеокарт", 203 posts)** [13].

- **The one known Zotac Twin Edge LHR strap photo:** vidijus asked on 09-Oct-2025, "ZOTAC GAMING GEFORCE RTX 3060ti Twin Edge LHR 8GB… конфигурация для этой модели? SKhynix → SAMSUNG"; **DoktorVGA replied 18-Feb-2026 with an attachment** — the file, thumbnail and download are **not visible to guests**. Guest-readable confirmation of the exchange exists (search + page 7); no Wayback copy [13][166].
- **The wall:** vlab attachments require login **and ≥15 posts** (rule 9 verbatim: " Просмотр вложений… только после написания 15ти или более сообщений"), or paid access (10 points per attachment in the schematics subforums; 1 point per post earned) [166]. **Practical tip: register, make 15 real posts (or buy access), then the DoktorVGA image and the whole strap archive unlock.** A fresh account with 0 posts still cannot see it — plan to actually participate.
- Public escape hatch already exhausted: the only non-gated strap archive posted in that topic (Yandex Disk, volkOFF) contains a single blurry phone macro of an **Asus RTX 3060 12 GB (GA106)** board edge — no legible designators, no GA104 material; two other public Yandex strap links are dead (404) [142]. So **no public source settles the Zotac GA104 strap layout** — every real GA104 strap photo is behind the wall.

**Open vlab threads on this exact card family — self-service targets (read the text as a guest; attachments need the 15-post account):**

| Thread | ID | What's in it |
|---|---|---|
| rtx 3060 lhr отключить канал памяти (shadowww82) | t=150732 | LHR channel-C disable: "Not for LHR version sadly" — dead end, but the current-state answer [34] |
| Zotac RTX 3060 TI LHR 8GB (spyke11) | t=153411 | **The closest published case to yours**: Zotac 3060 Ti LHR channel-B saga, NVMT numbers, ruzalit's advice; attachments walled [20] |
| RTX 3060ti LHR → Замена GPU без LHR (yellowfox) | t=124374 | GA104-202→200 core swap: boots after reflash [149] |
| Справочник СТРАПов (master strap thread) | t=104925 | Zotac Twin Edge LHR strap photo (walled); Gigabyte/Aurora/MSI strap recipes; Samsung-code gotcha [13] |
| 30-series custom BIOS / channel-disable master | t=128402 | stax's reduced-channel ROM archive (non-LHR); YunicheK: LHR files "В открытом доступе нет" [31] |
| Zotac Twin Edge 3060 Ti BIOS flash size mismatch | t=130014 | BIOS flash quirks on this board [171] |
| ga104-202-a1 memory resistance without chips (liquid damage) | t=138116 | memory-line resistance values (attachments walled); resolved = GPU dead [167] |
| GALAKURO 3060 Ti LHR (May 2026) | t=155256 | GA104-202 LHR sibling board [172] |
| Gigabyte 3060 Ti strap designators | t=124951 | R218→R220 = one resistor for Micron; 3070 strap block does NOT transplant [119] |
| Palit 3060 8GB straps (Samsung 8/16 Gb gotcha) | t=132141 | wrong Samsung code → GPU-Z says Samsung but 4 GB [120] |
| Asus Strix 3060 Ti straps (Hynix→Samsung) | t=143916 | "move all straps right, away from the flash" (photo walled) [121] |
| MSI 3060 Ventus Samsung straps | t=149434 | GA106 strap photo (walled) [122] |
| GA104-202↔200 swap pad inversion | t=143188 | two GA104 PCB variants invert B1/C0 data pads [150] |
| 3060 Ti artifacts, channel C1 (Frennis) | t=135249 | chip swap + GPU reball changed nothing → GPU-side; YunicheK: no LHR channel-disable BIOS ("Нет.") [33] |
| Zotac 3060 Ti LHR channel B (spyke11 mirror of badcaps) | t=153411 / badcaps 3821485 | bridged-balls precedent; 0.05-under-nominal balls anecdote [10] |

Named vlab members worth watching/replying-to if you register: **DoktorVGA** (the Zotac strap reply), **ruzalit** (memory-periphery/BIOS expert), **ayobisinen** (Moscow, strap/soldering advice), **hoolyman** (Aurora 3060 Ti Samsung strap recipe), **Frennis** (channel-disable cases), **uncledim** (Samsung 8/16 Gb strap gotcha), **YunicheK** (BIOS modder), **stax** (channel-disable ROMs) [13][20][31][33].

---

## 6. The strap procedure (RAMCFG) — how a vendor swap actually boots

### 6.1 The code table

The RAMCFG[4:0] encoding was read **verbatim from three independent GA104-family schematic pages** (MSI V390/PG142 p26 — local copy `files/V390_PG142.pdf`; ASUS TUF PG190-A02 p26 — local `files/TUF_3060ti.pdf`; ASUS CG142S — local `files/CG142S.pdf`), corroborated by NorthWest Repair's straps poster (local `files/drive/fixed/straps_table_part.jpg`, from his public Drive) and 16 GB-mod writeups [102][86][144][146]:

| RAMCFG[4:0] | Density | Bus | Vendor / die |
|---|---|---|---|
| **00000** | 8 Gb | 256-bit | **Samsung C** (alternate Samsung code: 00011; Micron = 00001/00100, Hynix = 00010/00101) |
| 00001 | 8 Gb | 256-bit | Micron A |
| **00010** | 8 Gb | 256-bit | **SK hynix M** (stock code for Hynix 3060 Ti cards per the PG142/PG190 reference pages) |
| 00011 | 8 Gb | 256-bit | Samsung C (alternate code) |
| 00100 | 8 Gb | 256-bit | Micron A |
| 00101 | 8 Gb | 256-bit | SK hynix M (alternate) |
| 00110 | 16 Gb | 256-bit | Samsung M (the 16 GB mod code) |
| 00111 | — | — | blank |

Only **straps 2-1-0** matter on 8 GB 256-bit cards; strap levels: **L = tied to 0 V, H = tied to 1.8 V** — and **M ("middle") is a board convention, not a GPU tri-state**: the TUF PG190-A02 legend defines M as "Tied to 0.9V" via explicit jumpers, while NW's poster (from boards he measured) says "Medium = no resistor" (empty pad), and envytools documents only binary pull-up/pull-down sampling after reset [102][86][177]. Practical rule: treat a **missing resistor pair as the ambiguous state and resolve it by measurement, never by assumption** [177]. Strap pins are GPU balls BM5/BN5/BP3/BP4/BR3/BR4 (STRAP0–5) on the GA104 BGA [102].

### 6.2 Physical implementation

Each strap net is a **100 kΩ 1 % 0402 pull-up/pull-down resistor pair** (not 0 Ω jumpers, despite how they look): on V390/PG142, GROUP0 = resistor pairs R265/R722 (STRAP0), R262/R255 (STRAP1), R261/R727 (STRAP2), each pair pulling the strap net to 1V8 or GND [13]. **Hynix (00010 = L-H-L on PG142) → Samsung (00000 = L-L-L) = move STRAP1's resistor from its 1.8 V pad to its GND pad** — one 0402 move [13][102]. (On a board whose measured stock state is inverted — the vlab precedent — the direction flips accordingly: this is why you measure first.) GPU Solutions' workflow confirms the mechanics on real boards: chapter "Resistance Check and Straps Rearrangement" with microscope + tweezers moving the small resistors (frames seen at 26:29–30:48 in Or83oiWeyJU; C3 verdict: the action, yellow-circled cluster, hot-air pass and post-work DMM checks are visible; designator-level detail is not legible at storyboard resolution) [90].

### 6.3 THE MEASURE-FIRST RULE (this is where DIY attempts die)

**Where to look on THIS board first:** the front side of the LHR Twin Edge has **no strap cluster** — the only public LHR PCB photo (TPU forum attachment 385854, 3024×4032, zoomed at native resolution across all four die-to-memory gaps) shows only MLCC decoupling fields and two jumper-style references (R232 + `000` by the memory-rail inductor L46; R6150 + `000` by the GS7155NV) — **no 3-resistor-pair strap group anywhere on the front**. GA104 convention puts the RAMCFG straps on the **back side** around the die (as on DoktorVGA's V397/V390 boards), and no public back-side PCB photo of a Twin Edge LHR exists — **photograph your own card's back side** (backplate off, die orientation arrow visible) and expect Zotac's own refdes families (R61xx/R62xx/R1xxx near the die's back-side corner), not Gigabyte-style 4-digit refs [7][13].

**LHR is not a strap.** The RAMCFG strap tables are structurally identical between PG190 SKU 10 (LHR) and PG190-A02 (non-LHR) documents; LHR identity rides on the PCI device ID 10DE:2489 + vBIOS/fuses — no public PG190 doc or envytools page shows any hash-limiter strap [178][177][157]. So the TUF PG190-A02 strap table governs the **code semantics** of your LHR board; only the physical resistor positions are Zotac-specific — which strengthens, not weakens, the measure-first rule.

Fact-check C2 downgraded "the table transfers to the Zotac" to **partly**: the *code table* is NVIDIA reference-level and transfers (verified verbatim in the PG190-A02 TUF schematic we hold locally, and again in the PG142/CG142S pages); **the physical strap state does not**. Evidence:

- NW's own poster legend: "**STRAPS ORDER IS SPECIFIC TO CARD MFG** … Always refer to schematic" [86].
- **LHR inversion precedent:** on a Gigabyte V397 (Vision LHR) the stock Hynix straps measured **H-L-H** where the V390 schematic says **L-H-L** — different Hynix die variants ship with different encodings; the OP's per-schematic strap set passed MATS but failed MODS 118/178/92 and driver install (vlab t=130309) [140].
- The 3070-style strap **block** (R265/R262/R261 in one place, pulled to 1.8 V) does **not** map to 3060 Ti boards — "in 3060ti the resistors with these designators are scattered around the board and not pulled to 1.8 V as the 3070 schematic shows" (vlab t=124951); the Gigabyte worked example is **one resistor: Strap2 R218→R220** for Micron, Gigabyte-specific designators [119].
- **NW's straps poster board is probably not a Twin Edge:** its designators (R215–R231, C213, Y1, MEC46) do not match the Twin Edge silkscreen seen in photos (R6150, C81/C80, U6, JT3; 4-digit refs on the review board) [134][7][6].
- The Samsung code may need to be **00011 instead of 00000** depending on which timing table the vBIOS exposes — "there are two types of samsung 8gb… 00000 and 00011. Depends on bios"; wrong code → GPU-Z reports Samsung but the card misbehaves or reports wrong size (a GA106 case reported Samsung-but-4 GB after the wrong Samsung code) [13][120].

**Rule: with the card powered, probe your own board's strap pads with a DMM (voltage mode) and record the actual L/H/M state before moving anything; then derive the minimal resistor move to the target code that the vBIOS supports.** Where designators are unknown, vlab techs find the strap pads by probing for the 1.8 V pull-up line from the GPU-side pads ("искал по контактным площадкам… чтобы на другом контакте была линия 1.8В") [119].

### 6.4 No vBIOS reflash needed — but the vBIOS must expose the target timing table

Fact-check **C1: confirmed (with nuance)** — cross-vendor swaps are set by straps, not by flashing another vBIOS. Independent statements: ssateneth2: "replace all X005 with samsung or micron **and adjust the strap** so it boots the correct timings"; khoavd83 (repair specialist): "You don't need a new bios. You change a few strap resistors"; TPU 342007 replies: "no VBIOS change is needed… Some resistor can be moved to make GPU-Z recognize Samsung… Samsung just works even if recognized as Hynix"; and the GPU Solutions workflow (swap → straps → MATS → boot → stress) never reflashes (frames) [27][143][90][92]. The Zotac Twin Edge OC LHR stock vBIOS (94.04.46.40.0E) is listed with Hynix/Micron/Samsung support, so the Samsung table should already be present [36]. **Do not cross-flash other vendors' vBIOSes** — device-ID/board-ID mismatch bricks or no-displays; nvflashk exists for legitimate board-ID overrides, and with no dual-BIOS switch keep your `--save` backup and an SOIC8 clip programmer nearby [38][143].

---

## 7. GDDR6 chip swap — procedure, parts, prices

### 7.1 Package facts (primary datasheet, corrected per C7)

All candidate chips are **FBGA-180, 14.0 × 12.0 mm, 0.75 mm ball pitch, ball Ø 0.48 ± 0.05 mm** (Samsung K4Z80325BC Rev1.3 datasheet, MO-328 variation; Micron land pattern identical: FBGA-180_L14.0-W12.0-P0.75) [147][148]. The "BGA-242/0.8 mm" figure floating in early notes is wrong [147]. **Stencil spec to buy: "GDDR6 / BGA-180, 0.75 mm pitch, 0.45 mm balls"** — 0.45 mm sits inside the 0.43–0.53 mm datasheet tolerance; vendors (gpufix/KrisFix, parts4laptops, AMAOE) all ship 0.45 for GDDR6 [147][49][169]. Not underfilled [91].

### 7.2 Procedure (converged from GPU Solutions frames, rupz's first-person log, shop guides)

1. **Prep:** conformal-coating/underfill check (GDDR6 here is not underfilled); flux around; shield nearby passives with Kapton/aluminum foil [57][64].
2. **Preheat the board to ~100–150 °C bottom-side** (IR plate or hotplate; GPU Solutions runs ~120 °C base preheat to protect the pads, and published shop guidance spans 100–180 °C overall) [91][24][57].
3. **Hot air 300–400 °C**, moderate flow, nozzle ~1–2 cm above the chip, circular motion; lift only when the chip floats freely — never pry (pad ripping) [91][64][57].
4. **Clean pads:** solder wick + flux, then flush/residue-clean; inspect every pad under the microscope — **wick-stuck pad rips and leftover old solder causing shorts are the two classic first-timer failures** (rupz's own log) [64].
5. **Reball new/ donor chips** with the GDDR6 stencil and **0.45 mm balls** (or buy pre-balled): stencil aligned, flux, balls, hot air till shiny spheres, clean [64][91][57].
6. **Place + reflow** with bottom preheat; flux first; align under microscope; reflow until self-centering; **clean flux residue thoroughly — flux residue reads as leakage/instability later** [57][64].
7. **Post-bake** after lead-free rework is industry practice; no Twin-Edge-specific recipe was published in any source read this run (gap).
8. **Validate:** resistance checks → MATS → boot/GPU-Z vendor → OCCT/FurMark/3DMark stress (the shop sequence) [90][92][19].

**Flux/temp cautions:** use no-clean T4/T5-class flux (genuine NC-559-V3 or Alpha OM-338 class); **leaded balls on a lead-free board = mixed-alloy "cocktail" — industry guidance says don't** (badcaps techs: "do NOT mix leaded with lead-free", "everything should be lead free") [57][66]. Overheating chips ("I have baked chips by overdoing the heating") and dislodging passives with high airflow are the other documented failure modes [64][56].

### 7.3 All-8 replacement doctrine (C5: confirmed community consensus)

Replace **all 8 chips**, not the failed one: LTT CIS shop ("after a while another chip fails… replace all Hynix with Samsung"); ssateneth2 (you *cannot* identify the dead chip with public tools anyway); NW Repair on Reddit ("X005 are faulty at the factory that develop issues overtime. Replace every single chip"); GPU Solutions ("if we leave any of these memory, card will return with the same memory issue") [6][27][15][90]. Counter-consideration: the exact-card badcaps case shows channel-restricted errors can be **bridged balls, not chips** — so localize with MATS/MODS first; if the pattern is channel-restricted with suspect margins, check the periphery before ordering chips [10].

### 7.4 Shopping list (Nov-2026 snapshot; prices verified this run — C8 corrections applied)

| Item | Price / stock (2026-11-06) | Notes |
|---|---|---|
| **Samsung K4Z80325BC-HC14** ×8 (target part) | **LCSC C2920181: ladder 1+ $11.32 / 10+ $10.75 / 30+ $9.76; stock 47 pcs → realistic 8-set ≈ $90**. The "$8.93" figure is the unreachable 112+ tier | [44] |
| same, broker route | Findchips: Win Source 5,985 pcs; $13.23 @8+ → **~$106 for 8** | [45] |
| same, AliExpress | $8.50–10.50/pc (tracker median) — **remarked/used-chip risk**; eBay 10-pc lots similar | [151] |
| **Micron D9WCW (MT61K256M32JE-14:A)** ×8 | **LCSC C1352195 OUT OF STOCK** (1+ tier $15.52 → ~$124); DigiKey ~$12.59/pc (~$100/set, snippet); gpufix/KrisFix €24.90 new (snippet) → **8-set ≈ $100–124** | [48][47][46] |
| GDDR6/BGA-180 stencil, 0.75 pitch, 0.45 balls | gpufix/KrisFix DDR6-SM 90×90 direct-heat **€6.49**; parts4laptops single stencil similar; JoshiRepair 9-slot reballing jig **£80** | [49][169][51] |
| 0.45 mm GDDR6 balls | the trade's standard size for GDDR6/BGA-180 (parts4laptops ships 0.45 mm as the GDDR6 practice size); JoshiRepair pre-balled Hynix S2C module £17.99 as a price anchor | [169][51] |
| **GA104 core stencil** (if core comes off) | gpufix/KrisFix GA104-SM **Ø0.45 mm, €32.99** — buy GA104-specific; GA104 ball pitch was never confirmed by a primary source (2713 vs 2714 both circulate) — do not hand-pick pitch | [50][147] |
| Flux | **NC-559-V3 genuine only from Inventec (DE)** — the brand is faked heavily elsewhere; Alpha OM-338-PT at JoshiRepair from £10 | [52][51] |
| SPI recovery | CH341A + SOIC8 clip (for a bad vBIOS brick; no dual-BIOS on this card) | [38] |
| Optional | 20 A SMD fuse kit (3060 Ti 12 V fuse cases exist) €3.80; GS7155NV LDO ~$0.92–few-€ | [49][16] |

**"Don't buy used cheaps":** vlab's Moscow tech on a failed Micron swap — "your used d9wcw can be dead that way (dont buy used cheaps)" [140]. Donor chips from scrapped cards are the counter-route: a parts card ($60–150, §11) can yield a full known-history set. Stock is thinning in the 2026 DRAM-crisis environment (LCSC down to 47 pcs; Micron 0; class action vs the three DRAM makers filed Jun-2026) — **buy chips early; expect price creep** [44][48][156].

### 7.5 Bridged-balls hazard precedent on this exact card

badcaps thread 3821485 (Zotac RTX 3060 Ti LHR, GA104, edited 2026-02-11): after a full GPU reball + B0/B1 chip swap, channel-B errors persisted; the cause found was **two solder balls under the GPU that had joined during reseating, shorting two memory lines of one channel**; the tech (DynaxSC) now reballs with balls **0.05 mm under nominal** to prevent ball-joining. C6 verdict: **partly-confirmed — one case report, one tech's practice, not a standard**; print as anecdote [10]. The NVMT signature to recognize: channel-B-only WCK offsets (WCK01=2, WCK23=16, WCK45=2, WCK67=16) with asymmetric DQ IB values (2/16/47/58/61, OB≈2) → signal-integrity/termination, IMC damage still possible; ruzalit's whole advice: "check the resistor values in the channel-B memory peripheral (decoupling/termination) network" before declaring anything dead [20][10].

---

## 8. Core reball / reflow — honest framing

**Reflow is a callback, not a repair.** The skeptical consensus is long-standing and blunt: Rossmann's 2014 thesis ("Reballing flip chip GPUs is BULLSHIT") is that failure lives inside the flip-chip package (internal bumps/circuitry), not in the external balls [63]; madpsy: "neither did it need reballed nor is it now repaired… you are effectively causing the internal tracks to realign… It's in a state of fragile mess… if you repeat this process you are killing it even faster" — with the explicit caveat that reballing **is** valid when *replacing the chip* [62]. techbenchlab's 2026 guide agrees: a reflowed/reballed degraded die "failed again → die degraded, stop; that is exactly why so many reball jobs 'last three months and come back'" [67]. rupz's first-person log: "these cards helped teach me that reflows should not be considered 'permanent fixes'" — his MSI 770 A/B needed chip replacement after failed reflows [64]. DIY heat-gun/oven "baking" is worse: the card NorthWest Repair became famous for resuscitating had been ruined by amateur baking and needed professional reballing of core **and** memory [61].

**Reball of a degraded GA104 core = placebo.** For your card the correct skeptic framing is: chip swap fixes memory; if it's the core, no amount of rework makes it well [62][64]. The vlab evidence is concrete: the exact-card channel-B case survived a **full GPU reball** with identical errors [10][20]; another 3060 Ti (channel C1) survived chip swap **and** re-reattachment with the same errors → GPU-side [33].

**When core reball IS the right call:**
- After removing the core for any reason (chip-level pad work, obvyazka access) — you must reball to reinstall [59].
- **IMC-pad / bridged-ball faults**: the badcaps precedent was literally two joined balls under the GPU shorting one channel's lines — reball with corrected ball size fixed it [10].
- **Donor-core replacement** (madpsy's valid case): documented GA104 transplants exist — GPU Solutions' full RTX 3070 (GA104) core swap, frames showing removal, reballed donor, resistance checks, MATS/NVMT pass, stable benchmarks [60]; gpu_lt's "3070 core on 3060 Ti PCB" reached verification with a documented failed intermediate attempt [69].
- **LHR↔non-LHR core swap nuance:** GA104-202 (LHR) → GA104-200 (non-LHR) on the same board reportedly "boots without problems after [vBIOS] reflash" (vlab t=124374, 2022) [149] — **but** t=143188 shows cross-swaps producing MATS B1/C0 errors on both boards because two GA104 PCB variants invert channel B1/C0 data pads at some points ("with the right BIOS for the PCB you can work around this"), and the 202 ultimately only worked on its own LHR board; a separate vlab case notes GA104-200 pads are incompatible with a 3070 PCB [150][141]. Frame: possible in principle, BIOS/PCB-variant dependent, **not a clean path** — and NVIDIA's own die-harvesting means GA104-200 donor silicon is plentiful but SKU-locked [70].

**Equipment deltas vs memory work:** GA104 is a bare 392 mm² FCBGA (TPU spec pages for this card: FCBGA-2713 [157]; stencil trade says "FCBGA2714") — **ball pitch was never confirmed by a primary source; buy a GA104-specific stencil** (gpufix/KrisFix GA104-SM Ø0.45 mm, €32.99; market-standard 0.45 mm balls) and do not hand-pick pitch [50][157]. Core work needs: a proper reballing jig/holder (flexible direct-heat stencils warp over a 20 mm die → bridges — the standing badcaps warning) [57]; higher thermal mass → stronger preheat (IR plate, not hot-air-only; the TPU DIY log with hot air alone lifted pads and blew off caps) [100]; a 55×55 mm-class nozzle and three-zone reflow as in GPU Solutions' procedure (clean old lead-free solder, flatten pads, thin flux, stencil+balls in holder, microscope check, preheat + hot air, second alignment pass, reflow on preheated PCB, resistance checks, POST — frames seen) [59]. The "0.05-under-nominal balls" trick is one tech's answer to ball-joining on this exact card — anecdote, not standard [10][6]. Donor/scam caution: a $350 "broken 4090" buyer received a **dummy die** — dummy-die scams exist precisely because core work is desirable [71].

---

## 9. Equipment & bench setup

### 9.1 Minimum viable DIY tier (~$400–700) — enough for a front-side memory swap

| Item | Pick | Price | Notes |
|---|---|---|---|
| IR bottom preheater (the real enabler) | **Puhui T-8280** 1500 W, 280×270 mm heating area, PID, 0–450 °C | **€130–160** (satkit €130 ex-VAT; Ali $129–139) | This is the basis of NorthWest Repair's rig: his preheater-upgrade video shows the **blue anodized clamp/holder bolted onto a Puhui T-8280** (frames seen) [53][54][58] |
| Hot-air station (≥850–1000 W class) | Quick **857DW+** or Atten **ST-862D** (GPU Solutions' daily drivers — he runs *two* stations and a spare element); Quick 861DW is the named reference standard | ~$80–250 | High airflow blows away adjacent 0201/0402 parts — low flow + distance + shielding [55][56] |
| Stereo microscope | 7–9× class with camera | $100–300 | mandatory for pad work [56] |
| KSGER/quick stage + tweezers | chip-holder reballing platform (AMAOE RTX3060/RX580 magnetic platform ~$29–31; NW prints his own holders) | $30–70 | [154][58] |
| Stencils + balls + flux | GDDR6/BGA-180 0.45 stencil €6.49; 0.45 mm balls; genuine NC-559-V3 (Inventec) or Alpha OM-338 | ~€25–50 | [49][52][51] |
| Bench PSU (current-limited) + DMM + LCR | Korad KA3010D class $60–90; cheap LCR for caps [56] | $100–150 | power-injection short hunting [22] |
| SOIC8 programmer | CH341A + clip | ~$10 | the only recovery for a bricked no-dual-BIOS card [38] |
| IR thermometer / thermal camera | handheld IR; FLIR/HIKMICRO class if budget allows | $30–400 | BitForge used a HIKMICRO overlay on a Zotac 3060 Ti (frame at 15:10) [17]; GPU Solutions' Tooltop T7 is the low-budget camera option [153] |

### 9.2 Recommended tier (~$1,000–1,600)

AOGA-856C+ / Quick 8800-class hot air; 7–9× trinocular; dedicated preheat plate + PCB holding jigs (NW's blue clamp pattern or JoshiRepair's £80 9-slot GDDR6 reballing jig); bench supply; **BGA station class** (direct-heat IR+hot-air, e.g. R490/IR6500/Seamark class, $1.5–4k pro tier) for core work [56][51]. Pro benches run $3,000–6,000+ [56]. GPU Solutions' full named kit (Quick 857DW+, two Atten ST-862D, FLIR camera, Tooltop T7, QRS-300B seeder, Xelite 5000 microscope, JBC tip station) is a good shopping template [55][153].

### 9.3 Safety & process notes

- **Do not mix leaded and lead-free** — industry guidance and badcaps techs are consistent ("everything should be lead free"); the mixed-alloy concern is a documented caution, not a solved problem [57][66]. Verify the alloy of the balls you order.
- Fume extraction for flux vapor is standard practice; none of the creators' benches in this run show a named extractor (gap — get one).
- Overheat discipline: chips get "baked" by over-long heating (rupz's own failures); preheat first, moderate hot-air, short cycles [64].
- Anti-sag bracket after reassembly: IPC-9704A strain → BGA cracking is documented physics on 30/40-series; a $10–25 bracket is the cheapest insurance [65].

---

## 10. Channel-disable salvage — honest closure

**For a GA104-202 (LHR) card, channel-disable is closed as of Jan 2026.** The mechanics where it *does* work: (a) strap-5 (GPU-ID strap) moved from GND to 1.8 V — on GA104-150, "Strap 5 … connected to GND at R215 … connect it to 1.8 V instead at R216" + a reduced-channel vendor-derived BIOS, then (b) flash the reduced-channel ROM, usually with (c) the two dead chips removed; Paulo Gomes' team turned an EVGA RTX 3070 into a working 6 GB (later 12 GB) this way [35][112].

**Why it fails on LHR:**
- The public BIOSes are **non-LHR**: vlab t=128402 master thread — "these are BIOSes from NON-LHR versions (GA104-200)… is there a BIOS for LHR versions, e.g. GA104-202?" → BIOS modder YunicheK: "**В открытом доступе нет**" (not publicly available); requests continue unanswered into 2026 [31].
- On the closest GA106 LHR case (t=141708): "your BIOS is from a regular 3060 with ID 2503, but my card is LHR with ID 2504, and **nvflash did not allow flashing**" — the Device-ID mismatch is the mechanism; the same wall was hit verbatim on a Zotac RTX 3060 12 GB (badcaps 3832009: "ID mismatch error, not possible to flash") [32][116].
- The resident answer when asked directly about a 3060 Ti **LHR** channel-repair BIOS (t=135249): "**Нет.**" [33]; for GA106-302 LHR channel C: "Not for LHR version sadly" — only channel-B disables circulate (t=150732) [34].
- The mechanism behind the wall: NVIDIA locked vBIOS signature verification from Turing onward (public modding depends on leaked engineering ROMs) [114], and TPU's own Q&A states the practical rule: you need a **signed** BIOS; the 3060 Ti "disabled-channel" mod worked via a special BIOS where **DeviceID 0x0040 = RTX 3060 Ti with one channel disabled** — i.e., a firmware identity change nvflash won't accept across the LHR boundary [110]. TPU's news item for that very BIOS (316166, "Patched vBIOS for RTX 3060 Ti with Memory Channel D Disabled") is now **deleted/404** — the public artifact is gone [111].
- **Local files:** NorthWest Repair's Drive carries `Disable_Memory_Channel_30_series.zip` (22.4 MB, dated 2023-03-10) including `3060 Ti.zip` with **N306T_A/B/C/D.ROM** (999,424 B each, one per disabled channel; extracted at `files/drive/extracted/dmc/`). They are **NVGI-signed containers** (encrypted payload); device-ID byte analysis was inconclusive; independent evidence says circulating 30-series channel-disable ROMs are non-LHR, and nvflashk flashes signed ROMs only, rejecting on board/device ID. **Treat these as non-LHR engineering ROMs; LHR compatibility unverified — do not count on them** [86].
- Clock-line jumper lore: on the channel-C case where chip swap + reball failed, a vlab member proposed the fault may be on the **clock/address lines rather than data**, and that "a disabled channel is not a fact it will work — it's easier to replace the GPU" (AlexFromHrodna) — no jumper recipe exists [33].
- If it ever worked, the cost: measured bus-width penalties on sibling mods — RTX 3090 384→320-bit ran at **95–96% of stock (~4–5% loss)**, while the 3090 12 GB/192-bit BIOS ran at 76–85%, and the 3070 6 GB mod ran RE4 at 50–60 FPS vs 70–80 on 12 GB (≈25–33% in that title) [113][112]. For a 256→192-bit 3060 Ti, **~8–15% is our extrapolation between those measured points, not a measurement** — expect roughly single-digit-to-low-teens loss, workload-dependent. Runtime `-disable_channel` switches in MATS/MODS are diagnostic conveniences, not a permanent fix — permanent disable requires a signed BIOS, which is the blocked part [110].

**Bottom line:** on this card, channel-disable is not a salvage path today. The real alternatives are the all-8 Samsung swap, a core swap (§8), or selling the board for parts.

---

## 11. Economics & go/no-go (Nov-2026 numbers, corrected per fact-checks C9/C10)

### 11.1 What the card is worth

| Measure | Value (early Nov 2026) | Source |
|---|---|---|
| Working used, **sold** median | **~$280** (GPU Sold, 195 sales/14 d; typical sold $260–300); pcprice.watch multi-market median $294–297, middle-50% sold $276–336; GetPCParts $243 (Oct-31 sold basis) — ≈ £215–235 (approximate conversion; no FX source read) | [73][74][77] |
| Working used, **asking** median | $300 (GPUHound, 99 listings mostly $299–379); $300→$329 in 32 days (+9.7%, Silicon Comps — asks, explicitly not sold); "fair asking" $266–294, **+9.2%/30 d, +19.7%/90 d** (ResalePrices) | [72][75][76][184] |
| LHR premium/discount | **None material** — LHR and non-LHR asks interleave in the same band; the mining-era LHR discount closed when driver 522.25 removed the limiter (Nov 2022) | [72][126] |
| Parts / for-repair cards | **~$60–150** (observed ask: $125 for a broken MSI Ventus 3X "AS IS for parts, repair, or salvage"); aggregators treat sub-¼-of-median listings as junk | [72][74] |
| The old "$180–220" numbers | Are **late-2025** (pcprice.watch sold medians: Nov 2025 $222, Dec 2025 $224) — using them today understates the market by ~25–30% | [74] |

### 11.2 What pros charge (2025–26 quotes gathered)

| Shop / region | Price | Notes |
|---|---|---|
| Blackstone Repair (UK) | **"From £70"; RTX 3060 Ti fixed £70**, £0 if unfixable, 90-day warranty — **but VRAM chips billed per chip fitted (GDDR6 1 GB £10)** → an 8-chip swap ≈ **£80–150 all-in** | the £70 is a labour floor, not a VRAM-swap price (C9) [78][79] |
| Brentworth (US) | $120–350 + $50 diagnostic | [80] |
| PCB-Werke (DE) | from €120 + €50 diagnostic | [81] |
| Repair Center (Lethbridge, CA) | $150 labour + $50 per module → ~$550 for a full 8-chip swap | [82] |
| Computer Repairs Pronto (AU) | from A$530, 12-month warranty | [83] |
| Computer Cures (AU) | single-chip $200–400; multi-chip $400–800+; **their own stated success rates: "roughly 50–70%" for VRAM chip replacement, 40–60% for GPU reball** | the only per-job success-rate figures found anywhere, and they're a shop's self-estimates, not data [84] |
| GPU Solutions (Dubai) | diagnostic AED 100–400 by tier (credited against repair); normal repair ≈ 10% of UAE market value, **min AED 200 (~$55)**, memory/core parts extra; their core-reball page separately lists a flat AED 100 install tier — C9 corrected the earlier "AED 100 core-reball add-on on a 250–350 tier" framing (that AED 100 is the tier-1 diagnostic fee) | [85][59] |
| MDrepairs (generic band) | minor $100–250; major board work $300–600+; on the 3060 Ti class: "$150 to $350+ — worth it on upper-tier cards, **marginal below**"; mid-tier ($250–600) "borderline… compare against used-market pricing" | [68] |

Realistic all-in band for a professional 8-chip VRAM swap on this card: **~£80–150 (UK) / $150–550 (US-CA) / €170–400 (DE)**, clustering around **$200–400** [79][82][84].

### 11.3 The break-even (C10 corrected)

- **Repair beats replace up to ~£140–160 / $180–210** (~60–70% of a ~$280 working replacement, allowing shipping + repair-failure risk). **Above ~£200 / $270, replace.** [73][76][78]
- DIY reality check: the minimum viable bench (§9) costs **$400–700+** — more than the card is worth. **Buying the gear for one card is not economic; it is only rational if you value the bench and skill for other cards** (rupz's advice: practice on scrap cards first [64]). Chips + consumables alone (~$110–160) make sense only if you already own the rework gear.
- Rising market cuts both ways: a card worth $294 justifies more repair spend than the same card worth $222, but donor/parts prices rise too, and GDDR6 chip stock is shrinking (2026 DRAM crisis; class action vs the DRAM makers filed Jun-2026) — **if you're going to fix it, act sooner** [76][156][44].
- **Donor-card alternative:** a for-parts Twin Edge ($60–150) yields a full known-history chip set + cooler + board; but the donor likely carries the same X005-era memory, so as a chip donor it only helps if its markings are clean (Samsung or benign Hynix) [123][98].
- Warranty context: no X005 program exists [14][42]; Zotac's warranty posture is adversarial in practice (public disputes over import-date vs purchase-date and a fake-invoice registration scandal) [158][159]; EU buyers retain statutory two-year rights regardless of the registration game [160]; NVIDIA's own page routes warranty claims to the AIB [42]; 2025 saw ~1000% more warranty claims across the industry (Warranty Week) [41].

**Verdict:** if you already have a BGA-capable bench → all-8 Samsung swap (~$90 chips + strap work) is clearly worth it. No bench, decent EMEAI registration → try warranty first. No bench, no warranty → pro repair ≤ ~$190 yes, ≥ ~$270 no; in between, compare against a ~$280 working used card and a $60–150 parts donor.

---

## 12. Content-creator intel — what was actually seen vs what was only claimed

**Provenance discipline:** [frames] = the research team inspected extracted video frames at the stated timestamps; [title/snippet] = claim rests on the video's title/description/search summary only — treat accordingly.

**NorthWest Repair (Tony, youtube.com/@northwestrepair):**
- *"Are Zotac cards repairable? 3060 twin edge artifacts"* (2022) — **closest on-brand Zotac Twin Edge repair** (a 3060 non-Ti): [frames] shroud removal on blue mat, DMM probing bare PCB, PCB clamped in a preheater/BGA fixture with its own LCD controller, hot-air + microscope work over a memory chip, gameplay with sensor overlay, closing "Overclocking" screen [88].
- *"Watch this if you have 3060 Ti"* (2024) — the family warning video: [frames] macro of GDDR6/core with caption "Soldering S2C chips can be fatal if not careful" (1:28); blue BGA/chip jig + loose memory chips + tweezers (2:08); caption "Always put a set of your own balls" over a ball grid (2:27); board clamped in the blue preheater station with thermocouple (2:47); hot-air over bare pads with chips removed (3:07); probing around MEC46 and R215–R231 (3:26–3:46) [87]. The "VRAM swap fixes 3060 Ti" message is [title/snippet]-grade; the reballing/jig workflow is [frames]-grade.
- *"HP GeForce RTX 3060 Ti artifacts fix"* (2022): [frames] green "PASS" memory-test screen (1:03), a datasheet on the desktop (1:16), blue clamp fixture + hot-air memory work (1:30–2:14), Windows boot logo (2:41) [89]. The "core reball" characterization circulating for this video is **title-only** — no reballing visible in the sampled frames [89].
- *"PUHUI T8280 IR Infrared preheating station Upgrade"*: [frames] the **blue anodized clamp holder (orange thumb-knobs) bolted to a Puhui T-8280 IR preheater** — the rig basis cited in §9; NW does not name his vendor, so buy the equivalent T-8280, not "NW's clamp" [58].
- **The Drive archive** ("GPU Shared", owner "T Tonycstech"): public Google Drive with boardview/schematic subfolders, MATS/MODS ISOs incl. **Mods 455 RTX30.iso**, the straps poster (transcribed in §6), power-sequence + GDDR5/6/6X/7 pinout posters, the channel-disable zip (local copies at `files/drive/`, fixed JPEGs at `files/drive/fixed/`), and the anti-resale note ("If you paid for these files, you are an idiot. They are absolutely free.") [86]. The 1.17 GB boardview `All.zip` subfolder is now **404/deleted** [139].
- His strap poster's worked example is a **Hynix 00101 → Micron 00001** swap (strap2 H→L) on a board whose designators do not match the Twin Edge — see the measure-first rule (§6.3) [86][134].
- Current repair status: northwestrepair.com was captured redirecting to `unavailable.php` with "too many orders" messaging (primary read during this run); pricing not published [163].

**GPU Solutions / "Graphics Card Repairs" (Frazer, Dubai)** — the most directly relevant creator for this exact repair:
- Gigabyte Aorus 3060 Ti X005→Samsung (Or83oiWeyJU): [frames] full-set desolder (13:54–23:21), **tweezers rearranging 0402-class resistors in the strap area under a yellow-circled annotation (28:19–28:49), hot-air pass (28:39), DMM checks (27:09/29:48/30:48)**, green-PASS memory test (32:47/42:04), Windows + God of War stress (45:12–48:21); description states the all-8 doctrine [90][15].
- ASUS TUF 3060 Ti X005→Samsung (VGpekr4MMQk): [frames] Samsung install overlays, post-repair DMM reading "29.1" on memory lines (19:15), GPU-Z vendor verification chapter [91].
- **Palit 3060 Ti Dual LHR** (0Aau4UZK5fk) — an LHR GA104 board: [frames] chapters "Full Memory Replacement (Hynix→Samsung)" 10:00, "Strap Configuration Change" 11:30, "MATS Memory Test Pass" 16:00, "Windows Driver Loads Successfully" 17:30, stress chapter 18:30 — the workflow needs **no reflash** [92].
- Core reball walkthrough (dIsCaqsKBl4) and RTX 3070 core transplant (3Ehk1g8bLO8): [frames] as summarized in §8 [59][60].
- *"MATS & MODS Complete Guide"* (jh5V2onzAV4): [frames] boot-stick menu with the red "FAIL! Can't read EDID" banner (0:30), Linux console test runs (5:30/6:00), green-PASS memtest screen (6:30), GPU-Z on a 3070 Ti (7:00) [93].
- Named tool list and NVMT bank-reading article: §9 and §4 [55][173].

**Others:** BitForge Repairs — *"Low-End 30 Series Killer – Zotac 3060 Ti Full Repair"* (2026-08-29): [frames] Zotac Twin Edge teardown, burnt "1R0 2210" inductor + polymer caps near the mounting hole (4:17/11:32), HIKMICRO thermal overlay (15:10) — strong evidence that **this model also dies of power-stage failures**, not just memory (the notes conflict on the 18:58 frame — FurMark beside the desoldered inductor vs a cleaning brush; the sheet is ambiguous, and the "shorted 12 V rail / failed DrMOS" characterization is description-level, so treat the fault specifics as indicative, not proven) [17]. Kiki Hobby Repair — *"Trying to fix 3 broken RTX 3060Ti graphics cards"*: [frames] three donor cards, DMM resistance/diode checks, bench supply, green PASS memory screen (11:28), Unigine validation (12:37–17:03) — a multi-card donor/scavenge workflow, no BGA chip work visible in the sampled frames [94]. RadPaw — *"RTX 3060 Ti Repair Hunting Down a Hidden Short"* (2026-07-24): [frames] power-schematic on screen (5:27), boardview (14:13), PEAK_PWR_LOGIC (16:22), −2.336 pF measurement (27:18) — a rail/short-hunting masterclass, **not** a core replacement (the "GPU Core Replacement" title circulating in some notes is wrong) [161]. gpu_lt — GA104 core transplants: [frames] with unreadable text detail [69]. CmdrSoyo — Twin Edge PCB overview [frames] [9]. Electronics Repair School — "Zotac 3060 & 3060ti – Two cards, same fault": **members-only, never viewable** [162]. vlab members (DoktorVGA, ruzalit, ayobisinen, hoolyman, Frennis, YunicheK, stax) are the primary *written* intel on this card family — §5.3 [13][20][31][33].

---

## 13. Open questions & uncertainties (what this run could not settle)

1. **Your memory population is unconfirmed** — no public Twin Edge OC LHR chip-marking photo or GPU-Z vendor screenshot exists; the LHR-era mix (Samsung vs Hynix vs possibly Micron) is unresolved until you read your own chips [123][157].
2. **The DoktorVGA Zotac Twin Edge LHR strap photo is behind vlab's login + 15-post wall** (no Wayback copy; attachment name not even guest-visible) — unlockable by registering and posting 15 times or buying access [13][166].
3. **No public back-side photo of a Twin Edge LHR PCB exists** — strap pads unobservable until you photograph your own card [157].
4. **NW's `All.zip` (1.17 GB boardview archive) is deleted (404)** — permanently unenumerable; PGTBoardView's catalog and paid Telegram libraries remain unenumerated; the сервискомп-анна paid "Zotac/Manli GA104 DN651/N651" schematic+boardview listing is unverified as to ZT-A30610H [139][132][134].
5. **PG190 document gaps:** no PG190 **SKU-10 (LHR)-specific** schematic or boardview is public — only A02-family docs; no Galax/Palit/KFA2/Inno3D/PNY/Gainward/Acer/XFX PG190 implementations are indexed; the i2mx open directory was unreachable (browser lead) and a YouTube PG190-A02 boardview video (GizarVibroTecnologia) may link a free file (unverified) [175][174].
6. **The straps poster board's identity is unknown** — designators mismatch the Twin Edge; do not treat it as a Twin Edge map [134][86].
7. **GS7155NV's exact rail on the Zotac board is inferred, not documented** (IOVDD_PROT/1.8 V-class auxiliary LDO by datasheet + PG190-family schematic analogy; no Zotac boardview to confirm) [16][8].
8. **No quantitative DIY success-rate data exists anywhere** — every durability claim (all-8 swaps "don't come back", reball "lasts 3 months") is anecdotal; the only percentages found are one shop's self-estimates (50–70% VRAM chip replacement, 40–60% reball) [84][62].
9. **The "half-day Samsung swap" anecdote is misattributed** — it is **not** in vlab t=135249 (that thread has no Samsung swap); the story belongs to a GA106 card in t=141708 ("2 Hynix cards" user), and its card brand/capacity details are unverified single-source forum lore [32].
10. MATS' "minimum clock 150–300 MHz" is a single-source figure [26]; MODS error-code meanings (FALCON etc.) and nvflash error codes were not resolvable from readable sources [140][38].
11. GA104 ball pitch and 2713-vs-2714 ball count remain unconfirmed by any primary source — buy GA104-labeled stencils, don't compute pitch [50][157].
12. DigiKey/Mouser stock for the Samsung part: unverified (bot-walls); AliExpress per-chip prices snippet-grade only [44][47].
13. Whether the local N306T_A–D channel-disable ROMs contain any LHR-compatible variant: payload is NVGI-encrypted; analysis inconclusive — assumed non-LHR per community evidence [86][31].

---

## 14. Methodology

- **Rounds:** 3 research rounds + a critic gap review; 12 fact-checks (C1–C12) run as independent verification workers; 4 real-browser laptop passes (TechPowerUp bot walls, Reddit, vlab guest views, badcaps file archive, price pages, native-resolution PCB photo inspection); 37 per-topic notes files; 19 frame sheets covering 17 YouTube videos (plus strip frames and crops).
- **Verdicts:** C1 confirmed-with-nuance (straps not vBIOS); C2 partly (code table transfers, physical strap state does not); C3 partly (strap-rearrangement action visible, designators not legible); C4 partly (batch doctrine solid, CS/MP folklore — hynix catalog says MP); C5 confirmed (all-8 doctrine); C6 partly (bridged-balls case real, 0.05-under is one anecdote); C7 partly (FBGA-180/0.75/0.48±0.05 datasheet-confirmed; GA104 pitch unconfirmed); C8 partly (LCSC $8.93 was the wrong quantity tier — real 8-set ≈ $90, stock 47; Micron ~$100–124 and OOS at LCSC); C9 partly (£70 real but a labour floor; chips per-chip extra); C10 partly (sold median ~$280; the $180–220 figures are late-2025); C11 partly (MATS-pass/OCCT-fail real; the 150–300 MHz figure single-source); C12 strongly-supported negative (no public Twin Edge schematic; paid corners open).
- **Corrections made because of fact-checks:** CS/MP layer removed from the doctrine; LCSC/Micron prices re-tiered; £70 repriced as "from"; used-value numbers re-dated to Nov-2026; strap-table transfer downgraded to "measure first"; MATS >256 MB marked non-informative; the half-day-Swap anecdote re-attributed to a GA106 card; board identity corrected late from PG142 to **PG190 SKU 10** (laptop pass 4), which reordered the schematic proxy tiers; the front-side strap-cluster assumption replaced by the verified front-side negative + back-side expectation.
- **What could not be read:** vlab attachments (15-post wall); Reddit old threads pre-2024 (login walls — worked via laptop passes where possible); zotac.com pages (JS); DigiKey/Mouser/eBay detail pages (bot walls); masterschematics.com (HTTP 525, defunct); boardsheet.net (NXDOMAIN); gstekic.com datasheet (dead — recovered from mirrors); Electronics Repair School video (members-only); NW `All.zip` (deleted); the TPU 316166 news item (deleted).
- **Local artifacts kept** (in the research folder): `files/V390_PG142.pdf`, `files/TUF_3060ti.pdf`, `files/CG142S.pdf` (proxy schematics; strap pages rendered as `files/*_p26*.png`), `files/xid_errors.pdf`, NW Drive dump under `files/drive/` (incl. `extracted/dmc/` N306T_A–D.ROMs and `fixed/*.jpg` — the raw `straps.png`/`GDDR7.png` in that folder are WebP disguised as PNG and crash image readers; use the fixed JPEGs), strap photo crops under `files/straps/`, and video frame sheets under `frames/`. TPU forum photo evidence (attachments 385854/385855) is downloadable directly from the thread [7].

---

## 15. Sources

**Board & platform identity**
1. gpu-monkey — ZOTAC RTX 3060 Ti Twin Edge OC LHR spec page. https://www.gpu-monkey.com/en/gpu-zotac_gaming_geforce_rtx_3060_ti_twin_edge_oc_lhr
2. VideoCardz — RTX 5060/5060 Ti shipping manifests (PG152 = Blackwell). https://videocardz.com/newz/nvidia-geforce-rtx-5060-and-5060-ti-with-gddr7-128-bit-memory-shipping-manifests-confirm
4. The Retro Web — GA104 PCI device IDs. https://theretroweb.com/chips/13967
6. TechPowerUp — Zotac GeForce RTX 3060 Ti Twin Edge review, p.3 (circuit board, VRM, Samsung chips). https://www.techpowerup.com/review/zotac-geforce-rtx-3060-ti-twin-edge/3.html
7. TechPowerUp forum thread 332878 — "Zotac RTX 3060Ti Twin Edge OC LHR PCB image" (GS7155NV identification; photos 385854/385855). https://www.techpowerup.com/forums/threads/zotac-rtx-3060ti-twin-edge-oc-lhr-pcb-image.332878/
8. Tom's Hardware — 12VHPWR connector melt reporting. https://www.tomshardware.com/pc-components/gpus/3090-owner-claims-nvidias-new-12vhpr-connector-melted-down-hits-105-degrees-celsius-before-shutting-down
9. CmdrSoyo — RTX 3060 Ti Twin Edge PCB overview (YouTube, frames). https://www.youtube.com/watch?v=uCNMMlZ7Yh4
12. Notebookcheck — GA103-based RTX 3060 Ti Zotac variants. https://www.notebookcheck.net/Nvidia-RTX-3060-Ti-GA103-model-spotted-in-the-wild-featuring-1920-shaders-and-8-GB-of-VRAM.574204.0.html
16. Gstek GS7155NV 3 A LDO datasheet (Rev 2.3, mirror). https://crossic.com/wp-content/uploads/2022/06/GS7155NV-1.pdf
36. TechPowerUp vBIOS DB — Zotac RTX 3060 Ti Twin Edge OC LHR 94.04.46.40.0E. https://www.techpowerup.com/vgabios/235333/zotac-rtx3060ti-8192-210519
37. TechPowerUp — Zotac RTX 3070 Twin Edge OC review (no dual-BIOS switch). https://www.techpowerup.com/review/zotac-geforce-rtx-3070-twin-edge-oc/
126. Tom's Hardware — NVIDIA restores LHR mining performance (driver 522.25). https://www.tomshardware.com/news/nvidia-restores-mining-performance-on-geforce-rtx-30-lhr-gpus
130. bytwork — Zotac RTX 3060 Ti Twin Edge review (K4Z80325BC-HC14). https://bytwork.com/komplektujushhie_dlja_majninga/videocards/zotac-3060-ti-twin-edge-obzor-test-v-igrakh-i-mayning
147. Samsung K4Z80325BC GDDR6 datasheet Rev1.3 (mirror). https://res.ameya360.com/38/46/887831f2217b4a688677750cf6247b08.pdf
148. ProtoFlow — Micron MT61K256M32JE FBGA-180 land pattern. https://www.protoflow.ai/library/parts/C1352195
157. TechPowerUp gpu-specs — ZOTAC RTX 3060 Ti Twin Edge (OC) LHR b9024/b9025 (PG190 SKU 10). https://www.techpowerup.com/gpu-specs/zotac-rtx-3060-ti-twin-edge-oc-lhr.b9025 · https://www.techpowerup.com/gpu-specs/zotac-rtx-3060-ti-twin-edge-lhr.b9024

**Failure modes, X005, artifacts**
5. Graphic Card Repairing (GPU Workbench Lab) — RTX 3060 Ti No-Display Complete Repair Guide. https://graphiccardrepairing.com/blog/rtx-3060-ti-no-display-repair-guide
10. badcaps — "Zotac RTX 3060 Ti LHR 8 Go" channel-B repair log + DynaxSC reply. https://www.badcaps.net/forum/troubleshooting-hardware-devices-and-electronics-theory/troubleshooting-desktop-motherboards-graphics-cards-and-pc-peripherals/3821485-zotac-rtx-3060-ti-lhr-8-go
14. overclockers.ru (DenebCore) — Defective Hynix memory on RTX 3060 Ti (CS/MP origin). https://overclockers.ru/blog/DenebCore/show/68927/defektnaya-pamyat-hynix-na-videokartah-rtx3060-ti-prodolzhenie-istorii
15. GPU Solutions — RTX 3060 Ti Hynix memory issue (X005 explainer). https://gpusolutions.net/3060ti-hynix-memory-issue/
17. BitForge Repairs — "This is the Low-End 30 Series Killer – Zotac 3060 Ti Full Repair" (YouTube, frames). https://www.youtube.com/watch?v=JFQK8QUyVP4
24. Graphic Card Repairing — GPU troubleshooting/diagnostics blog. https://graphiccardrepairing.com/blog
27. r/GPURepair — "3060Ti w/ X005 VRam failing – MODS & MATS Pass but OCCT Fail???" (ssateneth2, khoavd83, Drastic-Measures, northwestrepair). https://www.reddit.com/r/GPURepair/comments/1odqpso/3060ti_w_x005_vram_failing_mods_mats_pass_but/
28. r/GPURepair — "RTX 3060 Ti Hynix X005 – MATS errors on all channels above ~250MB…". https://www.reddit.com/r/GPURepair/comments/1xchm41/rtx_3060_ti_hynix_x005_mats_errors_on_all/
64. rupz.me (DIER) — Graphics card VRAM chip replacement procedure + failure log. https://rupz.me/electronics/graphics-card-vram-chip-replacement-procedure/
97. Linus Tech Tips forum — "VRAM underclock fixed this GPU but I want to know why" (−330 case). https://linustechtips.com/topic/1382879-vram-underclock-fixed-this-gpu-but-i-want-to-know-why/
98. overclockers.ru (DenebCore) — RTX 3060/3070 Ti memory overclocking; X005 vs S2C markings; vendor unknowable without opening. https://overclockers.ru/blog/DenebCore/show/70381/
99. overclockers.ru (DenebCore) — FurMark barely loads video memory. https://overclockers.ru/blog/DenebCore/show/70293/
104. Flowup — "I have an artifact problem, what should I do?" (colour myth). https://www.flowup.shop/en_GB/blog/questions-techniques-8/i-have-an-artifact-problemwhat-should-i-do-72
105. vlab.su t=156010 — Palit RTX 3070 geometric artifacts, clean MODS @100% = GPU. https://vlab.su/viewtopic.php?f=48&t=156010
106. NVIDIA — Xid Errors Reference (PDF; local copy files/xid_errors.pdf). https://docs.nvidia.com/deploy/pdf/XID_Errors.pdf
107. badcaps — "MATS/MODS detected and repaired GPU fault" (single-bank green lines). https://www.badcaps.net/forum/troubleshooting-hardware-devices-and-electronics-theory/troubleshooting-desktop-motherboards-graphics-cards-and-pc-peripherals/3641793-mats-mods-detected-and-repaired-gpu-fault-cant-seem-to-test-after
108. badcaps — "Artifacts from GPU not always a GPU chip fault" (HD6850 MLCC). https://www.badcaps.net/forum/general-topics/general-computer-tech-discussion/73227-artifacts-from-gpu-not-always-a-gpu-chip-fault
109. vlab.su t=144014 — "artifacts are very conditional". https://vlab.su/viewtopic.php?f=48&t=144014&start=60
123. r/Ravencoin — "Anyone mining with Zotac 3060 Ti with Hynix memory?" (Jul 2021; + r/gpumining r35mft, r/NiceHash q8qq5z). https://www.reddit.com/r/Ravencoin/comments/owen0r/
125. MSI forum — X005 batch window (Sep 2021 – Dec 2022). https://forum-en.msi.com/index.php?threads/question-about-certain-rtx-3060ti-models.414498/
127. SK hynix GDDR6 consumer product table (distributor mirrors: MP status). https://tongli-hk.net/wp-content/uploads/2025/05/SK-hynix__GDDR6_消费类.pdf · https://vdo.com.vn/en/san-pham/gddr/sk-hynix-dram-gddr-gddr6-p2853
129. r/GPURepair — Micron-equipped 3060 Ti Pro also fails. https://www.reddit.com/r/GPURepair/comments/1c91765/rtx_3060ti_problems_crashes_frequency_vram/

**Diagnostics, MATS/MODS**
19. repair.wiki — Nvidia GPU Memory Testing Guide (MATS/MODS doctrine, MODS version table; read via browser). https://repair.wiki/w/Nvidia_GPU_Memory_Testing_Guide
20. vlab.su t=153411 — "Zotac RTX 3060 TI LHR 8GB" (spyke11 + ruzalit). https://vlab.su/viewtopic.php?f=48&t=153411
21. memtest_vulkan — GitHub README. https://github.com/GpuZelenograd/memtest_vulkan
22. PNW Computers — GPU Repair Manual (read in round 1; repo location since moved/404). https://pnw-computers.github.io/gpu-repair-manual/
23. rtech.support — How to use OCCT (GPU/VRAM test settings). https://rtech.support/guides/how-to-use-occt/
26. corex-service.ru — MATS manual (min-clock, FBIO banks, Intel-vs-Ryzen bench). https://corex-service.ru/mats
29. YTEC-info — MATS Nvidia VRAM test mirror (GitHub). https://github.com/YTEC-info/MATS-Nvidia-VRAM-test
30. levirepair.eu — MATS/MODS/NVMT service stick page (commands, channel masks). https://levirepair.eu/gpu-repair-tools/matsmods-nvidia-service-stick/
38. nvflashk — GitHub (board-ID override, backup, fallback mode). https://github.com/notfromstatefarm/nvflashk
93. GPU Solutions — "How to Test Nvidia GPU Memory Errors | MATS, MODS and GDDR6 Guide" (YouTube, frames). https://www.youtube.com/watch?v=jh5V2onzAV4
100. TechPowerUp forum 306584 — "Reballing VRAM to a 3060 Ti" (DIY hot-air-only log). https://www.techpowerup.com/forums/threads/reballing-vram-to-a-3060-ti.306584/
118. r/GPURepair — "List of GPU repair resources & schematics" megathread. https://www.reddit.com/r/GPURepair/comments/smlu0q/list_of_gpu_repair_resources_schematics/
173. GPU Solutions — How I test GPU memory (FBPA decoding, MODS limits, free tool sharing). https://gpusolutions.net/how-i-test-gpu-memory-nvidia-vram-test-usb/

**Schematics, boardviews, vlab**
11. badcaps.net file archive search (guest searches: "Twin Edge" 0 hits; "GA104" 28 hits; "PG190" file hits incl. EVGA232 PDF; RTX 3060 archive thread) + unanswered request thread 3563068. https://www.badcaps.net/file_search · https://www.badcaps.net/forum/document-software-archive/schematics-and-boardviews/3474108-nvidia-geforce-rtx-3060-schematic-board-view · https://www.badcaps.net/forum/troubleshooting-hardware-devices-and-electronics-theory/troubleshooting-desktop-motherboards-graphics-cards-and-pc-peripherals/bios-schematic-requests/3563068-zotac-gaming-geforce-rtx-3060-ti-twin-edge-oc
13. vlab.su t=104925 — master strap-reference thread (DoktorVGA Zotac Twin Edge LHR reply 18-Feb-2026, walled; uncledim/hoolyman/Сц Гост recipes). https://vlab.su/viewtopic.php?f=48&t=104925
102. schematic-expert.com — RTX 3050/3060/3060 Ti schematics + boardviews (download table; PDF password = site URL). https://www.schematic-expert.com/nvidia/rtx-3050-rtx-3060-ti/
103. laptechinfo.com thread 4266 — unanswered Twin Edge OC LHR schematic request (2023-11-28, read in full). https://laptechinfo.com/threads/zotac-gaming-geforce-rtx-3060ti-twin-edge-oc-lhr-8gb-256bit-gddr6.4266/
119. vlab.su t=124951 — Gigabyte 3060 Ti strap designators (R218→R220; 3070 block does not transplant; 1.8 V probing method). https://vlab.su/viewtopic.php?f=48&t=124951
120. vlab.su t=132141 — RTX 3060 8 GB straps; Samsung 8/16 Gb code gotcha; Palit Dual Samsung photo (walled). https://vlab.su/viewtopic.php?f=48&t=132141
121. vlab.su t=143916 — Asus Strix 3060 Ti straps (Hynix→Samsung). https://vlab.su/viewtopic.php?f=48&t=143916
122. vlab.su t=149434 — MSI 3060 Ventus Samsung straps. https://vlab.su/viewtopic.php?f=48&t=149434
131. GPU Doctor — RTX 3060 Ti boardview catalogue (3 boards, no Zotac; from $3). https://gpudoctor.com/gpus/rtx-3060-ti
132. PGTBoardView (Paulo Gomes) — subscription boardview app/library. https://pgtboardview.com/ · https://pgtboardview.com/acervo.html
133. realschematic — Gigabyte RTX 3060 Ti Gaming OC Pro 8G rev 3.0 (LHR) schematic listing. https://realschematic.com/shop/12113/desc/gigabyte-geforce-rtx-3060-ti-gaming-oc-pro-8g-3-0
134. сервискомп-анна.рф resource #38833 — paid "Zotac/Manli RTX 3060 Ti/3070 GA104 DN651 N651 Схема + BoardView PDF" (2025-12-10; paywalled). https://сервискомп-анна.рф/forums/resources/zotac-manli-rtx-3060-3070-ga104-dn651-n651-Схема-boardview-pdf.38833/
135. pkbiosfix thread 10444 — RTX 3060/3060 Ti/3070 schematics + V397 boardviews (registration wall). https://pkbiosfix.com/threads/nvidia-rtx-3060-3060-ti-3070-schematics-boardview-files.10444/
136. IndiaFix — graphics-card schematic/boardview collection index. https://www.indiafix.in/p/graphics-card-schematic-diagram.html
137. OpenBoardView — GitHub. https://github.com/OpenBoardView/OpenBoardView
138. r/ZOTAC — "Zotac does not release Twin Edge schematics". https://www.reddit.com/r/ZOTAC/comments/wmefhw/
140. vlab.su t=130309 — Gigabyte V397 LHR Hynix→Micron swap; H-L-H vs L-H-L strap inversion; ayobisinen advice. https://vlab.su/viewtopic.php?f=48&t=130309
142. Yandex Disk (volkOFF) — the only public strap archive in t=104925 (single Asus 3060 12 GB photo). https://disk.yandex.ru/d/Zoh38vKcvItq5A
143. TechPowerUp forum 342007 — Palit 3060 Ti Dual LHR Samsung mod: straps vs BIOS replies. https://www.techpowerup.com/forums/threads/need-bios-for-palit-rtx-3060-ti-dual-lhr-samsung-gddr6-mod.342007/
144. Notebookcheck — RTX 3070 16 GB mod: strap codes 00000/00001/00110. https://www.notebookcheck.net/NVIDIA-GeForce-RTX-3070-mod-confirms-that-there-was-a-16-GB-VRAM-configuration-in-development.526945.0.html
146. GitHub (Nicoolodion) — RTX 3070 16 GB mod guide, §6 Soldering Straps. https://github.com/Nicoolodion/RTX-3070-16GB-GUIDE
166. vlab.su registration rules — rule 9: attachments need ≥15 posts (or paid access). https://vlab.su/ucp.php?mode=register
167. vlab.su t=138116 — GA104-202-A1 memory-line resistance without chips (liquid damage; resolved: GPU dead). https://vlab.su/viewtopic.php?f=48&t=138116
171. vlab.su t=130014 — Zotac Twin Edge 3060 Ti BIOS flash size mismatch. https://vlab.su/viewtopic.php?t=130014
172. vlab.su t=155256 — GALAKURO RTX 3060 Ti LHR (GA104-202). https://vlab.su/viewtopic.php?t=155256
174. laptechinfo resource 4693 — Gigabyte GV-N3060VISION OC-12GD PG190-A02 Rev 1.01 schematic (spoiler-password download). https://laptechinfo.com/resources/gigabyte-gv-n3060vision-oc-12gd-pg190-a02-rev-1-01.4693/
175. pc6.ca — EVGA232 RTX 2070/RTX 3060 PG190-A02 GA104-GA106 PDF mirror (12.3 MB, 52 pp; free-registration login). https://www.pc6.ca/zh/f/s3x2x1yq4sc7/EVGA232-RTX-2070-RTX3060-PG190-A02-GA104-GA106-pdfx-pdf
176. eletronicabr — Gigabyte PG190-A02 Rev 1.01 schematic listing (registration). https://eletronicabr.com/en/files/file/56791-
177. envytools — PSTRAPS: pins sampled at reset by board pull-ups/pull-downs. https://envytools.readthedocs.io/en/latest/hw/io/pstraps.html
178. r/EtherMining — LHR identification via GA104-202 + PCI device ID 2489. https://www.reddit.com/r/EtherMining/comments/oha2fy/
179. gadget-manual.com — NVIDIA schematic Drive archive (no PG190/30-series entries). https://www.gadget-manual.com/nvidia-geforce/
180. realschematic — ASUS TUF RTX 3060 Ti OC schematic+boardview bundle listing. https://realschematic.com/shop/11709/
183. ZOTAC — "Get 3+2" warranty announcement (EMEAI 30-series, 5 years with registration). https://www.zotac.com/us/emeai/news/get-32

**Channel disable & vBIOS**
31. vlab.su t=128402 — 30-series custom BIOS master thread; stax Drive archives; YunicheK on LHR. https://vlab.su/viewtopic.php?t=128402
32. vlab.su t=141708 — RTX 3060 12 GB LHR dead channel C; strap5 = GPU ID; nvflash 2503-vs-2504 refusal; half-day-Swap anecdote. https://vlab.su/viewtopic.php?f=48&t=141708
33. vlab.su t=135249 — 3060 Ti artifacts channel C1; chip swap + reball failed; YunicheK "Нет."; clock-line remark. https://vlab.su/viewtopic.php?t=135249
34. vlab.su t=150732 — "rtx 3060 lhr отключить канал памяти": "Not for LHR version sadly". https://vlab.su/viewtopic.php?f=48&t=150732
35. vlab.su t=150459 — GA104-150 channel-B/D disabled BIOSes; strap5 R215→R216 recipe. https://vlab.su/viewtopic.php?t=150459
110. TechPowerUp forum 331799 — disabling a VRAM channel: signed BIOS, DeviceID 0x0040 mechanism. https://www.techpowerup.com/forums/threads/is-disabling-a-select-vram-channel-still-a-thing.331799/
111. TechPowerUp news 316166 — "Patched vBIOS for RTX 3060 Ti with Memory Channel D Disabled" (now deleted/404). https://www.techpowerup.com/316166/patched-vbios-for-rtx-3060-ti-with-memory-channel-d-disabled
112. VideoCardz — RTX 3070 modded to 6 GB / 12 GB (Paulo Gomes; RE4 FPS numbers). https://videocardz.com/newz/nvidia-geforce-rtx-3070-has-been-modded-to-support-6gb-and-12gb-memory
113. VideoCardz — RTX 3090 custom 320-bit/192-bit BIOS tests (bus-width penalties). https://videocardz.com/newz/nvidia-geforce-rtx-3090-has-been-tested-with-custom-20gb-320b-and-12gb-192b-memory-bioses
114. Igor's Lab — NVIDIA vBIOS signature lock broken (leaked ROMs; Turing+). https://www.igorslab.de/en/durchbruch-bei-nvidia-bios-signature-lock-neue-tools-ermoeglichen-vbios-modding-und-crossflash/
116. badcaps 3832009 — Zotac RTX 3060 12 GB BIOS mod: "ID mismatch error, not possible to flash". https://www.badcaps.net/forum/troubleshooting-hardware-devices-and-electronics-theory/troubleshooting-desktop-motherboards-graphics-cards-and-pc-peripherals/3832009-request-zotac-rtx-3060-12gb-vram-bios-mod
141. vlab.su t=134989 — GA104-200 pad incompatibility on a 3070 PCB. https://vlab.su/viewtopic.php?f=48&t=134989
149. vlab.su t=124374 — "RTX 3060ti LHR → Замена GPU без LHR": GA104-202→200 boots after reflash. https://vlab.su/viewtopic.php?f=48&t=124374
150. vlab.su t=143188 — GA104-202↔200 swap: B1/C0 pad inversion on two PCB variants. https://vlab.su/viewtopic.php?f=48&t=143188

**Parts, equipment, rework**
44. LCSC — Samsung K4Z80325BC-HC14 (C2920181): ladder 1+ $11.32 / 10+ $10.75 / 30+ $9.76; stock 47 (2026-11-06, raw page JSON). https://www.lcsc.com/product-detail/memory-chips_Samsung_K4Z80325BC-HC14_C2920181.html
45. FindChips — K4Z80325BC broker offers (Win Source 5,985 pcs; $13.23 @8+). https://www.findchips.com/search/K4Z80325BC
46. KrisFix (gpufix.de) — D9WCW / MT61K256M32JE-14:A €24.90 (snippet). https://www.gpufix.de/de/d9wcw.html
47. DigiKey — MT61K256M32JE-14:A (~$12.59/pc snippet; in stock per vlab-era note; page bot-blocked). https://www.digikey.com/en/products/detail/micron-technology-inc/MT61K256M32JE-14-A/8509877
48. LCSC — Micron MT61K256M32JE-14:A (C1352195): **out of stock**, 1+ $15.52 (2026-11-06). https://www.lcsc.com/product-detail/C1352195.html
49. KrisFix (gpufix.de) — DDR6-SM reballing stencil 90×90 €6.49 (+ fuse/DrMOS parts on page). https://www.gpufix.de/en/ddr6-stencil.html
50. KrisFix (gpufix.de) — GA104/GA106/AD104/AD106 stencil Ø0.45 mm, €32.99. https://www.gpufix.de/en/ga104-stencil.html
51. JoshiRepair (UK) — shop: 9-slot GDDR6 reballing jig £80; pre-balled H56C8H24AIR-S2C £17.99; stencils £4.30–7.50; Alpha OM-338 flux. https://www.joshirepair.co.uk/shop
52. Inventec (DE) — AM-NC559-V3-100 genuine NC-559-V3, €28.40. https://shop.inventec.dehon.com/products/amtech-nc-559-v3
53. satkit.ie — Puhui T-8280 IR preheater €130 ex-VAT. https://satkit.ie/puhui-t-8280-infrared-preheater-for-pcb-and-bga/
54. Puhui T-8280 manual (1500 W, 280×270 mm heating area, 0–450 °C, PID; Purdue lab copy). https://www.purdue.edu/bidc/wp-content/uploads/2022/03/PUHUI-T-8280-IR-Preheat-Plate.pdf
55. GPU Solutions — Repair Tools (Quick 857DW+, Atten ST-862D ×2 + spare element, FLIR, Tooltop T7, QRS-300B, Xelite 5000, JBC). https://gpusolutions.net/repair-tools/
56. JLCPCB — Best BGA Rework Station Buying Guide (hot-air vs IR, preheater need, airflow hazards, $ tiers). https://jlcpcb.com/blog/best-bga-rework-station-buying-guide
57. badcaps thread 88467 — BGA reballing techniques & equipment (stencil warp, no mixed alloys, ball sizes, flux residue). https://www.badcaps.net/forum/troubleshooting-hardware-devices-and-electronics-theory/troubleshooting-desktop-motherboards-graphics-cards-and-pc-peripherals/88467-bga-reballing-techniques-and-equipment
58. NorthWest Repair — "PUHUI T8280 IR Infrared preheating station Upgrade" (Puhui T-8280 + blue clamp; frames). https://www.youtube.com/watch?v=P24O1ODFci0
59. GPU Solutions — "How to Reball a GPU Core | Step-by-Step" (frames). https://www.youtube.com/watch?v=dIsCaqsKBl4
60. GPU Solutions — "Swapping the GPU Core in My RTX 3070 – Is it Worth It?" (frames). https://www.youtube.com/watch?v=3Ehk1g8bLO8
61. Tom's Hardware — Northwest Repairs resuscitates a card ruined by baking. https://www.tomshardware.com/pc-components/gpus/botched-gpu-baking-job-is-fixed-by-a-maestro-chef-northwest-repairs-resuscitates-a-dead-graphics-card-by-reballing-its-core-and-memory
62. madpsy — "The nonsense that is 'Reballing' dead GPUs". https://madpsy.uk/the-nonsense-that-is-reballing-dead-gpus/
63. Louis Rossmann — "Reballing flip chip GPUs is BULLSHIT" (title confirmed; transcript not read). https://www.youtube.com/watch?v=1AcEt073Uds
65. Volt GPU Repairs — GPU sag, IPC-9704A strain physics, bracket products. https://voltgpurepairsydney.com.au/guides/gpu-support-bracket/
66. EEVblog — Getting started with BGA reflow and reballing (profiles, hybrid preheat+hot-air, leaded/lead-free). https://www.eevblog.com/forum/beginners/getting-started-with-bga-reflow-and-reballing/25/
67. TechBenchLab — BGA reballing guide (reflow durability, 180–220 °C preheat, 240–260 °C peak). https://techbenchlab.com/bga-reballing-guide/
151. alitools — AliExpress price tracker for K4Z80325BC-HC14 ($8.50–10.50 band). https://alitools.io/
153. GPU Solutions — Thermal Imaging for GPU Repair / Tooltop T7. https://gpusolutions.net/thermal-imaging-gpu-repair-tooltop-t7/
154. Martview — AMAOE RTX3060/RX580 directly-heating BGA reballing platform (~$29–31). https://www.martview.com/amaoe-0-25mm-directly-heating-bga-reballing-stencil-tin-planting-platform-for-rtx3060-rx580.html
169. Parts4Laptops — single GDDR6 stencils, 0.45 mm balls as the BGA-180 practice size. https://parts4laptops.eu/en/single-stencils/
170. FlexBV5 (PLDaniels) — boardview viewer (.fz/.cad/.tvw + schematic sync). https://pldaniels.com/flexbv5/free.php

**Economics, market, warranty**
68. MDrepairs — Is Graphics Card Repair Worth It? (cost bands, replace thresholds). https://mdrepairs.com/blog/graphics-card-repair-worth-it/
70. VideoCardz — GA104 harvesting / RTX 3060 with GA104 in China. https://videocardz.com/newz/nvidia-geforce-rtx-3060-with-ga104-gpu-now-available-in-china
71. Tom's Hardware — $350 "broken 4090" shipped with a dummy die (scam precedent). https://www.tomshardware.com/pc-components/gpus/buyer-pays-usd350-for-broken-rtx-4090-project-only-to-find-realistic-fake-gpu-die-and-swapped-memory-russian-repair-specialist-reveals-sophisticated-new-cam-using-dummy-pcbs
72. GPUHound — RTX 3060 Ti asking median $300; methodology; LHR asks interleaved. https://www.gpuhound.com/gpus/geforce-rtx-3060-ti
73. GPU Sold — sold median $280 (195 qualifying US eBay sales, 14-day window; updated 2026-11-04). https://gpusold.com/gpu/rtx-3060-ti
74. pcprice.watch — RTX 3060 Ti used price guide (monthly sold medians; Nov-2025 floor $222; RAM-crisis context). https://www.pcprice.watch/guides/rtx3060ti-used-price-2026
75. pcprice.watch — live search page ($297, 100 sold/30 d, +6.2%). https://www.pcprice.watch/search/RTX3060TI/US/GPU
76. ResalePrices — fair asking $266–294; +9.2%/30 d; +19.7%/90 d. https://resaleprices.com/gpu/nvidia-rtx-3060-ti
184. Silicon Comps — RTX 3060 Ti asking-price history ($300→$329 in 32 days, +9.7%; asking prices, not sold). https://siliconcomps.com/gpu/rtx-3060-ti/price-history/
77. GetPCParts — $243 sold average, ~120 sales/30 d. https://www.getpcparts.com/market-prices/gpu-graphics-cards/rtx-3060-ti
78. Blackstone Repair — RTX 30-series fixed prices (RTX 3060 Ti £70; £0 no-fix; 90-day warranty). https://blackstonerepair.co.uk/services/gpu-repair/rtx-30-series
79. Blackstone Repair — GPU repair cost page (GDDR6 1 GB £10/chip fitted; "From £70" range). https://blackstonerepair.co.uk/gpu-repair-cost
80. Brentworth — RTX 3060 Ti repair $120–350 + $50 diagnostic. https://www.brentworth.net/repair/nvidia-rtx-3000
81. PCB-Werke (DE) — RTX 3060 Ti repair from €120 + €50 diagnostic. https://www.pcb-werke.de/nvidia-rtx-3000-reparatur/
82. Repair Center (Lethbridge, CA) — $150 labour + $50 per memory module. https://repair-center.ca/
83. Computer Repairs Pronto (AU) — GPU repair from A$530, 12-month warranty. https://www.computerrepairspronto.com.au/services/graphics-card-repair-australia
84. Computer Cures (AU) — single-chip $200–400 / multi-chip $400–800+; stated 50–70% success on major damage. https://computercures.com.au/gpu-graphics-card-repair-cost-melbourne/
85. GPU Solutions — repair pricing (diagnostic AED 100–400 by tier, credited; normal repair ≈ 10% of UAE market value, min AED 200; parts extra) + core-reball page (flat AED 100 install tier). https://gpusolutions.net/detailed-repair-cost/ · https://gpusolutions.net/rbservices/gpu-core-reball/
39. ZOTAC USA warranty policy (Wayback 2025-12; 30-series = 2+1 yr, 30-day registration; stickers not valid in USA). https://web.archive.org/web/20251228094438/https://www.zotac.com/us/page/product-warranty-policy
40. ZOTAC EMEAI warranty policy (Wayback 2025-10; 3+2 yr; mining/third-party interference voids; 30-day grace). https://web.archive.org/web/20251012043233/http://www.zotac.com/emeai/page/product-warranty-policy
41. Warranty Week — 2025 GeForce warranty claims up ~1000%. https://www.warrantyweek.com/archive/ww20260409.html
42. NVIDIA — GeForce graphics-card warranty (warranty through the AIB). https://www.nvidia.com/en-us/support/warranty/graphics-cards/
156. pcprice.watch — RAM price guide 2026 (DRAM-crisis context). https://www.pcprice.watch/guides/ram-price-guide-2026-ddr5-ddr4-ddr3-used-dimm-market
158. Tom's Hardware — Zotac denies warranty on import-date grounds (India). https://www.tomshardware.com/pc-components/gpus/zotac-denies-warranty-support-to-rtx-3060-owner-in-india-after-just-one-year-despite-offering-three-years-of-coverage-company-says-gpus-2023-import-date-takes-precedence-over-purchase-date
159. Wccftech — Zotac fake-invoice warranty-registration scandal. https://wccftech.com/zotac-says-fake-invoice-was-used-for-warranty-registration-regarding-one-year-old-rtx-3060/
160. ECC Ireland — EU statutory remedies for faulty goods. https://www.eccireland.ie/faulty-goods-what-remedies-are-available-to-me/

**Creators & community**
69. gpu_lt ("GPU REPAIR IN EUROPE") — "3070 core on 3060ti pcb?" GA104 transplant (frames, text unreadable). https://www.youtube.com/watch?v=m7CXJxrMaCw
86. NorthWest Repair — public "GPU Shared" Google Drive (MATS/MODS ISOs incl. Mods 455 RTX30.iso; straps poster; channel-disable zip; pinout posters). https://drive.google.com/drive/folders/12XQpmc9tLwlRQjlo3Mn_XwKlVcV8XYGI
87. NorthWest Repair — "Watch this if you have 3060 Ti" (frames). https://www.youtube.com/watch?v=KVX0TuV-Fus
88. NorthWest Repair — "Are Zotac cards repairable? 3060 twin edge artifacts" (frames). https://www.youtube.com/watch?v=yh2acRteSVo
89. NorthWest Repair — "HP GeForce RTX 3060 TI artifacts fix" (frames; reball claim is title-only). https://www.youtube.com/watch?v=0lkXeV4V8KU
90. GPU Solutions / Graphics Card Repairs — "Fixing RTX 3060Ti – Hynix X005 Memory Upgrade" (frames; strap rearrangement). https://www.youtube.com/watch?v=Or83oiWeyJU
91. GPU Solutions / Graphics Card Repairs — "Asus TUF RTX 3060 Ti – Hynix X005 solution" (frames; 29.1 Ω reading). https://www.youtube.com/watch?v=VGpekr4MMQk
92. GPU Solutions — Palit RTX 3060 Ti Dual LHR Hynix→Samsung (frames; strap chapter, no reflash). https://www.youtube.com/watch?v=0Aau4UZK5fk
94. Kiki Hobby Repair — "Trying to fix 3 broken RTX 3060Ti graphics cards" (frames: donor cards, DMM checks, green PASS, Unigine). https://www.youtube.com/watch?v=avLM5Wyrsuo
95. VideoCardz — per-module GDDR6/GDDR6X temperature readouts (desktop GDDR6 not exposed). https://videocardz.com/newz/brazilian-gpu-mod-team-uncovers-per-module-temperatures-for-nvidia-gddr6-and-gddr6x-memory
96. Linus Tech Tips forum — Zotac RTX 3060 Ti Twin Edge OC LHR undervolt data (200→147 W; hotspot 90→82 °C). https://linustechtips.com/topic/1379971-zotac-rtx3060ti-twin-edge-oc-lhr-temperature-issue-just-sharing/
139. NorthWest Repair — boardview "All.zip" subfolder, now deleted (HTTP 404). https://drive.google.com/drive/folders/1bk3SnWCgzglM9ewO33RJKgZV5zO3hqgp
161. RadPaw — "RTX 3060 Ti Repair Hunting Down a Hidden Short" (2026-07-24; frames: schematic/boardview/PEAK_PWR_LOGIC/pF-meter short hunt). https://www.youtube.com/watch?v=UGq5OaU0Ho4
181. Linus Tech Tips forum — Zotac 3060 Ti, "stretched texture and polygon line artifacts", progressive, worse until memory downclock. https://linustechtips.com/topic/1580515/rtx-3060-ti-stretched-texture-and-polygon-line-artifacts/
182. r/GPURepair — 3060 Ti Gigabyte artifacting, suspecting VRAM. https://www.reddit.com/r/GPURepair/comments/1wi7hst/3060_ti_gigabyte_artifacting_suspecting_vram/
162. Electronics Repair School — "Zotac 3060 & 3060ti – Two cards, same fault" (members-only). https://www.youtube.com/watch?v=RbHlGSAks40
163. NorthWest Repair — official site (JS shell; repair status unconfirmed). https://northwestrepair.com

*Local artifacts (research folder):* `files/V390_PG142.pdf`, `files/TUF_3060ti.pdf` (+ `files/TUF_p26_tables.png`), `files/CG142S.pdf`, `files/xid_errors.pdf`, `files/drive/` NW Drive dump (incl. `extracted/dmc/` N306T_A–D.ROM and `fixed/*.jpg` — the raw `straps.png`/`GDDR7.png` are WebP-disguised PNGs; use the fixed JPEGs), `files/straps/` (Yandex-disk photo + crops), `frames/` (video frame sheets).
