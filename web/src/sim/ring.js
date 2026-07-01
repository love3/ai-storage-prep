// Client-side consistent hash ring (see kb/07 & demos/mini-distributed-store).

// 32-bit string hash (xmur3-ish) -> position on a 2^32 ring.
function hash32(str) {
  let h = 1779033703 ^ str.length
  for (let i = 0; i < str.length; i++) {
    h = Math.imul(h ^ str.charCodeAt(i), 3432918353)
    h = (h << 13) | (h >>> 19)
  }
  h = Math.imul(h ^ (h >>> 16), 2246822507)
  h = Math.imul(h ^ (h >>> 13), 3266489909)
  return (h ^= h >>> 16) >>> 0
}

export class HashRing {
  constructor(vnodes = 64) {
    this.vnodes = vnodes
    this.ring = new Map()       // pos -> node
    this.sorted = []            // sorted positions
    this.nodes = new Set()
  }
  _insert(pos, node) {
    this.ring.set(pos, node)
    let lo = 0, hi = this.sorted.length
    while (lo < hi) { const m = (lo + hi) >> 1; if (this.sorted[m] < pos) lo = m + 1; else hi = m }
    this.sorted.splice(lo, 0, pos)
  }
  addNode(node) {
    if (this.nodes.has(node)) return
    this.nodes.add(node)
    for (let i = 0; i < this.vnodes; i++) this._insert(hash32(`${node}#${i}`), node)
  }
  removeNode(node) {
    if (!this.nodes.has(node)) return
    this.nodes.delete(node)
    for (let i = 0; i < this.vnodes; i++) {
      const pos = hash32(`${node}#${i}`)
      this.ring.delete(pos)
      const idx = this.sorted.indexOf(pos)
      if (idx >= 0) this.sorted.splice(idx, 1)
    }
  }
  replicas(key, n) {
    if (!this.sorted.length) return []
    const pos = hash32(key)
    let lo = 0, hi = this.sorted.length
    while (lo < hi) { const m = (lo + hi) >> 1; if (this.sorted[m] <= pos) lo = m + 1; else hi = m }
    let idx = lo % this.sorted.length
    const out = [], seen = new Set()
    for (let c = 0; c < this.sorted.length && out.length < n; c++) {
      const node = this.ring.get(this.sorted[idx])
      if (!seen.has(node)) { seen.add(node); out.push(node) }
      idx = (idx + 1) % this.sorted.length
    }
    return out
  }
  // vnode positions normalized to [0,1) for drawing
  vnodePositions() {
    return this.sorted.map(p => ({ pos: p / 4294967296, node: this.ring.get(p) }))
  }
}

export { hash32 }
