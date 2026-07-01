# 11 · KV Cache: Lifecycle, Reuse, Offload, Tiering

> **The single most important note for this role.** JD R6 lists KV cache generation,
> access, reuse, offload, readback, and tiered offloading explicitly. This is where your
> storage expertise becomes an AI superpower.

## 1. KV cache lifecycle (the "generation → access → reuse → offload → readback" of the JD)

1. **Generation**: during prefill, every prompt token's K,V are computed and written; each
   decode step appends one token's K,V.
2. **Access**: every decode step reads the *entire* KV cache for that sequence (all layers,
   all prior tokens) to compute attention → read-heavy, latency-critical.
3. **Reuse**: identical prefixes (system prompts, few-shot examples, chat history,
   RAG documents) produce identical KV → cache and **reuse across requests** (prefix
   caching) to skip recomputation.
4. **Offload**: when KV exceeds HBM, move cold/less-active blocks down the hierarchy
   (HBM → DRAM → CXL → NVMe SSD → remote).
5. **Readback**: bring offloaded KV back (or attend to it in place) before it's needed —
   **prefetch to hide latency**.

This maps 1:1 onto a classic **multi-tier cache** with generation, hit/miss, eviction,
prefetch, and writeback — your wheelhouse.

## 2. PagedAttention (vLLM) — the foundational idea

**Problem:** naive serving allocates a contiguous KV buffer for each sequence sized to
`max_seq_len` → massive **internal fragmentation** and wasted HBM (you reserve for the
worst case). Also can't share.

**Solution (PagedAttention):** treat KV cache like **virtual memory with paging**.
- KV cache is split into fixed-size **blocks** (e.g., 16 tokens each).
- A per-sequence **block table** maps logical blocks → physical KV blocks (like a page
  table maps virtual → physical pages).
- Blocks are allocated on demand, need not be contiguous → **near-zero fragmentation**,
  much higher batch sizes / HBM utilization.
- **Copy-on-write** sharing: multiple sequences (or beams, or a shared prefix) point at
  the same physical blocks until one writes.

**This is literally OS virtual memory applied to KV cache.** If you know page tables, you
understand PagedAttention — say exactly that in the interview.

## 3. Prefix caching / reuse (huge practical win)

- **Automatic prefix caching (APC)**: hash the token prefix; if a new request shares a
  prefix (system prompt, common instructions, a RAG document, prior chat turns), reuse
  the already-computed KV blocks → **skip prefill for the shared part** → big TTFT and
  throughput wins.
- **RadixAttention (SGLang)**: organizes cached prefixes in a **radix tree** keyed by
  token sequences, with LRU eviction → automatic, fine-grained prefix sharing across
  requests. Excellent for chat, agents, few-shot, RAG where prefixes overlap heavily.
- Reuse turns prefill from a recompute cost into a **cache lookup + load** — and loading
  from DRAM/SSD can beat recomputing on GPU when prefixes are long.

## 4. The tiering hierarchy for KV cache

```
HBM  ── active sequences' hot KV (must be here to attend)
 │  evict/offload cold blocks  ▲ prefetch hot blocks back
DRAM ── recently used / paused sessions / near-term reuse
 │
CXL  ── memory-pool tier: larger, still byte-addressable, ~µs
 │
NVMe SSD ── prefix cache, paused/long sessions, cheap capacity
 │
Remote (RDMA / object) ── shared cluster KV pool, cold prefixes
```

**Design questions the JD wants you to reason about:**
- **What to keep hot?** Active decoding sequences must have their KV reachable by the GPU
  each step. Paused/idle sessions and reusable prefixes can go cold.
- **Granularity?** Per-block (page) offload, matching PagedAttention blocks.
- **When to offload?** On eviction pressure; predictively for paused sessions.
- **When to fetch back?** **Prefetch ahead of need** — you know the next layers/tokens
  you'll touch, so overlap the read with current compute (classic prefetching).
- **Offload vs recompute?** If bandwidth to fetch KV < cost to recompute prefill on GPU,
  offload+reload wins (long prefixes); else recompute. This is a real tradeoff to
  articulate.

## 5. The latency budget (do this math)

A decode step is ~10–50 ms. To offload/read KV without stalling, the transfer must finish
within the compute time it overlaps.
- Per-token KV ~ 100s KB–1 MB; a block (16 tokens) ~ MBs; a full long-context sequence ~
  many GB.
- PCIe Gen5 x16: ~64 GB/s → 1 GB in ~16 ms. NVMe Gen5 x4: ~14 GB/s → 1 GB in ~70 ms.
- **Conclusion:** you can't naively reload GBs of KV per step; you must (a) keep the
  *actively attended* KV in HBM, (b) offload only cold/paused KV, (c) **prefetch** and
  **overlap** aggressively, (d) use **high-QD async I/O (io_uring/GDS)** and possibly
  **GPUDirect Storage** to DMA SSD→GPU directly (KB 14), (e) compress/quantize KV to move
  fewer bytes.

This budgeting is exactly "分析计算、显存、内存与存储需求" and "推导产品核心需求" from the JD.

## 6. Reducing KV cache size (so you offload less)

- **GQA/MQA/MLA** (fewer KV heads / latent compression) — architectural.
- **KV quantization**: store K,V in FP8/INT8/INT4 → 2–4× smaller, with accuracy care
  (per-channel/per-token scaling; KIVI, etc.).
- **Eviction / sparsity**: keep only important tokens (H2O, StreamingLLM's attention
  sinks + sliding window, SnapKV, scissorhands) → bounded KV for long context.
- **Compression** of cold KV before SSD offload.

## 7. Systems that do KV offload / disaggregation (name-drop these)

- **vLLM**: PagedAttention, APC, CPU offload, and a KV connector API.
- **SGLang**: RadixAttention prefix cache; **HiCache** hierarchical KV (GPU/CPU/SSD).
- **LMCache**: KV caching/offload layer (DRAM/SSD/remote) that plugs into vLLM; prefix
  reuse across requests and instances.
- **Mooncake** (Kimi/Moonshot): KVCache-centric **disaggregated** architecture — a global
  KV cache pool over DRAM/SSD across the cluster with an RDMA transfer engine; prefill/
  decode disaggregation. The canonical "storage-centric LLM serving" paper.
- **NVIDIA Dynamo / NIXL**: disaggregated serving + KV transfer library.
- **DeepSeek 3FS**: high-throughput distributed FS feeding KV/training.

## 8. Analogy table (storage concept → KV cache concept)

| Storage / OS concept | KV cache analog |
|----------------------|-----------------|
| Virtual memory / page table | PagedAttention block table |
| Page / block | KV block (e.g., 16 tokens) |
| Page fault → load from disk | KV block miss → fetch from DRAM/SSD |
| Page cache / LRU | KV cache eviction (LRU/LFU/importance) |
| Prefetch / readahead | KV prefetch ahead of decode |
| Writeback | KV offload to lower tier |
| Copy-on-write | shared prefix blocks, beam search |
| Dedup / content hashing | prefix hashing (APC/RadixAttention) |
| Tiered storage (hot/warm/cold) | HBM/DRAM/CXL/SSD KV tiers |
| DMA / zero-copy | GPUDirect Storage into GPU HBM |

**Memorize this table** — it *is* your interview narrative.

## 9. Interview-ready talking points

- "KV cache is a textbook multi-tier cache: generate on prefill, read every decode step,
  reuse shared prefixes, evict/offload under pressure, prefetch back before use."
- "PagedAttention is OS paging for KV — fixed blocks + a per-sequence block table kill
  fragmentation and enable copy-on-write sharing; that's the vLLM throughput win."
- "Prefix caching (APC / SGLang RadixAttention) turns repeated system prompts, RAG docs,
  and chat history into cache hits, skipping prefill — often the biggest real-world win."
- "Offloading is a latency-budget problem: keep actively-attended KV in HBM, offload only
  cold/paused blocks, prefetch and overlap with compute, and use high-QD async I/O or
  GPUDirect Storage; recompute instead when that's cheaper than reloading."
- "To move fewer bytes I'd quantize KV to FP8/INT8 and use eviction/sparsity
  (StreamingLLM sinks, H2O) for long context; Mooncake shows the disaggregated,
  KV-pool-centric end state."
