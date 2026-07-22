# JustTCG integration experiment

This branch deliberately does not modify the live dashboard. It first measures whether JustTCG can identify and price the ten Japanese Pokémon cards used by the initial radar.

## What runs

`Check JustTCG coverage` calls the stable v1 cards endpoint and probes the beta v2 cards endpoint. The resulting report records:

- identity match strength;
- raw variant availability;
- PSA 7/8/9/10 availability;
- v2 availability and errors;
- API usage metadata, without storing the API key.

The workflow writes:

- `data/coverage-report.json` for machines;
- `data/coverage-report.md` for review.

## Decision rule

- PSA coverage >= 70%: use JustTCG as the primary automated provider.
- PSA coverage 30–69%: use a hybrid model with manual overrides.
- PSA coverage < 30%: use JustTCG mainly for raw/catalog data and retain another slab benchmark.

The API key is read exclusively from the `JUSTTCG_API_KEY` GitHub Actions secret.
