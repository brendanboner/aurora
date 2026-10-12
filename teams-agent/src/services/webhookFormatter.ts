/**
 * Formats a proactive feed update as a Teams Incoming Webhook payload.
 *
 * Teams webhooks accept Adaptive Cards via the "Workflow" format
 * (application/vnd.microsoft.card.adaptive inside an attachment wrapper).
 * This is the modern replacement for the legacy MessageCard format.
 *
 * Spec: https://learn.microsoft.com/en-us/microsoftteams/platform/webhooks-and-connectors/how-to/connectors-using
 */

import { FeedUpdatePayload } from './proactiveMessenger';
import axios from 'axios';

export interface WebhookDispatchResult {
  ok: boolean;
  status?: number;
  error?: string;
}

/**
 * POST a feed update card to a Teams Incoming Webhook URL.
 * The webhook posts as a named sender (agentName) with whatever icon was
 * configured when the webhook was created — zero IT overhead after that.
 */
export async function postToWebhook(
  webhookUrl: string,
  payload: FeedUpdatePayload
): Promise<WebhookDispatchResult> {
  const tagsStr = payload.tags?.length ? payload.tags.slice(0, 5).join(', ') : 'General';
  const publishedStr = payload.published_at
    ? new Date(payload.published_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
    : new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });

  const adaptiveCard = {
    type: 'AdaptiveCard',
    $schema: 'http://adaptivecards.io/schemas/adaptive-card.json',
    version: '1.5',
    body: [
      {
        type: 'Container',
        style: 'emphasis',
        bleed: true,
        items: [
          {
            type: 'ColumnSet',
            columns: [
              {
                type: 'Column',
                width: 'auto',
                items: [{ type: 'TextBlock', text: 'A', size: 'Large', weight: 'Bolder' }],
              },
              {
                type: 'Column',
                width: 'stretch',
                items: [
                  { type: 'TextBlock', text: payload.agent_name, weight: 'Bolder', size: 'Medium', wrap: true },
                  { type: 'TextBlock', text: 'New update in your interest area', size: 'Small', isSubtle: true, spacing: 'None' },
                ],
              },
            ],
          },
        ],
      },
      {
        type: 'Container',
        items: [
          { type: 'TextBlock', text: payload.title, weight: 'Bolder', size: 'Medium', wrap: true },
          { type: 'TextBlock', text: payload.summary || payload.title, wrap: true, spacing: 'Small', maxLines: 4 },
          {
            type: 'FactSet',
            facts: [
              { title: 'Tags', value: tagsStr },
              { title: 'Published', value: publishedStr },
            ],
            spacing: 'Small',
          },
        ],
      },
    ],
    actions: [
      ...(payload.source_url
        ? [{ type: 'Action.OpenUrl', title: 'View source', url: payload.source_url }]
        : []),
    ],
    // Note: imBack actions are not supported in webhook-posted cards (no bot session).
    // The "Ask about this" CTA is omitted here; users can @mention the bot directly.
    msteams: {
      width: 'Full',
    },
  };

  const body = {
    type: 'message',
    attachments: [
      {
        contentType: 'application/vnd.microsoft.card.adaptive',
        contentUrl: null,
        content: adaptiveCard,
      },
    ],
  };

  try {
    const res = await axios.post(webhookUrl, body, {
      headers: { 'Content-Type': 'application/json' },
      timeout: 8000,
    });
    return { ok: res.status >= 200 && res.status < 300, status: res.status };
  } catch (err: any) {
    return { ok: false, error: err?.message ?? String(err) };
  }
}
