---
name: PTB JobQueue + APScheduler version pinning
description: python-telegram-bot v21 JobQueue requires APScheduler >=3.6.3,<3.11; newer versions make job_queue None
---

## Rule
When using JobQueue in python-telegram-bot v21.x, APScheduler must be pinned to `>=3.6.3,<3.11`. APScheduler 3.11+ breaks the integration silently — `app.job_queue` returns `None` and `.run_repeating()` raises `AttributeError`.

**Why:** PTB v21 uses APScheduler internals that changed in 3.11. The extras `python-telegram-bot[job-queue]` enforce this pin, but pip-installing `apscheduler` directly installs the latest.

**How to apply:**
- Always install with: `pip install "apscheduler>=3.6.3,<3.11"`
- Guard the call anyway: `if app.job_queue is not None:` before `.run_repeating()`
- Confirmed working version: apscheduler 3.10.4
