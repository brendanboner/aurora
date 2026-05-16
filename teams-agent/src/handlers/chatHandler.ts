import { TurnContext } from 'botbuilder';
import { AuroraUserService } from '../services/auroraUserService';
import { AuroraOracleService } from '../services/auroraOracleService';
import { buildOracleResponseCard } from '../helpers/cardBuilder';
import { conversationReferenceStore } from '../services/conversationReferenceStore';
import axios from 'axios';

export class ChatHandler {
  private userService: AuroraUserService;
  private oracleService: AuroraOracleService;
  
  constructor() {
    this.userService = new AuroraUserService();
    this.oracleService = new AuroraOracleService();
  }
  
  /**
   * Handle user question
   */
  async handleQuestion(context: TurnContext, question: string): Promise<void> {
    try {
      // Get user info
      const email = this.userService.extractUserEmail(context.activity);
      const displayName = context.activity.from.name || 'User';

      // Get or create Aurora user, then link this conversation so personal agent
      // notifications can find the user's Teams channel via aurora_user_id.
      const auroraUser = await this.userService.getOrCreateUser(email, displayName);
      const convId = context.activity.conversation?.id;
      if (convId && auroraUser?.id) {
        conversationReferenceStore.linkAuroraUser(convId, auroraUser.id).catch(() => {});
      }

      // Parse @source mentions (e.g. "@wba what happened this week" or "@iot last meeting")
      // Agent mentions (@AgentName) are handled by agentHandler — here we handle datasource mentions.
      const mentionPattern = /@(\w+)/g;
      const mentions = [...question.matchAll(mentionPattern)].map(m => m[1]);
      let cleanQuestion = question;
      let datasourceIds: string[] = [];
      if (mentions.length > 0) {
        datasourceIds = await this.oracleService.resolveMentionsToDatasourceIds(mentions);
        if (datasourceIds.length > 0) {
          cleanQuestion = question.replace(mentionPattern, '').trim();
          console.log(`[Teams] @mentions ${mentions.join(',')} → datasource_ids: ${datasourceIds.join(',')}`);
        }
      }

      // Query Oracle (oracle also handles any remaining @mentions in cleanQuestion)
      const response = await this.oracleService.query(auroraUser.id, cleanQuestion, undefined, datasourceIds);
      
      // Send as Adaptive Card only. Setting `text` alongside `attachments` causes
      // the Agents Playground (and some Teams clients) to render both separately,
      // resulting in a duplicate response. The card already contains the full answer
      // and sources; the fallback `speak` field covers plain-text clients.
      const card = buildOracleResponseCard(response, question);

      let sourceLinks = '';
      if (response.documents && response.documents.length > 0) {
        sourceLinks = '\n\n📚 **Sources:**\n' + response.documents.map((doc, idx) =>
          `${idx + 1}. [${doc.title}](${doc.url})`
        ).join('\n');
      }
      const plainText = `${response.answer || 'Here are the results from Aurora Oracle:'}${sourceLinks}`;

      await context.sendActivity({
        attachments: [card],
        speak: plainText,   // screen-reader / plain-text fallback, not rendered as a second bubble
      });
      
      // If there are suggestions, mention them
      if (response.suggestions && response.suggestions.length > 0) {
        const suggestionText = `\n\n💡 **Related questions you might ask:**\n${response.suggestions.slice(0, 2).map(s => `• "${s.suggestion}"`).join('\n')}`;
        await context.sendActivity(suggestionText);
      }
      
    } catch (error) {
      console.error('Error handling question:', error);
      if (axios.isAxiosError(error)) {
        console.error('API Error:', error.response?.data);
        if (error.response?.status === 401 || error.response?.status === 403) {
          await context.sendActivity('⚠️ Authentication error: The bot cannot access Aurora services. Please configure AURORA_SERVICE_TOKEN or check backend authentication settings.');
          return;
        }
        if (error.response?.status === 503) {
          await context.sendActivity('The Oracle service is currently unavailable. Please try again in a moment.');
          return;
        }
      }
      await context.sendActivity(`Sorry, I encountered an error: ${error instanceof Error ? error.message : 'Unknown error'}. Please check the logs for details.`);
    }
  }

  /**
   * Context-aware group chat assistance.
   * Called when someone in a group/channel asks a Wi-Fi/standards question
   * without explicitly @mentioning the bot. Aurora offers brief, relevant context
   * framed as a helpful addition to the conversation — not a takeover.
   */
  async handleGroupContextQuestion(context: TurnContext, question: string): Promise<void> {
    try {
      const email = this.userService.extractUserEmail(context.activity);
      const displayName = context.activity.from.name || 'User';
      const auroraUser = await this.userService.getOrCreateUser(email, displayName);
      const convId = context.activity.conversation?.id;
      if (convId && auroraUser?.id) {
        conversationReferenceStore.linkAuroraUser(convId, auroraUser.id).catch(() => {});
      }

      const response = await this.oracleService.query(
        auroraUser.id,
        question,
        undefined,
        undefined,
      );

      if (!response?.answer || response.answer.length < 20) return; // don't respond if nothing useful

      // Trim to a concise group-friendly summary (max 3 sentences / 400 chars)
      let briefAnswer = response.answer.replace(/\[\d+\]/g, '').trim();
      const sentences = briefAnswer.match(/[^.!?]+[.!?]+/g) ?? [];
      briefAnswer = sentences.slice(0, 3).join(' ').trim() || briefAnswer.slice(0, 400);

      const topSource = response.documents?.[0];
      const sourceNote = topSource?.url
        ? `\n\n📎 Source: [${topSource.title || 'Reference'}](${topSource.url})`
        : '';

      await context.sendActivity(
        `💡 **Aurora can add context here:**\n\n${briefAnswer}${sourceNote}\n\n` +
        `_Ask me a follow-up or type \`help\` for more options._`
      );
    } catch (error) {
      // Silent failure in group context — don't disrupt the conversation
      console.warn('[ChatHandler] Group context question failed silently:', error instanceof Error ? error.message : error);
    }
  }

}
