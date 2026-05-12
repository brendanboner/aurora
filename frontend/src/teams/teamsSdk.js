/**
 * Teams SDK Integration Wrapper
 * Uses @microsoft/teams-js v2 SDK (promise-based API).
 * Detects Teams environment, initializes SDK, retrieves context, and provides SSO token helper.
 */

import * as microsoftTeams from '@microsoft/teams-js';

let teamsContext = {
  isTeams: false,
  initialized: false,
};

/**
 * Detect if running inside the Microsoft Teams iframe.
 * The v2 SDK surfaces this via app.isInitialized() after initialize() resolves,
 * but we can do a lightweight pre-check via the parent-frame origin hint Teams injects.
 */
export function isRunningInTeams() {
  try {
    return (
      window.parent !== window ||
      window.navigator.userAgent.includes('Teams') ||
      document.referrer.includes('teams.microsoft.com') ||
      document.referrer.includes('teams.live.com')
    );
  } catch {
    return false;
  }
}

/**
 * Initialize Teams SDK (v2) and retrieve context.
 * Safe to call multiple times — returns cached context after first successful init.
 */
export async function initializeTeamsSDK() {
  if (teamsContext.initialized) {
    return teamsContext;
  }

  try {
    await microsoftTeams.app.initialize();

    const context = await microsoftTeams.app.getContext();

    teamsContext = {
      isTeams: true,
      userId: context.user?.id,
      userPrincipalName: context.user?.userPrincipalName,
      tenantId: context.user?.tenant?.id,
      channelId: context.channel?.id,
      groupId: context.team?.groupId,
      teamName: context.team?.displayName,
      teamId: context.team?.internalId,
      initialized: true,
    };
  } catch (error) {
    // Not running in Teams or SDK initialization failed (e.g., browser standalone)
    console.warn('[TeamsSDK] Not running in Teams or SDK unavailable:', error?.message || error);
    teamsContext = {
      isTeams: false,
      initialized: true,
    };
  }

  return teamsContext;
}

/**
 * Get current Teams context (must call initializeTeamsSDK first).
 */
export function getTeamsContext() {
  return teamsContext;
}

/**
 * Silently acquire a Teams SSO token (Azure AD token for the signed-in Teams user).
 * Returns the token string, or null if not in Teams / SSO not configured.
 *
 * The token can be sent to the auth service's /auth/teams-sso endpoint to exchange
 * it for an Aurora session cookie without a browser redirect.
 *
 * Prerequisites (in manifest.json):
 *   "webApplicationInfo": { "id": "<azure-app-client-id>", "resource": "https://<your-domain>" }
 */
export async function getTeamsSSOToken() {
  if (!teamsContext.isTeams) {
    return null;
  }

  try {
    const token = await microsoftTeams.authentication.getAuthToken();
    return token;
  } catch (error) {
    console.warn('[TeamsSDK] SSO token acquisition failed:', error?.message || error);
    return null;
  }
}

/**
 * Notify Teams that the tab has loaded successfully.
 */
export function notifyTeamsSuccess() {
  try {
    if (teamsContext.isTeams) {
      microsoftTeams.app.notifySuccess();
    }
  } catch (error) {
    console.warn('[TeamsSDK] notifySuccess failed:', error);
  }
}

/**
 * Notify Teams that the tab failed to load.
 */
export function notifyTeamsFailure(reason) {
  try {
    if (teamsContext.isTeams) {
      microsoftTeams.app.notifyFailure({
        reason: microsoftTeams.app.FailedReason.Other,
        message: reason || 'Tab initialization failed',
      });
    }
  } catch (error) {
    console.warn('[TeamsSDK] notifyFailure failed:', error);
  }
}

/**
 * Navigate to a URL within Teams context.
 */
export function navigateInTeams(url) {
  try {
    if (teamsContext.isTeams) {
      microsoftTeams.app.openLink(url);
    } else {
      window.location.href = url;
    }
  } catch (error) {
    console.warn('[TeamsSDK] Navigation failed, falling back to window.location:', error);
    window.location.href = url;
  }
}

