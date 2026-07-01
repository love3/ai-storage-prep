<script setup>
const tiers = [
  { name: 'GPU HBM (HBM3e)', cap: '80–192 GB', bw: '3–8 TB/s', lat: '~100 ns', role: 'weights + active KV', w: 100, color: '#5b9cff' },
  { name: 'CPU DRAM (DDR5)', cap: '1–4 TB', bw: '200–500 GB/s', lat: '~100 ns', role: 'KV offload tier 1', w: 78, color: '#37d3a8' },
  { name: 'CXL memory', cap: '10s TB', bw: '50–100 GB/s', lat: '~300 ns', role: 'memory pool / KV tier', w: 58, color: '#ffd166' },
  { name: 'NVMe SSD (PCIe5)', cap: '10s–100s TB', bw: '1–14 GB/s', lat: '10–100 µs', role: 'KV tier 2 / prefix cache', w: 40, color: '#ef8354' },
  { name: 'Remote / object', cap: 'PB', bw: 'network-bound', lat: 'ms', role: 'cold cache / model store', w: 24, color: '#a78bfa' },
]
</script>

<template>
  <div class="panel">
    <h2>The one diagram: memory/storage hierarchy for LLM inference</h2>
    <p class="muted">Each tier down is ~10–100× cheaper per GB but ~10–100× slower. KV cache
      offload and PD disaggregation hide that latency with prefetch, async I/O, and overlap.</p>
    <div v-for="t in tiers" :key="t.name" style="margin:.5rem 0;">
      <div style="display:flex;align-items:center;gap:.6rem;">
        <div class="bar" :style="{ width: t.w + '%', background: t.color }"></div>
        <b>{{ t.name }}</b>
      </div>
      <div class="muted" style="font-size:.82rem;margin-left:.2rem;">
        {{ t.cap }} · {{ t.bw }} · {{ t.lat }} — <i>{{ t.role }}</i>
      </div>
    </div>
    <p class="muted" style="font-size:.82rem;margin-top:.8rem;">
      Links between tiers: NVLink / PCIe5 x16 (~64 GB/s), CXL, PCIe5 x4 NVMe (~14 GB/s),
      RDMA 400G (~50 GB/s). Bar width ∝ log-ish bandwidth.
    </p>
  </div>
</template>
