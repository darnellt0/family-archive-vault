# Deployment Guide

Options for deploying the Family Archive Vault intake web app.

## Option 1: Docker Compose (Recommended)

### Prerequisites
- Docker Desktop for Windows
- Service account JSON key
- Configured .env file

### Setup

1. **Create secrets directory:**
```cmd
mkdir secrets
copy C:\path\to\service-account.json secrets\service-account.json
```

2. **Build and run:**
```cmd
docker-compose up -d
```

3. **Check logs:**
```cmd
docker-compose logs -f intake
```

4. **Stop:**
```cmd
docker-compose down
```

### Accessing

- Local: `http://localhost:8000`
- Network: `http://YOUR_LOCAL_IP:8000`

### Notes
- Only the intake web app runs in Docker
- Worker and curator must run locally for GPU access
- Upload chunks stored in Docker volume

## Option 2: Cloud Deployment

### Railway.app

1. **Create Railway account**
2. **New Project → Deploy from GitHub**
3. **Add environment variables:**
   - All vars from `.env`
   - Add `SERVICE_ACCOUNT_JSON` with full JSON content
4. **Update Dockerfile** to read from env:
   ```dockerfile
   ENV SERVICE_ACCOUNT_JSON=${SERVICE_ACCOUNT_JSON}
   ```
5. **Deploy**

**URL:** Railway provides HTTPS URL automatically

### Heroku

1. **Install Heroku CLI**
2. **Login:**
   ```cmd
   heroku login
   ```
3. **Create app:**
   ```cmd
   heroku create family-archive-vault
   ```
4. **Set environment variables:**
   ```cmd
   heroku config:set DRIVE_ROOT_FOLDER_ID=your_folder_id
   heroku config:set SERVICE_ACCOUNT_JSON="$(cat secrets/service-account.json)"
   heroku config:set INTAKE_SECRET_KEY=your_secret
   ...
   ```
5. **Deploy:**
   ```cmd
   git push heroku main
   ```

**URL:** `https://family-archive-vault.herokuapp.com`

### DigitalOcean App Platform

1. **Create account**
2. **Create App → Docker Hub or GitHub**
3. **Configure environment variables**
4. **Deploy**

**Cost:** ~$5/month for basic droplet

## Option 3: Self-Hosted with Cloudflare Tunnel

Keep everything local but accessible via public URL.

### Setup

1. **Install Cloudflare Tunnel:**
   ```cmd
   winget install Cloudflare.cloudflared
   ```

2. **Login:**
   ```cmd
   cloudflared tunnel login
   ```

3. **Create tunnel:**
   ```cmd
   cloudflared tunnel create family-archive
   ```

4. **Configure tunnel:**

Create `cloudflared-config.yml`:
```yaml
tunnel: family-archive
credentials-file: C:\Users\YourName\.cloudflared\UUID.json

ingress:
  - hostname: family-archive.yourdomain.com
    service: http://localhost:8000
  - service: http_status:404
```

5. **Run tunnel:**
```cmd
cloudflared tunnel --config cloudflared-config.yml run family-archive
```

6. **Add DNS record** in Cloudflare dashboard

**URL:** `https://family-archive.yourdomain.com`

**Advantages:**
- No port forwarding
- Automatic HTTPS
- Free tier available
- Keeps worker local with GPU

## Option 4: Traditional VPS

### Example: DigitalOcean Droplet

1. **Create droplet** (Ubuntu 22.04)
2. **SSH into droplet**
3. **Install Docker:**
   ```bash
   curl -fsSL https://get.docker.com -o get-docker.sh
   sudo sh get-docker.sh
   ```
4. **Upload files:**
   ```cmd
   scp -r family-archive-vault root@your-ip:/root/
   ```
5. **SSH and run:**
   ```bash
   cd /root/family-archive-vault
   docker-compose up -d
   ```

**Configure firewall:**
```bash
ufw allow 8000/tcp
ufw enable
```

**Setup HTTPS with Caddy:**

Add to `docker-compose.yml`:
```yaml
  caddy:
    image: caddy:latest
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - caddy-data:/data
```

Create `Caddyfile`:
```
family-archive.yourdomain.com {
    reverse_proxy intake:8000
}
```

## Security Considerations

### For Production

1. **Enable HTTPS:**
   - Use Cloudflare, Caddy, or nginx with Let's Encrypt
   - Never expose HTTP on public internet

2. **Restrict access:**
   - Use firewall rules
   - Consider IP whitelisting
   - Add basic auth or OAuth

3. **Rate limiting:**
   - Already configured in app
   - Consider adding Cloudflare rate limiting

4. **Monitor logs:**
   - Setup log aggregation
   - Alert on errors

5. **Backup:**
   - Regular database backups
   - Google Drive is primary backup

6. **Update regularly:**
   ```cmd
   pip install --upgrade -r requirements.txt
   ```

### Environment Variables in Production

**Never commit `.env` to git!**

Use platform-specific secrets:
- Railway: Environment variables
- Heroku: Config vars
- Docker: Secrets or env_file
- VPS: .env file with restricted permissions

## Monitoring

### Health Checks

**Intake app:**
```bash
curl http://localhost:8000/api/health
```

**Expected:**
```json
{
  "status": "healthy",
  "drive_connected": true,
  "active_sessions": 0
}
```

### Uptime Monitoring

Use services like:
- UptimeRobot (free)
- Pingdom
- StatusCake

Monitor: `http://your-domain.com/api/health`

### Logs

**Docker:**
```cmd
docker-compose logs -f intake
```

**Local:**
```cmd
type F:\FamilyArchive\logs\worker_*.log
```

## Scaling Considerations

### Multiple Workers

For faster processing, run multiple workers:

1. **Each worker needs:**
   - Own GPU (or CPU)
   - Own cache directory
   - Shared database

2. **Configure:**
```bash
# Worker 1
LOCAL_CACHE=F:\FamilyArchive\cache1
GPU_DEVICE_ID=0

# Worker 2
LOCAL_CACHE=F:\FamilyArchive\cache2
GPU_DEVICE_ID=1
```

3. **Run:**
```cmd
# Terminal 1
set LOCAL_CACHE=F:\FamilyArchive\cache1
python -m worker.main

# Terminal 2
set LOCAL_CACHE=F:\FamilyArchive\cache2
python -m worker.main
```

### Load Balancing

For multiple intake instances:

```yaml
# docker-compose.yml
services:
  intake1:
    build: .
    ...
  intake2:
    build: .
    ...
  nginx:
    image: nginx:latest
    ports:
      - "80:80"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
```

## Backup Strategy

### Automated Backups

**Windows Task Scheduler:**

Create `backup.bat`:
```batch
@echo off
set BACKUP_DIR=F:\FamilyArchive\backups\%date:~-4,4%%date:~-10,2%%date:~-7,2%
mkdir %BACKUP_DIR%

copy F:\FamilyArchive\db\archive.db %BACKUP_DIR%\
copy .env %BACKUP_DIR%\

echo Backup complete: %BACKUP_DIR%
```

Schedule daily at 2 AM.

### Google Drive Backup

All critical data is already in Drive:
- Originals in ARCHIVE/
- Metadata in METADATA/sidecars_json/
- Rosetta Stone site in ROSETTA_STONE/

**To recover system:**
1. Reinstall Family Archive Vault
2. Configure with same Drive folder
3. System rebuilds from sidecars

## Cost Estimates

### Self-Hosted (Recommended)
- **Cost:** $0 (your hardware + internet)
- **Pros:** Full control, GPU access, no monthly fees
- **Cons:** Requires home PC running, power costs

### Cloud VM (Mixed)
- **Intake:** Railway/Heroku (~$5-10/month)
- **Worker:** Local (your PC)
- **Pros:** Reliable uploads, GPU locally
- **Cons:** Split setup, some costs

### Full Cloud
- **Not recommended** due to GPU requirements
- AWS GPU instances: $400+/month
- Alternative: Disable GPU features, use CPU only

### Google Drive Storage
- **15 GB free**
- **100 GB:** $2/month
- **2 TB:** $10/month
- Estimate: 1-2 TB for large family archive

## Maintenance

### Daily
- Check worker is running
- Review any error logs

### Weekly
- Run face clustering: `python -m scripts.cluster_faces`
- Review curator dashboard

### Monthly
- Backup database
- Update dependencies if needed
- Generate fresh Rosetta Stone

### Yearly
- Review storage usage
- Archive old Rosetta versions
- Update contributor tokens if needed

---

**Recommendation for most users:**
- Intake: Docker Compose or Cloudflare Tunnel
- Worker: Local with GPU
- Curator: Local
- Rosetta: Scheduled local generation
