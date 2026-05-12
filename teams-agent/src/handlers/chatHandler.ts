import { TurnContext, CardFactory, Attachment } from 'botbuilder';
import { AuroraUserService } from '../services/auroraUserService';
import { AuroraOracleService, OracleResponse } from '../services/auroraOracleService';
import * as ACData from 'adaptivecards-templating';
import oracleResponseCardTemplate from '../adaptiveCards/oracleResponseCard.json';
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
      
      // Get or create Aurora user
      const auroraUser = await this.userService.getOrCreateUser(email, displayName);
      
      // Query Oracle
      const response = await this.oracleService.query(auroraUser.id, question);
      
      // Send response as card with text summary for emulator compatibility
      const card = this.createOracleResponseCard(response, question);
      const sourceCount = response.documents?.length || 0;
      
      // Format all sources as links
      let sourceLinks = '';
      if (response.documents && response.documents.length > 0) {
        sourceLinks = '\n\n📚 **Sources:**\n' + response.documents.map((doc, idx) => 
          `${idx + 1}. [${doc.title}](${doc.url})`
        ).join('\n');
      }
      
      const summary = `${response.answer || 'Here are the results from Aurora Oracle:'}${sourceLinks}`;
      await context.sendActivity({ 
        text: summary,
        attachments: [card] 
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
   * Create Adaptive Card from Oracle response
   */
  private createOracleResponseCard(response: OracleResponse, question: string): Attachment {
    const template = new ACData.Template(oracleResponseCardTemplate);
    
    // Format citations for display
    const citations = response.documents.slice(0, 5).map((doc, index) => ({
      title: `[${index + 1}] ${doc.datasource_name || 'Source'}`,
      value: doc.title
    }));
    
    // Format topics if available
    const topics = response.graph_context?.central_topics?.slice(0, 5).join(', ') || '';
    
    const cardData = {
      question: question,
      answer: response.answer || 'I found some relevant documents but couldn\'t generate a specific answer. Please review the sources below.',
      citations: citations,
      confidence_score: response.confidence_score ? Math.round(response.confidence_score * 100) : null,
      topics: topics,
      document_count: response.documents.length,
      frontend_url: process.env.AURORA_FRONTEND_URL || 'http://localhost:3000',
      documents: response.documents.slice(0, 5).map((doc, index) => ({
        number: index + 1,
        title: doc.title || 'Source',
        url: doc.url || '',
        summary: doc.summary
          ? doc.summary.substring(0, 150) + (doc.summary.length > 150 ? '...' : '')
          : '',
        date: doc.publish_date
          ? new Date(doc.publish_date).toLocaleDateString('en-US', {
              month: 'short',
              day: 'numeric',
              year: 'numeric',
            })
          : 'Unknown date',
      }))
    };
    
    const cardPayload = template.expand({ $root: cardData });
    
    return CardFactory.adaptiveCard(cardPayload);
  }
}
