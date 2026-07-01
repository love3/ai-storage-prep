"""A tiny Dynamo/Cassandra-style replicated KV store (see kb/07).

* N-way replication over a consistent hash ring.
* Tunable quorum: W (write) + R (read); W + R > N gives strong-ish consistency.
* Per-key version counter -> read-repair picks the highest version.
* Nodes can be marked down (failure) and added/removed (rebalance) to show
  availability under failure and minimal key movement.

In-memory and single-process (each 'node' is a dict) -- a teaching model of the
data plane, not a production store. No external dependencies.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .ring import HashRing


@dataclass
class Versioned:
    value: str
    version: int


@dataclass
class Node:
    name: str
    alive: bool = True
    data: Dict[str, Versioned] = field(default_factory=dict)


class Cluster:
    def __init__(self, nodes: List[str], n_replicas: int = 3,
                 w: int = 2, r: int = 2, vnodes: int = 128):
        self.n = n_replicas
        self.w = w
        self.r = r
        self.ring = HashRing(vnodes=vnodes)
        self.nodes: Dict[str, Node] = {}
        for name in nodes:
            self.add_node(name)

    # --- membership ------------------------------------------------------
    def add_node(self, name: str):
        self.nodes[name] = Node(name)
        self.ring.add_node(name)

    def remove_node(self, name: str):
        self.ring.remove_node(name)
        self.nodes.pop(name, None)

    def set_alive(self, name: str, alive: bool):
        if name in self.nodes:
            self.nodes[name].alive = alive

    # --- data plane ------------------------------------------------------
    def _preference_list(self, key: str) -> List[str]:
        return self.ring.replicas(key, self.n)

    def put(self, key: str, value: str) -> Tuple[bool, dict]:
        pref = self._preference_list(key)
        # next version = max existing + 1 across replicas
        cur = max((self.nodes[n].data[key].version
                   for n in pref if n in self.nodes and key in self.nodes[n].data),
                  default=0)
        version = cur + 1
        acks = []
        for n in pref:
            node = self.nodes.get(n)
            if node and node.alive:
                node.data[key] = Versioned(value, version)
                acks.append(n)
        ok = len(acks) >= self.w
        return ok, {"key": key, "version": version, "preference_list": pref,
                    "acked_by": acks, "W": self.w, "N": self.n,
                    "durable": ok, "reason": None if ok else "not enough replicas up"}

    def get(self, key: str) -> Tuple[Optional[str], dict]:
        pref = self._preference_list(key)
        responses = []
        for n in pref:
            node = self.nodes.get(n)
            if node and node.alive and key in node.data:
                v = node.data[key]
                responses.append((n, v.value, v.version))
        quorum = len(responses) >= self.r
        best = max(responses, key=lambda t: t[2]) if responses else None
        # read-repair: push newest version to stale/alive replicas
        repaired = []
        if best:
            for n in pref:
                node = self.nodes.get(n)
                if node and node.alive:
                    have = node.data.get(key)
                    if not have or have.version < best[2]:
                        node.data[key] = Versioned(best[1], best[2])
                        repaired.append(n)
        return (best[1] if best else None), {
            "key": key, "preference_list": pref,
            "responded": [{"node": n, "version": ver} for n, _, ver in responses],
            "R": self.r, "N": self.n, "quorum_met": quorum,
            "value": best[1] if best else None,
            "version": best[2] if best else None,
            "read_repaired": repaired,
        }

    # --- introspection ---------------------------------------------------
    def stats(self) -> dict:
        return {
            "N": self.n, "W": self.w, "R": self.r,
            "consistency": "W+R>N (strong-ish)" if self.w + self.r > self.n
                           else "W+R<=N (eventual)",
            "nodes": [
                {"name": n.name, "alive": n.alive, "keys": len(n.data)}
                for n in self.nodes.values()
            ],
        }

    def key_placement(self, key: str) -> dict:
        pref = self._preference_list(key)
        return {"key": key, "preference_list": pref,
                "primary": pref[0] if pref else None}
