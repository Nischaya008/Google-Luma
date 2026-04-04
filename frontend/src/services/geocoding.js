/**
 * Forward geocoding: Open-Meteo (population-ranked, free) + Photon (OSM detail)
 * + Nominatim (global search, unbounded — bounded mode hid entire cities like Mumbai
 * when the map bias was Bengaluru).
 *
 * Open-Meteo: https://open-meteo.com/en/docs/geocoding-api — no API key, CORS-friendly.
 */
import { normalizeLatLonPair } from '../utils/geo';

const USER_AGENT = 'GoogleLuma/1.0 (safety routing)';

const OPEN_METEO_SEARCH = 'https://geocoding-api.open-meteo.com/v1/search';

/** ~Haversine km from bias point */
function distanceKm(lat, lon, bias) {
  if (!bias || !Number.isFinite(bias.lat) || !Number.isFinite(bias.lon)) return 0;
  const R = 6371;
  const dLat = ((lat - bias.lat) * Math.PI) / 180;
  const dLon = ((lon - bias.lon) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((bias.lat * Math.PI) / 180) *
      Math.cos((lat * Math.PI) / 180) *
      Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.asin(Math.min(1, Math.sqrt(a)));
}

function photonFeatureToLatLon(feature) {
  const g = feature?.geometry;
  if (!g?.coordinates) return null;
  const { type, coordinates: c } = g;

  if (type === 'Point' && Array.isArray(c) && c.length >= 2) {
    const [lon, lat] = c;
    return normalizeLatLonPair(lat, lon);
  }
  if (type === 'LineString' && Array.isArray(c) && c.length > 0) {
    const mid = c[Math.floor(c.length / 2)];
    if (Array.isArray(mid) && mid.length >= 2) {
      const [lon, lat] = mid;
      return normalizeLatLonPair(lat, lon);
    }
  }
  if (type === 'Polygon' && Array.isArray(c?.[0]) && c[0].length > 0) {
    const ring = c[0];
    let slat = 0;
    let slon = 0;
    let n = 0;
    for (const pt of ring) {
      if (Array.isArray(pt) && pt.length >= 2) {
        const [lon, lat] = pt;
        const pair = normalizeLatLonPair(lat, lon);
        if (pair) {
          slat += pair[0];
          slon += pair[1];
          n += 1;
        }
      }
    }
    if (n > 0) return normalizeLatLonPair(slat / n, slon / n);
  }
  return null;
}

function photonToPlace(feature, idx) {
  const props = feature.properties || {};
  const pair = photonFeatureToLatLon(feature);
  if (!pair) return null;
  const [lat, lon] = pair;
  const parts = [
    props.name,
    props.street,
    props.district,
    props.city || props.town || props.village,
    props.state,
    props.country,
  ].filter(Boolean);
  const uniqueParts = [...new Set(parts)];
  const displayName = uniqueParts.join(', ');
  const osmKey = props.osm_key != null && props.osm_value != null
    ? `${props.osm_key}:${props.osm_value}`
    : '';
  return {
    place_id: `ph:${props.osm_id ?? idx}:${osmKey}:${lat.toFixed(4)}:${lon.toFixed(4)}`,
    lat,
    lon,
    name: props.name || uniqueParts[0] || 'Location',
    display_name: displayName,
    provider: 'photon',
    population: 0,
    osm_key: props.osm_key,
    osm_value: props.osm_value,
    importance: typeof props.importance === 'number' ? props.importance : 0.25,
  };
}

function nominatimToPlace(hit, idx) {
  const lat = parseFloat(hit.lat);
  const lon = parseFloat(hit.lon);
  const pair = normalizeLatLonPair(lat, lon);
  if (!pair) return null;
  const display = hit.display_name || '';
  const parts = display.split(', ');
  return {
    place_id: `nm:${hit.osm_id ?? idx}:${pair[0].toFixed(5)}:${pair[1].toFixed(5)}`,
    lat: pair[0],
    lon: pair[1],
    name: parts[0] || display.slice(0, 48),
    display_name: display,
    provider: 'nominatim',
    population: 0,
    importance: parseFloat(hit.importance) || 0.15,
  };
}

/**
 * Stable key so many OSM segments (same railway, road) collapse to one row.
 * WHY: Photon returns separate LineString features per geometry chunk with the same label.
 */
function dedupeCanonicalKey(p) {
  const primary = (p.name || '')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 96);
  const rest = (p.display_name || '')
    .split(',')
    .slice(1, 6)
    .join(',')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 160);
  return `${primary}||${rest}`;
}

function openMeteoToPlace(hit, idx) {
  const lat = hit.latitude;
  const lon = hit.longitude;
  const pair = normalizeLatLonPair(lat, lon);
  if (!pair) return null;
  const admin = [hit.admin4, hit.admin3, hit.admin2, hit.admin1, hit.country]
    .filter(Boolean)
    .join(', ');
  const display = [hit.name, admin].filter(Boolean).join(', ');
  return {
    place_id: `om:${hit.id ?? idx}:${pair[0].toFixed(4)}:${pair[1].toFixed(4)}`,
    lat: pair[0],
    lon: pair[1],
    name: hit.name || 'Place',
    display_name: display,
    provider: 'open-meteo',
    population: typeof hit.population === 'number' ? hit.population : 0,
    importance: 0.5 + Math.min(0.45, Math.log10((hit.population || 0) + 10) / 12),
  };
}

function nominatimGlobalSearchUrl(q) {
  const base =
    import.meta.env.VITE_NOMINATIM_URL?.replace(/\/$/, '') ||
    (import.meta.env.DEV ? '/nominatim' : 'https://nominatim.openstreetmap.org');
  const path = `${base}/search`;
  const u = path.startsWith('http') ? new URL(path) : new URL(path, window.location.origin);
  u.searchParams.set('format', 'jsonv2');
  u.searchParams.set('addressdetails', '1');
  u.searchParams.set('limit', '12');
  u.searchParams.set('q', q);
  return u.toString();
}

function openMeteoUrl(q) {
  const u = new URL(OPEN_METEO_SEARCH);
  u.searchParams.set('name', q);
  u.searchParams.set('count', '15');
  u.searchParams.set('language', 'en');
  u.searchParams.set('format', 'json');
  return u.toString();
}

function photonUrl(q, bias) {
  const u = new URL('https://photon.komoot.io/api/');
  u.searchParams.set('q', q);
  u.searchParams.set('limit', '12');
  u.searchParams.set('lang', 'en');
  if (bias && Number.isFinite(bias.lat) && Number.isFinite(bias.lon)) {
    u.searchParams.set('lat', String(bias.lat));
    u.searchParams.set('lon', String(bias.lon));
  }
  return u.toString();
}

/**
 * Merge providers, dedupe by canonical label, keep best-scoring row per key.
 */
function dedupePlaces(rows) {
  const best = new Map();
  for (const r of rows) {
    if (!r) continue;
    const key = dedupeCanonicalKey(r);
    const prev = best.get(key);
    const score =
      (r.population || 0) * 2 +
      (r.importance || 0) * 1e6 +
      (r.provider === 'open-meteo' ? 5000 : 0);
    const prevScore = prev
      ? (prev.population || 0) * 2 +
        (prev.importance || 0) * 1e6 +
        (prev.provider === 'open-meteo' ? 5000 : 0)
      : -1;
    if (!prev || score >= prevScore) best.set(key, r);
  }
  return [...best.values()];
}

/**
 * Google-like ordering: prefix match, then population “trending”, then distance to bias.
 */
function rankPlaces(places, query, bias) {
  const qn = query.trim().toLowerCase();
  const shortQuery = qn.length <= 2;

  return places
    .map((p) => {
      const nameL = (p.name || '').toLowerCase();
      const dispL = (p.display_name || '').toLowerCase();
      let nameTier = 0;
      if (nameL.startsWith(qn)) nameTier = 3;
      else if (dispL.startsWith(qn)) nameTier = 2;
      else if (nameL.includes(qn) || dispL.includes(qn)) nameTier = 1;

      const dist = distanceKm(p.lat, p.lon, bias);
      const pop = p.population || 0;
      const popScore = Math.log10(pop + 1);

      // Short queries: emphasize population (major cities first); longer: distance + match.
      const distPenalty = shortQuery ? dist / 8000 : dist / 3500;
      const composite =
        nameTier * 4 +
        (shortQuery ? popScore * 2.2 : popScore * 1.4) -
        distPenalty +
        (p.provider === 'nominatim' && nameTier >= 2 ? 0.3 : 0);

      return { ...p, _rank: composite };
    })
    .sort((a, b) => b._rank - a._rank)
    .map(({ _rank, ...p }) => p);
}

/**
 * @param {string} query
 * @param {{ lat: number, lon: number }} bias
 * @param {AbortSignal} signal
 */
export async function fetchGeocodingSuggestions(query, bias, signal) {
  const q = query.trim();
  if (q.length < 1) return [];

  const safeBias =
    bias && Number.isFinite(bias.lat) && Number.isFinite(bias.lon)
      ? bias
      : { lat: 12.996, lon: 77.663 };

  const headers = {
    'Accept-Language': 'en-US,en;q=0.9',
    'User-Agent': USER_AGENT,
  };

  const [omRes, phRes, nmRes] = await Promise.allSettled([
    fetch(openMeteoUrl(q), { signal }),
    fetch(photonUrl(q, safeBias), { signal, headers }),
    fetch(nominatimGlobalSearchUrl(q), { signal, headers }),
  ]);

  const out = [];

  if (omRes.status === 'fulfilled' && omRes.value.ok) {
    try {
      const data = await omRes.value.json();
      let i = 0;
      for (const hit of data.results || []) {
        const p = openMeteoToPlace(hit, i++);
        if (p) out.push(p);
      }
    } catch {
      /* ignore */
    }
  }

  if (phRes.status === 'fulfilled' && phRes.value.ok) {
    try {
      const data = await phRes.value.json();
      let i = 0;
      for (const f of data.features || []) {
        const p = photonToPlace(f, i++);
        if (p) out.push(p);
      }
    } catch {
      /* ignore */
    }
  }

  if (nmRes.status === 'fulfilled' && nmRes.value.ok) {
    try {
      const arr = await nmRes.value.json();
      let j = 0;
      for (const h of arr || []) {
        const p = nominatimToPlace(h, j++);
        if (p) out.push(p);
      }
    } catch {
      /* ignore */
    }
  }

  const merged = dedupePlaces(out);
  return rankPlaces(merged, q, safeBias).slice(0, 18);
}
