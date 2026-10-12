"""Chunking Service - Document text chunking for enhanced answer generation.

This module provides functionality to split document content into smaller chunks
suitable for LLM processing. It uses a token-based approach with overlap to preserve
context at chunk boundaries.

Phase 5 of Oracle Service implementation (Enhanced Answers).
"""

import logging
import re
from dataclasses import dataclass
from typing import Optional

import tiktoken

from src.settings import settings

logger = logging.getLogger(__name__)

# Default encoding for OpenAI models
DEFAULT_ENCODING = "cl100k_base"

# Chunk configuration
DEFAULT_CHUNK_SIZE = 500  # Target tokens per chunk
DEFAULT_CHUNK_OVERLAP = 50  # Tokens of overlap between chunks
MIN_CHUNK_SIZE = 100  # Minimum chunk size to avoid tiny fragments


@dataclass
class TextChunk:
    """A chunk of text from a document."""
    text: str
    token_count: int
    chunk_index: int
    start_char: int  # Character offset in original text
    end_char: int
    source_url: str
    source_title: Optional[str] = None
    

@dataclass 
class ChunkedDocument:
    """A document that has been chunked."""
    url: str
    title: Optional[str]
    chunks: list[TextChunk]
    total_tokens: int
    total_chunks: int
    

def get_tokenizer(encoding_name: str = DEFAULT_ENCODING) -> tiktoken.Encoding:
    """Get the tiktoken encoder for token counting."""
    try:
        return tiktoken.get_encoding(encoding_name)
    except Exception as e:
        logger.warning(f"Failed to get encoding {encoding_name}, using fallback: {e}")
        return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str, encoding: Optional[tiktoken.Encoding] = None) -> int:
    """Count the number of tokens in a text string."""
    if not text:
        return 0
    if encoding is None:
        encoding = get_tokenizer()
    return len(encoding.encode(text))


def chunk_text(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    encoding: Optional[tiktoken.Encoding] = None,
) -> list[tuple[str, int, int]]:
    """
    Split text into chunks based on token count.
    
    Uses sentence-aware splitting to avoid cutting in the middle of sentences
    when possible, while maintaining the target chunk size.
    
    Args:
        text: The text to chunk
        chunk_size: Target number of tokens per chunk
        chunk_overlap: Number of tokens to overlap between chunks
        encoding: Tiktoken encoding to use (default: cl100k_base)
        
    Returns:
        List of tuples (chunk_text, start_char, end_char)
    """
    if not text or not text.strip():
        return []
    
    if encoding is None:
        encoding = get_tokenizer()
    
    # Clean text - normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    # Split into sentences for better chunk boundaries
    sentences = _split_into_sentences(text)
    
    chunks = []
    current_chunk_sentences = []
    current_chunk_tokens = 0
    current_start_char = 0
    
    for sentence in sentences:
        sentence_tokens = len(encoding.encode(sentence))
        
        # If a single sentence exceeds chunk size, split it by words
        if sentence_tokens > chunk_size:
            # Flush current chunk if any
            if current_chunk_sentences:
                chunk_text = ' '.join(current_chunk_sentences)
                end_char = current_start_char + len(chunk_text)
                chunks.append((chunk_text, current_start_char, end_char))
                
                # Calculate overlap for next chunk
                overlap_sentences = _get_overlap_sentences(
                    current_chunk_sentences, chunk_overlap, encoding
                )
                current_chunk_sentences = overlap_sentences
                current_chunk_tokens = sum(len(encoding.encode(s)) for s in overlap_sentences)
                current_start_char = end_char - len(' '.join(overlap_sentences)) if overlap_sentences else end_char
            
            # Split long sentence by words
            word_chunks = _split_long_sentence(sentence, chunk_size, chunk_overlap, encoding)
            for word_chunk, _, _ in word_chunks:
                chunk_start = text.find(word_chunk, current_start_char)
                if chunk_start == -1:
                    chunk_start = current_start_char
                chunk_end = chunk_start + len(word_chunk)
                chunks.append((word_chunk, chunk_start, chunk_end))
                current_start_char = chunk_end
            
            current_chunk_sentences = []
            current_chunk_tokens = 0
            continue
        
        # Check if adding this sentence would exceed chunk size
        if current_chunk_tokens + sentence_tokens > chunk_size and current_chunk_sentences:
            # Save current chunk
            chunk_text = ' '.join(current_chunk_sentences)
            end_char = current_start_char + len(chunk_text)
            chunks.append((chunk_text, current_start_char, end_char))
            
            # Calculate overlap for next chunk
            overlap_sentences = _get_overlap_sentences(
                current_chunk_sentences, chunk_overlap, encoding
            )
            current_chunk_sentences = overlap_sentences + [sentence]
            current_chunk_tokens = sum(len(encoding.encode(s)) for s in current_chunk_sentences)
            current_start_char = end_char - len(' '.join(overlap_sentences)) if overlap_sentences else end_char
        else:
            current_chunk_sentences.append(sentence)
            current_chunk_tokens += sentence_tokens
    
    # Don't forget the last chunk
    if current_chunk_sentences:
        chunk_text = ' '.join(current_chunk_sentences)
        end_char = current_start_char + len(chunk_text)
        # Only add if it meets minimum size
        if count_tokens(chunk_text, encoding) >= MIN_CHUNK_SIZE or not chunks:
            chunks.append((chunk_text, current_start_char, end_char))
        elif chunks:
            # Merge with previous chunk if too small
            prev_text, prev_start, _ = chunks[-1]
            chunks[-1] = (prev_text + ' ' + chunk_text, prev_start, end_char)
    
    return chunks


def _split_into_sentences(text: str) -> list[str]:
    """
    Split text into sentences using a simple regex-based approach.
    
    Handles common sentence endings while trying to avoid false splits
    on abbreviations like "Mr." or "Dr.".
    """
    # Pattern to split on sentence-ending punctuation followed by space and capital letter
    # This is a simplified approach - a full NLP solution would be more accurate
    sentence_pattern = r'(?<=[.!?])\s+(?=[A-Z])'
    
    sentences = re.split(sentence_pattern, text)
    
    # Clean up and filter empty sentences
    sentences = [s.strip() for s in sentences if s.strip()]
    
    return sentences


def _get_overlap_sentences(
    sentences: list[str],
    target_tokens: int,
    encoding: tiktoken.Encoding,
) -> list[str]:
    """Get the last sentences that fit within the target token count for overlap."""
    overlap = []
    tokens = 0
    
    for sentence in reversed(sentences):
        sentence_tokens = len(encoding.encode(sentence))
        if tokens + sentence_tokens > target_tokens:
            break
        overlap.insert(0, sentence)
        tokens += sentence_tokens
    
    return overlap


def _split_long_sentence(
    sentence: str,
    chunk_size: int,
    chunk_overlap: int,
    encoding: tiktoken.Encoding,
) -> list[tuple[str, int, int]]:
    """Split a long sentence into smaller chunks by words."""
    words = sentence.split()
    chunks = []
    current_words = []
    current_tokens = 0
    start_idx = 0
    
    for i, word in enumerate(words):
        word_tokens = len(encoding.encode(word + ' '))
        
        if current_tokens + word_tokens > chunk_size and current_words:
            chunk_text = ' '.join(current_words)
            chunks.append((chunk_text, start_idx, start_idx + len(chunk_text)))
            
            # Keep some words for overlap
            overlap_words = []
            overlap_tokens = 0
            for w in reversed(current_words):
                w_tokens = len(encoding.encode(w + ' '))
                if overlap_tokens + w_tokens > chunk_overlap:
                    break
                overlap_words.insert(0, w)
                overlap_tokens += w_tokens
            
            current_words = overlap_words + [word]
            current_tokens = overlap_tokens + word_tokens
            start_idx = start_idx + len(chunk_text) - len(' '.join(overlap_words))
        else:
            current_words.append(word)
            current_tokens += word_tokens
    
    # Last chunk
    if current_words:
        chunk_text = ' '.join(current_words)
        chunks.append((chunk_text, start_idx, start_idx + len(chunk_text)))
    
    return chunks


def chunk_document(
    content: str,
    url: str,
    title: Optional[str] = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> ChunkedDocument:
    """
    Chunk a document's content into smaller pieces.
    
    Args:
        content: The full text content of the document
        url: The document URL (for reference)
        title: Optional document title
        chunk_size: Target tokens per chunk
        chunk_overlap: Tokens of overlap
        
    Returns:
        ChunkedDocument with list of TextChunk objects
    """
    encoding = get_tokenizer()
    
    raw_chunks = chunk_text(content, chunk_size, chunk_overlap, encoding)
    
    chunks = []
    for i, (text, start, end) in enumerate(raw_chunks):
        chunks.append(TextChunk(
            text=text,
            token_count=count_tokens(text, encoding),
            chunk_index=i,
            start_char=start,
            end_char=end,
            source_url=url,
            source_title=title,
        ))
    
    total_tokens = count_tokens(content, encoding)
    
    return ChunkedDocument(
        url=url,
        title=title,
        chunks=chunks,
        total_tokens=total_tokens,
        total_chunks=len(chunks),
    )


def chunk_documents(
    documents: list[dict],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[ChunkedDocument]:
    """
    Chunk multiple documents.
    
    Args:
        documents: List of dicts with 'url', 'title', and 'content' keys
        chunk_size: Target tokens per chunk
        chunk_overlap: Tokens of overlap
        
    Returns:
        List of ChunkedDocument objects
    """
    chunked_docs = []
    
    for doc in documents:
        content = doc.get('content', '')
        if not content:
            logger.debug(f"Skipping document with no content: {doc.get('url', 'unknown')}")
            continue
        
        chunked = chunk_document(
            content=content,
            url=doc.get('url', ''),
            title=doc.get('title'),
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        chunked_docs.append(chunked)
    
    return chunked_docs


def get_all_chunks(chunked_documents: list[ChunkedDocument]) -> list[TextChunk]:
    """Flatten all chunks from multiple documents into a single list."""
    all_chunks = []
    for doc in chunked_documents:
        all_chunks.extend(doc.chunks)
    return all_chunks
