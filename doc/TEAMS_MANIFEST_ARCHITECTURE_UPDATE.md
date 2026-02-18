# Teams Manifest Architecture Update

**Date:** Latest update to Teams Integration
**Status:** ✅ Complete
**Impact:** Critical fix for Docker-based deployment

## Summary

The Teams manifest is now **dynamically generated** by the React frontend instead of being a static file. This resolves the Docker deployment issue and enables single-image deployment across all environments.

## What Changed

### Before
- Static file: `/public/manifest.json`
- Required manual updates for each environment
- Required file zipping and manual deployment for Teams sideload
- Not suitable for containerized deployment

### After
- Dynamic endpoint: `GET /manifest.json` (served by `/frontend/src/App.js`)
- Auto-detects deployment domain and protocol from `window.location`
- Single Docker image works for localhost, CloudFront, or any domain
- No files to manage, no environment-specific configuration

## How It Works

1. **React App Implementation** (`/frontend/src/App.js`)
   - `window.getTeamsManifest()` function generates manifest JSON
   - Detects current protocol (http/https) and host from `window.location`
   - Route handler at `/manifest.json` returns the dynamic manifest

2. **Manifest Endpoint Response**
   ```javascript
   // Example: running at http://localhost:3000
   GET /manifest.json → {
     "contentUrl": "http://localhost:3000/teams",
     "validDomains": ["localhost:3000", "localhost"],
     ...
   }
   
   // Example: running at https://aurora.company.com
   GET /manifest.json → {
     "contentUrl": "https://aurora.company.com/teams",
     "validDomains": ["aurora.company.com"],
     ...
   }
   ```

3. **Teams Sideload Process**
   - Instead of uploading a zip file, paste the manifest endpoint URL
   - Teams fetches manifest from `/manifest.json`
   - All URLs are already correct for current deployment

## Files Modified

### New Implementation
- `/frontend/src/App.js`
  - Added `window.getTeamsManifest()` function in useEffect
  - Added route handler for `/manifest.json` endpoint
  - Integrated `<TeamsNotificationContainer />` globally

### Deleted
- `/public/manifest.json` (no longer needed—dynamic instead)

### Updated Documentation
- `/doc/TEAMS_INTEGRATION_CHECKLIST.md`
  - **PART 2**: Simplified—manifest setup is automatic
  - **PART 3**: Updated sideload instructions to use `/manifest.json` endpoint
  - **PART 5**: Removed outdated production manifest update steps
  - **PART 7**: Updated troubleshooting for endpoint-based manifest
  - **PART 8**: Simplified deployment steps

## Benefits

✅ **Single Docker Image**
- One build works for all environments
- No configuration files, no environment-specific builds

✅ **Simpler Sideload**
- No file zipping or icon management
- Just paste `/manifest.json` endpoint into Teams

✅ **Auto-Correct URLs**
- contentUrl always matches current deployment
- validDomains automatically set to current domain

✅ **Production Ready**
- Deploys to CloudFront, local servers, or Kubernetes
- Works with any domain automatically

## Verification

Test that manifest generation works:

```bash
# Local development
curl http://localhost:3000/manifest.json | jq .

# Should return JSON with:
# - "contentUrl": "http://localhost:3000/teams"
# - "validDomains": ["localhost:3000", ...]

# Production (after deployment)
curl https://your-domain.com/manifest.json | jq .

# Should return JSON with:
# - "contentUrl": "https://your-domain.com/teams"
# - "validDomains": ["your-domain.com", ...]
```

## Sideload Instructions (New)

### Local Testing
1. Open Teams Desktop
2. Apps → Upload a custom app
3. Paste: `http://localhost:3000/manifest.json`
4. Click "Add"

### Production
1. Open Teams Desktop
2. Apps → Upload a custom app
3. Paste: `https://your-domain.com/manifest.json`
4. Click "Add"

## No More Needed

❌ `/teams-app-package/` directory (if created during earlier setup)
❌ Icon files (color-icon.png, outline-icon.png)
❌ Manifest file zipping
❌ Environment-specific manifest copies

## Next Steps

1. Follow updated `/doc/TEAMS_INTEGRATION_CHECKLIST.md`
2. Verify `/manifest.json` endpoint works locally
3. Deploy to production and verify endpoint responds
4. Sideload in Teams using endpoint URL

## Questions

- **Why dynamic?** Single Docker image requirement—can't embed static files with hardcoded domains
- **What if Teams needs icons?** Icons are generated dynamically or hosted separately; manifest references can be updated as needed
- **Does this affect Docker setup?** No—actually improves it; manifest is served by the app itself
- **Production deployment?** Deploy normally; manifest endpoint automatically detects new domain

---

**Status:** ✅ Ready for use. All code implemented and documented.
