#!/usr/bin/env python3
"""LLM inference sizing & roofline calculator.

Answers the JD's core question (R5): given a model + GPU, what are the
compute / VRAM / DRAM / storage requirements, and where is the bottleneck?

It computes:
  * model weight memory
  * KV cache size per token / per sequence / for a batch
  * how much context x batch fits in HBM after weights
  * prefill time (compute-bound) vs decode throughput (memory-bandwidth-bound)
  * the roofline crossover (batch size where decode stops being memory-bound)

Pure standard library. No GPU or model download needed -- runs anywhere.

Examples:
    python3 sizing.py --model llama-3-8b --gpu h100-80g
    python3 sizing.py --model llama-3-70b --gpu a100-80g --ctx 8192 --batch 32
    python3 sizing.py --model llama-3-8b --gpu h100-80g --kv-bytes 1   # FP8 KV
"""
import argparse

GiB = 1024 ** 3
TiB = 1024 ** 4

# --- model presets: (params_B, layers, kv_heads, head_dim, weight_bytes) ------
MODELS = {
    #                    params  layers kv_heads head_dim wbytes
    "llama-3-8b":      dict(params=8.0e9,  layers=32, kv_heads=8,  head_dim=128, wbytes=2),
    "llama-3-70b":     dict(params=70e9,   layers=80, kv_heads=8,  head_dim=128, wbytes=2),
    "llama-2-13b-mha": dict(params=13e9,   layers=40, kv_heads=40, head_dim=128, wbytes=2),
    "mistral-7b":      dict(params=7.3e9,  layers=32, kv_heads=8,  head_dim=128, wbytes=2),
    "qwen2-72b":       dict(params=72e9,   layers=80, kv_heads=8,  head_dim=128, wbytes=2),
}

# --- GPU presets: (HBM bytes, HBM BW GB/s, FP16 TFLOPS) -----------------------
GPUS = {
    "h100-80g":  dict(hbm=80 * GiB,  bw_GBs=3350, tflops=990),
    "a100-80g":  dict(hbm=80 * GiB,  bw_GBs=2039, tflops=312),
    "a100-40g":  dict(hbm=40 * GiB,  bw_GBs=1555, tflops=312),
    "l40s":      dict(hbm=48 * GiB,  bw_GBs=864,  tflops=362),
    "rtx4090":   dict(hbm=24 * GiB,  bw_GBs=1008, tflops=165),
    "apple-m3max": dict(hbm=128 * GiB, bw_GBs=400, tflops=28),  # unified memory
}


def human(n):
    for u in ["B", "KiB", "MiB", "GiB", "TiB"]:
        if abs(n) < 1024:
            return f"{n:.2f} {u}"
        n /= 1024
    return f"{n:.2f} PiB"


def kv_per_token(m, kv_bytes):
    return 2 * m["layers"] * m["kv_heads"] * m["head_dim"] * kv_bytes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="llama-3-8b", choices=list(MODELS))
    ap.add_argument("--gpu", default="h100-80g", choices=list(GPUS))
    ap.add_argument("--ctx", type=int, default=4096, help="context length (tokens)")
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--kv-bytes", type=float, default=2.0,
                    help="bytes/KV elem: 2=FP16, 1=FP8/INT8, 0.5=INT4")
    ap.add_argument("--weight-bytes", type=float, default=0.0,
                    help="override weight bytes/param (2=FP16, 1=INT8, 0.5=INT4)")
    args = ap.parse_args()

    m = MODELS[args.model]
    g = GPUS[args.gpu]
    wbytes = args.weight_bytes or m["wbytes"]

    weights = m["params"] * wbytes
    kvpt = kv_per_token(m, args.kv_bytes)
    kv_seq = kvpt * args.ctx
    kv_batch = kv_seq * args.batch

    print(f"=== {args.model} on {args.gpu} ===")
    print(f"  params            : {m['params']/1e9:.1f} B")
    print(f"  weight dtype      : {wbytes} B/param -> weights = {human(weights)}")
    print(f"  GPU HBM           : {human(g['hbm'])} @ {g['bw_GBs']} GB/s, "
          f"{g['tflops']} FP16 TFLOPS")
    print()
    print(f"  KV per token      : {human(kvpt)}  (2*L*kv_heads*head_dim*{args.kv_bytes})")
    print(f"  KV per seq @ctx={args.ctx}: {human(kv_seq)}")
    print(f"  KV for batch={args.batch}    : {human(kv_batch)}")

    # capacity: what fits in HBM after weights
    free = g["hbm"] - weights
    print()
    if free <= 0:
        print(f"  !! weights ({human(weights)}) do NOT fit in HBM ({human(g['hbm'])}). "
              f"Need tensor/pipeline parallel across GPUs or quantization.")
    else:
        max_tokens = int(free / kvpt)
        max_seqs = max_tokens // args.ctx
        print(f"  HBM free for KV   : {human(free)}")
        print(f"  => max KV tokens  : {max_tokens:,}  "
              f"(~{max_seqs:,} concurrent seqs @ ctx={args.ctx})")
        if kv_batch > free:
            print(f"  !! requested batch*ctx KV ({human(kv_batch)}) EXCEEDS free HBM "
                  f"({human(free)}) -> must offload/quantize/reduce batch (kb/11,13)")

    # prefill: compute-bound. fwd FLOPs ~ 2 * params per token.
    prefill_flops = 2 * m["params"] * args.ctx * args.batch
    prefill_s = prefill_flops / (g["tflops"] * 1e12)
    print()
    print(f"  PREFILL (compute-bound):")
    print(f"    FLOPs (~2*P*tokens): {prefill_flops:.2e}  "
          f"for {args.ctx*args.batch:,} prompt tokens")
    print(f"    ideal time @ {g['tflops']} TFLOPS: {prefill_s*1e3:.1f} ms "
          f"(TTFT floor; real is higher)")

    # decode: memory-bound. per step read weights + KV for the batch.
    bytes_per_step = weights + kv_batch          # weights read once, KV for batch
    step_s = bytes_per_step / (g["bw_GBs"] * 1e9)
    tok_per_s = args.batch / step_s
    print()
    print(f"  DECODE (memory-bandwidth-bound):")
    print(f"    bytes read/step   : {human(bytes_per_step)} "
          f"(weights {human(weights)} + KV {human(kv_batch)})")
    print(f"    step time @ {g['bw_GBs']} GB/s: {step_s*1e3:.2f} ms")
    print(f"    => throughput     : {tok_per_s:,.0f} tok/s "
          f"({step_s*1e3:.2f} ms/token per user at batch {args.batch})")

    # roofline crossover: batch where compute time ~ memory time per decode step
    # decode compute per step ~ 2*P*batch FLOPs; memory ~ weights + batch*kv_seq
    # crossover batch B*: 2*P*B / TFLOPS == (weights + B*kv_seq) / BW
    P = m["params"]; bw = g["bw_GBs"] * 1e9; fl = g["tflops"] * 1e12
    denom = (2 * P / fl) - (kv_seq / bw)
    print()
    if denom > 0:
        b_star = (weights / bw) / denom
        print(f"  ROOFLINE: decode is memory-bound until batch ~ {b_star:,.0f}; "
              f"beyond that it turns compute-bound.")
    else:
        print(f"  ROOFLINE: KV read dominates; decode stays memory-bound at all batch "
              f"sizes for ctx={args.ctx} (long context -> KV bandwidth is the wall).")
    print()
    print("  Interpretation: prefill wants FLOPs; decode wants HBM bandwidth and is")
    print("  amortized by batching. When KV*batch exceeds HBM you offload/tier it")
    print("  (kb/11) or disaggregate prefill/decode (kb/13).")


if __name__ == "__main__":
    main()
