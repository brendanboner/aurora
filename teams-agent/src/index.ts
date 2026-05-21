// Polyfill globalThis.crypto for Node < 19 (needed by botbuilder JWT internals)
if (typeof (globalThis as any).crypto === 'undefined') {
  (globalThis as any).crypto = require('crypto').webcrypto;
}

import * as restify from 'restify';
import * as path from 'path';
import { BotFrameworkAdapter, ConversationState, MemoryStorage, UserState } from 'botbuilder';
import { AuroraBot } from './bot';
import { ProactiveMessenger, FeedUpdatePayload, UserAgentUpdatePayload } from './services/proactiveMessenger';
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

// Create adapter.
// BOT_TENANT_ID is required for single-tenant Azure AD app registrations so
// the adapter acquires outgoing OAuth tokens from the correct tenant.
// For multi-tenant apps (botframework.com registration) leave BOT_TENANT_ID unset.
const adapter = new BotFrameworkAdapter({
  appId: process.env.BOT_ID || '',
  appPassword: process.env.BOT_PASSWORD || '',
  ...(process.env.BOT_TENANT_ID ? { channelAuthTenant: process.env.BOT_TENANT_ID } : {}),
});

// Normalise serviceUrl so the bot can always reply to the playground.
// The Agents Playground running on a Mac with Docker Desktop installed sends
// serviceUrl=http://host.docker.internal:PORT, which resolves only when Docker
// Desktop is running.  When we run the bot locally (not inside a container)
// we need plain localhost instead.  Inside Docker we do the reverse.
const IN_DOCKER = process.env.RUNNING_IN_DOCKER === 'true';

function normaliseServiceUrl(serviceUrl: string): string {
  if (!serviceUrl) return serviceUrl;
  if (IN_DOCKER) {
    // Container → replace localhost with host gateway so bot can reach Mac playground
    return serviceUrl.replace(/localhost/g, 'host.docker.internal');
  }
  // Host → replace host.docker.internal with localhost (playground on same machine)
  return serviceUrl.replace(/host\.docker\.internal/g, 'localhost');
}

const originalCreateConnectorClient = adapter.createConnectorClient.bind(adapter);
adapter.createConnectorClient = function(serviceUrl: string) {
  const normalised = normaliseServiceUrl(serviceUrl);
  if (normalised !== serviceUrl) {
    console.log(`[serviceUrl] ${serviceUrl} -> ${normalised}`);
  }
  return originalCreateConnectorClient(normalised);
};

// Error handler
adapter.onTurnError = async (context, error) => {
  const restErr = error as any;
  const body = restErr?.response?.bodyAsText || restErr?.message || String(error);
  console.error(`\n[onTurnError] ${restErr?.statusCode || ''} ${body.slice(0, 200)}`);
  console.error('  convId:', context.activity.conversation?.id, '| serviceUrl:', context.activity.serviceUrl);
  
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
  
  if (req.body?.serviceUrl) {
    const fixed = normaliseServiceUrl(req.body.serviceUrl);
    if (fixed !== req.body.serviceUrl) {
      console.log(`[serviceUrl] fixed incoming: ${req.body.serviceUrl} -> ${fixed}`);
      req.body.serviceUrl = fixed;
    }
  }
  
  try {
    await adapter.process(req, res, async (context) => {
      console.log('Processing activity:', context.activity.type, context.activity.text,
        '| convId:', context.activity.conversation?.id,
        '| activityId:', context.activity.id,
        '| serviceUrl:', context.activity.serviceUrl);
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
    return;
  }

  console.log(`[${new Date().toISOString()}] Proactive push: agent_slug=${body.agent_slug} title="${body.title}"`);

  // Respond immediately — delivery is fire-and-forget so slow/dead serviceUrls
  // don't block the caller (content_creator_service has a 5s timeout).
  res.json({ status: 'queued' });

  const payload = {
    agent_slug:    body.agent_slug,
    agent_name:    body.agent_name   || body.agent_slug,
    post_id:       body.post_id      || 0,
    title:         body.title,
    summary:       body.summary      || '',
    body:          body.body,        // full post body for inline reading
    tags:          body.tags         || [],
    source_url:    body.source_url,
    published_at:  body.published_at,
  };

  proactiveMessenger.pushFeedUpdate(payload).catch((err) => {
    console.error('[internal/push-feed-update] Delivery error:', err);
  });
});

/**
 * Internal endpoint for personal user-agent updates.
 * Routes by aurora_user_id → all Teams conversations linked to that user.
 * Called by content_creator_service after generating a post for a user agent.
 */
server.post('/internal/push-user-agent-update', async (req, res) => {
  const body = req.body as Partial<UserAgentUpdatePayload>;

  if (!body?.aurora_user_id || !body?.title) {
    res.json({ error: 'aurora_user_id and title are required' });
    return;
  }

  console.log(
    `[${new Date().toISOString()}] User-agent push: user=${body.aurora_user_id} agent="${body.agent_name}" title="${body.title}"`
  );

  res.json({ status: 'queued' });

  const payload: UserAgentUpdatePayload = {
    aurora_user_id: body.aurora_user_id,
    agent_name:     body.agent_name    || 'My Agent',
    post_id:        body.post_id       || 0,
    title:          body.title,
    summary:        body.summary       || '',
    body:           body.body,
    tags:           body.tags          || [],
    source_url:     body.source_url,
    published_at:   body.published_at,
  };

  proactiveMessenger.pushUserAgentUpdate(payload).catch((err) => {
    console.error('[internal/push-user-agent-update] Delivery error:', err);
  });
});

/**
 * System announcement endpoint — push important Aurora updates to group channels.
 *
 * POST /internal/push-announcement
 * Body: { title, summary, body?, tags?, importance?, scope? }
 *   importance: 'critical' | 'high' | 'normal'
 *   scope: 'groups' (default) | 'all'
 */
server.post('/internal/push-announcement', async (req, res) => {
  const body = req.body ?? {};
  if (!body?.title || !body?.summary) {
    res.json({ error: 'title and summary are required' });
    return;
  }

  console.log(`[${new Date().toISOString()}] Announcement push: "${body.title}" (importance=${body.importance ?? 'normal'}, scope=${body.scope ?? 'groups'})`);

  res.json({ status: 'queued', title: body.title });

  proactiveMessenger.pushAnnouncement({
    title:      body.title,
    summary:    body.summary,
    body:       body.body,
    tags:       body.tags,
    importance: body.importance,
    scope:      body.scope,
  }).catch((err) => {
    console.error('[internal/push-announcement] Delivery error:', err);
  });
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
