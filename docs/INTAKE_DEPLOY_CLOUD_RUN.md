# Intake Deploy (Cloud Run)

## Quick Start

### 1. Enable APIs
```bash
gcloud services enable run.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  drive.googleapis.com
```

### 2. Create service account
```bash
gcloud iam service-accounts create family-archive-intake \
  --display-name "Family Archive Intake"

# Download the JSON key
gcloud iam service-accounts keys create service-account.json \
  --iam-account family-archive-intake@YOUR_PROJECT_ID.iam.gserviceaccount.com
```

### 3. Store secrets in Secret Manager
```bash
# Service account credentials
gcloud secrets create FAMILY_ARCHIVE_SA_JSON --data-file=service-account.json

# Family registration code (pick something memorable)
echo -n "YourFamilyCode2024" | gcloud secrets create FAMILY_CODE --data-file=-
```

### 4. Deploy to Cloud Run
```bash
cd apps/intake-web

gcloud run deploy family-archive-intake \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars "DRIVE_ROOT_FOLDER_ID=YOUR_FOLDER_ID" \
  --set-secrets "SERVICE_ACCOUNT_JSON=FAMILY_ARCHIVE_SA_JSON:latest,FAMILY_CODE=FAMILY_CODE:latest" \
  --update-env-vars "BASE_URL=https://family-archive-intake-XXXXX-uc.a.run.app"
```

**Note:** After first deploy, copy the URL from the output and re-deploy with the correct `BASE_URL`.

### 5. Share with Family
After deployment, you'll get a URL like:
```
https://family-archive-intake-abc123-uc.a.run.app
```

Share these with your family:
- **Registration URL:** `https://YOUR-URL/register`
- **Family Code:** The code you set in step 3 (share privately via text/email)

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DRIVE_ROOT_FOLDER_ID` | Yes | Google Drive folder ID for uploads |
| `SERVICE_ACCOUNT_JSON` | Yes* | Service account JSON (as string) |
| `SERVICE_ACCOUNT_JSON_PATH` | Yes* | Path to service account JSON file |
| `FAMILY_CODE` | Yes | Secret code for self-registration |
| `BASE_URL` | Yes | Your Cloud Run URL (for redirects) |
| `CONTRIBUTORS_DB_PATH` | No | Path to SQLite DB (default: ./contributors.db) |

*One of `SERVICE_ACCOUNT_JSON` or `SERVICE_ACCOUNT_JSON_PATH` is required.

---

## Important Notes

1. **Share Drive folder with service account**
   - Open your Google Drive folder
   - Click Share → Add the service account email (from service-account.json)
   - Give "Editor" access

2. **Database persistence**
   - Cloud Run is stateless - the SQLite database resets on each deploy
   - For production, consider Cloud SQL or Firestore
   - For small families, this is fine - users can re-register

3. **Custom domain (optional)**
   ```bash
   gcloud run services update family-archive-intake \
     --region us-central1 \
     --update-env-vars "BASE_URL=https://photos.yourfamily.com"
   ```
   Then set up domain mapping in Cloud Run console.

---

## Troubleshooting

**"Registration is not enabled"**
- `FAMILY_CODE` environment variable is not set

**"Invalid link" on upload page**
- User's token not found - they need to re-register
- Or the contributors.db was reset (Cloud Run redeployed)

**Upload fails silently**
- Check Cloud Run logs: `gcloud run logs read family-archive-intake`
- Verify service account has Drive folder access
