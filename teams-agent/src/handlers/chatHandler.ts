import { TurnContext } from 'botbuilder';
import { AuroraUserService } from '../services/auroraUserService';
import { AuroraOracleService } from '../services/auroraOracleService';
import { buildOracleResponseCard } from '../helpers/cardBuilder';
import { conversationReferenceStore } from '../services/conversationReferenceStore';
import axios from 'axios';

// ── Conversation memory ───────────────────────────────────────────────────────
// In-memory store of the last exchange per conversation (TTL 30 min).
// Used to enrich follow-up questions with context from the previous answer.
interface ConvMemory {
  question: string;          // last question asked
  answerSummary: string;     // first 300 chars of last answer
  keyEntities: string[];     // proper nouns extracted from the answer
  ts: number;
}
const convMemory = new Map<string, ConvMemory>();
const MEMORY_TTL_MS = 30 * 60 * 1000;

/** Extract capitalised words / proper nouns from a text block. */
function extractEntities(text: string): string[] {
  const words = text.match(/\b[A-Z][a-zA-Z]{2,}\b/g) ?? [];
  const stopWords = new Set(['The','This','That','These','Those','When','Where',
    'What','Who','How','Why','Which','For','With','From','And','But','Also',
    'They','Their','Them','Has','Have','Had','Was','Were','Will','Would',
    'Should','Could','Been','Being','Into','Over','Under','About']);
  return [...new Set(words.filter(w => !stopWords.has(w)))].slice(0, 15);
}

/** True when a question looks like a follow-up referencing prior context. */
function isFollowUp(question: string, memory: ConvMemory): boolean {
  const q = question.toLowerCase();
  // Short question heuristic
  const wordCount = q.split(/\s+/).length;
  if (wordCount > 12) return false;
  // Pronoun / demonstrative reference
  const followUpTriggers = /\b(who|which|what|when|where|they|them|their|he|she|it|this|that|those|these|there|his|her|its)\b/i;
  if (followUpTriggers.test(question)) return true;
  // Mentions an entity from the previous answer
  const lowerEntities = memory.keyEntities.map(e => e.toLowerCase());
  return lowerEntities.some(e => q.includes(e));
}

/** Build a contextualised question by prepending last exchange. */
function enrichWithContext(question: string, memory: ConvMemory): string {
  return `Context from previous question ("${memory.question}"): ${memory.answerSummary}\n\nFollow-up question: ${question}`;
}

/** Store answer in per-conversation memory. */
function remember(convId: string, question: string, answer: string): void {
  convMemory.set(convId, {
    question,
    answerSummary: answer.slice(0, 300),
    keyEntities: extractEntities(answer),
    ts: Date.now(),
  });
}

/** Retrieve non-expired memory for a conversation. */
function recall(convId: string): ConvMemory | null {
  const m = convMemory.get(convId);
  if (!m) return null;
  if (Date.now() - m.ts > MEMORY_TTL_MS) { convMemory.delete(convId); return null; }
  return m;
}

// ── Timeout helper ────────────────────────────────────────────────────────────
function withTimeout<T>(promise: Promise<T>, ms: number, label: string): Promise<T> {
  return Promise.race([
    promise,
    new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error(`Timeout after ${ms}ms: ${label}`)), ms)
    ),
  ]);
}

export class ChatHandler {
  private userService: AuroraUserService;
  private oracleService: AuroraOracleService;

  constructor() {
    this.userService = new AuroraUserService();
    this.oracleService = new AuroraOracleService();
  }

  /**
   * Handle user question — personal chat full response with Adaptive Card.
   */
  async handleQuestion(context: TurnContext, question: string): Promise<void> {
    const convId = context.activity.conversation?.id ?? 'default';
    let resolvedQuestion = question;

    // Enrich with conversation context if this looks like a follow-up
    const mem = recall(convId);
    if (mem && isFollowUp(question, mem)) {
      resolvedQuestion = enrichWithContext(question, mem);
      console.log(`[ChatHandler] Follow-up detected — enriched question with context from "${mem.question}"`);
    }

    try {
      const email = this.userService.extractUserEmail(context.activity);
      const displayName = context.activity.from.name || 'User';
      const auroraUser = await this.userService.getOrCreateUser(email, displayName);

      if (convId && auroraUser?.id) {
        conversationReferenceStore.linkAuroraUser(convId, auroraUser.id).catch(() => {});
      }

      // Parse @source mentions
      const mentionPattern = /@(\w+)/g;
      const mentions = [...resolvedQuestion.matchAll(mentionPattern)].map(m => m[1]);
      let cleanQuestion = resolvedQuestion;
      let datasourceIds: string[] = [];
      if (mentions.length > 0) {
        datasourceIds = await this.oracleService.resolveMentionsToDatasourceIds(mentions);
        if (datasourceIds.length > 0) {
          cleanQuestion = resolvedQuestion.replace(mentionPattern, '').trim();
        }
      }

      // Query with 30s timeout — always produce a response
      let response;
      try {
        response = await withTimeout(
          this.oracleService.query(auroraUser.id, cleanQuestion, undefined, datasourceIds),
          30000,
          'oracle query'
        );
      } catch (timeoutErr) {
        console.warn('[ChatHandler] Oracle timeout:', timeoutErr);
        await context.sendActivity(
          `⏱ That query is taking longer than expected. Try rephrasing or adding more detail — for example, include the specific standard or working group name.`
        );
        return;
      }

      // Store the exchange in conversation memory
      if (response?.answer) {
        remember(convId, question, response.answer);
      }

      const card = buildOracleResponseCard(response, question);
      let sourceLinks = '';
      if (response.documents?.length) {
        sourceLinks = '\n\n📚 **Sources:**\n' + response.documents
          .map((doc: any, idx: number) => `${idx + 1}. [${doc.title}](${doc.url})`)
          .join('\n');
      }
      const plainText = `${response.answer || 'Here are the results:'}${sourceLinks}`;

      await context.sendActivity({ attachments: [card], speak: plainText });

      if (response.suggestions?.length) {
        const hint = `\n\n💡 **Related:**\n${response.suggestions.slice(0, 2)
          .map((s: any) => `• "${s.suggestion}"`).join('\n')}`;
        await context.sendActivity(hint);
      }

    } catch (error) {
      console.error('[ChatHandler] handleQuestion error:', error);
      if (axios.isAxiosError(error)) {
        if (error.response?.status === 401 || error.response?.status === 403) {
          await context.sendActivity('⚠️ Authentication error: The bot cannot access Aurora services. Please configure AURORA_SERVICE_TOKEN or check backend authentication settings.');
          return;
        }
        if (error.response?.status === 503) {
          await context.sendActivity('⚠️ The Aurora Oracle service is temporarily unavailable. Please try again in a moment.');
          return;
        }
      }
      // Always give the user SOMETHING
      await context.sendActivity(
        `I wasn't able to find an answer to that right now. ` +
        `Try adding more context — for example, mention the specific standard, working group, or time period you're interested in.`
      );
    }
  }

  /**
   * Context-aware group chat assistance — brief framing for group conversations.
   */
  async handleGroupContextQuestion(context: TurnContext, question: string): Promise<void> {
    const convId = context.activity.conversation?.id ?? 'default';
    let resolvedQuestion = question;

    const mem = recall(convId);
    if (mem && isFollowUp(question, mem)) {
      resolvedQuestion = enrichWithContext(question, mem);
    }

    try {
      const email = this.userService.extractUserEmail(context.activity);
      const displayName = context.activity.from.name || 'User';
      const auroraUser = await this.userService.getOrCreateUser(email, displayName);
      if (convId && auroraUser?.id) {
        conversationReferenceStore.linkAuroraUser(convId, auroraUser.id).catch(() => {});
      }

      let response;
      try {
        response = await withTimeout(
          this.oracleService.query(auroraUser.id, resolvedQuestion, undefined, undefined),
          25000,
          'oracle group query'
        );
      } catch {
        // Silent timeout in group context — don't disrupt the conversation
        return;
      }

      if (!response?.answer || response.answer.length < 20) return;

      if (response.answer) remember(convId, question, response.answer);

      const sentences = response.answer.replace(/\[\d+\]/g, '').match(/[^.!?]+[.!?]+/g) ?? [];
      const brief = sentences.slice(0, 3).join(' ').trim() || response.answer.slice(0, 400);
      const topSource = response.documents?.[0];
      const sourceNote = topSource?.url
        ? `\n\n📎 [${topSource.title || 'Source'}](${topSource.url})`
        : '';

      await context.sendActivity(
        `💡 **Aurora context:**\n\n${brief}${sourceNote}\n\n_Ask me directly for more detail._`
      );
    } catch {
      // Silent failure — never disrupt the group conversation
    }
  }
}
