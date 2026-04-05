/**
 * API Service Layer for Google Luma.
 *
 * Custom fetch wrapper with base URL resolution, timeout, and structured error handling.
 * Uses the Vite dev proxy (/api -> localhost:8000) so no CORS issues in development.
 */

// If VITE_API_URL is set (e.g., http://13.204.79.8:8000), use it. Otherwise rely on Vite proxy
const BASE_URL = import.meta.env.VITE_API_URL || '';
const API_BASE = `${BASE_URL}/api/v1/routing`;
const DEFAULT_TIMEOUT_MS = 900000;

/**
 * Internal fetch wrapper.
 * - Applies timeout via AbortController.
 * - Parses JSON and normalizes error shape.
 */
async function request(endpoint, options = {}) {
  const controller = new AbortController();
  const timeout = options.timeout || DEFAULT_TIMEOUT_MS;
  const timer = setTimeout(() => controller.abort(), timeout);

  const url = `${API_BASE}${endpoint}`;

  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        ...(options.headers || {}),
      },
    });

    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `Request failed with status ${response.status}`);
    }

    return await response.json();
  } catch (err) {
    if (err.name === 'AbortError') {
      throw new Error('Request timed out. Please try again.');
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * POST /init
 * Pre-warms the system with the user's location.
 */
export async function initSystemLocation(lat, lng) {
  // Allow a very long timeout for init since downloading a large graph can take time
  const params = new URLSearchParams({ lat, lng });
  return request(`/init?${params.toString()}`, {
    method: 'POST',
    timeout: 900000,
  });
}

/**
 * POST /route
 * Fetches a single route for the given mode.
 */
export async function fetchRoute({ source, destination, mode }) {
  return request('/route', {
    method: 'POST',
    body: JSON.stringify({ source, destination, mode }),
  });
}

/**
 * GET /routes/compare
 * Returns all three route variants (fastest, balanced, safest) in one call.
 */
export async function fetchAllRoutes({ source, destination, travelProfile = 'driving' }) {
  const params = new URLSearchParams({
    src_lat: source[0],
    src_lon: source[1],
    dest_lat: destination[0],
    dest_lon: destination[1],
    travel_profile: travelProfile === 'foot' ? 'foot' : 'driving',
  });
  return request(`/routes/compare?${params.toString()}`);
}

/**
 * GET /heatmap
 * Returns every edge in the road graph with its safety score and geometry.
 */
export async function fetchHeatmap(lat, lng) {
  const params = new URLSearchParams();
  if (lat && lng) {
    params.set('lat', lat);
    params.set('lng', lng);
  }
  const queryString = params.toString() ? `?${params.toString()}` : '';
  return request(`/heatmap${queryString}`);
}

/**
 * GET /explain
 * Returns SHAP-based explainability for a specific road segment.
 */
export async function fetchExplanation(u, v, key = 0) {
  const params = new URLSearchParams({ u, v, key });
  return request(`/explain?${params.toString()}`);
}

/**
 * POST /cv/analyze
 * Sends a base64-encoded camera frame for real-time CV safety analysis.
 * Returns cv_safety_score, blended score, detections, and AI explanation.
 */
export async function analyzeCameraFrame(frameBase64, routeSafetyScore = null) {
  return request('/cv/analyze', {
    method: 'POST',
    body: JSON.stringify({
      frame_base64: frameBase64,
      route_safety_score: routeSafetyScore,
    }),
    timeout: 10000, // 10s max — generous for heavy DETR inference
  });
}

/**
 * POST /cv/reset
 * Clears the anomaly detection history when starting a new session.
 */
export async function resetCVHistory() {
  return request('/cv/reset', { method: 'POST' });
}
