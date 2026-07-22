# JustTCG coverage report

Generated: `2026-07-22T23:15:44.246749+00:00`

## Summary

- Successful queries: **10/10**
- Strong identity matches: **10/10**
- Raw coverage: **10/10 (100.0%)**
- PSA coverage: **0/10 (0.0%)**
- Recommendation: **Usare JustTCG soprattutto per raw/catalogo e mantenere un benchmark slab separato.**

## Cards

| Card | Number | HTTP | Match | Raw | PSA 7 | PSA 8 | PSA 9 | PSA 10 | Notes |
|---|---:|---:|---:|:---:|:---:|:---:|:---:|:---:|---|
| Magikarp | 080/073 | 200 | 115 | ✅ | — | — | — | — |  |
| Charizard ex | 201/165 | 200 | 115 | ✅ | — | — | — | — |  |
| Eevee | 287/SM-P | 200 | 100 | ✅ | — | — | — | — |  |
| Lugia V | 110/098 | 200 | 115 | ✅ | — | — | — | — |  |
| Giratina VSTAR | 261/172 | 200 | 115 | ✅ | — | — | — | — |  |
| Mew ex | 205/165 | 200 | 115 | ✅ | — | — | — | — |  |
| Pikachu | 173/165 | 200 | 115 | ✅ | — | — | — | — |  |
| Psyduck | 286/SM-P | 200 | 100 | ✅ | — | — | — | — |  |
| Gengar VMAX | 020/019 | 200 | 100 | ✅ | — | — | — | — |  |
| Giratina V | 111/100 | 200 | 115 | ✅ | — | — | — | — |  |

## Interpretation

The v2 endpoint correctly identifies all ten Japanese cards and returns Japanese raw variants with US-market USD pricing. For this sample it returns no PSA 7, PSA 8, PSA 9 or PSA 10 variants. JustTCG is therefore suitable as an automated raw benchmark, but it should not be the only slab-price provider for this project.
