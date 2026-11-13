# Contributing

## Branches
| Branch | From | Into | Purpose |
|---|---|---|---|
| `main` | | | released code, tagged `vX.Y.Z`, protected |
| `develop` | `main` | | integration branch, default, protected |
| `feature/#<issue>-<description>` | `develop` | `develop` | new functionality |
| `fix/#<issue>-<description>` | `develop` | `develop` | bug fix |
| `release/<x.y.z>` | `develop` | `main` and `develop` | release preparation |
| `hotfix/#<issue>-<description>` | `main` | `main` and `develop` | urgent production fix |

Descriptions are lowercase words joined by hyphens. Every change starts with an issue.

## Commits
`<type>(#<issue>) - <description>`, type is one of `feat`, `refactor`, `fix`, `chore`, `test`.
Example: `feat(#10) - add sample intake form`.

## Pull requests
- Target `develop` (releases and hotfixes target `main`).
- Title like a commit message, body: one sentence and `Closes #<issue>`.
- `./check.sh` passes before pushing; run `./check.sh e2e` for critical paths.
- A pull request that changes code adds its line to `CHANGELOG.md`, and an entry that changes a
  regulated rule names that rule's id from `docs/compliance.md`.

## Code risk score
`./check.sh` scores every function, backend and frontend, with
`complexity^2 * (1 - coverage)^3 + complexity` (`backend/tools/crap.py`, #196) and fails when one
scores over 10. A fully covered function passes up to complexity 10, an untested one only up to
2, so a third branch asks for a test. The limit came from the measured distribution: on
2026-11-08 the quartiles were 1 to 3 and 4.2% of the functions were over 10. There is no list of
excused functions. Over the limit, cover the branches with tests or split the function: a flat
dispatch of codes becomes a table, a component with many JSX branches comes apart into named
pieces. The check also fails on anything it could not measure, a file with no coverage data or
a complexity that lands on no function.

What it cannot see: coverage comes from the unit tests only, so code that only the e2e suite
runs reads as untested. Every function over the limit on 2026-11-08 was brought under it by unit
tests or a split, none needed e2e coverage, so e2e coverage is not merged in.

## Releases
1. `release/<x.y.z>` from `develop`; only version bumps and release fixes.
2. Pull request into `main`; after merge tag `v<x.y.z>` on `main`.
3. Merge `main` back into `develop`.

Hotfixes follow the same path from `main`.

## Hooks
`tools/install-hooks.sh` installs:
- pre-commit: secrets in staged changes, then `./check.sh`
- commit-msg: the commit message format
- pre-push: the branch name format
