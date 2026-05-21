import { TurnContext } from 'botbuilder';
import { AuroraUserService } from '../services/auroraUserService';
import { AuroraOracleService } from '../services/auroraOracleService';
import { conversationReferenceStore } from '../services/conversationReferenceStore';
import axios from 'axios';

// ── Conversation memory ───────────────────────────────────────────────────────
// In-memory store of the last exchange per conversation (TTL 30 min).
// Used to enrich follow-up questions with context from the previous answer.
interface ConvMemory {
  question: string;
  answerSummary: string;
  keyEntities: string[];
  ts: number;
  documents?: Array<{ title: string; url: string; datasource_id?: string }>;  // for enhance
}
const convMemory = new Map<string, ConvMemory>();
const MEMORY_TTL_MS = 30 * 60 * 1000;

/** Replace [N] citation markers in answer text with clickable markdown links. */
function linkifyReferences(answer: string, docs: Array<{ url?: string; title?: string }>): string {
  return answer.replace(/\[(\d+)\]/g, (match, num) => {
    const idx = parseInt(num, 10) - 1;
    const doc = docs[idx];
    return doc?.url ? `[[${num}]](${doc.url})` : match;
  });
}

/** Build a plain-markdown oracle response with linked references and full source list. */
export function buildMarkdownResponse(
  answer: string,
  docs: Array<{ title?: string; url?: string }>,
  speakerPrefix?: string,
): string {
  const linkedAnswer = docs?.length ? linkifyReferences(answer, docs) : answer;
  const prefix = speakerPrefix ? `**${speakerPrefix}:** ` : '';

  let sources = '';
  if (docs?.length) {
    sources = '\n\n**Sources:**\n' + docs
      .map((doc, i) => {
        const label = doc.title || `Source ${i + 1}`;
        return doc.url ? `${i + 1}. [${label}](${doc.url})` : `${i + 1}. ${label}`;
      })
      .join('\n');
  }

  return `${prefix}${linkedAnswer}${sources}`;
}


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
  if (q.split(/\s+/).length > 12) return false;

  // All previous content lowercased for membership checks
  const prevContext = (memory.question + ' ' + memory.answerSummary +
    ' ' + memory.keyEntities.join(' ')).toLowerCase();

  // ── Step 1: detect "naming/activity" patterns that signal a NEW entity ──
  // Catches: "who is X", "what is X", "who has discussed X", "who talked about X"
  const namingMatch = q.match(/^(?:who|what)\s+(?:is|are|was|were|does|did|has|have|had|discussed?|talked?|mentioned?)\s+(.+)/i) ||
                      q.match(/^(?:tell me about|about|find|search for)\s+(.+)/i);
  if (namingMatch) {
    const pronouns = new Set(['they','them','their','he','she','it','this','that','those',
      'these','there','his','her','its','else','other','others','another','one','ones',
      'who','what','which','when','where','why','how','all','both','each','every']);
    const originalSubject = namingMatch[1].trim();
    const subjectEntityWords = originalSubject.split(/\s+/).filter(w => {
      const wl = w.toLowerCase();
      if (pronouns.has(wl) || w.length <= 2) return false;
      return /^[A-Z]/.test(w) || /^[A-Z]{2,}$/.test(w) || /\d/.test(w);
    });
    if (subjectEntityWords.length === 0) { /* fall through */ }
    else if (subjectEntityWords.some(w => !prevContext.includes(w.toLowerCase()))) return false;
  }

  // ── Step 1.5: version numbers / spec identifiers signal a topic shift ───
  // "Wi-Fi 9" after a "Wi-Fi in space" discussion is a new query, not a follow-up.
  // Any number in the question that doesn't appear in previous context = new topic.
  const questionNumbers = question.match(/\b\d+(?:\.\d+)*\b/g) || [];
  if (questionNumbers.some(n => !prevContext.includes(n))) return false;

  // ── Step 2: pronoun / demonstrative reference → follow-up ──────────────
  const pronounRef = /\b(they|them|their|he|she|it|this|that|those|these|there|his|her|its)\b/i;
  if (pronounRef.test(question)) return true;

  // ── Step 3: reuses a SPECIFIC known entity (≥6 chars) → follow-up ──────
  // Short terms like "Wi-Fi" or "IEEE" are too generic; require longer entities
  // to avoid false positives where every Wi-Fi question enriches from the last.
  const memEntitiesLower = memory.keyEntities.map(e => e.toLowerCase()).filter(e => e.length >= 6);
  return memEntitiesLower.some(e => q.includes(e));
}

/** Build a contextualised question by prepending last exchange. */
function enrichWithContext(question: string, memory: ConvMemory): string {
  return `Context from previous question ("${memory.question}"): ${memory.answerSummary}\n\nFollow-up question: ${question}`;
}

/** Store answer in per-conversation memory. Exported so agent handlers can also save context. */
export function rememberAnswer(convId: string, question: string, answer: string, docs?: Array<{ title: string; url: string; datasource_id?: string }>): void {
  remember(convId, question, answer, docs);
}

/** Store answer in per-conversation memory. */
function remember(convId: string, question: string, answer: string, docs?: Array<{ title: string; url: string; datasource_id?: string }>): void {
  convMemory.set(convId, {
    question,
    answerSummary: answer.slice(0, 300),
    keyEntities: extractEntities(answer),
    ts: Date.now(),
    documents: docs,
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
          this.oracleService.query(auroraUser.id, cleanQuestion, undefined, datasourceIds, auroraUser.email),
          30000,
          'oracle query'
        );
      } catch (timeoutErr) {
        console.warn('[ChatHandler] Oracle timeout:', timeoutErr);
        await context.sendActivity(
          `That query is taking longer than expected. Try rephrasing or adding more detail — for example, include the specific standard or working group name.`
        );
        return;
      }

      // Store the exchange in conversation memory (including documents for enhance)
      if (response?.answer) {
        remember(convId, question, response.answer, response.documents);
      }

      // Send as plain markdown with inline linked citations — no Adaptive Card for Q&A
      const text = buildMarkdownResponse(
        response.answer || 'Here are the relevant results:',
        response.documents ?? [],
      );
      await context.sendActivity(text);

      if (response.suggestions?.length) {
        const hint = `\n\n**Related:**\n${response.suggestions.slice(0, 2)
          .map((s: any) => `• "${s.suggestion}"`).join('\n')}`;
        await context.sendActivity(hint);
      }

    } catch (error) {
      console.error('[ChatHandler] handleQuestion error:', error);
      if (axios.isAxiosError(error)) {
        if (error.response?.status === 401 || error.response?.status === 403) {
          await context.sendActivity('Authentication error: the bot cannot access Aurora services. Please check the service configuration.');
          return;
        }
        if (error.response?.status === 503) {
          await context.sendActivity('Aurora is temporarily unavailable. Please try again in a moment.');
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
          this.oracleService.query(auroraUser.id, resolvedQuestion, undefined, undefined, auroraUser.email),
          25000,
          'oracle group query'
        );
      } catch (err: any) {
        // Silent in group context — don't disrupt the conversation, but log for debugging
        console.warn('[handleGroupContextQuestion] Oracle query failed:', err?.message || err);
        return;
      }

      if (!response?.answer || response.answer.length < 20) return;

      if (response.answer) remember(convId, question, response.answer, response.documents);

      const sentences = response.answer.replace(/\[\d+\]/g, '').match(/[^.!?]+[.!?]+/g) ?? [];
      const brief = sentences.slice(0, 3).join(' ').trim() || response.answer.slice(0, 400);
      const topSource = response.documents?.[0];
      const sourceNote = topSource?.url
        ? `\n\n[${topSource.title || 'Source'}](${topSource.url})`
        : '';

      await context.sendActivity(
        `**Aurora context:**\n\n${brief}${sourceNote}\n\n_Ask me directly for more detail._`
      );
    } catch {
      // Silent failure — never disrupt the group conversation
    }
  }

  /**
   * Handle "enhance" command — re-run last question through the enhance endpoint
   * which fetches and reads the source documents for a richer, cited answer.
   */
  async handleEnhance(context: TurnContext): Promise<void> {
    const convId = context.activity.conversation?.id ?? 'default';
    const mem = recall(convId);

    if (!mem) {
      await context.sendActivity('No recent answer to enhance — conversation history is reset when the bot restarts. Ask a question first, then type `enhance` in the same session.');
      return;
    }

    if (!mem.documents?.length) {
      // Memory exists but no source documents — re-query first to get documents
      await context.sendActivity(`Re-running *${mem.question}* to retrieve source documents…`);
      try {
        const email = this.userService.extractUserEmail(context.activity);
        const auroraUser = await this.userService.getOrCreateUser(email, context.activity.from.name || 'User');
        const response = await withTimeout(
          this.oracleService.query(auroraUser.id, mem.question, undefined, undefined, auroraUser.email),
          30000, 'pre-enhance query'
        );
        if (response?.documents?.length) {
          remember(convId, mem.question, response.answer || mem.answerSummary, response.documents);
        } else {
          await context.sendActivity('No source documents found for that question. The enhance feature works best with factual queries that return cited sources.');
          return;
        }
      } catch {
        await context.sendActivity('Could not retrieve source documents right now. Please try again.');
        return;
      }
    }

    const freshMem = recall(convId)!;
    await context.sendActivity(`Fetching source documents for a deeper answer on: *${freshMem.question}*`);

    try {
      const email = this.userService.extractUserEmail(context.activity);
      const displayName = context.activity.from.name || 'User';
      const auroraUser = await this.userService.getOrCreateUser(email, displayName);
      const currentMem = recall(convId)!;

      const enhanced = await withTimeout(
        this.oracleService.enhance(auroraUser.id, currentMem.question, currentMem.documents!, auroraUser.email),
        45000,
        'enhance query'
      );

      if (!enhanced) {
        await context.sendActivity('Could not produce an enhanced answer. Please try again.');
        return;
      }

      const sourceLinks = currentMem.documents!.slice(0, 5)
        .map((d, i) => `${i + 1}. [${d.title}](${d.url})`)
        .join('\n');

      await context.sendActivity(`**Enhanced answer:**\n\n${enhanced}\n\n**Sources:**\n${sourceLinks}`);
    } catch (err: any) {
      const isTimeout = err?.message?.includes('timeout');
      await context.sendActivity(isTimeout
        ? 'That is taking too long. Try a shorter question first.'
        : 'Could not fetch the source documents right now. Please try again.'
      );
    }
  }
}
