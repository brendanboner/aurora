import { TurnContext } from 'botbuilder';
import { AuroraUserService } from '../services/auroraUserService';
import { AuroraAgentService } from '../services/auroraAgentService';
import { AuroraOracleService } from '../services/auroraOracleService';
import { buildOracleResponseCard } from '../helpers/cardBuilder';
import { getWorkingGroupBySlug, listWorkingGroupSlugs } from '../services/workingGroupResolver';

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
   * Show a quick-select list of agents when the user types @ alone
   * or an unrecognised @ prefix. Uses suggestedActions so agent names
   * appear as tap-to-fill chips above the compose box.
   */
  async handleAgentSuggestions(context: TurnContext, partial: string = ''): Promise<void> {
    const email = this.userService.extractUserEmail(context.activity);
    const displayName = context.activity.from.name || 'User';
    const auroraUser = await this.userService.getOrCreateUser(email, displayName);
    const agentService = new AuroraAgentService(auroraUser.id, email);
    const agents = await agentService.listAgents();

    // Filter by partial match if the user typed @something
    const filtered = partial
      ? agents.filter((a) => a.name.toLowerCase().startsWith(partial.toLowerCase()))
      : agents;

    if (filtered.length === 0) {
      await context.sendActivity(
        `No agents match "@${partial}". Type \`agents\` to see the full list.`
      );
      return;
    }

    // suggestedActions render as chip buttons in Teams; value pre-fills "ask <name> "
    const actions = filtered.slice(0, 8).map((a) => ({
      type: 'imBack',
      title: `@${a.name}`,
      value: `ask ${a.name} `,
    }));

    const descriptions = filtered
      .slice(0, 8)
      .map((a) => `• **${a.name}** — ${a.description || a.persona || 'Content agent'}`)
      .join('\n');

    await context.sendActivity({
      text: `**Ask a creator agent** — select one below, then type your question:\n\n${descriptions}`,
      suggestedActions: {
        to: [context.activity.from.id],
        actions,
      },
    });
  }

  /** List all content creator agents. */
  async handleListAgents(context: TurnContext): Promise<void> {
    const email = this.userService.extractUserEmail(context.activity);
    const displayName = context.activity.from.name || 'User';
    const auroraUser = await this.userService.getOrCreateUser(email, displayName);

    const agentService = new AuroraAgentService(auroraUser.id, email);
    const agents = await agentService.listAgents();

    const agentLines = agents.length > 0
      ? agents.map((a) => {
          const desc = (a.description || a.persona || '').slice(0, 80);
          const slug = a.teams_slug ? ` — \`@${a.teams_slug}\`` : '';
          return `• **${a.name}**${slug}\n  ${desc}`;
        }).join('\n\n')
      : '_(none configured)_';

    const msg = [
      `**Aurora Agents**\n`,
      `**Creator Agents** (personalised personas)`,
      agentLines,
      ``,
      `**Working Groups & Organisations** (knowledge graph)`,
      listWorkingGroupSlugs(),
      ``,
      `Use: \`@aurora-slug your question\``,
      `Subscribe to updates: \`subscribe @aurora-slug\``,
    ].join('\n');

    await context.sendActivity(msg);
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

    const response = await this.oracleService.query(auroraUser.id, question, agentPersona);

    if (!response.answer && (!response.documents || response.documents.length === 0)) {
      await context.sendActivity(`**${matchedAgent.name}** could not find a relevant answer to that question.`);
      return;
    }

    const card = buildOracleResponseCard(response, question);

    let sourceLinks = '';
    if (response.documents && response.documents.length > 0) {
      sourceLinks = '\n\n**Sources:**\n' + response.documents.slice(0, 5).map((doc, idx) =>
        `${idx + 1}. [${doc.title}](${doc.url})`
      ).join('\n');
    }
    const summary = `**${matchedAgent.name}:** ${response.answer || 'Here are the results:'}${sourceLinks}`;

    await context.sendActivity({ text: summary, attachments: [card] });
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
      const response = await this.oracleService.query(auroraUser.id, question, agentPersona);
      await this.sendOracleResponse(context, agent.name, response, question);
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
      const response = await this.oracleService.query(auroraUser.id, question, wgPersona);
      await this.sendOracleResponse(context, wg.name, response, question);
      return;
    }

    // 3. Nothing matched
    await context.sendActivity(
      `No agent or working group found for \`@${teamsSlug}\`. Type \`agents\` to see available slugs.`
    );
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

    const sourceLinks = response.documents?.length
      ? '\n\n**Sources:**\n' + response.documents.slice(0, 5).map((doc: any, idx: number) =>
          `${idx + 1}. [${doc.title}](${doc.url})`
        ).join('\n')
      : '';

    const answer = response.answer || 'Here are the relevant results:';
    await context.sendActivity(`**${speakerName}:** ${answer}${sourceLinks}`);
  }
}
