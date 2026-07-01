"""Tiered KV-cache simulator.

Model (deliberately simple and defensible -- it is a *teaching* model):

* KV cache is a set of fixed-size blocks (PagedAttention style, KB 11).
* We build a block *reference stream* from the workload: prefill references
  each prompt block once; decode re-references the sequence's blocks
  (attention reads the whole KV each step, subsampled to keep it tractable).
* Each tier is an LRU list with a block capacity. Accessing a block promotes
  it to HBM (MRU); HBM overflow cascades the coldest block down to DRAM ->
  CXL -> SSD; overflow off the bottom tier evicts the block entirely.
* Access latency = read latency of the tier the block currently sits in.
  A reference to an evicted/never-computed block is a *recompute miss*.
* Prefix reuse: blocks of a shared prefix are deduplicated (COW); a later
  request reusing a live prefix hits instead of recomputing.
* Prefetch: an optional factor hiding a fraction of CXL/SSD latency by
  overlapping the fetch with decode compute (KB 02/11).

A cache simulator -- the exact storage-systems analogy the role wants.
All O(1) per access via per-tier OrderedDicts + a location map.
"""

from collections import OrderedDict
from dataclasses import dataclass
from typing import Dict, List, Optional

from .model import ModelConfig, kv_bytes_per_block
from .tiers import Hierarchy, DEFAULT_TIERS


RECOMPUTE_PENALTY_US = 2000.0  # ~ prefill recompute of a block on GPU (teaching value)


@dataclass
class SimResult:
    strategy: str
    n_references: int          # re-references (decode-time KV reads); the metric set
    populate: int              # first-touch prefill computes (not avoidable)
    tier_hits: Dict[str, int]
    recompute_misses: int      # re-reference of an evicted block (avoidable!)
    prefix_hits: int           # re-references served from a shared prefix block
    avg_access_latency_us: float
    p99_access_latency_us: float
    hbm_block_capacity: int
    total_block_capacity: int
    block_bytes: float
    distinct_blocks: int
    est_hbm_bytes_for_full_hot: int

    def as_dict(self):
        return dict(self.__dict__)

    def pretty(self) -> str:
        tot = max(1, self.n_references)
        lines = [f"[{self.strategy}]  block={self.block_bytes/1024:.1f} KiB  "
                 f"distinct={self.distinct_blocks:,}  re-refs={self.n_references:,}"]
        lines.append(f"  avg re-ref latency : {self.avg_access_latency_us:8.2f} us   "
                     f"p99 : {self.p99_access_latency_us:8.2f} us")
        lines.append(f"  recompute (evicted): {self.recompute_misses:>8,} "
                     f"({100*self.recompute_misses/tot:5.2f}%)   "
                     f"prefix-hits: {self.prefix_hits:,}")
        for name, h in self.tier_hits.items():
            lines.append(f"  hit {name:<5}         : {h:>8,} ({100*h/tot:5.2f}%)")
        return "\n".join(lines)


class KVCacheSimulator:
    def __init__(self, model: ModelConfig, hierarchy: Optional[Hierarchy] = None):
        self.model = model
        self.hier = hierarchy or Hierarchy(DEFAULT_TIERS)
        self.block_bytes = kv_bytes_per_block(model)
        self.tier_caps = [max(1, int(t.capacity_bytes // self.block_bytes))
                          for t in self.hier.tiers]

    # --- run --------------------------------------------------------------

    def run(self, stream, strategy: str = "tiered",
            prefetch_hide_frac: float = 0.0) -> SimResult:
        """Consume a reference stream (from workload.build_stream).

        strategy: 'hbm_only' (tier 0 only) or 'tiered' (full hierarchy).
        Prefix caching is expressed in the *stream* (shared block ids), so the
        typical comparison is: hbm_only+noPC vs tiered+noPC vs tiered+PC.
        """
        n_tiers = 1 if strategy == "hbm_only" else self.hier.n
        active_tiers = list(range(n_tiers))

        tiers: List["OrderedDict[str, bool]"] = [OrderedDict() for _ in active_tiers]
        loc: Dict[str, int] = {}
        ever: set = set()

        tier_hits = {t.name: 0 for t in self.hier.tiers}
        recompute = 0
        prefix_hits = 0
        populate = 0
        latencies: List[float] = []
        hbm_lat = self.hier.tiers[0].read_latency_us

        def evict_cascade(from_tier: int):
            ti = from_tier
            while ti < len(active_tiers) and len(tiers[ti]) > self.tier_caps[ti]:
                old_bid, _ = tiers[ti].popitem(last=False)  # coldest
                if ti + 1 < len(active_tiers):
                    tiers[ti + 1][old_bid] = True
                    loc[old_bid] = ti + 1
                    ti += 1
                else:
                    del loc[old_bid]  # evicted entirely -> recompute if seen again
                    break

        def latency_for(ti: int) -> float:
            lat = self.hier.tiers[ti].read_latency_us
            if ti >= 2 and prefetch_hide_frac > 0:  # CXL/SSD partly hidden by overlap
                lat = hbm_lat + (lat - hbm_lat) * (1.0 - prefetch_hide_frac)
            return lat

        def insert_hbm(bid):
            tiers[0][bid] = True
            loc[bid] = 0
            if len(tiers[0]) > self.tier_caps[0]:
                evict_cascade(0)

        for bid, is_prefix, fam in stream:
            if bid in loc:                          # cache hit (re-reference)
                ti = loc[bid]
                tier_hits[self.hier.tiers[ti].name] += 1
                latencies.append(latency_for(ti))
                if is_prefix:
                    prefix_hits += 1
                del tiers[ti][bid]
                insert_hbm(bid)
            elif bid in ever:                       # computed before, got evicted -> recompute
                recompute += 1
                latencies.append(RECOMPUTE_PENALTY_US)
                insert_hbm(bid)
            else:                                    # first touch = prefill compute (populate)
                populate += 1
                ever.add(bid)
                insert_hbm(bid)

        latencies.sort()
        n = len(latencies)
        avg = sum(latencies) / max(1, n)
        p99 = latencies[min(n - 1, int(0.99 * n))] if n else 0.0
        distinct = len({b for b, _, _ in stream})

        return SimResult(
            strategy=strategy,
            n_references=n,
            populate=populate,
            tier_hits=tier_hits,
            recompute_misses=recompute,
            prefix_hits=prefix_hits,
            avg_access_latency_us=avg,
            p99_access_latency_us=p99,
            hbm_block_capacity=self.tier_caps[0],
            total_block_capacity=sum(self.tier_caps[i] for i in active_tiers),
            block_bytes=self.block_bytes,
            distinct_blocks=distinct,
            est_hbm_bytes_for_full_hot=int(distinct * self.block_bytes),
        )
