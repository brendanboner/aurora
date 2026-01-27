# Aurora Teams Agent

Microsoft 365 Teams agent that integrates with the Aurora knowledge management system.

## Features

- 📰 **Personalized Content Feed** - Get curated posts from AI agents based on user preferences
- 🔮 **Oracle Chat Integration** - Ask questions and get intelligent answers from Aurora's knowledge base
- 💬 **Natural Conversation** - Interact naturally via Teams chat
- 🎯 **User Personalization** - Content tailored to each user's email/profile in Aurora

## Setup

### Prerequisites

- Node.js 18 or higher
- Microsoft 365 account with Teams
- Aurora backend services running (localhost:8000)
- Bot Framework registration

### Installation

1. Install dependencies:
```bash
npm install
```

2. Configure environment:
```bash
cp .env.dev .env
# Edit .env with your Bot ID and Password
```

3. Start Aurora services:
```bash
cd ../
docker-compose up -d
```

4. Run the bot:
```bash
npm run dev
```

### Testing Locally

1. Download [Bot Framework Emulator](https://github.com/Microsoft/BotFramework-Emulator/releases)
2. Open the emulator and connect to `http://localhost:3978/api/messages`
3. Enter your Bot ID and Password
4. Start chatting!

### Deploying to Teams

1. Build the app package:
```bash
cd appPackage
zip -r aurora-teams-app.zip manifest.json color.png outline.png
```

2. Upload to Teams:
   - Go to Teams > Apps > Manage your apps
   - Click "Upload an app"
   - Select "Upload a custom app"
   - Choose the `aurora-teams-app.zip` file

## Usage

### Commands

- `feed` or `show feed` - Display your personalized content feed
- `help` - Show available commands
- `about` - Learn about Aurora
- Just ask a question naturally! - e.g., "What's new in Wi-Fi 7?"

### Examples

```
User: feed
Bot: [Shows 5 personalized content cards]

User: What are MLO requirements?
Bot: [Provides answer with citations from Aurora knowledge base]

User: help
Bot: [Shows help card with all commands]
```

## Architecture

```
teams-agent/
├── src/
│   ├── index.ts              # Entry point & HTTP server
│   ├── bot.ts                # Main bot logic
│   ├── services/
│   │   ├── auroraUserService.ts    # User lookup/sync
│   │   ├── auroraFeedService.ts    # Content feed API
│   │   └── auroraOracleService.ts  # Oracle chat API
│   ├── handlers/
│   │   ├── feedHandler.ts          # Feed command handler
│   │   └── chatHandler.ts          # Chat/question handler
│   └── adaptiveCards/
│       ├── feedPostCard.json       # Feed post template
│       ├── oracleResponseCard.json # Oracle response template
│       └── welcomeCard.json        # Welcome message
└── appPackage/
    ├── manifest.json         # Teams app manifest
    ├── color.png            # App icon (192x192)
    └── outline.png          # App icon outline (32x32)
```

## Integration with Aurora

### User Matching

The bot matches Teams users to Aurora users by email address:
1. Extracts email from Teams context
2. Queries Aurora backend: `GET /api/backend/users/email/{email}`
3. If user doesn't exist, creates via sync endpoint
4. Uses Aurora `user_id` for all API calls

### API Endpoints Used

- `GET /api/backend/users/email/{email}` - User lookup
- `POST /api/backend/internal/sync-user` - User creation
- `GET /api/content_creator_service/feed` - Content feed
- `POST /api/oracle/query` - Knowledge search

## Development

### Local Development (without Docker)

```bash
npm run dev
```

### Docker Development (Recommended)

See **[DOCKER.md](DOCKER.md)** for complete Docker setup and debugging guide.

Quick start:
```bash
# Start in development mode with debugging
make build-dev
make up-dev

# Attach debugger in VS Code (F5)
# Select "Docker: Debug Teams Agent"
```

### Debug in VS Code

1. Install Teams Toolkit extension
2. Press F5 to start debugging
3. Select "Debug in Teams" option
4. Bot will open in Teams web/desktop client

### Running Tests

```bash
npm test

# Or in Docker
make test
```

### Building for Production

```bash
npm run build
npm start

# Or with Docker
make build
make up
```

## Troubleshooting

### Bot not responding in Teams
- Check Bot ID and Password are correct
- Verify Aurora services are running
- Check bot is properly registered in Azure

### User not found errors
- Verify user exists in Aurora backend
- Check email matching logic
- Review logs for API errors

### Feed showing no posts
- Verify user has preferences set in Aurora
- Check content_creator_service is running
- Review user_id is being passed correctly

## Contributing

When making changes:
1. Update TypeScript interfaces if API contracts change
2. Add error handling for new edge cases
3. Test with Bot Framework Emulator before deploying
4. Update this README with new features

## License

Internal use only - Aurora project
