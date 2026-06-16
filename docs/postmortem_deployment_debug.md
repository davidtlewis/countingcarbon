# Post-mortem: EC2 deployment debugging session (2026-06-16)

## Summary

First live deployment to EC2 took many more iterations than expected. This document records what went wrong, why, and what to take to future projects.

---

## The problems, in order

| # | Symptom | Root cause |
|---|---|---|
| 1 | `invalid number of arguments in 'server_name'` | `prompt()` in deploy.sh didn't capture input when script was piped through bash |
| 2 | 502 Bad Gateway | Gunicorn socket in wrong directory — `/run/` is root-owned; needed `RuntimeDirectory`-created subdirectory |
| 3 | 400 Bad Request | `ALLOWED_HOSTS` empty — same root cause as #1, domain never written to `.env` |
| 4 | No CSS / static 404 | `/home/ubuntu` was `chmod 700`, blocking nginx (`www-data`) from traversing to `staticfiles/` |
| 5 | 403 on all POSTs | allauth rate limiter calls `get_client_ip()` which raises `PermissionDenied` behind a proxy |
| 6 | 500 after fixing 403 | SMTP not configured; `ACCOUNT_EMAIL_VERIFICATION = "mandatory"` caused allauth to attempt email send on signup |

Problems 1–4 are normal first-deploy friction — each was straightforward once visible. The iteration cost came from 5 and 6.

---

## Root cause 1: diagnostic tooling removed mid-debug

When the 403 appeared, `LOGGING` was added to `prod.py` to surface tracebacks — correct move. But when we thought we'd identified the cause (allauth rate limiter), the logging was removed *before the problem was confirmed fixed*. That made the subsequent 500 completely invisible: gunicorn logged `500 145` with no traceback, and there was no way to see what was failing.

**Rule: never remove diagnostic instrumentation until the feature is confirmed working end-to-end.**

---

## Root cause 2: guessing at library API without reading the installed source

Three fixes were attempted for the allauth rate limiter, in sequence:

1. `ACCOUNT_CLIENT_IP_HEADER = "HTTP_X_REAL_IP"` — wrong setting name for this version of allauth
2. `ACCOUNT_RATE_LIMITS = {}` — setting is read, but the short-circuit check doesn't fire where expected
3. Custom `AccountAdapter.get_client_ip()` — correct; reads `X-Real-IP` set by nginx

Each attempt required a full deploy cycle: commit → push → redeploy → reproduce → read logs. That's expensive. The right move on the second failed attempt would have been to read the actual installed source on the server before committing a third guess:

```bash
cat /home/ubuntu/app/.venv/lib/python3.12/site-packages/allauth/core/internal/ratelimit.py
```

That would have shown exactly where the short-circuit is and what the correct override point was — saving at least two iterations.

**Rule: when a library isn't behaving as documented, read the installed source before trying another setting.**

---

## Root cause 3: not thinking one error ahead

The 403 was masking the 500. Once the rate limiter was fixed, the 500 appeared — which made it look like something new had broken. It hadn't: email sending had always been broken, but that code path was never reached while the rate limiter blocked everything first.

This is hard to avoid entirely. The mitigation is: when fixing a blocking error, ask "what will the next error be?" before declaring victory. In this case: fixing IP detection would allow signup to proceed → allauth would attempt to send a verification email → SMTP wasn't configured. That was predictable. Setting `ACCOUNT_EMAIL_VERIFICATION=none` at the same time would have collapsed two iterations into one.

**Rule: ask "once this is fixed, what's the next thing that will fail?"**

---

## Lessons for future projects

| Lesson | Concrete action |
|---|---|
| Keep error logging until fully done | Don't remove `LOGGING` from prod settings until the app is confirmed end-to-end healthy |
| Read installed source before guessing at library config | `cat .venv/lib/python3.12/site-packages/<package>/relevant_file.py` |
| Think one error ahead | When fixing a blocking error, reason about what the next layer will expose |
| Validate deploy script inputs upfront | Print all captured values before doing anything — make them easy to spot and correct |
| Pre-flight checklist for fresh deploys | SMTP, ALLOWED_HOSTS, home dir permissions, socket path — all verifiable before first request |

---

## Cost breakdown

Four of the seven deploy iterations came from just two mistakes: the allauth setting guesses (3 cycles) and the invisible 500 caused by removing logging prematurely (1 cycle). The other three were unavoidable first-deploy discoveries.
