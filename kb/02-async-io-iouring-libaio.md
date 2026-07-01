# 02 · Async I/O: io_uring, libaio, POSIX AIO

> This is a first-tier topic in the JD ("精通异步编程模型 Linux AIO、io_uring"). Be ready to
> compare them and explain io_uring's ring architecture in detail.

## 1. Why async I/O at all

Synchronous blocking I/O ties up a thread per outstanding request. To reach high IOPS
you either (a) run thousands of threads (context-switch + cache thrash cost), or
(b) issue many I/Os from few threads and reap completions asynchronously. Storage
devices want **high queue depth** to hit peak IOPS; async I/O is how one core keeps QD
high.

## 2. The options, ranked

| API | Async? | Buffered I/O? | Syscalls/op | Notes |
|-----|--------|---------------|-------------|-------|
| blocking `read/write` | No | Yes | 1 | one thread per in-flight I/O |
| `epoll`+nonblock | Yes (sockets, pipes) | n/a | — | **does not work for regular files** (always "ready") |
| POSIX AIO (`aio_*`) | "Yes" | Yes | — | usually glibc thread-pool emulation; weak |
| Linux `libaio` (`io_submit`) | Yes | **O_DIRECT only** | 2 (submit+getevents) | historically the DB path; limited |
| **io_uring** | Yes | Yes (buffered + direct) | 0–2, can be 0 with polling | modern, unified, fast |

**Key facts to state:**
- `epoll` is for **readiness** (sockets); regular files are always "readable", so epoll
  is useless for disk I/O. You need real async submission.
- `libaio` only truly async with **`O_DIRECT`**; buffered submissions silently block.
  Also 2 syscalls per batch, and copy-in overhead.
- **io_uring** fixes all of this: works with buffered + direct, batches submissions,
  and can run with *zero* syscalls per I/O in polled mode.

## 3. io_uring architecture (the money topic)

Two shared ring buffers in memory mapped between user space and kernel:

```
   User space                         Kernel
 ┌───────────────┐                 ┌───────────────┐
 │  SQ (submission│  ── entries ──► │  processes SQEs│
 │  queue) SQEs   │                 │  issues I/O    │
 └───────────────┘                 └───────────────┘
 ┌───────────────┐                 ┌───────────────┐
 │  CQ (completion│ ◄── entries ──  │  posts CQEs    │
 │  queue) CQEs   │                 │                │
 └───────────────┘                 └───────────────┘
```

Flow:
1. App gets an **SQE** (submission queue entry), fills opcode (READ/WRITE/etc.), fd,
   buffer, offset, user_data.
2. App advances the SQ tail (shared memory, no syscall).
3. App calls `io_uring_enter()` to tell the kernel to process N SQEs — **one syscall for
   a whole batch**.
4. Kernel processes, later posts **CQEs** to the CQ ring.
5. App reaps CQEs by reading the CQ head (no syscall).

### Advanced modes

- **`IORING_SETUP_SQPOLL`**: a kernel thread polls the SQ, so the app submits with
  **zero syscalls** — just write SQEs and update the tail. Great for ultra-low overhead.
- **`IORING_SETUP_IOPOLL`**: busy-poll for completions on the device (NVMe polling) —
  lowest latency, no interrupts, but burns a core.
- **Registered files / buffers** (`IORING_REGISTER_*`): pre-pin fds and buffers to skip
  per-op refcount/pinning cost.
- **Fixed buffers** avoid get_user_pages per I/O.
- **Linked SQEs / chains**: express dependencies (do B after A) in one submission.
- **Multishot** ops: one SQE yields many CQEs (e.g., accept, recv).
- io_uring also does **networking** ops (accept/recv/send), timeouts, fsync, openat,
  etc. — a general async syscall interface, not just storage.

### Why it's fast (summarize)
- Batched submission (amortize syscall).
- Optional zero syscalls (SQPOLL).
- No per-op copy of iocb (shared ring).
- Polled completions avoid interrupts.
- Registered/fixed resources avoid repeated setup.

### Cost / caveats
- Complexity; correctness of memory ordering on the rings.
- Security surface (some environments disable it via `io_uring_disabled` sysctl / seccomp).
- Buffer lifetime: buffers must stay valid until the CQE arrives.

## 4. Minimal io_uring (liburing) sketch

```c
struct io_uring ring;
io_uring_queue_init(QD, &ring, 0);          // set up rings

struct io_uring_sqe *sqe = io_uring_get_sqe(&ring);
io_uring_prep_read(sqe, fd, buf, len, offset);
io_uring_sqe_set_data(sqe, my_ctx);
io_uring_submit(&ring);                       // one syscall for the batch

struct io_uring_cqe *cqe;
io_uring_wait_cqe(&ring, &cqe);               // reap
void *ctx = io_uring_cqe_get_data(cqe);
int res = cqe->res;                           // bytes or -errno
io_uring_cqe_seen(&ring, cqe);
```

## 5. libaio sketch (for contrast)

```c
io_context_t ctx = 0;
io_setup(QD, &ctx);
struct iocb cb, *cbs[1] = { &cb };
io_prep_pread(&cb, fd, buf, len, offset);     // fd MUST be O_DIRECT for real async
io_submit(ctx, 1, cbs);                        // syscall 1
struct io_event ev[QD];
io_getevents(ctx, 1, QD, ev, NULL);            // syscall 2
```

## 6. Coroutines + io_uring = the modern high-perf pattern

The idiomatic model: an event loop that submits SQEs and, on completion, resumes the
coroutine that was waiting on that I/O. This gives synchronous-looking code with async
performance. See KB 03. (Python 3.12+ has no stdlib io_uring, but `asyncio` maps to
epoll; libraries like `io_uring`/`liburing` bindings exist. C++ uses `co_await` over an
io_uring backend; Rust uses `tokio-uring`/`glommio`.)

## 7. Practical tuning knobs

- **Queue depth (QD)**: too low → device idle; too high → latency spikes + memory. Sweep
  it (see demo 2).
- **Batch size** per `io_uring_enter`.
- **SQPOLL idle timeout** (`sq_thread_idle`).
- Pin the poller thread; watch NUMA locality of buffers vs device.
- For buffered vs direct: direct removes double-caching and page-cache CPU but loses
  readahead and caching benefits.

## 8. Relevance to the AI-storage role

KV cache offload to NVMe SSD is exactly a **high-QD, latency-sensitive async I/O**
problem: you must prefetch KV blocks and read them back without stalling decode.
io_uring (or SPDK/GDS) is the mechanism. When they ask "how would you offload KV cache
to SSD without killing latency", the answer includes: **async batched reads (io_uring),
prefetch ahead of need, overlap with compute, big enough QD to hit SSD bandwidth, and
possibly GPUDirect Storage to DMA straight into GPU memory** (KB 14).

## 9. Interview-ready talking points

- "epoll is readiness-based and useless for regular files; libaio needs O_DIRECT and
  costs 2 syscalls/batch; io_uring unifies everything with shared SQ/CQ rings."
- "io_uring's win is batched submission plus optional zero-syscall (SQPOLL) and
  interrupt-free (IOPOLL) modes, plus registered fds/buffers."
- "The rings are shared memory; you advance a tail to submit and read a head to reap —
  memory ordering matters."
- "For KV-cache-to-SSD, I'd drive it with io_uring at high queue depth, prefetching KV
  blocks so the reads overlap with decode compute."
