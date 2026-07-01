# 10 · Transformer & LLM Inference Basics

> JD Q7: Transformer, inference flow, attention, KV cache, prefill/decode, context window,
> batching. This is the conceptual foundation for everything storage-for-AI.

## 1. The Transformer decoder (inference view)

An autoregressive LLM is a stack of **N identical decoder layers**. Each layer:

```
x → LayerNorm → Multi-Head Attention → +residual
  → LayerNorm → FFN (MLP, 2 linears + activation) → +residual
```

- **Tokens** → **embeddings** (vectors of dim `d_model`, e.g. 4096).
- **Attention** lets each token attend to previous tokens (causal mask → can't see
  future).
- **FFN** is the bulk of the parameters (usually ~2/3 of weights).
- Final **LM head** projects to vocabulary logits → sample the next token.

Autoregressive generation: produce one token, append it, feed back, repeat.

## 2. Attention & why KV cache exists

For each token, attention computes **Query, Key, Value** vectors (via weight matrices
Wq, Wk, Wv). The output for a token is a weighted sum of the **Values** of all previous
tokens, weighted by `softmax(Q·Kᵀ / √d)`:

```
Attention(Q,K,V) = softmax(QKᵀ/√d_k) V
```

**Key insight:** to generate token *t*, you need the **K and V of all tokens 1..t-1**.
Those don't change once computed. So instead of recomputing them every step
(O(t²) waste), you **cache** them: this is the **KV cache**. Each new token computes its
own K,V once, appends to the cache, and attends over the whole cache. → generation
becomes O(t) per step instead of O(t²).

### Attention variants (they change KV cache size!)
- **MHA** (multi-head): H separate K/V heads → biggest KV cache.
- **MQA** (multi-query): all query heads share **one** K/V head → KV cache ÷ H.
- **GQA** (grouped-query): G groups share K/V → middle ground (Llama-2/3 use GQA). This
  is the main lever most models use to shrink KV cache.
- **MLA** (multi-head latent attention, DeepSeek): compresses K/V into a low-rank latent →
  much smaller KV cache; a hot research/production direction.

## 3. Prefill vs Decode — the two phases (MUST know cold)

| | **Prefill** | **Decode** |
|--|-------------|-----------|
| Input | the whole prompt (T tokens) at once | 1 token at a time |
| Parallelism | all prompt tokens in parallel | inherently sequential |
| Bottleneck | **compute-bound** (big matmuls, GEMM) | **memory-bandwidth-bound** |
| Produces | KV cache for the prompt + first token | 1 token + grows KV cache |
| Cost driver | O(T²) attention, big FLOPs | reload weights + KV each step |
| Metric | **TTFT** (time to first token) | **TPOT/ITL** (time per output token) |

**Why decode is memory-bound:** each decode step processes just *one* token but must
**read all model weights from HBM** (and the whole KV cache) to compute one token. The
arithmetic intensity is tiny (few FLOPs per byte loaded) → limited by **HBM bandwidth**,
not compute. This is the single most important fact for a storage/memory person:

> **Decode throughput ≈ HBM bandwidth / (bytes read per token).** More users/batching
> amortizes the weight read across many tokens → higher GPU utilization.

**Why they conflict:** prefill (compute-heavy, bursty) and decode (memory-heavy, steady)
have opposite resource profiles; mixing them in one engine causes interference → the
motivation for **PD disaggregation** (KB 13).

## 4. Batching (throughput lever)

- **Static batching**: wait to fill a batch, run together — bad latency, GPU idles.
- **Continuous / in-flight batching** (Orca, vLLM): schedule at the **iteration** level —
  finished sequences leave, new ones join every step, GPU never waits for the slowest.
  This is *the* throughput unlock for serving.
- Batching amortizes the weight-read (the memory-bound cost) across many sequences →
  raises tokens/s dramatically, at some latency cost. There's a batch-size vs latency
  tradeoff (and KV memory limits max batch).

## 5. Sizing the numbers (arithmetic you should do live)

**Model weight memory** ≈ params × bytes/param.
- 7B in FP16 ≈ 14 GB; in INT4 ≈ ~3.5 GB. 70B FP16 ≈ 140 GB (needs ≥2 GPUs).

**KV cache size** (the storage-relevant one):
```
KV bytes = 2 (K and V) × n_layers × n_kv_heads × head_dim × seq_len × batch × bytes_per_elem
```
- The `2 × n_layers × n_kv_heads × head_dim × bytes` part = **per-token KV size**.
- Example (Llama-2-13B-ish, MHA, FP16): ~800 KB–1 MB **per token**. At 4K context that's
  several GB per sequence; at 100 concurrent long sequences it dwarfs the weights.
- GQA/MQA/MLA shrink `n_kv_heads` → smaller KV. KV quantization (FP8/INT8) halves it.

**This is the crux of the role:** KV cache grows linearly with **context length × batch**
and quickly exceeds HBM → you must **page it, quantize it, offload it to DRAM/CXL/SSD, or
recompute it** (KB 11, 13).

## 6. Context window & long context

- **Context window** = max tokens the model attends over (2K → 128K → 1M+).
- Longer context = quadratic attention compute in prefill + **linear KV cache growth** →
  memory explosion. Long-context serving is fundamentally a **memory/storage** problem.
- Positional encoding (RoPE + scaling like YaRN) enables extension.

## 7. Sampling & throughput terms

- **Greedy / temperature / top-k / top-p / beam** sampling.
- **Speculative decoding**: a small draft model proposes k tokens, the big model verifies
  in one pass → fewer sequential big-model steps → lower latency (trades compute for
  latency). Also: Medusa, EAGLE, lookahead.
- Serving KPIs: **TTFT**, **TPOT/ITL** (inter-token latency), **throughput (tokens/s)**,
  **goodput** (requests meeting SLO), **GPU utilization (MFU)**.

## 8. Interview-ready talking points

- "Attention needs the K and V of all prior tokens; caching them (KV cache) turns
  per-step cost from O(t²) to O(t) — but the cache grows linearly with context × batch
  and becomes the memory bottleneck."
- "Prefill is compute-bound (parallel matmul over the prompt); decode is
  memory-bandwidth-bound (read all weights + KV to make one token). Decode throughput ≈
  HBM bandwidth ÷ bytes-per-token, which is why batching matters."
- "Continuous batching schedules at the iteration level so the GPU never idles waiting
  for the slowest sequence — the big serving-throughput win."
- "KV cache per token = 2 × layers × kv_heads × head_dim × bytes; GQA/MQA/MLA and KV
  quantization shrink it, and beyond HBM you page/offload/recompute it."
- "Long context is really a memory-hierarchy problem: quadratic prefill compute plus
  linear KV growth — exactly where storage and CXL/SSD tiering enter."
