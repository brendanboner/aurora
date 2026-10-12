-- Domain Preferences for User Preferences
-- Adds a domains array to user_preferences so users can declare which
-- networking domains they care about (e.g. 'routing', 'wi-fi', 'security').
-- The oracle uses this to soft-boost matching resources in results.
--
-- Valid domain values:
--   wi-fi, wired, routing, security, transport,
--   cloud, iot, video-audio, wireless-broadband, general

ALTER TABLE user_preferences
    ADD COLUMN IF NOT EXISTS domains TEXT[] DEFAULT '{}';

COMMENT ON COLUMN user_preferences.domains IS
    'Networking domain preferences. Valid values: wi-fi, wired, routing, security, '
    'transport, cloud, iot, video-audio, wireless-broadband, general';
