import { memo, useEffect, useRef, useState } from 'react';

/**
 * Lightweight map-themed trivia carousel (no Maps JavaScript API required).
 * Shown while the user sets origin/destination so the panel stays engaging
 * after removing the route-priority picker.
 *
 * Mobile: swipe left/right to navigate slides.
 * Auto-advances every `intervalMs` ms; user interaction resets the timer.
 */
const SLIDES = [
  {
    title: 'Blue dot, real life',
    body: "Google Maps shows your live location with the same fusion of GPS, Wi\u2011Fi, and cell towers your phone uses \u2014 not magic, just sensor math.",
  },
  {
    title: "Mercator's trade-off",
    body: "Most web maps use Mercator: great for local angles and navigation, but Greenland isn't really that big \u2014 areas stretch near the poles.",
  },
  {
    title: 'Traffic in color',
    body: 'Live traffic layers blend anonymous speed samples from drivers and historical patterns, so red segments usually mean "slower than normal right now."',
  },
  {
    title: 'Street View time travel',
    body: "In Street View you can open the timeline and jump years on the same corner \u2014 useful for seeing how a block changed before you visit.",
  },
  {
    title: "Offline isn't offline Earth",
    body: "Offline maps store tiles and routing graphs on-device; your routes still follow the roads that were in the download when you saved the region.",
  },
  {
    title: 'Plus codes',
    body: 'Open Location Codes turn any spot into a short address without a street name — handy where formal addressing is thin but coordinates work.',
  },
  {
    title: 'Why "avoid tolls" reroutes',
    body: 'Routing engines score many paths at once; a toll road might win on time while a parallel arterial wins on cost — your toggle picks the objective.',
  },
];

const SWIPE_THRESHOLD = 40; // px

const MapFactsSlideshow = memo(function MapFactsSlideshow({ intervalMs = 7000 }) {
  const [index, setIndex] = useState(0);
  const timerRef = useRef(null);
  const touchStartXRef = useRef(null);
  const touchStartYRef = useRef(null);
  const isDraggingRef = useRef(false);

  // ── Auto-advance ─────────────────────────────────────────────────
  const resetTimer = () => {
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => {
      setIndex((i) => (i + 1) % SLIDES.length);
    }, intervalMs);
  };

  useEffect(() => {
    resetTimer();
    return () => clearInterval(timerRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs]);

  // ── Navigation helpers ────────────────────────────────────────────
  const goTo = (newIndex) => {
    setIndex((newIndex + SLIDES.length) % SLIDES.length);
    resetTimer();
  };

  // ── Touch handlers ────────────────────────────────────────────────
  const handleTouchStart = (e) => {
    touchStartXRef.current = e.touches[0].clientX;
    touchStartYRef.current = e.touches[0].clientY;
    isDraggingRef.current = false;
  };

  const handleTouchMove = (e) => {
    if (touchStartXRef.current === null) return;
    const dx = e.touches[0].clientX - touchStartXRef.current;
    const dy = e.touches[0].clientY - touchStartYRef.current;
    // Only lock horizontal drag if it's clearly more horizontal than vertical
    if (!isDraggingRef.current && Math.abs(dx) > Math.abs(dy) && Math.abs(dx) > 8) {
      isDraggingRef.current = true;
    }
    if (isDraggingRef.current) {
      // Prevent parent scroll while swiping facts card
      e.stopPropagation();
    }
  };

  const handleTouchEnd = (e) => {
    if (touchStartXRef.current === null) return;
    const dx = e.changedTouches[0].clientX - touchStartXRef.current;
    touchStartXRef.current = null;
    touchStartYRef.current = null;

    if (isDraggingRef.current && Math.abs(dx) >= SWIPE_THRESHOLD) {
      goTo(dx < 0 ? index + 1 : index - 1);
    }
    isDraggingRef.current = false;
  };

  const slide = SLIDES[index];

  return (
    <div
      role="region"
      aria-roledescription="carousel"
      aria-label="Map facts"
      onTouchStart={handleTouchStart}
      onTouchMove={handleTouchMove}
      onTouchEnd={handleTouchEnd}
      style={{
        borderRadius: 14,
        border: '1.5px solid #E2DBD2',
        background: 'linear-gradient(145deg, #F8FAFF 0%, #FEFCF8 55%, #F5F2EC 100%)',
        padding: '14px 16px',
        minHeight: 108,
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        boxShadow: '0 1px 6px rgba(48,40,28,0.05)',
        // Prevent text selection during swipe
        userSelect: 'none',
        WebkitUserSelect: 'none',
        touchAction: 'pan-y', // allow vertical scroll pass-through; horizontal captured by JS
        cursor: 'grab',
      }}
    >
      {/* Header: label + dot indicators */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10 }}>
        <p
          style={{
            fontSize: 9,
            fontWeight: 700,
            color: '#5F6368',
            textTransform: 'uppercase',
            letterSpacing: '0.12em',
            margin: 0,
          }}
        >
          Google Maps · Fun facts
        </p>
        <div style={{ display: 'flex', gap: 4 }} aria-hidden>
          {SLIDES.map((_, i) => (
            <button
              key={i}
              aria-label={`Go to fact ${i + 1}`}
              onClick={() => goTo(i)}
              style={{
                width: i === index ? 14 : 5,
                height: 5,
                borderRadius: 99,
                background: i === index ? '#1A73E8' : '#D8D2C8',
                transition: 'all 240ms ease',
                border: 'none',
                padding: 0,
                cursor: 'pointer',
                flexShrink: 0,
              }}
            />
          ))}
        </div>
      </div>

      {/* Slide content — key-based remount for smooth fade-in */}
      <h3
        key={`title-${index}`}
        style={{
          fontSize: 14,
          fontWeight: 800,
          color: '#1C1917',
          margin: 0,
          letterSpacing: '-0.02em',
          lineHeight: 1.25,
          animation: 'fadeIn 220ms ease-out',
        }}
      >
        {slide.title}
      </h3>
      <p
        key={`body-${index}`}
        style={{
          fontSize: 12,
          color: '#5F6368',
          lineHeight: 1.55,
          margin: 0,
          fontWeight: 500,
          flex: 1,
          animation: 'fadeIn 280ms ease-out',
        }}
      >
        {slide.body}
      </p>

      {/* Swipe hint — visible on first render only as accessibility cue */}
      <p style={{
        fontSize: 9,
        color: '#B8B0A4',
        margin: 0,
        textAlign: 'right',
        fontWeight: 500,
        letterSpacing: '0.04em',
      }}>
        Swipe to explore ›
      </p>
    </div>
  );
});

export default MapFactsSlideshow;
