/**
 * Teams SDK Integration Wrapper
 * Detects Teams environment, initializes Microsoft Teams SDK, manages context
 */

export interface TeamsContext {
  isTeams: boolean;
  userId?: string;
  tenantId?: string;
  channelId?: string;
  groupId?: string;
  teamName?: string;
  teamId?: string;
  initialized: boolean;
}

let teamsContext: TeamsContext = {
  isTeams: false,
  initialized: false,
};

/**
 * Detect if running inside Teams iframe
 */
export function isRunningInTeams(): boolean {
  try {
    // Check if Teams SDK is available globally
    return !!(window as any).microsoftTeams;
  } catch {
    return false;
  }
}

/**
 * Initialize Teams SDK and retrieve context
 * Safe to call multiple times; only initializes once
 */
export async function initializeTeamsSDK(): Promise<TeamsContext> {
  // Return if already initialized
  if (teamsContext.initialized) {
    return teamsContext;
  }

  const inTeams = isRunningInTeams();
  
  if (!inTeams) {
    teamsContext = {
      isTeams: false,
      initialized: true,
    };
    return teamsContext;
  }

  try {
    // Load Teams SDK dynamically if not already loaded
    if (!(window as any).microsoftTeams) {
      await loadTeamsSDK();
    }

    const teams = (window as any).microsoftTeams;
    
    // Initialize Teams SDK
    await new Promise<void>((resolve) => {
      teams.initialize(() => {
        // Get context asynchronously
        teams.getContext((context: any) => {
          teamsContext = {
            isTeams: true,
            userId: context.userObjectId || context.userId,
            tenantId: context.tid,
            channelId: context.channelId,
            groupId: context.groupId,
            teamName: context.teamName,
            teamId: context.teamId,
            initialized: true,
          };
          resolve();
        });
      });
    });
  } catch (error) {
    console.warn('Failed to initialize Teams SDK:', error);
    teamsContext = {
      isTeams: false,
      initialized: true,
    };
  }

  return teamsContext;
}

/**
 * Load Teams SDK script dynamically
 */
function loadTeamsSDK(): Promise<void> {
  return new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = 'https://res.cdn.office.net/teams-js/2.0.0/js/microsoft.teams.min.js';
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error('Failed to load Teams SDK'));
    document.head.appendChild(script);
  });
}

/**
 * Get current Teams context (must call initializeTeamsSDK first)
 */
export function getTeamsContext(): TeamsContext {
  return teamsContext;
}

/**
 * Notify Teams that content has loaded (for tab initialization)
 */
export function notifyTeamsSuccess(): void {
  try {
    const teams = (window as any).microsoftTeams;
    if (teams?.notifySuccess) {
      teams.notifySuccess();
    }
  } catch (error) {
    console.warn('Failed to notify Teams success:', error);
  }
}

/**
 * Notify Teams of failure (for tab initialization)
 */
export function notifyTeamsFailure(reason?: string): void {
  try {
    const teams = (window as any).microsoftTeams;
    if (teams?.notifyFailure) {
      teams.notifyFailure(reason || 'Tab initialization failed');
    }
  } catch (error) {
    console.warn('Failed to notify Teams failure:', error);
  }
}

/**
 * Open URL in Teams context (uses Teams navigation if available)
 */
export function navigateInTeams(url: string): void {
  try {
    const teams = (window as any).microsoftTeams;
    if (teams?.executeDeepLink) {
      teams.executeDeepLink(url);
    } else {
      window.location.href = url;
    }
  } catch (error) {
    console.warn('Failed to navigate in Teams:', error);
    window.location.href = url;
  }
}
