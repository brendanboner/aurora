# Aurora Teams Agent - Setup Guide

## Quick Start

### 1. Install Dependencies

```bash
cd teams-agent
npm install
```

### 2. Register Bot with Microsoft Bot Framework

1. Go to [Azure Portal](https://portal.azure.com)
2. Create a new Bot Channels Registration (or Azure Bot)
3. Note your **Bot ID** (Application ID) and create a **Bot Password** (Client Secret)

### 3. Configure Environment

```bash
cp .env.dev .env
# Edit .env and add your Bot ID and Password
```

Your `.env` should look like:
```
BOT_ID=your-bot-application-id
BOT_PASSWORD=your-bot-client-secret
BOT_PORT=3978
AURORA_API_URL=http://localhost:8000
AURORA_FRONTEND_URL=http://localhost:3000
```

### 4. Start Aurora Backend

Make sure Aurora services are running:
```bash
cd ..
docker-compose up -d
# Verify services
curl http://localhost:8000/api/auth/health
curl http://localhost:8001/api/oracle/health
```

### 5. Build and Run the Bot

```bash
npm run build
npm start
```

Or for development with auto-reload:
```bash
npm run dev
```

### 6. Test with Bot Framework Emulator

1. Download [Bot Framework Emulator](https://github.com/Microsoft/BotFramework-Emulator/releases)
2. Open the emulator
3. Click "Open Bot"
4. Enter Bot URL: `http://localhost:3978/api/messages`
5. Enter your Bot ID and Password
6. Click "Connect"
7. Start chatting!

Test commands:
- `help` - See available commands
- `feed` - View your content feed
- `What is Wi-Fi 7?` - Ask a question

## Deploying to Teams

### Option 1: Side-load for Testing

1. Update `appPackage/manifest.json`:
   - Replace `{{APP_ID}}` with a new GUID
   - Replace `{{BOT_ID}}` with your Bot Application ID

2. Create the app package:
```bash
cd appPackage
zip -r aurora-teams-app.zip manifest.json color.png outline.png
```

3. Upload to Teams:
   - Open Teams
   - Go to Apps → Manage your apps
   - Click "Upload a custom app"
   - Select `aurora-teams-app.zip`

### Option 2: Use Teams Toolkit (VS Code)

1. Install "Teams Toolkit" extension in VS Code
2. Open the teams-agent folder in VS Code
3. Press F5 or click "Run and Debug"
4. Select "Debug in Teams"
5. Sign in with your Microsoft 365 account
6. The bot will open in Teams

## Creating App Icons

You need two icons:
- `color.png` - 192x192 px (full color)
- `outline.png` - 32x32 px (transparent outline)

Quick way to create them:
1. Use an online tool like [Canva](https://canva.com) or [Figma](https://figma.com)
2. Create a 192x192 image with Aurora logo/icon
3. Create a 32x32 transparent outline version
4. Save both in `appPackage/` folder

Or use placeholder icons:
```bash
cd appPackage
# Create simple placeholder icons (requires ImageMagick)
convert -size 192x192 xc:#4A90E2 -gravity center -pointsize 72 -fill white -annotate +0+0 "A" color.png
convert -size 32x32 xc:transparent -gravity center -pointsize 24 -fill black -annotate +0+0 "A" outline.png
```

## Troubleshooting

### Bot not responding
- Check bot is running: `curl http://localhost:3978/api/health`
- Verify Bot ID/Password in `.env`
- Check logs for errors

### "User not found" errors
- Verify Aurora backend is running
- Check user exists in Aurora database
- Review email matching logic

### No posts in feed
- Verify content_creator_service is running
- Check user has preferences set in Aurora
- Test the feed API directly:
  ```bash
  curl "http://localhost:8000/api/content_creator_service/feed?user_id=YOUR_USER_ID&limit=5"
  ```

### Oracle not responding
- Verify oracle service is running: `curl http://localhost:8001/api/oracle/health`
- Check oracle logs: `docker-compose logs oracle`
- Test oracle API directly:
  ```bash
  curl -X POST http://localhost:8001/api/oracle/query \
    -H "Content-Type: application/json" \
    -d '{"user_id":"test","question":"What is Wi-Fi 7?","mode":"answer"}'
  ```

## Next Steps

1. Customize the Adaptive Cards in `src/adaptiveCards/`
2. Add more commands in `src/bot.ts`
3. Implement proactive notifications
4. Add user preference management
5. Deploy to Azure for production use

## Production Deployment

For production:
1. Deploy bot to Azure App Service or Container Instance
2. Update Bot messaging endpoint in Azure Portal
3. Configure production environment variables
4. Enable App Insights for monitoring
5. Set up CI/CD pipeline

See Azure documentation: https://docs.microsoft.com/azure/bot-service/
