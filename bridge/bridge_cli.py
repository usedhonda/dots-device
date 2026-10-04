#!/usr/bin/env python3
import argparse, json, os, secrets, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TOKEN_FILE = ROOT / ".local" / "bridge-token"

def call(base, token, method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(base + path, data=data, method=method, headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=4) as res: return json.load(res)

def main():
    p = argparse.ArgumentParser(description="KAI bridge CLI"); p.add_argument("--base", default="http://127.0.0.1:8766"); p.add_argument("--token-file", default=str(TOKEN_FILE))
    sub = p.add_subparsers(dest="op", required=True)
    sub.add_parser("status"); sub.add_parser("requests"); sub.add_parser("pending"); sub.add_parser("choices")
    demo = sub.add_parser("demo"); demo.add_argument("kind", choices=["short", "four", "scroll", "off"])
    pub = sub.add_parser("publish"); pub.add_argument("id", nargs="?", choices=["schedule","messages","approvals","progress","summary","details","open_kai","focus","refresh"]); pub.add_argument("--request-id", default=None); pub.add_argument("--interaction-json", type=Path); pub.add_argument("--source", choices=["real", "simulation"])
    rep = sub.add_parser("reply"); rep.add_argument("request_id"); rep.add_argument("status", choices=["completed","failed","pending_agent"]); rep.add_argument("summary")
    ss = sub.add_parser("set-state"); ss.add_argument("summary"); ss.add_argument("--source", choices=["real", "simulation"], default="simulation")
    a=p.parse_args(); token=Path(a.token_file).read_text().strip()
    if a.op == "status": result=call(a.base,token,"GET","/admin/state")
    elif a.op == "requests": result=call(a.base,token,"GET","/admin/requests")
    elif a.op == "pending": result=call(a.base,token,"GET","/admin/requests?status=pending_agent")
    elif a.op == "choices": result=call(a.base,token,"GET","/admin/choices")
    elif a.op == "demo": result=call(a.base,token,"POST","/admin/demo",{"kind": a.kind})
    elif a.op == "publish":
        if a.interaction_json:
            payload=json.loads(a.interaction_json.read_text(encoding="utf-8")); payload["source"] = a.source or payload.get("source")
            result=call(a.base,token,"POST","/admin/interaction",payload)
        else:
            if not a.id: p.error("publish requires an id or --interaction-json")
            result=call(a.base,token,"POST","/command",{"id":a.id,"request_id":a.request_id or secrets.token_urlsafe(12)})
    elif a.op == "reply": result=call(a.base,token,"POST","/admin/reply",{"request_id":a.request_id,"status":a.status,"summary":a.summary})
    else: result=call(a.base,token,"POST","/admin/state",{"summary":a.summary,"source":a.source})
    print(json.dumps(result, indent=2, sort_keys=True))
if __name__ == "__main__": main()
