# Demo 3 · LLM Inference Profiling & Sizing

**What it shows:** how to reason quantitatively about an LLM's **compute / VRAM / DRAM /
storage** needs (JD R5) and how to *measure* the **prefill (compute-bound) vs decode
(memory-bandwidth-bound)** split (JD Q7, [`kb/10`](../../kb/10-transformer-inference-basics.md)).

Two tools:

## 1. `sizing.py` — the roofline / sizing calculator (runs anywhere, no GPU)

Given a model + GPU preset, it computes weights, KV cache per token/seq/batch, how much
context×batch fits in HBM, prefill compute time, decode throughput, and the roofline
crossover.

```bash
python3 sizing.py --model llama-3-8b  --gpu h100-80g
python3 sizing.py --model llama-3-70b --gpu a100-80g --ctx 8192 --batch 32
python3 sizing.py --model llama-3-8b  --gpu h100-80g --kv-bytes 1   # FP8 KV cache
python3 sizing.py --model llama-3-70b --gpu a100-40g               # shows it won't fit
```

Sample (llama-3-8b on H100-80G): weights 14.9 GiB, **KV 128 KiB/token**, ~130 concurrent
4K-context sequences fit in HBM, decode step ≈ 7.3 ms reading 22.9 GiB (weights + KV)
per step. Change `--kv-bytes 1` and watch KV pressure halve — the quantization lever
from [`kb/15`](../../kb/15-quantization-optimization.md).

Use it in the interview to *derive product requirements*: "at ctx=128K the KV cache is
X GB/seq, so N concurrent long sessions need Y TB across DRAM/CXL/SSD" — exactly the
"推导产品核心需求" the JD asks for.

## 2. `profile_ollama.py` — measure real prefill vs decode (cross-platform)

Drives a local **Ollama** server and measures **TTFT vs prompt length** (prefill) and
**inter-token latency / decode tok/s** (decode).

```bash
# https://ollama.com  (macOS + Linux)
ollama pull llama3.2:1b
python3 profile_ollama.py --model llama3.2:1b --plot ollama.png
```

Expected pattern (the whole point): **TTFT rises with prompt length** (prefill compute),
while **avg ITL and decode tok/s stay ~flat** (decode is memory-bound, prompt-length
independent). If Ollama isn't running it prints setup instructions and exits cleanly —
`sizing.py` needs nothing.

## 3. Profiling a real GPU stack (vLLM / TensorRT-LLM) — notes to speak to

vLLM needs a CUDA GPU, so here's the *method* (see [`kb/12`](../../kb/12-inference-frameworks.md)):

```bash
pip install vllm
vllm serve meta-llama/Llama-3.1-8B-Instruct \
    --max-model-len 8192 --gpu-memory-utilization 0.9 --enable-prefix-caching

# throughput / latency benchmark shipped with vLLM:
python -m vllm.entrypoints.openai.api_server ...   # or:
python benchmarks/benchmark_serving.py --model ... --dataset sharegpt \
    --request-rate 8 --num-prompts 1000
```

What to look at and *why*:
- **`nvidia-smi dmon` / DCGM**: SM utilization, HBM bandwidth utilization, memory used.
  Decode should be **memory-bandwidth-bound** (high mem BW %, moderate SM %).
- **Nsight Systems (`nsys`)**: timeline of prefill vs decode kernels, overlap, gaps.
- **vLLM metrics** (`/metrics`): running/waiting requests, **KV cache usage %**,
  prefix-cache hit rate, TTFT and TPOT histograms, preemptions (KV eviction).
- Turn on `--enable-prefix-caching` and re-run a workload with shared system prompts →
  watch TTFT drop and prefix-cache hit rate rise (kb/11).
- Sweep `--max-num-seqs` / batch → find where KV cache % saturates and preemptions start
  → that's your HBM KV ceiling; beyond it you offload/quantize/disaggregate.

## Files
- `sizing.py` — model×GPU sizing + roofline (stdlib only)
- `profile_ollama.py` — real TTFT/ITL measurement via Ollama (stdlib only)
- `requirements.txt` — matplotlib only (optional, for `--plot`)

> The calculators use rounded public model geometries and vendor GPU specs; treat the
> numbers as order-of-magnitude for reasoning, not datasheet-exact.
