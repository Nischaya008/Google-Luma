import { useEffect, useMemo, memo } from 'react';
import { useMap } from 'react-leaflet';
import L from 'leaflet';
import { safetyToColor } from '../utils/formatters';

/**
 * HeatmapLayer — memoized, imperative Leaflet layer.
 *
 * Performance: builds one L.layerGroup with all polylines using raw Leaflet API.
 * No React nodes for individual edges (would be 2000+ components otherwise).
 */
const HeatmapLayer = memo(function HeatmapLayer({ heatmapData, visible }) {
  const map = useMap();

  const layerGroup = useMemo(() => {
    if (!heatmapData?.edges) return null;

    const group = L.layerGroup();

    for (const edge of heatmapData.edges) {
      if (!edge.geometry || edge.geometry.length < 2) continue;

      const latlngs = edge.geometry.map((c) => [c[0], c[1]]);
      const color = safetyToColor(edge.safety_score);
      const pct = Math.round(edge.safety_score * 100);

      const line = L.polyline(latlngs, {
        color,
        weight: 3,
        opacity: 0.55,
        lineCap: 'round',
      });

      line.bindTooltip(
        `<div style="font-family:Inter,sans-serif;font-size:12px">Safety: <b>${pct}%</b></div>`,
        { className: 'luma-tooltip', direction: 'top', sticky: true }
      );

      // Hover effect — thicken line on mouseover
      line.on('mouseover', function () { this.setStyle({ weight: 5, opacity: 0.85 }); });
      line.on('mouseout', function () { this.setStyle({ weight: 3, opacity: 0.55 }); });

      group.addLayer(line);
    }

    return group;
  }, [heatmapData]);

  useEffect(() => {
    if (!layerGroup || !map) return;

    if (visible) {
      layerGroup.addTo(map);
    } else {
      map.removeLayer(layerGroup);
    }

    return () => { map.removeLayer(layerGroup); };
  }, [layerGroup, visible, map]);

  return null;
});

export default HeatmapLayer;
