# 0003 Stack defaults of the scaffold

Date: 2026-10-16
Status: proposed (confirm or replace per project)

## Context
The scaffold was verified with a set of defaults; some are project decisions.

## Decision
- API: DRF + drf-spectacular (alternative: Django Ninja).
- Router: TanStack Router, code-based (alternative: React Router).
- Server state: TanStack Query; forms: React Hook Form + zod.
- UI library: none in the scaffold (choose: MUI, shadcn/ui + Tailwind, Mantine).
- Lint: the official Vite template's oxlint, type-aware.
- Tests: pytest-django + model-bakery (backend), Vitest + Testing Library +
  MSW (frontend), Playwright for end-to-end (chosen over Cypress for WebKit,
  free parallel runs and the trace viewer).

## Consequences
Replace any default with a new ADR before building features on it.
