#!/usr/bin/env python3
"""FastAPI wrapper around the KV-cache offload simulator.

Run:
    pip install -r requirements.txt
    uvicorn app:app --reload
    # open http://127.0.0.1:8000/docs  (Swagger UI)
    # or POST http://127.0.0.1:8000/api/simulate

This is the same core `kvsim` engine the CLI uses, exposed over HTTP so the
Vue front-end (../../web) or curl can drive it.
"""
from typing import List, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from kvsim import (PRESETS, Hierarchy, DEFAULT_TIERS, KVCacheSimulator,
                   make_scenario, build_stream)

app = FastAPI(title="KV Cache Offload Simulator", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])


class SimRequest(BaseModel):
    model: str = "llama-3-8b"
    kv_bytes: Optional[float] = None      # 2=FP16, 1=FP8, 0.5=INT4
    requests: int = 400
    prefixes: int = 8
    share: float = 0.6
    sessions: int = 60
    revisit: float = 0.5
    prefetch: float = 0.0
    seed: int = 0


@app.get("/api/models")
def models():
    return {name: PRESETS[name].__dict__ for name in PRESETS}


@app.post("/api/simulate")
def simulate(req: SimRequest):
    model = PRESETS.get(req.model, PRESETS["llama-3-8b"])
    if req.kv_bytes:
        model = model.with_kv_dtype_bytes(req.kv_bytes)
    sc = make_scenario(n_requests=req.requests, n_prefixes=req.prefixes,
                       prefix_share_prob=req.share, n_sessions=req.sessions,
                       revisit_prob=req.revisit, seed=req.seed)
    sim = KVCacheSimulator(model, Hierarchy(DEFAULT_TIERS))
    stream_pc = build_stream(sc, model.block_tokens, prefix_cache=True)
    stream_no = build_stream(sc, model.block_tokens, prefix_cache=False)

    configs = [
        ("hbm_only", "hbm_only", stream_no),
        ("tiered", "tiered", stream_no),
        ("tiered+prefix", "tiered", stream_pc),
    ]
    results = []
    for label, strat, stream in configs:
        r = sim.run(stream, strategy=strat, prefetch_hide_frac=req.prefetch)
        d = r.as_dict()
        d["label"] = label
        results.append(d)

    return {
        "model": model.__dict__,
        "block_bytes": sim.block_bytes,
        "tier_caps_blocks": sim.tier_caps,
        "tiers": [t.__dict__ for t in sim.hier.tiers],
        "results": results,
    }


@app.get("/")
def root():
    return {"msg": "KV cache offload simulator API. See /docs"}
