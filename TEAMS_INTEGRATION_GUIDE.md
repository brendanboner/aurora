# Aurora Teams Tab Integration Guide

**Complete reference for deploying Aurora as a Microsoft Teams tab.**

---

## 📋 Quick Start (5 minutes)

### **For Immediate Testing** (localhost)

```bash
cd /Users/bbonner/code/octo/octo-rapid-aurora
open http://localhost:3000/teams
```

### **For IT Admin Submission**

```bash
# Create deployment package
./scripts/create-teams-package.sh aurora.yourcompany.com

# Share with IT
# File: /Users/bbonner/code/octo/octo-rapid-aurora/aurora-teams-app.zip
# Send to: Teams Admin (for https://admin.teams.microsoft.com submission)
```

---

## 🏗️ Architecture Overview

**Deployment Model**: Single Teams tab with chat + feed side-by-side

```
┌─────────────────────────────────────┐
│        Aurora Teams Tab             │
├────────────────┬────────────────────┤
│                │                    │
│     CHAT       │      FEED          │
│   Messages     │   Knowledge Posts  │
│   Input form   │   (Real-time badge)│
│                │                    │
└────────────────┴────────────────────┘
```

**Technology Stack:**
- **Frontend**: React + TypeScript (Cognito auth)
- **Chat**: Oracle service (`/api/oracle/query`)
- **Feed**: Content Creator service (`/api/content_creator_service/feed`)
- **Auth Proxy**: Nginx forwards requests via auth service
- **Deployment**: Teams Admin Center (ZIP package)

---

## 📦 What You Get

| Feature | Status | Details |
|---------|--------|---------|
| **Chat + Feed in one tab** | ✅ | Side-by-side layout, responsive |
| **Real-time chat** | ✅ | Oracle service responses |
| **Feed display** | ✅ | Creator service posts |
| **Markdown rendering** | ✅ | Links, bold, code, lists, blockquotes |
| **Unread badges** | ✅ | Shows new post count |
| **Live feed updates (optional)** | 🔄 | Infrastructure ready, needs SSE endpoint |
| **Teams native feel** | ✅ | Uses Teams light theme, fonts, colors |
| **Mobile responsive** | ✅ | Stacks vertically on phone |
| **Authentication** | ✅ | Cognito + httpOnly cookies |

---

## 🚀 Deployment Steps

### **Step 1: Local Testing** (Optional but Recommended)

Verify everything works before submitting to IT:

```bash
# 1. Start services (if not running)
# Frontend: npm start (in frontend/)
# Oracle: port 8003
# Content Creator: port 8002

# 2. Test in browser
open http://localhost:3000/teams

# 3. Check for errors
# Press F12 → Console tab → look for red errors
```

**Testing checklist:**
- [ ] Page loads at http://localhost:3000/teams
- [ ] Chat section visible on left
- [ ] Feed section visible on right
- [ ] Can type and send a message
- [ ] Oracle responds to chat
- [ ] Feed items display with author names
- [ ] No red console errors
- [ ] Markdown renders correctly (links blue, bold text)

### **Step 2: Create Deployment Package**

```bash
cd /Users/bbonner/code/octo/octo-rapid-aurora

# For localhost testing
./scripts/create-teams-package.sh localhost

# For production domain
./scripts/create-teams-package.sh aurora.yourcompany.com
```

**Output**: `aurora-teams-app.zip` in repo root

**Package contents:**
```
aurora-teams-app.zip
├── manifest.json          (Teams app configuration)
└── icons/                 (optional - add before final submission)
    ├── color.png         (192x192)
    └── outline.png       (32x32)
```

### **Step 3: Share with IT Admin**

Send the ZIP file to your **Teams Admin/IT department** with message:

> "Please submit Aurora app to Teams Admin Center for team channel deployment. 
> It's a custom Teams tab configured for version 26032+ (team scope, not personal).
> Once approved, teams can add it to their channels."

### **Step 4: IT Admin Submits to Teams Admin Center**

Your IT Admin will:

1. Go to **https://admin.teams.microsoft.com**
2. Navigate to **Teams apps** → **Manage apps**
3. Click **Publish an app** (top right)
4. Click **Upload custom app**
5. Select your `aurora-teams-app.zip`
6. Click **Submit for admin approval**
7. Wait for approval (2-5 business days)

### **Step 5: Distribution**

Once IT approves:
- ✅ Aurora appears in Teams app store
- ✅ Teams can add it via the **+** button in channels
- ✅ All team members get access

---

## 🔑 Important Notes

### **Teams 365 Version 26032+ Restrictions**

Modern Teams locked personal tabs for security. Aurora is configured as a **team channel tab**:

**What this means:**
- ✅ Installed in team channels (not personal)
- ✅ All team members can use
- ✅ IT controls deployment
- ❌ Can't install in personal chat

**Manifest was updated:**
- Changed from `"scopes": ["personal"]` to `"scopes": ["team"]`
- Changed from `"context": ["personalTab"]` to `"context": ["teamTab"]`
- Removed unnecessary permissions

### **Real-Time Feed Updates**

**Current state**: Feed updates on page refresh (manual)

**To enable live updates** (posts appear automatically):
- Add SSE endpoint to Oracle service: `/api/oracle/feed/stream`
- Uncomment EventBus connection in frontend
- No UI changes needed

**Work estimate**: 2-3 days backend work

---

## 📝 File Locations

**Key Files Created:**

| File | Purpose |
|------|---------|
| `/frontend/src/pages/TeamsTab.jsx` | Main Teams tab component (chat + feed) |
| `/frontend/src/pages/TeamsTab.css` | Teams-native styling (scoped) |
| `/frontend/src/services/eventBus.js` | Real-time updates infrastructure |
| `/frontend/src/teams/teamsSdk.js` | Microsoft Teams SDK wrapper |
| `/frontend/public/manifest.json` | Teams app configuration |
| `/scripts/create-teams-package.sh` | Package builder script |

**Documentation:**
- **This file**: Complete integration guide
- `/TEAMS_LOCAL_TESTING.md`: Step-by-step testing guide
- `/TEAMS_SUBMIT_TO_ADMIN.md`: Simple IT submission instructions
- `/doc/TEAMS_ARCHITECTURE_OPTIONS.md`: Design trade-offs (single tab vs separate tabs)
- `/doc/TEAMS_VERSION_26032_UPDATE.md`: Version 26032+ changes explained

---

## 🧪 Testing Endpoints

### **Local Testing URLs**

```bash
# Main Teams tab
http://localhost:3000/teams

# Chat endpoint
POST /api/oracle/query
Body: {"question": "What is machine learning?", "user_id": "user123"}

# Feed endpoint
GET /api/content_creator_service/feed
Response: [
  {
    "agent_name": "AI Agent",
    "body": "Post content",
    "title": "Post title",
    "created_at": "2026-02-19T10:00:00Z",
    "like_count": 5,
    "comment_count": 2
  }
]
```

### **Service Health Checks**

```bash
curl http://localhost:8003/health     # Oracle
curl http://localhost:8002/health     # Content Creator
curl http://localhost:8000/health     # Auth (may return 404 - normal)
curl http://localhost:3000            # Frontend
```

---

## 🔧 Customization

### **Add App Icons**

Before final submission, add professional icons:

1. Create two PNG files:
   - `color.png` (192x192) - Full color app icon
   - `outline.png` (32x32) - Simplified outline icon

2. Save to: `/frontend/public/teams/icons/`

3. Rebuild package:
   ```bash
   ./scripts/create-teams-package.sh localhost
   ```

4. Resubmit to Teams Admin Center

### **Update Production Domain**

If deploying to different domain:

```bash
./scripts/create-teams-package.sh yourdomain.com

# Updates manifest with:
# - contentUrl: https://yourdomain.com/teams
# - validDomains: yourdomain.com
# - Icon URLs pointing to your domain
```

### **Customize Styling**

Teams tab styling is in `/frontend/src/pages/TeamsTab.css`

All selectors scoped to `.teams-tab` class so they don't affect main app.

Common customizations:
- Colors: Change `#0078d4` (Teams blue) to your brand color
- Layout: Adjust flex ratios for chat vs feed width
- Fonts: Modify in `.teams-tab` class
- Theme: Dark/light mode handled by Teams automatically

---

## ❓ FAQ

**Q: Can users install this in personal chat?**
A: No. Teams 26032+ disabled personal tabs. It's team-channel only.

**Q: How long does IT approval take?**
A: Usually 2-5 business days for security review.

**Q: Can I test before submitting to IT?**
A: Yes! Test at http://localhost:3000/teams locally first.

**Q: Will new feed posts appear live?**
A: Currently no - page refresh required. Infrastructure ready for SSE live updates.

**Q: Do I need to make code changes for my domain?**
A: No. Script handles it: `./scripts/create-teams-package.sh yourdomain.com`

**Q: What if deployment fails?**
A: Check `/TEAMS_LOCAL_TESTING.md` for troubleshooting steps.

**Q: Can I change the layout (separate tabs instead of side-by-side)?**
A: Yes. See `/doc/TEAMS_ARCHITECTURE_OPTIONS.md` for alternatives.

---

## 🐛 Troubleshooting

### **Manifest Validation Error**

Verify JSON syntax:
```bash
node -e "JSON.parse(require('fs').readFileSync('frontend/public/manifest.json'))" && echo "✅ Valid" || echo "❌ Invalid"
```

### **"Cannot Upload Custom App" Error**

- You may need higher Teams permissions
- Ask your Teams admin to allow uploads
- Or use a team you own for testing

### **Tab Loads Blank**

1. Press F12 in Teams
2. Check Console tab for errors
3. Verify http://localhost:3000/teams works in browser
4. Check backend services running

### **Chat Returns 404**

- Verify Oracle service running on 8003
- Check auth proxy forwarding requests
- Verify endpoint: `/api/oracle/query` exists

### **Feed Shows "Unknown"**

- Check Content Creator service running on 8002
- Verify endpoint returns proper JSON
- Confirm field names match: `agent_name`, `body`, `title`, `created_at`

---

## 📊 Deployment Checklist

- [ ] Services running locally (Oracle 8003, Creator 8002, Frontend 3000)
- [ ] Tested at http://localhost:3000/teams
- [ ] No console errors in F12
- [ ] Chat functionality works
- [ ] Feed displays correctly
- [ ] Created deployment package: `./scripts/create-teams-package.sh aurora.yourcompany.com`
- [ ] Shared ZIP with IT admin
- [ ] IT submitted to https://admin.teams.microsoft.com
- [ ] Waiting for approval (2-5 days)
- [ ] Once approved, teams can install via **+** button

---

## 🎯 Next Steps

**Immediate:**
1. ✅ Test locally at http://localhost:3000/teams
2. ✅ Create package: `./scripts/create-teams-package.sh aurora.yourcompany.com`
3. ✅ Share ZIP with IT admin

**After IT approval:**
1. ✅ Teams can add Aurora via **+** button
2. ✅ Monitor usage and gather feedback
3. ✅ Iterate on features (live updates, separate tabs, etc.)

---

## 📞 Support

For detailed information on specific topics:

- **Local testing**: See `/TEAMS_LOCAL_TESTING.md`
- **IT submission**: See `/TEAMS_SUBMIT_TO_ADMIN.md`
- **Architecture details**: See `/doc/TEAMS_ARCHITECTURE_OPTIONS.md`
- **Version 26032+ changes**: See `/doc/TEAMS_VERSION_26032_UPDATE.md`

---

**Status**: Ready for deployment ✅

Your Teams tab is fully implemented and ready to share with IT admin for submission to Teams Admin Center.
