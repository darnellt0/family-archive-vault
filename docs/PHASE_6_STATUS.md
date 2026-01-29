# Phase 6 Status

Status: **NOT GO-LIVE READY** until acceptance tests below pass.

## Acceptance tests
1. `python dashboard_v12_api.py` exposes:
   - `/api/health`
   - `/api/ops/stats`
   - `/api/version`
2. Intake auth modes:
   - Local uses `SERVICE_ACCOUNT_JSON_PATH`
   - Cloud Run uses `SERVICE_ACCOUNT_JSON` from Secret Manager
3. Resumable uploads:
   - Interrupt a large upload mid-way
   - Resume without starting at byte 0
   - File is intact in Drive

## Known limitations (track here)
- None reported yet.

Once all three acceptance tests pass, mark status GO-LIVE READY.
