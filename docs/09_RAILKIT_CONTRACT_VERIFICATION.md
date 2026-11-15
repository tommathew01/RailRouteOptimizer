# 09 — RailKit Contract Verification Log

Purpose: record what is **known** about the RailKit contract, where it came from, and what is
still **unverified**. Nothing in this file is a live capture. Update it after every live contract
run (`RUN_LIVE_RAILKIT_TESTS=true`), and save sanitized live payloads as new fixtures.

Evidence collected: 2026-11-08.

## 1. Sources

| Source | What it established |
|---|---|
| https://railkit.in/docs (docs bundle: endpoint table, parameters, sample responses) | REST paths, path parameters, `DD-MM-YYYY` dates, sample JSON for train search, train info, seat availability, station search, fare |
| https://railkit.in/docs/errors | Envelope `{ success, data }` / `{ success: false, error }`; HTTP 400/401/403/404/429/500 meanings |
| https://railkit.in/pricing | Free 50 req/month (100 per 10 min), Pro 5,000/month (200 per 10 min), Advance 10,000/month (600 per 10 min); paid request packs |
| npm `railkit@6.0.2` (`index.d.ts`, README, string constants of the published bundle; not executed) | Base URL `https://api.railkit.in`; header `x-api-key`; `Accept: application/json`; input validation rules (5-digit train number, 1–5 character station codes, `DD-MM-YYYY`) |

## 2. Endpoints used by RailRoute

| Purpose | Method + path | Notes |
|---|---|---|
| Station search | `GET /api/v1/stations/search?name={q}` | ≥ 2 characters, ≤ 10 results, `data.stations[] = {code, name, lat, lon}` |
| Station by code | `GET /api/v1/stations/{code}` | `data = {code, name, lat, lon}` (verified live 2026-11-14: `TVCN` → THIRUVANANTHAPURAM NORTH). Used because name search does not match codes |
| Trains between stations | `GET /api/v1/trains/between/{from}/{to}?date=DD-MM-YYYY` | `date` optional; `data[]` (array) |
| Train info + route | `GET /api/v1/trains/{trainNumber}/info` | `data.trainInfo`, `data.route[]` |
| Seat availability | `GET /api/v1/seats/{trainNo}/{from}/{to}/{DD-MM-YYYY}/{class}/{quota}` | `data.train`, `data.fare`, `data.availability[]` |

Not used in MVP: fare lookup (`/api/v1/fare/...`) because availability already carries `data.fare`
and each extra call spends quota; live status, PNR, timetable endpoints.

## 3. Documentation-derived payload shapes

Copied from the RailKit docs bundle. Stored as fixtures under
`backend/tests/fixtures/railkit/` with provenance recorded in `MANIFEST.md`.

Seat availability:
```json
{
  "success": true,
  "data": {
    "train": { "trainNo": "12904", "trainName": "GOLDEN TEMPLE M", "from": "NZM", "to": "BDTS", "fromStationName": "Delhi Hazrat Nizamuddin", "toStationName": "Mumbai Bandra Terminus", "distance": 1366, "travelClass": "3A", "quota": "GN" },
    "fare": { "baseFare": 1505, "reservationCharge": 40, "superfastCharge": 45, "serviceTax": 80, "totalFare": 1670 },
    "availability": [{ "date": "1-9-2026", "status": "WAITLIST", "availabilityText": "WL 23", "rawStatus": "RLWL31/WL23", "prediction": "73% Chance", "predictionPercentage": 73, "canBook": true }]
  }
}
```

Train info (route item abbreviated to one stop in the docs):
```json
{ "success": true, "data": {
  "trainInfo": { "train_no": "12345", "train_name": "SARAIGHAT EXP", "from_stn_code": "HWH", "to_stn_code": "GHY", "from_time": "16:05", "to_time": "09:40", "running_days": "1111111", "classes": ["1A","2A","3A","SL","GEN","PWD"], "destination_day": 2 },
  "route": [{ "stnCode": "HWH", "stnName": "HOWRAH JN", "arrival": "--", "departure": "16:05", "halt": "0 min", "haltMinutes": 0, "distance": "0", "day": "1", "platform": 15 }]
} }
```

Trains between stations returns `data` as an array of
`{ train_no, train_name, source_stn_code, dstn_stn_code, from_stn_code, to_stn_code, from_time, to_time, travel_time, running_days, distance, halts }`.
There is **no class list** in this response.

## 4. How the adapter treats each uncertainty

| # | Question | Current handling | Live check |
|---|---|---|---|
| Q1 | **Answered (§5): boarding date.** Availability `date` for an intermediate station after midnight: boarding date at the from-station, or train start date? | `AVAILABILITY_DATE_POLICY` (default `SEGMENT_BOARDING_DATE`); affected segments are flagged and a warning is returned | Query a stop pair whose from-station is on route day 2 with both dates; compare echoed `data.availability[].date` |
| Q2 | Train search `date` = departure date at `from` station? | Assumed (D-01); the docs sample (12904 departing NZM 04:00, a route day-2 stop) is consistent | Search a pair whose source is on route day ≥ 2 |
| Q3 | Does plain REST with only `x-api-key` succeed? (The SDK also sends signed `x-irctc-sdk-*` headers.) | **Answered 2026-11-14 (live, Free plan): no.** `GET /api/v1/trains/between/…` returned `403` with `Missing SDK signature headers. To use the API, please upgrade your plan.` Mapped correctly to `AUTH` (never `NOT_AVAILABLE`); key not leaked | Re-run `make test-live` after any plan change |
| Q4 | `availability[].date` format(s) and number of entries | Tolerant parser (`D-M-YYYY`, `DD-MM-YYYY`, ISO, `D Mon YYYY`, `D-Mon-YYYY`); the entry must match the requested date, otherwise `UNKNOWN` | Inspect live payloads |
| Q5 | Vocabulary of RailKit's normalized `status` (only `WAITLIST` documented) | Parsed with the same IR vocabulary as `rawStatus`; disagreement between fields → `UNKNOWN` + anomaly | Collect CNF/AVL/RAC/WL/REGRET examples |
| Q6 | `rawStatus` variants (`AVAILABLE-0012`, `CURR_AVBL-…`, `REGRET/WL`, `TRAIN DEPARTED`, …) | Explicit pattern table; anything else → `UNKNOWN` | Same |
| Q7 | `predictionPercentage` type, range, presence on CNF/AVL; refresh cadence | int/float/numeric-string 0–100 accepted; else null + anomaly; strict `"NN% …"` text fallback only when the field is absent | Same |
| Q8 | `canBook` semantics | Stored verbatim (boolean only); never used for status | Same |
| Q9 | `data.fare.totalFare` currency/basis (per passenger? same for all dates in the response?) | Accepted only if a positive finite number; currency from `RAILKIT_FARE_CURRENCY` (default `INR`, inferred from ₹ in RailKit docs) | Compare with fare lookup once |
| Q10 | Classes accepted by seat availability (docs page 15 vs SDK README 8) | `SUPPORTED_CLASSES` default = intersection of 8 | Try `EA`, `VS` once |
| Q11 | Does `route[]` include non-stopping points? Is `day` the arrival day? Bit order of `running_days`? | All route entries are candidate stops; `day` treated as arrival day and validated against times (inconsistent → `ROUTE_UNVERIFIED`); `running_days` stored, not used for filtering | Compare with an official timetable |
| Q12 | Response for a station pair the train does not serve as a stop pair | Provider 400 → `PROVIDER_REJECTED` (never `NOT_AVAILABLE`) | Query a non-stop pair |
| Q13 | Which responses count against the monthly quota (4xx/5xx/retries)? Billing-cycle boundary? `Retry-After`? | Every attempt counted locally; month boundary = IST calendar month; 429 never retried in-call | Account dashboard |
| Q14 | Caching, storage, display and commercial redistribution rights | **Not stated anywhere.** TTLs are short and configurable; launch gate in doc 06 §8 remains open | Written confirmation from RailKit |
| Q15 | Echo validation: does `data.train.{trainNo,from,to,travelClass,quota}` always echo the request? | Present-and-different → `INVALID_RESPONSE`; absent → accepted with anomaly | Same |

## 5. Live findings

| Date | Plan | Result |
|---|---|---|
| 2026-11-14 | Free (50 req/month, "SDK Access only") | First request rejected: `403 Missing SDK signature headers. To use the API, please upgrade your plan.` |
| 2026-11-14 | Paid (direct REST) | Walkthrough passed twice (about 10 requests). Answers below; payloads in `backend/tests/fixtures/railkit/live/2026-11-14/` and pinned by `tests/unit/providers/test_railkit_live_fixtures.py`. |

### Answers

| # | Answer | Effect on the code |
|---|---|---|
| Q1 | **The boarding date at the segment's from-station.** Train 12248 runs Saturdays only from NZM and reaches RTM on day 2. RTM→BDTS for Sun 29 Nov answered with the next four Sunday run dates; the same query for Sat 28 Nov (the train's start date) was rejected with `400 Unable to process your request`. | Default `SEGMENT_BOARDING_DATE` confirmed and reported as verified (`/meta`); a warning is shown only if `TRAIN_START_DATE` is configured. |
| Q2 | Train search is date-filtered: all 17 returned trains have the requested weekday set in `running_days`. 12904, which boards NZM at 04:00 on its day 2, is listed for the date at the boarding station, consistent with D-01. | None. |
| Q3 | Direct REST with `x-api-key` works on the paid plan; the Free plan returns 403 (above). | None. |
| Q4 | `date` is `D-M-YYYY` without zero padding. The list holds the requested date and the next three **run dates** of that train at that station (consecutive days only for daily trains). | None: the mapper already selects the exact requested date. |
| Q5 | `status` values seen: `WAITLIST`, `AVAILABLE`. | None. |
| Q6 | `rawStatus` seen: `RLWL70/WL56`, `GNWL86/WL60`, `AVAILABLE-0019`; `availabilityText`: `WL 56`, `AVL 19`. All parse. | None. |
| Q7 | `predictionPercentage` is an integer. Waitlists carry e.g. `"82% Chance"`/82; **available seats carry `"Available"`/100.** | Confirms D-03: predictions must not reorder all-available paths. |
| Q8 | `canBook: true` on waitlisted entries — bookable is not confirmed. | None. |
| Q9 | `data.fare` has the documented shape (`totalFare` 1670 for 12904 NZM→BDTS 3A; 645 for 12248 RTM→BDTS CC); no currency field (INR assumed). Per-passenger basis still unconfirmed. | None. |
| Q11 | `route[]` lists stoppages only (every intermediate stop has a halt); `day` is a 1-based string; `"--"` marks origin arrival and terminus departure. `running_days` is **Monday-first** (17/17 trains have the Saturday bit for a Saturday search, against 9/17 if Sunday-first). `trainInfo` also has `prs_classes` (reservable classes only). | None. |
| Q12 | A date the train does not serve for a valid pair returns `400 Unable to process your request`, mapped to `PROVIDER_REJECTED` (never "not available"). Invalid stop pairs remain untested. | None. |
| Q15 | Every response echoed the requested train, stations, class and quota. | None. |
| New | **Train search matches station clusters.** NDLS→BCT returned 17 trains and none ran NDLS→BCT exactly (NZM/DEE/NDLS → BDTS/CSMT/MMCT/PNVL/BSR). Extra fields: `classes_of_travel` (empty), `train_type_name`, Hindi names. | The train list offers a one-click search for the stations each train really uses; recommendations still start and end at the searched stations. |

Still open: Q10 (whether `EA`, `VS`, … are accepted), Q12 for invalid stop pairs, Q13 (what counts against the quota, billing-cycle boundary, `Retry-After`). Q14 (usage rights) is set aside by the product owner.

## 6. Live verification procedure

1. Put `RAILKIT_API_KEY` in the untracked root `.env` (never in source files).
2. Keep `RAILWAY_PROVIDER=mock` for normal development.
3. Run `make test-live` (about 5 requests). It prints a report and writes it, with sanitized
   payloads, to `backend/tests/fixtures/railkit/live/run-<timestamp>/report.json`.
4. Promote useful payloads to a dated folder, add them to `MANIFEST.md`, and pin them with a test.
5. Update section 4 with the answers.
