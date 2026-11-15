# RailKit fixtures — provenance

Files at the top level are documentation-derived or synthetic. `live/` holds sanitized live captures.

| File | Provenance |
|---|---|
| `seat_availability_docs.json` | Verbatim sample from the RailKit docs bundle (railkit.in/docs, seat availability), retrieved 2026-11-08 |
| `train_search_docs.json` | Verbatim sample from the RailKit docs bundle (train search), retrieved 2026-11-08 |
| `train_info_docs.json` | Verbatim sample from the RailKit docs bundle (train info; route abbreviated to one stop by RailKit), retrieved 2026-11-08 |
| `station_search_docs.json` | Verbatim sample from the RailKit docs bundle (station search), retrieved 2026-11-08 |
| `train_info_synthetic_overnight.json` | **Synthetic.** Field names and value formats copied from `train_info_docs.json`; stops, times and train are invented to exercise midnight crossing (including midnight during a halt) and mixed `platform`/`haltMinutes` types |
| Error envelopes in tests | Shapes from railkit.in/docs/errors (`{ "success": false, "error": "…" }`) |

Status/prediction variants used by the tests (AVL, CNF, RAC, REGRET, malformed predictions, missing
dates, echo mismatches, …) are produced in test code by mutating `seat_availability_docs.json`, so
the only base shape is the documented one.

## Live captures (paid plan, sanitized by the capture code)

| File | Provenance |
|---|---|
| `live/2026-11-14/train_search.json` | Live run 2, 2026-11-14: trains between NDLS and BCT for 28-11-2026 |
| `live/2026-11-14/train_info_12904.json` | Live run 1, 2026-11-14 |
| `live/2026-11-14/train_info_12248.json` | Live run 2, 2026-11-14 |
| `live/2026-11-14/seat_availability_direct.json` | Live run 2: 12248 NZM→BDTS, CC, GN, sent 28-11-2026 |
| `live/2026-11-14/seat_availability_after_midnight_boarding_date.json` | Live run 2: 12248 RTM→BDTS, CC, GN, sent 29-11-2026 (boarding date at RTM) |
| `live/2026-11-14/report.json` | Live run 2 probe report (Q1 verdict `SEGMENT_BOARDING_DATE`) |

| `live/2026-11-15/seat_12904_ASR_LDH_3A_TQ.json` | Quota probe, 2026-11-15 13:13 IST: 12904 ASR→LDH, 3A, **TQ**, sent 16-11-2026 (Tatkal window open) |
| `live/2026-11-15/seat_12904_ASR_LDH_SL_TQ.json` | Same probe: SL, **TQ** |
| `live/2026-11-15/report.json` | Quota probe report; includes the PT probe (3A, **PT**) answered `400 Quota not allowed` |

Run 1's direct availability capture (12904 NZM→BDTS 3A) was overwritten by run 2. Live runs
now write to `live/run-<UTC timestamp>/`; promote files to a dated folder deliberately.
