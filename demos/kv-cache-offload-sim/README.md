# Demo 1 · KV Cache Tiered-Offload Simulator

**What it shows (and why an interviewer cares):** LLM serving KV cache is a
multi-tier cache problem. This simulator models KV cache spread across
**HBM → DRAM → CXL → NVMe SSD** with PagedAttention-style blocks, LRU eviction,
prefix reuse, session readback, and prefetch — and quantifies the payoff of
tiering vs. evict-and-recompute. It's the storage-systems ↔ AI bridge from
[`kb/11-kv-cache-management.md`](../../kb/11-kv-cache-management.md).

## The story it tells

Running `./run.sh` on the default multi-turn workload:

| Strategy | avg KV re-access | recompute (evicted) | where reads are served |
|----------|------------------|---------------------|------------------------|
| **hbm_only** (evict + recompute) | ~1170 µs | **58%** | HBM only |
| **tiered** (spill to SSD) | ~31 µs | **0%** | HBM/DRAM/CXL/SSD |
| **tiered + prefix cache** | ~22 µs | **0%** | more DRAM/CXL hits, fewer distinct blocks |

Then the **prefetch sweep** shows overlapping the fetch with compute hides
SSD/CXL latency, dropping avg re-access latency from ~16 µs to <1 µs.

Key takeaways to say out loud:
- When KV overflows HBM, **recompute is brutal** (58% of re-reads) — tiering turns
  those into cheap SSD/CXL readbacks and drops effective latency ~50×.
- **Prefix caching** (APC / RadixAttention) shrinks the working set (fewer distinct
  blocks) and keeps hot shared prefixes in fast tiers.
- **Prefetch/overlap** is what makes SSD-backed KV viable — the same principle as
  readahead + async I/O in the storage stack (KB 02).
- **FP8 KV** (`--kv-bytes 1`) halves block size → more fits in HBM → fewer spills.

## Run it

```bash
# Core simulator + CLI need ONLY the Python standard library (3.8+).
./run.sh
# or directly:
python3 cli.py --requests 400
python3 cli.py --model llama-3-70b --revisit 0.6
python3 cli.py --sweep-prefetch
python3 cli.py --kv-bytes 1            # FP8 KV cache
python3 cli.py --plot out.png          # needs matplotlib

# Optional FastAPI server (drives the same engine over HTTP):
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload               # http://127.0.0.1:8000/docs
```

## How the model works (be ready to defend it)

- **Blocks**: KV cache split into fixed-size blocks (PagedAttention). Block size is
  computed from real model geometry: `2 × layers × kv_heads × head_dim × bytes ×
  block_tokens` (see `kvsim/model.py`).
- **Reference stream**: prefill references each prompt block once; decode re-reads the
  sequence's KV (subsampled); multi-turn sessions re-read their history on resume
  (`kvsim/workload.py`).
- **Tiers**: each tier is an LRU list with a block capacity. A referenced block is
  promoted to HBM; HBM overflow cascades the coldest block down to DRAM → CXL → SSD;
  overflow off SSD evicts it (a later reference = recompute). O(1) per access.
- **Metrics**: we measure **re-references** (decode-time KV reads), separating
  first-touch prefill (`populate`) from avoidable **recompute** (a re-read of an
  evicted block). Latency = the read latency of the tier the block sits in;
  `--prefetch f` hides fraction `f` of CXL/SSD latency (overlap with compute).

> **Honesty note:** tier *latencies/bandwidths* are order-of-magnitude real; tier
> *capacities* are demo-scaled down (proportions kept) so a laptop workload exercises
> all tiers. `REALISTIC_TIERS` in `kvsim/tiers.py` has real absolute sizes. The
> recompute penalty is a fixed teaching value. This is a *teaching* simulator, not a
> cycle-accurate model.

## Files
- `kvsim/model.py` — model geometry → KV byte math
- `kvsim/tiers.py` — the HBM/DRAM/CXL/SSD hierarchy
- `kvsim/workload.py` — prefixes + multi-turn sessions → reference stream
- `kvsim/simulator.py` — the tiered LRU cache engine
- `cli.py` — comparison, sweeps, plotting
- `app.py` — FastAPI wrapper
