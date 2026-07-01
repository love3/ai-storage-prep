# 03 · Coroutines & High-Concurrency Models

> JD asks for coroutine internals ("理解协程实现的原理与应用") and bonus points for
> libco / Boost.Coroutine. Know stackful vs stackless and how coroutines pair with async I/O.

## 1. The concurrency spectrum

| Model | Unit | Scheduler | Cost/switch | Scale |
|-------|------|-----------|-------------|-------|
| Process | process | kernel | high (addr space) | 100s |
| Thread | kernel thread | kernel (preemptive) | ~1–2 µs + cache | 1000s |
| Coroutine | user-space | app (cooperative) | ~10–50 ns | millions |
| Event loop / callback | closure | app | none (no stack) | millions |

Coroutines give you **cheap, cooperative** concurrency: no kernel involvement to switch,
no per-thread stack overhead at scale, no locking for data touched only between yield
points (single-threaded). The tradeoff: **cooperative** — one coroutine that never
yields (e.g., a blocking syscall or a tight CPU loop) stalls everyone on that thread.

## 2. Stackful vs stackless coroutines

**Stackful** (a.k.a. fibers): each coroutine owns a full call stack. You can yield from
*any* nested function. Switching = save/restore registers + swap stack pointer.
- Examples: **libco** (Tencent), **Boost.Coroutine/Context**, Go goroutines (runtime),
  ucontext/`makecontext`/`swapcontext`, `setjmp`/`longjmp`-based hacks.
- Pros: transparent — existing synchronous code can yield deep in the stack.
- Cons: each needs a stack (memory), stack size guessing, harder to make safe.

**Stackless**: the coroutine is a state machine; local state lives in a heap-allocated
frame. You can only suspend at explicit `await`/`yield` points in the coroutine
function itself.
- Examples: **C++20 coroutines** (`co_await`/`co_yield`/`co_return`), **Rust async/await**,
  **Python `async def`**, C#/JS async.
- Pros: tiny per-coroutine memory (just the live state), compiler-optimizable.
- Cons: "colored functions" — async infects call chains; can't yield from arbitrary depth.

**Interview one-liner:** "Stackful = own stack, yield anywhere, more memory (libco,
Boost.Context, goroutines). Stackless = compiler-generated state machine, suspend only
at await points, tiny memory (C++20, Rust, Python)."

## 3. How a stackful switch works (mechanics)

At the lowest level (e.g., Boost.Context `jump_fcontext`, or libco):
1. Save callee-saved registers (rbx, rbp, r12–r15, rsp, rip) of the current coroutine
   onto its stack / context struct.
2. Load the target coroutine's saved registers, including its `rsp` (stack pointer) and
   return address.
3. Return — now executing on the other coroutine's stack.

No kernel transition; it's ~a few dozen instructions. `ucontext` does this but is slow
(it also saves the signal mask via a syscall) — that's why libco/Boost roll their own.

**libco extra trick:** it *hooks* blocking syscalls (`read`, `write`, `connect`, ...)
via symbol interposition so that a blocking call transparently registers with an epoll
loop and yields the coroutine instead of blocking the thread. That's how it makes
legacy synchronous code non-blocking without rewrites.

## 4. Stackless in C++20 (concept)

```cpp
task<int> read_block(int fd, void* buf, size_t n, off_t off) {
    int r = co_await async_read(fd, buf, n, off);  // suspend; io_uring backend resumes us
    co_return r;
}
```
The compiler transforms the function into a state machine with a `promise_type`; the
`co_await` splits it at the suspension point. An **executor / io_uring backend** resumes
the coroutine handle when the CQE arrives.

## 5. Coroutines + async I/O (the pattern that matters)

The high-performance server pattern:
```
loop:
  submit ready coroutines' I/O as io_uring SQEs
  io_uring_enter()               # batch submit
  for each CQE:
      resume the coroutine waiting on cqe->user_data
```
This yields **synchronous-looking code** with **event-loop performance**. Runtimes that
embody this: Rust `glommio`/`tokio-uring` (thread-per-core + io_uring), C++ `seastar`
(ScyllaDB), Go net poller (epoll under goroutines).

## 6. Thread-per-core / shared-nothing

Modern storage engines (ScyllaDB/Seastar, SPDK, glommio) use **thread-per-core**: pin
one thread per core, each owns a shard of data and its own io_uring, **no shared mutable
state → no locks**. Communication is via message passing between cores. This eliminates
lock contention and cache-line bouncing that limit shared-everything designs at high
core counts. Combine with coroutines for programmability.

**Talking point:** "At a million IOPS, the enemy is the lock and the cache line. Thread-
per-core + io_uring + coroutines (Seastar/SPDK model) removes shared state so scaling is
linear in cores."

## 7. Python concurrency (for prototyping — Q2)

- **`asyncio`**: stackless coroutines (`async def`/`await`) on a single-thread epoll
  loop. Great for I/O-bound orchestration; **GIL** means no CPU parallelism.
- **threads**: I/O concurrency only (GIL); fine for blocking calls that release the GIL.
- **multiprocessing**: real parallelism, IPC cost.
- For real storage benchmarking you drop to C / liburing, or call fio; use Python for
  orchestration, data analysis (pandas), and plotting.

## 8. Pitfalls & correctness

- **Blocking in a coroutine** (a real blocking syscall, `time.sleep`, heavy CPU) stalls
  the whole loop → offload to a thread pool / separate reactor.
- **Cancellation & lifetimes**: buffers awaited by I/O must outlive the await; cancelled
  coroutines must not free in-flight buffers (esp. with io_uring).
- **Fairness / starvation**: a coroutine that rarely yields starves peers (cooperative).
- **Stack size** (stackful): too small → overflow; too big → memory blowup at scale.

## 9. Interview-ready talking points

- "Coroutines are ~10–50 ns cooperative switches in user space vs ~1–2 µs preemptive
  thread switches; that's why you can have millions."
- "Stackful (libco, Boost.Context) yields anywhere at the cost of a stack; stackless
  (C++20, Rust, Python) is a compiler state machine with minimal memory but colored
  functions."
- "libco hooks blocking syscalls and turns them into epoll yields — legacy code becomes
  async for free."
- "The winning server architecture is thread-per-core + io_uring + coroutines: no shared
  state, no locks, batched async I/O, synchronous-looking code (Seastar/SPDK/glommio)."
