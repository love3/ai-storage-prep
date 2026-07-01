"""Memory/storage hierarchy definition (see KB 00 diagram)."""

from dataclasses import dataclass, field
from typing import List


@dataclass
class Tier:
    name: str
    capacity_bytes: int      # usable capacity for KV blocks on this tier
    read_latency_us: float   # per-block access latency to bring/attend a block
    bandwidth_GBs: float     # sustained bandwidth (for transfer-time modeling)
    cost_per_GB: float       # relative $ (for narrative only)

    # runtime state
    used_bytes: int = field(default=0, repr=False)


def _gib(n: float) -> int:
    return int(n * (1024 ** 3))


# A representative memory/storage hierarchy. LATENCIES and BANDWIDTHS are
# order-of-magnitude real values (see KB 00/06/14). CAPACITIES are *demo-scaled*
# down (proportions roughly preserved) so a laptop-scale workload exercises all
# tiers instead of fitting entirely in HBM. Override via Hierarchy(custom).
DEFAULT_TIERS: List[Tier] = [
    Tier("HBM",  _gib(0.5), read_latency_us=0.1,  bandwidth_GBs=3500, cost_per_GB=100.0),
    Tier("DRAM", _gib(2),   read_latency_us=0.2,  bandwidth_GBs=300,  cost_per_GB=5.0),
    Tier("CXL",  _gib(4),   read_latency_us=0.4,  bandwidth_GBs=80,   cost_per_GB=2.5),
    Tier("SSD",  _gib(64),  read_latency_us=80.0, bandwidth_GBs=12,   cost_per_GB=0.3),
]

# Realistic single-GPU-node absolute capacities (for the sizing calculator/UI).
REALISTIC_TIERS: List[Tier] = [
    Tier("HBM",  _gib(80),    read_latency_us=0.1,  bandwidth_GBs=3500, cost_per_GB=100.0),
    Tier("DRAM", _gib(1024),  read_latency_us=0.2,  bandwidth_GBs=300,  cost_per_GB=5.0),
    Tier("CXL",  _gib(4096),  read_latency_us=0.4,  bandwidth_GBs=80,   cost_per_GB=2.5),
    Tier("SSD",  _gib(65536), read_latency_us=80.0, bandwidth_GBs=12,   cost_per_GB=0.3),
]


class Hierarchy:
    """Holds tiers top (fastest) -> bottom (slowest/cheapest)."""

    def __init__(self, tiers: List[Tier]):
        # deep-ish copy so simulator runs are independent
        self.tiers = [Tier(t.name, t.capacity_bytes, t.read_latency_us,
                           t.bandwidth_GBs, t.cost_per_GB) for t in tiers]

    def tier(self, idx: int) -> Tier:
        return self.tiers[idx]

    @property
    def n(self) -> int:
        return len(self.tiers)

    def reset(self):
        for t in self.tiers:
            t.used_bytes = 0

    def transfer_us(self, idx: int, nbytes: float) -> float:
        """Latency to move nbytes from tier idx (latency + bandwidth term)."""
        t = self.tiers[idx]
        return t.read_latency_us + (nbytes / (t.bandwidth_GBs * 1e9)) * 1e6
