# 0001 Custom user model and public UUIDs

Date: 2026-10-16
Status: accepted

## Context
Changing the user model or primary key type after the first migration is very
costly. Sequential ids in URLs let anyone enumerate records.

## Decision
A custom `User` from the first migration. Internal integer primary keys; the
API and URLs use a separate `public_id` UUID on every exposed model.

## Migration impact
Both are in the initial migrations; reversing them later means rewriting all
foreign keys.

## Consequences
+ No enumeration through the API; internal joins stay on small integers.
- Two identifiers per row; serializers must never expose `id`.

Revisit when: never for the user model; for ids only if a data store without
integer keys is adopted.
