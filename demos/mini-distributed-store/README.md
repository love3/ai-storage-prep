# Demo 4 · Mini Distributed KV Store (consistent hashing + replication + quorum)

**What it shows:** the data-plane of a Dynamo/Cassandra/Ceph-style distributed store from
[`kb/07`](../../kb/07-distributed-storage-ceph.md) — **consistent hashing with virtual
nodes**, **N-way replication**, **tunable W/R quorums** (W+R>N ⇒ strong-ish consistency),
**availability under node failure**, **read-repair**, and **minimal data movement on
rebalance**. The AI tie-in: this is exactly the machinery a **distributed KV-cache pool**
(Mooncake-style, [`kb/13`](../../kb/13-pd-disaggregation-long-context.md)) reuses.

## Run the narrated walkthrough (no dependencies)

```bash
python3 demo.py
```

It demonstrates, with numbers:

| Step | Result on default run |
|------|-----------------------|
| Load balance (vnodes) | ~25% of replicas per node across 4 nodes |
| Kill primary of a key | `GET` still succeeds via replicas (quorum met) |
| 2 replicas down | `PUT` correctly **fails** W=2 (quorum enforced) |
| Read-repair | stale replica auto-updated to newest version on read |
| **Add a node (rebalance)** | **~20% of data moves** (ideal 1/nodes) vs **~80%** for naive `key % nodecount` |

That last row is the headline: **consistent hashing moves ~1/N of the data on membership
change, not everything** — the property that makes elastic scaling and failure recovery
cheap.

## Interactive dashboard (FastAPI)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload      # open http://127.0.0.1:8000/
```

The dashboard lets you PUT/GET keys, see each key's **preference list** (replica set),
**kill/revive/add/remove nodes**, and watch key counts rebalance and reads survive
failures live. (A client-side consistent-hashing *ring visualizer* is also in the
[web site](../../web) for GitHub Pages.)

## Design notes (be ready to defend)

- **Ring**: keys and nodes hashed onto a 2³² ring (md5); a key's replicas are the next
  `N` distinct **physical** nodes clockwise. **Virtual nodes** (128/node) smooth load and
  minimize movement — same idea as Cassandra vnodes / Ceph CRUSH weights.
- **Quorum**: `put` needs `W` acks, `get` needs `R` responses. `W+R>N` ⇒ read and write
  quorums overlap ⇒ a read sees the latest acked write (strong-ish; ignoring concurrent
  writes / clock skew — real systems add vector clocks or leaders, kb/07).
- **Versions + read-repair**: each value carries a version; reads take the max and push it
  back to stale replicas. A simplification of anti-entropy (Merkle trees / hinted handoff).
- **Failure**: a down node isn't written/read; availability holds as long as ≥W (writes)
  or ≥R (reads) replicas are up. This is the CAP/PACELC tradeoff made concrete.

> Teaching model: single-process, in-memory (each "node" is a dict), no real network or
> persistence. It faithfully models placement/replication/quorum semantics, not durability
> or wire protocols.

## Files
- `store/ring.py` — consistent hash ring with virtual nodes
- `store/cluster.py` — replication, quorum, versions, read-repair, membership
- `demo.py` — narrated walkthrough with metrics
- `app.py` — FastAPI + built-in HTML dashboard
