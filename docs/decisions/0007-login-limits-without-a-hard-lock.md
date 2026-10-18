# 0007 Login limits that never lock an account for everyone

Date: 2026-10-18
Status: accepted

## Context
Until #36 an account was locked for 30 minutes after 5 failed logins from any
address, and the right password was refused while it lasted. Anyone could lock
any user out with five requests. The counter was a get plus a set in
`DatabaseCache`, so parallel failures were lost, and the cache's cull deletes
the rows with the lowest keys first, which were the login counters. The client
address came from `X-Forwarded-For` by hop count, so a client that reached the
app port directly chose its own address.

Seen in production Django code (2026-10): a per-account hard lock (zulip,
care without a captcha, allauth for 5 minutes), per-address only (posthog with
django-axes, saleor), which a botnet spreads out, and the client's first
`X-Forwarded-For` value as its address (sentry, saleor, healthchecks, netbox).

## Decision
- The client address is `REMOTE_ADDR`, or the first untrusted hop from the
  right of `X-Forwarded-For` when `REMOTE_ADDR` is one of
  `DJANGO_TRUSTED_PROXIES` (`cultures/core/client_ip.py`, the only reader).
  gunicorn trusts the same list.
- Three counters in `users_loginfailures`, one upsert per failure: per
  (account, address bucket) with a back-off that doubles, per address bucket
  across accounts, per account across addresses. The account counter only puts
  the account "under attack": then a browser with a known-device cookie for
  that account may still try, everyone else gets the 429.
- The known-device cookie is set on every successful login, signed per account
  with the public id and the password hash in the salt (a password change
  revokes it). One browser holds up to five accounts.
- A success deletes its own pair counter only.
- Counter keys are HMACs, the log line names an account reference, never the
  typed name. Staff clear an account's counters in admin, with a reason.

## Consequences
+ An attacker can slow an account down but not lock its owner out of a
  browser the owner used before.
+ Counts are exact under parallel requests and survive a cache flush.
- A first login from a new browser while the account is under attack waits
  for the window (an hour by default) or for staff. There is no password
  reset by email yet, which would be the second way in.
- A stolen known-device cookie removes the account limit for its holder until
  the password changes.
- Behind a proxy the deploy must list the proxy's addresses; startup refuses
  `DJANGO_BEHIND_TLS_PROXY` without them.

Revisit when: password reset by email exists (it should clear the counters
and the user should get a notice when the account goes under attack), or the
app gets a second factor.
