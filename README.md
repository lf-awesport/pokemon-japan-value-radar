# Poké Value Radar — Japan

Dashboard mobile-first per valutare carte Pokémon giapponesi raw e gradate durante un acquisto in negozio.

## Modello dati ibrido

- `data/cards.json`: identità, soglie d'acquisto, raw locale JP curata e liquidità.
- `data/slab-benchmarks.json`: benchmark occidentali della stessa slab, fonte, data e confidence.
- `data/justtcg-raw.json`: benchmark automatico JustTCG per carte raw in lingua giapponese sul mercato US.
- `data/justtcg-mappings.json`: mapping stabile tra le carte del radar e JustTCG.

La raw JustTCG non è un prezzo di negozio giapponese. È un confronto globale automatico separato dalla raw locale curata.

## Aggiornamento

Il workflow `Refresh JustTCG raw prices` usa il repository secret `JUSTTCG_API_KEY`, rispetta il limite gratuito di 10 richieste al minuto e conserva l'ultimo dato valido quando una carta non viene aggiornata.

Il workflow è pianificato tre volte al giorno. Ogni aggiornamento valida i dataset prima del commit.

## Funzioni

- cambio EUR/JPY e EUR/USD;
- tax-free e scenario IVA import;
- prezzo visto in negozio salvato localmente;
- margine netto, ROI, sconto raw, prezzo massimo consigliato;
- verdetto Compra / Valuta / Passa;
- filtri, preferiti, stampa e fallback dati.

## Sviluppo locale

```bash
python -m http.server 8000
python scripts/validate_data.py
```
