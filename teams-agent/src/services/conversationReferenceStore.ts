import { Pool, PoolClient } from 'pg';
import { ConversationReference } from 'botbuilder';

export interface StoredConversationReference {
  id: number;
  conversation_id: string;
  service_url: string;
  tenant_id: string | null;
  bot_id: string | null;
  conversation_type: string;
  channel_id: string | null;
  aad_object_id: string | null;
  aurora_user_id: string | null;
  subscribed_agent_slugs: string[];
  default_agent_slug: string | null;
  default_agent_expires_at: Date | null;
}

let _pool: Pool | null = null;

function getPool(): Pool {
  if (!_pool) {
    _pool = new Pool({
      host:     process.env.POSTGRES_HOST     || 'postgres',
      port:     parseInt(process.env.POSTGRES_PORT || '5432', 10),
      user:     process.env.POSTGRES_USER     || 'aurora',
      password: process.env.POSTGRES_PASSWORD || 'aurora_password',
      database: process.env.POSTGRES_DB       || 'aurora',
    });
    _pool.on('error', (err) => console.error('[ConversationReferenceStore] pool error:', err));
  }
  return _pool;
}

export class ConversationReferenceStore {

  /** Upsert a conversation reference when the bot joins or a user messages. */
  async save(
    ref: Partial<ConversationReference>,
    opts: {
      aadObjectId?: string;
      auroraUserId?: string;
      conversationType?: string;
      channelId?: string;
    } = {}
  ): Promise<void> {
    const convId   = ref.conversation?.id;
    const svcUrl   = ref.serviceUrl;
    const tenantId = (ref.conversation as any)?.tenantId ?? null;
    const botId    = ref.bot?.id ?? null;

    if (!convId || !svcUrl) {
      console.warn('[ConversationReferenceStore] save() called with incomplete ref — skipping');
      return;
    }

    const convType = opts.conversationType ?? ref.conversation?.conversationType ?? 'personal';

    await getPool().query(
      `INSERT INTO teams_conversation_references
         (conversation_id, service_url, tenant_id, bot_id, conversation_type, channel_id, aad_object_id, aurora_user_id)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
       ON CONFLICT (conversation_id) DO UPDATE SET
         service_url  = EXCLUDED.service_url,
         tenant_id    = COALESCE(EXCLUDED.tenant_id, teams_conversation_references.tenant_id),
         bot_id       = COALESCE(EXCLUDED.bot_id,    teams_conversation_references.bot_id),
         aad_object_id = COALESCE(EXCLUDED.aad_object_id, teams_conversation_references.aad_object_id),
         aurora_user_id = COALESCE(EXCLUDED.aurora_user_id, teams_conversation_references.aurora_user_id),
         updated_at   = NOW()`,
      [convId, svcUrl, tenantId, botId, convType, opts.channelId ?? null, opts.aadObjectId ?? null, opts.auroraUserId ?? null]
    );
  }

  /** Remove a conversation reference when the bot is removed. */
  async delete(conversationId: string): Promise<void> {
    await getPool().query(
      'DELETE FROM teams_conversation_references WHERE conversation_id = $1',
      [conversationId]
    );
  }

  /** Retrieve all conversation references where aurora_user_id matches. */
  async getForUser(auroraUserId: string): Promise<StoredConversationReference[]> {
    const res = await getPool().query<StoredConversationReference>(
      'SELECT * FROM teams_conversation_references WHERE aurora_user_id = $1',
      [auroraUserId]
    );
    return res.rows;
  }

  /** Retrieve a single conversation reference by conversation ID. */
  async get(conversationId: string): Promise<StoredConversationReference | null> {
    const res = await getPool().query<StoredConversationReference>(
      'SELECT * FROM teams_conversation_references WHERE conversation_id = $1',
      [conversationId]
    );
    return res.rows[0] ?? null;
  }

  /**
   * Retrieve all conversations subscribed to a given agent slug.
   */
  async getSubscribed(agentSlug: string): Promise<StoredConversationReference[]> {
    const res = await getPool().query<StoredConversationReference>(
      `SELECT * FROM teams_conversation_references
       WHERE $1 = ANY(subscribed_agent_slugs)`,
      [agentSlug]
    );
    return res.rows;
  }

  /** Add an agent slug to a conversation's subscribed list. */
  async subscribe(conversationId: string, agentSlug: string): Promise<void> {
    await getPool().query(
      `UPDATE teams_conversation_references
       SET subscribed_agent_slugs = array_append(
             subscribed_agent_slugs,
             $2::TEXT
           ),
           updated_at = NOW()
       WHERE conversation_id = $1
         AND NOT ($2 = ANY(subscribed_agent_slugs))`,
      [conversationId, agentSlug]
    );
  }

  /** Remove an agent slug from a conversation's subscribed list. */
  async unsubscribe(conversationId: string, agentSlug: string): Promise<void> {
    await getPool().query(
      `UPDATE teams_conversation_references
       SET subscribed_agent_slugs = array_remove(subscribed_agent_slugs, $2::TEXT),
           updated_at = NOW()
       WHERE conversation_id = $1`,
      [conversationId, agentSlug]
    );
  }

  /**
   * Set the default agent for a conversation/channel.
   * Pass null to clear. ttlMinutes controls how long the default lasts (0 = permanent).
   */
  async setDefaultAgent(conversationId: string, agentSlug: string | null, ttlMinutes = 0): Promise<void> {
    const expires = ttlMinutes > 0
      ? new Date(Date.now() + ttlMinutes * 60 * 1000)
      : null;

    await getPool().query(
      `UPDATE teams_conversation_references
       SET default_agent_slug     = $2,
           default_agent_expires_at = $3,
           updated_at = NOW()
       WHERE conversation_id = $1`,
      [conversationId, agentSlug, expires]
    );
  }

  /**
   * Get the effective default agent slug for a conversation.
   * Returns null if none set or TTL has expired.
   */
  async getDefaultAgent(conversationId: string): Promise<string | null> {
    const res = await getPool().query<{ default_agent_slug: string | null; default_agent_expires_at: Date | null }>(
      `SELECT default_agent_slug, default_agent_expires_at
       FROM teams_conversation_references
       WHERE conversation_id = $1`,
      [conversationId]
    );
    if (!res.rows.length) return null;

    const { default_agent_slug, default_agent_expires_at } = res.rows[0];
    if (!default_agent_slug) return null;
    if (default_agent_expires_at && default_agent_expires_at < new Date()) {
      // TTL expired — clear it asynchronously
      this.setDefaultAgent(conversationId, null).catch(() => {});
      return null;
    }
    return default_agent_slug;
  }

  /** Retrieve all group/channel conversations (for broadcast announcements). */
  async getAllGroupConversations(): Promise<StoredConversationReference[]> {
    const res = await getPool().query<StoredConversationReference>(
      `SELECT * FROM teams_conversation_references
       WHERE conversation_type IN ('channel', 'groupChat', 'group')
       ORDER BY updated_at DESC`
    );
    return res.rows;
  }

  /** Retrieve ALL conversations (personal + group) — for wide announcements. */
  async getAllConversations(): Promise<StoredConversationReference[]> {
    const res = await getPool().query<StoredConversationReference>(
      'SELECT * FROM teams_conversation_references ORDER BY updated_at DESC'
    );
    return res.rows;
  }

  /** Bulk-update aurora_user_id once identity is resolved. */
  async linkAuroraUser(conversationId: string, auroraUserId: string): Promise<void> {
    await getPool().query(
      `UPDATE teams_conversation_references
       SET aurora_user_id = $2, updated_at = NOW()
       WHERE conversation_id = $1`,
      [conversationId, auroraUserId]
    );
  }

  // ── Webhook methods ──────────────────────────────────────────────────────────

  /**
   * Store a Teams Incoming Webhook URL for a specific agent slug in this conversation.
   * The webhook is used instead of bot push when posting proactive updates,
   * allowing messages to arrive with the agent's custom name and icon.
   */
  async setWebhookUrl(conversationId: string, agentSlug: string, webhookUrl: string): Promise<void> {
    await getPool().query(
      `UPDATE teams_conversation_references
       SET agent_webhook_urls = agent_webhook_urls || jsonb_build_object($2::TEXT, $3::TEXT),
           updated_at = NOW()
       WHERE conversation_id = $1`,
      [conversationId, agentSlug, webhookUrl]
    );
  }

  /** Remove a webhook URL for a specific agent slug from this conversation. */
  async removeWebhookUrl(conversationId: string, agentSlug: string): Promise<void> {
    await getPool().query(
      `UPDATE teams_conversation_references
       SET agent_webhook_urls = agent_webhook_urls - $2::TEXT,
           updated_at = NOW()
       WHERE conversation_id = $1`,
      [conversationId, agentSlug]
    );
  }

  /**
   * Get all conversations that have a webhook URL configured for the given agent slug,
   * along with the webhook URL. Used by ProactiveMessenger to prefer webhook dispatch.
   */
  async getWebhooksForAgent(agentSlug: string): Promise<Array<{ conversation_id: string; webhook_url: string }>> {
    const res = await getPool().query<{ conversation_id: string; webhook_url: string }>(
      `SELECT conversation_id,
              agent_webhook_urls->$1 AS webhook_url
       FROM teams_conversation_references
       WHERE agent_webhook_urls ? $1`,
      [agentSlug]
    );
    return res.rows;
  }
}

export const conversationReferenceStore = new ConversationReferenceStore();
