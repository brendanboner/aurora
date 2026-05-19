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
import { lastPostByConv, lastDeliveredPost } from './services/proactiveMessenger';

// Matches @<slug> or @aurora-<slug> at the start of a message.
// The @ is required to avoid matching regular words as agent names.
// In Teams group chat the @ is preserved in plain text (only stripped
// when wrapped in <at></at> tags, which only happens for the bot itself).
const AGENT_SLUG_RE = /^@(?:aurora-)?([\w-]+)(?:\s|$)/i;

/** Normalise a slug/mention to the canonical aurora-<slug> form. */
function canonicalSlug(raw: string): string {
  const s = raw.toLowerCase().replace(/^@/, '').replace(/^aurora-/, '');
  return `aurora-${s}`;
}

// Keywords that indicate a message is about Wi-Fi / standards topics Aurora can help with
const AURORA_TOPIC_RE = /\b(wi-?fi|802\.1[01356]|ieee|ietf|wba|wfa|5g|6g|spectrum|standard|amendment|certification|handover|roaming|tgbn|802\.11bn|wi-fi\s*8|wi-?fi\s*7|mlr?o|ofdma|qos|latency|throughput|passpoint|openroaming|tsn|pqc|post.quantum|ambient.power|ultra.high.reliability)\b/i;

// Question patterns (the message is asking something, not just stating)
const QUESTION_RE = /(\?$|^(do|does|did|can|will|would|should|is|are|was|were|has|have|had|what|when|where|who|why|how)\b)/i;

// Demo: conversations that have opted into group-simulation mode (for Agents Playground)
const groupModeConversations = new Set<string>();

// Commands that set a conversation-scoped default agent
const SET_CHANNEL_AGENT_RE = /^setChannelAgent\s+@?(?:aurora-)?([\w-]+)$/i;
const CLEAR_CHANNEL_AGENT_RE = /^(clearChannelAgent|clear|reset|general|exit)$/i;

// Webhook management commands
// setAgentWebhook @aurora-ietf https://outlook.office.com/webhook/...
const SET_WEBHOOK_RE   = /^setAgentWebhook\s+@?aurora-([\w-]+)\s+(https:\/\/\S+)$/i;
const REMOVE_WEBHOOK_RE = /^removeAgentWebhook\s+@?aurora-([\w-]+)$/i;

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
      // Also strip plain-text bot name prefixes that Agents Playground may inject
      const rawText = context.activity.text?.trim() || '';
      let text = rawText.replace(/<at>[^<]*<\/at>/gi, '').trim();
      // Strip plain-text bot mention prefix (e.g. "Test Bot groupmode on" → "groupmode on")
      const botName = (context.activity.recipient?.name || '').trim();
      if (botName && text.toLowerCase().startsWith(botName.toLowerCase())) {
        text = text.slice(botName.length).trim();
      }
      // Also strip generic "aurora " prefix
      if (/^aurora\s+/i.test(text)) {
        text = text.replace(/^aurora\s+/i, '').trim();
      }
      const lower = text.toLowerCase().trim();

      console.log(`[${new Date().toISOString()}] Received message from ${context.activity.from.name}: "${text}" (lower="${lower}"`);

      try {
        const convId = context.activity.conversation.id;

        // ── EXPLICIT COMMANDS — checked first, always override any agent scope ──
        // clear / reset / exit — escape from any scoped workgroup context
        if (CLEAR_CHANNEL_AGENT_RE.test(lower)) {
          await conversationReferenceStore.setDefaultAgent(convId, null);
          groupModeConversations.delete(convId);
          await context.sendActivity('Cleared. Back to general questions.');
        }
        // groupmode on / off — accept "groupmode on", "group mode on", "groupmode", etc.
        else if (/^group\s*mode\s*(on|true|enable|1)?$/i.test(lower)) {
          groupModeConversations.add(convId);
          await context.sendActivity(
            'Group mode on.\n\nAurora will now watch for Wi-Fi and standards questions in this conversation and add context automatically — no @mention needed.\n\nType a question about Wi-Fi 8, handover, 802.11bn etc.\nType `groupmode off` or `clear` to turn off.'
          );
        }
        else if (/^group\s*mode\s*(off|false|disable|0)$/i.test(lower)) {
          groupModeConversations.delete(convId);
          await context.sendActivity('Group mode off.');
        }
        // ── Agent slug routing: @<slug> or @aurora-<slug> + question ──────
        else if (text.match(AGENT_SLUG_RE)) {
          const slugMatch = text.match(AGENT_SLUG_RE)!;
          const slug = canonicalSlug(slugMatch[1]);
          const question = text.replace(AGENT_SLUG_RE, '').trim();
          if (question) {
            await conversationReferenceStore.setDefaultAgent(convId, slug, 30);
            await this.agentHandler.handleAskAgentBySlug(context, slug, question);
          } else {
            await this.agentHandler.handleAgentSuggestions(context);
          }
        }
        // ── setChannelAgent @aurora-<slug> ─────────────────────────────────
        else if (SET_CHANNEL_AGENT_RE.test(text)) {
          const m = text.match(SET_CHANNEL_AGENT_RE)!;
          const slug = canonicalSlug(m[1]);
          await conversationReferenceStore.setDefaultAgent(convId, slug);
          await context.sendActivity(
            `Scoped to **${slug}**. All messages answered through that agent.\n\n_Type \`clear\` to return to general questions._`
          );
        }
        // ── setAgentWebhook @aurora-<slug> https://... ─────────────────────
        else if (SET_WEBHOOK_RE.test(text)) {
          const m = text.match(SET_WEBHOOK_RE)!;
          const slug = `aurora-${m[1].toLowerCase()}`;
          const url  = m[2];
          await conversationReferenceStore.setWebhookUrl(convId, slug, url);
          // Also subscribe so bot push also works as a fallback
          await conversationReferenceStore.subscribe(convId, slug);
          await context.sendActivity(
            `Webhook set for **${slug}** in this conversation. Posts will arrive with the agent's custom name and icon.\n\nTo remove: \`removeAgentWebhook @${slug}\``
          );
        }
        // ── removeAgentWebhook @aurora-<slug> ──────────────────────────────
        else if (REMOVE_WEBHOOK_RE.test(text)) {
          const m = text.match(REMOVE_WEBHOOK_RE)!;
          const slug = `aurora-${m[1].toLowerCase()}`;
          await conversationReferenceStore.removeWebhookUrl(convId, slug);
          await context.sendActivity(`Webhook removed for **${slug}**. Bot push will be used instead if subscribed.`);
        }
        // ── subscribe @aurora-<slug> or subscribe @<slug> ─────────────────
        else if (/^subscribe\s+@?(?:aurora-)?([\w-]+)$/i.test(lower)) {
          const m = text.match(/^subscribe\s+@?(?:aurora-)?([\w-]+)$/i)!;
          const slug = `aurora-${m[1].toLowerCase()}`;
          const displaySlug = slug.replace(/^aurora-/, '');
          await conversationReferenceStore.subscribe(convId, slug);
          await context.sendActivity(
            `Subscribed to **${displaySlug}**. You'll receive a message when there's new content. Type \`unsubscribe @${displaySlug}\` to stop.`
          );
        }
        // ── unsubscribe @aurora-<slug> or unsubscribe @<slug> ─────────────
        else if (/^unsubscribe\s+@?(?:aurora-)?([\w-]+)$/i.test(lower)) {
          const m = text.match(/^unsubscribe\s+@?(?:aurora-)?([\w-]+)$/i)!;
          const slug = `aurora-${m[1].toLowerCase()}`;
          await conversationReferenceStore.unsubscribe(convId, slug);
          await context.sendActivity(`Unsubscribed from **${slug.replace(/^aurora-/, '')}**.`);
        }
        // ── subscriptions / my subscriptions ──────────────────────────────
        else if (lower === 'subscriptions' || lower === 'my subscriptions' || lower === 'following') {
          const ref = await conversationReferenceStore.get(convId);
          const slugs: string[] = ref?.subscribed_agent_slugs ?? [];
          if (slugs.length === 0) {
            await context.sendActivity(
              `No active subscriptions. Type \`subscribe @slug\` to receive updates from an agent, or \`agents\` to see what's available.`
            );
          } else {
            const list = slugs.map(s => `• \`@${s.replace(/^aurora-/, '')}\``).join('\n');
            await context.sendActivity(
              `**Subscriptions (${slugs.length}):**\n\n${list}\n\nType \`unsubscribe @aurora-slug\` to remove one.`
            );
          }
        }
        // ── share / unshare personal agent with this group ────────────────
        // "share Wi-Fi 8 Daily Brief" — adds this My-Agent to the group opt-in list
        else if (/^share\s+.+/i.test(lower)) {
          const agentName = text.slice(6).trim();
          const convType = context.activity.conversation?.conversationType ?? 'personal';
          if (convType === 'personal') {
            await context.sendActivity('Personal agent sharing is only needed for group chats. In personal chat your My-Agents always appear automatically.');
          } else {
            await conversationReferenceStore.sharePersonalAgent(convId, agentName);
            await context.sendActivity(`**${agentName}** will now share posts to this group when they publish.\n\nTo stop: \`unshare ${agentName}\``);
          }
        }
        else if (/^unshare\s+.+/i.test(lower)) {
          const agentName = text.slice(8).trim();
          await conversationReferenceStore.unsharePersonalAgent(convId, agentName);
          await context.sendActivity(`**${agentName}** removed from this group's shared agents.`);
        }
        else if (lower === 'shared' || lower === 'shared agents') {
          const shared = await conversationReferenceStore.getSharedPersonalAgents(convId);
          if (shared.length === 0) {
            await context.sendActivity('No personal agents are shared to this group.\n\nTo share one: `share Agent Name`');
          } else {
            await context.sendActivity(`**Personal agents shared here:**\n\n${shared.map(s => `• ${s}`).join('\n')}\n\nTo remove: \`unshare Agent Name\``);
          }
        }
        // ── show — inline full post from last proactive notification ─────
        else if (lower === 'show' || lower === 'read more' || lower === 'full post') {
          // Try per-conv first, fall back to the most recently delivered post globally
          const post = lastPostByConv.get(convId) || lastDeliveredPost;
          if (!post) {
            await context.sendActivity('No recent post to show. Subscribe to an agent and wait for a notification, then type `show`.');
          } else {
            await context.sendActivity(`**${post.title}**\n*By ${post.agent_name}*\n\n${post.body}`);
          }
        }
        // ── my agents — list personal agents with share hints ─────────────
        else if (lower === 'my agents' || lower === 'my agent' || lower === 'myagents') {
          await this.agentHandler.handleListMyAgents(context);
        }
        // ── feed ──────────────────────────────────────────────────────────
        else if (lower === 'feed' || lower === 'show feed' || lower === 'my feed') {
          await this.feedHandler.handleShowFeedCommand(context, 5);
        }
        // ── enhance ───────────────────────────────────────────────────────
        else if (lower === 'enhance' || lower === 'enhance answer' || lower === 'more detail') {
          await this.chatHandler.handleEnhance(context);
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
            // Remind user how to exit the scoped context (shown once per message)
            // Note: hint is subtle — appended only if answer was short/empty to avoid noise
          } else {
            // ── Routing for group vs personal ──────────────────────────────
            // Direct @mention (group or personal) → full answer, always.
            // groupmode passive listening (no @mention) → brief context snippet.
            const convType = context.activity.conversation?.conversationType ?? 'personal';
            const wasDirectlyMentioned = rawText.includes('<at>');
            const isPassiveGroupMode = groupModeConversations.has(convId) && !wasDirectlyMentioned;

            if (isPassiveGroupMode && QUESTION_RE.test(text) && AURORA_TOPIC_RE.test(text)) {
              // Bot is passively listening in groupmode — add brief context without taking over
              await this.chatHandler.handleGroupContextQuestion(context, text);
            } else {
              // Directly addressed (personal chat or @mention in group) — give the full answer
              await this.chatHandler.handleQuestion(context, text);
            }
          }
        }
      } catch (error: any) {
        const detail = error?.response?.data ?? error?.message ?? String(error);
        console.error('[ERROR] Error handling message:', detail);
        console.error(error);
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
      // Non-fatal: proactive messaging won't work for this conversation (expected when no DB)
      console.debug('[AuroraBot] Could not store conversation reference:', (err as Error).message);
    }
  }

  private async sendWelcomeMessage(context: TurnContext): Promise<void> {
    const welcomeCard = CardFactory.heroCard(
      'Aurora',
      'Wi-Fi and standards intelligence, directly in Teams.',
      [],
      [],
      {
        text: `**Getting started**

• Type \`feed\` to see your personalised content feed
• Ask any question — Aurora searches Wi-Fi Alliance, WBA, IETF, and IEEE sources
• Type \`agents\` to see available expert agents
• Type \`help\` for all commands`
      }
    );

    await context.sendActivity({ attachments: [welcomeCard] });
  }

  private async sendHelpMessage(context: TurnContext): Promise<void> {
    const help = `**Aurora — Commands**

**Feed**
• \`feed\` — Your personalised content feed
• \`my agents\` — List your personal My-Agents with share instructions
• \`show\` — Read the full text of the last agent notification inline
• \`enhance\` — Re-run the last answer with full source document analysis for deeper citations

**Agents**
• \`agents\` — List available AI agents
• \`@slug question\` — Ask a specific agent (e.g. \`@ietf What is new?\`, \`@wifi8mtg What was discussed?\`)
• \`setChannelAgent @slug\` — Lock this channel to one agent
• \`clearChannelAgent\` — Remove the channel lock

**Group Channel Mode**
• \`groupmode on\` — Aurora monitors for Wi-Fi and standards questions and adds context
• \`groupmode off\` — Back to direct-query mode

**Proactive Updates**
• \`subscribe @slug\` — Receive posts from a system agent in this chat
• \`unsubscribe @slug\` — Stop notifications
• \`subscriptions\` — List active subscriptions
• \`share Agent Name\` — Share a personal My-Agent's output to this group *(group chats only)*
• \`unshare Agent Name\` — Stop sharing
• \`shared\` — List personal agents shared to this group

**Other**
• \`about\` — About Aurora
• \`help\` — This message

Or just type any question and Aurora will search its knowledge base.`;

    await context.sendActivity(help);
  }

  private async sendAboutMessage(context: TurnContext): Promise<void> {
    const aboutText = `**About Aurora**

Aurora is an intelligent knowledge system built on Wi-Fi Alliance, WBA, IETF, and IEEE standards content. It combines:

• AI-powered expert agents that generate and curate content
• A knowledge graph connecting topics, organisations, and people
• Natural language search across member-only and public sources

In Teams, Aurora provides personalised content feeds, instant answers with source citations, and proactive updates when new content matches your interests.

Type \`help\` for a list of commands.`;

    await context.sendActivity(MessageFactory.text(aboutText));
  }

  // Required for state persistence
  async run(context: TurnContext) {
    await super.run(context);
    await this.conversationState.saveChanges(context, false);
    await this.userState.saveChanges(context, false);
  }
}
