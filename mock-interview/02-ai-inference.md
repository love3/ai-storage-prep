# Mock Interview · AI / LLM Inference & KV Cache

---

### Q1. Why does a KV cache exist, and how big is it?

**A.** In attention, each token's output is a weighted sum over the **Keys and Values of all
prior tokens**. Those K/V don't change once computed, so we cache them instead of
recomputing every step — turning per-step cost from O(t²) to O(t). Size:
`KV bytes = 2 × n_layers × n_kv_heads × head_dim × seq_len × batch × bytes_per_elem`.
The per-token part (e.g., ~128 KiB/token for Llama-3-8B in FP16) times context times batch
grows fast — at long context and high concurrency the KV cache **dwarfs the model
weights**, which is exactly why storage/memory hierarchy becomes the bottleneck.

---

### Q2. Explain prefill vs decode and why it matters for hardware.

**A.** **Prefill** processes the whole prompt in parallel — big matmuls, **compute-bound**,
sets TTFT. **Decode** generates one token at a time; each step must **read all model
weights (and the KV cache) from HBM** to produce a single token → tiny arithmetic
intensity → **memory-bandwidth-bound**, sets TPOT/inter-token latency. So
**decode throughput ≈ HBM bandwidth ÷ bytes-read-per-token**, and **batching** amortizes
the weight read across many sequences. Their opposite profiles (compute-heavy bursty vs
memory-heavy steady) are why mixing them interferes — the motivation for PD
disaggregation. *I have a sizing calculator that computes this per model/GPU.*

---

### Q3. What is PagedAttention and why did it matter?

**A.** Naive serving pre-allocates a contiguous KV buffer per sequence sized to
`max_seq_len` → huge internal fragmentation and wasted HBM, and no sharing. **PagedAttention**
(vLLM) applies **OS virtual-memory paging** to KV: fixed-size **blocks** (e.g. 16 tokens)
plus a per-sequence **block table** mapping logical→physical blocks. Blocks are allocated
on demand and need not be contiguous → near-zero fragmentation → much higher batch sizes
and HBM utilization; plus **copy-on-write** sharing for common prefixes / beam search.
It's literally a page table for KV cache — if you know virtual memory, you know
PagedAttention.

---

### Q4. How would you offload KV cache to SSD without wrecking decode latency?

**A.** Treat it as a **multi-tier cache with a hard latency budget**. Keep the *actively
attended* KV in HBM; offload only **cold/paused** sessions and reusable prefixes down
HBM→DRAM→CXL→SSD. Make transfers cheap and hidden: **block-granular** (match paging),
**prefetch** the blocks the next layers/tokens will touch and **overlap** the read with
current compute (classic readahead), drive it with **high-QD async I/O (io_uring)** or
**GPUDirect Storage** to DMA SSD→GPU directly, and **quantize KV (FP8/INT8)** to move fewer
bytes. Decide **offload vs recompute** by comparing reload bandwidth cost to prefill
recompute cost. *My KV-offload simulator shows tiering turning ~54% recompute misses into
cheap SSD/CXL readbacks (avg ~1170 µs → ~22 µs), and prefetch hiding the SSD latency.*

---

### Q5. What's prefix caching and when is it a big win?

**A.** Identical prefixes across requests — system prompts, few-shot templates, RAG
documents, chat history — produce identical KV. **Automatic prefix caching** (vLLM) hashes
the prefix and reuses cached KV blocks; **RadixAttention** (SGLang) keeps prefixes in a
radix tree with LRU eviction for fine-grained cross-request sharing. The win: **skip
prefill for the shared part** → big TTFT and throughput gains, and a smaller working set.
Huge for agents, chat, and RAG where prefixes overlap heavily; loading a long shared prefix
from cache can beat recomputing it on the GPU.

---

### Q6. Explain PD (prefill/decode) disaggregation and its main challenge.

**A.** Run prefill on one GPU pool and decode on another, transferring the KV cache between
them. Benefits: no prefill/decode interference (better TTFT *and* TPOT together),
independent scaling (tune the prefill:decode ratio), and hardware specialization. The main
challenge is **moving GBs of KV per request fast enough** — solved by **streaming KV
layer-by-layer** over RDMA/NVLink/**GPUDirect**, overlapping transfer with compute,
**quantizing KV**, and **reusing prefixes** (global prefix cache) so you often skip the
transfer. **Mooncake** is the reference: a KV-cache-centric disaggregated design with a
global DRAM+SSD KV pool over RDMA and cache-aware scheduling.

---

### Q7. Long-context inference (128K–1M tokens) — what breaks and how do you fix it?

**A.** Two things break. (1) **Prefill compute is O(T²)** — mitigate with **FlashAttention**
(tile through SRAM, never materialize the T×T matrix), **chunked prefill**, **prefix
cache**, and **ring/context parallelism** (shard the sequence). (2) **KV memory is O(T)** —
hundreds of GB per sequence, won't fit HBM — mitigate with **offload/tiering** to
DRAM/CXL/SSD (+prefetch), **KV quantization**, **sparsity/eviction** (StreamingLLM attention
sinks + sliding window, H2O, SnapKV), and architectural tricks (**MLA** latent KV
compression, GQA, hybrid SSM layers). It's fundamentally a memory-hierarchy + I/O-scheduling
problem — a storage problem wearing an AI hat.

---

### Q8. Compare vLLM, SGLang, TensorRT-LLM, llama.cpp for a serving decision.

**A.** **vLLM**: PagedAttention + continuous batching → high-throughput GPU serving,
automatic prefix caching, CPU/KV offload connectors. **SGLang**: RadixAttention prefix tree
+ **HiCache** GPU/CPU/SSD KV tiering → best for heavy prefix reuse (agents/RAG).
**TensorRT-LLM**: compiled fused kernels, FP8/INT4 → lowest latency/highest efficiency on
NVIDIA, at the cost of a per-config build (often behind Triton). **llama.cpp/Ollama**: pure
C/C++, CPU/Metal/CUDA, GGUF quant, partial GPU offload → local/edge/AI-PC. Rule of thumb:
throughput→vLLM/TRT-LLM; prefix-heavy→SGLang; NVIDIA min-latency→TRT-LLM; run-anywhere→
llama.cpp; giant MoE on small VRAM→KTransformers.

---

### Q9. How does quantization help, and what are the main methods?

**A.** It shrinks **weights** and **KV cache**, and because decode is memory-bound, fewer
bytes/weight and bytes/KV means more tokens/s *and* less to offload/transfer. Weight
methods: **GPTQ** (Hessian-based error minimization, INT4), **AWQ** (protect salient
channels), **SmoothQuant** (shift activation outliers into weights to enable W8A8), **FP8**
(near-lossless on new HW), **GGUF k-quants** (edge). **KV quantization** (FP8/INT8, per-
token/per-channel like **KIVI**) directly shrinks the thing I care about. Always validate
with perplexity + task/long-context metrics — every trick trades some accuracy.

---

### Q10. What is GPUDirect Storage and why does it matter here?

**A.** GDS lets an **NVMe SSD (or NVMe-oF target) DMA directly into GPU HBM** via PCIe
peer-to-peer, bypassing the CPU/DRAM **bounce buffer** (API: `cuFile`). That's what makes
**SSD-backed KV tiers** and fast weight loading viable at scale — you feed the GPU at PCIe
bandwidth without burning host CPU/DRAM bandwidth. Combined with **GPU-Initiated Storage**
(the GPU itself issues NVMe I/O mid-kernel, BaM-style), the GPU can **demand-page** KV
blocks or embeddings from SSD without a CPU round-trip — ideal for sparse long-context KV
access. **CXL** adds a byte-addressable memory tier between DRAM and SSD for KV offload/
pooling.
