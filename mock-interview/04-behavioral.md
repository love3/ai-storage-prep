# Mock Interview · Behavioral & Narrative

> Use **STAR** (Situation, Task, Action, Result). Prepare 4–5 real stories and map them to
> these prompts. Below are frameworks + example scaffolds — fill with your own specifics.

---

### Q1. Why this role / why storage-for-AI?

**Framework:** connect your storage background to the AI-infra bottleneck.

> "My background is in [storage systems / performance engineering / kernel]. What pulls me
> to this role is that LLM inference has turned **memory and storage hierarchy into the
> primary scaling bottleneck** — KV cache is a new caching problem with a brutal latency
> budget that maps directly onto everything I know about page cache, async I/O, NVMe, and
> tiering. I've gone deep on vLLM/SGLang internals and PagedAttention, and I built a
> KV-cache-offload simulator and a raw-io_uring benchmark to reason about the
> prefetch/overlap budget quantitatively. I want to help design the HBM→DRAM→CXL→NVMe path
> that keeps GPUs saturated."

---

### Q2. Tell me about a hard performance problem you solved.

**Scaffold (STAR):**
- **S/T:** a system missed its latency/throughput SLO under load.
- **A:** applied a *method* — defined the metric + representative workload, used USE to find
  the saturated resource, split software vs device time (e.g. blktrace Q2D vs D2C or perf
  flame graphs), formed a hypothesis, changed **one variable**, re-measured vs baseline.
- **R:** quantified improvement (e.g. "p99 from X→Y ms, throughput +Z%"), and — key —
  explain the **root cause** (lock contention / copies / GC jitter / QD too low / NUMA),
  not just the fix. Mention what you'd monitor to prevent regression.

*Pick a story where the bottleneck was non-obvious and data-driven.*

---

### Q3. Describe a time you had to learn a new, deep technical area fast.

**Scaffold:** show a **learning system**: primary sources (papers, kernel docs, specs) →
build a small artifact to test understanding → teach it back. Example: "To ramp on LLM
inference I read the vLLM/PagedAttention and Mooncake papers, then built a KV-offload
simulator and a sizing calculator so I could *derive* the numbers myself rather than
memorize them. Building the artifact exposed the subtleties — e.g. that decode is
memory-bound, so batching and KV byte-size dominate." Ties directly to this prep kit.

---

### Q4. Tell me about a disagreement on a technical decision.

**Framework:** show **professional objectivity** — you argue from data and tradeoffs, stay
respectful, and commit once decided.

> "We disagreed on X vs Y. I laid out the tradeoff explicitly (latency vs throughput / cost
> vs complexity), ran a small benchmark to get real numbers instead of arguing from
> intuition, and we chose based on the SLO that mattered. When the data contradicted my
> initial preference, I changed my position — and I said so."

---

### Q5. A time you drove a decision under uncertainty / influenced without authority.

**Framework (maps to JD R7: tech pre-research & requirement definition):**

> "I had to define requirements for [a new capability] with incomplete information. I
> reduced uncertainty by **quantifying the design space** (back-of-envelope sizing,
> prototypes/simulations), framed the options as clear architecture tradeoffs with the
> numbers attached, and socialized a one-page recommendation with upstream/downstream
> stakeholders. That turned a vague debate into a concrete decision and a roadmap."

*This is exactly the "将前沿技术问题转化为清晰的架构观点、实验方案和产品建议" the JD asks for.*

---

### Q6. Where do you see storage-for-AI going in 2–3 years? (vision question)

**Talking points:**
- **Disaggregation everywhere:** PD-split serving with a **KV-cache pool** as a first-class,
  tiered, distributed data structure (Mooncake trajectory).
- **The GPU as a storage initiator:** GPUDirect Storage becoming standard, and
  **GPU-initiated I/O** (BaM) letting GPUs demand-page KV/embeddings from NVMe.
- **CXL memory pooling** as the DRAM↔SSD tier for KV and for fighting stranded memory.
- **Purpose-built KV SSDs:** read-optimized, predictable-latency, ZNS/FDP QLC.
- **Standards to push:** NVMe (ZNS/FDP, computational storage), CXL 3.0 fabrics, OCP
  datacenter SSD/NIC/DPU specs; **DPU offload** of the storage/network data path.
- **Long-context** driving all of the above — 1M-token KV is a hierarchy problem.

*Close with: "That's why this role is interesting — it's where storage systems, networking,
and AI systems converge, and I want to be building at that intersection."*

---

### Questions to ask THEM (shows seriousness)

- How is KV cache managed today — single-node paging, or a disaggregated pool? What's the
  current bottleneck: HBM capacity, bandwidth, or transfer?
- Are you PD-disaggregated in production yet? What broke first?
- How much of the roadmap is GPUDirect Storage / CXL / GPU-initiated I/O vs software tiering?
- What inference frameworks are in production (vLLM / SGLang / TRT-LLM / in-house)?
- How do storage requirements flow into the hardware/roadmap and standards proposals?
