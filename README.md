# AI Storage Expert — Interview Prep Kit

Preparation material for a **Storage AI Expert (AI存储专家)** role that sits at the
intersection of **distributed / low-level storage systems** and **LLM inference
infrastructure** (KV cache, PD disaggregation, GPU Direct Storage, etc.).

The original job description lives in [`JD.md`](./JD.md).

## What's inside

| Area | Path | Description |
|------|------|-------------|
| 🗺️ Role & skills map | [`kb/00-overview-and-role-map.md`](./kb/00-overview-and-role-map.md) | JD decomposition → skill matrix → study plan |
| 📚 Knowledge base | [`kb/`](./kb/) | 15 deep-dive notes covering the full stack |
| 🧪 Demo projects | [`demos/`](./demos/) | 4 runnable projects (Linux + macOS) |
| 🎤 Mock interviews | [`mock-interview/`](./mock-interview/) | Q&A with model answers |
| 🌐 Web site | [`web/`](./web/) | Vue site with interactive demos (GitHub Pages) |

## Knowledge base index

**Storage systems**
1. [Linux I/O stack end-to-end](./kb/01-linux-io-stack.md)
2. [Async I/O: io_uring, libaio, POSIX AIO](./kb/02-async-io-iouring-libaio.md)
3. [Coroutines & high-concurrency models](./kb/03-coroutines-concurrency.md)
4. [Block devices, page cache, I/O schedulers](./kb/04-block-page-cache-scheduler.md)
5. [SSD / NAND / FTL internals](./kb/05-ssd-nand-ftl-internals.md)
6. [NVMe & PCIe](./kb/06-nvme-pcie.md)
7. [Distributed storage & Ceph](./kb/07-distributed-storage-ceph.md)
8. [Storage networking: RDMA, TCP, kernel bypass](./kb/08-storage-networking-rdma.md)
9. [Performance tuning: fio, SPDK, methodology](./kb/09-performance-tuning-fio-spdk.md)

**AI / LLM inference**
10. [Transformer & LLM inference basics](./kb/10-transformer-inference-basics.md)
11. [KV cache: lifecycle, reuse, offload, tiering](./kb/11-kv-cache-management.md)
12. [Inference frameworks (vLLM, SGLang, llama.cpp, ...)](./kb/12-inference-frameworks.md)
13. [PD disaggregation & long-context inference](./kb/13-pd-disaggregation-long-context.md)
14. [GPU Direct Storage, GPU-Initiated Storage, CXL](./kb/14-gds-cxl-emerging.md)
15. [Quantization & inference optimization](./kb/15-quantization-optimization.md)

## Demo projects

| Demo | Stack | Runs on | Pages? |
|------|-------|---------|--------|
| [KV Cache offload simulator](./demos/kv-cache-offload-sim/) | FastAPI + Vue | Linux/macOS | ✅ (client sim) |
| [Async I/O benchmark](./demos/async-io-bench/) | C + Python | Linux (uring), macOS (fallback) | results only |
| [LLM inference profiling](./demos/llm-inference-profiling/) | Python + llama.cpp/Ollama | Linux/macOS | notes |
| [Mini distributed store](./demos/mini-distributed-store/) | FastAPI + Vue | Linux/macOS | ✅ (client sim) |

## Quick start

```bash
# KB is plain markdown — just read it.

# Run a demo (example: mini distributed store)
cd demos/mini-distributed-store
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
./run.sh

# Build the web site locally
cd web
npm install
npm run dev
```

## How to use this kit

1. Start with [`kb/00-overview-and-role-map.md`](./kb/00-overview-and-role-map.md) to see the skill map and a 2-week study plan.
2. Read KB notes; each ends with **interview-ready talking points**.
3. Run the demos and be ready to *walk through the code and the numbers*.
4. Drill with [`mock-interview/`](./mock-interview/).

> All content is study material written for interview prep; verify specifics against
> primary sources (kernel docs, vLLM/SGLang docs, NVMe/CXL specs) before quoting numbers.
