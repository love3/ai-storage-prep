"""Consistent hash ring with virtual nodes (see kb/07).

Keys and nodes are hashed onto a 2^32 ring. A key is owned by the first vnode
clockwise; replicas are the next distinct *physical* nodes clockwise. Virtual
nodes smooth load distribution and minimize key movement when membership
changes -- the same idea CRUSH/Dynamo/Cassandra use.
"""

import bisect
import hashlib
from typing import Dict, List


def _hash(key: str) -> int:
    return int(hashlib.md5(key.encode()).hexdigest(), 16) & 0xFFFFFFFF


class HashRing:
    def __init__(self, vnodes: int = 128):
        self.vnodes = vnodes
        self._ring: Dict[int, str] = {}     # position -> physical node
        self._sorted: List[int] = []        # sorted positions
        self.nodes: set = set()

    def add_node(self, node: str):
        if node in self.nodes:
            return
        self.nodes.add(node)
        for i in range(self.vnodes):
            pos = _hash(f"{node}#{i}")
            self._ring[pos] = node
            bisect.insort(self._sorted, pos)

    def remove_node(self, node: str):
        if node not in self.nodes:
            return
        self.nodes.discard(node)
        for i in range(self.vnodes):
            pos = _hash(f"{node}#{i}")
            if pos in self._ring:
                del self._ring[pos]
                idx = bisect.bisect_left(self._sorted, pos)
                if idx < len(self._sorted) and self._sorted[idx] == pos:
                    self._sorted.pop(idx)

    def replicas(self, key: str, n: int) -> List[str]:
        """First n distinct physical nodes clockwise from hash(key)."""
        if not self._sorted:
            return []
        pos = _hash(key)
        idx = bisect.bisect(self._sorted, pos) % len(self._sorted)
        out: List[str] = []
        seen = set()
        for _ in range(len(self._sorted)):
            node = self._ring[self._sorted[idx]]
            if node not in seen:
                seen.add(node)
                out.append(node)
                if len(out) == n:
                    break
            idx = (idx + 1) % len(self._sorted)
        return out

    def owner(self, key: str) -> str:
        r = self.replicas(key, 1)
        return r[0] if r else ""
