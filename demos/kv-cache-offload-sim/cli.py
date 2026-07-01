#!/usr/bin/env python3
"""KV cache offload simulator -- CLI.

Compares serving strategies on a synthetic multi-turn workload:
  * hbm_only         : evict-and-recompute when KV overflows HBM
  * tiered           : spill cold KV to DRAM -> CXL -> SSD (read back on reuse)
  * tiered + prefix  : also reuse shared prefixes across requests (APC)

Examples:
    python3 cli.py
    python3 cli.py --model llama-3-70b --requests 500 --revisit 0.6
    python3 cli.py --sweep-prefetch
    python3 cli.py --kv-bytes 1     # FP8 KV -> smaller blocks, fewer spills
    python3 cli.py --plot out.png   # requires matplotlib (optional)
"""
import argparse
import json
import sys

from kvsim import (PRESETS, Hierarchy, DEFAULT_TIERS, KVCacheSimulator,
                   make_scenario, build_stream)


def human(n):
    for u in ["B", "KiB", "MiB", "GiB", "TiB"]:
        if abs(n) < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} PiB"


def main():
    ap = argparse.ArgumentParser(description="Tiered KV-cache offload simulator")
    ap.add_argument("--model", default="llama-3-8b", choices=list(PRESETS))
    ap.add_argument("--kv-bytes", type=float, default=0.0,
                    help="bytes per KV elem (2=FP16, 1=FP8/INT8, 0.5=INT4)")
    ap.add_argument("--requests", type=int, default=400)
    ap.add_argument("--prefixes", type=int, default=8)
    ap.add_argument("--share", type=float, default=0.6, help="prefix share prob")
    ap.add_argument("--sessions", type=int, default=60)
    ap.add_argument("--revisit", type=float, default=0.5,
                    help="probability a request resumes an existing session")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--prefetch", type=float, default=0.0,
                    help="fraction of CXL/SSD latency hidden by overlap [0,1)")
    ap.add_argument("--sweep-prefetch", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--plot", metavar="PATH", default=None)
    args = ap.parse_args()

    model = PRESETS[args.model]
    if args.kv_bytes:
        model = model.with_kv_dtype_bytes(args.kv_bytes)

    sc = make_scenario(n_requests=args.requests, n_prefixes=args.prefixes,
                       prefix_share_prob=args.share, n_sessions=args.sessions,
                       revisit_prob=args.revisit, seed=args.seed)
    sim = KVCacheSimulator(model, Hierarchy(DEFAULT_TIERS))

    stream_pc = build_stream(sc, model.block_tokens, prefix_cache=True)
    stream_no = build_stream(sc, model.block_tokens, prefix_cache=False)

    print(f"model={model.name}  kv_bytes/elem={model.bytes_per_elem}  "
          f"block={human(sim.block_bytes)}")
    caps = "  ".join(f"{t.name}={t.read_latency_us}us/{sim.tier_caps[i]}blk"
                     for i, t in enumerate(sim.hier.tiers))
    print(f"tiers (demo-scaled): {caps}")
    hot = human(len({b for b, _, _ in stream_no}) * sim.block_bytes)
    print(f"workload: {len(sc.turns)} reqs, {sc.n_sessions} sessions, "
          f"{args.prefixes} prefixes; KV to keep ALL hot in HBM = {hot}")
    print("=" * 80)

    configs = [
        ("hbm_only  (evict+recompute)", "hbm_only", stream_no),
        ("tiered    (spill to SSD)   ", "tiered",   stream_no),
        ("tiered + prefix-cache      ", "tiered",   stream_pc),
    ]
    results = []
    for label, strat, stream in configs:
        r = sim.run(stream, strategy=strat, prefetch_hide_frac=args.prefetch)
        results.append((label, r))
        print(f">>> {label}")
        print(r.pretty())
        print("-" * 80)

    if args.sweep_prefetch:
        print("\nprefetch sweep (tiered + prefix-cache): overlap hides SSD/CXL latency")
        print(f"{'hide_frac':>10} | {'avg_us':>10} | {'p99_us':>10}")
        for pf in [0.0, 0.25, 0.5, 0.75, 0.9, 0.95]:
            r = sim.run(stream_pc, strategy="tiered", prefetch_hide_frac=pf)
            print(f"{pf:>10.2f} | {r.avg_access_latency_us:>10.2f} | "
                  f"{r.p99_access_latency_us:>10.2f}")

    if args.json:
        print(json.dumps([r.as_dict() for _, r in results], indent=2))

    if args.plot:
        try:
            make_plot(results, args.plot)
            print(f"\nwrote {args.plot}")
        except ImportError:
            print("matplotlib not installed; `pip install matplotlib` to plot",
                  file=sys.stderr)


def make_plot(results, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = [lbl.strip() for lbl, _ in results]
    rs = [r for _, r in results]
    x = range(len(labels))
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.2))

    ax[0].bar(x, [r.avg_access_latency_us for r in rs], color="#4C78A8", label="avg")
    ax[0].plot(x, [r.p99_access_latency_us for r in rs], "o-r", label="p99")
    ax[0].set_xticks(list(x)); ax[0].set_xticklabels(labels, rotation=12, fontsize=8)
    ax[0].set_ylabel("KV re-access latency (us)")
    ax[0].set_title("Effective KV access latency"); ax[0].legend()

    tiers = list(rs[0].tier_hits.keys()) + ["recompute"]
    bottom = [0.0] * len(rs)
    for t in tiers:
        if t == "recompute":
            vals = [100 * r.recompute_misses / max(1, r.n_references) for r in rs]
        else:
            vals = [100 * r.tier_hits[t] / max(1, r.n_references) for r in rs]
        ax[1].bar(x, vals, bottom=bottom, label=t)
        bottom = [b + v for b, v in zip(bottom, vals)]
    ax[1].set_xticks(list(x)); ax[1].set_xticklabels(labels, rotation=12, fontsize=8)
    ax[1].set_ylabel("% of KV re-references"); ax[1].set_title("Where KV reads are served")
    ax[1].legend(fontsize=8)
    fig.tight_layout(); fig.savefig(path, dpi=120)


if __name__ == "__main__":
    main()
