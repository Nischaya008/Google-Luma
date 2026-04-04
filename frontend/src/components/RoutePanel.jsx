import { useMemo, memo } from 'react';
import { formatETA, formatSafetyPercent, getModeColor, getModeLabel, safetyToColor } from '../utils/formatters';

const SHIELD_ICON = (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
    <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z" />
  </svg>
);
const CLOCK_ICON = (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
    <path d="M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zM12 20c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8zm.5-13H11v6l5.25 3.15.75-1.23-4.5-2.67V7z" />
  </svg>
);
const ROUTE_ICON = (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
    <path d="M21 3L3 10.53v.98l6.84 2.65L12.48 21h.98L21 3z" />
  </svg>
);
const WARN_ICON = (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor">
    <path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z" />
  </svg>
);
const CHECK_ICON = (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor">
    <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z" />
  </svg>
);
const STAR_ICON = (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor">
    <path d="M12 17.27L18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21z" />
  </svg>
);

/**
 * RoutePanel — shows meaningful info about the CURRENTLY SELECTED route.
 * Mode switching is done by the Sidebar, not here.
 */
const RoutePanel = memo(function RoutePanel({
  routes,
  selectedRoute,
  tradeoffs,
  loading,
  onSelectRoute,
  travelLabel,
}) {
  const route = useMemo(
    () => routes.find(r => r.mode === selectedRoute) || routes[0],
    [routes, selectedRoute]
  );

  const fastestRoute = useMemo(() => routes.find(r => r.mode === 'fastest'), [routes]);
  const tradeoff = tradeoffs?.[selectedRoute];

  // Loading skeleton
  if (loading) {
    return (
      <div id="route-panel" style={panelStyle}>
        <div style={{ display: 'flex', gap: 16, width: '100%' }}>
          {[1, 2, 3, 4].map(i => (
            <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div style={skeletonStyle(14, '60%')} />
              <div style={skeletonStyle(22, '80%')} />
              <div style={skeletonStyle(8, '100%', true)} />
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (!route || routes.length === 0) return null;

  const modeColor = getModeColor(route.mode);
  const safetyPct = Math.round(route.average_safety_score * 100);
  const isFastest = route.mode === 'fastest';
  const isSafest = route.mode === 'safest';
  const timeDelta = tradeoff?.time_penalty_seconds;
  const safetyGain = tradeoff?.safety_gain_absolute;
  const safetyGainPct = Math.round((safetyGain ?? 0) * 100);

  // Qualitative safety label
  const safetyLabel = safetyPct >= 80 ? 'High Safety' : safetyPct >= 60 ? 'Moderate Safety' : 'Low Safety';
  const safetyLabelColor = safetyPct >= 80 ? '#1E8E3E' : safetyPct >= 60 ? '#F29900' : '#EA4335';

  // Check if we have multiple distinct physical routes
  const hasMultipleTabs = useMemo(() => {
    const groups = [];
    (routes || []).forEach(r => {
      let match = groups.find(g =>
        Math.abs(g.estimated_time_seconds - r.estimated_time_seconds) <= 60 &&
        Math.abs(g.average_safety_score - r.average_safety_score) <= 0.03
      );
      if (!match) groups.push(r);
    });
    return groups.length > 1;
  }, [routes]);

  // Real distance from OSRM (km)
  const estimatedKm = route.distance_meters
    ? (route.distance_meters / 1000).toFixed(1)
    : null;

  return (
    <div id="route-panel" style={panelStyle}>

      {/* ── Section header ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, flexShrink: 0 }}>
        <div style={{
          width: 26, height: 26, borderRadius: 8,
          background: `${modeColor}18`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: modeColor, flexShrink: 0,
        }}>
          {SHIELD_ICON}
        </div>
        <div>
          <h2 style={{ fontSize: 13, fontWeight: 800, color: '#1C1917', letterSpacing: '-0.1px', lineHeight: 1.2 }}>
            {(() => {
              const sharedModes = routes.filter(r =>
                Math.abs(r.estimated_time_seconds - route.estimated_time_seconds) <= 60 &&
                Math.abs(r.average_safety_score - route.average_safety_score) <= 0.03
              ).map(r => r.mode);
              let combinedLabel = sharedModes.map(getModeLabel).join(' & ');
              if (sharedModes.length === 3) combinedLabel = "Fastest, Balanced & Safest";
              return combinedLabel;
            })()} · {travelLabel || 'Drive'}
          </h2>
          <p style={{ fontSize: 10, color: '#9C9284', fontWeight: 500, marginTop: 1 }}>
            Safety analysis for your selected path
          </p>
        </div>
      </div>

      {/* ── Stats row ── */}
      <div className="flex overflow-x-auto snap-x snap-mandatory pb-2 -mx-4 px-4 md:mx-0 md:px-0 luma-scrollbar" style={{ gap: 12, flexShrink: 0 }}>
        <style>{`.luma-scrollbar::-webkit-scrollbar { display: none; } .luma-scrollbar { scrollbar-width: none; }`}</style>

        {/* Stat card: Travel time */}
        <StatCard
          icon={CLOCK_ICON}
          iconColor="#1A73E8"
          iconBg="#E8F0FE"
          label="Travel Time"
          value={formatETA(route.estimated_time_seconds)}
          sub={
            !isFastest && timeDelta > 0
              ? `+${Math.round(timeDelta)}s vs fastest`
              : 'Shortest possible'
          }
          subColor={!isFastest && timeDelta > 0 ? '#F29900' : '#1E8E3E'}
        />

        {/* Stat card: Safety score */}
        <StatCard
          icon={SHIELD_ICON}
          iconColor={safetyLabelColor}
          iconBg={`${safetyLabelColor}18`}
          label="Safety Score"
          value={formatSafetyPercent(route.average_safety_score)}
          sub={safetyLabel}
          subColor={safetyLabelColor}
          progress={safetyPct}
          progressColor={modeColor}
        />

        {/* Stat card: Distance estimate */}
        {estimatedKm && (
          <StatCard
            icon={ROUTE_ICON}
            iconColor="#6B6259"
            iconBg="#F0EBE2"
            label="Est. Distance"
            value={`${estimatedKm} km`}
            sub="Actual road distance"
            subColor="#9C9284"
          />
        )}

        {/* Stat card: Safety gain vs fastest */}
        {hasMultipleTabs && !isFastest && safetyGain != null && (
          <StatCard
            icon={isSafest ? STAR_ICON : CHECK_ICON}
            iconColor={modeColor}
            iconBg={`${modeColor}18`}
            label="Safety Gain"
            value={`${safetyGainPct >= 0 ? '+' : ''}${safetyGainPct}%`}
            sub="vs fastest route"
            subColor={modeColor}
          />
        )}
        {hasMultipleTabs && isFastest && (
          <StatCard
            icon={WARN_ICON}
            iconColor="#EA4335"
            iconBg="#FDE8E7"
            label="Safety Tradeoff"
            value="—"
            sub="Switch to Safest for protection"
            subColor="#EA4335"
          />
        )}
      </div>

      {/* ── Safety bar ── */}
      <div style={{ marginTop: 10, flexShrink: 0 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
          <span style={{ fontSize: 9.5, fontWeight: 700, color: '#9C9284', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            Route Safety Level
          </span>
          <span style={{ fontSize: 10.5, fontWeight: 700, color: modeColor }}>{safetyPct}% safe</span>
        </div>
        <div style={{ height: 5, borderRadius: 99, background: '#EAE4DC', overflow: 'hidden' }}>
          <div style={{
            height: '100%', borderRadius: 99,
            width: `${safetyPct}%`,
            background: `linear-gradient(90deg, ${safetyLabelColor}80, ${modeColor})`,
            transition: 'width 700ms ease-out',
          }} />
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 3 }}>
          <span style={{ fontSize: 9, color: '#EA4335', fontWeight: 600 }}>Low</span>
          <span style={{ fontSize: 9, color: '#F29900', fontWeight: 600 }}>Moderate</span>
          <span style={{ fontSize: 9, color: '#1E8E3E', fontWeight: 600 }}>High</span>
        </div>
      </div>

      {/* ── AI Insight callout ── */}
      <div className="hidden md:flex" style={{
        marginTop: 10,
        padding: '10px 14px',
        borderRadius: 12,
        background: 'linear-gradient(to right, #F8FAFC, #FFFFFF)',
        border: `1.5px solid ${modeColor}40`,
        boxShadow: `0 2px 8px ${modeColor}10`,
        alignItems: 'flex-start', gap: 10,
        flexShrink: 0,
      }}>
        <div style={{ color: modeColor, marginTop: 2, flexShrink: 0 }}>
          {/* Minimal Sparkle Icon for AI */}
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
            <path d="M19 3l-1.4 3.1L14.5 7.5l3.1 1.4L19 12l1.4-3.1L23.5 7.5l-3.1-1.4L19 3zm-7 3L8.5 12.5 2 16l6.5 3.5L12 26l3.5-6.5L22 16l-6.5-3.5L12 6z" />
          </svg>
        </div>
        <div style={{ flex: 1 }}>
          <p style={{ fontSize: 11, color: '#1A73E8', fontWeight: 800, marginBottom: 3, letterSpacing: '0.02em', textTransform: 'uppercase' }}>
            AI Evaluation
          </p>
          <p style={{ fontSize: 11.5, color: '#3C4043', fontWeight: 500, lineHeight: 1.5, letterSpacing: '-0.1px' }}>
            {route.ai_insight ? route.ai_insight :
              (isSafest ? `Prioritizes well-lit, low-risk roads. Avg safety: ${safetyPct}%. Recommended for night travel.` :
                isFastest ? `Quickest path but may pass lower-safety zones. ${safetyGain ? 'Switch to Safest for +' + Math.round(safetyGain * 100) + '% protection.' : 'Consider Safest for better protection.'}` :
                  `Balanced: saves ${timeDelta ? Math.round(timeDelta) + 's' : 'time'} vs Safest while keeping ${safetyPct}% safety — a smart everyday choice.`
              )
            }
          </p>
        </div>
      </div>
    </div>
  );
});

// ── Sub-component: individual stat card ──
function StatCard({ icon, iconColor, iconBg, label, value, sub, subColor, progress, progressColor }) {
  return (
    <div className="flex-1 min-w-[130px] md:min-w-0 snap-start" style={{
      padding: '8px 10px',
      borderRadius: 12,
      background: 'white',
      border: '1.5px solid #EAE4DC',
      display: 'flex', flexDirection: 'column', gap: 2,
      boxShadow: '0 1px 3px rgba(48,40,28,0.04)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 1 }}>
        <div style={{
          width: 20, height: 20, borderRadius: 6,
          background: iconBg, color: iconColor,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          flexShrink: 0,
        }}>
          {icon}
        </div>
        <span style={{ fontSize: 9, fontWeight: 700, color: '#9C9284', textTransform: 'uppercase', letterSpacing: '0.07em' }}>
          {label}
        </span>
      </div>
      <span style={{ fontSize: 17, fontWeight: 800, color: '#1C1917', letterSpacing: '-0.3px', lineHeight: 1.1 }}>
        {value}
      </span>
      {progress != null && (
        <div style={{ height: 2.5, borderRadius: 99, background: '#EAE4DC', margin: '1px 0', overflow: 'hidden' }}>
          <div style={{ height: '100%', width: `${progress}%`, borderRadius: 99, background: progressColor, transition: 'width 600ms' }} />
        </div>
      )}
      <span style={{ fontSize: 9.5, fontWeight: 600, color: subColor, lineHeight: 1.3 }}>{sub}</span>
    </div>
  );
}

// ── Styles helpers ──
const panelStyle = {
  position: 'relative',
  background: 'rgba(254,252,248,0.97)',
  backdropFilter: 'blur(16px)',
  borderTop: '1.5px solid #DDD5C8',
  padding: '12px 16px 14px',
  display: 'flex',
  flexDirection: 'column',
  boxShadow: '0 -4px 24px rgba(48,40,28,0.08)',
  boxSizing: 'border-box',
  borderTopRightRadius: 20,
  borderBottomRightRadius: 0,
  borderTopLeftRadius: 0,
  height: '100%',
};

function skeletonStyle(h, w, full) {
  return {
    height: h,
    width: full ? '100%' : w,
    borderRadius: 6,
    background: 'linear-gradient(90deg, #EDE9E1 25%, #E2DDD5 50%, #EDE9E1 75%)',
    backgroundSize: '200% 100%',
    animation: 'shimmer 1.4s ease-in-out infinite',
  };
}

export default RoutePanel;
