import { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { fetchAllRoutes, fetchHeatmap } from '../services/api';
import { coordsFromLocation } from '../utils/geo';
import { loadRecentRoutes, persistRecentRoute } from '../utils/recentRoutesStorage';

/**
 * Central routing state hook.
 *
 * Owns: source, destination, routes, selectedRoute, heatmap, loading, error.
 * Exposes imperative actions that components can call.
 */
export default function useRoutes() {
  const [source, setSource] = useState(null);           // [lat, lon] | null
  const [destination, setDestination] = useState(null);  // [lat, lon] | null
  /** OSRM profile: driving (car) or foot (walking) */
  const [travelProfile, setTravelProfile] = useState('driving');
  const [selectedMode, setSelectedMode] = useState('safest');
  const [routes, setRoutes] = useState([]);              // RoutePayload[]
  const [rankings, setRankings] = useState(null);
  const [tradeoffs, setTradeoffs] = useState(null);
  const [selectedRoute, setSelectedRoute] = useState(null); // mode string
  const [heatmapData, setHeatmapData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [heatmapLoading, setHeatmapLoading] = useState(false);
  const [error, setError] = useState(null);
  const [heatmapError, setHeatmapError] = useState(null);
  const [recentVersion, setRecentVersion] = useState(0);

  // Prevent duplicate in-flight requests
  const abortRef = useRef(null);

  const recentRoutes = useMemo(() => loadRecentRoutes(), [recentVersion]);

  const findRoutesLiveRef = useRef(async () => {});

  // New origin/destination → heatmap tiles are for the wrong bbox until re-fetched
  useEffect(() => {
    setHeatmapData(null);
    setHeatmapError(null);
  }, [source, destination]);

  /**
   * Fetches all three route variants for the current source / destination.
   */
  /**
   * Clears routes (back to landing) WITHOUT clearing source/destination.
   * Used by the × button so addresses remain filled in the search panel.
   */
  const clearRoutes = useCallback(() => {
    if (abortRef.current) abortRef.current.abort();
    setRoutes([]);
    setSelectedRoute(null);
    setRankings(null);
    setTradeoffs(null);
    setError(null);
  }, []);

  const clearHeatmapError = useCallback(() => setHeatmapError(null), []);

  /**
   * @param {{ source?: object, destination?: object }} [overrides] — optional locations to use instead of state (recent-route replay).
   */
  const findRoutes = useCallback(async (overrides = {}) => {
    const src = overrides.source ?? source;
    const dest = overrides.destination ?? destination;

    if (!src || !dest) {
      setError('Please set both a source and a destination.');
      return;
    }

    const srcPair = coordsFromLocation(src);
    const destPair = coordsFromLocation(dest);
    if (!srcPair || !destPair) {
      setError(
        'Invalid coordinates (latitude must be ±90°, longitude ±180°). Re-select your places or tap the map again.'
      );
      return;
    }

    if (overrides.source) setSource(overrides.source);
    if (overrides.destination) setDestination(overrides.destination);

    // Cancel any prior in-flight request
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setError(null);
    setRoutes([]);
    setSelectedRoute(null);
    setRankings(null);
    setTradeoffs(null);

    try {
      const data = await fetchAllRoutes({
        source: srcPair,
        destination: destPair,
        travelProfile,
      });
      if (controller.signal.aborted) return;

      setRoutes(data.routes || []);
      setRankings(data.rankings || null);
      setTradeoffs(data.tradeoff_metrics || null);

      const match = (data.routes || []).find((r) => r.mode === selectedMode);
      setSelectedRoute(match ? match.mode : data.routes?.[0]?.mode || null);

      persistRecentRoute(src, dest);
      setRecentVersion((v) => v + 1);
    } catch (err) {
      if (err.name !== 'AbortError') {
        setError(err.message || 'Failed to fetch routes.');
      }
    } finally {
      setLoading(false);
    }
  }, [source, destination, selectedMode, travelProfile]);

  findRoutesLiveRef.current = findRoutes;

  // Re-fetch when user switches Drive/Walk while results are visible
  useEffect(() => {
    if (routes.length === 0) return;
    findRoutesLiveRef.current();
  }, [travelProfile]);

  /**
   * Load heatmap for map viewport center (lat/lng), using the same safety stack as routing.
   */
  const loadHeatmap = useCallback(async ({ lat, lng }) => {
    if (lat == null || lng == null || Number.isNaN(lat) || Number.isNaN(lng)) {
      setHeatmapError('Could not read map center. Pan the map and try again.');
      return;
    }
    setHeatmapLoading(true);
    setHeatmapError(null);
    try {
      const data = await fetchHeatmap(lat, lng);
      setHeatmapData(data);
    } catch (err) {
      console.error('Heatmap load failed:', err);
      setHeatmapError(err.message || 'Could not load safety heatmap for this area.');
    } finally {
      setHeatmapLoading(false);
    }
  }, []);

  return {
    // State
    source,
    destination,
    travelProfile,
    selectedMode,
    routes,
    rankings,
    tradeoffs,
    selectedRoute,
    heatmapData,
    loading,
    heatmapLoading,
    error,
    heatmapError,
    recentRoutes,

    // Actions
    setSource,
    setDestination,
    setTravelProfile,
    setSelectedMode,
    setSelectedRoute,
    setError,
    clearHeatmapError,
    setHeatmapError,
    findRoutes,
    clearRoutes,
    loadHeatmap,
  };
}
