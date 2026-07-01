<script setup>
import { ref, computed, watchEffect } from 'vue'
import { MODELS, TIERS, blockBytes, makeScenario, buildStream, runSim } from '../sim/kvsim.js'

const model = ref('llama-3-8b')
const requests = ref(300)
const share = ref(0.6)
const revisit = ref(0.5)
const prefetch = ref(0)
const kvBytes = ref(2)

const results = ref([])
const meta = ref({})

function human(n) {
  const u = ['B', 'KiB', 'MiB', 'GiB', 'TiB']; let i = 0
  while (Math.abs(n) >= 1024 && i < u.length - 1) { n /= 1024; i++ }
  return n.toFixed(1) + ' ' + u[i]
}

watchEffect(() => {
  const turns = makeScenario({ requests: requests.value, share: share.value,
    revisit: revisit.value, seed: 1 })
  const blk = blockBytes(model.value, kvBytes.value)
  const sNo = buildStream(turns, false)
  const sPc = buildStream(turns, true)
  const configs = [
    ['hbm_only (evict+recompute)', 'hbm_only', sNo],
    ['tiered (spill to SSD)', 'tiered', sNo],
    ['tiered + prefix cache', 'tiered', sPc],
  ]
  results.value = configs.map(([label, strat, stream]) => {
    const r = runSim(stream, blk, strat, prefetch.value)
    return { label, ...r }
  })
  meta.value = { blk, hotAll: new Set(sNo.map(x => x[0])).size * blk }
})

const tierNames = TIERS.map(t => t.name)
function seg(r, name) {
  const idx = tierNames.indexOf(name)
  return 100 * r.hits[idx] / Math.max(1, r.nRefs)
}
function recPct(r) { return 100 * r.recompute / Math.max(1, r.nRefs) }
</script>

<template>
  <div class="panel">
    <h2>KV Cache Tiered-Offload Simulator</h2>
    <p class="muted">Multi-turn serving workload (shared prefixes + resumed sessions).
      Compare evict-and-recompute vs spilling cold KV to DRAM/CXL/SSD, plus prefix caching
      and prefetch. Mirrors <code>demos/kv-cache-offload-sim</code>.</p>

    <div class="controls">
      <label class="control">Model
        <select v-model="model"><option v-for="m in Object.keys(MODELS)" :key="m">{{ m }}</option></select>
      </label>
      <label class="control">Requests: {{ requests }}
        <input type="range" min="100" max="800" step="50" v-model.number="requests"></label>
      <label class="control">Prefix share: {{ share.toFixed(2) }}
        <input type="range" min="0" max="1" step="0.05" v-model.number="share"></label>
      <label class="control">Session revisit: {{ revisit.toFixed(2) }}
        <input type="range" min="0" max="0.9" step="0.05" v-model.number="revisit"></label>
      <label class="control">Prefetch hide: {{ prefetch.toFixed(2) }}
        <input type="range" min="0" max="0.95" step="0.05" v-model.number="prefetch"></label>
      <label class="control">KV dtype
        <select v-model.number="kvBytes">
          <option :value="2">FP16 (2B)</option><option :value="1">FP8/INT8 (1B)</option>
          <option :value="0.5">INT4 (0.5B)</option></select></label>
    </div>

    <p class="muted" style="font-size:.82rem;">
      block size = {{ human(meta.blk || 0) }} ·
      KV to keep <b>all</b> hot in HBM = {{ human(meta.hotAll || 0) }} (HBM demo cap 0.5 GiB)
    </p>

    <table>
      <thead><tr><th>strategy</th><th>avg re-access</th><th>p99</th>
        <th>recompute</th><th>where KV reads are served</th></tr></thead>
      <tbody>
        <tr v-for="r in results" :key="r.label">
          <td>{{ r.label }}</td>
          <td :class="['kpi', r.avg < 100 ? 'good' : 'bad']" style="font-size:1rem;">{{ r.avg.toFixed(1) }} µs</td>
          <td>{{ r.p99.toFixed(0) }} µs</td>
          <td :class="recPct(r) > 5 ? 'kpi bad' : ''" style="font-size:1rem;">{{ recPct(r).toFixed(1) }}%</td>
          <td>
            <div style="display:flex;height:20px;border-radius:4px;overflow:hidden;min-width:200px;">
              <div v-for="t in TIERS" :key="t.name" :style="{ width: seg(r, t.name) + '%', background: t.color }"
                :title="t.name + ' ' + seg(r, t.name).toFixed(1) + '%'"></div>
              <div :style="{ width: recPct(r) + '%', background: '#555' }" title="recompute"></div>
            </div>
          </td>
        </tr>
      </tbody>
    </table>

    <div class="legend" style="margin-top:.6rem;">
      <span v-for="t in TIERS" :key="t.name"><span class="swatch" :style="{ background: t.color }"></span>{{ t.name }}</span>
      <span><span class="swatch" style="background:#555"></span>recompute</span>
    </div>

    <p class="muted" style="font-size:.82rem;margin-top:.8rem;">
      Try it: drop <b>prefetch</b> to 0 and raise <b>revisit</b> — hbm_only's recompute
      explodes while tiered stays cheap. Raise <b>prefetch</b> to hide SSD latency. Switch
      KV dtype to <b>FP8</b> to shrink blocks so more fits in fast tiers.
    </p>
  </div>
</template>
