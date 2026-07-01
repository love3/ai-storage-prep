# 15 · Quantization & Inference Optimization

> JD Q9 (bonus): OSS model deploy, **quantization**, inference optimization, long-context
> tuning. Storage angle: quantization shrinks weights *and* KV cache → less to store, move,
> and offload.

## 1. Why quantize

- **Weights**: FP16 → INT8/FP8/INT4 cuts VRAM and model-file size 2–4× → fits bigger
  models, faster loading (less to read from SSD), less bandwidth per token in decode
  (decode is memory-bound!).
- **KV cache**: FP16 → FP8/INT8/INT4 cuts the KV footprint 2–4× → less HBM, less to
  offload/transfer (directly helps KV tiering + PD disaggregation).
- **Activations**: needed for full INT8 matmul (W8A8) to actually speed up compute.

## 2. Number formats

| Format | Bits | Note |
|--------|------|------|
| FP32 | 32 | training reference |
| FP16 / BF16 | 16 | standard inference; BF16 more exponent range |
| FP8 (E4M3/E5M2) | 8 | Hopper/Ada HW support; great accuracy/speed | 
| INT8 | 8 | W8A8 with scales; mature |
| INT4 | 4 | weight-only (W4A16) common; GPTQ/AWQ |
| INT2/ternary/1-bit | ≤2 | research (BitNet) |

**Quantization = map floats to a small integer grid via scale (and zero-point).**
- **Per-tensor** (one scale) → coarse; **per-channel/per-group** (e.g. group of 128) →
  much better accuracy. Outliers are the enemy.

## 3. PTQ vs QAT

- **PTQ (Post-Training Quantization)**: quantize a trained model, maybe with a small
  calibration set. Fast, no retraining. What you use in serving.
- **QAT (Quantization-Aware Training)**: simulate quantization during training → best
  accuracy at low bits, but expensive.

## 4. The key weight-quant methods (name them)

- **GPTQ**: layer-wise, uses second-order (Hessian) info to minimize error; good INT4
  weight-only. Fast, accurate.
- **AWQ (Activation-aware Weight Quant)**: protects the ~1% salient weight channels
  (identified via activation magnitude) by scaling → strong INT4 with little loss;
  hardware-friendly.
- **SmoothQuant**: migrates activation outliers into weights so **W8A8** works (enables
  INT8 activations, not just weights).
- **LLM.int8()**: mixed — keep outlier dims in FP16, rest INT8.
- **FP8**: often near-lossless with HW support; increasingly the default on new NVIDIA HW.
- **GGUF quants** (llama.cpp): Q4_K_M, Q5_K_M, Q6_K, Q8_0 — k-quants with per-block scales;
  the practical edge/CPU format.

## 5. KV cache quantization (storage-critical)

- Store K and V in FP8/INT8/INT4 instead of FP16 → 2–4× smaller KV.
- Care: K and V have different sensitivity; use **per-token / per-channel scaling**
  (methods: **KIVI** — per-channel K, per-token V; also FP8 KV in vLLM/TRT-LLM).
- Directly reduces HBM pressure, offload volume, and PD transfer bytes → **fewer bytes to
  move is the whole game** for the storage role.

## 6. Beyond quantization — inference optimizations to know

- **FlashAttention / FlashAttention-2/3**: IO-aware attention kernel — tiles Q,K,V through
  SRAM, avoids materializing the T×T attention matrix in HBM → O(T) memory, big speedup.
  (An "IO-aware algorithm" — a storage-minded person loves this framing.)
- **PagedAttention** (KB 11): memory efficiency.
- **Continuous batching** (KB 10): throughput.
- **Speculative decoding / Medusa / EAGLE**: cut sequential decode steps.
- **Chunked prefill**: cap TTFT interference.
- **Tensor/pipeline/expert parallelism**: shard big models across GPUs.
- **CUDA graphs, kernel fusion, quantized kernels (Marlin, FP8 GEMM)**: kernel-level.
- **MoE**: only a few experts active per token → more params, ~constant compute, but
  expert weights are a storage/loading problem (KTransformers offloads them).

## 7. Long-context tuning (JD Q9)

- **RoPE scaling** (linear/NTK/**YaRN**) to extend context beyond training length.
- **KV eviction/sparsity** (StreamingLLM sinks + sliding window, H2O, SnapKV) to bound KV.
- **Chunked prefill + prefix cache** to make long prompts affordable.
- **KV quantization + offload/tiering** to fit the KV in the hierarchy.
- Evaluate with **needle-in-a-haystack** / long-context benchmarks to ensure quality
  survives the tricks.

## 8. Accuracy vs efficiency (always mention the tradeoff)

Every optimization trades some quality/accuracy for speed/memory. Validate with
perplexity + task metrics; INT4 weight-only + FP8 KV is often a sweet spot; sub-4-bit and
aggressive KV eviction need careful eval. Never quote a compression number without the
accuracy caveat — interviewers probe for that maturity.

## 9. Interview-ready talking points

- "Quantization helps decode directly because decode is memory-bandwidth-bound — fewer
  bytes per weight and per KV element means more tokens/s and less to offload or
  transfer."
- "GPTQ uses Hessian-based error minimization; AWQ protects salient channels; SmoothQuant
  shifts activation outliers into weights to enable W8A8; FP8 is near-lossless on new
  hardware."
- "KV quantization (FP8/INT8, per-token/per-channel like KIVI) shrinks the exact thing I
  care about — the KV cache I have to store, tier, and move in PD disaggregation."
- "FlashAttention is an IO-aware kernel: tile through SRAM, never materialize the T×T
  matrix in HBM — the same 'respect the memory hierarchy' principle I apply to storage."
- "Every trick trades accuracy for efficiency; I'd validate INT4+FP8-KV with perplexity
  and long-context needle tests before shipping."
