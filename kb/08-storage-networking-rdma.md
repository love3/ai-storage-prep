# 08 · Storage Networking: RDMA, TCP, Kernel Bypass

> JD R3 (customize/tune RDMA, TCP/UDP for low latency & high throughput) and bonus B3
> (DPDK/SPDK) & B4 (DPU offload). Networking is now on the LLM critical path (KV transfer
> in PD disaggregation, NVMe-oF).

## 1. Why the network matters for AI storage

- **PD disaggregation** (KB 13): prefill and decode run on different GPUs/nodes → the KV
  cache must be shipped between them fast (GBs, low latency).
- **Distributed / disaggregated storage** (NVMe-oF): remote SSD at near-local latency.
- **Collectives** (NCCL) for tensor/pipeline parallelism ride the same fabric.
- Latency budget: a decode step is ~10–50 ms; a KV transfer that adds ms matters.

## 2. The TCP kernel overhead problem

Classic sockets: per-packet interrupts, kernel→user copies, protocol processing on the
CPU, context switches, and the socket lock. At 100–400 GbE this **saturates CPU before
the wire**. Mitigations before going exotic:

- **Interrupt coalescing**, **NAPI** (poll under load), **RSS** (spread flows across
  queues/cores), **GRO/GSO/TSO** (offload segmentation), **jumbo frames**.
- **Zero-copy**: `sendfile`, `splice`, `MSG_ZEROCOPY`, `SO_ZEROCOPY`.
- **Busy polling** (`SO_BUSY_POLL`), **XDP** (eBPF at the driver for fast
  filtering/redirect).
- Tune socket buffers (`net.core.rmem/wmem`), congestion control (**BBR** vs CUBIC),
  NIC ring sizes, IRQ affinity, RFS/aRFS.

## 3. RDMA — Remote Direct Memory Access

RDMA lets a NIC read/write **remote memory directly**, bypassing the remote CPU and
kernel: **zero-copy, kernel-bypass, one-sided ops**. This is the low-latency,
high-throughput fabric for HPC/AI.

**Transports:**
- **InfiniBand (IB)**: purpose-built lossless fabric + RDMA native.
- **RoCE v2** (RDMA over Converged Ethernet): RDMA over UDP/IP on Ethernet; needs a
  (near-)**lossless** network — **PFC** (Priority Flow Control) + **ECN/DCQCN**
  congestion control. Most common in AI datacenters.
- **iWARP**: RDMA over TCP (handles loss itself, less config, higher latency).

**Verbs / building blocks:**
- **QP (Queue Pair)**: send queue + receive queue per connection.
- **CQ (Completion Queue)**: completions reaped like io_uring (same mental model!).
- **MR (Memory Region)**: pinned, registered memory the NIC may DMA (with rkey/lkey).
- **Operations**:
  - **SEND/RECV** (two-sided: receiver must post a buffer).
  - **RDMA WRITE / READ** (one-sided: initiator specifies remote address + rkey, remote
    CPU uninvolved) — the killer feature for pushing/pulling KV cache.
  - **Atomics** (fetch-add, cmp-swap) for remote coordination.
- **Polling vs event** completions; **inline** small payloads.

**Why fast:** no per-packet CPU, no copies, no context switch, transport offloaded to
NIC hardware. Latency ~1–2 µs; bandwidth line-rate (100–400+ GbE / NDR IB).

**Gotchas:** memory registration/pinning cost (register once, reuse — like io_uring fixed
buffers); RoCE requires careful PFC/ECN tuning or you get congestion collapse / head-of-
line blocking; scaling many QPs pressures NIC cache.

## 4. NVMe-oF (NVMe over Fabrics)

Carries NVMe commands over a fabric so remote SSDs behave like local NVMe:
- **NVMe/RDMA** (RoCE/IB/iWARP): lowest latency; command capsules + RDMA for data.
- **NVMe/TCP**: no special NIC, easy to deploy, higher latency/CPU (offload helps).
- **NVMe/FC**: Fibre Channel SANs.

Enables **storage disaggregation** (JD B4): compute nodes with little local storage, a
pool of NVMe reached over the fabric at ~near-local latency. Foundation for shared/remote
KV cache tiers.

## 5. Kernel bypass: DPDK & SPDK

- **DPDK** (Data Plane Development Kit): userspace **networking** — poll-mode drivers,
  hugepages, no kernel network stack, no interrupts. For packet processing at line rate
  (routers, load balancers, custom protocols).
- **SPDK** (Storage Performance Development Kit): userspace **storage** — poll-mode NVMe
  driver, userspace block stack, NVMe-oF target/initiator, vhost, all lockless
  thread-per-core with its own reactor. Removes syscalls, interrupts, and copies from the
  storage path → millions of IOPS per core.

**Cost/benefit:** kernel bypass gives you the CPU back and slashes latency, but you lose
the kernel's drivers, security, and features — you own everything. Use when the kernel
stack is the proven bottleneck.

## 6. DPU / SmartNIC offload (JD B4)

**DPUs** (NVIDIA BlueField, Intel IPU) put Arm cores + accelerators + NIC on one card to
**offload** networking, storage (NVMe-oF target, virtualization), and security from the
host CPU. Trends: offload the entire storage/network data path off the host so host CPUs
serve applications; "infrastructure on the DPU." Relevant to disaggregated storage,
multi-tenant isolation, and freeing GPU-server CPUs.

## 7. Putting it together for KV transfer (PD disaggregation)

To move KV cache from a prefill node to a decode node:
1. KV blocks live in pinned/registered GPU or host memory (MR).
2. Use **RDMA WRITE/READ** (or NCCL/NIXL/UCX under the hood) to move blocks one-sided.
3. **Overlap** the transfer with compute (start sending layer L's KV while computing L+1).
4. Optionally **GPUDirect RDMA**: NIC DMAs straight to/from **GPU** memory (P2P over
   PCIe), skipping host DRAM entirely (KB 14).
Modern stacks: **NIXL** (NVIDIA inference transfer lib), **UCX**, **Mooncake transfer
engine**, **NCCL** for collectives.

## 8. Tooling

- `ib_write_bw`/`ib_read_bw`/`ib_send_lat` (perftest), `rdma`/`ibv_devinfo`, `perfquery`.
- `ethtool -S`, `ss -i`, `nstat`, `netperf`/`iperf3`, `tcpdump`, `bpftrace` net probes.
- NVMe-oF: `nvme connect`/`discover`; SPDK `nvmf_tgt`.

## 9. Interview-ready talking points

- "RDMA is kernel-bypass, zero-copy, and offloaded to the NIC; one-sided WRITE/READ let
  the initiator touch remote memory without the remote CPU — ideal for shipping KV cache
  in PD disaggregation."
- "RoCEv2 needs a lossless fabric — PFC + ECN/DCQCN — or you get congestion collapse;
  iWARP rides TCP so it tolerates loss but is slower."
- "Its completion model (QP + CQ + registered MR) is the same batched, poll-or-event,
  pre-pinned-buffer idea as io_uring."
- "NVMe-oF disaggregates storage at near-local latency; SPDK/DPDK take the kernel out of
  the storage/network path for millions of IOPS per core; DPUs offload the whole
  infrastructure data path off the host."
- "For KV transfer I overlap RDMA moves with compute and, where possible, use GPUDirect
  RDMA to DMA straight into GPU memory and skip host DRAM."
