#!/usr/bin/env python3
"""async-io-bench orchestrator.

Builds iobench (via make), sweeps queue depth across I/O engines, collects
IOPS / bandwidth / latency percentiles, writes a CSV, prints a table, and
(optionally) plots the throughput-vs-latency knee curve from kb/09.

Cross-platform: on Linux you get sync/threads/posixaio/iouring; on macOS
io_uring is unavailable so it's skipped automatically.

Usage:
    python3 bench.py                       # default sweep on a scratch file
    python3 bench.py --engines iouring threads sync --qds 1 4 16 64 128
    python3 bench.py --direct              # O_DIRECT (measures device, not cache)
    python3 bench.py --plot sweep.png
"""
import argparse
import csv
import os
import platform
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(HERE, "iobench")


def build():
    if platform.system() == "Windows":
        print("Windows not supported for the C benchmark; use WSL.", file=sys.stderr)
        sys.exit(2)
    if shutil.which("make") is None:
        print("`make` not found; build iobench manually with cc.", file=sys.stderr)
        sys.exit(2)
    subprocess.run(["make", "-C", HERE], check=True)


def make_scratch(path, size_mb):
    if os.path.exists(path) and os.path.getsize(path) >= size_mb * 1024 * 1024:
        return
    print(f"creating {size_mb} MiB scratch file at {path} ...")
    with open(path, "wb") as f:
        chunk = os.urandom(1024 * 1024)
        for _ in range(size_mb):
            f.write(chunk)


def run_one(path, engine, qd, bs, ios, direct):
    cmd = [BIN, "--file", path, "--engine", engine, "--qd", str(qd),
           "--bs", str(bs), "--ios", str(ios)]
    if direct:
        cmd.append("--direct")
    out = subprocess.run(cmd, capture_output=True, text=True)
    for line in out.stdout.splitlines():
        if line.startswith("RESULT,"):
            f = line.split(",")
            return {
                "engine": f[1], "qd": int(f[2]), "bs": int(f[3]), "ios": int(f[4]),
                "iops": float(f[5]), "MBps": float(f[6]), "avg_us": float(f[7]),
                "p50_us": float(f[8]), "p99_us": float(f[9]), "p999_us": float(f[10]),
            }
    if out.returncode == 3:  # engine unsupported
        return None
    print(f"  [{engine} qd={qd}] no result: {out.stderr.strip()}", file=sys.stderr)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="/tmp/iobench.dat")
    ap.add_argument("--size-mb", type=int, default=512)
    ap.add_argument("--engines", nargs="+",
                    default=["sync", "threads", "posixaio", "iouring"])
    ap.add_argument("--qds", nargs="+", type=int, default=[1, 2, 4, 8, 16, 32, 64, 128])
    ap.add_argument("--bs", type=int, default=4096)
    ap.add_argument("--ios", type=int, default=100000)
    ap.add_argument("--direct", action="store_true")
    ap.add_argument("--csv", default=os.path.join(HERE, "results.csv"))
    ap.add_argument("--plot", default=None)
    args = ap.parse_args()

    build()
    make_scratch(args.file, args.size_mb)

    rows = []
    print(f"\nsweep: engines={args.engines} qds={args.qds} bs={args.bs} "
          f"direct={args.direct}\n")
    hdr = f"{'engine':>9} {'qd':>4} {'IOPS':>10} {'MB/s':>9} " \
          f"{'avg_us':>8} {'p99_us':>9} {'p99.9_us':>9}"
    print(hdr); print("-" * len(hdr))
    for engine in args.engines:
        for qd in args.qds:
            if engine == "sync" and qd != args.qds[0]:
                continue  # sync is QD1; run once
            r = run_one(args.file, engine, qd, args.bs, args.ios, args.direct)
            if r is None:
                continue
            rows.append(r)
            print(f"{r['engine']:>9} {r['qd']:>4} {r['iops']:>10,.0f} "
                  f"{r['MBps']:>9.1f} {r['avg_us']:>8.2f} {r['p99_us']:>9.2f} "
                  f"{r['p999_us']:>9.2f}")

    with open(args.csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print(f"\nwrote {args.csv}")

    if args.plot:
        try:
            plot(rows, args.plot)
            print(f"wrote {args.plot}")
        except ImportError:
            print("matplotlib not installed; pip install matplotlib", file=sys.stderr)

    print("\nNOTE: without --direct this measures page-cache + framework overhead,")
    print("not the device. For real device numbers run with --direct on a scratch")
    print("file on a real filesystem/SSD (see README). See kb/09 for methodology.")


def plot(rows, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    engines = sorted({r["engine"] for r in rows})
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.5))
    for e in engines:
        pts = sorted([r for r in rows if r["engine"] == e], key=lambda r: r["qd"])
        ax[0].plot([p["qd"] for p in pts], [p["iops"] for p in pts], "o-", label=e)
        ax[1].plot([p["iops"] for p in pts], [p["p99_us"] for p in pts], "o-", label=e)
    ax[0].set_xlabel("queue depth"); ax[0].set_ylabel("IOPS")
    ax[0].set_title("Throughput vs queue depth"); ax[0].set_xscale("log", base=2)
    ax[0].legend(); ax[0].grid(True, alpha=0.3)
    ax[1].set_xlabel("IOPS"); ax[1].set_ylabel("p99 latency (us)")
    ax[1].set_title("Latency vs throughput (the knee)"); ax[1].legend()
    ax[1].grid(True, alpha=0.3)
    fig.tight_layout(); fig.savefig(path, dpi=120)


if __name__ == "__main__":
    main()
