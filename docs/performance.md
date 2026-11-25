# Performance at collection scale

Measured for #71 on 2026-11-25, on a development box (Docker, PostgreSQL in a container), lab BAC
after `seed_dev` and `seed_scale` with its defaults: 5,030 strains, 50,027 vials, 505 boxes, one
in ten strains regulated. The seed took 676 s; `audit_reconcile` reported 0 alarms afterwards.

## How to measure

    docker compose run --rm -e DEV_PASSWORD=... backend python manage.py seed_dev
    docker compose run --rm backend python manage.py seed_scale          # --strains, --vials
    docker compose run --rm backend python tools/measure_scale.py        # API: time and queries
    cd frontend && E2E_PORT=... VITE_API_PROXY=http://localhost:<backend> \
      npx playwright test -c playwright.perf.config.ts                   # browser: time to content

`measure_scale.py` signs in as the lab manager, warms each request once, then reports the median of
five. The browser script (`e2e/perf/`, not part of the e2e suite) times from navigation to the
screen's first content row or heading on a production build.

## API, 5,000 strains

Measured after 95 % of the batches were released (by SQL on the throwaway database), as in a
working collection; with every batch waiting the numbers were the same but the overview.

| screen | ms (median of 5) | queries |
|---|---:|---:|
| strain list | 26 | 13 |
| strain list, search | 44 | 13 |
| vial list | 45 | 15 |
| deposit list | 32 | 12 |
| request list | 18 | 12 |
| search, many hits ("Bacillus", about 4,500 matches) | 103 | 12 |
| search, one strain (its number) | 62 | 12 |
| storage tree (every unit, 505 boxes) | 96 | 12 |
| box grid | 48 | 12 |
| strain detail | 28 | 17 |
| material: passages, batches, vials | 24, 22, 30 | 12, 12, 15 |
| home overview | 136 (304 before ANALYZE) | 25 |

## Browser, time to content

| screen | ms |
|---|---:|
| home | 910 |
| strain list | 384 |
| deposit list | 338 |
| request list | 357 |
| storage tree | 467 |
| box | 371 |
| strain page | 462 |
| strain material | 482 |

The home page loads the overview and the lab list after sign-in; the other screens are around
0.4 s, most of it the page's code and the first paint, not the API.

## What the numbers showed

- No N+1: every query count is fixed by the page size and stays the same at 50 and 500 strains.
- The one slow query was the home overview's batches waiting for checks: 171 ms on the plan for
  empty tables right after the bulk seed, 15 ms after `ANALYZE`. A partial index on waiting
  batches gave 16 to 13 ms, not worth a migration. `seed_scale` now ends with `ANALYZE`, as
  autovacuum does for a collection that grows slowly.
- Search ranks every matching row: about 0.02 ms per row, linear. A trigram index would not help
  a term most strains match.
- The storage tree returns every unit of the lab: 96 ms for 505 boxes and their racks, unpaginated by design (the
  tree needs all of them).

## Budgets in CI

The `scale` job (`tools/scale-check.sh`) seeds 50 strains, measures, adds up to 500 and measures
again. It fails when a screen's query count differs between the two sizes, when a screen answers
other than 200, or when a screen takes more than 1,500 ms. The count is exact and the same on any
runner, so it is the real regression gate. Time on a shared runner varies by a factor of two or
more, so the budget is ten times the largest measured time: it catches a missing index or a lost
`select_related` on a large table, not a drift. The exact counts on small data stay in the
`query_counts.json` baselines.
