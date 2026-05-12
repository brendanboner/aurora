import { TurnContext, CardFactory } from 'botbuilder';
import * as ACData from 'adaptivecards-templating';
import { AuroraUserService } from '../services/auroraUserService';
import { AuroraAgentService } from '../services/auroraAgentService';
import { AuroraOracleService } from '../services/auroraOracleService';
import agentListCardTemplate from '../adaptiveCards/agentListCard.json';

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

  /** List all content creator agents. */
  async handleListAgents(context: TurnContext): Promise<void> {
    const email = this.userService.extractUserEmail(context.activity);
    const displayName = context.activity.from.name || 'User';
    const auroraUser = await this.userService.getOrCreateUser(email, displayName);

    const agentService = new AuroraAgentService(auroraUser.id, email);
    const agents = await agentService.listAgents();

    if (agents.length === 0) {
      await context.sendActivity('No content agents are currently available.');
      return;
    }

    const template = new ACData.Template(agentListCardTemplate);
    const cardPayload = template.expand({
      $root: {
        agents: agents.map((a) => ({
          name: a.name,
          description: a.description || a.persona || 'No description available.',
        })),
        frontend_url: process.env.AURORA_FRONTEND_URL || 'http://localhost:3000',
      },
    });

    await context.sendActivity({
      text: `📋 Found **${agents.length}** content agents. Type \`@Aurora follow <name>\` to follow one.`,
      attachments: [CardFactory.adaptiveCard(cardPayload)],
    });
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
        `❌ Could not find an agent matching "**${agentName}**". Type \`agents\` to see available agents.`
      );
      return;
    }

    await agentService.followAgent(agent.id, auroraUser.id);
    await context.sendActivity(
      `✅ You are now following **${agent.name}**! Their posts will appear in your feed. Type \`feed\` to see your latest content.`
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
        `❌ Could not find an agent matching "**${agentName}**". Type \`agents\` to see available agents.`
      );
      return;
    }

    await agentService.unfollowAgent(agent.id, auroraUser.id);
    await context.sendActivity(`✅ You have unfollowed **${agent.name}**.`);
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
        `❌ Could not find an agent matching the start of "**${rawArgs}**". Type \`agents\` to see available agents.`
      );
      return;
    }

    const question = parts.slice(questionStart).join(' ');
    if (!question.trim()) {
      await context.sendActivity(`Please include a question after the agent name. Example: \`ask ${matchedAgent.name} What is Wi-Fi 7?\``);
      return;
    }

    // Augment the question with agent persona context for Oracle
    const agentContext = matchedAgent.persona
      ? `[Context: Responding as ${matchedAgent.name} — ${matchedAgent.persona}]\n\n`
      : `[Context: From the perspective of ${matchedAgent.name}]\n\n`;

    await context.sendActivity(`💬 Asking **${matchedAgent.name}**: *${question}*...`);

    const response = await this.oracleService.query(auroraUser.id, agentContext + question);
    await context.sendActivity(response.answer || 'I could not find a relevant answer.');
  }
}
