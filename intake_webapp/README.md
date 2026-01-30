# Intake Web (Cloud Run)

Mobile-first intake uploader that writes manifests to Google Drive and supports resumable uploads.

## Local dev

```bash
cd apps/intake-web
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
set DRIVE_ROOT_FOLDER_ID=YOUR_FOLDER_ID
set INTAKE_TOKEN_MAP_PATH=token_map.json
set SERVICE_ACCOUNT_JSON_PATH=F:\FamilyArchive\config\service-account.json
uvicorn main:app --reload --port 8080
```

Open http://localhost:8080/u/<token> using a token from token_map.json.

## Env vars

- `DRIVE_ROOT_FOLDER_ID` (required)
- `INTAKE_TOKEN_MAP_PATH` (default: token_map.json)
- `SERVICE_ACCOUNT_JSON` (raw JSON string, preferred for Cloud Run)
- `SERVICE_ACCOUNT_JSON_PATH` (file path for local dev or secret mount)
- `MAX_FILE_SIZE_BYTES` (default: 25GB)
- `MAX_FILES_PER_BATCH` (default: 100)
- `RATE_LIMIT_PER_MIN` (default: 120)

## Auth modes

The intake app supports two auth modes:
1. `SERVICE_ACCOUNT_JSON` (env var string)
2. `SERVICE_ACCOUNT_JSON_PATH` (file path)

If both are set, `SERVICE_ACCOUNT_JSON` takes priority.

## Resumable uploads

Uploads are sent to Google Drive using resumable upload sessions.
- Session URLs + byte offsets are stored server-side and in localStorage on the client.
- If a mobile browser refreshes or drops connection, the next chunk resumes at the last confirmed offset.

To verify:
1. Start a large video upload.
2. Disconnect network or refresh page mid-upload.
3. Re-open `/u/<token>` and retry. The upload resumes instead of starting at byte 0.

## Cloud Run

See `/docs/INTAKE_DEPLOY_CLOUD_RUN.md` for the exact deployment steps.
