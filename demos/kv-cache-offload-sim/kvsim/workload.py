"""Synthetic serving workload generator with shared prefixes and multi-turn
sessions -- the two things that make KV tiering interesting.

* Shared prefixes: system prompts / few-shot templates / RAG docs reused across
  requests. Prefix caching (APC / RadixAttention) turns these into hits.
* Multi-turn sessions: a chat session that pauses and resumes. On resume, the
  session's earlier KV (its history) is re-read -- but by then it may have been
  offloaded to CXL/SSD, so it must be *read back*. This is the JD's
  "KV access / reuse / offload / readback" story and is what makes tiering +
  prefetch matter.

Deterministic given a seed. Produces a *reference stream* of
(block_id, is_prefix, prefix_family) tuples consumed by the simulator.
"""

import random
from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class Turn:
    req_id: int
    session_id: int
    is_continuation: bool
    prefix_id: int
    prefix_tokens: int
    history_tokens: int    # session context re-read on resume
    new_tokens: int        # this turn's new prompt tokens
    decode_tokens: int


@dataclass
class Scenario:
    turns: List[Turn] = field(default_factory=list)
    n_prefixes: int = 0
    n_sessions: int = 0


def make_scenario(
    n_requests: int = 400,
    n_prefixes: int = 8,
    prefix_share_prob: float = 0.6,
    n_sessions: int = 60,
    revisit_prob: float = 0.5,
    prefix_len_range=(256, 2048),
    new_len_range=(32, 512),
    decode_len_range=(64, 512),
    seed: int = 0,
) -> Scenario:
    rng = random.Random(seed)
    prefix_lengths = [rng.randint(*prefix_len_range) for _ in range(max(1, n_prefixes))]
    session_ctx = {}      # session_id -> accumulated context tokens
    session_prefix = {}   # session_id -> prefix family (sticky per session)
    live_sessions: List[int] = []
    turns: List[Turn] = []

    for i in range(n_requests):
        if live_sessions and rng.random() < revisit_prob:
            sid = rng.choice(live_sessions)
            cont = True
        else:
            sid = len(session_ctx)
            if sid >= n_sessions and live_sessions:
                sid = rng.choice(live_sessions); cont = True
            else:
                cont = False
                session_ctx[sid] = 0
                live_sessions.append(sid)
                if rng.random() < prefix_share_prob and n_prefixes > 0:
                    session_prefix[sid] = rng.randrange(n_prefixes)
                else:
                    session_prefix[sid] = -1

        pid = session_prefix.get(sid, -1)
        plen = prefix_lengths[pid] if pid >= 0 else rng.randint(*prefix_len_range)
        history = session_ctx.get(sid, 0)
        new_tokens = rng.randint(*new_len_range)
        decode = rng.randint(*decode_len_range)
        turns.append(Turn(i, sid, cont, pid, plen, history, new_tokens, decode))
        session_ctx[sid] = history + new_tokens + decode  # grow context

    return Scenario(turns=turns, n_prefixes=n_prefixes, n_sessions=len(session_ctx))


def build_stream(sc: Scenario, block_tokens: int = 16, prefix_cache: bool = True,
                 decode_subsample: int = 6) -> List[Tuple[str, bool, int]]:
    """Turn a scenario into a block reference stream.

    prefix_cache: if True, shared prefixes across requests use the SAME block ids
    (cross-request reuse). If False, each request gets private prefix block ids,
    so identical system prompts are recomputed every time (no APC).
    """
    bt = block_tokens
    stream: List[Tuple[str, bool, int]] = []

    def nblocks(tokens):
        return (tokens + bt - 1) // bt

    for t in sc.turns:
        seq_blocks = []
        # prefix
        for b in range(nblocks(t.prefix_tokens)):
            if prefix_cache and t.prefix_id >= 0:
                bid = f"P{t.prefix_id}:{b}"          # shared across requests
            else:
                bid = f"S{t.session_id}:PX{b}" if t.prefix_id >= 0 else f"R{t.req_id}:P{b}"
            seq_blocks.append(bid)
            stream.append((bid, True, t.prefix_id))
        # session history (re-read on resume -> readback candidates)
        for b in range(nblocks(t.history_tokens)):
            bid = f"S{t.session_id}:H{b}"
            seq_blocks.append(bid)
            stream.append((bid, False, -1))
        # new prompt tokens for this turn (become part of history)
        base = nblocks(t.history_tokens)
        for b in range(nblocks(t.new_tokens)):
            bid = f"S{t.session_id}:H{base + b}"
            seq_blocks.append(bid)
            stream.append((bid, False, -1))
        # decode: append generated blocks and re-read the sequence KV (subsampled)
        n_dec = nblocks(t.decode_tokens)
        step = max(1, n_dec // max(1, decode_subsample))
        gbase = base + nblocks(t.new_tokens)
        g = 0
        for _ in range(0, n_dec, step):
            bid = f"S{t.session_id}:H{gbase + g}"
            g += 1
            seq_blocks.append(bid)
            sub = max(1, len(seq_blocks) // 12)
            for sb in seq_blocks[::sub]:
                stream.append((sb, False, -1))
    return stream
