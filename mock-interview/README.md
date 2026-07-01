# Mock Interview Bank

Practice questions with **model answers**, mapped to the JD. Cover four areas:

1. [Storage systems & Linux internals](./01-storage-systems.md)
2. [AI / LLM inference & KV cache](./02-ai-inference.md)
3. [System design (the headline round)](./03-system-design.md)
4. [Behavioral & narrative](./04-behavioral.md)

## How to use

- **First pass:** cover the answer, speak your response aloud for 60–120 s, then compare.
- **Second pass:** for design questions, whiteboard the diagram before reading.
- Tie every storage answer back to the AI angle and vice-versa — that bridge is your
  differentiator (see [`kb/00`](../kb/00-overview-and-role-map.md)).
- Reference the demos: "I built an io_uring benchmark / KV-offload simulator to reason
  about this quantitatively."

## The 6 things you must be able to whiteboard cold

1. The Linux I/O stack top-to-bottom (kb/01).
2. The io_uring SQ/CQ ring architecture (kb/02).
3. NAND asymmetry → FTL/GC/write-amplification (kb/05).
4. Prefill vs decode (compute- vs memory-bound) and the KV-cache size formula (kb/10).
5. PagedAttention = OS paging for KV; the storage↔KV analogy table (kb/11).
6. PD disaggregation + the memory/storage hierarchy for KV offload (kb/00, 13).
