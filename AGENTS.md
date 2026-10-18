# Conventions

Each rule says how it is enforced: [lint], [types], [test], [review].

## Backend (Django + DRF)
- Apps by domain under `backend/cultures/`; settings in `backend/config/settings/`. [review]
- All writes go through `services.py` (transaction, rules, audit, `on_commit` side effects); all reads through `selectors.py` that take the user. Views and serializers stay thin. [review]
- Audit trail (ADR 0005, `cultures.audit`): an audited write runs in `with audited_atomic():` (never plain `transaction.atomic()`) and records `record_event()` or, for many objects, `record_batch()` inside it. It raises without an audit context: requests have one, commands and tasks enter `audit_context(...)`, data migrations `migration_audit(...)`. Event types are registered in `audit/registry.py`. [test]
- Never `QuerySet.update()`, `bulk_create()` or raw SQL on an audited model outside its app's services: the row trigger records it, but with no event that explains it. [review]
- Every regulated table has an entry in `ROW_AUDITED_TABLES` (each column audited, excluded or secret: noise is excluded, secrets such as the password hash are `secret`, stored in no row but recorded as changed with the marker `"redacted"`) and a migration with `attach_row_audit()` using the same values; `audit/tests/test_invariants.py` compares both with `pg_trigger` and the real columns, so a new column fails until it is classified. Audit tables are append-only: no code updates or deletes them. [test]
- Django admin writes through services too: every ModelAdmin of a model in `ROW_AUDITED_TABLES`, or with an inline of one, overrides `save_model` (and `save_formset` when it has inlines) to call services inside `audit_context(channel=Channel.WEB, actor=<request.user>)`, and allows no delete unless `delete_model` and `delete_queryset` call a service. `audit/tests/test_admin_writes.py` walks the admin site. [test]
- Users change only through `users/services.py`: `user_create`, `user_update` (profile fields), `user_activate`, `user_deactivate`, `user_set_staff` and `user_set_superuser` (each its own event, reason required), `user_set_password` (the event holds no value). Admin, commands and seeds call them. `createsuperuser` and `changepassword` are the project's own commands (`cultures.users` comes before `django.contrib.auth` in `INSTALLED_APPS`), and `User.objects.create_superuser` needs an audit context with a reason. Users are never deleted. [test]
- Every login entry point has the API login's limits: the per-IP `LoginThrottle` (one budget shared by all of them) and the per-account `login_limits`. The admin login gets them from `users/admin_site.py`. [test]
- Viewsets extend `ScopedModelViewSet`/`ScopedReadOnlyViewSet` (`core/api.py`): implement `scoped_queryset()` (rows the user may see) and `has_perm(perm, obj)` (the project's role check), and map every action, `@action` extras included, in `action_perms`. A missing entry, or overriding `get_queryset`, `get_object`, `get_permissions`, `check_*_permissions` or `permission_classes` (also through a mixin) fails at import. Not visible is 404, visible but not permitted is 403. Load objects in actions only with `self.get_object()`. [test]
- Lab scope (ADR 0006, `cultures.labs`): roles per lab (viewer < technician < curator < manager) map to permissions only in `labs/permissions.py` (`GRANTS`, cumulative); a new feature adds its permissions there. Checks use the request's access object (`access_of(request)`: `can(perm, lab_id)`, `labs_with(perm)`), never `is_superuser` or `is_staff`. Every model with a `lab` foreign key uses a `LabScopedQuerySet` and reads through `for_access(access, perm)`; `labs/tests/test_scoping.py` walks the app registry. The service copies `lab` from the URL or the parent, never from input. [test]
- Membership changes go through `labs/services.py`: `member_*` for lab managers (grant at most your own role, re-checked under the lab lock), `membership_*` and `lab_*` for staff in admin and commands; both keep the last manager. Lock the lab row before memberships. [test]
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
- Import boundaries in `.oxlintrc.json`: features import no other feature, app, pages or routes; shared code (`lib`, `components`, `hooks`) imports none of them; `dompurify` only in `lib/sanitize.ts`; `@mui/*` and `@emotion/*` only in `components/ui` and `app/` (ADR 0004), everything else imports from `@/components/ui`. `frontend/tools/lint-boundaries.test.ts` probes every boundary, so a config change that drops one fails. [lint] [test]
- Selects in forms are `SelectField` from `@/components/ui`: a native `<select>` on `TextField`'s wiring, so `{...register(name)}` works and the ref is the `<select>`. Screens hide actions the role may not do (`canManageMembers`, `grantableRoles` in `features/labs/schemas.ts`); the server still refuses them, and tests cover both. [test]
- Server state via TanStack Query with key factories (`api/keys.ts`); never fetch in effects. [lint] [review]
- Form fields are `TextField` from `@/components/ui` with `{...register(name)}`: label, hint and error wired, the ref on the input so the first invalid field gets focus. [test]
- A session starts or ends only through `resetSessionCache` (`features/auth/api/cache.ts`): login, logout and the 401 handler. Never `queryClient.clear()`: it destroys the me query under the always-mounted shell, which then shows the previous user. [test]
- API calls only through `src/lib/api.ts` (typed from `openapi.yml`, adds CSRF). Regenerate types with `npm run api:types` after backend schema changes. [types]
- HTML only through `components/SafeHtml.tsx`; links through `safeHref`; `window.open` only via `openExternal`; no `localStorage` outside `lib/storage.ts` (preferences only). [lint]
- Every screen handles loading, error, empty and data; every failed mutation shows a message. [review] [test]
- strict TypeScript with `noUncheckedIndexedAccess`; type-aware oxlint with `--deny-warnings`. [lint] [types]

## Checks before every commit
`./check.sh` (also run by the pre-commit hook from `tools/install-hooks.sh`): gitleaks on changes, missing and risky migrations (django-migration-linter, warnings are errors), API schema and TS types up to date (`./sync-api.sh` fixes), `check --deploy` with production settings, ruff, mypy, pytest, tsc, oxlint, Vitest. `./check.sh e2e` adds Playwright, `./check.sh audit` adds pip-audit and npm audit. [test]
Then read the staged diff (scope, migrations SQL, API breaks, security of the diff) and commit explicit paths with a short English message.

## Git flow
Issue first; branch `feature|fix|hotfix/#<issue>-<description>` (or `release/<x.y.z>`) from `develop` (hotfix from `main`); commits `<type>(#<issue>) - <description>`; pull request into `develop` with `Closes #<issue>`. Hooks enforce names and messages. [lint] Details: CONTRIBUTING.md.
