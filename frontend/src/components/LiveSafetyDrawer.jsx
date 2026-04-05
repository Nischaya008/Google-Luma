import { memo, useState } from 'react';

const SUN_ICON = (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line></svg>
);

const PEOPLE_ICON = (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg>
);

const CAR_ICON = (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><rect x="1" y="9" width="22" height="10" rx="2" ry="2"></rect><circle cx="6.5" cy="19.5" r="1.5"></circle><circle cx="17.5" cy="19.5" r="1.5"></circle><path d="M2 9v-2a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v2"></path></svg>
);

const INFRA_ICON = (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><rect x="8" y="2" width="8" height="20" rx="2" ry="2"></rect><circle cx="12" cy="7" r="2"></circle><circle cx="12" cy="12" r="2"></circle><circle cx="12" cy="17" r="2"></circle></svg>
);

/**
 * LiveSafetyDrawer — Bottom drawer for the camera safety view.
 *
 * Matches the existing Sidebar drawer UX with swipe-up/down.
 * Shows real-time safety score, feature breakdown, and AI explanation.
 */
const LiveSafetyDrawer = memo(function LiveSafetyDrawer({
  cvScore,
  finalScore,
  explanation,
  isAnomaly,
  anomalyLabel,
  features,
  analyzing,
  frameCount,
}) {
  const [expanded, setExpanded] = useState(false);
  const [touchStartY, setTouchStartY] = useState(0);
  const [dragOffset, setDragOffset] = useState(0);

  const handleTouchStart = (e) => {
    setTouchStartY(e.touches[0].clientY);
    setDragOffset(0);
  };

  const handleTouchMove = (e) => {
    if (!touchStartY) return;
    const dy = e.touches[0].clientY - touchStartY;
    if (!expanded && dy < 0) setDragOffset(dy);
    else if (expanded && dy > 0) setDragOffset(dy);
    else if (expanded && dy < 0) setDragOffset(dy * 0.15);
  };

  const handleTouchEnd = (e) => {
    if (!touchStartY) return;
    const dy = e.changedTouches[0].clientY - touchStartY;
    if (dy > 40 && expanded) setExpanded(false);
    else if (dy < -40 && !expanded) setExpanded(true);
    setTouchStartY(0);
    setDragOffset(0);
  };

  const displayScore = finalScore != null ? Math.round(finalScore * 100) : null;
  const cvDisplayScore = cvScore != null ? Math.round(cvScore * 100) : null;

  // Color based on score
  const scoreColor =
    displayScore == null
      ? '#9C9284'
      : displayScore >= 70
        ? '#1E8E3E'
        : displayScore >= 45
          ? '#F29900'
          : '#EA4335';

  return (
    <div
      className="live-safety-drawer"
      style={{
        position: 'absolute',
        bottom: 0,
        left: 0,
        right: 0,
        zIndex: 1100,
        background: '#FEFCF8',
        borderTop: '1.5px solid #DDD5C8',
        borderTopLeftRadius: 22,
        borderTopRightRadius: 22,
        boxShadow: '0 -4px 32px rgba(48,40,28,0.18)',
        transform: expanded
          ? `translateY(${Math.max(0, dragOffset)}px)`
          : `translateY(calc(100% - 85px + ${Math.min(0, dragOffset)}px))`,
        transition: dragOffset
          ? 'none'
          : 'transform 400ms cubic-bezier(0.4,0,0.2,1)',
        maxHeight: '70vh',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* Drag handle + header */}
      <div
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
        onClick={() => setExpanded((p) => !p)}
        style={{ cursor: 'pointer', flexShrink: 0 }}
      >
        {/* Drag bar */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'center',
            paddingTop: 12,
            paddingBottom: 8,
          }}
        >
          <div
            style={{
              width: 44,
              height: 5,
              borderRadius: 99,
              background: '#A89F95',
              boxShadow: 'inset 0 1px 1px rgba(0,0,0,0.1)',
            }}
          />
        </div>

        {/* Branding + live score header */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '0 20px 12px',
          }}
        >
          {/* Logo + title */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <img
              src="/maps_logo.png"
              alt="Google Luma"
              style={{
                width: 32,
                height: 32,
                objectFit: 'contain',
                flexShrink: 0,
              }}
            />
            <div>
              <h2
                style={{
                  fontSize: 15,
                  fontWeight: 800,
                  color: '#1C1917',
                  letterSpacing: '-0.2px',
                  lineHeight: 1.2,
                }}
              >
                Google Luma
              </h2>
              <p
                style={{
                  fontSize: 9,
                  fontWeight: 600,
                  color: '#9C9284',
                  letterSpacing: '0.06em',
                  textTransform: 'uppercase',
                  marginTop: 1,
                }}
              >
                Live Safety Scoring
              </p>
            </div>
          </div>

          {/* Live score badge */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '6px 14px',
              borderRadius: 99,
              background: `${scoreColor}15`,
              border: `1.5px solid ${scoreColor}40`,
            }}
          >
            {analyzing && (
              <div className="live-safety-pulse" style={{ background: scoreColor }} />
            )}
            <span
              style={{
                fontSize: 22,
                fontWeight: 800,
                color: scoreColor,
                letterSpacing: '-0.5px',
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {displayScore != null ? `${displayScore}%` : '—'}
            </span>
          </div>
        </div>

        {/* Anomaly alert banner */}
        {isAnomaly && anomalyLabel && (
          <div
            className="live-safety-anomaly-alert"
            style={{
              margin: '0 16px 10px',
              padding: '10px 14px',
              borderRadius: 12,
              background: '#FDE8E7',
              border: '1.5px solid #F5A9A5',
              display: 'flex',
              alignItems: 'center',
              gap: 8,
            }}
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="#EA4335"
              style={{ flexShrink: 0 }}
            >
              <path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z" />
            </svg>
            <span
              style={{
                fontSize: 12,
                fontWeight: 700,
                color: '#C5221F',
                lineHeight: 1.3,
              }}
            >
              {anomalyLabel}
            </span>
          </div>
        )}
      </div>

      {/* Expandable content */}
      <div
        style={{
          overflowY: expanded ? 'auto' : 'hidden',
          maxHeight: expanded ? '50vh' : 0,
          opacity: expanded ? 1 : 0,
          transition: dragOffset
            ? 'none'
            : 'max-height 400ms cubic-bezier(0.4,0,0.2,1), opacity 300ms ease',
          padding: expanded ? '0 20px 20px' : '0 20px',
        }}
      >
        {/* Divider */}
        <div
          style={{ height: 1, background: '#EAE4DC', marginBottom: 14 }}
        />

        {/* AI Explanation */}
        <div
          style={{
            padding: '12px 14px',
            borderRadius: 12,
            background: 'linear-gradient(to right, #F8FAFC, #FFFFFF)',
            border: `1.5px solid ${scoreColor}30`,
            boxShadow: `0 2px 8px ${scoreColor}10`,
            marginBottom: 14,
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              marginBottom: 6,
            }}
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill={scoreColor}
            >
              <path d="M19 3l-1.4 3.1L14.5 7.5l3.1 1.4L19 12l1.4-3.1L23.5 7.5l-3.1-1.4L19 3zm-7 3L8.5 12.5 2 16l6.5 3.5L12 26l3.5-6.5L22 16l-6.5-3.5L12 6z" />
            </svg>
            <span
              style={{
                fontSize: 10,
                fontWeight: 800,
                color: scoreColor,
                letterSpacing: '0.04em',
                textTransform: 'uppercase',
              }}
            >
              AI Explanation
            </span>
          </div>
          <p
            style={{
              fontSize: 12,
              color: '#3C4043',
              fontWeight: 500,
              lineHeight: 1.55,
              margin: 0,
            }}
          >
            {explanation || 'Waiting for camera feed analysis…'}
          </p>
        </div>

        {/* Feature chips */}
        <div
          style={{
            display: 'flex',
            gap: 8,
            flexWrap: 'wrap',
            marginBottom: 14,
          }}
        >
          <FeatureChip
            icon={SUN_ICON}
            label="Brightness"
            value={
              features
                ? `${Math.round(features.brightness * 100)}%`
                : '—'
            }
            color={
              features?.brightness >= 0.6
                ? '#1E8E3E'
                : features?.brightness >= 0.3
                  ? '#F29900'
                  : '#EA4335'
            }
          />
          <FeatureChip
            icon={PEOPLE_ICON}
            label="People"
            value={features ? `${features.crowdCount}` : '—'}
            color={
              features?.crowdCount >= 3
                ? '#1E8E3E'
                : features?.crowdCount >= 1
                  ? '#F29900'
                  : '#EA4335'
            }
          />
          <FeatureChip
            icon={CAR_ICON}
            label="Vehicles"
            value={features ? `${features.vehicleCount}` : '—'}
            color={
              features?.vehicleCount >= 2
                ? '#1E8E3E'
                : features?.vehicleCount >= 1
                  ? '#F29900'
                  : '#6B6259'
            }
          />
          <FeatureChip
            icon={INFRA_ICON}
            label="Infrastructure"
            value={features ? `${features.infraCount}` : '—'}
            color={features?.infraCount >= 1 ? '#1E8E3E' : '#6B6259'}
          />
        </div>

        {/* Score breakdown */}
        <div style={{ marginBottom: 10 }}>
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              marginBottom: 4,
            }}
          >
            <span
              style={{
                fontSize: 9.5,
                fontWeight: 700,
                color: '#9C9284',
                textTransform: 'uppercase',
                letterSpacing: '0.08em',
              }}
            >
              Live Safety Level
            </span>
            <span
              style={{
                fontSize: 10.5,
                fontWeight: 700,
                color: scoreColor,
              }}
            >
              {displayScore != null ? `${displayScore}% safe` : '—'}
            </span>
          </div>
          <div
            style={{
              height: 5,
              borderRadius: 99,
              background: '#EAE4DC',
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                height: '100%',
                borderRadius: 99,
                width: `${displayScore ?? 0}%`,
                background: `linear-gradient(90deg, ${scoreColor}80, ${scoreColor})`,
                transition: 'width 700ms ease-out',
              }}
            />
          </div>
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              marginTop: 3,
            }}
          >
            <span style={{ fontSize: 9, color: '#EA4335', fontWeight: 600 }}>
              Low
            </span>
            <span style={{ fontSize: 9, color: '#F29900', fontWeight: 600 }}>
              Moderate
            </span>
            <span style={{ fontSize: 9, color: '#1E8E3E', fontWeight: 600 }}>
              High
            </span>
          </div>
        </div>

        {/* CV vs Route score breakdown */}
        {cvDisplayScore != null && (
          <div
            style={{
              display: 'flex',
              gap: 8,
              marginTop: 10,
            }}
          >
            <ScoreCard
              label="CV Score"
              value={`${cvDisplayScore}%`}
              sub="Camera analysis"
              color="#1A73E8"
            />
            <ScoreCard
              label="Blended"
              value={`${displayScore}%`}
              sub="70% ML + 30% CV"
              color={scoreColor}
            />
            <ScoreCard
              label="Frames"
              value={`${frameCount}`}
              sub="Analyzed"
              color="#6B6259"
            />
          </div>
        )}
      </div>
    </div>
  );
});

function FeatureChip({ icon, label, value, color }) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 5,
        padding: '5px 10px',
        borderRadius: 99,
        background: `${color}12`,
        border: `1px solid ${color}30`,
        fontSize: 11,
        fontWeight: 600,
        color: color,
        whiteSpace: 'nowrap',
      }}
    >
      <span style={{ fontSize: 13 }}>{icon}</span>
      <span style={{ color: '#6B6259', fontWeight: 500 }}>{label}:</span>
      <span>{value}</span>
    </div>
  );
}

function ScoreCard({ label, value, sub, color }) {
  return (
    <div
      style={{
        flex: 1,
        padding: '8px 10px',
        borderRadius: 12,
        background: 'white',
        border: '1.5px solid #EAE4DC',
        textAlign: 'center',
      }}
    >
      <p
        style={{
          fontSize: 9,
          fontWeight: 700,
          color: '#9C9284',
          textTransform: 'uppercase',
          letterSpacing: '0.06em',
          marginBottom: 2,
        }}
      >
        {label}
      </p>
      <p
        style={{
          fontSize: 18,
          fontWeight: 800,
          color: color,
          letterSpacing: '-0.3px',
          lineHeight: 1.1,
        }}
      >
        {value}
      </p>
      <p
        style={{
          fontSize: 9,
          color: '#9C9284',
          fontWeight: 500,
          marginTop: 2,
        }}
      >
        {sub}
      </p>
    </div>
  );
}

export default LiveSafetyDrawer;
