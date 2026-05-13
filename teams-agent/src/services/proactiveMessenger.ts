import { BotFrameworkAdapter, CardFactory, ConversationReference, MessageFactory } from 'botbuilder';
import * as ACData from 'adaptivecards-templating';
import { conversationReferenceStore } from './conversationReferenceStore';
import proactiveFeedCardTemplate from '../adaptiveCards/proactiveFeedCard.json';

export interface FeedUpdatePayload {
  agent_slug: string;
  agent_name: string;
  post_id: number;
  title: string;
  summary: string;
  tags: string[];
  source_url?: string;
  published_at?: string;
}

/**
 * Sends a proactive feed update card to all conversations subscribed to the given agent slug.
 * Called from the /internal/push-feed-update endpoint.
 */
export class ProactiveMessenger {
  constructor(private adapter: BotFrameworkAdapter) {}

  async pushFeedUpdate(payload: FeedUpdatePayload): Promise<{ sent: number; errors: number }> {
    const refs = await conversationReferenceStore.getSubscribed(payload.agent_slug);

    if (refs.length === 0) {
      console.log(`[ProactiveMessenger] No subscribed conversations for agent slug "${payload.agent_slug}"`);
      return { sent: 0, errors: 0 };
    }

    const card = this.buildCard(payload);
    const activity = MessageFactory.attachment(card);
    let sent = 0;
    let errors = 0;

    for (const row of refs) {
      const ref: Partial<ConversationReference> = {
        serviceUrl: row.service_url,
        conversation: { id: row.conversation_id, isGroup: row.conversation_type !== 'personal' } as any,
        bot: row.bot_id ? { id: row.bot_id, name: 'Aurora' } : undefined,
      };

      try {
        await this.adapter.continueConversation(ref as ConversationReference, async (ctx) => {
          await ctx.sendActivity(activity);
        });
        sent++;
      } catch (err) {
        console.error(
          `[ProactiveMessenger] Failed to push to conversation ${row.conversation_id}:`,
          (err as Error).message
        );
        errors++;
      }
    }

    console.log(`[ProactiveMessenger] Pushed "${payload.title}" to ${sent} conversations (${errors} errors)`);
    return { sent, errors };
  }

  private buildCard(payload: FeedUpdatePayload) {
    const template = new ACData.Template(proactiveFeedCardTemplate);
    const tagsStr = payload.tags.length > 0 ? payload.tags.slice(0, 5).join(', ') : 'General';

    const data = {
      agent_name:    payload.agent_name,
      agent_slug:    payload.agent_slug,
      title:         payload.title,
      summary:       payload.summary || payload.title,
      tags:          tagsStr,
      published_at:  payload.published_at
        ? new Date(payload.published_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
        : new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }),
      has_meta:      true,
      source_url:    payload.source_url || '',
      has_url:       !!payload.source_url,
    };

    const cardPayload = template.expand({ $root: data });
    return CardFactory.adaptiveCard(cardPayload);
  }
}
