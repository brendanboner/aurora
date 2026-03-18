/**
 * Event Bus for Server-Sent Events
 * Manages feed updates → chat messages and toast notifications
 * Implements automatic message injection and alert system
 */

class EventBus {
  constructor() {
    this.eventSource = null;
    this.isConnected = false;
    this.reconnectAttempts = 0;
    this.maxReconnectAttempts = 5;
    this.reconnectDelay = 3000; // ms

    this.feedListeners = new Set();
    this.chatListeners = new Set();
    this.toastListeners = new Set();
    this.connectionListeners = new Set();
  }

  /**
   * Connect to SSE stream for real-time updates
   */
  connect() {
    if (this.isConnected || this.eventSource) {
      return;
    }

    try {
      // SSE endpoint: /api/oracle/feed/stream (when implemented)
      // For now, this is a placeholder - Oracle doesn't have SSE yet
      // TODO: Implement feed streaming in Oracle service
      console.log('[EventBus] Feed streaming not yet implemented in Oracle service');
      this.isConnected = false;
      this.emitConnectionStatus(false);
      return;
    } catch (error) {
      console.error('[EventBus] Failed to establish SSE connection:', error);
      this.handleConnectionError();
    }
  }

  /**
   * Disconnect from SSE stream
   */
  disconnect() {
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
  handleFeedUpdate(feedUpdate) {
    // Emit raw feed update for components that need it
    this.emitFeedUpdate(feedUpdate);

    // Auto-convert to chat message
    const chatMessage = {
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
    const notification = {
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
  formatFeedAsMessage(feedUpdate) {
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
  handleConnectionError() {
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
  onFeedUpdate(listener) {
    this.feedListeners.add(listener);
    return () => this.feedListeners.delete(listener);
  }

  /**
   * Subscribe to chat messages (both from user and system)
   */
  onChatMessage(listener) {
    this.chatListeners.add(listener);
    return () => this.chatListeners.delete(listener);
  }

  /**
   * Subscribe to toast notifications
   */
  onNotification(listener) {
    this.toastListeners.add(listener);
    return () => this.toastListeners.delete(listener);
  }

  /**
   * Subscribe to connection status changes
   */
  onConnectionStatus(listener) {
    this.connectionListeners.add(listener);
    return () => this.connectionListeners.delete(listener);
  }

  /**
   * Manually add a message to chat (e.g., user sent message)
   */
  addChatMessage(message) {
    this.emitChatMessage(message);
  }

  /**
   * Get current connection status
   */
  getConnectionStatus() {
    return this.isConnected;
  }

  // Private emit methods
  emitFeedUpdate(event) {
    this.feedListeners.forEach((listener) => listener(event));
  }

  emitChatMessage(event) {
    this.chatListeners.forEach((listener) => listener(event));
  }

  emitNotification(event) {
    this.toastListeners.forEach((listener) => listener(event));
  }

  emitConnectionStatus(status) {
    this.connectionListeners.forEach((listener) => listener(status));
  }
}

// Export singleton instance
export const eventBus = new EventBus();
