# Plan: pr/3-tls Review Fixes

**Branch:** `pr/3-tls` (rebased on `origin/main` after pr/2 merge)  
**Problem:** The 9 commits have the original (pre-review) TLS implementation. All review fixes were lost during rebase (never committed).  
**Goal:** Re-apply all fixes, commit, push.

## Steps

1. `constants.py` — add `TLS_CERT_DIR = Path("/etc/dovecot/private")`
2. `charm.py` — delete `_on_certificate_available`, create `_setup_tls`, wire `certificate_available` → `_reconcile`, use `TLS_CERT_DIR` constant, remove `tls_enabled` from template context
3. `dovecot.conf.tmpl` — always `ssl = required`, remove conditional and stale TODO
4. `test_charm.py` — delete 3 old TLS tests, replace `_install` patches with `_setup_tls`, add comments
5. `test_storage.py` — add `_setup_tls` patches to 6 tests reaching ActiveStatus
6. `tests/unit/test_tls.py` (new) — 6 tests following SKILL.md principles
7. `tests/integration/test_tls.py` — fix copyright, remove sleeps, fix stat quoting, add ssl=required assertion
8. `docs/explanation/charm-state-diagrams.md` — update for TLS states
9. Remove `dovecot-charm-state-diagrams.rst` if exists
10. Run `tox -e fmt,unit,lint` — all must pass
11. Commit and push
