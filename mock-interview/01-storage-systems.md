# Mock Interview · Storage Systems & Linux Internals

> Model answers are concise talking-point form. Expand naturally when speaking.

---

### Q1. Walk me through what happens when an app calls `read()` on a file.

**A.** `read()` traps into the kernel → **VFS** dispatches to the filesystem. For buffered
I/O the kernel checks the **page cache** (indexed by inode+offset); on a hit it copies the
page to the user buffer. On a miss it allocates a page, issues readahead, and submits a
**bio** to the **block layer**. bios are merged into requests, scheduled by **blk-mq**
(per-CPU software queues → hardware queues), handed to the **NVMe driver**, which rings a
doorbell; the SSD controller DMAs data back and posts a completion (interrupt or polled).
The page is filled, copied to userspace, and `read()` returns. `O_DIRECT` skips the page
cache and DMAs straight into an aligned user buffer.
*Bridge:* "Every layer is either a copy, a latency source, or a durability boundary — the
same map I use to reason about KV-cache offload paths."

---

### Q2. `libaio` vs `io_uring` vs `epoll` — when do you use each?

**A.** **epoll** is *readiness*-based — great for sockets, useless for regular files
(always "ready"). **libaio** does async disk I/O but only truly async with **`O_DIRECT`**,
and costs two syscalls per batch (`io_submit`/`io_getevents`). **io_uring** unifies
everything via shared **SQ/CQ rings**: batched submission (one `io_uring_enter` for many
ops), works with buffered *and* direct I/O, and can run with **zero syscalls** (SQPOLL) or
**interrupt-free** (IOPOLL), plus registered fds/buffers. For a new high-performance path
today I default to io_uring; libaio only for legacy.

---

### Q3. Explain io_uring's ring architecture.

**A.** Two ring buffers shared (mmap'd) between user and kernel. The app fills a
**submission queue entry (SQE)** — opcode, fd, buffer, offset, user_data — advances the SQ
tail (a memory write, no syscall), then calls `io_uring_enter` to process a batch. The
kernel executes and posts **completion queue entries (CQEs)** to the CQ ring; the app reaps
by reading the CQ head. Memory ordering on head/tail matters. Advanced: **SQPOLL** (kernel
thread polls the SQ → zero submit syscalls), **IOPOLL** (busy-poll completions, no IRQ),
**registered buffers/files** (skip per-op pinning), **linked SQEs** (dependencies),
**multishot**. *I built a raw-syscall io_uring benchmark to demonstrate this — it shows
io_uring hitting ~250k IOPS/core with lower p99 than a thread pool, while POSIX AIO
flatlines because glibc emulates it with a thread pool.*

---

### Q4. What is write amplification and how do you reduce it?

**A.** NAND can't overwrite in place — program is page-granular, **erase is
block-granular** and slow. So the FTL writes out-of-place and later **garbage-collects**,
copying still-valid pages before erasing a block. **WA = NAND bytes written ÷ host bytes
written**; GC copying is the main source (also RMW on misaligned writes, metadata). Reduce
it with **over-provisioning** (more GC headroom), **TRIM/discard** (don't copy dead data),
**sequential/append-only** writes (whole blocks invalidate together → WA≈1), alignment, and
**ZNS/FDP** (host groups data by lifetime so zones erase together). *For a read-mostly,
append-written KV-cache SSD tier, ZNS/FDP QLC is a great fit.*

---

### Q5. Why does an SSD look fast then slow down under sustained writes?

**A.** The **SLC cache**: TLC/QLC drives run part of the NAND in fast 1-bit SLC mode as a
write buffer. Bursts hit SLC (fast); once it fills, writes fall back to native TLC/QLC
(slow) and the drive must fold SLC→TLC in the background — the throughput "cliff."
Consequence for benchmarking: you must **precondition** (fill + reach steady state) and
report sustained numbers, not the SLC burst. Always report **p99/p99.9**, since GC induces
tail latency.

---

### Q6. How would you diagnose high I/O latency on a production box?

**A.** Start with **method, not tools**: define the metric/SLO and workload, then apply
**USE** (Utilization/Saturation/Errors per resource). `iostat -x` for per-device latency
(`r_await`/`w_await`), queue depth (`aqu-sz`) — ignore `%util` on SSDs. Split software vs
device with **blktrace/btt**: **Q2D** (time in block layer/scheduler) vs **D2C** (device
service time). `biolatency`/`biosnoop` (bpftrace) for histograms and per-process. `perf`
flame graphs if CPU-bound (copies, spinlocks, softirq). Check page-cache hit
(`cachestat`), writeback stalls (`Dirty`/`Writeback` in `/proc/meminfo`, `dirty_ratio`),
and NUMA/IRQ affinity. Change one variable, re-measure against baseline.

---

### Q7. Stackful vs stackless coroutines — trade-offs, and how do they pair with io_uring?

**A.** **Stackful** (libco, Boost.Context, goroutines) give each coroutine a full stack, so
you can yield from arbitrary call depth; cost is memory per stack and stack-size guessing.
**Stackless** (C++20, Rust, Python `async`) are compiler-generated state machines — tiny
per-coroutine memory, but "colored" functions (async infects the call chain) and you can
only suspend at `await` points. Switching a coroutine is ~10–50 ns in user space vs
~1–2 µs for a preemptive thread. The winning server pattern is **thread-per-core +
io_uring + coroutines** (Seastar/SPDK/glommio): submit each coroutine's I/O as SQEs, resume
the coroutine on its CQE — synchronous-looking code, no locks (shared-nothing), batched
async I/O.

---

### Q8. Which I/O scheduler for an NVMe SSD, and why?

**A.** Usually **`none`**. A modern NVMe device has deep hardware queues and does its own
ordering; a kernel scheduler mostly adds CPU and latency. For SATA SSDs or mixed workloads
I'd use **mq-deadline** to stop writes starving reads; for proportional multi-tenant QoS,
**bfq** or cgroup v2 `io.max`/`io.latency`. The deeper point: blk-mq's per-CPU software
queues exist precisely so a million-IOPS device isn't bottlenecked on one queue lock.

---

### Q9. HDD vs SSD vs NVMe — contrast the performance characteristics.

**A.** HDD: mechanical seek+rotate → ~5–10 ms random latency, ~100–200 IOPS, loves
**sequential**. SATA SSD: ~100 µs, ~50–100k IOPS, AHCI QD=32 ceiling. NVMe SSD: ~10–80 µs,
500k–several-M IOPS, 3–14 GB/s (PCIe4/5), 64k queues. NVMe wins on random and parallelism;
its caveats are **GC jitter** (tail latency) and the **SLC cliff**. For an AI KV tier you
want NVMe (ideally read-optimized, predictable-latency, high-QD).

---

### Q10. What is RDMA and why is it relevant to AI serving?

**A.** RDMA lets a NIC read/write **remote memory directly** — zero-copy, kernel-bypass,
offloaded to hardware; **one-sided READ/WRITE** don't involve the remote CPU. Building
blocks: **QP** (queue pair), **CQ** (completions, same model as io_uring), **MR**
(registered/pinned memory). Transports: InfiniBand, **RoCEv2** (needs a lossless fabric —
PFC + ECN/DCQCN), iWARP (over TCP). Relevance: **PD disaggregation** ships the KV cache
between prefill and decode nodes, and **NVMe-oF** disaggregates storage — both want RDMA's
µs latency and line-rate bandwidth, ideally with **GPUDirect RDMA** to DMA straight into
GPU memory.
