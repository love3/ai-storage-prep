# 07 · Distributed Storage & Ceph

> JD R1 (file/object/block + consistency layer) and bonus B1 (Ceph core module dev).
> Know Ceph's architecture, CRUSH, replication vs EC, and the consistency/consensus story.

## 1. Distributed storage design axes

- **Data model**: block (volumes), file (POSIX namespace), object (key→blob, S3).
- **Data placement**: central metadata (HDFS NameNode, GFS master) vs algorithmic
  (Ceph CRUSH — no lookup, compute placement) vs consistent hashing (Dynamo, Swift).
- **Redundancy**: replication (N copies, simple, storage-heavy) vs **erasure coding**
  (k data + m parity, storage-efficient, CPU + rebuild cost).
- **Consistency**: strong (linearizable, needs consensus) vs eventual (AP, Dynamo) vs
  causal. Governed by **CAP** and **PACELC** (even without partitions you trade latency
  vs consistency).
- **Failure handling**: replication/recovery, scrubbing, rebalancing, fencing.

## 2. Ceph architecture (the canonical example)

```
Clients (librados / RBD / CephFS / RGW-S3)
        │
     RADOS  (Reliable Autonomic Distributed Object Store)
   ┌────────────┬───────────────┬──────────────┐
   │ MON        │ OSD (many)     │ MGR / MDS     │
   │ (cluster   │ (one per disk, │ MDS=CephFS    │
   │  map,      │  stores objects│ metadata,     │
   │  Paxos)    │  on BlueStore) │ MGR=mgmt      │
   └────────────┴───────────────┴──────────────┘
```

- **RADOS**: everything is an **object** in a **pool**; higher services build on it:
  - **RBD** (block), **CephFS** (POSIX file, via MDS metadata servers), **RGW** (S3/Swift
    object).
- **MON (Monitors)**: maintain the authoritative **cluster maps** (monmap, osdmap,
  crushmap, pgmap) via a **Paxos** quorum → strongly consistent membership/config.
- **OSD (Object Storage Daemons)**: one per disk; store objects, handle replication,
  recovery, scrubbing. Modern OSDs use **BlueStore** (writes objects directly to raw
  block device + RocksDB for metadata, bypassing a local filesystem to avoid double
  journaling).
- **MDS**: CephFS metadata (dynamic subtree partitioning of the namespace).
- **MGR**: metrics, dashboard, balancer modules.

## 3. CRUSH — placement without a lookup table

**CRUSH** (Controlled Replication Under Scalable Hashing) computes *where* an object lives
from its name + the cluster map, deterministically, on the client — **no central
metadata lookup** for data placement.

```
object name → hash → Placement Group (PG) → CRUSH(pg, crushmap, rules) → set of OSDs
```

- Objects map to a fixed number of **PGs** (a level of indirection so rebalancing moves
  PGs, not individual objects).
- CRUSH walks a hierarchical **failure domain** tree (root→datacenter→rack→host→osd) and
  places replicas in *different* domains per the pool's rule (e.g., 3 replicas across 3
  racks).
- Adding/removing OSDs changes the map → only the affected PGs move (minimal data
  movement, like consistent hashing but hierarchy-aware and weighted).

**Why it matters:** scales because clients compute placement (no metadata bottleneck),
and failure domains give durability. This is the "no central lookup" idea to contrast
with HDFS's NameNode.

## 4. Consistency & the write path

- Each PG has a **primary OSD**; writes go to the primary, which **replicates to the
  secondaries and waits for acks** before acking the client → **strong consistency**
  (synchronous replication within the PG).
- **Peering**: when membership changes, OSDs in a PG agree on the authoritative history
  (the PG log) before serving I/O.
- **Scrubbing**: periodic consistency checks (light = metadata, deep = data checksums)
  catch bit rot; BlueStore checksums every read.

## 5. Erasure coding vs replication

| | Replication (3×) | EC (e.g., 4+2) |
|--|------------------|----------------|
| Storage overhead | 200% | 50% |
| Write cost | 3 writes | encode + 6 writes |
| Read cost | 1 read | 1 (fast path) or reconstruct |
| Recovery | copy | read k chunks + decode (heavy) |
| Best for | hot, small, latency | cold, large, capacity |

EC saves capacity but costs CPU and makes recovery/partial-write expensive. Ceph
supports EC pools (often for RGW/cold); RBD/CephFS hot data usually replicated (or EC +
replicated cache tier historically).

## 6. Consensus primer (for the "consistency layer" keyword)

- **Paxos / Raft / ZAB**: replicated log agreed by a **majority quorum** (2f+1 nodes
  tolerate f failures). Used for **metadata / membership / config**, not the bulk data
  path (too slow for every object).
- **Raft** (easier to understand): leader election + log replication + safety via term
  numbers and majority commit. Ceph MON uses Paxos; etcd/Consul/CockroachDB use Raft.
- **Quorum systems (R + W > N)**: Dynamo-style tunable consistency without a leader.
- Pattern to articulate: **strong consistency for the control plane (small, rare
  changes) via consensus; scalable, often eventually-consistent or primary-replicated
  data plane.**

## 7. Other systems worth name-dropping

- **HDFS/GFS**: central metadata master + chunk/datanodes; append-optimized, big files.
- **Amazon Dynamo / Cassandra**: consistent hashing + vector clocks + tunable quorums,
  AP, eventual consistency.
- **MinIO / Swift**: object stores, EC.
- **Lustre / GPFS(Spectrum Scale) / BeeGFS / DAOS**: HPC parallel filesystems — DAOS is
  NVMe/PMEM + userspace (SPDK) and very relevant to AI training/inference data pipelines.
- **JuiceFS / 3FS (DeepSeek)**: modern AI-oriented distributed FS (3FS targets
  high-throughput random reads for training/KV using NVMe + RDMA).

## 8. AI relevance

- **Model/dataset store**: object store (S3/RGW) for weights & datasets; parallel FS or
  DAOS/3FS for high-throughput training reads.
- **Distributed KV cache pool**: KV cache offloaded across nodes needs a fast
  consistent-hashing / directory service + RDMA transport (KB 08, 11). Think "distributed
  cache with a brutal latency SLA," reusing consistent hashing, replication, and
  membership from classic distributed storage.
- **Consistency** for KV cache is usually *not* the hard part (cache is reconstructable);
  **placement, eviction, and fast transfer** are.

## 9. Interview-ready talking points

- "Ceph's core trick is CRUSH: clients *compute* placement from the cluster map, so there's
  no central metadata bottleneck; PGs add indirection so rebalancing moves groups, not
  objects, across failure domains."
- "Writes are primary-driven and synchronously replicated within a PG → strong
  consistency; MONs keep membership/config strongly consistent via Paxos."
- "Replication is simple and fast; erasure coding (k+m) saves capacity but costs CPU and
  makes recovery/partial writes expensive — hot data replicated, cold data EC."
- "Consensus (Paxos/Raft, majority quorum) is for the control plane; the data plane
  scales with algorithmic placement and primary replication."
- "For a distributed KV-cache pool I'd reuse consistent hashing + membership + RDMA
  transport, but relax consistency since cache is reconstructable and instead optimize
  placement, eviction, and transfer latency."
