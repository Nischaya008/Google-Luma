import { useState, useEffect } from 'react';

export default function ToastNotification() {
  const [show, setShow] = useState(false);
  const [isDesktop, setIsDesktop] = useState(true);

  useEffect(() => {
    // Check if device is probably a desktop based on window width or touch points
    const checkIsDesktop = () => window.innerWidth > 768;
    setIsDesktop(checkIsDesktop());
    
    const handleResize = () => setIsDesktop(checkIsDesktop());
    window.addEventListener('resize', handleResize);

    // Show toast after a slight delay so it catches attention
    const timer = setTimeout(() => {
      setShow(true);
      // Auto-hide after 15 seconds
      setTimeout(() => setShow(false), 15000);
    }, 2500);

    return () => {
      window.removeEventListener('resize', handleResize);
      clearTimeout(timer);
    };
  }, []);

  if (!show) return null;

  return (
    <div style={{
      position: 'fixed',
      bottom: isDesktop ? '32px' : '90px',
      left: '50%',
      transform: 'translateX(-50%)',
      zIndex: 9999,
      display: 'flex',
      flexDirection: 'column',
      gap: '8px',
      animation: 'luma-toast-in 0.5s cubic-bezier(0.175, 0.885, 0.32, 1.275) forwards',
      pointerEvents: 'auto',
      maxWidth: 'calc(100vw - 32px)',
      width: isDesktop ? 'auto' : '100%',
    }}>
      <style>{`
        @keyframes luma-toast-in {
          from { opacity: 0; transform: translate(-50%, 20px); }
          to { opacity: 1; transform: translate(-50%, 0); }
        }
        @keyframes luma-toast-pulse {
          0% { box-shadow: 0 0 0 0 rgba(26, 115, 232, 0.4); }
          70% { box-shadow: 0 0 0 6px rgba(26, 115, 232, 0); }
          100% { box-shadow: 0 0 0 0 rgba(26, 115, 232, 0); }
        }
      `}</style>
      
      {/* Route tip (All devices) */}
      <div style={{
        background: '#FEFCF8',
        border: '1.5px solid #1A73E8',
        padding: '12px 18px',
        borderRadius: '16px',
        boxShadow: '0 8px 24px rgba(48,40,28,0.12)',
        display: 'flex',
        alignItems: 'flex-start',
        gap: '12px',
        position: 'relative',
        animation: 'luma-toast-pulse 2s infinite',
      }}>
        <div style={{
          width: '24px', height: '24px', borderRadius: '50%',
          background: '#E8F0FE', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
          color: '#1A73E8'
        }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path>
            <circle cx="12" cy="10" r="3"></circle>
          </svg>
        </div>
        <div style={{ flex: 1 }}>
          <h4 style={{ margin: 0, fontSize: '13px', fontWeight: 700, color: '#1C1917', lineHeight: 1.2 }}>
            Try different routes!
          </h4>
          <p style={{ margin: '4px 0 0 0', fontSize: '12px', color: '#6B6259', lineHeight: 1.4 }}>
            Place pins or search different cities to see how the safety engine adapts to different scenarios.
          </p>
        </div>
        <button 
          onClick={() => setShow(false)}
          style={{
            background: 'transparent', border: 'none', padding: '4px', cursor: 'pointer',
            color: '#B0A899', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center'
          }}
          aria-label="Close"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
             <line x1="18" y1="6" x2="6" y2="18"></line>
             <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
        </button>
      </div>

      {/* Mobile features tip (Desktop only) */}
      {isDesktop && (
        <div style={{
          background: '#1C1917',
          border: '1.5px solid #30281C',
          padding: '10px 16px',
          borderRadius: '12px',
          boxShadow: '0 4px 12px rgba(0,0,0,0.1)',
          display: 'flex',
          alignItems: 'center',
          gap: '10px'
        }}>
           <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#EAE4DC" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
             <rect x="5" y="2" width="14" height="20" rx="2" ry="2"></rect>
             <line x1="12" y1="18" x2="12.01" y2="18"></line>
          </svg>
          <p style={{ margin: 0, fontSize: '12px', color: '#EAE4DC', fontWeight: 500, lineHeight: 1.3 }}>
            <strong>Pro tip:</strong> Open this app on your mobile device to try the Live Safety Camera!
          </p>
        </div>
      )}
    </div>
  );
}
