import {
  TeamsActivityHandler,
  TurnContext,
  MessageFactory,
  ConversationState,
  UserState,
  CardFactory
} from 'botbuilder';
import { FeedHandler } from './handlers/feedHandler';
import { ChatHandler } from './handlers/chatHandler';
import { AgentHandler } from './handlers/agentHandler';
import { conversationReferenceStore } from './services/conversationReferenceStore';

// Regex: matches @aurora-<slug> at the start of a message
const AGENT_SLUG_RE = /^@aurora-([\w-]+)\s*/i;

// Commands that set a conversation-scoped default agent
const SET_CHANNEL_AGENT_RE = /^setChannelAgent\s+@aurora-([\w-]+)$/i;
const CLEAR_CHANNEL_AGENT_RE = /^clearChannelAgent$/i;

export class AuroraBot extends TeamsActivityHandler {
  private feedHandler: FeedHandler;
  private chatHandler: ChatHandler;
  private agentHandler: AgentHandler;
  private conversationState: ConversationState;
  private userState: UserState;

  constructor(conversationState: ConversationState, userState: UserState) {
    super();

    this.conversationState = conversationState;
    this.userState = userState;
    this.feedHandler = new FeedHandler();
    this.chatHandler = new ChatHandler();
    this.agentHandler = new AgentHandler();

    // Handle incoming messages
    this.onMessage(async (context, next) => {
      // Store the conversation reference so we can send proactive messages later
      await this.saveConversationRef(context);

      // Strip Teams @mention tags: "<at>Bot Name</at> actual message"
      const rawText = context.activity.text?.trim() || '';
      const text = rawText.replace(/<at>[^<]*<\/at>/gi, '').trim();
      const lower = text.toLowerCase();

      console.log(`[${new Date().toISOString()}] Received message from ${context.activity.from.name}: ${text}`);

      try {
        const convId = context.activity.conversation.id;

        // ── Agent slug routing: @aurora-<slug> <question> ──────────────────
        const slugMatch = text.match(AGENT_SLUG_RE);
        if (slugMatch) {
          const slug = slugMatch[1].toLowerCase();
          const question = text.replace(AGENT_SLUG_RE, '').trim();
          if (question) {
            // Temporary default agent (30 min TTL) when the user uses a slug prefix
            await conversationReferenceStore.setDefaultAgent(convId, `aurora-${slug}`, 30);
            await this.agentHandler.handleAskAgentBySlug(context, `aurora-${slug}`, question);
          } else {
            await this.agentHandler.handleAgentSuggestions(context);
          }
        }
        // ── setChannelAgent @aurora-<slug> ─────────────────────────────────
        else if (SET_CHANNEL_AGENT_RE.test(text)) {
          const m = text.match(SET_CHANNEL_AGENT_RE)!;
          const slug = `aurora-${m[1].toLowerCase()}`;
          await conversationReferenceStore.setDefaultAgent(convId, slug);
          await context.sendActivity(
            `✅ This conversation is now scoped to **${slug}**. All messages will be answered through that agent.\n\nType \`clearChannelAgent\` to remove the scope.`
          );
        }
        // ── clearChannelAgent ──────────────────────────────────────────────
        else if (CLEAR_CHANNEL_AGENT_RE.test(lower)) {
          await conversationReferenceStore.setDefaultAgent(convId, null);
          await context.sendActivity('✅ Channel agent scope cleared. Aurora will answer directly.');
        }
        // ── subscribe @aurora-<slug> ───────────────────────────────────────
        else if (/^subscribe\s+@?aurora-([\w-]+)$/i.test(lower)) {
          const m = text.match(/^subscribe\s+@?aurora-([\w-]+)$/i)!;
          const slug = `aurora-${m[1].toLowerCase()}`;
          await conversationReferenceStore.subscribe(convId, slug);
          await context.sendActivity(
            `✅ Subscribed to proactive updates from **${slug}**.\n\nYou'll receive a message when there's new content. Type \`unsubscribe @${slug}\` to stop.`
          );
        }
        // ── unsubscribe @aurora-<slug> ─────────────────────────────────────
        else if (/^unsubscribe\s+@?aurora-([\w-]+)$/i.test(lower)) {
          const m = text.match(/^unsubscribe\s+@?aurora-([\w-]+)$/i)!;
          const slug = `aurora-${m[1].toLowerCase()}`;
          await conversationReferenceStore.unsubscribe(convId, slug);
          await context.sendActivity(`✅ Unsubscribed from **${slug}** updates.`);
        }
        // ── feed ──────────────────────────────────────────────────────────
        else if (lower === 'feed' || lower === 'show feed' || lower === 'my feed') {
          await this.feedHandler.handleShowFeedCommand(context, 5);
        }
        // ── agents / list agents ──────────────────────────────────────────
        else if (lower === 'agents' || lower === 'list agents' || lower === 'show agents') {
          await this.agentHandler.handleListAgents(context);
        }
        // ── follow <agent name> ────────────────────────────────────────────
        else if (lower.startsWith('follow ')) {
          await this.agentHandler.handleFollowAgent(context, text.substring(7).trim());
        }
        // ── unfollow <agent name> ──────────────────────────────────────────
        else if (lower.startsWith('unfollow ')) {
          await this.agentHandler.handleUnfollowAgent(context, text.substring(9).trim());
        }
        // ── ask <agent name> <question> ────────────────────────────────────
        else if (lower.startsWith('ask ')) {
          await this.agentHandler.handleAskAgent(context, text.substring(4).trim());
        }
        // ── help ───────────────────────────────────────────────────────────
        else if (lower === 'help' || lower === '?') {
          await this.sendHelpMessage(context);
        }
        // ── about ──────────────────────────────────────────────────────────
        else if (lower === 'about' || lower === 'info') {
          await this.sendAboutMessage(context);
        }
        // ── @<agent name> <question> ───────────────────────────────────────
        else if (text.startsWith('@')) {
          const afterAt = text.substring(1).trim();
          if (!afterAt) {
            await this.agentHandler.handleAgentSuggestions(context);
          } else {
            await this.agentHandler.handleAskAgent(context, afterAt);
          }
        }
        // ── Default: check for channel-scoped default agent first ──────────
        else if (text.length > 0) {
          const defaultSlug = await conversationReferenceStore.getDefaultAgent(convId);
          if (defaultSlug) {
            await this.agentHandler.handleAskAgentBySlug(context, defaultSlug, text);
          } else {
            await this.chatHandler.handleQuestion(context, text);
          }
        }
      } catch (error) {
        console.error('[ERROR] Error handling message:', error);
        await context.sendActivity('Sorry, I encountered an error. Please try again or type "help" for assistance.');
      }

      // Save state changes
      await this.conversationState.saveChanges(context, false);
      await this.userState.saveChanges(context, false);
      
      await next();
    });

    // Handle bot added to conversation — store reference for proactive messaging
    this.onMembersAdded(async (context, next) => {
      const membersAdded = context.activity.membersAdded;
      for (const member of membersAdded || []) {
        if (member.id !== context.activity.recipient.id) {
          console.log(`[${new Date().toISOString()}] New member added: ${member.name}`);
          await this.saveConversationRef(context);
          await this.sendWelcomeMessage(context);
        }
        // Bot itself was added — store the conversation ref so we can push proactively
        if (member.id === context.activity.recipient.id) {
          await this.saveConversationRef(context);
          console.log(`[${new Date().toISOString()}] Bot added to conversation — reference stored`);
        }
      }
      await next();
    });

    // Handle bot removed from conversation — delete the stored reference
    this.onMembersRemoved(async (context, next) => {
      const membersRemoved = context.activity.membersRemoved || [];
      for (const member of membersRemoved) {
        if (member.id === context.activity.recipient.id) {
          const convId = context.activity.conversation.id;
          await conversationReferenceStore.delete(convId).catch((err) =>
            console.warn('[AuroraBot] Failed to delete conversation reference:', err?.message)
          );
          console.log(`[${new Date().toISOString()}] Bot removed — conversation reference deleted`);
        }
      }
      await next();
    });

    // Handle conversation update (good for debugging)
    this.onConversationUpdate(async (context, next) => {
      console.log(`[${new Date().toISOString()}] Conversation updated: ${context.activity.type}`);
      await next();
    });
  }

  /** Store a conversation reference in PostgreSQL for proactive messaging. */
  private async saveConversationRef(context: TurnContext): Promise<void> {
    try {
      const activity = context.activity;
      const convType = activity.conversation?.conversationType || 'personal';
      const aadObjectId = (activity.from as any)?.aadObjectId ?? undefined;

      await conversationReferenceStore.save(
        {
          serviceUrl: activity.serviceUrl,
          conversation: activity.conversation,
          bot: activity.recipient,
        },
        {
          aadObjectId,
          conversationType: convType,
          channelId: activity.channelId,
        }
      );
    } catch (err) {
      // Non-fatal: proactive messaging just won't work for this conversation
      console.warn('[AuroraBot] Could not store conversation reference:', (err as Error).message);
    }
  }

  private async sendWelcomeMessage(context: TurnContext): Promise<void> {
    const welcomeCard = CardFactory.heroCard(
      '👋 Welcome to Aurora!',
      'Your intelligent knowledge assistant',
      [],
      [],
      {
        subtitle: 'I can help you stay informed and find information',
        text: `
**What I can do:**

📰 **Personalized Content Feed**
Get curated posts from industry experts and AI agents based on your interests.
Command: \`feed\`

🔮 **Knowledge Search**
Ask me anything about Wi-Fi standards, technology, or industry news.
Just type your question naturally!

🤖 **Agent Personas**
Talk to a specific creator agent: \`@aurora-<slug> your question\`
Lock a channel to one agent: \`setChannelAgent @aurora-<slug>\`

🔔 **Proactive Updates**
Subscribe to an agent's feed: \`subscribe @aurora-<slug>\`

💡 **Examples:**
• "feed" - View your content feed
• "What's new in Wi-Fi 7?" - Ask a question
• "@aurora-ietf What's happening in QUIC?" - Ask the IETF agent
• "help" - See all commands

**Ready to get started?** Try typing "feed" or ask me a question!
        `
      }
    );

    await context.sendActivity({ attachments: [welcomeCard] });
  }

  private async sendHelpMessage(context: TurnContext): Promise<void> {
    const helpCard = CardFactory.adaptiveCard({
      type: 'AdaptiveCard',
      version: '1.5',
      body: [
        {
          type: 'TextBlock',
          text: '📚 Aurora Bot Help',
          weight: 'Bolder',
          size: 'Large'
        },
        {
          type: 'TextBlock',
          text: 'Here\'s what I can help you with:',
          wrap: true,
          spacing: 'Medium'
        },
        {
          type: 'Container',
          spacing: 'Medium',
          items: [
            { type: 'TextBlock', text: '📰 Content Feed Commands', weight: 'Bolder' },
            {
              type: 'TextBlock',
              text: '• `feed` or `show feed` - View your personalized content feed\n• `my feed` - Same as above',
              wrap: true,
              spacing: 'Small'
            }
          ]
        },
        {
          type: 'Container',
          spacing: 'Medium',
          items: [
            { type: 'TextBlock', text: '🤖 Agent Commands', weight: 'Bolder' },
            {
              type: 'TextBlock',
              text: '• `agents` - List available AI content agents\n• `follow <agent name>` - Follow an agent\n• `unfollow <agent name>` - Unfollow an agent\n• `ask <agent name> <question>` - Ask from that agent\'s perspective\n• `@<agent name> <question>` - Shorthand for ask\n• `@aurora-<slug> <question>` - Ask by Teams slug (e.g. `@aurora-ietf What\'s new?`)\n• `setChannelAgent @aurora-<slug>` - Route ALL messages in this chat through one agent\n• `clearChannelAgent` - Remove channel-scoped agent',
              wrap: true,
              spacing: 'Small'
            }
          ]
        },
        {
          type: 'Container',
          spacing: 'Medium',
          items: [
            { type: 'TextBlock', text: '🔔 Proactive Notifications', weight: 'Bolder' },
            {
              type: 'TextBlock',
              text: '• `subscribe @aurora-<slug>` - Get pushed updates from an agent\n• `unsubscribe @aurora-<slug>` - Stop pushed updates',
              wrap: true,
              spacing: 'Small'
            }
          ]
        },
        {
          type: 'Container',
          spacing: 'Medium',
          items: [
            { type: 'TextBlock', text: '🔮 Ask Questions', weight: 'Bolder' },
            {
              type: 'TextBlock',
              text: 'Just type your question naturally! I\'ll search Aurora\'s knowledge base for answers.',
              wrap: true,
              spacing: 'Small'
            }
          ]
        },
        {
          type: 'Container',
          spacing: 'Medium',
          items: [
            { type: 'TextBlock', text: 'ℹ️ Other Commands', weight: 'Bolder' },
            {
              type: 'TextBlock',
              text: '• `help` or `?` - Show this help message\n• `about` - Learn about Aurora',
              wrap: true,
              spacing: 'Small'
            }
          ]
        }
      ]
    });

    await context.sendActivity({ attachments: [helpCard] });
  }

  private async sendAboutMessage(context: TurnContext): Promise<void> {
    const aboutText = `
**About Aurora** 🌟

Aurora is an intelligent knowledge management system that combines:
• **AI-Powered Content Creation** - Automated expert agents
• **Knowledge Graphs** - Connected information about topics, organizations, and people
• **Smart Search** - Natural language queries with contextual understanding

**Your Personal Assistant**
I connect you to Aurora's capabilities right here in Teams, providing:
✅ Personalized content recommendations
✅ Instant answers to your questions
✅ Links to full documents and sources
✅ Proactive updates when new content matches your interests

Built with ❤️ for staying informed about technology and industry standards.
    `;

    await context.sendActivity(MessageFactory.text(aboutText));
  }

  // Required for state persistence
  async run(context: TurnContext) {
    await super.run(context);
    await this.conversationState.saveChanges(context, false);
    await this.userState.saveChanges(context, false);
  }
}
  private feedHandler: FeedHandler;
  private chatHandler: ChatHandler;
  private agentHandler: AgentHandler;
  private conversationState: ConversationState;
  private userState: UserState;

  constructor(conversationState: ConversationState, userState: UserState) {
    super();

    this.conversationState = conversationState;
    this.userState = userState;
    this.feedHandler = new FeedHandler();
    this.chatHandler = new ChatHandler();
    this.agentHandler = new AgentHandler();

    // Handle incoming messages
    this.onMessage(async (context, next) => {
      // Strip Teams @mention tags: "<at>Bot Name</at> actual message"
      const rawText = context.activity.text?.trim() || '';
      const text = rawText.replace(/<at>[^<]*<\/at>/gi, '').trim();
      const lower = text.toLowerCase();

      console.log(`[${new Date().toISOString()}] Received message from ${context.activity.from.name}: ${text}`);

      try {
        // Command: show feed
        if (lower === 'feed' || lower === 'show feed' || lower === 'my feed') {
          await this.feedHandler.handleShowFeedCommand(context, 5);
        }
        // Command: list agents
        else if (lower === 'agents' || lower === 'list agents' || lower === 'show agents') {
          await this.agentHandler.handleListAgents(context);
        }
        // Command: follow <agent name>
        else if (lower.startsWith('follow ')) {
          await this.agentHandler.handleFollowAgent(context, text.substring(7).trim());
        }
        // Command: unfollow <agent name>
        else if (lower.startsWith('unfollow ')) {
          await this.agentHandler.handleUnfollowAgent(context, text.substring(9).trim());
        }
        // Command: ask <agent name> <question>
        else if (lower.startsWith('ask ')) {
          await this.agentHandler.handleAskAgent(context, text.substring(4).trim());
        }
        // Command: help
        else if (lower === 'help' || lower === '?') {
          await this.sendHelpMessage(context);
        }
        // Command: about
        else if (lower === 'about' || lower === 'info') {
          await this.sendAboutMessage(context);
        }
        // Command: @AgentName <question> — direct question to a named agent
        // Also handles bare "@" or "@partial" to show agent suggestions
        else if (text.startsWith('@')) {
          const afterAt = text.substring(1).trim();
          if (!afterAt) {
            // Just "@" — show full agent list with chip suggestions
            await this.agentHandler.handleAgentSuggestions(context);
          } else {
            // Try to route as "ask <name> <question>"
            // If the name doesn't resolve, handleAskAgent will show a helpful error
            await this.agentHandler.handleAskAgent(context, afterAt);
          }
        }
        // Default: treat as Oracle question
        else if (text.length > 0) {
          await this.chatHandler.handleQuestion(context, text);
        }
      } catch (error) {
        console.error('[ERROR] Error handling message:', error);
        await context.sendActivity('Sorry, I encountered an error. Please try again or type "help" for assistance.');
      }

      // Save state changes
      await this.conversationState.saveChanges(context, false);
      await this.userState.saveChanges(context, false);
      
      await next();
    });

    // Handle bot added to conversation
    this.onMembersAdded(async (context, next) => {
      const membersAdded = context.activity.membersAdded;
      for (const member of membersAdded || []) {
        if (member.id !== context.activity.recipient.id) {
          console.log(`[${new Date().toISOString()}] New member added: ${member.name}`);
          await this.sendWelcomeMessage(context);
        }
      }
      await next();
    });

    // Handle conversation update (good for debugging)
    this.onConversationUpdate(async (context, next) => {
      console.log(`[${new Date().toISOString()}] Conversation updated: ${context.activity.type}`);
      await next();
    });
  }

  private async sendWelcomeMessage(context: TurnContext): Promise<void> {
    const welcomeCard = CardFactory.heroCard(
      '👋 Welcome to Aurora!',
      'Your intelligent knowledge assistant',
      [],
      [],
      {
        subtitle: 'I can help you stay informed and find information',
        text: `
**What I can do:**

📰 **Personalized Content Feed**
Get curated posts from industry experts and AI agents based on your interests.
Command: \`feed\`

🔮 **Knowledge Search**
Ask me anything about Wi-Fi standards, technology, or industry news.
Just type your question naturally!

💡 **Examples:**
• "feed" - View your content feed
• "What's new in Wi-Fi 7?" - Ask a question
• "help" - See all commands

**Ready to get started?** Try typing "feed" or ask me a question!
        `
      }
    );

    await context.sendActivity({ attachments: [welcomeCard] });
  }

  private async sendHelpMessage(context: TurnContext): Promise<void> {
    const helpCard = CardFactory.adaptiveCard({
      type: 'AdaptiveCard',
      version: '1.5',
      body: [
        {
          type: 'TextBlock',
          text: '📚 Aurora Bot Help',
          weight: 'Bolder',
          size: 'Large'
        },
        {
          type: 'TextBlock',
          text: 'Here\'s what I can help you with:',
          wrap: true,
          spacing: 'Medium'
        },
        {
          type: 'Container',
          spacing: 'Medium',
          items: [
            {
              type: 'TextBlock',
              text: '📰 Content Feed Commands',
              weight: 'Bolder'
            },
            {
              type: 'TextBlock',
              text: '• `feed` or `show feed` - View your personalized content feed\n• `my feed` - Same as above',
              wrap: true,
              spacing: 'Small'
            }
          ]
        },
        {
          type: 'Container',
          spacing: 'Medium',
          items: [
            {
              type: 'TextBlock',
              text: '🤖 Agent Commands',
              weight: 'Bolder'
            },
            {
              type: 'TextBlock',
              text: '• `agents` - List all available AI content agents\n• `follow <agent name>` - Follow an agent\n• `unfollow <agent name>` - Unfollow an agent\n• `ask <agent name> <question>` - Ask from that agent\'s perspective\n• `@<agent name> <question>` - Shorthand for ask (e.g. `@TechWatcher what is Wi-Fi 7?`)\n• `@` alone — show agent list with quick-select chips',
              wrap: true,
              spacing: 'Small'
            }
          ]
        },
        {
          type: 'Container',
          spacing: 'Medium',
          items: [
            {
              type: 'TextBlock',
              text: '🔮 Ask Questions',
              weight: 'Bolder'
            },
            {
              type: 'TextBlock',
              text: 'Just type your question naturally! I\'ll search Aurora\'s knowledge base for answers.',
              wrap: true,
              spacing: 'Small'
            }
          ]
        },
        {
          type: 'Container',
          spacing: 'Medium',
          items: [
            {
              type: 'TextBlock',
              text: '💡 Example Questions',
              weight: 'Bolder'
            },
            {
              type: 'TextBlock',
              text: '• "What are MLO requirements?"\n• "Show me recent 802.11be updates"\n• "What is Wi-Fi 7?"',
              wrap: true,
              spacing: 'Small'
            }
          ]
        },
        {
          type: 'Container',
          spacing: 'Medium',
          items: [
            {
              type: 'TextBlock',
              text: 'ℹ️ Other Commands',
              weight: 'Bolder'
            },
            {
              type: 'TextBlock',
              text: '• `help` or `?` - Show this help message\n• `about` - Learn about Aurora',
              wrap: true,
              spacing: 'Small'
            }
          ]
        }
      ]
    });

    await context.sendActivity({ attachments: [helpCard] });
  }

  private async sendAboutMessage(context: TurnContext): Promise<void> {
    const aboutText = `
**About Aurora** 🌟

Aurora is an intelligent knowledge management system that combines:
• **AI-Powered Content Creation** - Automated expert agents
• **Knowledge Graphs** - Connected information about topics, organizations, and people
• **Smart Search** - Natural language queries with contextual understanding

**Your Personal Assistant**
I connect you to Aurora's capabilities right here in Teams, providing:
✅ Personalized content recommendations
✅ Instant answers to your questions
✅ Links to full documents and sources

Built with ❤️ for staying informed about technology and industry standards.
    `;

    await context.sendActivity(MessageFactory.text(aboutText));
  }

  // Required for state persistence
  async run(context: TurnContext) {
    await super.run(context);
    // Save any state changes
    await this.conversationState.saveChanges(context, false);
    await this.userState.saveChanges(context, false);
  }
}
