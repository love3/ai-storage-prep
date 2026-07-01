// Client-side port of demos/kv-cache-offload-sim (see kb/11).
// A tiered LRU KV-cache simulator: HBM -> DRAM -> CXL -> SSD.

export const MODELS = {
  'llama-3-8b':      { layers: 32, kvHeads: 8,  headDim: 128 },
  'llama-3-70b':     { layers: 80, kvHeads: 8,  headDim: 128 },
  'llama-2-13b-mha': { layers: 40, kvHeads: 40, headDim: 128 },
}

// demo-scaled capacities (bytes); latencies are order-of-magnitude real (us)
export const TIERS = [
  { name: 'HBM',  cap: 0.5 * 2 ** 30, lat: 0.1,  color: '#5b9cff' },
  { name: 'DRAM', cap: 2   * 2 ** 30, lat: 0.2,  color: '#37d3a8' },
  { name: 'CXL',  cap: 4   * 2 ** 30, lat: 0.4,  color: '#ffd166' },
  { name: 'SSD',  cap: 64  * 2 ** 30, lat: 80.0, color: '#ef8354' },
]
const RECOMPUTE_US = 2000
const BLOCK_TOKENS = 16

export function blockBytes(model, kvBytes) {
  const m = MODELS[model]
  return 2 * m.layers * m.kvHeads * m.headDim * kvBytes * BLOCK_TOKENS
}

// deterministic PRNG
function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}
const ri = (rng, lo, hi) => lo + Math.floor(rng() * (hi - lo + 1))

export function makeScenario({ requests = 300, prefixes = 8, share = 0.6,
  sessions = 50, revisit = 0.5, seed = 1 }) {
  const rng = mulberry32(seed)
  const prefixLen = Array.from({ length: Math.max(1, prefixes) }, () => ri(rng, 256, 2048))
  const ctx = {}, spref = {}, live = []
  const turns = []
  for (let i = 0; i < requests; i++) {
    let sid, cont
    if (live.length && rng() < revisit) { sid = live[ri(rng, 0, live.length - 1)]; cont = true }
    else {
      sid = Object.keys(ctx).length
      if (sid >= sessions && live.length) { sid = live[ri(rng, 0, live.length - 1)]; cont = true }
      else { cont = false; ctx[sid] = 0; live.push(sid); spref[sid] = (rng() < share && prefixes > 0) ? ri(rng, 0, prefixes - 1) : -1 }
    }
    const pid = spref[sid] ?? -1
    const plen = pid >= 0 ? prefixLen[pid] : ri(rng, 256, 2048)
    const hist = ctx[sid] || 0
    const nt = ri(rng, 32, 512), dec = ri(rng, 64, 512)
    turns.push({ req: i, sid, pid, plen, hist, nt, dec })
    ctx[sid] = hist + nt + dec
  }
  return turns
}

const nb = (t) => Math.ceil(t / BLOCK_TOKENS)

export function buildStream(turns, prefixCache = true, sub = 6) {
  const s = []
  for (const t of turns) {
    const seq = []
    for (let b = 0; b < nb(t.plen); b++) {
      const id = (prefixCache && t.pid >= 0) ? `P${t.pid}:${b}`
        : (t.pid >= 0 ? `S${t.sid}:PX${b}` : `R${t.req}:P${b}`)
      seq.push(id); s.push([id, true])
    }
    for (let b = 0; b < nb(t.hist); b++) { const id = `S${t.sid}:H${b}`; seq.push(id); s.push([id, false]) }
    const base = nb(t.hist)
    for (let b = 0; b < nb(t.nt); b++) { const id = `S${t.sid}:H${base + b}`; seq.push(id); s.push([id, false]) }
    const nd = nb(t.dec), step = Math.max(1, Math.floor(nd / Math.max(1, sub)))
    const gbase = base + nb(t.nt); let g = 0
    for (let d = 0; d < nd; d += step) {
      const id = `S${t.sid}:H${gbase + g}`; g++; seq.push(id)
      const ss = Math.max(1, Math.floor(seq.length / 12))
      for (let k = 0; k < seq.length; k += ss) s.push([seq[k], false])
    }
  }
  return s
}

// strategy: 'hbm_only' | 'tiered' ; prefetch in [0,1)
export function runSim(stream, blkBytes, strategy, prefetch = 0) {
  const nTiers = strategy === 'hbm_only' ? 1 : TIERS.length
  const caps = TIERS.slice(0, nTiers).map(t => Math.max(1, Math.floor(t.cap / blkBytes)))
  const maps = Array.from({ length: nTiers }, () => new Map())
  const loc = new Map(), ever = new Set()
  const hits = TIERS.map(() => 0)
  let recompute = 0, prefixHits = 0, populate = 0
  const lat = []
  const hbmLat = TIERS[0].lat

  const latFor = (ti) => {
    let l = TIERS[ti].lat
    if (ti >= 2 && prefetch > 0) l = hbmLat + (l - hbmLat) * (1 - prefetch)
    return l
  }
  const cascade = (from) => {
    let ti = from
    while (ti < nTiers && maps[ti].size > caps[ti]) {
      const old = maps[ti].keys().next().value
      maps[ti].delete(old)
      if (ti + 1 < nTiers) { maps[ti + 1].set(old, 1); loc.set(old, ti + 1); ti++ }
      else { loc.delete(old); break }
    }
  }
  const insHbm = (id) => { maps[0].set(id, 1); loc.set(id, 0); if (maps[0].size > caps[0]) cascade(0) }

  for (const [id, isPrefix] of stream) {
    if (loc.has(id)) {
      const ti = loc.get(id); hits[ti]++; lat.push(latFor(ti)); if (isPrefix) prefixHits++
      maps[ti].delete(id); insHbm(id)
    } else if (ever.has(id)) { recompute++; lat.push(RECOMPUTE_US); insHbm(id) }
    else { populate++; ever.add(id); insHbm(id) }
  }
  lat.sort((a, b) => a - b)
  const n = lat.length
  const avg = n ? lat.reduce((a, b) => a + b, 0) / n : 0
  const p99 = n ? lat[Math.min(n - 1, Math.floor(0.99 * n))] : 0
  const distinct = new Set(stream.map(x => x[0])).size
  return { strategy, nRefs: n, populate, hits, recompute, prefixHits, avg, p99, caps, distinct }
}
