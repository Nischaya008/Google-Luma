import { memo, useState } from 'react';

function truncate(s, max = 36) {
  if (!s || s.length <= max) return s || '';
  return `${s.slice(0, max - 1)}…`;
}

/**
 * Home-only panel: up to 5 stored routes (localStorage). 
 * On desktop, it's a fixed card. 
 * On mobile, it collapses to a circular button and expands on tap.
 */
const RecentRoutesPanel = memo(function RecentRoutesPanel({
  items,
  onSelect,
  loading,
}) {
  const [isOpen, setIsOpen] = useState(false);

  if (!items?.length) return null;

  return (
    <aside
      aria-label="Recent routes"
      className={`recent-routes-panel ${isOpen ? 'open' : 'closed'}`}
      onClick={(e) => {
        if (!isOpen) setIsOpen(true);
      }}
      style={{
        position: 'fixed',
        zIndex: 997,
        right: 16,
        bottom: 5, // Desktop bottom
        width: 'min(300px, calc(100vw - 32px))',
        maxHeight: 'min(52vh, 340px)',
        display: 'flex',
        flexDirection: 'column',
        background: '#FEFCF8',
        border: '1.5px solid #DDD5C8',
        borderRadius: 20,
        boxShadow: '0 -4px 32px rgba(48,40,28,0.12), 0 -1px 6px rgba(48,40,28,0.05)',
        overflow: 'hidden',
      }}
    >
      <style>{`
        .recent-routes-icon {
           display: none;
        }
        .recent-routes-close {
           display: none;
        }
        
        @media (max-width: 767px) {
          .recent-routes-panel {
            /* Shifted up to sit nicely above the centered pill buttons */
            bottom: 154px !important;
            right: 16px !important;
            transition: width 300ms cubic-bezier(0.4, 0, 0.2, 1), 
                        max-height 300ms cubic-bezier(0.4, 0, 0.2, 1), 
                        border-radius 300ms cubic-bezier(0.4, 0, 0.2, 1) !important;
          }
          .recent-routes-panel.closed {
            width: 44px !important;
            max-height: 44px !important;
            border-radius: 50% !important;
            cursor: pointer;
          }
          .recent-routes-panel.open {
            width: min(300px, calc(100vw - 32px)) !important;
            max-height: 340px !important;
            border-radius: 20px !important;
            cursor: default;
          }
          
          .recent-routes-content {
            opacity: 1;
            transition: opacity 200ms ease 100ms;
            display: flex;
            flex-direction: column;
            height: 100%;
          }
          .recent-routes-panel.closed .recent-routes-content {
            opacity: 0;
            pointer-events: none;
            transition: opacity 100ms ease;
          }
          
          .recent-routes-icon {
            position: absolute;
            top: 0; left: 0; right: 0; bottom: 0;
            display: flex;
            align-items: center; justify-content: center;
            color: #1A73E8;
            opacity: 0;
            pointer-events: none;
            transition: opacity 200ms ease;
          }
          .recent-routes-panel.closed .recent-routes-icon {
            opacity: 1;
            pointer-events: auto;
            transition: opacity 200ms ease 100ms;
          }
          
          .recent-routes-close {
             display: flex;
             position: absolute;
             top: 10px; right: 10px;
             background: #F5F0E8;
             border: none;
             border-radius: 50%;
             width: 24px; height: 24px;
             font-size: 14px;
             cursor: pointer;
             align-items: center; justify-content: center;
             color: #9C9284;
             z-index: 10;
          }
        }
      `}</style>

      {/* Closed state icon (Mobile only) */}
      <div className="recent-routes-icon" aria-hidden="true">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <polyline points="12 6 12 12 16 14" />
        </svg>
      </div>

      {/* Content wrapper */}
      <div className="recent-routes-content" style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        <button
          className="recent-routes-close"
          onClick={(e) => { e.stopPropagation(); setIsOpen(false); }}
          aria-label="Close recent routes"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>

        <div
          style={{
            padding: '12px 16px 10px',
            borderBottom: '1px solid #EAE4DC',
            flexShrink: 0,
          }}
        >
          <p
            style={{
              margin: 0,
              fontSize: 10,
              fontWeight: 700,
              color: '#9C9284',
              textTransform: 'uppercase',
              letterSpacing: '0.1em',
            }}
          >
            Recent routes
          </p>
          <p style={{ margin: '4px 0 0', fontSize: 11, color: '#B0A899', fontWeight: 500 }}>
            Saved on this device only
          </p>
        </div>
        <ul
          style={{
            listStyle: 'none',
            margin: 0,
            padding: '6px 0',
            overflowY: 'auto',
            flex: 1,
            // Prevent scrolling on touch when dragging if we want, but auto is fine here
          }}
        >
          {items.map((entry) => (
            <li key={entry.id} style={{ margin: 0 }}>
              <button
                type="button"
                disabled={loading}
                onClick={() => onSelect(entry)}
                style={{
                  width: '100%',
                  textAlign: 'left',
                  padding: '10px 16px',
                  border: 'none',
                  background: 'transparent',
                  cursor: loading ? 'not-allowed' : 'pointer',
                  opacity: loading ? 0.65 : 1,
                  transition: 'background 150ms',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 6,
                }}
                onMouseEnter={(e) => {
                  if (!loading) e.currentTarget.style.background = '#F5F0E8';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = 'transparent';
                }}
              >
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
                  <span
                    style={{
                      width: 8,
                      height: 8,
                      borderRadius: '50%',
                      background: '#1A73E8',
                      marginTop: 4,
                      flexShrink: 0,
                    }}
                  />
                  <span
                    style={{
                      fontSize: 12,
                      fontWeight: 600,
                      color: '#1C1917',
                      lineHeight: 1.35,
                    }}
                  >
                    {truncate(entry.source.label)}
                  </span>
                </div>
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8, paddingLeft: 16 }}>
                  <span
                    style={{
                      width: 8,
                      height: 8,
                      borderRadius: 2,
                      background: '#EA4335',
                      marginTop: 4,
                      flexShrink: 0,
                    }}
                  />
                  <span
                    style={{
                      fontSize: 12,
                      fontWeight: 600,
                      color: '#1C1917',
                      lineHeight: 1.35,
                    }}
                  >
                    {truncate(entry.destination.label)}
                  </span>
                </div>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </aside>
  );
});

export default RecentRoutesPanel;
