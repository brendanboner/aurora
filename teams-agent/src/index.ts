import * as restify from 'restify';
import * as path from 'path';
import { BotFrameworkAdapter, ConversationState, MemoryStorage, UserState } from 'botbuilder';
import { AuroraBot } from './bot';
import { ProactiveMessenger, FeedUpdatePayload } from './services/proactiveMessenger';
import * as dotenv from 'dotenv';

// Load environment variables.
// In production (Docker), vars are injected by --env-file before Node starts;
// dotenv fills any gaps from a local .env file without overriding existing vars.
dotenv.config();

console.log('='.repeat(80));
console.log('Aurora Teams Agent Starting...');
console.log('='.repeat(80));
console.log(`Environment: ${process.env.NODE_ENV || 'development'}`);
console.log(`Aurora API URL: ${process.env.AURORA_API_URL}`);
console.log(`Bot Port: ${process.env.BOT_PORT || 3978}`);
console.log('='.repeat(80));

// Create HTTP server
const server = restify.createServer();
server.use(restify.plugins.bodyParser());

const port = process.env.BOT_PORT || 3978;
server.listen(port, () => {
  console.log(`\n✅ ${server.name} listening on ${server.url}`);
  console.log('\n📱 Get Bot Framework Emulator: https://aka.ms/botframework-emulator');
  console.log('\n📦 To test in Teams: Upload the app package from appPackage/ folder');
  console.log('\n🔧 Bot endpoints:');
  console.log(`   - Messages: ${server.url}/api/messages`);
  console.log(`   - Health: ${server.url}/api/health`);
  console.log('\n' + '='.repeat(80) + '\n');
});

// Create adapter
// For local development with emulator, empty credentials work fine
const adapter = new BotFrameworkAdapter({
  appId: process.env.BOT_ID || '',
  appPassword: process.env.BOT_PASSWORD || ''
});

// Override createConnectorClient to replace localhost with host.docker.internal
// This is needed when running in Docker on macOS to reach the emulator
const originalCreateConnectorClient = adapter.createConnectorClient.bind(adapter);
adapter.createConnectorClient = function(serviceUrl: string) {
  // If we're in Docker and the service URL points to localhost, use host.docker.internal
  if (serviceUrl && serviceUrl.includes('localhost')) {
    const dockerServiceUrl = serviceUrl.replace('localhost', 'host.docker.internal');
    console.log(`Redirecting serviceUrl: ${serviceUrl} -> ${dockerServiceUrl}`);
    return originalCreateConnectorClient(dockerServiceUrl);
  }
  return originalCreateConnectorClient(serviceUrl);
};

// Error handler
adapter.onTurnError = async (context, error) => {
  console.error(`\n[onTurnError] unhandled error: ${error}`);
  console.error(error);
  
  try {
    await context.sendActivity('Sorry, something went wrong. Please try again.');
    
    // Send trace activity for Bot Framework Emulator
    await context.sendTraceActivity(
      'OnTurnError Trace',
      `${error}`,
      'https://www.botframework.com/schemas/error',
      'TurnError'
    );
  } catch (sendError) {
    console.error(`Error sending error message: ${sendError}`);
  }
};

// Create conversation and user state with in-memory storage
const memoryStorage = new MemoryStorage();
const conversationState = new ConversationState(memoryStorage);
const userState = new UserState(memoryStorage);

// Proactive messaging helper (needs adapter reference)
const proactiveMessenger = new ProactiveMessenger(adapter);

// Create the main dialog
const bot = new AuroraBot(conversationState, userState);

// Listen for incoming requests
server.post('/api/messages', async (req, res) => {
  console.log(`[${new Date().toISOString()}] Incoming POST to /api/messages`);
  console.log('Request body type:', req.body?.type);
  console.log('ServiceUrl from request:', req.body?.serviceUrl);
  
  // Fix serviceUrl for Docker: replace localhost with host.docker.internal
  if (req.body?.serviceUrl && req.body.serviceUrl.includes('localhost')) {
    const originalUrl = req.body.serviceUrl;
    req.body.serviceUrl = req.body.serviceUrl.replace('localhost', 'host.docker.internal');
    console.log(`Fixed serviceUrl: ${originalUrl} -> ${req.body.serviceUrl}`);
  }
  
  try {
    await adapter.process(req, res, async (context) => {
      console.log('Processing activity:', context.activity.type, context.activity.text);
      await bot.run(context);
      await conversationState.saveChanges(context);
      await userState.saveChanges(context);
    });
    console.log('Request processed successfully');
  } catch (err) {
    console.error('Error processing request:', err);
    throw err;
  }
});

// Health check endpoint
server.get('/api/health', async (req, res) => {
  res.json({ 
    status: 'healthy', 
    timestamp: new Date().toISOString(),
    service: 'aurora-teams-agent',
    aurora_api: process.env.AURORA_API_URL
  });
});

/**
 * Internal proactive push endpoint — called by content_creator_service when a new post is created.
 * Not authenticated (Docker network isolation is the security boundary).
 * Body: { agent_slug, agent_name, post_id, title, summary, tags, source_url?, published_at? }
 */
server.post('/internal/push-feed-update', async (req, res) => {
  const body = req.body as Partial<FeedUpdatePayload>;

  if (!body?.agent_slug || !body?.title) {
    res.json({ error: 'agent_slug and title are required' });
    (res as any).status = 400;
    return;
  }

  console.log(`[${new Date().toISOString()}] Proactive push: agent_slug=${body.agent_slug} title="${body.title}"`);

  try {
    const result = await proactiveMessenger.pushFeedUpdate({
      agent_slug:    body.agent_slug,
      agent_name:    body.agent_name   || body.agent_slug,
      post_id:       body.post_id      || 0,
      title:         body.title,
      summary:       body.summary      || '',
      tags:          body.tags         || [],
      source_url:    body.source_url,
      published_at:  body.published_at,
    });
    res.json({ status: 'ok', ...result });
  } catch (err) {
    console.error('[internal/push-feed-update] Error:', err);
    res.json({ error: (err as Error).message });
  }
});

// Graceful shutdown
process.on('SIGTERM', () => {
  console.log('\n\n🛑 SIGTERM signal received: closing HTTP server');
  server.close(() => {
    console.log('✅ HTTP server closed');
    process.exit(0);
  });
});

process.on('SIGINT', () => {
  console.log('\n\n🛑 SIGINT signal received: closing HTTP server');
  server.close(() => {
    console.log('✅ HTTP server closed');
    process.exit(0);
  });
});
