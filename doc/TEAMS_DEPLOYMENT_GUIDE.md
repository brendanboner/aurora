# Teams Tab Deployment Guide

This guide explains how Aurora works as a Microsoft Teams Tab in a Docker-containerized environment.

## Architecture Overview

```
Docker Container (Frontend - React)
├─ Port 3000 (React dev) / 80 (production)
│  ├─ /teams → TeamsTab component
│  ├─ /manifest.json → Dynamic manifest (auto-generated based on current host)
│  └─ / → Main Aurora app
│
Nginx Reverse Proxy (Production)
├─ https://d23ew7gbss3vnh.cloudfront.net/teams
├─ https://d23ew7gbss3vnh.cloudfront.net/manifest.json
└─ https://d23ew7gbss3vnh.cloudfront.net/api/* → Backend services
```

## Key Point: Dynamic Manifest Generation

**The manifest.json is NOT a static file.** It's generated dynamically by the frontend based on the current request host.

### Why?

1. **Single Docker image** - Works in any environment (localhost, CloudFront, etc.)
2. **No configuration needed** - Manifest automatically adapts to deployment URL
3. **No file downloads required** - Teams reads it directly from `/manifest.json`

### How It Works

**File**: `/frontend/src/App.js`

```javascript
// Manifest is generated dynamically when App loads
window.getTeamsManifest = () => {
  const protocol = window.location.protocol;  // https or http
  const host = window.location.host;          // d23ew7gbss3vnh.cloudfront.net
  const baseUrl = `${protocol}//${host}`;     // https://d23ew7gbss3vnh.cloudfront.net

  return {
    // ... manifest config ...
    staticTabs: [{
      contentUrl: `${baseUrl}/teams`,          // Automatically correct URL
      websiteUrl: `${baseUrl}/teams`,
    }],
    validDomains: [host],                      // Includes current domain
  };
};

// /manifest.json endpoint returns the dynamic manifest
if (location.pathname === '/manifest.json') {
  const manifest = window.getTeamsManifest?.() || {};
  return <pre>{JSON.stringify(manifest, null, 2)}</pre>;
}
```

## Deployment Steps

### Local Development (Docker)

```bash
# Start frontend container
docker-compose up frontend

# Frontend runs on http://localhost:3000
# Get manifest: curl http://localhost:3000/manifest.json
# Teams tab: http://localhost:3000/teams
```

**Manifest output**:
```json
{
  "staticTabs": [{
    "contentUrl": "http://localhost:3000/teams",
    "websiteUrl": "http://localhost:3000/teams"
  }],
  "validDomains": ["localhost:3000"]
}
```

### Production Deployment (CloudFront)

```bash
# Build frontend
npm run build

# Deploy to CloudFront
# Frontend is served at: https://d23ew7gbss3vnh.cloudfront.net

# Get manifest: curl https://d23ew7gbss3vnh.cloudfront.net/manifest.json
# Teams tab: https://d23ew7gbss3vnh.cloudfront.net/teams
```

**Manifest output** (automatically generated):
```json
{
  "staticTabs": [{
    "contentUrl": "https://d23ew7gbss3vnh.cloudfront.net/teams",
    "websiteUrl": "https://d23ew7gbss3vnh.cloudfront.net/teams"
  }],
  "validDomains": ["d23ew7gbss3vnh.cloudfront.net"]
}
```

## Testing in Teams

### No File Download Needed

**Old (wrong) way**: 
❌ Download manifest.json from somewhere  
❌ Zip it with icons  
❌ Upload to Teams  

**New (correct) way**:
✅ Teams reads manifest directly from `/manifest.json` endpoint  
✅ No files to download  
✅ No manual zipping  

### Sideload Aurora Tab

**Local**:
1. Open Teams Desktop
2. Click "Apps" → "Upload a custom app"
3. Enter URL: `http://localhost:3000/manifest.json`
4. Click "Add"

**Production**:
1. Open Teams Desktop
2. Click "Apps" → "Upload a custom app"
3. Enter URL: `https://d23ew7gbss3vnh.cloudfront.net/manifest.json`
4. Click "Add"

That's it. No zipping, no icons, no file management.

## What Changed

| Component | Before | After |
|-----------|--------|-------|
| Manifest location | `/public/manifest.json` (static file) | `/manifest.json` (dynamic endpoint) |
| Icons in manifest | Relative paths | Generated at runtime |
| Deployment | Upload zip file | Teams reads endpoint |
| Config for env | Update manifest.json per env | Automatic (based on host) |
| Docker containers | Need to copy manifest | Already included |

## Benefits

✅ **Single Docker image** works in all environments  
✅ **No configuration needed** per environment  
✅ **No files to manage** (manifest is generated)  
✅ **Simpler Teams sideload** (just paste URL)  
✅ **Automatic HTTPS/HTTP** detection  

## Implementation Details

### Frontend Code

**File**: `/frontend/src/App.js`

```javascript
// 1. Generate manifest based on current host
useEffect(() => {
  window.getTeamsManifest = () => {
    const protocol = window.location.protocol;
    const host = window.location.host;
    const baseUrl = `${protocol}//${host}`;
    
    return {
      // ... manifest with dynamic URLs ...
    };
  };
}, []);

// 2. Serve manifest at /manifest.json
if (location.pathname === '/manifest.json') {
  const manifest = window.getTeamsManifest?.() || {};
  return <pre>{JSON.stringify(manifest, null, 2)}</pre>;
}
```

### Docker Setup

No changes needed to Dockerfile or docker-compose.yml. The frontend automatically serves the manifest.

**Local dev**:
```yaml
frontend:
  build: ./frontend
  ports:
    - "3000:3000"
  # Manifest served at http://localhost:3000/manifest.json
```

**Production (nginx)**:
```nginx
location /manifest.json {
  proxy_pass http://frontend:3000/manifest.json;
  add_header Content-Type application/json;
}

location /teams {
  proxy_pass http://frontend:3000/teams;
}
```

## User Guide: Integrating Teams Tab

### For Local Testing

1. **Start containers**:
   ```bash
   docker-compose up
   ```

2. **Open Teams Desktop**:
   - Click "Apps"
   - Click "Upload a custom app"
   - Paste: `http://localhost:3000/manifest.json`
   - Click "Add"

3. **Aurora tab appears** with Chat + Feed

### For Production

1. **Deploy frontend to CloudFront**:
   ```bash
   npm run build
   # Deploy build/ folder to CloudFront
   ```

2. **Open Teams Desktop**:
   - Click "Apps"
   - Click "Upload a custom app"
   - Paste: `https://d23ew7gbss3vnh.cloudfront.net/manifest.json`
   - Click "Add"

3. **Aurora tab appears** automatically

## Troubleshooting

### "Failed to download manifest"

**Problem**: Teams can't reach `/manifest.json` endpoint

**Solutions**:
```bash
# Test locally
curl http://localhost:3000/manifest.json

# Test production
curl https://d23ew7gbss3vnh.cloudfront.net/manifest.json

# Check frontend is running
docker logs aurora-frontend

# Verify port mapping
docker ps | grep frontend
```

### "Invalid manifest"

**Problem**: Manifest JSON is malformed

**Solution**: Check it returns valid JSON:
```bash
curl -s http://localhost:3000/manifest.json | python -m json.tool
```

### "CORS error" in Teams

**Problem**: Teams iframe can't reach manifest

**Solution**: 
- Ensure CORS headers are set (already done in auth service)
- Manifest must be served from same domain as tab

## Security Notes

✅ Manifest is public (no secrets)  
✅ Generated at runtime (no hardcoded values)  
✅ Based on request host (secure for any domain)  
✅ Icons are loaded from frontend assets (no external URLs)  

## Summary

**Aurora Teams Tab works completely within the Docker container system.**

- No files to download
- No manual configuration per environment
- Manifest auto-generated from host
- Works locally and in production
- Single Docker image for all environments
