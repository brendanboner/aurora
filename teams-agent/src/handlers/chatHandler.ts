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
  
}
