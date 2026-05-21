import { CardFactory, TurnContext } from 'botbuilder';
import { AuroraUserService } from '../services/auroraUserService';
import { AuroraAgentService } from '../services/auroraAgentService';
import { AuroraOracleService } from '../services/auroraOracleService';
import { getWorkingGroupBySlug, listWorkingGroups } from '../services/workingGroupResolver';
import { rememberAnswer, buildMarkdownResponse } from './chatHandler';

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

    const filtered = partial
      ? agents.filter((a) => a.name.toLowerCase().startsWith(partial.toLowerCase()))
      : agents;

    if (filtered.length === 0) {
      await context.sendActivity(`No agents match "@${partial}". Type \`agents\` to see the full list.`);
      return;
    }

    const card = buildAgentListCard(
      'Aurora Agents',
      filtered.slice(0, 10).map((a: any) => ({
        name: a.name,
        desc: (a.description || a.persona || '').slice(0, 80),
        value: `@${(a.teams_slug || a.name).replace(/^aurora-/, '')} `,
      })),
      'Select an agent to start a conversation:',
    );
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

    // Build a combined card: creator agents + working groups + clear
    const allItems = [
      ...agents.map((a) => ({
        name: a.name,
        desc: (a.description || a.persona || '').slice(0, 80),
        value: `@${(a.teams_slug || a.name).replace(/^aurora-/, '')} `,
      })),
      ...wgs.map((wg) => ({
        name: wg.name,
        desc: wg.description || '',
        value: `@${wg.slug.replace(/^aurora-/, '')} `,
      })),
    ];

    if (allItems.length === 0) {
      await context.sendActivity('No agents are configured yet.');
      return;
    }

    const card = buildAgentListCard('Aurora Agents', allItems, 'Click an agent to start a conversation:');
    await context.sendActivity({ attachments: [CardFactory.adaptiveCard(card)] });
  }

  /** List the user's personal My-Agents with share-command hints. */
  async handleListMyAgents(context: TurnContext): Promise<void> {
    const email = this.userService.extractUserEmail(context.activity);
    const displayName = context.activity.from.name || 'User';
    const auroraUser = await this.userService.getOrCreateUser(email, displayName);
    const agentService = new AuroraAgentService(auroraUser.id, email);

    let myAgents: any[] = [];
    try {
      myAgents = await agentService.listUserAgents();
    } catch {
      await context.sendActivity('Could not reach the content creator service right now. Please try again.');
      return;
    }

    if (myAgents.length === 0) {
      await context.sendActivity('You have no personal agents yet. Create them at aurora-octo.xcloudiq.com/profile/my-agents');
      return;
    }

    const items = myAgents.map((a) => ({
      name: a.name,
      desc: `${a.enabled ? '● active' : '○ paused'}${a.posting_cadence ? ` · ${a.posting_cadence}` : ''}`,
      value: `@${(a.teams_slug || a.name).replace(/^aurora-/, '')} `,
    }));

    const card = buildAgentListCard('My Personal Agents', items, 'Click an agent to start a conversation:');
    await context.sendActivity({ attachments: [CardFactory.adaptiveCard(card)] });
  }

  /** Follow an agent by name. */
  async handleFollowAgent(context: TurnContext, agentName: string): Promise<void> {
    if (!agentName.trim()) {
      await context.sendActivity('Please specify an agent name. Example: `follow TechWatcher`');
      return;
    }

    const email = this.userService.extractUserEmail(context.activity);
    const displayName = context.activity.from.name || 'User';
    const auroraUser = await this.userService.getOrCreateUser(email, displayName);
    const agentService = new AuroraAgentService(auroraUser.id, email);

    const agent = await agentService.findAgentByName(agentName);
    if (!agent) {
      await context.sendActivity(
        `No agent found matching "${agentName}". Type \`agents\` to see what's available.`
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
      await context.sendActivity('Please specify an agent name. Example: `unfollow TechWatcher`');
      return;
    }

    const email = this.userService.extractUserEmail(context.activity);
    const displayName = context.activity.from.name || 'User';
    const auroraUser = await this.userService.getOrCreateUser(email, displayName);
    const agentService = new AuroraAgentService(auroraUser.id, email);

    const agent = await agentService.findAgentByName(agentName);
    if (!agent) {
      await context.sendActivity(
        `No agent found matching "${agentName}". Type \`agents\` to see what's available.`
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
        `No agent found matching "${rawArgs}". Type \`agents\` to see what's available.`
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

    // 3. Try as a personal My-Agent slug (e.g. @pqc-project, @open-roaming-agent)
    try {
      const personalAgent = await agentService.getUserAgentBySlug(teamsSlug);
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
      const items = closeMatches.map((wg) => ({
        name: wg.name,
        desc: wg.description || '',
        value: `@${wg.slug.replace(/^aurora-/, '')} `,
      }));
      const card = buildAgentListCard(
        `No agent found for "@${teamsSlug}"`,
        items,
        question
          ? `Did you mean one of these? They can answer: "${question}"`
          : 'Did you mean one of these?',
      );
      await context.sendActivity({ attachments: [CardFactory.adaptiveCard(card)] });
    } else {
      const card = buildAgentListCard(
        `No agent found for "@${teamsSlug}"`,
        [{ name: 'Ask Aurora directly', desc: 'Search across all knowledge sources', value: question || `${teamsSlug} ` }],
        'Type `agents` to browse all available agents, or ask Aurora directly:',
      );
      await context.sendActivity({ attachments: [CardFactory.adaptiveCard(card)] });
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
    await context.sendActivity(text);
  }
}

/**
 * Build an Adaptive Card that lists agents/working groups as clickable buttons.
 * Each agent has an Action.Submit (imBack) so clicking sends "@slug " to start
 * a dialog. A "Clear" button at the bottom returns to general mode.
 *
 * Uses only card-level actions (no ActionSet inside body) for Teams compatibility.
 */
function buildAgentListCard(
  title: string,
  items: Array<{ name: string; desc?: string; value: string }>,
  subtitle?: string
): Record<string, unknown> {
  // Body: name + description rows only (no nested action sets)
  const bodyRows: Record<string, unknown>[] = [];
  items.forEach((item, i) => {
    if (i > 0) {
      // Use separator: true on the TextBlock instead of a Separator element
      bodyRows.push({
        type: 'TextBlock',
        text: item.name,
        weight: 'Bolder',
        wrap: true,
        separator: true,
        spacing: 'Small',
      });
    } else {
      bodyRows.push({ type: 'TextBlock', text: item.name, weight: 'Bolder', wrap: true });
    }
    if (item.desc) {
      bodyRows.push({
        type: 'TextBlock',
        text: item.desc,
        isSubtle: true,
        size: 'Small',
        wrap: true,
        spacing: 'None',
      });
    }
  });

  // Card-level actions: one per agent + clear
  const actions: Record<string, unknown>[] = [
    ...items.map((item) => ({
      type: 'Action.Submit',
      title: `Ask ${item.name}`,
      data: { msteams: { type: 'imBack', value: item.value } },
    })),
    {
      type: 'Action.Submit',
      title: '✕ Clear',
      data: { msteams: { type: 'imBack', value: 'clear' } },
    },
  ];

  return {
    type: 'AdaptiveCard',
    $schema: 'http://adaptivecards.io/schemas/adaptive-card.json',
    version: '1.3',
    body: [
      { type: 'TextBlock', text: title, weight: 'Bolder', size: 'Large' },
      ...(subtitle ? [{ type: 'TextBlock', text: subtitle, isSubtle: true, spacing: 'Small', wrap: true }] : []),
      ...bodyRows,
    ],
    actions,
  };
}
