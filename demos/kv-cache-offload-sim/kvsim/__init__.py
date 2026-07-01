"""KV cache tiered-offload simulator.

Models an LLM serving KV cache spread across a memory/storage hierarchy
(HBM -> DRAM -> CXL -> NVMe SSD) with paging, LRU eviction, prefix reuse,
and prefetch. Reports hit rates per tier and the effective average latency
of KV block re-access during decode.

Pure standard library -- runs on macOS and Linux with any Python 3.8+.
"""

from .model import ModelConfig, PRESETS, kv_bytes_per_token, kv_bytes_per_block
from .tiers import Tier, Hierarchy, DEFAULT_TIERS, REALISTIC_TIERS
from .simulator import KVCacheSimulator, SimResult
from .workload import Scenario, Turn, make_scenario, build_stream

__all__ = [
    "ModelConfig", "PRESETS", "kv_bytes_per_token", "kv_bytes_per_block",
    "Tier", "Hierarchy", "DEFAULT_TIERS", "REALISTIC_TIERS",
    "KVCacheSimulator", "SimResult",
    "Scenario", "Turn", "make_scenario", "build_stream",
]
