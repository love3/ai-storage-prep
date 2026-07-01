<script setup>
import { ref, computed, reactive } from 'vue'
import { HashRing, hash32 } from '../sim/ring.js'

const COLORS = ['#5b9cff', '#37d3a8', '#ffd166', '#ef8354', '#a78bfa', '#f472b6', '#4ade80', '#22d3ee']
const N = 3, W = 2, R = 2

const state = reactive({ nodes: ['n1', 'n2', 'n3', 'n4'], down: new Set(), seq: 5 })
const key = ref('user:42')
const bump = ref(0)   // force recompute

const ring = computed(() => {
  bump.value
  const r = new HashRing(48)
  state.nodes.forEach(n => r.addNode(n))
  return r
})
const colorOf = (n) => COLORS[state.nodes.indexOf(n) % COLORS.length]

const replicas = computed(() => ring.value.replicas(key.value, N))
const readAvailable = computed(() =>
  replicas.value.filter(n => !state.down.has(n)).length >= R)
const writeAvailable = computed(() =>
  replicas.value.filter(n => !state.down.has(n)).length >= W)

// load distribution across sample keys
const load = computed(() => {
  bump.value
  const c = {}; state.nodes.forEach(n => c[n] = 0)
  const K = 3000
  for (let i = 0; i < K; i++)
    ring.value.replicas('key-' + i, N).forEach(n => c[n]++)
  const tot = Object.values(c).reduce((a, b) => a + b, 0) || 1
  return state.nodes.map(n => ({ n, pct: 100 * c[n] / tot }))
})

// ring geometry
const R0 = 150, CX = 170, CY = 170
function xy(pos, radius) {
  const a = pos * 2 * Math.PI - Math.PI / 2
  return [CX + radius * Math.cos(a), CY + radius * Math.sin(a)]
}
const ticks = computed(() => ring.value.vnodePositions())
const keyPos = computed(() => (hash32(key.value) >>> 0) / 4294967296)

function addNode() {
  state.seq++
  state.nodes.push('n' + state.seq); bump.value++
}
function removeNode(n) {
  state.nodes = state.nodes.filter(x => x !== n)
  state.down.delete(n); bump.value++
}
function toggleDown(n) {
  state.down.has(n) ? state.down.delete(n) : state.down.add(n); bump.value++
}

// rebalance metric: data moved when adding one node
const rebalance = ref(null)
function measureRebalance() {
  const K = 3000
  const before = []
  for (let i = 0; i < K; i++) before.push(new Set(ring.value.replicas('key-' + i, N)))
  state.seq++; const newNode = 'n' + state.seq
  state.nodes.push(newNode); bump.value++
  let moved = 0
  const r2 = ring.value
  for (let i = 0; i < K; i++) {
    const after = new Set(r2.replicas('key-' + i, N))
    for (const x of after) if (!before[i].has(x)) moved++
  }
  rebalance.value = {
    node: newNode,
    moved: (100 * moved / (K * N)).toFixed(1),
    ideal: (100 / state.nodes.length).toFixed(0),
    naive: (100 * (state.nodes.length - 1) / state.nodes.length).toFixed(0),
  }
}
</script>

<template>
  <div class="panel">
    <h2>Consistent-Hashing Replicated Store</h2>
    <p class="muted">N={{ N }} replicas, W={{ W }}, R={{ R }} (W+R&gt;N ⇒ strong-ish).
      Keys and virtual nodes on a 2³² ring. Mirrors <code>demos/mini-distributed-store</code>.</p>

    <div class="grid2">
      <div>
        <svg :width="CX * 2" :height="CY * 2" style="max-width:100%;">
          <circle :cx="CX" :cy="CY" :r="R0" fill="none" stroke="#2a3550" stroke-width="2" />
          <line v-for="(t, i) in ticks" :key="i"
            :x1="xy(t.pos, R0 - 8)[0]" :y1="xy(t.pos, R0 - 8)[1]"
            :x2="xy(t.pos, R0 + 8)[0]" :y2="xy(t.pos, R0 + 8)[1]"
            :stroke="colorOf(t.node)" stroke-width="2" />
          <!-- key marker -->
          <circle :cx="xy(keyPos, R0)[0]" :cy="xy(keyPos, R0)[1]" r="6" fill="#fff" stroke="#000" />
          <text :x="CX" :y="CY - 6" text-anchor="middle" fill="#e6ebf5" font-size="13">key:</text>
          <text :x="CX" :y="CY + 14" text-anchor="middle" fill="#fff" font-size="13" font-weight="bold">{{ key }}</text>
        </svg>
      </div>

      <div>
        <label class="control" style="margin-bottom:.6rem;">Key
          <input type="text" v-model="key"></label>
        <p>Preference list (replicas clockwise):</p>
        <p>
          <span v-for="(n, i) in replicas" :key="n"
            :style="{ background: colorOf(n), color: '#06101f', padding: '3px 8px', borderRadius: '6px', marginRight: '5px', opacity: state.down.has(n) ? 0.4 : 1 }">
            {{ n }}<span v-if="i === 0"> (primary)</span><span v-if="state.down.has(n)"> ✗</span>
          </span>
        </p>
        <p>
          read quorum: <b :class="readAvailable ? 'kpi good' : 'kpi bad'" style="font-size:1rem;">
            {{ readAvailable ? 'AVAILABLE' : 'UNAVAILABLE' }}</b> ·
          write quorum: <b :class="writeAvailable ? 'kpi good' : 'kpi bad'" style="font-size:1rem;">
            {{ writeAvailable ? 'AVAILABLE' : 'UNAVAILABLE' }}</b>
        </p>
      </div>
    </div>

    <h3 style="margin-bottom:.3rem;">Nodes</h3>
    <div>
      <span v-for="n in state.nodes" :key="n"
        :style="{ display: 'inline-block', border: '1px solid #2a3550', borderRadius: '8px', padding: '6px 10px', margin: '3px', opacity: state.down.has(n) ? 0.45 : 1 }">
        <b :style="{ color: colorOf(n) }">{{ n }}</b>
        <button class="ghost" style="margin-left:6px;padding:2px 6px;" @click="toggleDown(n)">
          {{ state.down.has(n) ? 'revive' : 'kill' }}</button>
        <button class="ghost" style="padding:2px 6px;" @click="removeNode(n)">remove</button>
      </span>
      <button class="act" style="margin-left:6px;" @click="addNode">+ add node</button>
    </div>

    <h3 style="margin-bottom:.3rem;margin-top:1rem;">Load distribution ({{ state.nodes.length }} nodes)</h3>
    <div v-for="l in load" :key="l.n" style="display:flex;align-items:center;gap:.5rem;margin:2px 0;">
      <span style="width:34px;font-size:.85rem;">{{ l.n }}</span>
      <div class="bar" :style="{ width: (l.pct * 2.5) + '%', background: colorOf(l.n) }"></div>
      <span class="muted" style="font-size:.82rem;">{{ l.pct.toFixed(1) }}%</span>
    </div>

    <div style="margin-top:1rem;">
      <button class="act" @click="measureRebalance">Measure rebalance (add a node)</button>
      <span v-if="rebalance" class="muted" style="margin-left:.6rem;">
        added <b>{{ rebalance.node }}</b>: <b class="kpi good" style="font-size:1rem;">{{ rebalance.moved }}%</b>
        of data moved (ideal ~{{ rebalance.ideal }}%) vs naive key-mod-N ~{{ rebalance.naive }}%.
      </span>
    </div>
  </div>
</template>
