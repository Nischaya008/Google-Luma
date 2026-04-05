import { memo, useMemo } from 'react';
import useLiveSafety from '../hooks/useLiveSafety';
import MiniMapPIP from './MiniMapPIP';
import LiveSafetyDrawer from './LiveSafetyDrawer';

/**
 * LiveSafetyView — Full-screen mobile camera safety analysis view.
 *
 * Layout (matching the wireframe):
 *   ┌────────────────────────────────┐
 *   │ [← Back]           [Map PIP]  │
 *   │                               │
 *   │        Camera Feed            │
 *   │        (full screen)          │
 *   │                               │
 *   │  ┌─────────────────────────┐  │
 *   │  │  Google Luma            │  │
 *   │  │  Live Safety + AI      │  │
 *   │  └─────────────────────────┘  │
 *   └────────────────────────────────┘
 *
 * Only renders on mobile (md:hidden).
 */
const LiveSafetyView = memo(function LiveSafetyView({
  route,
  routeSafetyScore,
  userLocation,
  onBack,
}) {
  const {
    videoRef,
    canvasRef,
    cvScore,
    finalScore,
    explanation,
    isAnomaly,
    anomalyLabel,
    features,
    analyzing,
    error,
    frameCount,
  } = useLiveSafety({
    routeSafetyScore,
    enabled: true,
  });

  // Score-based border glow color for visual feedback
  const glowColor = useMemo(() => {
    if (finalScore == null) return 'transparent';
    if (finalScore >= 0.7) return 'rgba(30, 142, 62, 0.3)';
    if (finalScore >= 0.45) return 'rgba(242, 153, 0, 0.3)';
    return 'rgba(234, 67, 53, 0.3)';
  }, [finalScore]);

  return (
    <div
      className="md:hidden"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 2500,
        background: '#000',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* Full-screen camera feed */}
      <video
        ref={videoRef}
        autoPlay
        playsInline
        muted
        style={{
          position: 'absolute',
          inset: 0,
          width: '100%',
          height: '100%',
          objectFit: 'cover',
          // Subtle border glow based on safety score
          boxShadow: `inset 0 0 60px ${glowColor}`,
        }}
      />

      {/* Hidden canvas for frame capture */}
      <canvas ref={canvasRef} style={{ display: 'none' }} />

      {/* Top overlay controls */}
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          zIndex: 1200,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          padding: '16px 16px 0',
        }}
      >
        {/* Back button */}
        <button
          onClick={onBack}
          aria-label="Back to results"
          style={{
            width: 42, height: 42, borderRadius: '50%',
            background: 'rgba(255,255,255,0.93)',
            backdropFilter: 'blur(12px)',
            border: '1.5px solid rgba(210,204,196,0.7)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            cursor: 'pointer',
            boxShadow: '0 2px 10px rgba(48,40,28,0.12)',
            transition: 'all 180ms',
            color: '#1C1917',
            flexShrink: 0
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

        {/* Map PIP */}
        <MiniMapPIP route={route} userLocation={userLocation} />
      </div>

      {/* Camera error overlay */}
      {error && (
        <div
          style={{
            position: 'absolute',
            top: '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
            zIndex: 1300,
            background: 'rgba(0,0,0,0.7)',
            backdropFilter: 'blur(8px)',
            borderRadius: 16,
            padding: '24px 28px',
            maxWidth: 300,
            textAlign: 'center',
          }}
        >
          <svg
            width="36"
            height="36"
            viewBox="0 0 24 24"
            fill="#EA4335"
            style={{ marginBottom: 12 }}
          >
            <path d="M18 10.48V6c0-1.1-.9-2-2-2H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2v-4.48l4 3.98v-11l-4 3.98zm-2-.79V18H4V6h12v3.69z" />
            <path d="M2 2L22 22" stroke="#EA4335" strokeWidth="2" />
          </svg>
          <p
            style={{
              color: 'white',
              fontSize: 14,
              fontWeight: 600,
              lineHeight: 1.5,
              marginBottom: 16,
            }}
          >
            {error}
          </p>
          <button
            onClick={onBack}
            style={{
              padding: '10px 24px',
              borderRadius: 12,
              background: '#1A73E8',
              color: 'white',
              fontWeight: 700,
              fontSize: 13,
              border: 'none',
              cursor: 'pointer',
            }}
          >
            Go Back
          </button>
        </div>
      )}

      {/* Analyzing indicator (top center) */}
      {analyzing && (
        <div
          style={{
            position: 'absolute',
            top: 170,
            left: '50%',
            transform: 'translateX(-50%)',
            zIndex: 1200,
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            padding: '5px 12px',
            borderRadius: 99,
            background: 'rgba(0,0,0,0.45)',
            backdropFilter: 'blur(8px)',
          }}
        >
          <div className="live-safety-scan-dot" />
          <span
            style={{
              fontSize: 10,
              fontWeight: 600,
              color: 'rgba(255,255,255,0.85)',
              letterSpacing: '0.04em',
            }}
          >
            Analyzing frame…
          </span>
        </div>
      )}

      {/* Bottom safety drawer */}
      <LiveSafetyDrawer
        cvScore={cvScore}
        finalScore={finalScore}
        explanation={explanation}
        isAnomaly={isAnomaly}
        anomalyLabel={anomalyLabel}
        features={features}
        analyzing={analyzing}
        frameCount={frameCount}
      />
    </div>
  );
});

export default LiveSafetyView;
