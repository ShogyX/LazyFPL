## Summary

<!-- What does this PR change and why? -->

## Changes

<!-- Bullet the notable changes. -->
-

## Testing

- [ ] `pytest -q` passes (backend; needs the `fpl_test` Postgres DB)
- [ ] `cd frontend && npm run build` passes (frontend type-check + build)
- [ ] Leakage audit still clean if `model/`, `features/`, or `backtest/` changed
      (`fpl features audit --seasons <season>`)

## Checklist

- [ ] No secrets / `.env` committed; new secrets use `SecretStr` and are never logged
- [ ] DB schema changes have a matching Alembic migration **and** mirror in `db/models.py`
- [ ] Updated docs / README if behaviour or setup changed
