---
name: qwen38-nvfp4-ops
description: Use when rebuilding, packing, or serving the Qwen3.8 Flash-Next Uncensored NVFP4 graft. Covers the RTN recipe, graft/requant scripts, and HF upload steps.
---

# Qwen3.8 Flash-Next Uncensored → NVFP4 graft

## Purpose

Build and serve `mazinb/Qwen3.8-Flash-Next-Uncensored-NVFP4`: the
abliterated OrcaRouter BF16 model (`orcarrouter/Qwen3.8-Flash-Next-Uncensored`,
336 GB, 131 shards, gated — access granted) quantized to NVFP4 for one
121 GiB Blackwell box. Working dir:
`/home/mazin/projects/qwen38-uncensored-nvfp4/`.

## Key paths

| Path | What |
|---|---|
| `graft.py` | Rebuild: `--download` fetches needed shards (~99 GB), hard-links the Primitive NVFP4 skeleton, requants expert `down_proj`, overlays BF16 writers |
| `test_nvfp4.py` | CPU NVFP4 packer round-trip test |
| `nvfp4.py` | Packer primitives (weight-only, group 16) |
| `TASKS.md` | Checklist — all items done as of 2026-08-29 |
| `/home/mazin/projects/vllm/Qwen3.8-Flash-Next-Uncensored-NVFP4` | Output checkpoint (hard-links Primitive skeleton + rewritten shards) |
| `/home/mazin/jupyterlab/.venv/bin/python` | Interpreter used for packer/graft runs |

## The recipe (do not deviate)

- **Experts only**: 48 layers × 512 routed experts (`gate`/`up`/`down`) →
  NVFP4 group 16. Producer string `modelopt 0.46.0-compatible-rtn`.
  **Weights-only RTN, no calibration; `input_scale = 1.0`.**
- **BF16 (never quantize)**: PLE n-gram table (51B — required by
  `VLLM_PLE_CPU_OFFLOAD`), attention, GDN, shared experts, routers, MTP,
  vision.
- **Abliteration overlay**: OrcaRouter only orthogonalized 149 residual-writer
  tensors (`self_attn.o_proj`, `linear_attn.out_proj`, fused
  `mlp.experts.down_proj` × 512 experts × 49 layers incl. MTP,
  `mlp.shared_expert.down_proj`, `ple.value_proj`, `embed_tokens`).
  `experts.gate_up_proj`, routers, vision, n-gram table, `lm_head`,
  Hyper-Connection mixers were never touched — so Primitive's NVFP4
  `gate_proj`/`up_proj` stays valid; only `down_proj` is re-quantized.
- Peak RAM is one 1.4 GiB expert shard, not 336 GB. Disk needs ~2.9 T free.

## Common commands

```bash
# Round-trip packer test (run before any rebuild)
/home/mazin/jupyterlab/.venv/bin/python test_nvfp4.py

# Full rebuild (~99 GB edited shards + requant + BF16 overlay)
/home/mazin/jupyterlab/.venv/bin/python graft.py --download

# Historical serve (see Pitfalls — vLLM is retired on GB10)
# start-vllm-flash.sh, daily default 64K × 4;
# 256K × 1: MAX_MODEL_LEN=262144 MAX_NUM_SEQS=1
# After reboot: enable-ple-swap.sh BEFORE vLLM.

# Upload
huggingface-cli repo create Qwen3.8-Flash-Next-Uncensored-NVFP4 --type model
huggingface-cli upload Qwen3.8-Flash-Next-Uncensored-NVFP4 \
  /home/mazin/projects/vllm/Qwen3.8-Flash-Next-Uncensored-NVFP4
```

## Verification

- `test_nvfp4.py` round-trip passes before any pack.
- After a rebuild: serve locally, `pong` ping + a vision `image_url` (red PNG)
  check before uploading to HF.
- Hub card: license **Qwen Community 1.0** (same as Primitive/Qwen source —
  never claim Apache), credit `orcarouter/Qwen3.8-Flash-Next-Uncensored` as
  the abliterated BF16 parent.

## Pitfalls

- **GB10 GPU rule wins now**: `vllm-text` is **retired**; port **:8000 stays
  free for experiments** and the GLM brain on :8888 (`glm53-flash-tf`) is
  **never** stopped, paused, or `docker rm`'d by anything. Do not restart
  vLLM or re-serve this checkpoint without an explicit user ask.
- Full-model ModelOpt `mtq.quantize` on 336 GB BF16 will OOM 121 GiB unified
  memory — the shard-by-shard graft is the only viable path.
- Never quantize the PLE n-gram table; `VLLM_PLE_CPU_OFFLOAD` needs it BF16.
- Do not claim Apache licensing on the Hub card.
- This is not: a calibrated PTQ, the FP8 uncensored checkpoint, or a 27B
  dense abliterated model.
