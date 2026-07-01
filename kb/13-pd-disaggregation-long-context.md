# 13 · PD Disaggregation & Long-Context Inference

> JD R6 headline topics: "PD分离架构对存储需求" and "长上下文推理". This is the frontier the
> role is being hired to work on — go deep.

## 1. Why disaggregate Prefill and Decode

Recall (KB 10): **prefill is compute-bound**, **decode is memory-bandwidth-bound**, and
their profiles conflict. When both run on the same GPU/engine:
- A long prefill **stalls** ongoing decodes (a big prompt monopolizes compute) → decode
  latency (TPOT) spikes.
- You can't independently scale or tune them; batching one hurts the other.
- Different optimal hardware: prefill wants FLOPs; decode wants bandwidth + big batch.

**PD disaggregation** = run prefill on one pool of GPUs, decode on another, and **transfer
the KV cache** from prefill nodes to decode nodes.

```
Request ─► [Prefill pool]  compute prompt KV, first token
                  │  transfer KV cache (RDMA / NVLink / GDS)
                  ▼
           [Decode pool]  autoregressive generation using received KV
```

Benefits: independent scaling (ratio of prefill:decode GPUs tuned to workload), no
prefill/decode interference → better **TTFT** *and* **TPOT** simultaneously, hardware
specialization, higher goodput.

Cost / new problems: **you must move the KV cache fast** (GBs) and manage a **KV pool** —
this is precisely the storage/networking problem the role owns.

## 2. The KV transfer problem (storage/network core)

For each request, prefill produces the prompt's KV (can be GBs for long prompts). To
start decode you must get it to the decode GPU:

- **Transport**: RDMA (RoCE/IB), NVLink (same node), or **GPUDirect** (NIC/SSD → GPU HBM
  directly, KB 14). Libraries: **NIXL**, **UCX**, **Mooncake transfer engine**, NCCL.
- **Layer-wise / chunked streaming**: don't wait for the whole KV — stream layer L's KV
  while prefill computes layer L+1, and start decode as chunks arrive → **overlap hides
  transfer latency**. (Same overlap principle as prefetch in storage.)
- **KV pool / cache**: a shared, tiered store (DRAM/CXL/SSD/remote) holding KV so that (a)
  decode nodes pull from it, (b) prefixes are reused across requests and nodes (global
  prefix cache), (c) prefill can be skipped on cache hits.
- **Placement & scheduling**: route a request to a decode node that already has (part of)
  its prefix KV → cache-affinity scheduling (Mooncake, SGLang, Dynamo do this).

**Bandwidth reasoning (say it):** transfer time = KV bytes / link BW. For 1 GB of KV over
Gen5 x16 (~64 GB/s) ≈ 16 ms; over 400G RDMA (~50 GB/s) ≈ 20 ms. That's comparable to
several decode steps → must overlap/stream, quantize KV to move fewer bytes, and exploit
prefix cache hits to avoid transfer entirely.

## 3. Mooncake (the canonical case study — read it)

Kimi/Moonshot's serving architecture. Key ideas to cite:
- **KVCache-centric, disaggregated**: separate prefill and decode pools, plus a **global
  KV cache pool** pooled from **CPU DRAM + SSD across the cluster**, connected by a
  high-speed **RDMA transfer engine**.
- **Prefix cache reuse** across the cluster: dedup/reuse KV for shared prefixes → less
  prefill, less transfer.
- **Cache-aware scheduling**: route to nodes with the relevant KV; balance load vs cache
  locality.
- Handles overload with early rejection / SLO-based admission.
- Thesis: **treat KV cache as the central, tiered, distributed data structure of the
  serving system** — a storage system problem. This is *the* paper to reference for this
  role.

Also: **NVIDIA Dynamo** (disaggregated serving framework + NIXL + KV-aware routing),
**DistServe**, **Splitwise** (prefill/decode split analysis), **LMCache**.

## 4. Long-context inference

Long context (128K → 1M+ tokens) stresses two things:

**(a) Prefill compute — quadratic.** Attention is O(T²). A 1M-token prompt is enormous.
Mitigations:
- **Chunked / piecewise prefill**, **prefix cache** (skip already-seen context),
  efficient attention kernels (**FlashAttention**: tiling to keep attention in SRAM,
  O(T) memory not O(T²)), **ring attention / context parallelism** (shard the sequence
  across GPUs).

**(b) KV cache memory — linear in T.** 1M tokens × per-token KV can be **hundreds of
GB per sequence** → cannot fit in HBM. Mitigations (all storage-relevant):
- **Offload/tiering** KV to DRAM/CXL/SSD (KB 11) with prefetch.
- **KV quantization** (FP8/INT4).
- **Sparsity / eviction**: attention **sinks** + sliding window (**StreamingLLM**),
  **H2O**, **SnapKV**, quest — keep only "heavy hitter" tokens → bounded KV.
- **Architectural**: **MLA** (DeepSeek latent KV compression), GQA/MQA, hybrid
  attention/SSM (Mamba/linear attention layers) to cap KV growth.
- **Retrieval-style**: keep full KV in SSD, load only the blocks that attention will
  actually weight (sparse/paged retrieval of KV).

**The pitch:** "Long-context serving is fundamentally a memory-hierarchy and I/O
scheduling problem: the KV cache for 1M tokens lives across HBM/DRAM/CXL/SSD, and the job
is to load the right blocks fast enough — prefetch, quantize, evict, and DMA directly to
the GPU. That's a storage systems problem wearing an AI hat."

## 5. Storage requirements PD/long-context impose (JD "推导产品核心需求")

- **Capacity**: KV pool sized for concurrent long sessions + prefix cache (10s–100s TB
  SSD, TBs DRAM/CXL).
- **Bandwidth**: sustain KV transfer + offload/reload at aggregate GB/s per GPU → many
  NVMe drives, RDMA fabric, GDS.
- **Latency / tail**: p99 KV block fetch must fit inside a decode step's overlap window →
  high-QD async, predictable-latency SSD, avoid GC jitter.
- **Read pattern**: mostly-read, high-QD, block-granular (paged) random reads of KV; write
  = append on offload. → favors QLC/ZNS/FDP, big DRAM map.
- **Consistency**: cache-weak (reconstructable); focus on placement/eviction/transfer.
- **Interfaces**: KV connector / transfer engine (NIXL/UCX), GDS, NVMe-oF for remote pool.

## 6. Interview-ready talking points

- "Prefill and decode have opposite resource profiles and interfere; PD disaggregation
  runs them on separate pools and ships the KV cache between them, so you scale each
  independently and improve TTFT and TPOT together."
- "The catch is moving GBs of KV per request — solved by streaming KV layer-by-layer over
  RDMA/NVLink/GDS, overlapping with compute, quantizing KV, and reusing prefixes so you
  skip transfer entirely."
- "Mooncake is the reference: a KV-cache-centric disaggregated design with a global
  DRAM+SSD KV pool over RDMA and cache-aware scheduling — LLM serving as a distributed
  storage problem."
- "Long context is a memory-hierarchy problem: quadratic prefill (mitigated by
  FlashAttention, chunked prefill, prefix cache, ring attention) plus linear KV growth
  that overflows HBM into DRAM/CXL/SSD, tamed by offload+prefetch, KV quantization, and
  sparsity like StreamingLLM sinks and H2O."
- "From those, I derive product needs: high-QD read-optimized SSD (QLC/ZNS), big DRAM/CXL
  map, RDMA + GPUDirect Storage, predictable tail latency, and a KV connector interface."
