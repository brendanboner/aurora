import { CardFactory, Attachment } from 'botbuilder';
import * as ACData from 'adaptivecards-templating';
import { OracleResponse } from '../services/auroraOracleService';
import oracleResponseCardTemplate from '../adaptiveCards/oracleResponseCard.json';

/**
 * Builds the shared Adaptive Card for any Oracle response (used by both
 * ChatHandler and AgentHandler so both get clickable RichTextBlock links).
 */
export function buildOracleResponseCard(response: OracleResponse, question: string): Attachment {
  const template = new ACData.Template(oracleResponseCardTemplate);

  const citations = response.documents.slice(0, 5).map((doc, index) => ({
    title: `[${index + 1}] ${doc.datasource_name || 'Source'}`,
    value: doc.title,
  }));

  const topics = response.graph_context?.central_topics?.slice(0, 5).join(', ') || '';

  const cardData = {
    question,
    answer:
      response.answer ||
      "I found some relevant documents but couldn't generate a specific answer. Please review the sources below.",
    citations,
    confidence_score: response.confidence_score ? Math.round(response.confidence_score * 100) : null,
    topics,
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
    })),
  };

  const cardPayload = template.expand({ $root: cardData });
  return CardFactory.adaptiveCard(cardPayload);
}
