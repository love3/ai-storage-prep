# 05 · SSD / NAND / FTL Internals

> JD "plus" items Q10–Q13 hinge on this: WA, GC, FTL, SLC cache, QLC, IOPS/BW/latency/QoS.
> The AI angle: "ultra-high-performance SSD" (超高性能SSD) as a KV cache tier.

## 1. NAND flash basics

- **Cell types**: SLC (1 bit/cell), MLC (2), TLC (3), QLC (4), PLC (5, emerging). More
  bits/cell → cheaper $/GB but **slower, less endurance, higher error rates**.
- **Hierarchy**: cell → **page** (read/program unit, e.g. 16KB) → **block** (erase unit,
  e.g. hundreds of pages, MBs) → plane → die → package.
- **The fundamental asymmetry**:
  - **Read**: fast, page granularity (~10–100 µs).
  - **Program (write)**: page granularity, slower (~100s µs–ms for QLC).
  - **Erase**: **block granularity only**, slow (~ms). *You cannot overwrite a page in
    place — you must erase the whole block first.*

This erase-before-write + block-erase asymmetry is the root cause of **everything**: FTL,
GC, and write amplification.

## 2. Endurance & retention

- **P/E cycles** (program/erase endurance): SLC ~50–100k, MLC ~3–10k, TLC ~1–3k,
  QLC ~100s–1k. Cells wear out.
- **Retention** degrades with wear and heat; ECC (BCH → LDPC) corrects errors; read
  retry / read-level shifting recovers marginal cells.
- **DWPD** (drive writes per day) and **TBW** (terabytes written) are the endurance specs
  you quote.

## 3. The FTL (Flash Translation Layer)

The SSD controller's firmware that hides NAND's quirks and presents a normal LBA block
device. Responsibilities:

- **Logical→physical mapping (L2P)**: maps host LBAs to physical NAND pages. Page-level
  mapping needs a big table (~1 GB DRAM per 1 TB at 4KB granularity → the "1GB DRAM per
  TB" rule of thumb). DRAM-less SSDs use **HMB** (Host Memory Buffer) over PCIe or
  coarser mapping (slower random).
- **Out-of-place writes**: writes go to a fresh page; old page marked invalid; L2P
  updated. This is why an "overwrite" doesn't erase in place.
- **Garbage collection (GC)**: reclaims blocks with invalid pages by copying still-valid
  pages elsewhere, then erasing the block. Costs bandwidth/endurance → **write
  amplification**.
- **Wear leveling**: spreads P/E cycles across blocks so they wear evenly.
- **Bad block management**, **ECC**, **read disturb / program disturb** handling.

## 4. Write Amplification (WA) — a must-know

**WA = (bytes actually written to NAND) / (bytes written by host).**

Sources: GC copying valid pages, metadata, RMW on misaligned writes, padding partial
pages. WA > 1 always for random writes; can be 3–10× on a full drive with small random
writes. Consequences: less usable write bandwidth, faster wear.

**Reducing WA:**
- **Over-provisioning (OP)**: reserve spare capacity → GC has more room → fewer valid-page
  copies per erase → lower WA. Enterprise SSDs OP 7–28%+.
- **TRIM/`discard`**: tells SSD which LBAs are free so GC doesn't copy dead data. `fstrim`,
  mount `discard`, or NVMe deallocate.
- **Sequential / append-only** write patterns (log-structured, f2fs, RocksDB) → whole
  blocks invalidated together → near-1 WA.
- **Aligned, large writes**; avoid tiny random overwrites.
- **Zoned Namespaces (ZNS)** / **FDP (Flexible Data Placement)**: host groups data by
  lifetime so the SSD erases whole zones together → WA≈1, less OP needed. Very relevant
  to purpose-built KV-cache SSDs.

## 5. SLC cache (the "fast then slow" behavior)

TLC/QLC drives run part of the NAND in **SLC mode** (1 bit/cell) as a fast write buffer.
Bursts hit SLC cache (fast); once it fills, writes fall back to native TLC/QLC (slow) and
the drive also has to fold SLC→TLC in the background. This is why consumer SSD write
throughput **collapses after sustained writes** ("the cliff"). For benchmarking, you must
**precondition** (fill + steady-state) to measure real sustained performance, not the SLC
burst (see KB 09).

## 6. QLC — the AI storage angle

QLC: cheap, dense, decent **read** performance, poor write endurance/latency. That
read-heavy, write-once profile is a good match for **read-mostly KV cache / prefix cache
tiers** and model weight storage. Strategy: write sequentially/append (low WA), read
randomly at high QD. "Ultra-high-performance SSD" for AI often means high-read-bandwidth,
high-QD-optimized, possibly ZNS/FDP QLC or fast TLC with big DRAM.

## 7. Performance metrics vocabulary

- **IOPS**: I/O operations per second (depends on block size + pattern + QD).
- **Bandwidth/throughput**: bytes/s (≈ IOPS × block size for large I/O).
- **Latency**: per-op time; report **percentiles (p50/p99/p99.9)** not just average — the
  tail is what hurts (QoS). LLM decode is latency-sensitive → p99 matters.
- **Queue depth (QD)**: outstanding I/Os. IOPS rises with QD until saturation; latency
  rises too (Little's Law: QD = IOPS × latency).
- **QoS**: bounding tail latency / isolating tenants. SSDs jitter due to GC → enterprise
  drives offer more consistent latency, sometimes "predictable latency" modes.
- **Read/write asymmetry & mixed workloads**: writes trigger GC that hurts read latency →
  70/30 mixed is a realistic torture test.

**Little's Law (say it):** average outstanding = arrival rate × latency. To hit 1M IOPS
at 100 µs latency you need QD≈100. This justifies async I/O + high QD.

## 8. HDD vs SSD vs NVMe (know the contrasts)

| | HDD | SATA SSD | NVMe SSD |
|--|-----|----------|----------|
| Random 4K latency | ~5–10 ms (seek+rotate) | ~100 µs | ~10–80 µs |
| IOPS | ~100–200 | ~50–100k | ~500k–several M |
| Bandwidth | ~200 MB/s | ~500 MB/s | ~3–14 GB/s (PCIe4/5) |
| Interface QD | 1 (per actuator) | 32 (AHCI) | 64k queues × 64k depth |
| Sweet spot | cold/sequential, $/GB | general | hot data, KV cache tier |

HDDs love **sequential**; random is catastrophic (mechanical seek). SSDs kill random but
suffer GC jitter and the SLC cliff.

## 9. Interview-ready talking points

- "NAND can't overwrite in place — program is page-granular, erase is block-granular and
  slow. That asymmetry forces out-of-place writes, an FTL with an L2P map, GC, and wear
  leveling."
- "Write amplification is GC copying valid pages; fight it with over-provisioning, TRIM,
  sequential/append writes, and ZNS/FDP for lifetime-grouped placement."
- "Benchmarks lie unless you precondition past the SLC cache to steady state; the SLC
  cliff is why consumer drives look fast then tank."
- "QLC is cheap, read-good, write-poor — perfect for read-mostly KV/prefix cache and
  model weights if you write append-only and read at high QD."
- "Report p99/p99.9, not averages; GC-induced tail latency is the real QoS enemy, and
  Little's Law tells you the QD you need for target IOPS at a given latency."
