#!/usr/bin/env python3
"""Probe JustTCG coverage for a small Japanese Pokémon card watchlist.

The script writes a report even when individual lookups fail. It exits non-zero
only for configuration/authentication failures, so a partial provider outage
cannot destroy the last known report.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
CARDS_PATH = ROOT / "data" / "coverage-cards.json"
REPORT_JSON = ROOT / "data" / "coverage-report.json"
REPORT_MD = ROOT / "data" / "coverage-report.md"
V1_BASE = "https://api.justtcg.com/v1/cards"
V2_BASE = "https://api.justtcg.com/v2/cards"
TIMEOUT_SECONDS = 25


def normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def request_json(url: str, api_key: str, retries: int = 3) -> tuple[int, dict[str, Any], dict[str, str]]:
    headers = {
        "x-api-key": api_key,
        "Accept": "application/json, application/problem+json",
        "User-Agent": "pokemon-japan-value-radar/coverage-check",
    }
    for attempt in range(retries):
        req = Request(url, headers=headers)
        try:
            with urlopen(req, timeout=TIMEOUT_SECONDS) as response:
                body = response.read().decode("utf-8")
                parsed = json.loads(body) if body else {}
                return response.status, parsed, dict(response.headers.items())
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(body) if body else {}
            except json.JSONDecodeError:
                parsed = {"error": body[:1000]}
            if exc.code == 429 and attempt + 1 < retries:
                retry_after = exc.headers.get("Retry-After")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else 2 ** attempt
                time.sleep(min(wait, 20))
                continue
            return exc.code, parsed, dict(exc.headers.items())
        except (URLError, TimeoutError) as exc:
            if attempt + 1 < retries:
                time.sleep(2 ** attempt)
                continue
            return 0, {"error": str(exc), "code": "NETWORK_ERROR"}, {}
    return 0, {"error": "request failed", "code": "UNKNOWN"}, {}


def score_candidate(target: dict[str, Any], candidate: dict[str, Any]) -> int:
    score = 0
    target_number = normalize(target["number"])
    candidate_number = normalize(candidate.get("number"))
    if target_number and candidate_number == target_number:
        score += 80
    elif target_number and (target_number in candidate_number or candidate_number in target_number):
        score += 40

    name = normalize(candidate.get("name"))
    names = [target["name"], *target.get("aliases", [])]
    score += max(
        35 if normalize(value) == name else 20 if normalize(value) in name or name in normalize(value) else 0
        for value in names
    )

    target_set = normalize(target.get("set"))
    candidate_set = normalize(candidate.get("set_name") or candidate.get("set"))
    if target_set and candidate_set == target_set:
        score += 30
    elif target_set and (target_set in candidate_set or candidate_set in target_set):
        score += 15
    return score


def collect_variants(payload: Any) -> list[dict[str, Any]]:
    variants: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            keys = {str(key).lower() for key in value}
            looks_like_variant = bool(
                {"condition", "printing", "grade", "grading_company", "gradingcompany", "markets", "price"} & keys
            )
            if looks_like_variant:
                variants.append(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload)
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for variant in variants:
        fingerprint = json.dumps(variant, sort_keys=True, ensure_ascii=False)
        if fingerprint not in seen:
            seen.add(fingerprint)
            unique.append(variant)
    return unique


def variant_text(variant: dict[str, Any]) -> str:
    values = [
        variant.get("condition"),
        variant.get("printing"),
        variant.get("language"),
        variant.get("grade"),
        variant.get("grading_company"),
        variant.get("gradingCompany"),
        variant.get("name"),
        variant.get("label"),
    ]
    return " ".join(str(value) for value in values if value is not None).lower()


def grade_coverage(variants: list[dict[str, Any]]) -> dict[str, Any]:
    raw_count = 0
    japanese_count = 0
    grades = {"PSA 7": False, "PSA 8": False, "PSA 9": False, "PSA 10": False}
    market_regions: set[str] = set()
    latest = 0

    for variant in variants:
        text = variant_text(variant)
        if "japanese" in text or "japan" in text:
            japanese_count += 1
        is_graded = any(token in text for token in ("psa", "bgs", "cgc", "sgc", "graded"))
        if not is_graded and any(token in text for token in ("near mint", " nm", "ungraded", "raw")):
            raw_count += 1
        for label in grades:
            grade = label.split()[-1]
            if "psa" in text and re.search(rf"(?:^|\D){re.escape(grade)}(?:\.0)?(?:\D|$)", text):
                grades[label] = True

        updated = variant.get("last_updated") or variant.get("lastUpdated") or 0
        try:
            latest = max(latest, int(updated))
        except (TypeError, ValueError):
            pass

        markets = variant.get("markets")
        if isinstance(markets, list):
            for market in markets:
                if isinstance(market, dict):
                    region = market.get("region") or market.get("country") or market.get("market")
                    if region:
                        market_regions.add(str(region))

    return {
        "variant_count": len(variants),
        "raw_variant_count": raw_count,
        "japanese_variant_count": japanese_count,
        "psa_grades": grades,
        "psa_any": any(grades.values()),
        "market_regions": sorted(market_regions),
        "latest_variant_update": datetime.fromtimestamp(latest, timezone.utc).isoformat() if latest else None,
    }


def api_error(payload: dict[str, Any]) -> str | None:
    error = payload.get("error") or payload.get("detail") or payload.get("title")
    code = payload.get("code") or payload.get("type")
    if error and code:
        return f"{code}: {error}"
    return str(error) if error else None


def query_v1(card: dict[str, Any], api_key: str) -> dict[str, Any]:
    params = {
        "game": "pokemon-japan",
        "q": card["name"],
        "number": card["number"],
        "limit": 20,
        "include_null_prices": "true",
        "include_price_history": "false",
        "include_statistics": "false",
    }
    status, payload, _ = request_json(f"{V1_BASE}?{urlencode(params)}", api_key)
    candidates = payload.get("data") if isinstance(payload.get("data"), list) else []
    ranked = sorted(candidates, key=lambda item: score_candidate(card, item), reverse=True)
    best = ranked[0] if ranked else None
    return {
        "status": status,
        "error": api_error(payload),
        "candidate_count": len(candidates),
        "best_score": score_candidate(card, best) if best else 0,
        "best_match": best,
        "usage": payload.get("_metadata"),
    }


def query_v2(card: dict[str, Any], api_key: str) -> dict[str, Any]:
    # V2 is beta. Keep the probe isolated so a contract change degrades the
    # report instead of breaking the workflow.
    attempts = [
        {"game": "pokemon-japan", "regions": "US,JP", "q": card["name"], "number": card["number"], "limit": 20},
        {"game": "pokemon-japan", "regions": "US", "q": card["name"], "number": card["number"], "limit": 20},
    ]
    last: dict[str, Any] = {"status": 0, "error": "v2 not attempted", "payload": {}}
    for params in attempts:
        status, payload, headers = request_json(f"{V2_BASE}?{urlencode(params)}", api_key)
        last = {"status": status, "error": api_error(payload), "payload": payload, "link": headers.get("Link")}
        if status == 200:
            break
        if status in (401, 403, 429):
            break
    data = last["payload"].get("data") if isinstance(last["payload"], dict) else None
    candidates = data if isinstance(data, list) else []
    ranked = sorted(candidates, key=lambda item: score_candidate(card, item), reverse=True)
    best = ranked[0] if ranked else None
    return {
        "status": last["status"],
        "error": last["error"],
        "candidate_count": len(candidates),
        "best_score": score_candidate(card, best) if best else 0,
        "best_match": best,
        "link": last.get("link"),
    }


def slim_card(card: dict[str, Any] | None) -> dict[str, Any] | None:
    if not card:
        return None
    return {
        "id": card.get("id"),
        "uuid": card.get("uuid"),
        "name": card.get("name"),
        "set": card.get("set"),
        "set_name": card.get("set_name"),
        "number": card.get("number"),
        "rarity": card.get("rarity"),
    }


def write_reports(results: list[dict[str, Any]], started_at: str, usage: dict[str, Any] | None) -> None:
    total = len(results)
    raw = sum(1 for result in results if result["raw_available"])
    graded = sum(1 for result in results if result["psa_any"])
    exact = sum(1 for result in results if result["match_score"] >= 80)
    v2_ok = sum(1 for result in results if result["v2_status"] == 200)
    summary = {
        "cards_tested": total,
        "exact_or_strong_matches": exact,
        "raw_coverage": raw,
        "raw_coverage_pct": round(raw / total * 100, 1) if total else 0,
        "psa_coverage": graded,
        "psa_coverage_pct": round(graded / total * 100, 1) if total else 0,
        "v2_successful_queries": v2_ok,
    }
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "started_at": started_at,
        "provider": "JustTCG",
        "api_usage": usage,
        "summary": summary,
        "cards": results,
    }
    REPORT_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    recommendation = (
        "Provider principale per raw e slab."
        if summary["psa_coverage_pct"] >= 70
        else "Provider ibrido: automatico dove coperto, override manuale per le slab mancanti."
        if summary["psa_coverage_pct"] >= 30
        else "Usare JustTCG soprattutto per raw/catalogo; mantenere benchmark slab manuali o con altra fonte."
    )
    lines = [
        "# JustTCG coverage report",
        "",
        f"Generated: `{report['generated_at']}`",
        "",
        "## Summary",
        "",
        f"- Cards tested: **{total}**",
        f"- Strong identity matches: **{exact}/{total}**",
        f"- Raw coverage: **{raw}/{total} ({summary['raw_coverage_pct']}%)**",
        f"- PSA coverage: **{graded}/{total} ({summary['psa_coverage_pct']}%)**",
        f"- Successful v2 queries: **{v2_ok}/{total}**",
        f"- Recommendation: **{recommendation}**",
        "",
        "## Cards",
        "",
        "| Card | Number | Match | Raw | PSA 7 | PSA 8 | PSA 9 | PSA 10 | V2 | Notes |",
        "|---|---:|---:|:---:|:---:|:---:|:---:|:---:|---:|---|",
    ]
    for result in results:
        grades = result["psa_grades"]
        notes = result.get("error") or result.get("v2_error") or ""
        notes = str(notes).replace("|", "/")[:120]
        lines.append(
            f"| {result['name']} | {result['number']} | {result['match_score']} | "
            f"{'✅' if result['raw_available'] else '—'} | "
            f"{'✅' if grades['PSA 7'] else '—'} | {'✅' if grades['PSA 8'] else '—'} | "
            f"{'✅' if grades['PSA 9'] else '—'} | {'✅' if grades['PSA 10'] else '—'} | "
            f"{result['v2_status']} | {notes} |"
        )
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    api_key = os.environ.get("JUSTTCG_API_KEY", "").strip()
    if not api_key:
        print("JUSTTCG_API_KEY is missing", file=sys.stderr)
        return 2

    cards = json.loads(CARDS_PATH.read_text(encoding="utf-8"))
    started_at = datetime.now(timezone.utc).isoformat()
    results: list[dict[str, Any]] = []
    usage: dict[str, Any] | None = None

    for index, card in enumerate(cards, start=1):
        print(f"[{index}/{len(cards)}] {card['name']} {card['number']}", flush=True)
        v1 = query_v1(card, api_key)
        if v1["status"] in (401, 403):
            print(f"Authentication/permission failure: {v1['error']}", file=sys.stderr)
            return 3
        if usage is None and isinstance(v1.get("usage"), dict):
            usage = v1["usage"]

        v2 = query_v2(card, api_key)
        best = v2.get("best_match") or v1.get("best_match")
        all_variants = collect_variants(best or {})
        coverage = grade_coverage(all_variants)
        match_score = max(v1.get("best_score", 0), v2.get("best_score", 0))
        results.append(
            {
                "id": card["id"],
                "name": card["name"],
                "set": card["set"],
                "number": card["number"],
                "match_score": match_score,
                "matched_card": slim_card(best),
                "v1_status": v1["status"],
                "v2_status": v2["status"],
                "error": v1.get("error"),
                "v2_error": v2.get("error"),
                "raw_available": coverage["raw_variant_count"] > 0,
                **coverage,
            }
        )
        time.sleep(0.25)

    write_reports(results, started_at, usage)
    print(f"Wrote {REPORT_JSON.relative_to(ROOT)} and {REPORT_MD.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
