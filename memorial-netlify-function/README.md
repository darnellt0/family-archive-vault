# Memorial Site → Family Archive Upload Integration

This connects the Ruth Tomlinson Brown memorial site to the Family Archive photo storage.

## Setup Instructions

### Step 1: Add Environment Variables to Netlify

Go to your Netlify dashboard for ruthtomlinsonbrown.com:
1. Site settings → Environment variables
2. Add these variables (get values from your Railway Family Archive deployment):

```
R2_ACCOUNT_ID=your_cloudflare_account_id
R2_ACCESS_KEY_ID=your_r2_access_key
R2_SECRET_ACCESS_KEY=your_r2_secret_key
R2_BUCKET_NAME=family-archive-uploads
```

**To find these values:**
- Go to Railway dashboard → family-archive-vault → Variables
- Copy the R2 values from there

### Step 2: Add the Netlify Function

**Option A: If your memorial site is in a Git repo**
1. Copy the `netlify/` folder and files to your repo
2. Copy `package.json` and `netlify.toml` to the root
3. Commit and push - Netlify will auto-deploy

**Option B: If using Netlify's file upload**
1. Download this folder
2. Drag the `netlify/` folder into your site's deploy

### Step 3: Update the Memorial Site JavaScript

Find the photo upload JavaScript in your memorial site's HTML and replace it with the code in `MEMORIAL_SITE_UPDATE.js`.

The key change is replacing the fake timeout with a real fetch to:
```
/.netlify/functions/upload
```

### Step 4: Test It

1. Go to ruthtomlinsonbrown.com
2. Upload a photo
3. Check https://family-archive-vault-production.up.railway.app/gallery
4. The photo should appear under "Photos from Memorial_Guest"

## File Structure

```
memorial-netlify-function/
├── netlify/
│   └── functions/
│       └── upload.js          # The serverless function
├── package.json               # Dependencies (AWS SDK for R2)
├── netlify.toml               # Netlify config
├── MEMORIAL_SITE_UPDATE.js    # JS code to add to memorial site
└── README.md                  # This file
```

## Troubleshooting

**"Storage not configured" error:**
- Check that all 4 R2 environment variables are set in Netlify

**Photos not appearing in gallery:**
- Check Railway logs for the Family Archive
- Make sure R2_BUCKET_NAME matches in both projects

**CORS errors:**
- The function includes CORS headers, but make sure you're calling from the same domain

## How It Works

1. User selects photos on memorial site
2. JavaScript sends photos to `/.netlify/functions/upload`
3. Netlify Function uploads to Cloudflare R2 bucket
4. Family Archive gallery reads from the same R2 bucket
5. Photos appear in the gallery!
