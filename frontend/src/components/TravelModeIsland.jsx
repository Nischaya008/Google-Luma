import { memo } from 'react';

/**
 * Top-center "dynamic island" style control for Drive vs Walk (OSRM profiles).
 */
const TravelModeIsland = memo(function TravelModeIsland({
  value,
  onChange,
  disabled = false,
}) {
  const isDrive = value === 'driving';

  return (
    <div
      role="tablist"
      aria-label="Travel mode"
      style={{
        position: 'fixed',
        top: 12,
        left: '50%',
        transform: 'translateX(-50%)',
        zIndex: 1100,
        display: 'flex',
        alignItems: 'center',
        gap: 0,
        padding: 4,
        borderRadius: 999,
        background: 'rgba(28, 25, 23, 0.92)',
        backdropFilter: 'blur(14px)',
        border: '1px solid rgba(255,255,255,0.12)',
        boxShadow: '0 8px 32px rgba(0,0,0,0.28), 0 0 0 1px rgba(0,0,0,0.04)',
        opacity: disabled ? 0.55 : 1,
        pointerEvents: disabled ? 'none' : 'auto',
        transition: 'opacity 200ms ease',
      }}
    >
      <button
        type="button"
        role="tab"
        aria-selected={isDrive}
        id="travel-mode-drive"
        onClick={() => onChange('driving')}
        style={{
          border: 'none',
          cursor: disabled ? 'not-allowed' : 'pointer',
          padding: '8px 18px',
          borderRadius: 999,
          fontSize: 12.5,
          fontWeight: 700,
          letterSpacing: '0.02em',
          transition: 'background 220ms ease, color 220ms ease, transform 180ms ease',
          background: isDrive ? '#FEFCF8' : 'transparent',
          color: isDrive ? '#1C1917' : 'rgba(255,255,255,0.72)',
          transform: isDrive ? 'scale(1.02)' : 'scale(1)',
          display: 'flex',
          alignItems: 'center',
          gap: 6,
        }}
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
          <path d="M18.92 6.01C18.72 5.42 18.16 5 17.5 5h-11c-.66 0-1.21.42-1.42 1.01L3 12v8c0 .55.45 1 1 1h1c.55 0 1-.45 1-1v-1h12v1c0 .55.45 1 1 1h1c.55 0 1-.45 1-1v-8l-2.08-5.99zM6.5 16c-.83 0-1.5-.67-1.5-1.5S5.67 13 6.5 13s1.5.67 1.5 1.5S7.33 16 6.5 16zm11 0c-.83 0-1.5-.67-1.5-1.5s.67-1.5 1.5-1.5 1.5.67 1.5 1.5-.67 1.5-1.5 1.5zM5 11l1.5-4.5h11L19 11H5z" />
        </svg>
        Drive
      </button>
      <button
        type="button"
        role="tab"
        aria-selected={!isDrive}
        id="travel-mode-walk"
        onClick={() => onChange('foot')}
        style={{
          border: 'none',
          cursor: disabled ? 'not-allowed' : 'pointer',
          padding: '8px 18px',
          borderRadius: 999,
          fontSize: 12.5,
          fontWeight: 700,
          letterSpacing: '0.02em',
          transition: 'background 220ms ease, color 220ms ease, transform 180ms ease',
          background: !isDrive ? '#FEFCF8' : 'transparent',
          color: !isDrive ? '#1C1917' : 'rgba(255,255,255,0.72)',
          transform: !isDrive ? 'scale(1.02)' : 'scale(1)',
          display: 'flex',
          alignItems: 'center',
          gap: 6,
        }}
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
          <path d="M13.5 5.5c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zM9.8 8.9L7 23h2.1l1.8-8 2.1 2v6h2v-7.5l-2.1-2 .6-3c1.1 1.2 2.9 2 4.6 2v-2c-1.3 0-2.6-.6-3.4-1.6l-1-1.3c-.4-.5-.9-.9-1.6-1.1l-5.3-1.5c-.5-.1-1.1.1-1.4.5l-1.8 2.2L9 10v5h2v-4.4l1.8-.6" />
        </svg>
        Walk
      </button>
    </div>
  );
});

export default TravelModeIsland;
