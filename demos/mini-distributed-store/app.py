#!/usr/bin/env python3
"""FastAPI front-end for the mini distributed store.

Run:
    pip install -r requirements.txt
    uvicorn app:app --reload
    # open http://127.0.0.1:8000/  (built-in dashboard)
    # or http://127.0.0.1:8000/docs (Swagger)
"""
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from store import Cluster

app = FastAPI(title="Mini Distributed Store", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])

cluster = Cluster(["n1", "n2", "n3", "n4"], n_replicas=3, w=2, r=2)


class PutBody(BaseModel):
    key: str
    value: str


@app.get("/api/stats")
def stats():
    return cluster.stats()


@app.get("/api/placement")
def placement(key: str):
    return cluster.key_placement(key)


@app.post("/api/put")
def put(body: PutBody):
    ok, meta = cluster.put(body.key, body.value)
    return {"ok": ok, **meta}


@app.get("/api/get")
def get(key: str):
    val, meta = cluster.get(key)
    return {"value": val, **meta}


@app.post("/api/node/{name}/{action}")
def node_action(name: str, action: str):
    if action == "add":
        cluster.add_node(name)
    elif action == "remove":
        cluster.remove_node(name)
    elif action == "down":
        cluster.set_alive(name, False)
    elif action == "up":
        cluster.set_alive(name, True)
    return cluster.stats()


DASH = """<!doctype html><html><head><meta charset=utf-8>
<title>Mini Distributed Store</title>
<style>body{font-family:system-ui,sans-serif;max-width:820px;margin:2rem auto;color:#222}
button{margin:2px;padding:4px 8px}input{padding:4px}pre{background:#f4f4f4;padding:10px;border-radius:6px;overflow:auto}
.node{display:inline-block;border:1px solid #ccc;border-radius:8px;padding:8px 12px;margin:4px}
.down{opacity:.4;background:#fdd}</style></head><body>
<h2>Mini Distributed Store <small>(consistent hashing + N=3 replicas, W=R=2)</small></h2>
<div id=nodes></div>
<h3>Put / Get</h3>
<input id=k placeholder=key value=user:42> <input id=v placeholder=value value=alice>
<button onclick=doput()>PUT</button> <button onclick=doget()>GET</button>
<button onclick=doplace()>placement</button>
<h3>Result</h3><pre id=out>ready</pre>
<script>
const api=(p,m='GET',b)=>fetch(p,{method:m,headers:{'Content-Type':'application/json'},
  body:b?JSON.stringify(b):undefined}).then(r=>r.json());
async function refresh(){const s=await api('/api/stats');
 document.getElementById('nodes').innerHTML=s.nodes.map(n=>
  `<span class=node ${n.alive?'':'down'}><b>${n.name}</b> keys:${n.keys}<br>
   <button onclick="act('${n.name}','${n.alive?'down':'up'}')">${n.alive?'kill':'revive'}</button>
   <button onclick="act('${n.name}','remove')">remove</button></span>`).join('')
  +`<div><button onclick="act('n'+(s.nodes.length+1),'add')">+ add node</button>
    <i>${s.consistency}</i></div>`;}
async function act(n,a){await api(`/api/node/${n}/${a}`,'POST');refresh();}
async function doput(){const o=await api('/api/put','POST',
 {key:k.value,value:v.value});show(o);refresh();}
async function doget(){show(await api('/api/get?key='+encodeURIComponent(k.value)));refresh();}
async function doplace(){show(await api('/api/placement?key='+encodeURIComponent(k.value)));}
function show(o){document.getElementById('out').textContent=JSON.stringify(o,null,2);}
refresh();
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return DASH
