# Deploying R2 Sync Worker to Railway

## Quick Deploy

1. **Create a new service in Railway**
   - Go to your Railway project
   - Click "New Service" → "GitHub Repo"
   - Select your FamilyArchive repo
   - Set the root directory to: `services/r2_sync`

2. **Add Environment Variables**

   Copy these from your existing intake-webapp service:
   ```
   R2_ACCOUNT_ID=<your_cloudflare_account_id>
   R2_ACCESS_KEY_ID=<r2_access_key>
   R2_SECRET_ACCESS_KEY=<r2_secret_key>
   R2_BUCKET_NAME=family-archive-uploads
   ```

   Add Google Drive credentials (copy from existing service or create new):
   ```
   SERVICE_ACCOUNT_JSON=<paste entire service account JSON here>
   DRIVE_ROOT_FOLDER_ID=<your_drive_folder_id>
   ```

   Optional settings:
   ```
   R2_SYNC_POLL_INTERVAL=300          # Sync every 5 minutes (default)
   R2_SYNC_DELETE_AFTER=true          # Delete from R2 after sync (default)
   R2_SYNC_BATCH_SIZE=20              # Files per sync cycle (default)
   ```

3. **Deploy**
   - Railway will automatically build and deploy
   - Check logs to verify it's running

## Environment Variables Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `R2_ACCOUNT_ID` | Yes | Cloudflare account ID |
| `R2_ACCESS_KEY_ID` | Yes | R2 API access key |
| `R2_SECRET_ACCESS_KEY` | Yes | R2 API secret key |
| `R2_BUCKET_NAME` | No | Bucket name (default: `family-archive-uploads`) |
| `SERVICE_ACCOUNT_JSON` | Yes | Google service account JSON content |
| `DRIVE_ROOT_FOLDER_ID` | Yes | Google Drive folder ID |
| `R2_SYNC_POLL_INTERVAL` | No | Seconds between sync cycles (default: 300) |
| `R2_SYNC_DELETE_AFTER` | No | Delete from R2 after sync (default: true) |
| `R2_SYNC_BATCH_SIZE` | No | Max files per cycle (default: 20) |

## Verify It's Working

1. Upload a test photo via the memorial site
2. Check Railway logs - you should see:
   ```
   Starting R2 sync cycle
   Found 1 files to sync
   Uploaded photo.jpg to Drive: <file_id>
   Deleted photo.jpg from R2
   Created manifest: r2sync_..._Memorial.json
   ```
3. Check Google Drive `INBOX_UPLOADS/Memorial_Guest_UPLOADS/` folder

## Troubleshooting

**"No service account credentials found"**
- Ensure `SERVICE_ACCOUNT_JSON` is set with the full JSON content
- Make sure there are no extra quotes or escaping issues

**"R2 credentials not configured"**
- Check all R2 environment variables are set
- Verify they match the credentials in your Cloudflare dashboard

**"Drive schema not found"**
- Ensure `DRIVE_ROOT_FOLDER_ID` is set correctly
- The service account must have access to this folder
