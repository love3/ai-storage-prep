# Mock Interview · System Design (the headline round)

> These are open-ended. Structure every answer: **clarify requirements → back-of-envelope
> sizing → architecture → data path → failure/tail → tradeoffs → what I'd measure.**

---

## D1. Design a KV-cache offloading system for an LLM serving cluster.

**Clarify:** models & context lengths? concurrency/QPS? SLOs (TTFT, TPOT p99)? multi-turn/
RAG (prefix reuse)? single node or disaggregated? hardware (GPUs, NVMe, RDMA, CXL)?

**Sizing (do it out loud):** per-token KV (e.g. 128 KiB for 8B FP16); at ctx=8K that's
~1 GB/seq; 100 concurrent long sessions ≈ 100 GB → exceeds an 80 GB HBM after weights →
**must tier**. Decode step ~10–50 ms sets the latency budget for any readback.

**Architecture:**
- **Paged KV** (PagedAttention blocks) as the unit of placement.
- **Tiers:** HBM (active) → DRAM → CXL (byte-addressable) → NVMe SSD → remote/RDMA pool.
- **Global prefix cache** (content-hashed / radix tree) shared across instances to skip
  prefill on shared prefixes.
- **Placement/eviction policy:** keep actively-attended blocks in HBM; evict cold/paused
  sessions downward (LRU/importance); pin hot shared prefixes.
- **Prefetch engine:** predict next blocks (you know the layer/token order) and stage them
  up a tier ahead of need; **overlap with compute**.
- **Transport:** io_uring / **GPUDirect Storage** for SSD→GPU; RDMA (+GDS RDMA) for remote.
- **Reduce bytes:** FP8/INT8 **KV quantization**; compress cold KV.

**Failure/tail:** cache is reconstructable → on miss, **recompute** (prefill) as fallback;
bound p99 with predictable-latency SSD, QoS (separate namespaces / cgroup io.latency),
avoid GC jitter (over-provision, ZNS/FDP). Decide **offload vs recompute** per block by
comparing reload cost to recompute cost.

**Tradeoffs:** offload saves HBM/compute but adds latency & bandwidth pressure; quantization
saves bytes but risks accuracy; CXL is byte-addressable (attend near in-place) but slower
than DRAM. **What I'd measure:** KV cache hit rate per tier, prefix-cache hit rate,
readback p99, decode stall time, recompute rate, effective tokens/s. *(This is exactly what
my KV-offload simulator quantifies.)*

---

## D2. Design the storage/memory tier for prefill/decode disaggregation.

**Key idea:** a **KV pool** decoupled from compute. Prefill nodes write KV to the pool
(DRAM+SSD, RDMA-reachable); decode nodes pull from it; a directory/metadata service maps
`(request, layer, block) → location`. **Cache-aware scheduling** routes a request to a
decode node that already holds (part of) its prefix.

**Transfer:** stream **layer-by-layer** so decode starts as soon as early layers arrive;
one-sided **RDMA WRITE/READ**; **GPUDirect RDMA** to land KV in GPU HBM directly; NIXL/UCX/
Mooncake-style transfer engine.

**Sizing:** transfer time = KV bytes / link BW (1 GB over 400G RDMA ≈ 20 ms ≈ a few decode
steps) → must overlap/stream, quantize, and prefer prefix-cache hits to avoid transfer.

**Consistency/durability:** KV is reconstructable → weak consistency is fine; optimize
placement, eviction, and transfer latency, not linearizability. **Scaling:** consistent
hashing + membership for the pool; replicate hot prefixes.

**Tradeoffs:** disaggregation improves TTFT/TPOT and utilization but adds network
dependency and a KV-movement tax; worth it when prefill/decode interference or independent
scaling dominates.

---

## D3. Design a distributed object store for model weights & training/inference datasets.

**Requirements:** PB scale, immutable large objects (weights, shards, datasets), very high
**read** throughput to feed many GPUs, durability, multi-tenant.

**Architecture:** S3-style object API over a **RADOS/Ceph-like** core or consistent-hashing
placement (compute location, no central metadata bottleneck — like CRUSH). **Erasure
coding** (e.g. 8+3) for cold capacity efficiency; **replication** for hot/small.
**Parallel read** path: stripe large objects; clients read shards in parallel; cache hot
objects on local NVMe (dm-cache / app cache) and feed GPUs via **GDS**. For training,
consider a parallel FS / DAOS / 3FS for high-throughput random reads.

**Failure/tail:** background scrubbing + checksums (bit rot), rebalancing on membership
change (minimal movement via consistent hashing/CRUSH), **hedged reads** to tame tail
latency at fan-out. **Tradeoffs:** EC (space-efficient, CPU + slow recovery) vs replication
(fast, space-heavy). **Measure:** read GB/s per client, tail latency, rebalance data moved,
durability (annual data loss).

---

## D4. Your NVMe SSD tier hits a latency cliff under mixed read/write. Diagnose & fix.

**Diagnose:** confirm with `iostat -x` (w_await/r_await, aqu-sz), `nvme smart-log` (media
errors, temp, spare). The cliff is likely **SLC cache exhaustion + GC** under sustained
writes stealing bandwidth from reads, and possibly thermal throttling. Verify by
**preconditioning** and measuring steady state, and by isolating read-only vs mixed.

**Fix:** increase **over-provisioning**; make writes **sequential/append** (log-structured)
to cut WA; enable **TRIM**; separate read and write traffic (different namespaces / drives /
cgroup `io.max`); pick **predictable-latency / enterprise** drives; consider **ZNS/FDP** so
host controls placement; ensure alignment (avoid RMW); pin IRQ/threads NUMA-locally.
**Measure:** p99/p99.9 read latency under the mixed workload before/after, and WA (host vs
NAND writes).

---

## D5. Pick the async I/O + concurrency model for a new high-performance storage engine.

**A.** **Thread-per-core, shared-nothing** (each core owns a data shard + its own io_uring),
**coroutines** for programmability, **io_uring** for batched async I/O (SQPOLL/IOPOLL if the
latency justifies burning a core), **O_DIRECT** with the engine managing its own cache to
avoid double-caching, and **NUMA/PCIe-affinity** pinning. This removes lock contention and
cache-line bouncing that cap shared-everything designs at high core counts (the
Seastar/SPDK model). If the kernel stack itself is the proven bottleneck, go **SPDK**
(userspace poll-mode NVMe). **Measure:** IOPS/core, p99, scalability vs cores, and compare
kernel io_uring vs SPDK to quantify kernel overhead.
