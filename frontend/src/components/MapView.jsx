import { useEffect, useMemo, useRef, useCallback, memo, useImperativeHandle } from 'react';
import { MapContainer, TileLayer, Polyline, Marker, Tooltip, useMap } from 'react-leaflet';
import L from 'leaflet';
import { toLatLngs, getModeColor, formatETA, formatSafetyPercent } from '../utils/formatters';
import { DEFAULT_MAP_CENTER } from '../constants/mapDefaults';

/**
 * Exposes imperative map helpers for heatmap centering, fly-to-user, and route bounds.
 */
function MapApiBridge({ controllerRef, routes }) {
  const map = useMap();

  useImperativeHandle(
    controllerRef,
    () => ({
      getCenter() {
        const c = map.getCenter().wrap();
        return [c.lat, c.lng];
      },
      flyToUser(latlng, zoom = 15) {
        map.flyTo(latlng, zoom, { animate: true, duration: 1.25 });
      },
      fitRoutes() {
        const pts = [];
        (routes || []).forEach((r) => {
          (r.route_geometry || []).forEach((c) => pts.push([c.lat, c.lon]));
        });
        if (pts.length < 2) return;
        map.flyToBounds(L.latLngBounds(pts), { padding: [60, 60], maxZoom: 16, duration: 1.25, animate: true });
      },
    }),
    [map, routes]
  );

  return null;
}

/* ── Stable marker icons (created once, never re-allocated) ── */
function createSvgIcon(color, label) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="28" height="40" viewBox="0 0 28 40">
    <path d="M14 0C6.27 0 0 6.27 0 14c0 10.5 14 26 14 26s14-15.5 14-26C28 6.27 21.73 0 14 0z" fill="${color}"/>
    <circle cx="14" cy="14" r="6" fill="white"/>
    <text x="14" y="17" text-anchor="middle" fill="${color}" font-size="9" font-weight="700" font-family="Inter,sans-serif">${label}</text>
  </svg>`;
  return L.divIcon({
    html: svg,
    className: '',
    iconSize: [28, 40],
    iconAnchor: [14, 40],
    tooltipAnchor: [0, -40],
  });
}

const sourceIcon = createSvgIcon('#1A73E8', 'A');
const destIcon = createSvgIcon('#202124', 'B');

/** GPS / browser location — blue dot with pulse + subtle blink */
const userLocationIcon = L.divIcon({
  className: 'luma-user-location-icon',
  html: `
    <div class="luma-user-location-marker" aria-hidden="true">
      <span class="luma-user-location-pulse"></span>
      <span class="luma-user-location-core"></span>
    </div>
  `,
  iconSize: [48, 48],
  iconAnchor: [24, 24],
});

/* ── FitBounds — only fires when bounds reference actually changes ── */
function FitBounds({ bounds }) {
  const map = useMap();
  const prevBoundsRef = useRef(null);

  useEffect(() => {
    if (!bounds || bounds.length === 0) return;

    // Shallow compare to avoid re-fitting identical bounds
    const serialized = JSON.stringify(bounds);
    if (serialized === prevBoundsRef.current) return;
    prevBoundsRef.current = serialized;

    map.fitBounds(bounds, { padding: [60, 60], maxZoom: 16, animate: true, duration: 0.5 });
  }, [bounds, map]);

  return null;
}

/* ── MapClickHandler — crosshair cursor when in placing mode ── */
function MapClickHandler({ onMapClick, isPlacing }) {
  const map = useMap();

  useEffect(() => {
    const container = map.getContainer();
    if (isPlacing) {
      container.style.cursor = 'crosshair';
    } else {
      container.style.cursor = '';
    }
    return () => { container.style.cursor = ''; };
  }, [map, isPlacing]);

  useEffect(() => {
    if (!onMapClick) return;
    const handler = (e) => {
      const wrapped = e.latlng.wrap();
      onMapClick([wrapped.lat, wrapped.lng]);
    };
    map.on('click', handler);
    return () => map.off('click', handler);
  }, [map, onMapClick]);

  return null;
}

/* ── Individual polyline — memoized to prevent re-bindng event handlers ── */
const RoutePolyline = memo(function RoutePolyline({ route, isSelected, onSelect, travelLabel }) {
  const latlngs = useMemo(() => toLatLngs(route.route_geometry), [route.route_geometry]);
  const color = getModeColor(route.mode);

  // Stable pathOptions — only changes when isSelected toggles
  const pathOptions = useMemo(() => ({
    color,
    weight: isSelected ? 5 : 4,
    opacity: isSelected ? 0.9 : 0.6,
    dashArray: isSelected ? undefined : '1, 8',
    lineCap: 'round',
    lineJoin: 'round',
  }), [color, isSelected]);

  // Stable event handler ref — prevents Leaflet from rebinding on every render
  const handleClick = useCallback(() => onSelect(route.mode), [onSelect, route.mode]);
  const eventHandlers = useMemo(() => ({ click: handleClick }), [handleClick]);

  return (
    <Polyline
      positions={latlngs}
      pathOptions={pathOptions}
      eventHandlers={eventHandlers}
    >
      <Tooltip className="luma-tooltip" direction="top" sticky>
        <div className="flex flex-col gap-0.5">
          <span className="font-semibold" style={{ color }}>
            {route.mode.charAt(0).toUpperCase() + route.mode.slice(1)} · {travelLabel}
          </span>
          <span>ETA: {formatETA(route.estimated_time_seconds)}</span>
          <span>Safety: {formatSafetyPercent(route.average_safety_score)}</span>
        </div>
      </Tooltip>
    </Polyline>
  );
});

/**
 * MapView Component.
 *
 * Performance optimizations:
 *   - Each polyline is a memoized component with stable pathOptions/eventHandlers
 *   - FitBounds skips re-fitting if bounds haven't actually changed
 *   - Crosshair cursor applied via imperative DOM (not React re-render)
 */
const MapView = memo(function MapView({
  source,
  destination,
  systemLocation,
  routes,
  selectedRoute,
  onSelectRoute,
  onMapClick,
  isPlacing,
  children,
  mapControllerRef,
  travelProfile,
}) {
  const travelLabel = travelProfile === 'foot' ? 'Walk' : 'Drive';
  const defaultCenter = DEFAULT_MAP_CENTER;

  // Only recompute fitBounds when route data structurally changes
  const fitBounds = useMemo(() => {
    const selected = routes.find((r) => r.mode === selectedRoute);
    if (selected) return toLatLngs(selected.route_geometry);
    const pts = [];
    if (source) pts.push(source);
    if (destination) pts.push(destination);
    
    if (pts.length >= 2) return pts;

    // Center map roughly ~2km around the single point
    if (pts.length === 1 && routes.length === 0) {
      const p = pts[0];
      const offset = 0.02;
      return [
        [p[0] - offset, p[1] - offset],
        [p[0] + offset, p[1] + offset]
      ];
    }
    
    if (pts.length === 0 && systemLocation && routes.length === 0) {
      const offset = 0.02;
      return [
        [systemLocation[0] - offset, systemLocation[1] - offset],
        [systemLocation[0] + offset, systemLocation[1] + offset]
      ];
    }
    
    return null;
  }, [routes, selectedRoute, source, destination, systemLocation]);

  // Sort so selected route renders last (on top) — stable sort key
  const sortedRoutes = useMemo(() => {
    return [...routes].sort((a, b) => {
      if (a.mode === selectedRoute) return 1;
      if (b.mode === selectedRoute) return -1;
      return 0;
    });
  }, [routes, selectedRoute]);

  return (
    <MapContainer
      center={defaultCenter}
      zoom={14}
      className="w-full h-full"
      zoomControl={true}
    >
      <TileLayer
        attribution='&copy; <a href="https://carto.com/">CARTO</a>'
        url="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png"
      />

      {mapControllerRef && (
        <MapApiBridge controllerRef={mapControllerRef} routes={routes} />
      )}

      <MapClickHandler onMapClick={onMapClick} isPlacing={isPlacing} />
      {fitBounds && <FitBounds bounds={fitBounds} />}

      {sortedRoutes.map((route, idx) => (
        <RoutePolyline
          key={`${route.mode}-${idx}`}
          route={route}
          isSelected={route.mode === selectedRoute}
          onSelect={onSelectRoute}
          travelLabel={travelLabel}
        />
      ))}

      {source && (
        <Marker position={source} icon={sourceIcon}>
          <Tooltip className="luma-tooltip" direction="top" offset={[0, -40]} permanent={false}>
            Origin
          </Tooltip>
        </Marker>
      )}

      {destination && (
        <Marker position={destination} icon={destIcon}>
          <Tooltip className="luma-tooltip" direction="top" offset={[0, -40]} permanent={false}>
            Destination
          </Tooltip>
        </Marker>
      )}

      {systemLocation && systemLocation.length >= 2 && (
        <Marker
          position={systemLocation}
          icon={userLocationIcon}
          zIndexOffset={1000}
        >
          <Tooltip className="luma-tooltip" direction="top" offset={[0, -8]} permanent={false}>
            Your location
          </Tooltip>
        </Marker>
      )}

      {children}
    </MapContainer>
  );
});

export default MapView;
