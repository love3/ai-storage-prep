# 09 · Performance Tuning: fio, SPDK, Methodology

> JD Q1/Q6/Q11/Q13. Performance work is judged on *method*, not luck. Show a repeatable
> methodology, the right tools, and correct experiment hygiene.

## 1. Methodology first (say this before any tool)

**Define the goal + metric + workload.** "Faster" is meaningless. Specify:
- Metric: p99 latency? IOPS? bandwidth? at what QD/block size/read-write mix?
- Workload: representative of production (block size, randomness, QD, read/write ratio,
  working-set size vs cache).
- SLO: e.g., "1M read IOPS at p99 < 200 µs".

**The USE method (Brendan Gregg):** for every resource (CPU, memory, disk, net) check
**Utilization, Saturation, Errors**. Find the saturated resource → that's the bottleneck.

**The RED method** (for services): Rate, Errors, Duration.

**Loop:** hypothesize bottleneck → measure → change *one* variable → re-measure →
keep/revert. Always compare against a baseline. Beware measuring the benchmark, not the
system.

## 2. fio — the workhorse

fio generates precise synthetic workloads and reports latency percentiles.

```ini
# 4K random read, io_uring, QD=32, direct, measure sustained
[randread]
ioengine=io_uring      # or libaio, psync, sync, posixaio (macOS)
direct=1               # O_DIRECT: bypass page cache (measure device, not RAM)
rw=randread            # randwrite, randrw, read, write
bs=4k
iodepth=32             # queue depth per job
numjobs=4              # parallel jobs (threads)
size=100G
runtime=120
ramp_time=30           # warm-up excluded from stats
time_based=1
group_reporting=1
percentile_list=50:99:99.9:99.99
```

**Critical hygiene:**
- `direct=1` to measure the device, not the page cache (else you benchmark RAM).
- **Precondition** SSDs: fill the whole device, then run steady-state to get *past the
  SLC cache and into GC steady state* (KB 05). Report steady-state numbers.
- Use `ramp_time` to exclude warm-up.
- Working set > cache if you want to measure media, not cache.
- Report **percentiles** (`--latency-percentiles`), not just mean; the tail is the story.
- Sweep **QD** and **block size** to draw the latency-throughput curve (Little's Law).
- Match `ioengine` to what production uses (io_uring vs libaio vs sync).

**Reading output:** IOPS, BW, clat (completion latency) percentiles, `iodepth`
distribution. Cross-check with `iostat -x` during the run.

## 3. Latency vs throughput curve (draw this)

```
throughput ▲            ___________  <- saturation (device max)
           │          /
           │        /
           │      /
           │____/______________________►  offered load / QD
latency    ▲                        /
           │                      /   <- knee: queueing latency explodes
           │__________________ /
           │__________________________►  QD
```
Below the knee, adding QD buys throughput cheaply; past it, latency explodes for little
gain (Little's Law: QD = throughput × latency). **The right operating point is just
below the knee.** This single graph reframes most tuning discussions.

## 4. The observability toolbox by layer

| Layer | Tools |
|-------|-------|
| App | strace/ltrace, perf record, flamegraphs |
| Syscall/scheduler | `perf trace`, `bpftrace`, `runqlat`, `offcputime` |
| Page cache/VM | `cachestat`, `vmstat`, `/proc/meminfo` |
| Block | `iostat -x`, `blktrace`+`btt`, `biolatency`, `biosnoop` |
| NVMe/device | `nvme smart-log`, `nvme error-log`, controller telemetry |
| Net | `sar -n`, `ss -i`, `nstat`, `ethtool -S`, `ib_*_bw` |
| GPU | `nvidia-smi dmon`, `nsys`(Nsight Systems), `ncu`, DCGM |
| Whole system | `perf`, `bpftrace`, `sar`, `dstat` |

**blktrace stages to know:** Q (queued) → G (get request) → I (inserted) → D (dispatched
to driver) → C (completed). **Q2D** = time in the block layer/scheduler; **D2C** = device
service time. If Q2D dominates, the bottleneck is software/queueing; if D2C dominates,
it's the device.

## 5. Flame graphs & CPU profiling

`perf record -g` → flame graph shows where CPU time goes. For storage, look for: copy
functions (memcpy/copy_user), lock contention (spinlock), interrupt handling, filesystem
overhead. This is how you justify O_DIRECT, io_uring, or kernel bypass with data.

## 6. SPDK for perf (kernel-bypass benchmarking)

- `spdk/perf` (bdevperf, `nvme perf`) drives NVMe in userspace poll-mode → shows the
  device's true ceiling without kernel overhead. Comparing kernel io_uring numbers vs
  SPDK numbers quantifies kernel overhead → the argument for bypass.
- SPDK thread-per-core reactors, no locks, hugepages, poll-mode driver.

## 7. Common bottlenecks & fixes (cheat sheet)

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Low IOPS, low latency, device idle | QD too low / not async | raise iodepth, use io_uring |
| High CPU, moderate IOPS | copies / interrupts / softirq | O_DIRECT, io_uring polling, IRQ affinity, SPDK |
| Throughput cliff after seconds | SLC cache exhausted / GC | precondition; expect steady-state; more OP |
| High p99 tail, ok p50 | GC jitter / noisy neighbor / writeback stall | QoS (cgroup io.latency), separate namespaces, tune dirty_ratio |
| Scales poorly with cores | shared queue lock / cache bouncing | blk-mq, thread-per-core, NUMA pinning |
| Cross-NUMA penalty | buffer/IRQ on wrong node | pin threads+IRQ+memory to device's node |
| Random write amplification | small unaligned writes | align, batch, log-structured, TRIM |

## 8. Cluster-scale perf (JD Q6)

- Tail latency amplification: a request that fans out to N shards is as slow as the
  slowest shard → **hedged requests**, **tail-tolerant** techniques (Dean & Barroso,
  "The Tail at Scale").
- Load imbalance / hot shards → better hashing, replication of hot keys.
- Coordinated omission in load generators (fix: open-loop generators, correct latency
  accounting).
- Noisy neighbors → isolation (cgroups, dedicated queues, QoS).

## 9. Interview-ready talking points

- "I start with a metric, an SLO, and a representative workload, then apply USE — find
  the saturated resource before touching anything, and change one variable at a time."
- "With fio I always use direct=1, precondition the SSD to steady state past the SLC
  cache, exclude warm-up, and report p99/p99.9 — averages hide the tail that actually
  breaks SLOs."
- "The latency-throughput knee (Little's Law) tells me the right QD; below it throughput
  is cheap, above it latency explodes."
- "blktrace splits Q2D (software/queueing) from D2C (device) so I know whether to fix the
  stack or the hardware; comparing kernel io_uring to SPDK quantifies kernel overhead."
- "At cluster scale the tail dominates: a fan-out request is as slow as its slowest
  shard, so I use hedging, isolation, and QoS to tame p99."
