import { memo, useMemo } from 'react';
import { MapContainer, TileLayer, Polyline, Marker } from 'react-leaflet';
import L from 'leaflet';
import { toLatLngs, getModeColor } from '../utils/formatters';

/**
 * MiniMapPIP — Picture-in-Picture map overlay for the live camera view.
 *
 * Shows the active route polyline and user's current location.
 * Non-interactive (no zoom controls, no click handlers).
 * Fixed 200×140px, rounded corners, semi-transparent border.
 */

/* GPS dot icon — smaller version for PIP */
const pipLocationIcon = L.divIcon({
  className: '',
  html: `<div style="width:10px;height:10px;border-radius:50%;background:#1a73e8;border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,0.3)"></div>`,
  iconSize: [10, 10],
  iconAnchor: [5, 5],
});

const MiniMapPIP = memo(function MiniMapPIP({ route, userLocation }) {
  const latlngs = useMemo(
    () => (route?.route_geometry ? toLatLngs(route.route_geometry) : []),
    [route]
  );

  const center = useMemo(() => {
    if (userLocation?.length >= 2) return userLocation;
    if (latlngs.length > 0) {
      const mid = latlngs[Math.floor(latlngs.length / 2)];
      return [mid[0], mid[1]];
    }
    return [12.97, 77.59]; // Fallback: Bangalore
  }, [userLocation, latlngs]);

  const bounds = useMemo(() => {
    if (latlngs.length >= 2) return latlngs;
    return null;
  }, [latlngs]);

  const modeColor = route ? getModeColor(route.mode) : '#1A73E8';

  return (
    <div
      style={{
        width: 200,
        height: 140,
        borderRadius: 16,
        overflow: 'hidden',
        border: '2px solid rgba(255,255,255,0.85)',
        boxShadow: '0 4px 20px rgba(0,0,0,0.3)',
        position: 'relative',
        pointerEvents: 'none', // Non-interactive
      }}
    >
      <MapContainer
        center={center}
        zoom={14}
        zoomControl={false}
        attributionControl={false}
        dragging={false}
        scrollWheelZoom={false}
        doubleClickZoom={false}
        touchZoom={false}
        keyboard={false}
        style={{ width: '100%', height: '100%' }}
        bounds={bounds}
        boundsOptions={{ padding: [15, 15] }}
      >
        <TileLayer
          url="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png"
        />

        {latlngs.length >= 2 && (
          <Polyline
            positions={latlngs}
            pathOptions={{
              color: modeColor,
              weight: 3,
              opacity: 0.9,
              lineCap: 'round',
            }}
          />
        )}

        {userLocation?.length >= 2 && (
          <Marker position={userLocation} icon={pipLocationIcon} />
        )}
      </MapContainer>

      {/* "Map Route" label */}
      <div
        style={{
          position: 'absolute',
          bottom: 6,
          left: '50%',
          transform: 'translateX(-50%)',
          background: 'rgba(0,0,0,0.55)',
          color: 'white',
          fontSize: 9,
          fontWeight: 700,
          padding: '3px 8px',
          borderRadius: 99,
          letterSpacing: '0.04em',
          textTransform: 'uppercase',
          whiteSpace: 'nowrap',
          pointerEvents: 'none',
        }}
      >
        Map Route
      </div>
    </div>
  );
});

export default MiniMapPIP;
