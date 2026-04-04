/**
 * Persist last N route searches in localStorage (home UX only; not synced).
 */
import { coordsFromLocation } from './geo';

const STORAGE_KEY = 'luma_recent_routes_v1';
export const RECENT_ROUTES_MAX = 5;

function routeFingerprint(src, dest) {
  const s = coordsFromLocation(src);
  const d = coordsFromLocation(dest);
  if (!s || !d) return null;
  return `${s[0].toFixed(4)}:${s[1].toFixed(4)}|${d[0].toFixed(4)}:${d[1].toFixed(4)}`;
}

function normalizeEndpoint(loc, pair) {
  const [lat, lon] = pair;
  const label =
    loc && typeof loc === 'object' && loc.label
      ? loc.label
      : `${lat.toFixed(4)}, ${lon.toFixed(4)}`;
  return { label, coords: [lat, lon] };
}

/**
 * @returns {Array<{ id: string, savedAt: number, source: {label: string, coords: number[]}, destination: {label: string, coords: number[]} }>}
 */
export function loadRecentRoutes() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(
        (e) =>
          e &&
          Array.isArray(e.source?.coords) &&
          e.source.coords.length >= 2 &&
          Array.isArray(e.destination?.coords) &&
          e.destination.coords.length >= 2
      )
      .slice(0, RECENT_ROUTES_MAX);
  } catch {
    return [];
  }
}

/**
 * Push a successful search to the front; dedupe by coordinate fingerprint.
 */
export function persistRecentRoute(source, destination) {
  const sPair = coordsFromLocation(source);
  const dPair = coordsFromLocation(destination);
  if (!sPair || !dPair) return;

  const fp = routeFingerprint(source, destination);
  if (!fp) return;

  const entry = {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
    savedAt: Date.now(),
    source: normalizeEndpoint(source, sPair),
    destination: normalizeEndpoint(destination, dPair),
  };

  let list = loadRecentRoutes();
  list = list.filter((e) => {
    const other = routeFingerprint(
      { coords: e.source.coords },
      { coords: e.destination.coords }
    );
    return other !== fp;
  });
  list.unshift(entry);
  list = list.slice(0, RECENT_ROUTES_MAX);
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
  } catch {
    /* quota / private mode */
  }
}
