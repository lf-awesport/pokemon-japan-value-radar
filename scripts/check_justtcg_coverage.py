#!/usr/bin/env python3
"""Probe JustTCG v2 coverage for selected Japanese Pokémon cards."""
import json, os, re, sys, time, unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
CARDS = ROOT / "data/coverage-cards.json"
OUT_JSON = ROOT / "data/coverage-report.json"
OUT_MD = ROOT / "data/coverage-report.md"
API = "https://api.justtcg.com/v2/cards"
INTERVAL = 7.0  # Free tier: 10 requests/minute.


def norm(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    return re.sub(r"[^a-z0-9]+", "", "".join(c for c in value if not unicodedata.combining(c)).lower())


def err(payload):
    msg = payload.get("error") or payload.get("detail") or payload.get("title")
    code = payload.get("code") or payload.get("type") or payload.get("status")
    return f"{code}: {msg}" if code and msg else str(msg) if msg else None


def fetch(url, key):
    headers = {"x-api-key": key, "Accept": "application/json, application/problem+json",
               "User-Agent": "pokemon-japan-value-radar/coverage-check"}
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers=headers), timeout=30) as res:
                return res.status, json.loads(res.read().decode() or "{}")
        except HTTPError as exc:
            raw = exc.read().decode(errors="replace")
            try: payload = json.loads(raw or "{}")
            except json.JSONDecodeError: payload = {"error": raw[:1000]}
            if exc.code == 429 and attempt < 2:
                retry = exc.headers.get("Retry-After")
                time.sleep(max(INTERVAL, float(retry) if retry and retry.isdigit() else 0))
                continue
            return exc.code, payload
        except (URLError, TimeoutError) as exc:
            if attempt < 2:
                time.sleep(2 ** attempt); continue
            return 0, {"code": "NETWORK_ERROR", "error": str(exc)}
    return 0, {"code": "UNKNOWN", "error": "request failed"}


def set_name(card):
    value = card.get("set_name") or card.get("set")
    return str(value.get("name") or value.get("id") or "") if isinstance(value, dict) else str(value or "")


def score(target, card):
    result = 80 if norm(target["number"]) == norm(card.get("number")) else 0
    actual = norm(card.get("name")); expected = [target["name"], *target.get("aliases", [])]
    result += 35 if any(norm(x) == actual for x in expected) else 20 if actual and any(norm(x) in actual or actual in norm(x) for x in expected) else 0
    wanted, found = norm(target.get("set")), norm(set_name(card))
    result += 30 if wanted == found else 15 if wanted and found and (wanted in found or found in wanted) else 0
    return result


def flatten(value):
    if isinstance(value, dict): return " ".join(flatten(v) for k, v in value.items() if k not in {"price_history", "priceHistory"})
    if isinstance(value, list): return " ".join(flatten(v) for v in value)
    return str(value or "").lower()


def sample_variant(v):
    keep = {"id","uuid","name","type","kind","condition","printing","language","grade",
            "grading_company","grader","label","price","last_updated","updated_at"}
    result = {k: val for k, val in v.items() if k in keep}
    result["available_keys"] = sorted(v)
    markets = v.get("markets") if isinstance(v.get("markets"), list) else []
    result["markets"] = [{k: val for k, val in m.items() if k in {"region","country","market","currency","price","market_price","low_price","mid_price","high_price","last_updated","updated_at"}} for m in markets if isinstance(m, dict)]
    return result


def coverage(card):
    variants = card.get("variants", []) if card else []
    variants = [v for v in variants if isinstance(v, dict)] if isinstance(variants, list) else []
    grades = {f"PSA {n}": False for n in (7,8,9,10)}; raw = 0; regions = set()
    for v in variants:
        text = flatten(v); graded = any(x in text for x in ("psa","bgs","cgc","sgc","graded"))
        if not graded and any(x in text for x in ("near mint","ungraded","raw"," nm ")): raw += 1
        for label in grades:
            n = label.split()[-1]
            if "psa" in text and re.search(rf"(?:^|\D){n}(?:\.0)?(?:\D|$)", text): grades[label] = True
        for market in v.get("markets", []) if isinstance(v.get("markets"), list) else []:
            if isinstance(market, dict):
                region = market.get("region") or market.get("country") or market.get("market")
                if region: regions.add(str(region))
    return {"variant_count":len(variants),"raw_variant_count":raw,"raw_available":raw>0,
            "psa_grades":grades,"psa_any":any(grades.values()),"market_regions":sorted(regions),
            "variant_samples":[sample_variant(v) for v in variants[:20]]}


def query(target, key):
    params = {"game":"pokemon-japan","regions":"US","q":target["name"],"number":target["number"],"limit":20}
    status, payload = fetch(f"{API}?{urlencode(params)}", key)
    cards = payload.get("data", []) if isinstance(payload, dict) else []
    cards = cards if isinstance(cards, list) else []; cards.sort(key=lambda c: score(target,c), reverse=True)
    best = cards[0] if cards else None
    return status, err(payload), cards, best, payload.get("_metadata") if isinstance(payload, dict) else None


def slim(card):
    if not card: return None
    return {"id":card.get("id"),"uuid":card.get("uuid"),"name":card.get("name"),
            "set":card.get("set"),"set_name":set_name(card),"number":card.get("number"),
            "rarity":card.get("rarity"),"available_keys":sorted(card)}


def write(results, usage):
    total=len(results); ok=sum(r["status"]==200 for r in results); matched=sum(r["match_score"]>=80 for r in results)
    raw=sum(r["raw_available"] for r in results); psa=sum(r["psa_any"] for r in results)
    pct=lambda n: round(n/total*100,1) if total else 0
    summary={"cards_tested":total,"successful_queries":ok,"strong_matches":matched,
             "raw_coverage":raw,"raw_coverage_pct":pct(raw),"psa_coverage":psa,"psa_coverage_pct":pct(psa)}
    recommendation=("Provider principale per raw e slab." if pct(psa)>=70 else
                    "Provider ibrido con override manuali." if pct(psa)>=30 else
                    "Usare JustTCG soprattutto per raw/catalogo e mantenere un benchmark slab separato.")
    report={"generated_at":datetime.now(timezone.utc).isoformat(),"provider":"JustTCG v2 beta",
            "api_usage":usage,"summary":summary,"recommendation":recommendation,"cards":results}
    OUT_JSON.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n")
    lines=["# JustTCG coverage report","",f"Generated: `{report['generated_at']}`","","## Summary","",
           f"- Successful queries: **{ok}/{total}**",f"- Strong identity matches: **{matched}/{total}**",
           f"- Raw coverage: **{raw}/{total} ({pct(raw)}%)**",f"- PSA coverage: **{psa}/{total} ({pct(psa)}%)**",
           f"- Recommendation: **{recommendation}**","","## Cards","",
           "| Card | Number | HTTP | Match | Raw | PSA 7 | PSA 8 | PSA 9 | PSA 10 | Notes |",
           "|---|---:|---:|---:|:---:|:---:|:---:|:---:|:---:|---|"]
    icon=lambda x:"✅" if x else "—"
    for r in results:
        g=r["psa_grades"]; note=str(r.get("error") or "").replace("|","/")[:120]
        lines.append(f"| {r['name']} | {r['number']} | {r['status']} | {r['match_score']} | {icon(r['raw_available'])} | {icon(g['PSA 7'])} | {icon(g['PSA 8'])} | {icon(g['PSA 9'])} | {icon(g['PSA 10'])} | {note} |")
    OUT_MD.write_text("\n".join(lines)+"\n")


def main():
    key=os.environ.get("JUSTTCG_API_KEY","").strip()
    if not key: print("JUSTTCG_API_KEY is missing",file=sys.stderr); return 2
    targets=json.loads(CARDS.read_text()); results=[]; usage=None; last=0.0
    for i,target in enumerate(targets,1):
        delay=INTERVAL-(time.monotonic()-last)
        if last and delay>0: time.sleep(delay)
        print(f"[{i}/{len(targets)}] {target['name']} {target['number']}",flush=True); last=time.monotonic()
        status,error,cards,best,meta=query(target,key)
        if status in (401,403): print(f"Authentication/permission failure: {error}",file=sys.stderr); return 3
        usage=usage or meta
        results.append({"id":target["id"],"name":target["name"],"set":target["set"],"number":target["number"],
                        "status":status,"error":error,"candidate_count":len(cards),"match_score":score(target,best) if best else 0,
                        "matched_card":slim(best),**coverage(best)})
    write(results,usage); print(f"Wrote {OUT_JSON.relative_to(ROOT)} and {OUT_MD.relative_to(ROOT)}"); return 0

if __name__=="__main__": raise SystemExit(main())
