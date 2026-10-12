import { CardFactory, TurnContext } from 'botbuilder';
import { AuroraUserService } from '../services/auroraUserService';
import { AuroraAgentService } from '../services/auroraAgentService';
import { AuroraOracleService } from '../services/auroraOracleService';
import { getWorkingGroupBySlug, listWorkingGroups } from '../services/workingGroupResolver';
import { rememberAnswer, buildMarkdownResponse } from './chatHandler';
import { conversationReferenceStore } from '../services/conversationReferenceStore';

const ORACLE_TIMEOUT_MS = 30_000;

function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  return Promise.race([
    promise,
    new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error(`timeout after ${ms}ms`)), ms)
    ),
  ]);
}

/**
 * Handles agent-related commands:
 *   agents                         — list all available agents
 *   follow <agent name>            — follow an agent
 *   unfollow <agent name>          — unfollow an agent
 *   ask <agent name> <question>    — ask a question in the context of a specific agent
 */
export class AgentHandler {
  private userService: AuroraUserService;
  private oracleService: AuroraOracleService;

  constructor() {
    this.userService = new AuroraUserService();
    this.oracleService = new AuroraOracleService();
  }

  /**
   * Show a quick-select card of agents when the user types @ alone
   * or an unrecognised @ prefix.
   */
  async handleAgentSuggestions(context: TurnContext, partial: string = ''): Promise<void> {
    const email = this.userService.extractUserEmail(context.activity);
    const displayName = context.activity.from.name || 'User';
    const auroraUser = await this.userService.getOrCreateUser(email, displayName);
    const agentService = new AuroraAgentService(auroraUser.id, email);
    const agents = await agentService.listAgents();

    const filtered = (
      partial
        ? agents.filter((a) => {
            const slug = toTeamsSlug(a.teams_slug, a.name);
            return slug.includes(partial.toLowerCase()) || a.name.toLowerCase().includes(partial.toLowerCase());
          })
        : agents
    ).slice(0, 10);

    if (filtered.length === 0) {
      await context.sendActivity(`No agents match "@${partial}". Type \`/agents\` to see the full list.`);
      return;
    }

    const items: AgentListItem[] = filtered.map((a: any) => ({
      slug: toTeamsSlug(a.teams_slug, a.name),
      desc: (a.description || '').slice(0, 120),
      isCreatorAgent: true,
    }));

    const card = buildAgentListCard('Aurora Agents', items);
    await context.sendActivity({ attachments: [CardFactory.adaptiveCard(card)] });
  }

  /** List all content creator agents. */
  async handleListAgents(context: TurnContext): Promise<void> {
    const email = this.userService.extractUserEmail(context.activity);
    const displayName = context.activity.from.name || 'User';
    const auroraUser = await this.userService.getOrCreateUser(email, displayName);

    const agentService = new AuroraAgentService(auroraUser.id, email);
    let agents: any[] = [];
    try {
      agents = await agentService.listAgents();
    } catch {
      // Content creator service unavailable — show working groups only
    }

    const wgs = listWorkingGroups();

    const agentItems: AgentListItem[] = agents.map((a) => ({
      slug: toTeamsSlug(a.teams_slug, a.name),
      desc: (a.description || '').slice(0, 120),
      isCreatorAgent: true,
    }));

    const wgItems: AgentListItem[] = wgs.map((wg) => ({
      slug: wg.slug.replace(/^aurora-/, ''),
      desc: (wg.description || '').slice(0, 120),
      isCreatorAgent: false,
    }));

    const allItems = [...agentItems, ...wgItems];

    if (allItems.length === 0) {
      await context.sendActivity('No agents are configured yet.');
      return;
    }

    const card = buildAgentListCard('Aurora Agents', allItems);
    await context.sendActivity({ attachments: [CardFactory.adaptiveCard(card)] });
  }

  /** List the user's personal My-Agents with share-command hints. */
  async handleListMyAgents(context: TurnContext): Promise<void> {
    const email = this.userService.extractUserEmail(context.activity);
    const displayName = context.activity.from.name || 'User';
    const auroraUser = await this.userService.getOrCreateUser(email, displayName);
    const convId = context.activity.conversation?.id ?? 'default';
    // Only link the conversation to a real (non-synthetic) account so we don't
    // overwrite a previously-linked real aurora_user_id with a @teams.aad placeholder.
    if (!auroraUser.email.endsWith('@teams.aad')) {
      conversationReferenceStore.linkAuroraUser(convId, auroraUser.id).catch(() => {});
    }
    const agentService = new AuroraAgentService(auroraUser.id, email.startsWith('aad:') ? auroraUser.email : email);

    let myAgents: any[] = [];
    try {
      myAgents = await agentService.listUserAgents();
    } catch {
      await context.sendActivity('Could not reach the content creator service right now. Please try again.');
      return;
    }

    if (myAgents.length === 0) {
      await context.sendActivity(
        'You have no personal agents yet. Create them at aurora-octo.xcloudiq.com/profile/my-agents'
      );
      return;
    }

    const items: AgentListItem[] = myAgents.map((a) => ({
      slug: toTeamsSlug(a.teams_slug, a.name),
      desc: `${a.enabled ? '● active' : '○ paused'}${a.posting_cadence ? ` · ${a.posting_cadence}` : ''}${a.project_description ? ' — ' + (a.project_description as string).slice(0, 80) : ''}`,
      isCreatorAgent: false, // personal agents: talk only (no public subscribe)
    }));

    const card = buildAgentListCard('My Personal Agents', items);
    await context.sendActivity({ attachments: [CardFactory.adaptiveCard(card)] });
  }

  /** Follow an agent by name. */
  async handleFollowAgent(context: TurnContext, agentName: string): Promise<void> {
    if (!agentName.trim()) {
      await context.sendActivity('Please specify an agent name. Example: `/follow TechWatcher`');
      return;
    }

    const email = this.userService.extractUserEmail(context.activity);
    const displayName = context.activity.from.name || 'User';
    const auroraUser = await this.userService.getOrCreateUser(email, displayName);
    const agentService = new AuroraAgentService(auroraUser.id, email);

    const agent = await agentService.findAgentByName(agentName);
    if (!agent) {
      await context.sendActivity(
        `No agent found matching "${agentName}". Type \`/agents\` to see what's available.`
      );
      return;
    }

    await agentService.followAgent(agent.id, auroraUser.id);
    await context.sendActivity(
      `Now following **${agent.name}**. Their posts will appear in your feed.`
    );
  }

  /** Unfollow an agent by name. */
  async handleUnfollowAgent(context: TurnContext, agentName: string): Promise<void> {
    if (!agentName.trim()) {
      await context.sendActivity('Please specify an agent name. Example: `/unfollow TechWatcher`');
      return;
    }

    const email = this.userService.extractUserEmail(context.activity);
    const displayName = context.activity.from.name || 'User';
    const auroraUser = await this.userService.getOrCreateUser(email, displayName);
    const agentService = new AuroraAgentService(auroraUser.id, email);

    const agent = await agentService.findAgentByName(agentName);
    if (!agent) {
      await context.sendActivity(
        `No agent found matching "${agentName}". Type \`/agents\` to see what's available.`
      );
      return;
    }

    await agentService.unfollowAgent(agent.id, auroraUser.id);
    await context.sendActivity(`Unfollowed **${agent.name}**.`);
  }

  /**
   * Ask a question directed at a specific agent persona.
   * Routes to Oracle with added context about the agent so the answer
   * reflects that agent's style / knowledge area.
   *
   * Command format: ask <agent name> <question>
   * Parsing: everything up to the first word boundary before "?" or after
   * the agent name is the question.
   */
  async handleAskAgent(context: TurnContext, rawArgs: string): Promise<void> {
    // Attempt to split: first "word(s)" up to 3 tokens = agent name, rest = question
    // e.g. "TechWatcher what is Wi-Fi 7?" → agent="TechWatcher", q="what is Wi-Fi 7?"
    //      "Tech Watcher what is Wi-Fi 7?" → agent="Tech Watcher", q="what is Wi-Fi 7?"
    const parts = rawArgs.trim().split(/\s+/);
    if (parts.length < 2) {
      await context.sendActivity(
        'Usage: `ask <agent name> <question>`\nExample: `ask TechWatcher What is Wi-Fi 7?`'
      );
      return;
    }

    const email = this.userService.extractUserEmail(context.activity);
    const displayName = context.activity.from.name || 'User';
    const auroraUser = await this.userService.getOrCreateUser(email, displayName);
    const agentService = new AuroraAgentService(auroraUser.id, email);
    const agents = await agentService.listAgents();

    // Try matching progressively longer prefixes of parts[] as the agent name
    let matchedAgent = null;
    let questionStart = 1;
    for (let i = Math.min(parts.length - 1, 4); i >= 1; i--) {
      const candidate = parts.slice(0, i).join(' ');
      const found = agents.find((a) => a.name.toLowerCase().startsWith(candidate.toLowerCase()));
      if (found) {
        matchedAgent = found;
        questionStart = i;
        break;
      }
    }

    if (!matchedAgent) {
      await context.sendActivity(
        `No agent found matching "${rawArgs}". Type \`/agents\` to see what's available.`
      );
      return;
    }

    const question = parts.slice(questionStart).join(' ');
    if (!question.trim()) {
      await context.sendActivity(`Please include a question after the agent name. Example: \`ask ${matchedAgent.name} What is Wi-Fi 7?\``);
      return;
    }

    // Build the AgentPersona payload so oracle responds in the agent's voice
    const agentPersona = {
      name: matchedAgent.name,
      persona: matchedAgent.persona,
      tone_style: matchedAgent.tone_style || 'analytical',
      content_length_preference: matchedAgent.content_length_preference || 'medium',
      expertise_topics: matchedAgent.expertise_topics || [],
      expertise_organisations: matchedAgent.expertise_organisations || [],
      expertise_standards: matchedAgent.expertise_standards || [],
      llm_temperature_override: matchedAgent.llm_temperature_override ?? null,
    };

    try {
      const response = await withTimeout(
        this.oracleService.query(auroraUser.id, question, agentPersona, undefined, auroraUser.email),
        ORACLE_TIMEOUT_MS
      );
      await this.sendOracleResponse(context, matchedAgent.name, response, question);
    } catch (err: any) {
      const isTimeout = err?.message?.includes('timeout');
      await context.sendActivity(isTimeout
        ? `That query is taking too long. Try a more specific question.`
        : `**${matchedAgent.name}** could not retrieve an answer right now. Please try again.`
      );
    }
  }

  /**
   * Ask a question directed at a specific agent persona resolved by Teams slug.
   * Used when the user types @aurora-<slug> <question>.
   */
  async handleAskAgentBySlug(context: TurnContext, teamsSlug: string, question: string): Promise<void> {
    const email = this.userService.extractUserEmail(context.activity);
    const displayName = context.activity.from.name || 'User';
    const auroraUser = await this.userService.getOrCreateUser(email, displayName);
    const agentService = new AuroraAgentService(auroraUser.id, email);

    // 1. Try creator agent first
    const agent = await agentService.getAgentBySlug(teamsSlug);
    if (agent) {
      const agentPersona = {
        name: agent.name,
        persona: agent.persona,
        tone_style: agent.tone_style || 'analytical',
        content_length_preference: agent.content_length_preference || 'medium',
        expertise_topics: agent.expertise_topics || [],
        expertise_organisations: agent.expertise_organisations || [],
        expertise_standards: agent.expertise_standards || [],
        llm_temperature_override: agent.llm_temperature_override ?? null,
      };
      await context.sendActivity(`Asking **${agent.name}**...`);
      try {
        const response = await withTimeout(
          this.oracleService.query(auroraUser.id, question, agentPersona, undefined, auroraUser.email),
          ORACLE_TIMEOUT_MS
        );
        await this.sendOracleResponse(context, agent.name, response, question);
      } catch (err: any) {
        const isTimeout = err?.message?.includes('timeout');
        await context.sendActivity(isTimeout
          ? `That query is taking too long. Try a more specific question.`
          : `**${agent.name}** could not retrieve an answer right now. Please try again.`
        );
      }
      return;
    }

    // 2. Fall back to working group persona from registry
    const wg = getWorkingGroupBySlug(teamsSlug);
    if (wg) {
      const wgPersona = {
        name: wg.name,
        persona: wg.persona,
        tone_style: wg.tone_style,
        content_length_preference: 'medium',
        expertise_topics: wg.expertise_topics,
        expertise_organisations: wg.expertise_organisations,
        expertise_standards: [],
        llm_temperature_override: null,
      };
      await context.sendActivity(`Asking **${wg.name}**...`);
      try {
        // Pass datasource_ids so results are scoped to this WG's sources, not all sources
        const response = await withTimeout(
          this.oracleService.query(auroraUser.id, question, wgPersona, wg.datasource_ids, auroraUser.email),
          ORACLE_TIMEOUT_MS
        );
        await this.sendOracleResponse(context, wg.name, response, question);
      } catch (err: any) {
        const isTimeout = err?.message?.includes('timeout');
        await context.sendActivity(isTimeout
          ? `That query is taking too long. Try a more specific question.`
          : `**${wg.name}** could not retrieve an answer right now. Please try again.`
        );
      }
      return;
    }

    // 3. Try as a personal My-Agent handle (e.g. @edgeai, @pqc-project).
    //    Personal-agent handles in user_agent.teams_slug are stored WITHOUT the
    //    "aurora-" prefix (that prefix is the creator-agent convention only).
    //    canonicalSlug() always prepends "aurora-", so strip it back off here
    //    before the lookup or @edgeai will hit "aurora-edgeai" and miss.
    const personalHandle = teamsSlug.replace(/^aurora-/, '');
    try {
      const personalAgent = await agentService.getUserAgentBySlug(personalHandle);
      if (personalAgent) {
        const description = personalAgent.project_description || personalAgent.persona || '';
        const persona = {
          name: personalAgent.name,
          persona: `You are ${personalAgent.name}. ${description}`,
          tone_style: 'analytical' as const,
          content_length_preference: 'medium',
          expertise_topics: personalAgent.expertise_topics || [],
          expertise_organisations: [] as string[],
          expertise_standards: [] as string[],
          llm_temperature_override: null,
        };
        await context.sendActivity(`Asking **${personalAgent.name}**...`);
        try {
          const response = await withTimeout(
            this.oracleService.query(auroraUser.id, question, persona, undefined, auroraUser.email),
            ORACLE_TIMEOUT_MS
          );
          await this.sendOracleResponse(context, personalAgent.name, response, question);
        } catch (err: any) {
          const isTimeout = err?.message?.includes('timeout');
          await context.sendActivity(isTimeout
            ? `That query is taking too long. Try a more specific question.`
            : `**${personalAgent.name}** could not retrieve an answer right now. Please try again.`
          );
        }
        return;
      }
    } catch { /* fall through */ }

    // 4. Try as a datasource filter (e.g. @wifi8mtg, @wfa, @broadcast)
    // Strip aurora- prefix for datasource resolution
    const datasourceSlug = teamsSlug.replace(/^aurora-/, '');
    try {
      const resolved = await this.oracleService.resolveMentionsToDatasourceIds([datasourceSlug]);
      if (resolved.length > 0) {
        console.log(`[AgentHandler] Routing @${datasourceSlug} as datasource filter: ${resolved}`);
        const dsUser = await this.userService.getOrCreateUser(
          this.userService.extractUserEmail(context.activity),
          context.activity.from.name || 'User'
        );
        const response = await withTimeout(
          this.oracleService.query(dsUser.id, question, undefined, resolved, dsUser.email),
          ORACLE_TIMEOUT_MS
        );
        await this.sendOracleResponse(context, datasourceSlug, response, question);
        return;
      }
    } catch { /* fall through */ }

    // Nothing matched — show a card with close working-group matches and a fallback
    const wgs = listWorkingGroups();
    const slug = teamsSlug.toLowerCase();
    const closeMatches = wgs
      .filter((wg) =>
        wg.slug.replace(/^aurora-/, '').includes(slug) ||
        wg.name.toLowerCase().includes(slug) ||
        (wg.description || '').toLowerCase().includes(slug)
      )
      .slice(0, 5);

    if (closeMatches.length > 0) {
      const items: AgentListItem[] = closeMatches.map((wg) => ({
        slug: wg.slug.replace(/^aurora-/, ''),
        desc: wg.description || '',
        isCreatorAgent: false,
      }));
      const hint = question ? `Did you mean one of these? They can answer: "${question}"` : 'Did you mean one of these?';
      const card = buildAgentListCard(`No agent found for "@${teamsSlug}" — close matches:`, items);
      await context.sendActivity(hint);
      await context.sendActivity({ attachments: [CardFactory.adaptiveCard(card)] });
    } else {
      await context.sendActivity(
        `No agent found for "@${teamsSlug}". Type \`/agents\` to browse all available agents, or just ask Aurora directly.`
      );
    }
  }

  private async sendOracleResponse(
    context: TurnContext,
    speakerName: string,
    response: any,
    question: string
  ): Promise<void> {
    if (!response.answer && (!response.documents || response.documents.length === 0)) {
      await context.sendActivity(`**${speakerName}** couldn't find relevant information for that question.`);
      return;
    }

    // Store in conversation memory so 'enhance' works after any @slug query
    const convId = context.activity.conversation?.id ?? 'default';
    if (response.answer) {
      rememberAnswer(convId, question, response.answer, response.documents);
    }

    const text = buildMarkdownResponse(
      response.answer || 'Here are the relevant results:',
      response.documents ?? [],
      speakerName,
    );
    const hasDocs = (response.documents?.length ?? 0) > 0;
    await context.sendActivity(
      hasDocs
        ? {
            text,
            // Suggested-action chip beneath the message — "Enhance" re-runs
            // the answer with deeper source analysis (uses the docs already
            // retrieved). imBack sends the value back to the bot as if typed,
            // hitting the existing handler in bot.ts. The "show" command is
            // intentionally NOT exposed here — it's only meaningful for the
            // last proactive agent notification, not for an interactive Q&A.
            suggestedActions: {
              to: context.activity.from ? [context.activity.from.id] : [],
              actions: [
                { type: 'imBack', title: '🔍 Enhance', value: 'enhance' },
              ],
            },
          }
        : text,
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

interface AgentListItem {
  slug: string;          // clean, space-free slug  e.g. "mister-multipath"
  desc: string;          // one-line description shown beneath the slug
  isCreatorAgent: boolean; // true → show [subscribe] button; false → [talk] only
}

/**
 * Convert a raw teams_slug or display name into a clean, hyphenated slug
 * with no spaces and no "aurora-" prefix.
 *
 * Examples:
 *   "aurora-mister-multipath" → "mister-multipath"
 *   "Mister Multipath"        → "mister-multipath"
 *   "IETF"                    → "ietf"
 */
function toTeamsSlug(teamsSlug: string | null | undefined, displayName: string): string {
  const raw = (teamsSlug || displayName || '').trim();
  return raw
    .toLowerCase()
    .replace(/^aurora-/, '')
    .replace(/[^a-z0-9-]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

/**
 * Build a compact Adaptive Card listing agents/datasources.
 *
 * Each row:
 *   @slug  [subscribe]  [talk]     ← creator agents
 *   @slug  [talk]                  ← datasources / personal agents
 *   description text (subtle, small)
 *
 * Buttons use Action.Submit with msteams imBack so Teams sends the value
 * back to the bot as a new message:
 *   [talk]      → "setChannelAgent <slug>"   (sets conversation scope)
 *   [subscribe] → "subscribe @<slug>"        (subscribe to posts)
 */
function buildAgentListCard(
  title: string,
  items: AgentListItem[],
): Record<string, unknown> {
  const rows: Record<string, unknown>[] = [];

  for (let i = 0; i < items.length; i++) {
    const item = items[i];

    const talkAction = {
      type: 'Action.Submit',
      title: 'talk',
      style: 'positive',
      data: { msteams: { type: 'imBack', value: `/setChannelAgent ${item.slug}` } },
    };

    const subscribeAction = {
      type: 'Action.Submit',
      title: 'subscribe',
      data: { msteams: { type: 'imBack', value: `/subscribe @${item.slug}` } },
    };

    // Info column: @slug + description
    const infoColumn: Record<string, unknown> = {
      type: 'Column',
      width: 'stretch',
      items: [
        {
          type: 'TextBlock',
          text: `**@${item.slug}**`,
          wrap: false,
          spacing: 'None',
        },
        ...(item.desc
          ? [{
              type: 'TextBlock',
              text: item.desc,
              isSubtle: true,
              size: 'Small',
              wrap: true,
              spacing: 'None',
            }]
          : []),
      ],
    };

    // Button column: [subscribe] [talk] or just [talk]
    const buttonActions: Record<string, unknown>[] = [
      ...(item.isCreatorAgent ? [subscribeAction] : []),
      talkAction,
    ];

    const buttonColumn: Record<string, unknown> = {
      type: 'Column',
      width: 'auto',
      verticalContentAlignment: 'Center',
      items: [{
        type: 'ActionSet',
        actions: buttonActions,
      }],
    };

    rows.push({
      type: 'ColumnSet',
      separator: i > 0,
      spacing: i > 0 ? 'Small' : 'None',
      columns: [infoColumn, buttonColumn],
    });
  }

  return {
    type: 'AdaptiveCard',
    $schema: 'http://adaptivecards.io/schemas/adaptive-card.json',
    version: '1.3',
    body: [
      {
        type: 'TextBlock',
        text: title,
        weight: 'Bolder',
        size: 'Medium',
        spacing: 'None',
      },
      {
        type: 'TextBlock',
        text: 'Type `@handle your question` at any time, or click **talk** to scope this conversation to an agent. Type `/clear` to return to general Aurora.',
        isSubtle: true,
        size: 'Small',
        wrap: true,
        spacing: 'Small',
      },
      ...rows,
    ],
  };
}
