# Cross-relay probe, second run (2026-09-25): the two claude-opus-4-7 requests again, without a temperature.
# The first run (probe.py) sent temperature 0 and aisa.one answered HTTP 400 for this model. The key is read from
# the environment variable RELAY_API_KEY. Writes output-claude-opus-4-7.json next to this file.
import json, os, urllib.request, urllib.error
KEY = os.environ["RELAY_API_KEY"]
S = os.path.dirname(os.path.abspath(__file__))
msgs = json.load(open(os.path.join(S, "messages.json"), encoding="utf-8"))
res = {}
for cid in ("judge-0003", "exec-0003"):
    body = {"model": "claude-opus-4-7", "max_tokens": 2048,
            "messages": [{"role": "system", "content": msgs[cid]["system"]}, {"role": "user", "content": msgs[cid]["user"]}]}
    req = urllib.request.Request("https://api.aisa.one/v1/chat/completions", data=json.dumps(body).encode(), headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=240) as r:
            d = json.loads(r.read()); t = d["choices"][0]["message"]["content"] or ""
            letters = [c for c in t if c.isalpha()]
            res[cid] = {"served": d.get("model"), "prompt_tokens": (d.get("usage") or {}).get("prompt_tokens"), "upper": round(sum(c.isupper() for c in letters) / max(1, len(letters)), 3), "head": t[:200].replace("\n", " | ")}
    except urllib.error.HTTPError as e:
        res[cid] = {"http": e.code, "body": e.read()[:200].decode("utf-8", "replace")}
for k, v in res.items():
    print(k, json.dumps(v, ensure_ascii=False))
json.dump(res, open(os.path.join(S, "output-claude-opus-4-7.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
