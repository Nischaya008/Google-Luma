/**
 * Formatting utilities for Google Luma.
 * Centralizes all display-related transforms so components stay clean.
 */

/**
 * Converts seconds into a human-readable string like "4 min" or "1 hr 12 min".
 */
export function formatETA(seconds) {
  if (seconds == null || isNaN(seconds)) return '--';
  const totalMinutes = Math.round(seconds / 60);
  if (totalMinutes < 1) return '<1 min';
  if (totalMinutes < 60) return `${totalMinutes} min`;
  const hrs = Math.floor(totalMinutes / 60);
  const mins = totalMinutes % 60;
  return mins > 0 ? `${hrs} hr ${mins} min` : `${hrs} hr`;
}

/**
 * Converts a 0-1 safety score to a percentage string like "82%".
 */
export function formatSafetyPercent(score) {
  if (score == null || isNaN(score)) return '--';
  return `${Math.round(score * 100)}%`;
}

/**
 * Returns a human label for a route mode.
 */
export function getModeLabel(mode) {
  const labels = {
    fastest: 'Fastest',
    balanced: 'Balanced',
    safest: 'Safest',
  };
  return labels[mode] || mode;
}

/**
 * Returns the brand color for a given route mode.
 */
export function getModeColor(mode) {
  const colors = {
    fastest: '#1A73E8',
    balanced: '#F9AB00',
    safest: '#34A853',
  };
  return colors[mode] || '#5F6368';
}

/**
 * Converts a safety score (0-1) to a gradient color from red through yellow to green.
 */
export function safetyToColor(score) {
  if (score == null) return '#5F6368';
  const clamped = Math.max(0, Math.min(1, score));
  // Red (0) -> Yellow (0.5) -> Green (1)
  if (clamped <= 0.5) {
    const ratio = clamped / 0.5;
    const r = 234;
    const g = Math.round(67 + (188 - 67) * ratio);
    const b = Math.round(53 + (4 - 53) * ratio);
    return `rgb(${r},${g},${b})`;
  }
  const ratio = (clamped - 0.5) / 0.5;
  const r = Math.round(249 + (52 - 249) * ratio);
  const g = Math.round(171 + (168 - 171) * ratio);
  const b = Math.round(0 + (83 - 0) * ratio);
  return `rgb(${r},${g},${b})`;
}

/**
 * Converts backend coordinate objects [{lat, lon}] to Leaflet-compatible [lat, lng] arrays.
 */
export function toLatLngs(coordArray) {
  if (!Array.isArray(coordArray)) return [];
  return coordArray.map((c) => [c.lat, c.lon]);
}
