<script setup>
import { ref } from 'vue'
import HierarchyDiagram from './components/HierarchyDiagram.vue'
import KvCacheSim from './components/KvCacheSim.vue'
import HashRingViz from './components/HashRingViz.vue'

const tab = ref('overview')
const tabs = [
  ['overview', 'Overview'],
  ['kv', 'KV Cache Offload Sim'],
  ['ring', 'Consistent-Hashing Store'],
]
const repo = 'https://github.com/love3/ai-storage-prep'
</script>

<template>
  <div class="wrap">
    <header>
      <h1>AI Storage Expert — Interactive Prep</h1>
      <p>Where <b>distributed / low-level storage</b> meets <b>LLM inference infrastructure</b>.
        Two runnable simulators from the prep kit, plus the one diagram to memorize.</p>
    </header>

    <div class="tabs">
      <button v-for="[k, label] in tabs" :key="k"
        :class="{ active: tab === k }" @click="tab = k">{{ label }}</button>
    </div>

    <section v-show="tab === 'overview'">
      <div class="panel">
        <h2>The thesis</h2>
        <p>Modern LLM serving is bottlenecked less by FLOPs than by <b>memory capacity,
          bandwidth, and data movement</b>. <b>KV cache</b> is the new hot data set, and the
          job is to design the <b>HBM → DRAM → CXL → NVMe SSD</b> hierarchy (and the RDMA
          fabric) that keeps GPUs saturated. Storage systems skills — page cache, async I/O,
          NVMe, tiering, consistent hashing — map directly onto KV cache offload, prefix
          caching, and prefill/decode disaggregation.</p>
      </div>
      <HierarchyDiagram />
      <div class="panel">
        <h2>Explore</h2>
        <ul>
          <li><b>KV Cache Offload Sim</b> — watch tiering turn recompute misses into cheap
            SSD/CXL readbacks, and prefetch hide the latency.</li>
          <li><b>Consistent-Hashing Store</b> — add/kill nodes and see load balance,
            replication, and minimal data movement (the basis of a distributed KV pool).</li>
          <li>Full knowledge base, mock interviews, and the Python/C source for these demos
            live in the <a :href="repo">GitHub repo</a>.</li>
        </ul>
      </div>
    </section>

    <section v-show="tab === 'kv'"><KvCacheSim /></section>
    <section v-show="tab === 'ring'"><HashRingViz /></section>

    <footer>
      Study material for interview prep · numbers are order-of-magnitude teaching values ·
      <a :href="repo">source on GitHub</a>
    </footer>
  </div>
</template>
