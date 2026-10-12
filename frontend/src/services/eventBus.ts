/**
 * Event Bus for Server-Sent Events
 * Manages feed updates → chat messages and toast notifications
 * Implements automatic message injection and alert system
 */

import apiClient from '../api/client';

export interface FeedUpdateEvent {
  id: string;
  type: 'new_post' | 'post_update' | 'comment' | 'like';
  content: string;
  author: string;
  authorId: string;
  timestamp: string;
  metadata?: Record<string, any>;
}

export interface ChatMessageEvent {
  id: string;
  type: 'message' | 'system';
  content: string;
  author: string;
  timestamp: string;
  isSystemGenerated?: boolean;
}

export interface ToastNotification {
  id: string;
  title: string;
  message: string;
  type: 'info' | 'success' | 'warning' | 'error';
  duration?: number; // ms, default 4000
  action?: {
    label: string;
    callback: () => void;
  };
}

type EventListener<T> = (event: T) => void;

class EventBus {
  private eventSource: EventSource | null = null;
  private isConnected = false;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectDelay = 3000; // ms

  private feedListeners: Set<EventListener<FeedUpdateEvent>> = new Set();
  private chatListeners: Set<EventListener<ChatMessageEvent>> = new Set();
  private toastListeners: Set<EventListener<ToastNotification>> = new Set();
  private connectionListeners: Set<EventListener<boolean>> = new Set();

  /**
   * Connect to SSE stream for real-time updates
   */
  public connect(): void {
    if (this.isConnected || this.eventSource) {
      return;
    }

    try {
      // SSE endpoint: /api/feed/stream
      // Backend must stream updates as Server-Sent Events
      this.eventSource = new EventSource('/api/feed/stream', {
        withCredentials: true,
      });

      this.eventSource.addEventListener('feed_update', (event: Event) => {
        try {
          const data = JSON.parse((event as MessageEvent).data) as FeedUpdateEvent;
          this.handleFeedUpdate(data);
        } catch (error) {
          console.error('Failed to parse feed update:', error);
        }
      });

      this.eventSource.addEventListener('chat_message', (event: Event) => {
        try {
          const data = JSON.parse((event as MessageEvent).data) as ChatMessageEvent;
          this.emitChatMessage(data);
        } catch (error) {
          console.error('Failed to parse chat message:', error);
        }
      });

      this.eventSource.addEventListener('notification', (event: Event) => {
        try {
          const data = JSON.parse((event as MessageEvent).data) as ToastNotification;
          this.emitNotification(data);
        } catch (error) {
          console.error('Failed to parse notification:', error);
        }
      });

      this.eventSource.onerror = () => {
        this.handleConnectionError();
      };

      this.isConnected = true;
      this.reconnectAttempts = 0;
      this.emitConnectionStatus(true);
      console.log('[EventBus] Connected to SSE stream');
    } catch (error) {
      console.error('[EventBus] Failed to establish SSE connection:', error);
      this.handleConnectionError();
    }
  }

  /**
   * Disconnect from SSE stream
   */
  public disconnect(): void {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
      this.isConnected = false;
      this.emitConnectionStatus(false);
      console.log('[EventBus] Disconnected from SSE stream');
    }
  }

  /**
   * Handle feed updates: inject into chat and trigger notification
   */
  private handleFeedUpdate(feedUpdate: FeedUpdateEvent): void {
    // Emit raw feed update for components that need it
    this.emitFeedUpdate(feedUpdate);

    // Auto-convert to chat message
    const chatMessage: ChatMessageEvent = {
      id: `feed-${feedUpdate.id}`,
      type: 'system',
      content: this.formatFeedAsMessage(feedUpdate),
      author: feedUpdate.author,
      timestamp: feedUpdate.timestamp,
      isSystemGenerated: true,
    };

    // Inject into chat
    this.emitChatMessage(chatMessage);

    // Trigger toast notification
    const notification: ToastNotification = {
      id: feedUpdate.id,
      title: `New update from ${feedUpdate.author}`,
      message: feedUpdate.content.substring(0, 100) + (feedUpdate.content.length > 100 ? '...' : ''),
      type: 'info',
      duration: 5000,
      action: {
        label: 'View',
        callback: () => {
          // User clicked "View" - could navigate to full post
          console.log('User wants to view feed update:', feedUpdate.id);
        },
      },
    };

    this.emitNotification(notification);
  }

  /**
   * Format feed update as readable chat message
   */
  private formatFeedAsMessage(feedUpdate: FeedUpdateEvent): string {
    switch (feedUpdate.type) {
      case 'new_post':
        return `📰 ${feedUpdate.author} posted: "${feedUpdate.content.substring(0, 80)}..."`;
      case 'post_update':
        return `✏️ ${feedUpdate.author} updated their post: "${feedUpdate.content.substring(0, 80)}..."`;
      case 'comment':
        return `💬 ${feedUpdate.author} commented: "${feedUpdate.content.substring(0, 80)}..."`;
      case 'like':
        return `👍 ${feedUpdate.author} liked a post`;
      default:
        return `📢 Update from ${feedUpdate.author}: ${feedUpdate.content}`;
    }
  }

  /**
   * Handle connection errors and attempt reconnect
   */
  private handleConnectionError(): void {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }

    this.isConnected = false;
    this.emitConnectionStatus(false);

    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      this.reconnectAttempts++;
      const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1); // exponential backoff
      console.log(
        `[EventBus] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`
      );

      setTimeout(() => {
        this.connect();
      }, delay);
    } else {
      console.error('[EventBus] Max reconnect attempts reached. Falling back to polling.');
      // Fallback: emit event so UI can switch to polling if needed
      this.emitNotification({
        id: 'connection-failed',
        title: 'Connection Lost',
        message: 'Real-time updates unavailable. Falling back to polling.',
        type: 'warning',
        duration: 5000,
      });
    }
  }

  /**
   * Subscribe to feed updates
   */
  public onFeedUpdate(listener: EventListener<FeedUpdateEvent>): () => void {
    this.feedListeners.add(listener);
    return () => this.feedListeners.delete(listener);
  }

  /**
   * Subscribe to chat messages (both from user and system)
   */
  public onChatMessage(listener: EventListener<ChatMessageEvent>): () => void {
    this.chatListeners.add(listener);
    return () => this.chatListeners.delete(listener);
  }

  /**
   * Subscribe to toast notifications
   */
  public onNotification(listener: EventListener<ToastNotification>): () => void {
    this.toastListeners.add(listener);
    return () => this.toastListeners.delete(listener);
  }

  /**
   * Subscribe to connection status changes
   */
  public onConnectionStatus(listener: EventListener<boolean>): () => void {
    this.connectionListeners.add(listener);
    return () => this.connectionListeners.delete(listener);
  }

  /**
   * Manually add a message to chat (e.g., user sent message)
   */
  public addChatMessage(message: ChatMessageEvent): void {
    this.emitChatMessage(message);
  }

  /**
   * Get current connection status
   */
  public getConnectionStatus(): boolean {
    return this.isConnected;
  }

  // Private emit methods
  private emitFeedUpdate(event: FeedUpdateEvent): void {
    this.feedListeners.forEach((listener) => listener(event));
  }

  private emitChatMessage(event: ChatMessageEvent): void {
    this.chatListeners.forEach((listener) => listener(event));
  }

  private emitNotification(event: ToastNotification): void {
    this.toastListeners.forEach((listener) => listener(event));
  }

  private emitConnectionStatus(status: boolean): void {
    this.connectionListeners.forEach((listener) => listener(status));
  }
}

// Export singleton instance
export const eventBus = new EventBus();
