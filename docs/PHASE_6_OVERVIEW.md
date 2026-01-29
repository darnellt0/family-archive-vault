# Phase 6 Overview

This repo now includes:
- Intake Web App (Cloud Run) in `apps/intake-web`
- Local worker pipeline in `services/worker`
- Curator dashboard in `apps/curator-dashboard`
- Rosetta Stone v2 generator in `services/rosetta`

Key entrypoints:
- Backend API: `python dashboard_v12_api.py`
- Worker: `python -m services.worker.worker`
- Curator dashboard: `streamlit run apps/curator-dashboard/curator.py`
- Rosetta generator: `python services/rosetta/build_site.py`

See:
- `docs/DRIVE_SETUP.md`
- `docs/INTAKE_DEPLOY_CLOUD_RUN.md`
- `docs/OPERATIONS_WINDOWS.md`

Smoke scripts:
- `tools/phase6/smoke_drive_schema.py`
- `tools/phase6/smoke_intake.py`
- `tools/phase6/smoke_worker_db.py`
- `tools/phase6/smoke_whisper_guardrails.py`
- `tools/phase6/smoke_rosetta.py`
