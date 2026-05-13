import { BotFrameworkAdapter, CardFactory, ConversationReference, MessageFactory } from 'botbuilder';
import * as ACData from 'adaptivecards-templating';
import { conversationReferenceStore } from './conversationReferenceStore';
import { postToWebhook } from './webhookFormatter';
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
 * Sends a proactive feed update to all conversations subscribed to the given agent slug.
 *
 * Dispatch priority per conversation:
 *   1. Teams Incoming Webhook (if set) — posts with agent's custom name + icon, zero IT
 *   2. Bot push via continueConversation() — falls back when no webhook configured
 */
export class ProactiveMessenger {
  constructor(private adapter: BotFrameworkAdapter) {}

  async pushFeedUpdate(payload: FeedUpdatePayload): Promise<{ sent: number; errors: number; webhook: number; bot: number }> {
    // Gather subscribed conversations and conversations with webhooks in parallel
    const [subscribedRefs, webhookConvs] = await Promise.all([
      conversationReferenceStore.getSubscribed(payload.agent_slug),
      conversationReferenceStore.getWebhooksForAgent(payload.agent_slug),
    ]);

    // Build a map of conversationId → webhookUrl for O(1) lookup
    const webhookMap = new Map(webhookConvs.map((w) => [w.conversation_id, w.webhook_url]));

    if (subscribedRefs.length === 0 && webhookConvs.length === 0) {
      console.log(`[ProactiveMessenger] No subscribers or webhooks for agent slug "${payload.agent_slug}"`);
      return { sent: 0, errors: 0, webhook: 0, bot: 0 };
    }

    // Union: all conversations that should receive the update
    // (subscribed via bot OR has a webhook configured — webhook implies interest)
    const allConvIds = new Set([
      ...subscribedRefs.map((r) => r.conversation_id),
      ...webhookConvs.map((w) => w.conversation_id),
    ]);

    const refMap = new Map(subscribedRefs.map((r) => [r.conversation_id, r]));
    const botCard = this.buildBotCard(payload);
    const botActivity = MessageFactory.attachment(botCard);

    let sent = 0, errors = 0, webhookCount = 0, botCount = 0;

    for (const convId of allConvIds) {
      const webhookUrl = webhookMap.get(convId);

      if (webhookUrl) {
        // Preferred: post to Teams Incoming Webhook (custom agent name/icon)
        const result = await postToWebhook(webhookUrl, payload);
        if (result.ok) {
          webhookCount++;
          sent++;
        } else {
          console.warn(`[ProactiveMessenger] Webhook failed for ${convId}: ${result.error ?? result.status} — falling back to bot push`);
          // Fall through to bot push on webhook failure
          await this.botPush(refMap.get(convId), botActivity, convId)
            ? (botCount++, sent++) : errors++;
        }
      } else {
        // Bot push via continueConversation
        await this.botPush(refMap.get(convId), botActivity, convId)
          ? (botCount++, sent++) : errors++;
      }
    }

    console.log(
      `[ProactiveMessenger] "${payload.title}" → ${sent} sent (${webhookCount} webhook, ${botCount} bot, ${errors} errors)`
    );
    return { sent, errors, webhook: webhookCount, bot: botCount };
  }

  private async botPush(
    row: { service_url: string; conversation_id: string; bot_id: string | null; channel_id?: string | null } | undefined,
    activity: ReturnType<typeof MessageFactory.attachment>,
    convId: string
  ): Promise<boolean> {
    if (!row) {
      console.warn(`[ProactiveMessenger] No bot ref for conversation ${convId} — skipping bot push`);
      return false;
    }
    const ref: Partial<ConversationReference> = {
      serviceUrl: row.service_url,
      channelId:  row.channel_id ?? 'msteams',
      conversation: { id: row.conversation_id, isGroup: false, tenantId: undefined } as any,
      bot: row.bot_id ? { id: row.bot_id, name: 'Aurora' } : undefined,
    };
    try {
      // Wrap with a 10-second timeout — stale serviceUrls (e.g. closed emulator sessions)
      // hang indefinitely without this, blocking all subsequent push deliveries.
      const TIMEOUT_MS = 10_000;
      await Promise.race([
        this.adapter.continueConversation(ref as ConversationReference, async (ctx) => {
          await ctx.sendActivity(activity);
        }),
        new Promise<never>((_, reject) =>
          setTimeout(() => reject(new Error(`timeout after ${TIMEOUT_MS}ms`)), TIMEOUT_MS)
        ),
      ]);
      console.log(`[ProactiveMessenger] Bot push delivered to ${convId}`);
      return true;
    } catch (err) {
      console.error(`[ProactiveMessenger] Bot push failed for ${convId}:`, (err as Error).message);
      return false;
    }
  }

  private buildBotCard(payload: FeedUpdatePayload) {
    const template = new ACData.Template(proactiveFeedCardTemplate);
    const tagsStr = payload.tags.length > 0 ? payload.tags.slice(0, 5).join(', ') : 'General';
    const data = {
      agent_name:   payload.agent_name,
      agent_slug:   payload.agent_slug,
      title:        payload.title,
      summary:      payload.summary || payload.title,
      tags:         tagsStr,
      published_at: payload.published_at
        ? new Date(payload.published_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
        : new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }),
      has_meta:     true,
      source_url:   payload.source_url || '',
      has_url:      !!payload.source_url,
    };
    const cardPayload = template.expand({ $root: data });
    return CardFactory.adaptiveCard(cardPayload);
  }
}

