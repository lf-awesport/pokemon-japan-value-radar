#!/usr/bin/env python3
"""Refresh Japanese-language raw card prices from JustTCG v2.

The returned market is US/USD. These values are intentionally kept separate from
curated Japanese-store raw prices and from curated graded-card benchmarks.
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
MAPPINGS_PATH = ROOT / "data" / "justtcg-mappings.json"
OUTPUT_PATH = ROOT / "data" / "justtcg-raw.json"
API = "https://api.justtcg.com/v2/cards"
INTERVAL_SECONDS = 7.0


def norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return re.sub(r"[^a-z0-9]+", "", text)


def set_name(card: dict[str, Any]) -> str:
    value = card.get("set_name") or card.get("set")
    if isinstance(value, dict):
        return str(value.get("name") or value.get("id") or "")
    return str(value or "")


def identity_score(target: dict[str, Any], card: dict[str, Any]) -> int:
    score = 80 if norm(target["number"]) == norm(card.get("number")) else 0
    actual_name = norm(card.get("name"))
    expected = [target["name"], *target.get("aliases", [])]
    if any(norm(item) == actual_name for item in expected):
        score += 35
    elif actual_name and any(norm(item) in actual_name or actual_name in norm(item) for item in expected):
        score += 20
    wanted_set, found_set = norm(target.get("set")), norm(set_name(card))
    if wanted_set == found_set:
        score += 30
    elif wanted_set and found_set and (wanted_set in found_set or found_set in wanted_set):
        score += 15
    return score


def fetch_json(url: str, api_key: str) -> tuple[int, dict[str, Any]]:
    headers = {
        "x-api-key": api_key,
        "Accept": "application/json, application/problem+json",
        "User-Agent": "pokemon-japan-value-radar/raw-refresh",
    }
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers=headers), timeout=30) as response:
                return response.status, json.loads(response.read().decode() or "{}")
        except HTTPError as exc:
            raw = exc.read().decode(errors="replace")
            try:
                payload = json.loads(raw or "{}")
            except json.JSONDecodeError:
                payload = {"error": raw[:1000]}
            if exc.code == 429 and attempt < 2:
                retry_after = exc.headers.get("Retry-After")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else INTERVAL_SECONDS
                time.sleep(max(INTERVAL_SECONDS, wait))
                continue
            return exc.code, payload
        except (URLError, TimeoutError) as exc:
            if attempt < 2:
                time.sleep(2**attempt)
                continue
            return 0, {"error": str(exc)}
    return 0, {"error": "request failed"}


def query_card(target: dict[str, Any], api_key: str) -> tuple[int, dict[str, Any] | None, str | None]:
    params = {
        "game": target.get("game", "pokemon-japan"),
        "regions": target.get("marketRegion", "US"),
        "q": target["name"],
        "number": target["number"],
        "limit": 20,
    }
    status, payload = fetch_json(f"{API}?{urlencode(params)}", api_key)
    error = payload.get("error") or payload.get("detail") if isinstance(payload, dict) else None
    cards = payload.get("data", []) if isinstance(payload, dict) else []
    if not isinstance(cards, list):
        cards = []
    cards.sort(key=lambda card: identity_score(target, card), reverse=True)
    best = cards[0] if cards and identity_score(target, cards[0]) >= 80 else None
    return status, best, str(error) if error else None


def extract_near_mint(card: dict[str, Any], target: dict[str, Any]) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    variants = card.get("variants", [])
    if not isinstance(variants, list):
        return None
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        if str(variant.get("type", "")).lower() != "raw":
            continue
        if str(variant.get("condition", "")).lower() != "near mint":
            continue
        if str(variant.get("language", "")).lower() != str(target.get("language", "Japanese")).lower():
            continue
        markets = variant.get("markets", [])
        if not isinstance(markets, list):
            continue
        for market in markets:
            if not isinstance(market, dict):
                continue
            if market.get("region") != target.get("marketRegion", "US"):
                continue
            if market.get("currency") != "USD" or not isinstance(market.get("price"), (int, float)):
                continue
            candidates.append({"variant": variant, "market": market})
    if not candidates:
        return None
    candidates.sort(key=lambda item: (str(item["variant"].get("printing")) == "Holofoil", item["market"]["price"]), reverse=True)
    selected = candidates[0]
    variant, market = selected["variant"], selected["market"]
    provider_timestamp = market.get("updated_at")
    return {
        "baseCardId": target["baseCardId"],
        "providerCardId": card.get("id"),
        "variantId": variant.get("id"),
        "condition": "Near Mint",
        "printing": variant.get("printing"),
        "language": target.get("language", "Japanese"),
        "marketRegion": target.get("marketRegion", "US"),
        "currency": "USD",
        "priceUsd": round(float(market["price"]), 2),
        "providerUpdatedAt": datetime.fromtimestamp(provider_timestamp, timezone.utc).isoformat() if provider_timestamp else None,
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "source": "JustTCG v2",
    }


def main() -> int:
    api_key = os.environ.get("JUSTTCG_API_KEY", "").strip()
    if not api_key:
        print("JUSTTCG_API_KEY is missing", file=sys.stderr)
        return 2

    mappings_payload = json.loads(MAPPINGS_PATH.read_text(encoding="utf-8"))
    mappings = mappings_payload.get("mappings", [])
    old_payload = json.loads(OUTPUT_PATH.read_text(encoding="utf-8")) if OUTPUT_PATH.exists() else {"records": []}
    records = {row["baseCardId"]: row for row in old_payload.get("records", []) if row.get("baseCardId")}
    success = 0
    errors: list[dict[str, Any]] = []
    last_request = 0.0

    for index, target in enumerate(mappings, start=1):
        delay = INTERVAL_SECONDS - (time.monotonic() - last_request)
        if last_request and delay > 0:
            time.sleep(delay)
        print(f"[{index}/{len(mappings)}] {target['name']} {target['number']}", flush=True)
        last_request = time.monotonic()
        status, card, error = query_card(target, api_key)
        if status in (401, 403):
            print(f"Authentication failure: {error or status}", file=sys.stderr)
            return 3
        record = extract_near_mint(card, target) if card else None
        if record:
            records[target["baseCardId"]] = record
            success += 1
        else:
            errors.append({"baseCardId": target["baseCardId"], "httpStatus": status, "error": error or "No exact Near Mint Japanese raw variant"})

    output = {
        "meta": {
            "version": 1,
            "provider": "JustTCG v2",
            "marketRegion": "US",
            "language": "Japanese",
            "currency": "USD",
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "successfulRecords": success,
            "totalRecords": len(records),
            "errors": errors,
            "disclaimer": "Prices describe Japanese-language raw cards in the US market, not Japanese store prices.",
        },
        "records": sorted(records.values(), key=lambda row: row["baseCardId"]),
    }
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Updated {success}/{len(mappings)} records; preserved {len(records) - success} previous records.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
