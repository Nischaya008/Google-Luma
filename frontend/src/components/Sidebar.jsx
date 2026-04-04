import { memo, useState, useMemo } from 'react';
import AddressAutocomplete from './AddressAutocomplete';
import { DEFAULT_MAP_CENTER } from '../constants/mapDefaults';
import { computeSearchBias } from '../utils/geo';
import MapFactsSlideshow from './MapFactsSlideshow';

const MODES = [
  {
    id: 'fastest',
    label: 'Fastest',
    sub: 'Min. time',
    color: '#1A73E8',
    bg: '#E8F0FE',
    border: '#C5D8F9',
    textColor: '#1557B0',
    icon: (active) => (
      <svg width="16" height="16" viewBox="0 0 24 24" fill={active ? 'white' : '#1557B0'}>
        <path d="M13 2.05v2.02c3.95.49 7 3.85 7 7.93 0 3.21-1.81 6-4.72 7.28L13 17v5l5-3.08C21.49 16.89 23 13.62 23 12c0-5.18-3.95-9.45-10-9.95zM11 2.05C4.95 2.55 1 6.82 1 12c0 1.62 1.51 4.89 5 6.92L11 22v-5l-2.28-1.72C6.81 14 5 11.21 5 8c0-4.08 3.05-7.44 7-7.95v2.02z" />
      </svg>
    ),
  },
  {
    id: 'balanced',
    label: 'Balanced',
    sub: 'Smart mix',
    color: '#F29900',
    bg: '#FEF3DC',
    border: '#FAD87A',
    textColor: '#8A5800',
    icon: (active) => (
      <svg width="16" height="16" viewBox="0 0 24 24" fill={active ? 'white' : '#8A5800'}>
        <path d="M12 3L1 9l4 2.18V15c0 3.31 3.13 5 7 5s7-1.69 7-5v-3.82L21 9 12 3zm2.45 11.19c-.47.44-1.3.81-2.45.81s-1.98-.37-2.45-.81L8.5 13h7l-1.05 1.19zM17 12.5l-5-2.73-5 2.73v-.73l5-2.73 5 2.73v.73z" />
      </svg>
    ),
  },
  {
    id: 'safest',
    label: 'Safest',
    sub: 'Max safety',
    color: '#1E8E3E',
    bg: '#E6F4EA',
    border: '#A8D5B5',
    textColor: '#145A2B',
    icon: (active) => (
      <svg width="16" height="16" viewBox="0 0 24 24" fill={active ? 'white' : '#145A2B'}>
        <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4zm-2 16l-4-4 1.41-1.41L10 14.17l6.59-6.59L18 9l-8 8z" />
      </svg>
    ),
  },
];

/**
 * RoutePanel sits fixed at bottom-0.  On desktop it is ~220px tall.
 * We offset the sidebar above it when in nav mode using md:bottom-[232px].
 */
const Sidebar = memo(function Sidebar({
  source,
  destination,
  selectedMode,
  travelProfile,
  loading,
  error,
  hasRoutes,
  onSetSource,
  onSetDestination,
  onSetSelectedMode,
  onSetSelectedRoute,
  onFindRoutes,
  onSetError,
  placingMarker,
  onSetPlacingMarker,
  mobileOpen,
  onToggleMobile,
  routes,
  /** [lat, lon] when browser GPS is known; null uses DEFAULT_MAP_CENTER for search bias */
  gpsCoords,
}) {
  const biasFrom = useMemo(
    () =>
      computeSearchBias({
        field: 'source',
        source,
        destination,
        gpsCoords: gpsCoords || null,
        defaultCenter: DEFAULT_MAP_CENTER,
      }),
    [source, destination, gpsCoords]
  );
  const biasTo = useMemo(
    () =>
      computeSearchBias({
        field: 'destination',
        source,
        destination,
        gpsCoords: gpsCoords || null,
        defaultCenter: DEFAULT_MAP_CENTER,
      }),
    [source, destination, gpsCoords]
  );

  const canSearch = source && destination && !loading;
  const currentStep = !source ? 1 : !destination ? 2 : 3;
  const [touchStartY, setTouchStartY] = useState(0);
  const [dragOffset, setDragOffset] = useState(0);

  const handleTouchStart = (e) => {
    setTouchStartY(e.touches[0].clientY);
    setDragOffset(0);
  };

  const handleTouchMove = (e) => {
    if (!touchStartY) return;
    const dy = e.touches[0].clientY - touchStartY;

    // Pulling up is negative dy, pulling down is positive
    if (!mobileOpen && dy < 0) {
      setDragOffset(dy);
    } else if (mobileOpen && dy > 0) {
      setDragOffset(dy);
    } else if (mobileOpen && dy < 0) {
      setDragOffset(dy * 0.15); // visual resistance
    }
  };

  const handleTouchEnd = (e) => {
    if (!touchStartY) return;
    const endY = e.changedTouches[0].clientY;
    const dy = endY - touchStartY;

    if (dy > 40 && mobileOpen) onToggleMobile();
    else if (dy < -40 && !mobileOpen) onToggleMobile();

    setTouchStartY(0);
    setDragOffset(0);
  };

  // nav mode: compact card sits above RoutePanel
  // landing mode: full card at bottom-left
  const desktopBottom = hasRoutes ? 'md:bottom-[214px]' : 'md:bottom-6';

  return (
    <>
      {/* Mobile backdrop */}
      {!hasRoutes && mobileOpen && (
        <div
          className="fixed inset-0 bg-black/25 z-[999] md:hidden"
          onClick={onToggleMobile}
        />
      )}

      <aside
        id="sidebar"
        className={hasRoutes
          // Nav mode: inside App's flex dock — just be a flex column filling width
          ? 'relative z-[1000] flex flex-col w-full'
          // Landing mode: absolute floating card
          : [
            'absolute z-[1000] flex flex-col',
            'bottom-0 left-0 right-0 max-h-[85vh] rounded-t-[22px] overflow-hidden',
            'md:right-auto md:bottom-1 md:left-5 md:w-[400px] md:rounded-[20px] md:max-h-[calc(100vh-48px)]',
          ].join(' ')
        }
        style={{
          background: '#FEFCF8',
          border: '1.5px solid #DDD5C8',
          borderRight: '1.5px solid #DDD5C8',
          borderTopRightRadius: hasRoutes ? 20 : undefined,
          borderBottomRightRadius: hasRoutes ? 0 : undefined,
          borderTopLeftRadius: hasRoutes ? 20 : undefined,
          boxShadow: '0 -4px 32px rgba(48,40,28,0.12), 0 -1px 6px rgba(48,40,28,0.05)',
          transform: !hasRoutes ? (mobileOpen ? `translateY(${Math.max(0, dragOffset)}px)` : `translateY(calc(100% - 90px + ${Math.min(0, dragOffset)}px))`) : 'none',
          transition: dragOffset ? 'none' : 'transform 400ms cubic-bezier(0.4,0,0.2,1), bottom 400ms cubic-bezier(0.4,0,0.2,1)',
        }}
        role="complementary"
        aria-label="Route controls"
      >
        <style>{`
          @media (min-width: 768px) {
            #sidebar { transform: translateY(0) !important; }
          }
        `}</style>
        {/* Header container with swipe handlers for mobile */}
        <div
          onTouchStart={handleTouchStart}
          onTouchMove={handleTouchMove}
          onTouchEnd={handleTouchEnd}
          className={hasRoutes && !mobileOpen ? "cursor-pointer" : ""}
          onClick={() => { if (hasRoutes && !mobileOpen) onToggleMobile(); }}
        >
          {/* Drag handle — mobile only */}
          <button
            className="w-full flex justify-center pt-4 pb-3 md:hidden shrink-0 cursor-pointer"
            onClick={onToggleMobile}
            aria-label="Toggle panel"
            style={{ WebkitTapHighlightColor: 'transparent' }}
          >
            <div style={{
              width: 44,
              height: 5,
              borderRadius: 99,
              background: '#A89F95',
              boxShadow: 'inset 0 1px 1px rgba(0,0,0,0.1)'
            }} />
          </button>

          {/* ── HEADER ── */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '4px 24px 16px', flexShrink: 0 }}>
            <img
              src="/maps_logo.png"
              alt="Google Maps"
              style={{ width: 38, height: 38, objectFit: 'contain', flexShrink: 0 }}
            />
            <div>
              <h1 style={{ fontSize: 18, fontWeight: 800, color: '#1C1917', letterSpacing: '-0.3px', lineHeight: 1.2 }}>
                Google Luma
              </h1>
              <p style={{ fontSize: 10, fontWeight: 600, color: '#9C9284', letterSpacing: '0.06em', textTransform: 'uppercase', marginTop: 2 }}>
                Safety-Aware Navigation
              </p>
              <p style={{ fontSize: 10, fontWeight: 700, color: travelProfile === 'foot' ? '#1E8E3E' : '#1A73E8', marginTop: 4, letterSpacing: '0.04em' }}>
                {travelProfile === 'foot' ? 'Walking routes' : 'Driving routes'}
              </p>
            </div>
          </div>
        </div>

        <div
          className="md:!max-h-[800px] md:!opacity-100"
          style={{
            maxHeight: hasRoutes ? (mobileOpen ? '70vh' : '0px') : '70vh',
            opacity: hasRoutes ? (mobileOpen ? 1 : 0) : 1,
            overflowX: 'hidden',
            overflowY: (hasRoutes && !mobileOpen) ? 'hidden' : 'auto',
            transition: dragOffset ? 'none' : 'max-height 400ms cubic-bezier(0.4,0,0.2,1), opacity 300ms ease',
            WebkitOverflowScrolling: 'touch',
          }}
        >
          {/* Divider */}
          <div style={{ height: 1, background: '#EAE4DC', margin: '0 24px' }} />

          {/* ── STEP PROGRESS — landing only ── */}
          {!hasRoutes && (
            <div style={{ padding: '12px 24px 6px' }}>
              <div style={{ display: 'flex', gap: 5, marginBottom: 8 }}>
                {[1, 2, 3].map((s) => (
                  <div
                    key={s}
                    style={{
                      flex: 1, height: 3, borderRadius: 99,
                      background: s < currentStep ? '#1E8E3E' : s === currentStep ? '#1A73E8' : '#E2DBD2',
                      transition: 'background 500ms',
                    }}
                  />
                ))}
              </div>
              <p style={{ fontSize: 11.5, color: '#6B6259', fontWeight: 500 }}>
                {currentStep === 1 && <><strong style={{ color: '#1A73E8' }}>Step 1</strong> of 3 — Set your starting point</>}
                {currentStep === 2 && <><strong style={{ color: '#1A73E8' }}>Step 2</strong> of 3 — Choose your destination</>}
                {currentStep === 3 && <><strong style={{ color: '#1E8E3E' }}>Step 3</strong> of 3 — Search your route</>}
              </p>
            </div>
          )}

          {/* ── ROUTE INPUTS ── */}
          <div style={{ padding: '10px 24px 0' }}>
            <div style={{
              background: 'white',
              borderRadius: 16,
              border: '1.5px solid #E2DBD2',
              padding: '4px 0',
              boxShadow: '0 1px 6px rgba(48,40,28,0.04)',
            }}>
              {/* FROM */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 14px' }}>
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flexShrink: 0, width: 18 }}>
                  <div style={{
                    width: 10, height: 10, borderRadius: '50%',
                    background: source ? '#1A73E8' : 'white',
                    border: source ? '2px solid #1A73E8' : '2px solid #B0A899',
                    transition: 'all 200ms',
                  }} />
                  <div style={{ width: 2, height: 22, background: '#DDD5C8', borderRadius: 2, marginTop: 3 }} />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 9.5, fontWeight: 700, color: '#9C9284', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 3 }}>
                    From
                  </div>
                  <AddressAutocomplete
                    placeholder="Where are you starting?"
                    value={source?.label || source?.coords || source}
                    onLocationSelect={(loc) => {
                      onSetSource(loc);
                      onSetPlacingMarker('destination');
                    }}
                    isActive={placingMarker === 'source'}
                    onClick={() => onSetPlacingMarker('source')}
                    searchBias={biasFrom}
                  />
                </div>
              </div>

              {/* Separator */}
              <div style={{ height: 1, background: '#F0EBE2', margin: '0 14px 0 42px' }} />

              {/* TO */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 14px' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: 18, flexShrink: 0 }}>
                  <div style={{
                    width: 10, height: 10, borderRadius: 3,
                    background: destination ? '#EA4335' : 'white',
                    border: destination ? '2px solid #EA4335' : '2px solid #B0A899',
                    transition: 'all 200ms',
                  }} />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 9.5, fontWeight: 700, color: '#9C9284', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 3 }}>
                    To
                  </div>
                  <AddressAutocomplete
                    placeholder="Where are you going?"
                    value={destination?.label || destination?.coords || destination}
                    onLocationSelect={(loc) => {
                      onSetDestination(loc);
                      onSetPlacingMarker(null);
                    }}
                    isActive={placingMarker === 'destination'}
                    onClick={() => onSetPlacingMarker('destination')}
                    searchBias={biasTo}
                  />
                </div>
              </div>
            </div>

            {/* Map tap hint */}
            {placingMarker && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 10, padding: '0 2px' }}>
                <span style={{ position: 'relative', display: 'flex', width: 9, height: 9, flexShrink: 0 }}>
                  <span style={{
                    position: 'absolute', inset: 0, borderRadius: '50%',
                    background: '#1A73E8', opacity: 0.4,
                    animation: 'ping 1.2s cubic-bezier(0,0,0.2,1) infinite',
                  }} />
                  <span style={{ width: 9, height: 9, borderRadius: '50%', background: '#1A73E8', position: 'relative' }} />
                </span>
                <p style={{ fontSize: 11.5, color: '#6B6259', fontWeight: 500 }}>
                  Tap the map to set your{' '}
                  <strong style={{ color: '#1A73E8', fontWeight: 700 }}>{placingMarker}</strong>
                </p>
              </div>
            )}
          </div>

          {/* ── Map trivia slideshow (replaces route-priority cards on landing) ── */}
          {!hasRoutes && (
            <div style={{ padding: '14px 24px 0' }}>
              <MapFactsSlideshow />
            </div>
          )}

          {/* ── MODE PILLS — nav ── */}
          {hasRoutes && (
            <div style={{ padding: '12px 24px 0' }}>
              <div style={{ display: 'flex', gap: 7 }}>
                {(() => {
                  const uniqueGroups = [];
                  (routes || []).forEach(r => {
                    let match = uniqueGroups.find(g =>
                      Math.abs(g.time - r.estimated_time_seconds) <= 60 &&
                      Math.abs(g.safety - r.average_safety_score) <= 0.03
                    );
                    if (match) {
                      match.modes.push(r.mode);
                    } else {
                      uniqueGroups.push({
                        time: r.estimated_time_seconds,
                        safety: r.average_safety_score,
                        modes: [r.mode]
                      });
                    }
                  });

                  return uniqueGroups.map(group => {
                    const primaryModeId = group.modes[0];
                    const baseModeDef = MODES.find(m => m.id === primaryModeId);

                    let combinedLabel = group.modes.map(m => MODES.find(def => def.id === m)?.label).join(' & ');
                    if (group.modes.length === 3) combinedLabel = "Fastest, Balanced & Safest";

                    const isActive = group.modes.includes(selectedMode);

                    return (
                      <button
                        key={primaryModeId}
                        id={`mode-pill-${primaryModeId}`}
                        onClick={() => {
                          onSetSelectedMode(primaryModeId);
                          if (onSetSelectedRoute) onSetSelectedRoute(primaryModeId);
                        }}
                        style={{
                          flex: 1,
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          gap: 5,
                          padding: '8px 4px',
                          borderRadius: 99,
                          border: `1.5px solid ${isActive ? baseModeDef.color : '#DDD5C8'}`,
                          background: isActive ? baseModeDef.color : 'white',
                          cursor: 'pointer',
                          fontSize: 12,
                          fontWeight: 700,
                          color: isActive ? 'white' : baseModeDef.textColor,
                          transition: 'all 200ms',
                          boxShadow: isActive ? `0 3px 10px ${baseModeDef.color}40` : 'none',
                          letterSpacing: '-0.01em',
                        }}
                        aria-pressed={isActive}
                      >
                        {baseModeDef.icon(isActive)}
                        {combinedLabel}
                      </button>
                    );
                  });
                })()}
              </div>
            </div>
          )}

          {/* ── SEARCH CTA — landing ── */}
          {!hasRoutes && (
            <div style={{ padding: '16px 24px 18px' }}>
              <button
                id="btn-find-route"
                onClick={onFindRoutes}
                disabled={!canSearch}
                style={{
                  width: '100%',
                  padding: '15px 24px',
                  borderRadius: 14,
                  border: 'none',
                  background: canSearch ? '#1A73E8' : '#E8E2D9',
                  color: canSearch ? 'white' : '#A89F95',
                  fontSize: 14,
                  fontWeight: 700,
                  letterSpacing: '0.01em',
                  cursor: canSearch ? 'pointer' : 'not-allowed',
                  transition: 'all 250ms',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 9,
                  boxShadow: canSearch ? '0 3px 14px rgba(26,115,232,0.35)' : 'none',
                }}
                aria-label="Compute Safe Route"
              >
                {loading ? (
                  <>
                    <svg className="animate-spin" width="17" height="17" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
                    </svg>
                    Computing routes…
                  </>
                ) : (
                  <>
                    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <circle cx="11" cy="11" r="7" />
                      <line x1="21" y1="21" x2="16.65" y2="16.65" />
                    </svg>
                    Compute Safe Route
                  </>
                )}
              </button>
            </div>
          )}

          {/* ── SEARCH CTA — nav ── */}
          {hasRoutes && (
            <div style={{ padding: '12px 24px 18px' }}>
              <button
                id="btn-update-route"
                onClick={onFindRoutes}
                disabled={!canSearch || loading}
                style={{
                  width: '100%',
                  padding: '10px 16px',
                  borderRadius: 12,
                  border: 'none',
                  background: canSearch && !loading ? '#1A73E8' : '#E8E2D9',
                  color: canSearch && !loading ? 'white' : '#A89F95',
                  fontSize: 13,
                  fontWeight: 700,
                  letterSpacing: '0.01em',
                  cursor: canSearch && !loading ? 'pointer' : 'not-allowed',
                  transition: 'all 250ms',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 8,
                  boxShadow: canSearch && !loading ? '0 2px 8px rgba(26,115,232,0.25)' : 'none',
                }}
                aria-label="Update route"
              >
                {loading ? (
                  <>
                    <svg className="animate-spin" width="15" height="15" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
                    </svg>
                    Updating…
                  </>
                ) : (
                  <>
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M21.5 2v6h-6M2 22v-6h6M21.34 15.57a10 10 0 1 1-.92-10.42L21.5 8M2.66 8.43a10 10 0 1 1 .92 10.42L2.5 16" />
                    </svg>
                    Update Route
                  </>
                )}
              </button>
            </div>
          )}

          {/* ── ERROR ── */}
          {error && (
            <div
              style={{
                margin: '0 24px 16px',
                padding: '12px 14px',
                borderRadius: 12,
                background: '#FFF0EE',
                border: '1.5px solid #FAC5C1',
                color: '#C5221F',
                fontSize: 12.5,
                fontWeight: 500,
                display: 'flex',
                alignItems: 'flex-start',
                gap: 9,
              }}
              role="alert"
            >
              <svg style={{ width: 15, height: 15, marginTop: 1, flexShrink: 0 }} viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z" />
              </svg>
              {error}
            </div>
          )}

          {/* ── FOOTER — landing ── */}
          {!hasRoutes && (
            <div style={{
              borderTop: '1px solid #EAE4DC',
              padding: '10px 24px',
              textAlign: 'center',
              fontSize: 9.5,
              color: '#B8B0A4',
              fontWeight: 600,
              letterSpacing: '0.07em',
              textTransform: 'uppercase',
              flexShrink: 0,
            }}>
              Powered by PredictXGB · OSMnx
            </div>
          )}
        </div>
      </aside>
    </>
  );
});

export default Sidebar;
