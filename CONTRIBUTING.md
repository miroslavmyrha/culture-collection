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
