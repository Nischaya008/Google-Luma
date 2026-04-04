/**
 * Default map focus when GPS is unavailable or times out.
 * Bennigana Halli — East Bengaluru, Karnataka, India (WGS84).
 */
export const DEFAULT_MAP_CENTER = [12.9960, 77.6630];
export const DEFAULT_MAP_LABEL = 'Bennigana Halli, Bengaluru, Karnataka';

/** Total wait for browser geolocation before falling back to default map (ms). */
export const LOCATION_WAIT_MS = 60_000;
/** Show “default map in Xs” when remaining time is at or below this (ms). */
export const LOCATION_WARNING_REMAINING_MS = 30_000;
