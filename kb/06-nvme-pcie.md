# 06 · NVMe & PCIe

> The transport that makes modern SSDs fast, and the bus everything (GPU, SSD, NIC, CXL)
> shares. JD Q10/Q13 and R8 (track NVMe/OCP standards).

## 1. Why NVMe replaced AHCI/SATA

AHCI/SATA was designed for one slow spinning disk: **a single command queue, depth 32,
one interrupt**. NAND flash is parallel and fast, so the interface became the bottleneck.
**NVMe** is a protocol designed for flash over PCIe:

- **Up to 64K queues, each up to 64K deep** → massive parallelism, scales per-CPU.
- **Paired Submission Queue (SQ) / Completion Queue (CQ)** in host memory; the host rings
  a **doorbell** register to notify the controller.
- **MSI-X**: per-queue interrupts → each CPU handles its own completions, no shared lock.
- Streamlined command set, low per-command overhead, **polling** support.

This maps perfectly onto **blk-mq** (per-CPU software queue → NVMe HW queue) and io_uring.

## 2. NVMe command flow

```
1. Host builds a command in a Submission Queue (SQ) entry.
2. Host writes the SQ tail doorbell (MMIO) → controller knows there's work.
3. Controller fetches command via DMA, executes (reads/writes NAND).
4. Controller DMAs data to/from host, posts a completion to the CQ.
5. Controller raises MSI-X interrupt (or host polls the CQ).
6. Host processes completion, writes CQ head doorbell.
```

- **Admin queue** (create/delete queues, identify, firmware) vs **I/O queues**.
- Data described by **PRP** (Physical Region Pages) or **SGL** (Scatter-Gather Lists).
- **Namespaces**: an NVMe controller exposes one or more namespaces (like LUNs);
  `nvme0n1`. Namespace management allows partitioning a drive.

## 3. NVMe features relevant to AI storage

- **Multiple namespaces + NS management**: isolate KV cache vs dataset on one device.
- **ZNS (Zoned Namespaces)**: append-only zones → host controls placement, WA≈1.
- **FDP (Flexible Data Placement)**: hint data lifetime/streams; reduce WA without ZNS's
  strict append rules.
- **NVMe-oF (over Fabrics)**: NVMe over RDMA (RoCE/iWARP/IB), TCP, or FC → disaggregated
  storage with near-local latency. Basis of **storage disaggregation** (JD B4) and
  remote KV cache pools.
- **CMB (Controller Memory Buffer)** / **PMR**: device-side memory exposed over PCIe BAR;
  enables peer-to-peer DMA (e.g., NIC or GPU DMAs straight to SSD CMB) — building block
  for **GPUDirect Storage** (KB 14).
- **Directives/streams**, **atomic writes**, **DSM/TRIM (deallocate)**.

## 4. PCIe essentials

- **Lanes & generations**: bandwidth per lane roughly doubles each gen.
  | Gen | per-lane | x4 (NVMe SSD) | x16 (GPU) |
  |-----|----------|---------------|-----------|
  | Gen3 | ~1 GB/s | ~4 GB/s | ~16 GB/s |
  | Gen4 | ~2 GB/s | ~8 GB/s | ~32 GB/s |
  | Gen5 | ~4 GB/s | ~14–16 GB/s | ~64 GB/s |
  | Gen6 | ~8 GB/s | ~28 GB/s | ~128 GB/s |
  (Approximate usable; encoding/overhead applies.)
- **Topology**: CPU **root complex** → PCIe switches → endpoints (GPU, NVMe, NIC). Each
  CPU socket has its own root complex → **NUMA/PCIe affinity** matters: a GPU and the SSD
  feeding it should hang off the same socket/switch to avoid crossing the inter-socket
  link (UPI/Infinity Fabric).
- **P2P DMA (peer-to-peer)**: endpoints DMA directly to each other via a PCIe switch,
  **bypassing CPU DRAM** — the mechanism behind GPUDirect (GPU↔NIC, GPU↔NVMe).
- **BAR / MMIO**, **TLPs**, ** atomics**, **ACS** (affects P2P routing / security).
- **IOMMU (VT-d/AMD-Vi)**: DMA address translation & isolation; SR-IOV for device
  virtualization. IOMMU can add latency; sometimes disabled/passthrough for perf.

## 5. Bandwidth budgeting (a killer whiteboard skill)

Example: "Can one PCIe Gen5 x16 GPU be fed KV cache from local NVMe?"
- GPU link: ~64 GB/s (Gen5 x16).
- One Gen5 x4 NVMe: ~14 GB/s → need ~4–5 drives (or RAID0) to saturate the GPU link.
- If KV blocks are, say, 128 KB and you need X GB/s, IOPS = X/128KB → check it's within
  drive IOPS and QD budget.
Being able to do this arithmetic live is exactly the "推导产品核心需求" (derive core product
requirements) the JD wants.

## 6. Observability & tooling

- `nvme-cli`: `nvme list`, `nvme id-ctrl`, `nvme id-ns`, `nvme smart-log` (wear, temp,
  media errors), `nvme error-log`, `nvme zns ...`, `nvme fdp ...`.
- `lspci -vvv`, `lspci -tv` (topology), `setpci` (link speed/width), check `LnkSta`.
- `nvme get-feature`, telemetry log for controller diagnostics.
- `/sys/class/nvme/`, `/sys/block/nvme0n1/queue/`.

## 7. Interview-ready talking points

- "NVMe beats AHCI by giving each CPU its own deep SQ/CQ pair with MSI-X, so a
  million-IOPS device isn't bottlenecked on one queue lock — it pairs naturally with
  blk-mq and io_uring."
- "The command flow is doorbell → DMA fetch → execute → DMA data → completion +
  interrupt (or poll); polling trades a burned core for the lowest latency."
- "ZNS/FDP push placement to the host to kill write amplification; CMB and P2P DMA let a
  NIC or GPU talk to the SSD directly — that's the foundation of GPUDirect Storage and
  disaggregation."
- "PCIe/NUMA affinity is real money: keep the GPU and its feeding SSDs/NIC on the same
  root complex, and budget bandwidth — a Gen5 x16 GPU needs ~4–5 Gen5 x4 NVMe drives to
  saturate."
