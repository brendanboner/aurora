# Teams Installation Quick Start

## ⚡ Fast Track to Teams

### 1. Package is Ready
✅ `aurora-teams-app.zip` is validated and ready to upload

### 2. Install Now

#### Option A: Personal Testing (5 minutes)
1. Open **Teams Desktop** or **teams.microsoft.com**
2. Click **Apps** (left sidebar)
3. Click **Manage your apps** → **Upload a custom app**
4. Select: `aurora-teams-app.zip`
5. Click **Add**

#### Option B: Organization Deployment (Admin Required)
1. Go to: https://admin.teams.microsoft.com
2. **Teams apps** → **Manage apps** → **Upload new app**
3. Upload: `aurora-teams-app.zip`
4. Approve and assign to users/groups

---

## 🔧 Rebuild Package (if needed)

```bash
# Default (uses aurora-octo.xcloudiq.com)
./scripts/create-teams-package.sh aurora-octo.xcloudiq.com .

# Custom domain
./scripts/create-teams-package.sh your-domain.com .

# Validate
./scripts/validate-teams-package.sh aurora-teams-app.zip
```

---

## 📝 What Was Fixed

- ✅ Valid JSON (was corrupted by sed)
- ✅ Modern Teams schema v1.16 compliance
- ✅ Both personal and channel tabs configured
- ✅ SSO/identity support added
- ✅ Icons at correct location and size
- ✅ All HTTPS URLs
- ✅ Proper validDomains array

---

## 🐛 Troubleshooting

### Upload fails: "Invalid package"
```bash
./scripts/validate-teams-package.sh aurora-teams-app.zip
```

### Tab shows "Cannot reach app"
- Check: `curl -I https://aurora-octo.xcloudiq.com/teams`
- Ensure HTTPS (not HTTP)
- Verify CORS headers allow Teams

### Need to change domain
```bash
# Edit manifest and rebuild
vim frontend/public/manifest.json
./scripts/create-teams-package.sh YOUR-NEW-DOMAIN.com .
```

---

## 📚 Documentation

- **Full Guide**: `TEAMS_DEPLOYMENT.md`
- **Fix Details**: `TEAMS_PACKAGE_FIX.md`
- **Teams Integration**: `TEAMS_INTEGRATION_GUIDE.md`

---

## ✅ Validation Status

**Package**: `aurora-teams-app.zip` (2.1 KB)  
**Status**: ✅ All checks passed  
**Schema**: Teams v1.16 (Office 365)  
**Domain**: aurora-octo.xcloudiq.com  
**Ready**: Yes - upload now!
