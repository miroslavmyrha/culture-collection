# Conventions

Each rule says how it is enforced: [lint], [types], [test], [review].

## Backend (Django + DRF)
- Apps by domain under `backend/cultures/`; settings in `backend/config/settings/`. [review]
- All writes go through `services.py` (transaction, rules, audit, `on_commit` side effects); all reads through `selectors.py` that take the user. Views and serializers stay thin. [review]
- Viewsets extend `ScopedModelViewSet`/`ScopedReadOnlyViewSet` (`core/api.py`): implement `scoped_queryset()` (rows the user may see) and `has_perm(perm, obj)` (the project's role check), and map every action, `@action` extras included, in `action_perms`. A missing entry, or overriding `get_queryset`, `get_object`, `get_permissions`, `check_*_permissions` or `permission_classes` (also through a mixin) fails at import. Not visible is 404, visible but not permitted is 403. Load objects in actions only with `self.get_object()`. [test]
- Related ids in input use `ScopedRelatedField(model=..., scope=...)`: same scope as reads, same error for missing and forbidden. [review]
- Services raise `cultures.core.exceptions` (`NotFound`, `Forbidden`, `Conflict` 409, `PreconditionFailed` 412, `RuleViolation` 422), never DRF exceptions; the API handler maps them. [review]
- Every error body is the problem shape from `core/errors.py` (`type`, `title`, `status`, `detail`, `code`, `errors[{attr, code, detail}]`), `application/problem+json`. [test]
- Paginated querysets must be ordered; the paginator appends `pk` and caps `limit` at 200. [test]
- Settings read the environment only through `config/env.py` (strict, `*_FILE` secrets). Every startup refusal in `production.py` has a case in `REFUSALS` (`core/tests/test_settings.py`), and every readiness check a breaker in `BREAKERS` (`core/tests/test_health.py`). [test]
- Never `fields = "__all__"`; separate input and output serializers. [review]
- Anonymous state-changing endpoints call `enforce_csrf(request)` (DRF does not check CSRF there). [test]
- Internal integer ids never leave the server; the API uses `public_id`. [test]
- Database constraints for invariants; `on_delete=PROTECT` for anything precious. [review]
- Declare error responses in `extend_schema` so the generated client types know them. [types]
- mypy strict, ruff (security, bugbear, Django rules). [lint] [types]
- Every routed viewset has a `ViewsetContract` test class (`core/testing/`); an API view without an object scope goes into the reviewed `EXEMPT` list of `core/tests/test_contract_coverage.py` as an `Exemption(reason, url_name, tests)`, and the named test file must call that URL. [test]
- An anonymous (`AllowAny`) view with an unsafe method gets a throttle keyed on the client address (`ClientIdentMixin`) with its own scope and rate, like `LoginThrottle`. [test]
- Shared test tools come from `cultures.core.testing` (`logged_in`, `assert_problem`, `run_before`, `ViewsetContract`), never copied into an app. Each tool, and each guard or fixture of the root `conftest.py`, has a self-test listed in `SELF_TESTS` (`core/tests/test_testing_tools.py`) that runs it on a broken target. List endpoints keep an exact query count in the app's `tests/query_counts.json` (`query_baseline` fixture; rewrite with `UPDATE_QUERY_COUNTS=1 pytest cultures/<app>/tests` and review the diff). [test]
- Tests run only with `config.settings.test` (forced by `--ds`, guarded in the root `conftest.py`). Email goes through `MAILERS`, never the deprecated `EMAIL_*` connection settings. [test]

## Contract between backend and frontend
- Anonymous requests get 401 (`WWW-Authenticate: Session realm="api"`); 403 means logged in but not allowed, or a CSRF failure.
- CSRF cookie: `csrftoken` in development, `__Host-csrftoken` in production (session cookie `__Host-sessionid`). The SPA reads whichever exists and sends it as `X-CSRFToken`.
- Every response carries `X-Request-ID`; show it in error messages so users can report it.
- Errors: the problem shape above; field errors by dotted `attr`.

## Frontend (React + TypeScript)
- Features in `frontend/src/features/<domain>/{api,components,schemas.ts}`; pages are thin. [review]
- Import boundaries in `.oxlintrc.json`: features import no other feature, app, pages or routes; shared code (`lib`, `components`, `hooks`) imports none of them; `dompurify` only in `lib/sanitize.ts`. `frontend/tools/lint-boundaries.test.ts` probes every boundary, so a config change that drops one fails. [lint] [test]
- Server state via TanStack Query with key factories (`api/keys.ts`); never fetch in effects. [lint] [review]
- API calls only through `src/lib/api.ts` (typed from `openapi.yml`, adds CSRF). Regenerate types with `npm run api:types` after backend schema changes. [types]
- HTML only through `components/SafeHtml.tsx`; links through `safeHref`; `window.open` only via `openExternal`; no `localStorage` outside `lib/storage.ts` (preferences only). [lint]
- Every screen handles loading, error, empty and data; every failed mutation shows a message. [review] [test]
- strict TypeScript with `noUncheckedIndexedAccess`; type-aware oxlint with `--deny-warnings`. [lint] [types]

## Checks before every commit
`./check.sh` (also run by the pre-commit hook from `tools/install-hooks.sh`): gitleaks on changes, missing and risky migrations (django-migration-linter, warnings are errors), API schema and TS types up to date (`./sync-api.sh` fixes), `check --deploy` with production settings, ruff, mypy, pytest, tsc, oxlint, Vitest. `./check.sh e2e` adds Playwright, `./check.sh audit` adds pip-audit and npm audit. [test]
Then read the staged diff (scope, migrations SQL, API breaks, security of the diff) and commit explicit paths with a short English message.

## Git flow
Issue first; branch `feature|fix|hotfix/#<issue>-<description>` (or `release/<x.y.z>`) from `develop` (hotfix from `main`); commits `<type>(#<issue>) - <description>`; pull request into `develop` with `Closes #<issue>`. Hooks enforce names and messages. [lint] Details: CONTRIBUTING.md.
