# Web — Interactive Demos (Vue 3 + Vite → GitHub Pages)

A small Vue 3 app that hosts **client-side** ports of two demos so they run in the
browser with no backend (perfect for GitHub Pages):

- **KV Cache Offload Sim** — the tiered LRU KV-cache simulator (port of
  `demos/kv-cache-offload-sim`), with live sliders for prefix share, session revisit,
  prefetch, and KV dtype.
- **Consistent-Hashing Store** — an SVG ring visualizer (port of
  `demos/mini-distributed-store`): add/kill/remove nodes, inspect a key's replica set and
  quorum availability, watch load balance, and measure rebalance data movement.
- **Overview** — the memory/storage hierarchy diagram to memorize.

## Develop

```bash
npm install
npm run dev        # http://localhost:5173  (base '/ai-storage-prep/')
npm run build      # -> dist/
npm run preview
```

## Deploy

Pushes to `main` that touch `web/**` trigger `.github/workflows/deploy-pages.yml`, which
builds with `BASE_PATH=/ai-storage-prep/` and publishes `web/dist` to GitHub Pages.
Enable it once in **Settings → Pages → Source: GitHub Actions**. The site then lives at
`https://<user>.github.io/ai-storage-prep/`.

> The in-browser sims mirror the Python/JS logic of the CLI demos and reproduce the same
> qualitative numbers (recompute ~54% for HBM-only vs ~0% tiered; ~20% data moved on
> rebalance). They are teaching models — see the demo folders for the authoritative
> implementations.

## Structure
- `src/App.vue` — tabs + overview
- `src/components/HierarchyDiagram.vue` — the hierarchy chart
- `src/components/KvCacheSim.vue` — KV cache simulator UI
- `src/components/HashRingViz.vue` — consistent-hashing ring UI
- `src/sim/kvsim.js`, `src/sim/ring.js` — the ported simulation engines
