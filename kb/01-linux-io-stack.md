# 01 · The Linux I/O Stack, End to End

> Goal: be able to whiteboard the full path from `read()`/`write()` down to NAND/platter
> and back, and know where every latency and copy happens.

## 1. The layers (top to bottom)

```
Application
  │  read()/write()/pread()/io_uring_enter()/...   (syscall boundary)
VFS  (Virtual File System)  ── dentry cache, inode cache
  │
Page Cache  (buffered I/O)  ── or O_DIRECT bypasses this
  │
Filesystem  (ext4/xfs/btrfs/f2fs)  ── block allocation, journaling, extents
  │
Block layer:  bio → request → blk-mq (multi-queue)  ── I/O scheduler (mq-deadline/kyber/bfq/none)
  │
Block device driver (nvme, scsi/sd, virtio-blk)
  │
Hardware queues (NVMe SQ/CQ) → PCIe → SSD controller → FTL → NAND
```

## 2. Buffered vs Direct vs mmap

| Path | Page cache? | Copies | Use when |
|------|-------------|--------|----------|
| Buffered (`read`/`write`) | Yes | kernel↔user copy | general purpose, read-heavy reuse |
| `O_DIRECT` | No (bypasses) | DMA to user buffer (aligned) | DBs, want to manage own cache, avoid double-caching |
| `mmap` | Yes (demand paging) | none (page faults) | random access, shared read |
| `sendfile`/splice | Yes | zero-copy kernel→kernel | serving files to socket |

**Interview trap:** `O_DIRECT` requires alignment (buffer, offset, length aligned to
logical block / 512 or 4096). It is *not* the same as `O_SYNC`. `O_DIRECT` skips the
page cache; `O_SYNC` forces durability (data + metadata) before return. You often want
neither or both, deliberately.

## 3. The write path & durability

Buffered write returns after copying into the page cache (dirty pages). Durability is a
separate concern:

- **Dirty pages** are flushed by the `pdflush`/`writeback` (flusher) threads based on
  `vm.dirty_ratio`, `vm.dirty_background_ratio`, `vm.dirty_expire_centisecs`.
- `fsync(fd)` flushes a file's data + metadata; `fdatasync` skips non-essential
  metadata. `sync()` flushes everything.
- Filesystems add **journaling** (ext4 `data=ordered` default): metadata journaled,
  data written before metadata commit to avoid exposing garbage.
- Devices have **volatile write caches**; a `FLUSH`/FUA (Force Unit Access) command is
  what actually makes data power-safe. `fsync` triggers a device cache flush.

**The durability chain:** `app buffer → page cache → fs journal → block layer → device
write cache → NAND`. A crash anywhere loses in-flight data unless flushed.

## 4. bio, request, and blk-mq

- A **`bio`** is the fundamental unit: a set of segments (page, offset, len) for a
  contiguous device region. One logical I/O may split into multiple bios.
- bios are merged/assembled into **`request`s**.
- **blk-mq** (multi-queue block layer, default since ~4.x) replaced the single request
  queue with **per-CPU software queues** feeding a smaller number of **hardware
  queues**. This removed the single queue lock that killed scalability on NVMe (which
  can have thousands of queues). Essential for millions of IOPS.

```
per-CPU software queues ──► hardware dispatch queues ──► device HW queues (NVMe SQ/CQ)
```

## 5. I/O schedulers (blk-mq era)

| Scheduler | Idea | When |
|-----------|------|------|
| `none` | FIFO, no reordering | fast NVMe SSD (default for NVMe) |
| `mq-deadline` | deadlines to avoid starvation, light merging | SATA SSD, mixed |
| `kyber` | latency-target based, self-tuning | low-latency SSD |
| `bfq` | fairness / proportional (cgroup), good for desktop/HDD | HDD, interactive, QoS |

**Key point:** For a modern NVMe SSD you often want `none` — the device's own scheduling
+ deep queues beat kernel reordering, and the scheduler just adds CPU. For HDDs,
seek-optimizing/fair schedulers still matter. Set via
`echo none > /sys/block/nvme0n1/queue/scheduler`.

## 6. Where the latency & CPU goes (mental model)

For a 4KB random read from NVMe:
- Syscall + VFS + fs: ~1–3 µs CPU.
- Block layer + driver + doorbell: ~1–2 µs.
- Device (NVMe SSD): ~10–80 µs (media + controller).
- Interrupt / completion handling: ~1–3 µs (or polled: 0 but burns CPU).

So at low queue depth, **software overhead is a large fraction** for fast SSDs → this is
*why* io_uring, polling, and SPDK exist (see KB 02, 08, 09).

## 7. Observability toolbox

| Tool | What it shows |
|------|---------------|
| `iostat -x 1` | per-device IOPS, throughput, await (latency), %util, queue depth (aqu-sz) |
| `blktrace`/`blkparse`/`btt` | per-bio tracing: queue→dispatch→complete timings |
| `biolatency`/`biosnoop` (bcc/bpftrace) | latency histograms, per-process bio |
| `perf` | CPU profiling, where kernel time goes |
| `/proc/diskstats`, `/sys/block/*/queue/*` | counters, queue config |
| `fio` | synthetic workload generation (KB 09) |

**`iostat` reading tips:** `%util` is misleading on SSDs (can be 100% while far from
saturated because it assumes one "server"); trust `aqu-sz` (avg queue depth) and
`r_await`/`w_await` (latency) instead. Throughput = IOPS × block size.

## 8. Filesystems in one breath

- **ext4**: mature, journaling, extents, good default.
- **xfs**: excellent large-file & parallel throughput, delayed allocation, great for big
  streaming (log/AI dataset) workloads.
- **btrfs/zfs**: CoW, snapshots, checksums, compression; write amplification tradeoffs.
- **f2fs**: log-structured, designed for flash (append-friendly, GC-aware).

For AI dataset serving, **xfs on NVMe** is a common, boring, correct choice; large
sequential reads with big readahead.

## 9. Interview-ready talking points

- "Draw the stack: VFS → page cache → fs → blk-mq → driver → NVMe queues → FTL → NAND.
  Every layer either adds a copy, adds latency, or adds a chance to lose data."
- "blk-mq exists because a single request queue lock can't feed a million-IOPS NVMe
  device; per-CPU software queues remove the lock."
- "On NVMe I set the scheduler to `none` — the software scheduler just burns CPU when
  the device is already good at internal ordering with deep queues."
- "Durability is a chain; `write()` returning means 'in page cache', not 'on media'.
  Only `fsync` + a device flush/FUA makes it power-safe."
- "For fast SSDs at low QD, software overhead dominates the media latency — that's the
  entire justification for io_uring and kernel-bypass."
