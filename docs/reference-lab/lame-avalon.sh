#!/bin/sh
# The reference lab's primary server ("lame"): Qwen3.8-Flash-Next IQ3_KS on Avalon (a llama.cpp fork, HIP build)
# on an RX 7800 XT 16 GB + Ryzen 5 3600 + 128 GB DDR4. In the lab this runs as a NixOS systemd unit; this is the
# same command line as a plain script. Engine: https://github.com/freriadoc/Avalon  Model:
# https://huggingface.co/freriadoc/Qwen3.8-Flash-Next-Avalon-GGUF (33 shards + MTP head + mmproj + moe-cache-ranking.bin)
#
# Run it from the model directory: the expert cache is prefilled from moe-cache-ranking.bin beside the model.
# PATH must contain ffmpeg (WebP pictures, docs/TROUBLESHOOTING.md).
M=/models/freriadoc/Qwen3.8-Flash-Next-Avalon-GGUF
cd "$M" || exit 1
exec llama-server \
  --device ROCm0 \
  --host 0.0.0.0 --port 8080 \
  -m "$M/Qwen3.8-Flash-Next-Avalon-IQ3KS-00001-of-00033.gguf" \
  --alias qwen3.8-flash-next-iq3ks \
  -c 262144 \
  -b 2048 -ub 2048 `# NOT upstream's 9536 (tuned on 20 GB): on 16 GB it OOMs past ~32K of context` \
  -fa on -ctk q8_0 -ctv q4_0 \
  --jinja \
  --parallel 1 `# a sparse MoE gains nothing from more slots; --cache-ram (default 8 GiB) keeps idle conversations` \
  -md "$M/MTP/mtp-Qwen3.8-Flash-Next-shared-IQ3K-IQ4NL-FR65k.gguf" \
  --spec-type draft-mtp --spec-draft-n-max 2 -ubd 256 -ctkd q8_0 -ctvd q8_0 \
  --mmproj "$M/mmproj-Qwen3.8-Flash-Next-BF16.gguf" \
  --mmproj-device Vulkan0 `# the image encoder on a second, older card (RX 570); "none" puts it on the CPU` \
  --image-max-tokens 1536 \
  --temp 0.65 --top-p 0.95 --top-k 20 --min-p 0.05 --repeat-penalty 1.0 \
  --chat-template-kwargs '{"preserve_thinking": true, "reasoning_effort":"medium"}' \
  --reasoning-budget 8192 `# below dsh's 16384 output cap, or the model thinks to "length"` \
  --no-webui
