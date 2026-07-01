# 14 · GPUDirect Storage, GPU-Initiated Storage, CXL & Emerging Tech

> JD R8: track GDS, GPU-Initiated Storage, CXL, NVMe, OCP; assess product impact and make
> standards proposals. This note is about the near-future data-movement stack for AI.

## 1. The problem: the CPU/DRAM "bounce buffer" tax

Traditionally, to get data from SSD/NIC into GPU memory: SSD → **host DRAM (bounce
buffer)** → GPU HBM (two copies, CPU involved, extra latency + DRAM bandwidth burned).
At AI scale (feeding many GPUs KV cache and datasets) this bounce buffer becomes a
bottleneck. The whole "GPUDirect" family removes the CPU/DRAM from the path via **PCIe
peer-to-peer DMA**.

## 2. GPUDirect family

- **GPUDirect RDMA**: a NIC DMAs directly to/from **GPU memory** over PCIe P2P → GPU↔GPU
  across nodes without host copies. Basis of NCCL/RDMA collectives and KV transfer in PD
  disaggregation.
- **GPUDirect Storage (GDS)**: an **NVMe SSD (or NVMe-oF target) DMAs directly into GPU
  HBM**, bypassing the host bounce buffer. API: **cuFile** (`cuFileRead`/`cuFileWrite`).
  Under the hood it uses P2P DMA + a kernel driver (`nvidia-fs`) that hooks the block
  layer / VFS to map GPU buffers as DMA targets.
  - **Why it matters here:** offloaded KV cache and model weights can be loaded
    **SSD → GPU directly** at PCIe bandwidth with low CPU cost → the enabling tech for
    SSD-backed KV tiers and fast model loading.
  - Works with local NVMe and **NVMe-oF over RDMA** (remote KV pool → GPU directly).
- **GPUDirect Async / Storage-Next**: reduce CPU from the *control* path too (submission),
  not just data.

## 3. GPU-Initiated Storage (the frontier)

Normally the **CPU** issues I/O (submits NVMe commands). **GPU-Initiated Storage** lets the
**GPU itself** initiate storage I/O from within a kernel — the GPU rings the NVMe
doorbell / posts commands directly, no CPU round-trip.
- Projects/ideas: **BaM (Big accelerator Memory)** (GPU-orchestrated NVMe access, treat
  SSD as GPU-addressable memory), **SCADA / GPUDirect Storage-next**, NVIDIA "GPU-initiated
  communication".
- **Why it matters:** for fine-grained, data-dependent access (e.g., the GPU decides
  which KV blocks / graph nodes / embeddings to fetch mid-kernel), a CPU round-trip per
  fetch is fatal. GPU-initiated I/O lets the GPU demand-page from SSD like it demand-pages
  from HBM. This is a natural fit for **sparse KV retrieval** and huge embedding tables.
- Interview framing: "This collapses the compute/storage boundary — the GPU becomes a
  first-class storage initiator, which is exactly what sparse/long-context KV access
  wants."

## 4. CXL (Compute Express Link) — memory pooling & tiering

CXL is a cache-coherent interconnect **over the PCIe physical layer**. Three protocols:
- **CXL.io** (PCIe-like config/IO), **CXL.cache** (device caches host memory coherently),
  **CXL.mem** (host accesses device-attached memory coherently, byte-addressable).

Use cases directly hitting JD R2 ("memory pooling"):
- **Type 3 memory expanders**: add DRAM capacity/bandwidth to a host as a **new NUMA
  node** over CXL → a **memory tier between DRAM and SSD** (~300 ns, 10s of TB).
- **Memory pooling (CXL 2.0)**: a shared pool of memory **disaggregated** across hosts via
  a CXL switch; allocate to whichever server needs it → fight stranded memory.
- **Memory sharing / fabric (CXL 3.0)**: multiple hosts coherently share memory; fabric
  topologies.

**For LLM/KV:** CXL memory is an ideal **KV offload tier** — byte-addressable (attend
almost in place, no block reload), far bigger than local DRAM, cheaper than HBM. Also
enables pooling GPU-server DRAM so KV can spill without touching SSD. The tiering
placement question (what KV goes to CXL vs SSD) is squarely this role's design work.
Tradeoff: CXL latency (~150–400 ns) > local DRAM; NUMA-aware placement + hot/cold
classification needed (kernel tiering: `NUMA balancing`, `DAMON`, `memory tiering`).

## 5. NVMe / ZNS / FDP / OCP (standards to track — R8)

- **NVMe** evolutions (KB 06): ZNS, FDP, CMB/PMR, NVMe-oF, computational storage.
- **OCP (Open Compute Project)**: hyperscaler-driven open hardware — server, storage
  (e.g. **OCP NVMe cloud SSD spec / Datacenter NVMe SSD**), NIC (OCP NIC 3.0), and
  **CXL/memory** working groups. Tracking OCP tells you where hyperscalers are steering
  SSD/CXL/DPU requirements. The JD explicitly wants you to "propose standards" — OCP and
  NVM Express and CXL Consortium are the venues.
- **Computational Storage (CSD)**: push compute (compression, search, dedup, even parts
  of attention) into the SSD/DPU to cut data movement.

## 6. How it all composes for AI storage (the end-state diagram)

```
        ┌────────────────────── GPU (HBM) ──────────────────────┐
        │   weights + hot KV                                      │
        └──▲───────────────▲───────────────────▲─────────────────┘
   GPUDirect RDMA   GPUDirect Storage    (GPU-Initiated Storage)
     (NIC→GPU)        (SSD→GPU)             (GPU→NVMe doorbell)
        │                 │                     │
   RDMA fabric        local NVMe            local/remote NVMe
   (KV transfer,     (KV tier, weights)    (demand-paged KV)
    NVMe-oF)              │
        │            CXL memory tier (byte-addressable KV offload / pooling)
   remote KV pool /       │
   object store       CPU DRAM
```

## 7. Interview-ready talking points

- "GPUDirect Storage DMAs the SSD straight into GPU HBM via PCIe P2P, skipping the host
  bounce buffer — that's what makes SSD-backed KV tiers and fast weight loading viable;
  cuFile is the API, and it works over NVMe-oF too."
- "GPU-Initiated Storage (BaM-style) lets the GPU itself issue NVMe I/O mid-kernel, so it
  can demand-page KV blocks or embeddings from SSD without a CPU round-trip — ideal for
  sparse long-context KV access."
- "CXL gives a byte-addressable memory tier between DRAM and SSD and enables memory
  pooling across hosts — a great KV offload tier because you can attend almost in place
  instead of reloading blocks; the design work is hot/cold placement across HBM/DRAM/CXL/
  SSD."
- "I'd track NVMe (ZNS/FDP), CXL Consortium, and OCP to steer SSD/CXL/DPU requirements and
  push proposals like read-optimized, predictable-latency KV SSDs and GPU-initiated I/O
  support."
