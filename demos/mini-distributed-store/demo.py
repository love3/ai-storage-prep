#!/usr/bin/env python3
"""Narrated walkthrough of the mini distributed store (see kb/07).

Shows: load balance across nodes, availability under node failure via
replicas, quorum enforcement, read-repair, and minimal key movement on
rebalance -- the core properties of a consistent-hashing replicated store.

No dependencies. Run: python3 demo.py
"""
from collections import Counter
from store import Cluster


def hr(title):
    print("\n" + "=" * 70 + f"\n{title}\n" + "=" * 70)


def load_distribution(cluster, n_keys=5000):
    c = Counter()
    for i in range(n_keys):
        for node in cluster.ring.replicas(f"key-{i}", cluster.n):
            c[node] += 1
    return c


def main():
    hr("1) Build a 4-node cluster: N=3 replicas, W=2, R=2  (W+R>N => strong-ish)")
    cluster = Cluster(["n1", "n2", "n3", "n4"], n_replicas=3, w=2, r=2)
    print(cluster.stats()["consistency"])

    hr("2) Load distribution across nodes (5000 keys x 3 replicas)")
    dist = load_distribution(cluster)
    total = sum(dist.values())
    for node, cnt in sorted(dist.items()):
        print(f"   {node}: {cnt:>6} replicas ({100*cnt/total:.1f}%)")
    print("   -> virtual nodes keep it balanced near the ideal 25% each")

    hr("3) Write some keys and show their preference lists")
    for k, v in [("user:42", "alice"), ("cart:7", "3 items"), ("doc:foo", "hello")]:
        ok, meta = cluster.put(k, v)
        print(f"   PUT {k}={v!r} -> replicas {meta['preference_list']} "
              f"acked_by {meta['acked_by']} durable={ok}")

    hr("4) Kill the primary of 'user:42' -- reads still succeed via replicas")
    primary = cluster.key_placement("user:42")["primary"]
    print(f"   primary of user:42 = {primary}; marking it DOWN")
    cluster.set_alive(primary, False)
    val, meta = cluster.get("user:42")
    print(f"   GET user:42 -> {val!r}  quorum_met={meta['quorum_met']} "
          f"(responded {[r['node'] for r in meta['responded']]})")

    hr("5) Quorum enforcement: take a 2nd replica down, writes fail W=2")
    reps = cluster.key_placement("user:42")["preference_list"]
    second = [n for n in reps if n != primary][0]
    cluster.set_alive(second, False)
    ok, meta = cluster.put("user:42", "alice-v2")
    print(f"   with {primary} and {second} down: PUT durable={ok} "
          f"(acked_by {meta['acked_by']}, need W={meta['W']}) reason={meta['reason']}")
    cluster.set_alive(primary, True)
    cluster.set_alive(second, True)

    hr("6) Read-repair: stale replica gets updated on read")
    cluster.set_alive(reps[2], False)          # hide one replica during a write
    cluster.put("doc:foo", "hello-v2")
    cluster.set_alive(reps[2], True)           # it comes back stale
    val, meta = cluster.get("doc:foo")
    print(f"   GET doc:foo -> {val!r}; read-repaired nodes: {meta['read_repaired']}")

    hr("7) Rebalance: add node n5 -> only a small fraction of DATA moves")
    n_keys = 5000
    before = {i: set(cluster.ring.replicas(f"key-{i}", cluster.n))
              for i in range(n_keys)}
    cluster.add_node("n5")
    total_assignments = n_keys * cluster.n
    moved_assignments = 0        # replica placements that actually transfer data
    touched_keys = 0
    for i in range(n_keys):
        after = set(cluster.ring.replicas(f"key-{i}", cluster.n))
        added = after - before[i]
        moved_assignments += len(added)   # each newly-added replica must copy the value
        if after != before[i]:
            touched_keys += 1
    print(f"   added n5 (now {len(cluster.nodes)} nodes)")
    print(f"   DATA moved (replica copies): {moved_assignments}/{total_assignments} "
          f"= {100*moved_assignments/total_assignments:.1f}%  (ideal ~1/nodes "
          f"= {100/len(cluster.nodes):.0f}%)")
    print(f"   keys with any replica change: {touched_keys}/{n_keys} "
          f"= {100*touched_keys/n_keys:.1f}%")
    print(f"   naive key-mod-nodecount hashing would remap ~"
          f"{100*(len(cluster.nodes)-1)/len(cluster.nodes):.0f}% of all keys")

    hr("8) New load distribution after adding n5")
    dist = load_distribution(cluster); total = sum(dist.values())
    for node, cnt in sorted(dist.items()):
        print(f"   {node}: {100*cnt/total:.1f}%")

    print("\nTalking points: consistent hashing + vnodes = balanced load and minimal")
    print("movement on membership change; N replicas + W+R>N = availability under")
    print("failure with strong-ish consistency; read-repair heals stale replicas. kb/07")


if __name__ == "__main__":
    main()
