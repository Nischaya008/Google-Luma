import { useState, useCallback, useEffect, useRef } from 'react';
import useRoutes from './hooks/useRoutes';
import MapView from './components/MapView';
import Sidebar from './components/Sidebar';
import RoutePanel from './components/RoutePanel';
import HeatmapLayer from './components/HeatmapLayer';
import RecentRoutesPanel from './components/RecentRoutesPanel';
import TravelModeIsland from './components/TravelModeIsland';
import LiveSafetyView from './components/LiveSafetyView';
import ToastNotification from './components/ToastNotification';
import { initSystemLocation } from './services/api';
import { normalizeLatLonPair } from './utils/geo';
import {
  DEFAULT_MAP_CENTER,
  DEFAULT_MAP_LABEL,
  LOCATION_WAIT_MS,
  LOCATION_WARNING_REMAINING_MS,
} from './constants/mapDefaults';

export default function App() {
  const {
    source,
    destination,
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
    setSource,
    setDestination,
    setSelectedMode,
    setSelectedRoute,
    setError,
    clearHeatmapError,
    setHeatmapError,
    findRoutes,
    clearRoutes,
    loadHeatmap,
    recentRoutes,
    travelProfile,
    setTravelProfile,
  } = useRoutes();

  const mapControllerRef = useRef(null);
  const hasRoutes = routes.length > 0;

  const [placingMarker, setPlacingMarker] = useState('source');
  const [heatmapVisible, setHeatmapVisible] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [liveSafetyActive, setLiveSafetyActive] = useState(false);
  const [systemInitializing, setSystemInitializing] = useState(true);
  const [systemLocation, setSystemLocation] = useState(null);
  /** 'pending' | 'gps' | 'default' — whether the blue dot reflects a real GPS fix */
  const [locationSource, setLocationSource] = useState('pending');
  const [secondsRemaining, setSecondsRemaining] = useState(Math.ceil(LOCATION_WAIT_MS / 1000));
  const [showFallbackWarning, setShowFallbackWarning] = useState(false);
  const gpsAcquiredRef = useRef(false);

  useEffect(() => {
    gpsAcquiredRef.current = false;
    const deadline = Date.now() + LOCATION_WAIT_MS;

    const tick = () => {
      const left = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
      setSecondsRemaining(left);
      setShowFallbackWarning(
        left > 0 &&
        left * 1000 <= LOCATION_WARNING_REMAINING_MS &&
        !gpsAcquiredRef.current
      );
      if (left === 0 && !gpsAcquiredRef.current) {
        setLocationSource('default');
        setSystemInitializing(false);
        clearInterval(interval);
      }
    };

    const interval = setInterval(tick, 250);
    tick();

    const finishGps = (latitude, longitude) => {
      if (gpsAcquiredRef.current) return;
      gpsAcquiredRef.current = true;
      setSystemLocation([latitude, longitude]);
      setLocationSource('gps');
      setShowFallbackWarning(false);
      initSystemLocation(latitude, longitude)
        .then(() => setSystemInitializing(false))
        .catch(() => setSystemInitializing(false));
      clearInterval(interval);
    };

    if ('geolocation' in navigator) {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          const { latitude, longitude } = position.coords;
          finishGps(latitude, longitude);
        },
        () => {
          /* denied / unavailable — keep countdown until timeout */
        },
        { enableHighAccuracy: true, timeout: LOCATION_WAIT_MS - 500, maximumAge: 0 }
      );
    } else {
      gpsAcquiredRef.current = true;
      setLocationSource('default');
      setSystemInitializing(false);
      clearInterval(interval);
    }

    return () => clearInterval(interval);
  }, []);

  const requestBrowserLocation = useCallback(
    (onSuccess, onError) => {
      if (!('geolocation' in navigator)) {
        onError(new Error('Geolocation is not supported in this browser.'));
        return;
      }
      navigator.geolocation.getCurrentPosition(
        (position) => {
          const { latitude, longitude } = position.coords;
          setSystemLocation([latitude, longitude]);
          setLocationSource('gps');
          onSuccess([latitude, longitude]);
        },
        (err) => onError(err),
        { enableHighAccuracy: true, timeout: 25000, maximumAge: 0 }
      );
    },
    []
  );

  const handleMapClick = useCallback(
    async (latlng) => {
      const normalized = normalizeLatLonPair(latlng[0], latlng[1]);
      if (!normalized) {
        setError('That tap produced invalid coordinates. Try again or search by place name.');
        return;
      }
      const [lat, lon] = normalized;
      const isSource = placingMarker === 'source';
      const handler = isSource ? setSource : setDestination;
      const fallbackLabel = `${lat.toFixed(4)}, ${lon.toFixed(4)}`;
      handler({ coords: [lat, lon], label: fallbackLabel });
      if (isSource) setPlacingMarker('destination');
      else if (placingMarker === 'destination') setPlacingMarker(null);
      else setPlacingMarker('destination');
      setMobileOpen(false);

      try {
        const res = await fetch(
          `https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lon}&format=json`,
          { headers: { 'Accept-Language': 'en-US,en;q=0.9', 'User-Agent': 'GoogleLuma/1.0' } }
        );
        const data = await res.json();
        if (data.display_name) {
          const label = data.display_name.split(',').slice(0, 2).join(', ');
          handler({ coords: [lat, lon], label });
        }
      } catch (e) {
        console.error('Reverse geocode failed', e);
      }
    },
    [placingMarker, setSource, setDestination, setError]
  );

  const handleHeatmapToggle = useCallback(() => {
    const next = !heatmapVisible;
    setHeatmapVisible(next);
    if (next) {
      clearHeatmapError();
      requestAnimationFrame(() => {
        const c = mapControllerRef.current?.getCenter?.();
        if (c?.length >= 2 && Number.isFinite(c[0]) && Number.isFinite(c[1])) {
          loadHeatmap({ lat: c[0], lng: c[1] });
        } else {
          setHeatmapError('Map is not ready — try again in a moment.');
        }
      });
    }
  }, [heatmapVisible, loadHeatmap, clearHeatmapError, setHeatmapError]);

  const handleMapLocateOrCenter = useCallback(() => {
    if (hasRoutes) {
      mapControllerRef.current?.fitRoutes?.();
      return;
    }
    if (systemLocation?.length >= 2 && locationSource === 'gps') {
      mapControllerRef.current?.flyToUser?.(systemLocation, 15);
      return;
    }
    requestBrowserLocation(
      (ll) => {
        initSystemLocation(ll[0], ll[1]).catch(() => { });
        mapControllerRef.current?.flyToUser?.(ll, 15);
      },
      () =>
        setError(
          'Location permission is required. Allow access in your browser settings, or search for a place.'
        )
    );
  }, [hasRoutes, systemLocation, locationSource, requestBrowserLocation, setError]);

  const handleToggleMobile = useCallback(() => setMobileOpen(p => !p), []);

  const handleRecentRouteSelect = useCallback(
    (entry) => {
      findRoutes({
        source: { coords: [...entry.source.coords], label: entry.source.label },
        destination: { coords: [...entry.destination.coords], label: entry.destination.label },
      });
    },
    [findRoutes]
  );

  /** X button: clear routes but keep addresses so user can re-search */
  const handleBackToSearch = useCallback(() => {
    clearRoutes();
    setLiveSafetyActive(false);
    setPlacingMarker(null); // addresses already set; don't reset marker mode
  }, [clearRoutes]);

  /** Activate live camera safety mode (mobile only) */
  const handleActivateLiveSafety = useCallback(() => {
    setLiveSafetyActive(true);
  }, []);

  /** Deactivate live camera safety mode */
  const handleDeactivateLiveSafety = useCallback(() => {
    setLiveSafetyActive(false);
  }, []);

  useEffect(() => {
    if (hasRoutes) {
      setMobileOpen(false);
    }
  }, [hasRoutes]);

  // ── Shared pill button styles ──────────────────────────
  const pillBtnBase = {
    display: 'flex', alignItems: 'center', gap: 7,
    padding: '9px 15px',
    borderRadius: 99,
    backdropFilter: 'blur(12px)',
    fontSize: 12.5,
    fontWeight: 700,
    letterSpacing: '0.01em',
    cursor: 'pointer',
    transition: 'all 280ms cubic-bezier(0.4,0,0.2,1)',
    flexShrink: 0,
    whiteSpace: 'nowrap',
  };

  // ── Heatmap pill button (shared style) ──────────────────────────
  const HeatmapBtn = ({ style = {} }) => (
    <button
      id="btn-heatmap-toggle"
      onClick={handleHeatmapToggle}
      aria-pressed={heatmapVisible}
      aria-label="Toggle safety heatmap"
      style={{
        ...pillBtnBase,
        border: `1.5px solid ${heatmapVisible ? '#1A73E8' : 'rgba(210,204,196,0.8)'}`,
        background: heatmapVisible ? '#1A73E8' : 'rgba(255,255,255,0.93)',
        color: heatmapVisible ? 'white' : '#1C1917',
        boxShadow: heatmapVisible
          ? '0 4px 14px rgba(26,115,232,0.35)'
          : '0 2px 10px rgba(48,40,28,0.10)',
        ...style,
      }}
    >
      <svg width="13" height="13" viewBox="0 0 24 24" fill={heatmapVisible ? 'white' : '#1A73E8'}>
        <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z" />
      </svg>
      {heatmapLoading ? 'Loading…' : 'Safety Heatmap'}
      {heatmapVisible && (
        <span style={{ width: 5, height: 5, borderRadius: '50%', background: 'rgba(255,255,255,0.7)', flexShrink: 0 }} />
      )}
    </button>
  );

  const LocateBtn = ({ style = {} }) => (
    <button
      type="button"
      onClick={handleMapLocateOrCenter}
      aria-label={hasRoutes ? 'Center map on routes' : 'Go to my location'}
      style={{
        ...pillBtnBase,
        border: '1.5px solid rgba(210,204,196,0.8)',
        background: 'rgba(255,255,255,0.93)',
        color: '#1C1917',
        boxShadow: '0 2px 10px rgba(48,40,28,0.10)',
        ...style,
      }}
    >
      {hasRoutes ? (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#1A73E8" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" />
        </svg>
      ) : (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#1A73E8" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <circle cx="12" cy="12" r="3" />
          <path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
        </svg>
      )}
      {hasRoutes ? 'Center route' : 'My location'}
    </button>
  );

  return (
    <div className="relative w-full h-full bg-[var(--color-bg)]">

      <TravelModeIsland
        value={travelProfile === 'foot' ? 'foot' : 'driving'}
        onChange={(v) => setTravelProfile(v === 'foot' ? 'foot' : 'driving')}
        disabled={loading}
      />

      {/* ── Sidebar (landing mode — absolute bottom-left) ── */}
      {!hasRoutes && (
        <Sidebar
          source={source}
          destination={destination}
          selectedMode={selectedMode}
          travelProfile={travelProfile}
          loading={loading}
          error={error}
          hasRoutes={false}
          onSetSource={setSource}
          onSetDestination={setDestination}
          onSetSelectedMode={setSelectedMode}
          onSetSelectedRoute={setSelectedRoute}
          onFindRoutes={findRoutes}
          onSetError={setError}
          placingMarker={placingMarker}
          onSetPlacingMarker={setPlacingMarker}
          mobileOpen={mobileOpen}
          onToggleMobile={handleToggleMobile}
          routes={routes}
          gpsCoords={systemLocation}
        />
      )}

      {/* ── Map (full screen) ── */}
      <div className="absolute inset-0">
        <MapView
          source={source?.coords || source}
          destination={destination?.coords || destination}
          systemLocation={locationSource === 'gps' ? systemLocation : null}
          routes={routes}
          selectedRoute={selectedRoute}
          onSelectRoute={setSelectedRoute}
          onMapClick={handleMapClick}
          isPlacing={!!placingMarker}
          mapControllerRef={mapControllerRef}
          travelProfile={travelProfile}
        >
          <HeatmapLayer heatmapData={heatmapData} visible={heatmapVisible} />
        </MapView>

        {!hasRoutes && (
          <RecentRoutesPanel
            items={recentRoutes}
            onSelect={handleRecentRouteSelect}
            loading={loading}
          />
        )}

        {/* ── Pill buttons (Desktop always, Mobile when hasRoutes) ── */}
        <div
          className={!hasRoutes ? "hidden md:flex" : "flex"}
          style={{
            position: 'absolute',
            top: hasRoutes ? 72 : 16,
            right: 16,
            zIndex: 1000,
            flexDirection: 'column',
            alignItems: 'flex-end',
            gap: 10,
            maxWidth: 280,
          }}
        >
          <HeatmapBtn />
          <LocateBtn />
          {heatmapError && (
            <div
              role="alert"
              style={{
                fontSize: 11,
                fontWeight: 600,
                color: '#C5221F',
                background: '#FFF0EE',
                border: '1.5px solid #FAC5C1',
                borderRadius: 12,
                padding: '8px 12px',
                lineHeight: 1.4,
              }}
            >
              {heatmapError}
            </div>
          )}
        </div>

        {/* ── Mobile-only pill buttons: horizontal row above drawer, hidden when drawer open ── */}
        {!hasRoutes && (
          <div
            className="flex md:hidden"
            style={{
              position: 'absolute',
              // Sits just above the peekable drawer handle (90px) + some gap
              bottom: 114,
              left: '50%',
              zIndex: 998, // Placed below drawer (1000) so it smoothly slides behind it
              flexDirection: 'row',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 8,
              // Fade out very quickly when drawer opens
              opacity: mobileOpen ? 0 : 1,
              transform: `translateX(-50%) ${mobileOpen ? 'translateY(12px)' : 'translateY(0)'}`,
              pointerEvents: mobileOpen ? 'none' : 'auto',
              transition: 'opacity 150ms ease, transform 150ms ease',
            }}
          >
            <HeatmapBtn />
            <LocateBtn />
          </div>
        )}

        {/* Mobile heatmap error (shown when drawer closed) */}
        {!hasRoutes && heatmapError && !mobileOpen && (
          <div
            className="flex md:hidden"
            role="alert"
            style={{
              position: 'absolute',
              bottom: 146,
              right: 12,
              zIndex: 1001,
              fontSize: 11,
              fontWeight: 600,
              color: '#C5221F',
              background: '#FFF0EE',
              border: '1.5px solid #FAC5C1',
              borderRadius: 12,
              padding: '8px 12px',
              lineHeight: 1.4,
              maxWidth: 220,
            }}
          >
            {heatmapError}
          </div>
        )}

        {/* X button — nav only */}
        {hasRoutes && (
          <button
            onClick={handleBackToSearch}
            aria-label="Back to search"
            style={{
              position: 'absolute', top: 16, right: 16, zIndex: 1001,
              width: 42, height: 42, borderRadius: '50%',
              background: 'rgba(255,255,255,0.93)',
              backdropFilter: 'blur(12px)',
              border: '1.5px solid rgba(210,204,196,0.7)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              cursor: 'pointer',
              boxShadow: '0 2px 10px rgba(48,40,28,0.12)',
              transition: 'all 180ms',
              color: '#1C1917',
            }}
            onMouseEnter={e => e.currentTarget.style.background = 'white'}
            onMouseLeave={e => e.currentTarget.style.background = 'rgba(255,255,255,0.93)'}
          >
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        )}

        {/* Compact onboarding hint */}
        {!source && !destination && !hasRoutes && (
          <div className="absolute left-1/2 -translate-x-1/2 z-[500] flex items-center md:bottom-8 top-24 md:top-auto" style={{
            gap: 10,
            background: 'rgba(254,252,248,0.97)',
            backdropFilter: 'blur(16px)',
            border: '1.5px solid rgba(210,204,196,0.7)',
            borderRadius: 99,
            padding: '10px 18px',
            boxShadow: '0 4px 20px rgba(48,40,28,0.12)',
            animation: 'fadeIn 0.4s ease-out',
            whiteSpace: 'nowrap',
          }}>
            {/* Pulsing dot */}
            <span style={{ position: 'relative', width: 10, height: 10, flexShrink: 0 }}>
              <span style={{
                position: 'absolute', inset: 0, borderRadius: '50%',
                background: '#1A73E8', opacity: 0.3,
                animation: 'ping 1.4s cubic-bezier(0,0,0.2,1) infinite',
              }} />
              <span style={{ position: 'absolute', inset: '2px', borderRadius: '50%', background: '#1A73E8' }} />
            </span>
            <span style={{ fontSize: 13, fontWeight: 600, color: '#1C1917' }}>
              Tap the map to set your route
            </span>
          </div>
        )}
      </div>

      {/* ── L-shape navigation dock (nav mode only) ── */}
      {hasRoutes && (
        <div style={{
          position: 'absolute',
          bottom: 0,
          left: 0,
          right: 0,
          zIndex: 1000,
          display: 'flex',
          alignItems: 'flex-end',
          pointerEvents: 'none',

          /* Desktop: flex-row L-layout */
        }}
          className="flex-col md:flex-row"
        >
          {/* ── Sidebar compact card (left column) ── */}
          <div style={{ flexShrink: 0, pointerEvents: 'auto' }} className="w-full md:w-[420px]">
            <Sidebar
              source={source}
              destination={destination}
              selectedMode={selectedMode}
              travelProfile={travelProfile}
              loading={loading}
              error={error}
              hasRoutes={true}
              onSetSource={setSource}
              onSetDestination={setDestination}
              onSetSelectedMode={setSelectedMode}
              onSetSelectedRoute={setSelectedRoute}
              onFindRoutes={findRoutes}
              onSetError={setError}
              placingMarker={placingMarker}
              onSetPlacingMarker={setPlacingMarker}
              mobileOpen={mobileOpen}
              onToggleMobile={handleToggleMobile}
              routes={routes}
              gpsCoords={systemLocation}
            />
          </div>

          {/* ── RoutePanel (right column, fills remaining width) ── */}
          <div style={{ flex: 1, minWidth: 0, pointerEvents: 'auto', width: '100%' }}>
            <RoutePanel
              routes={routes}
              selectedRoute={selectedRoute}
              tradeoffs={tradeoffs}
              loading={loading}
              onSelectRoute={setSelectedRoute}
              travelLabel={travelProfile === 'foot' ? 'Walk' : 'Drive'}
              onActivateLiveSafety={handleActivateLiveSafety}
            />
          </div>
        </div>
      )}

      {/* ── Live Safety Camera View (mobile only, overlays everything) ── */}
      {liveSafetyActive && hasRoutes && (
        <LiveSafetyView
          route={routes.find(r => r.mode === selectedRoute) || routes[0]}
          routeSafetyScore={
            (routes.find(r => r.mode === selectedRoute) || routes[0])?.average_safety_score ?? null
          }
          userLocation={locationSource === 'gps' ? systemLocation : null}
          onBack={handleDeactivateLiveSafety}
        />
      )}

      {/* ── Init overlay ── */}
      {systemInitializing && (
        <div style={{
          position: 'absolute', inset: 0, zIndex: 2000,
          background: '#FEFCF8',
          display: 'flex', flexDirection: 'column',
          alignItems: 'center',
          overflowY: 'auto', overflowX: 'hidden',
          padding: '32px 20px',
          boxSizing: 'border-box',
        }}>
          <div style={{ flex: 1 }} />

          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 32 }}>
            <img src="/maps_logo.png" alt="Google Luma" style={{ width: 42, height: 42, objectFit: 'contain', flexShrink: 0 }} />
            <div>
              <h1 style={{ fontSize: 22, fontWeight: 800, color: '#1C1917', letterSpacing: '-0.4px', lineHeight: 1.1 }}>
                Google Luma
              </h1>
              <p style={{ fontSize: 10, fontWeight: 600, color: '#9C9284', letterSpacing: '0.07em', textTransform: 'uppercase', marginTop: 3 }}>
                Safety-Aware Navigation
              </p>
            </div>
          </div>

          <img src="/loading.gif" alt="Loading…"
            style={{ width: 120, height: 120, objectFit: 'contain', marginBottom: 24 }} />

          <h2 style={{ fontSize: 18, fontWeight: 700, color: '#1C1917', textAlign: 'center', marginBottom: 10, letterSpacing: '-0.2px' }}>
            Preparing your map
          </h2>
          <p style={{ fontSize: 13, color: '#6B6259', textAlign: 'center', maxWidth: 320, lineHeight: 1.65, fontWeight: 400, marginBottom: 12 }}>
            Luma waits up to <strong style={{ color: '#1A73E8', fontWeight: 600 }}>one minute</strong> for your location so the map can start near you.
            If permission is not granted in time, Luma opens the map at <strong style={{ color: '#1A73E8', fontWeight: 600 }}>{DEFAULT_MAP_LABEL}</strong>.
          </p>
          {locationSource === 'pending' ? (
            <div style={{
              marginBottom: 16,
              padding: '12px 18px',
              borderRadius: 14,
              background: '#F0F4FA',
              border: '1.5px solid #D7E3FC',
              minWidth: 200,
              textAlign: 'center',
            }}>
              <p style={{ margin: 0, fontSize: 11, fontWeight: 700, color: '#5F6368', letterSpacing: '0.06em', textTransform: 'uppercase' }}>
                Time remaining
              </p>
              <p style={{ margin: '6px 0 0', fontSize: 28, fontWeight: 800, color: '#1A73E8', letterSpacing: '-0.5px', fontVariantNumeric: 'tabular-nums' }}>
                {String(Math.floor(secondsRemaining / 60)).padStart(2, '0')}:{String(secondsRemaining % 60).padStart(2, '0')}
              </p>
            </div>
          ) : (
            <div style={{
              marginBottom: 16,
              padding: '12px 18px',
              borderRadius: 14,
              background: '#E8F0FE',
              border: '1.5px solid #C5D8F9',
              minWidth: 200,
              textAlign: 'center',
            }}>
              <p style={{ margin: 0, fontSize: 11, fontWeight: 700, color: '#1A73E8', letterSpacing: '0.06em', textTransform: 'uppercase' }}>
                Location Acquired
              </p>
              <p style={{ margin: '6px 0 0', fontSize: 16, fontWeight: 700, color: '#1A73E8', letterSpacing: '-0.2px', display: 'flex', alignItems: 'center', justifyContent: 'center', height: '34px' }}>
                Building safe routes...
              </p>
            </div>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, width: '100%', maxWidth: 320 }}>
            {[
              { label: 'Waiting for your location (up to 1 minute)', done: locationSource !== 'pending' },
              { label: 'Initializing safety engine', done: !systemInitializing },
            ].map(({ label, done }, i) => (
              <div key={i} style={{
                display: 'flex', alignItems: 'center', gap: 12,
                padding: '11px 16px', borderRadius: 13,
                background: done ? '#E8F0FE' : 'white',
                border: `1.5px solid ${done ? '#C5D8F9' : '#EAE4DC'}`,
                boxShadow: '0 1px 4px rgba(48,40,28,0.04)',
              }}>
                <div style={{
                  width: 26, height: 26, borderRadius: '50%',
                  background: done ? '#1A73E8' : '#F0EBE2',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
                }}>
                  {done ? (
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="white">
                      <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z" />
                    </svg>
                  ) : (
                    <svg className="animate-spin" width="13" height="13" viewBox="0 0 24 24" fill="none">
                      <circle cx="12" cy="12" r="10" stroke="#B0A899" strokeWidth="4" opacity="0.3" />
                      <path fill="#9C9284" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" opacity="0.75" />
                    </svg>
                  )}
                </div>
                <p style={{ fontSize: 12.5, fontWeight: 600, color: done ? '#1A73E8' : '#6B6259', flex: 1, lineHeight: 1.3 }}>
                  {label}
                </p>
              </div>
            ))}
          </div>

          <p style={{ fontSize: 10.5, color: '#B8B0A4', marginTop: 24, textAlign: 'center', fontWeight: 500 }}>
            Only required on first load · Subsequent searches are instant
          </p>

          <div style={{ flex: 1 }} />
        </div>
      )}

      {/* ── Toast Notifications ── */}
      <ToastNotification />
    </div>
  );
}
