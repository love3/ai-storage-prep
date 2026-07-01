#!/usr/bin/env python3
"""Measure real prefill vs decode timing against a running Ollama server.

Demonstrates the two-phase story from kb/10:
  * TTFT (time to first token) grows with PROMPT length  -> prefill is compute-bound
  * inter-token latency (ITL) stays ~flat                 -> decode is memory-bound
  * decode throughput (tok/s) is roughly prompt-independent

Cross-platform (Ollama runs on macOS + Linux). Uses only the standard library.

Setup:
    # install Ollama from https://ollama.com, then:
    ollama pull llama3.2:1b        # small model is fine for the demo
    ollama serve                    # (usually already running)
    python3 profile_ollama.py --model llama3.2:1b

If Ollama isn't reachable, it prints instructions and exits cleanly.
"""
import argparse
import json
import sys
import time
import urllib.request
import urllib.error


def gen_stream(host, model, prompt, num_predict):
    url = f"{host}/api/generate"
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": True,
        "options": {"num_predict": num_predict, "temperature": 0.0},
    }).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    ttft = None
    tok_times = []
    with urllib.request.urlopen(req, timeout=120) as resp:
        for line in resp:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            now = time.perf_counter()
            if obj.get("response"):
                if ttft is None:
                    ttft = now - t0
                tok_times.append(now)
            if obj.get("done"):
                meta = obj
                break
    return ttft, tok_times, meta


def summarize(ttft, tok_times):
    n = len(tok_times)
    if n < 2:
        return ttft, 0.0, 0.0
    itls = [(tok_times[i] - tok_times[i - 1]) * 1e3 for i in range(1, n)]
    avg_itl = sum(itls) / len(itls)
    total = tok_times[-1] - tok_times[0]
    tok_s = (n - 1) / total if total > 0 else 0
    return ttft, avg_itl, tok_s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="http://localhost:11434")
    ap.add_argument("--model", default="llama3.2:1b")
    ap.add_argument("--prompt-lens", nargs="+", type=int,
                    default=[16, 64, 256, 1024, 2048])
    ap.add_argument("--num-predict", type=int, default=64)
    ap.add_argument("--plot", default=None)
    args = ap.parse_args()

    # probe
    try:
        urllib.request.urlopen(f"{args.host}/api/tags", timeout=3)
    except Exception as e:
        print("Ollama not reachable at", args.host, "->", e)
        print("\nInstall from https://ollama.com, then:")
        print("  ollama pull llama3.2:1b && ollama serve")
        print("This demo needs a running Ollama; the sizing.py calculator needs nothing.")
        sys.exit(0)

    base = "The quick brown fox jumps over the lazy dog. "
    print(f"model={args.model}  num_predict={args.num_predict}\n")
    hdr = f"{'prompt_tokens~':>14} {'TTFT_ms':>10} {'avg_ITL_ms':>11} {'decode_tok/s':>13}"
    print(hdr); print("-" * len(hdr))
    rows = []
    for plen in args.prompt_lens:
        prompt = (base * ((plen // 10) + 1))[:plen * 5]  # ~plen tokens-ish
        try:
            ttft, tok_times, meta = gen_stream(args.host, args.model, prompt,
                                               args.num_predict)
        except urllib.error.URLError as e:
            print("request failed:", e); break
        ttft, avg_itl, tok_s = summarize(ttft, tok_times)
        # Ollama reports token counts in ns; prefer them if present
        approx_prompt = meta.get("prompt_eval_count", plen)
        rows.append((approx_prompt, ttft * 1e3, avg_itl, tok_s))
        print(f"{approx_prompt:>14} {ttft*1e3:>10.1f} {avg_itl:>11.2f} {tok_s:>13.1f}")

    print("\nExpected: TTFT rises with prompt length (prefill=compute-bound);")
    print("avg ITL and decode tok/s stay ~flat (decode=memory-bandwidth-bound). kb/10")

    if args.plot and rows:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            xs = [r[0] for r in rows]
            fig, ax = plt.subplots(1, 2, figsize=(11, 4))
            ax[0].plot(xs, [r[1] for r in rows], "o-")
            ax[0].set_xlabel("prompt tokens"); ax[0].set_ylabel("TTFT (ms)")
            ax[0].set_title("Prefill: TTFT vs prompt length")
            ax[1].plot(xs, [r[2] for r in rows], "o-r", label="avg ITL (ms)")
            ax[1].plot(xs, [r[3] for r in rows], "s-g", label="decode tok/s")
            ax[1].set_xlabel("prompt tokens"); ax[1].set_title("Decode: ~flat")
            ax[1].legend()
            fig.tight_layout(); fig.savefig(args.plot, dpi=120)
            print("wrote", args.plot)
        except ImportError:
            print("matplotlib not installed", file=sys.stderr)


if __name__ == "__main__":
    main()
