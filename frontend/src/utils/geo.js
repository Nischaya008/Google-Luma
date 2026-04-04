/**
 * WGS84 helpers — prevents invalid lon/lat (e.g. OSRM 400, OSMnx UTM failures).
 * Convention: stored pairs are always [latitude, longitude] in decimal degrees.
 */

/**
 * @param {number} lat
 * @param {number} lon
 * @returns {boolean}
 */
export function isValidWgs84(lat, lon) {
  return (
    Number.isFinite(lat) &&
    Number.isFinite(lon) &&
    Math.abs(lat) <= 90 &&
    Math.abs(lon) <= 180
  );
}

/**
 * Returns [lat, lon] if valid, tries lon/lat swap if that fixes range, else null.
 * @param {number} a
 * @param {number} b
 * @returns {[number, number]|null}
 */
export function normalizeLatLonPair(a, b) {
  const x = Number(a);
  const y = Number(b);
  if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
  if (isValidWgs84(x, y)) return [x, y];
  if (isValidWgs84(y, x)) return [y, x];
  return null;
}

/**
 * Resolve { coords, label } | [lat, lon] to validated [lat, lon] or null.
 * @param {unknown} location
 * @returns {[number, number]|null}
 */
export function coordsFromLocation(location) {
  if (!location) return null;
  const raw = Array.isArray(location) ? location : location.coords;
  if (!Array.isArray(raw) || raw.length < 2) return null;
  return normalizeLatLonPair(raw[0], raw[1]);
}

/**
 * Great-circle distance in meters between two [lat, lon] pairs.
 * @param {[number, number]} a
 * @param {[number, number]} b
 * @returns {number}
 */
export function haversineMeters(a, b) {
  if (!a || !b || a.length < 2 || b.length < 2) return Number.POSITIVE_INFINITY;
  const R = 6371000;
  const dLat = ((b[0] - a[0]) * Math.PI) / 180;
  const dLon = ((b[1] - a[1]) * Math.PI) / 180;
  const lat1 = (a[0] * Math.PI) / 180;
  const lat2 = (b[0] * Math.PI) / 180;
  const s =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(s)));
}

/**
 * Choose Photon/Nominatim bias: user area (GPS or default city) unless the other
 * route endpoint is far away — then bias to that endpoint so suggestions match
 * the remote city’s streets and POIs.
 *
 * @param {object} p
 * @param {'source'|'destination'} p.field — which input is being searched
 * @param {unknown} p.source
 * @param {unknown} p.destination
 * @param {[number, number]|null} p.gpsCoords — real GPS when available
 * @param {[number, number]} p.defaultCenter
 * @param {number} [p.farThresholdM=45000]
 * @returns {{ lat: number, lon: number, strategy: string }}
 */
export function computeSearchBias({
  field,
  source,
  destination,
  gpsCoords,
  defaultCenter,
  farThresholdM = 45000,
}) {
  const base = gpsCoords && gpsCoords.length >= 2 ? gpsCoords : defaultCenter;
  const otherLoc = field === 'source' ? destination : source;
  const otherCoords = coordsFromLocation(otherLoc);
  if (otherCoords && base && base.length >= 2) {
    const dist = haversineMeters(base, otherCoords);
    if (Number.isFinite(dist) && dist >= farThresholdM) {
      return {
        lat: otherCoords[0],
        lon: otherCoords[1],
        strategy: 'remote_endpoint',
      };
    }
  }
  return {
    lat: base[0],
    lon: base[1],
    strategy: gpsCoords ? 'gps_or_user_area' : 'default_city',
  };
}

