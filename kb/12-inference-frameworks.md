# 12 · Inference Frameworks (vLLM, SGLang, llama.cpp, TensorRT-LLM, Ollama, KTransformers)

> JD Q8 requires deploy + tune of at least one; R5 requires reasoning about each
> framework's compute/VRAM/DRAM/storage needs. Know what each is *for* and its KV/offload story.

## 1. The landscape at a glance

| Framework | Language/target | Superpower | KV / offload story | Best for |
|-----------|-----------------|------------|--------------------|----------|
| **vLLM** | Python/CUDA (also ROCm, CPU) | PagedAttention + continuous batching | paging, APC prefix cache, CPU offload, KV connector, PD disagg | high-throughput GPU serving |
| **SGLang** | Python/CUDA | RadixAttention prefix cache + structured programs | radix prefix tree, **HiCache** GPU/CPU/SSD tiering, PD disagg | agents/RAG/chat, heavy prefix reuse |
| **TensorRT-LLM** | C++/CUDA (NVIDIA only) | max perf via compiled kernels | paged KV, quant (FP8/INT4), in-flight batching | lowest latency on NVIDIA, production |
| **llama.cpp** | C/C++ (GGUF) | runs anywhere (CPU/Metal/CUDA/Vulkan) | mmap weights, GGUF quant, partial GPU offload | local/edge, Macs, CPU, AI PC |
| **Ollama** | Go wrapper over llama.cpp | dead-simple UX, model registry | inherits llama.cpp | desktop/dev, quick demos |
| **KTransformers** | Python/CUDA+CPU | **GPU+CPU heterogeneous** MoE offload | offload expert/weights to CPU/DRAM, keep hot on GPU | huge MoE (e.g. DeepSeek) on limited VRAM |
| **TGI** | Rust/Python | HF-integrated serving | paged KV, continuous batching | HF ecosystem |

## 2. vLLM (the reference high-throughput server)

- **PagedAttention** (KB 11) + **continuous batching** = its core. High GPU utilization
  and throughput.
- **OpenAI-compatible server** (`vllm serve <model>`), tensor/pipeline parallel across
  GPUs, quantization (AWQ/GPTQ/FP8), speculative decoding, **automatic prefix caching**,
  **chunked prefill** (split long prefills to interleave with decode and cap TTFT
  interference), **CPU KV offload**, **KV connector** interface (LMCache, disaggregated).
- **Resource reasoning:** VRAM = weights + KV cache + activations + CUDA overhead. vLLM's
  `gpu_memory_utilization` reserves a fraction; the rest of KV space bounds max batch /
  context. When KV won't fit → enable offload / more GPUs / quantize.
- Deploy: `vllm serve meta-llama/Llama-3.1-8B-Instruct --max-model-len 8192
  --gpu-memory-utilization 0.9 --enable-prefix-caching`.

## 3. SGLang

- **RadixAttention**: automatic, tree-structured prefix cache (KB 11) → excellent when
  many requests share prefixes (agents, few-shot, RAG). LRU eviction across the tree.
- **HiCache**: hierarchical KV cache across **GPU → CPU DRAM → SSD** with prefetch — the
  most storage-relevant feature; directly the JD's tiered offload.
- Structured generation / a frontend DSL for controlling multi-step LLM programs.
- Also supports PD disaggregation and speculative decoding.

## 4. TensorRT-LLM

- Compiles model into optimized CUDA/TensorRT engines (fused kernels, FP8 on Hopper,
  INT4/INT8, custom attention) → **lowest latency & highest efficiency on NVIDIA**.
- **In-flight batching**, **paged KV cache**, quantization toolkit.
- Cost: build/compile step per model+config+GPU; less flexible than vLLM.
- Often paired with **Triton Inference Server** for production deployment.

## 5. llama.cpp & Ollama (cross-platform / edge — your demo target)

- **llama.cpp**: pure C/C++, no Python/CUDA required. Backends: CPU (AVX/NEON), **Apple
  Metal**, CUDA, Vulkan, ROCm. Uses **GGUF** files with many quantization levels
  (Q4_K_M, Q5_K_M, Q8_0, ...). **mmap**s weights (page cache does the loading!),
  supports partial **GPU offload** (`-ngl N` layers on GPU, rest on CPU).
- **Ollama**: friendly wrapper (`ollama run llama3.2`), model library, REST API. Great
  for demos and AI-PC/edge scenarios.
- **Storage relevance:** on edge/CPU, weight *loading* (mmap from SSD) and *KV in DRAM*
  dominate; quantization trades quality for footprint; the page cache is your friend.
  Perfect to demonstrate "LLM on AI PC / edge" (JD R4).

## 6. KTransformers (heterogeneous GPU+CPU)

- Targets running **very large MoE models** (e.g. DeepSeek-V2/V3, 100s of GB) on limited
  VRAM by keeping **hot/attention weights on GPU** and **offloading experts/cold weights
  to CPU DRAM**, using clever CPU kernels + selective expert loading.
- Directly embodies "memory pooling / heterogeneous offload" — a great talking point for
  the memory-hierarchy theme.

## 7. How to compare / choose (interview framing)

- **Max GPU throughput, many users** → vLLM or TensorRT-LLM.
- **Heavy shared prefixes / agents / RAG** → SGLang (RadixAttention) or vLLM APC.
- **Lowest latency on NVIDIA, willing to compile** → TensorRT-LLM (+Triton).
- **Local / Mac / CPU / edge / AI PC** → llama.cpp / Ollama.
- **Huge MoE on small VRAM** → KTransformers.
- **Cross-instance/global KV offload** → LMCache / Mooncake / SGLang HiCache.

## 8. Resource/needs reasoning table (JD R5 — "analyze compute/VRAM/DRAM/storage needs")

| Phase / need | Compute | VRAM (HBM) | DRAM | Storage |
|--------------|---------|------------|------|---------|
| Load weights | — | weights (or partial) | mmap cache | model files (GB–100s GB) |
| Prefill | high (GEMM) | KV grows | offload target | prefix cache source |
| Decode | low, mem-BW-bound | weights+KV read each step | KV offload tier | KV tier / prefix cache |
| Long context | quadratic prefill | KV explodes | tier 1 offload | tier 2 offload |
| MoE | expert GEMMs | hot experts | cold experts (KTrans) | expert weights |

Being able to fill this in per framework/model is exactly what R5 asks.

## 9. Interview-ready talking points

- "vLLM = PagedAttention + continuous batching for throughput; SGLang = RadixAttention
  prefix tree + HiCache GPU/CPU/SSD tiering; TensorRT-LLM = compiled max-perf on NVIDIA;
  llama.cpp/Ollama = run anywhere for edge/AI-PC; KTransformers = GPU+CPU heterogeneous
  for giant MoE."
- "VRAM budget = weights + KV cache + activations + overhead; when KV outgrows HBM you
  quantize it, page it, offload it (CPU/SSD via KV connector / HiCache / LMCache), or add
  GPUs."
- "For heavy prefix reuse I'd pick SGLang RadixAttention or vLLM automatic prefix caching;
  chunked prefill caps TTFT interference from long prompts."
- "For an AI-PC/edge demo I use llama.cpp/Ollama with GGUF quant and partial GPU offload;
  there weight loading (mmap from SSD) and KV in DRAM dominate the storage picture."
