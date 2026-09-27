# Cross-relay probe (2026-09-25): send the same judge-0003 and exec-0003 messages to claude-opus-4-7 and
# claude-sonnet-4-6 through aisa.one and report the share of upper-case letters in each reply. The key is read
# from the environment variable RELAY_API_KEY. Cost: 4 calls, about 130K input tokens, under one dollar.
import json, os, sys, time, urllib.request
KEY = os.environ["RELAY_API_KEY"]
S = os.path.dirname(os.path.abspath(__file__))
msgs = json.load(open(os.path.join(S, "messages.json"), encoding="utf-8"))
out = {}
for model in ("claude-opus-4-7", "claude-sonnet-4-6"):
    for cid in ("judge-0003", "exec-0003"):
        body = {"model": model, "temperature": 0, "max_tokens": 2048,
                "messages": [{"role": "system", "content": msgs[cid]["system"]},
                             {"role": "user", "content": msgs[cid]["user"]}]}
        req = urllib.request.Request("https://api.aisa.one/v1/chat/completions", data=json.dumps(body).encode("utf-8"),
                                     headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.loads(r.read().decode("utf-8"))
            text = d["choices"][0]["message"]["content"] or ""
            letters = [c for c in text if c.isalpha()]
            up = sum(c.isupper() for c in letters) / max(1, len(letters))
            out[(model, cid)] = {"served": d.get("model"), "prompt_tokens": (d.get("usage") or {}).get("prompt_tokens"),
                                 "upper_share": round(up, 3), "head": text[:200].replace("\n", " | "), "secs": round(time.time() - t0, 1)}
        except Exception as e:  # noqa: BLE001
            out[(model, cid)] = {"error": str(e)[:200]}
for k, v in out.items():
    print(k, json.dumps(v, ensure_ascii=False))
