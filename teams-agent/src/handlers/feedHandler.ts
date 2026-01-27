import { TurnContext, CardFactory, Attachment } from 'botbuilder';
import { AuroraUserService, AuroraUser } from '../services/auroraUserService';
import { AuroraFeedService, FeedPost } from '../services/auroraFeedService';
import * as ACData from 'adaptivecards-templating';
import feedPostCardTemplate from '../adaptiveCards/feedPostCard.json';

export class FeedHandler {
  private userService: AuroraUserService;
  private feedService: AuroraFeedService;
  
  constructor() {
    this.userService = new AuroraUserService();
    this.feedService = new AuroraFeedService();
  }
  
  /**
   * Send daily digest to user
   */
  async sendDailyDigest(context: TurnContext): Promise<void> {
    try {
      // Get user info from Teams context
      const email = this.userService.extractUserEmail(context.activity);
      const displayName = context.activity.from.name || 'User';
      
      // Get or create Aurora user
      const auroraUser = await this.userService.getOrCreateUser(email, displayName);
      
      // Fetch top posts
      const posts = await this.feedService.getTopPosts(auroraUser.id, 5);
      
      if (posts.length === 0) {
        await context.sendActivity('📭 No new posts in your feed today. Check back later or adjust your preferences in Aurora!');
        return;
      }
      
      // Send header message
      await context.sendActivity(`📰 **Your Aurora Feed** (${posts.length} ${posts.length === 1 ? 'post' : 'posts'})`);
      
      // Send each post as a card
      for (const post of posts) {
        const card = this.createFeedPostCard(post);
        // Add text summary for emulator compatibility - include agent name and source links
        const content = post.summary || post.body;
        const firstSource = post.sources && post.sources.length > 0 ? post.sources[0] : null;
        const sourceLink = firstSource && firstSource.url ? `\n\n📖 [Source: ${firstSource.title || 'View article'}](${firstSource.url})` : '';
        const summary = `**${post.title}**\n👤 By ${post.agent_name}\n\n${content}${sourceLink}`;
        await context.sendActivity({ 
          text: summary,
          attachments: [card] 
        });
      }
      
    } catch (error) {
      console.error('Error sending daily digest:', error);
      if (axios.isAxiosError(error)) {
        console.error('API Error:', error.response?.data);
      }
      await context.sendActivity('Sorry, I encountered an error fetching your feed. Please make sure the Aurora backend is running and try again.');
    }
  }
  
  /**
   * Handle "show feed" command
   */
  async handleShowFeedCommand(context: TurnContext, limit: number = 5): Promise<void> {
    await this.sendDailyDigest(context);
  }
  
  /**
   * Create Adaptive Card from feed post
   */
  private createFeedPostCard(post: FeedPost): Attachment {
    const template = new ACData.Template(feedPostCardTemplate);
    
    // Format data for the card
    const createdDate = new Date(post.created_at);
    const formattedDate = createdDate.toLocaleDateString('en-US', { 
      month: 'short', 
      day: 'numeric',
      year: createdDate.getFullYear() !== new Date().getFullYear() ? 'numeric' : undefined
    });
    
    const cardData = {
      title: post.title,
      agent_name: post.agent_name,
      created_at: formattedDate,
      summary: post.summary || post.body.substring(0, 200) + '...',
      normalized_score: Math.round(post.normalized_score * 100),
      tags: post.tags.slice(0, 3).join(', ') || 'No tags',
      id: post.id,
      frontend_url: process.env.AURORA_FRONTEND_URL || 'http://localhost:3000',
      importance_emoji: post.importance === 'critical' ? '🔴' : post.importance === 'high' ? '🟠' : '🟢'
    };
    
    const cardPayload = template.expand({ $root: cardData });
    
    return CardFactory.adaptiveCard(cardPayload);
  }
}

// Import axios for error checking
import axios from 'axios';
