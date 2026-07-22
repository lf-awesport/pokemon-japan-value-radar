#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    return json.loads((ROOT / "data" / name).read_text(encoding="utf-8"))


cards = load("cards.json").get("cards", [])
slabs = load("slab-benchmarks.json").get("benchmarks", [])
raw = load("justtcg-raw.json").get("records", [])
mappings = load("justtcg-mappings.json").get("mappings", [])

ids = [card["id"] for card in cards]
assert len(ids) == len(set(ids)), "Duplicate card IDs"
card_ids = set(ids)
base_ids = {card["baseCardId"] for card in cards}
assert all(row["cardId"] in card_ids for row in slabs), "Slab benchmark references unknown card"
assert all(row["baseCardId"] in base_ids for row in raw), "Raw record references unknown base card"
assert all(row["baseCardId"] in base_ids for row in mappings), "Mapping references unknown base card"
assert all(isinstance(row.get("valueEur"), (int, float)) and row["valueEur"] > 0 for row in slabs)
assert all(isinstance(row.get("priceUsd"), (int, float)) and row["priceUsd"] > 0 for row in raw)
print(f"Validated {len(cards)} cards, {len(slabs)} slabs, {len(raw)} raw records, {len(mappings)} mappings.")
