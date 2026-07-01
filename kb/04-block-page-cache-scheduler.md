# 04 · Block Devices, Page Cache, I/O Scheduling

> JD Q4: "block device drivers, page cache, I/O scheduling". This note goes deeper on
> caching and scheduling than KB 01.

## 1. Page cache internals

The page cache is unified with the VM: file data is cached in **pages** indexed by
`(inode, offset)` in an `address_space` / radix-tree (xarray).

- **Read**: `read()` → look up page; hit → copy out; miss → allocate page, issue readahead,
  block until filled, copy out.
- **Write (buffered)**: copy into page, mark **dirty**, return. Writeback later.
- **Reclaim**: under memory pressure, the LRU-ish lists (active/inactive) evict clean
  pages instantly and write back dirty pages first. Controlled by `vm.swappiness`,
  watermarks (`min/low/high`), and the `kswapd` reclaimer.

### Readahead
Sequential detection triggers **readahead**: the kernel prefetches ahead of the read
position, growing the window while the pattern stays sequential and shrinking on random
access. Tunables: `/sys/block/*/queue/read_ahead_kb`, `posix_fadvise(SEQUENTIAL|RANDOM|
WILLNEED|DONTNEED)`, `madvise`. Huge for streaming AI datasets; harmful for pure random.

### Double caching problem
With buffered I/O, a database that also caches pages wastes RAM caching twice and burns
CPU copying. Hence DBs use `O_DIRECT` + their own buffer pool. Same logic can apply to a
KV-cache store that manages its own memory.

### Writeback tuning
- `vm.dirty_background_ratio` (%): start async flush.
- `vm.dirty_ratio` (%): throttle/block writers (synchronous) — a latency cliff.
- `vm.dirty_expire_centisecs`: age before forced flush.
Big `dirty_ratio` = burstier, risk of huge stalls; small = smoother but more overhead.

## 2. Block device model

- **Logical block size** (usually 512e/4Kn) vs **physical block size** (4K). Misaligned
  4K writes on a 4Kn device cause read-modify-write.
- `/sys/block/<dev>/queue/`: `logical_block_size`, `physical_block_size`,
  `max_sectors_kb`, `nr_requests`, `rotational` (1=HDD, 0=SSD), `nomerges`, `scheduler`.
- **Merging**: adjacent bios merge into one request (front/back merge) to reduce op
  count. `nomerges` disables it (useful to measure raw device).
- **Multipath / device-mapper**: `dm-*` targets (linear, crypt, thin, cache, raid) stack
  virtual block devices. `dm-cache`/`bcache` = SSD cache in front of HDD (a tiering
  primitive relevant to KV tiering discussions).

## 3. blk-mq recap (see KB 01) + tags

- Per-CPU **software queues** → **hardware queues** → device.
- Each in-flight request needs a **tag** (`nr_requests` / device queue depth bounds it).
  Tag exhaustion = the queue is full → backpressure. NVMe supports many deep queues, so
  tags rarely bottleneck; SATA (QD=32) does.

## 4. I/O schedulers — deeper

| Scheduler | Mechanism | Strength | Weakness |
|-----------|-----------|----------|----------|
| `none` | FIFO + merge | lowest CPU, best for NVMe | no fairness/QoS |
| `mq-deadline` | read/write FIFOs with expiry + sorted dispatch | bounds worst-case latency, prevents write starvation | modest reordering |
| `kyber` | measures latency, throttles to hit read/write latency targets | self-tuning low latency | needs tuning of targets |
| `bfq` | budget fair queueing, per-cgroup weights | fairness, interactivity, proportional QoS | CPU cost, less throughput at extreme IOPS |

**Choosing:**
- NVMe, throughput/latency king, trust device → `none`.
- SATA SSD/mixed, avoid write starving reads → `mq-deadline`.
- Need proportional I/O between tenants/cgroups → `bfq` (or `io.latency`/`io.max` in
  cgroup v2 blkio).

## 5. cgroup v2 I/O control (QoS — relevant to multi-tenant clusters)

- `io.max`: hard IOPS/bandwidth caps per device per cgroup.
- `io.latency`: latency target; throttles others to protect a workload.
- `io.weight` (with bfq): proportional sharing.
- `io.cost` model estimates device capacity.

This is how you enforce **QoS** (a JD keyword) between, say, KV-cache traffic and dataset
ingestion on shared NVMe.

## 6. Memory management crossovers

- **NUMA**: place buffers and the issuing thread on the node near the device (PCIe root
  complex affinity). Cross-node DMA and cache misses hurt. `numactl`, `/proc/*/numa_maps`,
  `lstopo`.
- **Huge pages**: reduce TLB misses for large mappings (mmap'd datasets, GPU pinned
  buffers). THP can cause latency jitter; often disabled for latency-sensitive stores.
- **Memory pooling / CXL** (JD R2): CXL lets you attach far memory as a NUMA node;
  scheduling KV cache into CXL memory is a "memory pooling" use case (KB 14).

## 7. Observing cache & scheduler behavior

- `free -m`, `/proc/meminfo` (`Dirty`, `Writeback`, `Cached`).
- `vmstat 1` (bi/bo blocks in/out, si/so swap).
- `cachestat`/`cachetop` (bcc) — page cache hit ratio.
- `fincore`/`vmtouch` — what of a file is resident.
- `blktrace` + `btt` — where time goes per request (Q2D queue→dispatch, D2C device time).

## 8. Interview-ready talking points

- "Page cache is unified with the VM; reads populate it with readahead, writes dirty
  pages flushed by writeback under `dirty_ratio` control — and `dirty_ratio` is a
  latency cliff when writers get throttled."
- "Databases and custom caches use O_DIRECT to avoid double-caching and page-cache CPU,
  managing their own buffer pool — same reasoning applies to a KV-cache offload engine."
- "For NVMe I use `none`; for SATA `mq-deadline` to stop writes starving reads; for
  multi-tenant QoS I reach for bfq or cgroup v2 `io.max`/`io.latency`."
- "Alignment matters: unaligned 4K writes on a 4Kn device force read-modify-write and
  tank performance."
- "NUMA and device affinity matter at scale — place the buffer and issuing core near the
  PCIe root complex of the device."
