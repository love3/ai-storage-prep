# 00 · Role & Skills Map

> Decompose the JD, map it to a concrete skill matrix, and give yourself a study plan.

## 1. What this role actually is

This is a **systems + AI infrastructure** role. You are expected to be a *storage
systems expert* who understands **why LLM inference is now the dominant storage
workload driver**. The unifying thesis:

> Modern LLM serving is bottlenecked less by FLOPs and more by **memory capacity,
> memory bandwidth, and data movement**. KV cache is the new "hot data set". Storage,
> networking, and memory hierarchies (HBM → DRAM → CXL → NVMe SSD) are now on the
> critical path of token latency. This role designs that hierarchy.

Two pillars:

- **Pillar A — Low-level storage systems**: Linux I/O stack, async I/O (io_uring),
  block/NVMe, SSD internals, distributed storage (Ceph), RDMA, kernel bypass (SPDK),
  performance engineering.
- **Pillar B — LLM inference internals**: Transformer inference, KV cache lifecycle,
  vLLM/SGLang/TensorRT-LLM, PD (prefill/decode) disaggregation, long context,
  GPU Direct Storage (GDS), CXL.

The magic word connecting them is **KV cache offload / tiering**: taking KV cache that
doesn't fit in GPU HBM and pushing it to DRAM → CXL → NVMe SSD, and reading it back
fast enough to keep GPUs busy. This is where "storage" meets "AI".

## 2. JD → skill matrix

| # | JD responsibility / requirement | Core skills | KB |
|---|---|---|---|
| R1 | Distributed storage (file/object/block + consistency) | Ceph, RADOS/CRUSH, Paxos/Raft, erasure coding | 07 |
| R2 | Scheduling, memory pooling | I/O scheduling, CXL memory pooling, NUMA | 04, 14 |
| R3 | Storage network stack (RDMA/TCP/UDP) tuning | RDMA verbs, RoCE, NVMe-oF, zero-copy | 08 |
| R4 | LLM deployment on GPU/AI-PC/edge, perf bottleneck analysis | profiling, roofline, memory analysis | 10, 15 |
| R5 | Reason about compute/VRAM/DRAM/storage needs of inference frameworks | vLLM, SGLang, llama.cpp, TensorRT-LLM | 11, 12 |
| R6 | KV cache gen/access/reuse/offload/readback + tiering, PD split, long ctx, ultra SSD | KV cache mgmt, prefix caching, tiering | 11, 13 |
| R7 | New-product tech pre-research, requirement definition | architecture, tradeoff analysis | all |
| R8 | Track GDS, GPU-Initiated Storage, CXL, NVMe, OCP; standards | spec literacy | 06, 14 |
| Q1 | Linux, problem localization, perf analysis | perf, ftrace, bpftrace, blktrace | 01, 09 |
| Q2 | Python / C / C++ / Shell | prototyping, data analysis | demos |
| Q3 | Async programming (AIO, io_uring), coroutines | io_uring, epoll, coroutine internals | 02, 03 |
| Q4 | Storage stack: block drivers, page cache, I/O scheduling | 01, 04 |
| Q5 | Kernel, filesystems, multithread/concurrency | 01, 03, 04 |
| Q6 | Perf tuning at cluster scale | 09 |
| Q7 | Transformer, inference flow, attention, KV cache, prefill/decode, batching | 10 |
| Q8 | ≥1 inference framework deploy + tune | 12 |
| Q9 | (plus) OSS model deploy/quant/opt/long-ctx | 13, 15 |
| Q10 | (plus) SSD/NAND/NVMe/PCIe/IO stack/FS/block | 05, 06 |
| Q11 | (plus) fio, SPDK, io_uring, libaio, GDS | 02, 09, 14 |
| Q12 | (plus) IOPS/BW/latency/QoS/WA/GC/FTL/SLC/QLC | 05, 09 |
| Q13 | HDD/SSD/NVMe characteristics, I/O perf analysis | 05, 09 |
| B1 | (bonus) Ceph core module dev | 07 |
| B2 | (bonus) coroutine libs (libco/Boost.Coroutine) | 03 |
| B3 | (bonus) kernel bypass (DPDK/SPDK) | 08, 09 |
| B4 | (bonus) DPU offload, storage-compute disaggregation | 08, 14 |

## 3. Skill self-assessment matrix

Rate yourself 1–5 and target the gaps. Print this and fill it in.

| Skill cluster | Topics | Your level (1-5) | Priority |
|---|---|---|---|
| Linux I/O internals | page cache, bio, blk-mq, schedulers | | High |
| Async I/O | io_uring, libaio, epoll, coroutines | | High |
| SSD/NVMe HW | FTL, GC, WA, QLC, NVMe queues, PCIe | | High |
| Distributed storage | Ceph, CRUSH, replication, EC, consistency | | Med |
| Storage networking | RDMA, RoCE, NVMe-oF, SPDK, DPDK | | Med |
| Perf engineering | fio, perf, bpftrace, roofline | | High |
| LLM inference basics | attention, prefill/decode, batching | | High |
| KV cache | PagedAttention, prefix cache, offload/tiering | | **Critical** |
| Inference frameworks | vLLM, SGLang, llama.cpp, TRT-LLM | | High |
| PD disaggregation | prefill/decode split, KV transfer | | **Critical** |
| GDS / CXL | GPUDirect Storage, CXL memory pooling | | High |
| Quantization | INT8/FP8/INT4, GPTQ/AWQ, KV quant | | Med |

## 4. The "one diagram" you must be able to draw

The **memory/storage hierarchy for LLM inference**, with capacity, bandwidth, and
latency at each tier, and where KV cache lives:

```
                 capacity      bandwidth        latency     $/GB
GPU HBM (HBM3e)   ~80-192 GB    ~3-8 TB/s        ~100 ns     $$$$$   <- weights + active KV
  │  (NVLink / PCIe5 x16 ~64 GB/s)
CPU DRAM (DDR5)   ~1-4 TB       ~200-500 GB/s    ~100 ns     $$$     <- KV offload tier 1
  │  (CXL 2.0/3.0)
CXL memory        ~10s TB       ~50-100 GB/s     ~300 ns     $$      <- memory pooling / KV tier
  │  (PCIe5 x4 NVMe ~14 GB/s per drive)
NVMe SSD          ~10s-100s TB  ~1-14 GB/s/drive ~10-100 µs  $       <- KV tier 2 / prefix cache
  │  (network: RDMA 400G ~50 GB/s, NVMe-oF)
Remote / object   PB            network-bound    ms          ¢       <- cold cache, model store
```

**Talking point:** "The whole game is keeping the GPU's math units fed. Every tier
down is ~10–100× cheaper per GB but ~10–100× slower. KV cache offload and PD
disaggregation are about *hiding* that latency with prefetch, async I/O, and overlap so
that decode never stalls on a cache miss."

## 5. Two-week study plan

**Week 1 — storage foundations (your presumed strength, sharpen for interview):**
- Day 1: KB 01 (Linux I/O stack) + draw the full path from `read()` to platter/NAND.
- Day 2: KB 02 + 03 (async I/O + coroutines); run demo 2 (async-io-bench).
- Day 3: KB 04 (block/page cache/scheduler) + `blktrace`/`fio` hands-on.
- Day 4: KB 05 + 06 (SSD/NAND/FTL, NVMe/PCIe); memorize WA/GC/QLC talking points.
- Day 5: KB 07 (Ceph) + 08 (RDMA/SPDK).
- Day 6: KB 09 (perf methodology); run fio experiments, learn USE method.
- Day 7: Review; do storage mock interview.

**Week 2 — AI inference (the differentiator):**
- Day 8: KB 10 (transformer inference) — compute vs memory bound, prefill vs decode.
- Day 9: KB 11 (KV cache) — PagedAttention, prefix caching, offload; run demo 1.
- Day 10: KB 12 (frameworks); deploy a model with Ollama/llama.cpp; run demo 3.
- Day 11: KB 13 (PD disaggregation, long context) — this is the headline topic.
- Day 12: KB 14 (GDS, CXL) + KB 15 (quantization).
- Day 13: Build/rehearse the "storage hierarchy for inference" whiteboard talk.
- Day 14: Full mock interview (system design + behavioral).

## 6. Positioning / narrative for the interview

Craft a 60-second pitch that bridges both pillars. Template:

> "My background is in [storage systems / performance engineering]. What excites me
> about this role is that LLM inference has turned storage and memory hierarchy into
> the primary scaling bottleneck. KV cache is essentially a new caching problem with a
> brutal latency budget, and it maps directly onto everything I know about page cache,
> async I/O, NVMe, and tiering. I've been going deep on vLLM/SGLang internals and
> PagedAttention, and I built a KV-cache-offload simulator and an io_uring benchmark to
> reason quantitatively about the prefetch/overlap budget. I want to help design the
> HBM→DRAM→CXL→NVMe path that keeps GPUs saturated."

Keep this handy — it frames every other answer.
