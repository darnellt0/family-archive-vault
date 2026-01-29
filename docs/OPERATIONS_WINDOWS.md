# Operations (Windows)

## Prereqs
- Python 3.11+
- ffmpeg (includes ffprobe). Download from https://ffmpeg.org and add to PATH.
- Git

## Setup
```
python -m venv .venv
.venv\\Scripts\\activate
pip install -r apps/curator-dashboard/requirements.txt
pip install -r services/rosetta/requirements.txt
```

## Run worker
```
set DRIVE_ROOT_FOLDER_ID=YOUR_FOLDER_ID
set SERVICE_ACCOUNT_JSON_PATH=F:\\FamilyArchive\\config\\service-account.json
python services/worker/drive_bootstrap.py
python -m services.worker.worker
```

## Run curator dashboard
```
streamlit run apps/curator-dashboard/curator.py
```

## Run Rosetta generator
```
python services/rosetta/build_site.py
```

## Health + Ops checks
```
http://localhost:5000/api/health
http://localhost:5000/api/version
http://localhost:5000/api/ops/stats
```

Ops stats include backlog counts and last run timestamps. Use this to confirm the worker and Rosetta builder are active.

## Suggested Task Scheduler
- Worker: every 15 minutes
- Rosetta build: nightly (e.g. 2 AM)

## Logs
- `F:\\FamilyArchive\\logs\\worker.log`
- `F:\\FamilyArchive\\logs\\errors\\<drive_id>.log`
