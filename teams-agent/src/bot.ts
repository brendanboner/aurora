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
      console.log(`[${new Date().toISOString()}] Received message from ${context.activity.from.name}: ${context.activity.text}`);
      
      const text = context.activity.text?.trim() || '';
      const lower = text.toLowerCase();

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
              text: '• `agents` - List all available AI content agents\n• `follow <agent name>` - Follow an agent (their posts appear in your feed)\n• `unfollow <agent name>` - Unfollow an agent\n• `ask <agent name> <question>` - Ask a question from that agent\'s perspective',
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
