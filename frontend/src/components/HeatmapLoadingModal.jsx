import { memo, useEffect, useRef, useState, useMemo } from 'react';

/**
 * HeatmapLoadingModal — Premium loading overlay shown while the safety heatmap
 * is being generated on the backend.
 *
 * Features:
 *   • Segmented progress bar mapping to real backend pipeline stages
 *   • Auto-rotating Google fun-facts carousel
 *   • Explains why heatmap takes time (OSMnx graph download + ML scoring)
 *   • Responsive: centered on both mobile and desktop
 *   • Auto-closes when `loading` flips to false
 */

/* Google Material Design SVG icon helpers — compact, colored, brand-aligned */
const GIcon = ({ d, color = '#1A73E8', size = 18 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill={color} style={{ flexShrink: 0 }}>
    <path d={d} />
  </svg>
);

const GOOGLE_FACTS = [
  {
    icon: <GIcon d="M15.5 14h-.79l-.28-.27A6.47 6.47 0 0016 9.5 6.5 6.5 0 109.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z" color="#4285F4" />,
    title: 'The name "Google"',
    body: 'Google\'s name is a play on "googol" — the number 1 followed by 100 zeros, reflecting the mission to organize an immense amount of information.',
  },
  {
    icon: <GIcon d="M20.5 3l-.16.03L15 5.1 9 3 3.36 4.9c-.21.07-.36.25-.36.48V20.5c0 .28.22.5.5.5l.16-.03L9 18.9l6 2.1 5.64-1.9c.21-.07.36-.25.36-.48V3.5c0-.28-.22-.5-.5-.5zM15 19l-6-2.11V5l6 2.11V19z" color="#34A853" />,
    title: '99% of the world mapped',
    body: 'Google Maps covers over 99% of the world, with more than 100 million km of roads mapped and 1 billion+ active users every month.',
  },
  {
    icon: <GIcon d="M18.92 6.01C18.72 5.42 18.16 5 17.5 5h-11c-.66 0-1.21.42-1.42 1.01L3 12v8c0 .55.45 1 1 1h1c.55 0 1-.45 1-1v-1h12v1c0 .55.45 1 1 1h1c.55 0 1-.45 1-1v-8l-2.08-5.99zM6.5 16C5.67 16 5 15.33 5 14.5S5.67 13 6.5 13s1.5.67 1.5 1.5S7.33 16 6.5 16zm11 0c-.83 0-1.5-.67-1.5-1.5s.67-1.5 1.5-1.5 1.5.67 1.5 1.5-.67 1.5-1.5 1.5zM5 11l1.5-4.5h11L19 11H5z" color="#FBBC04" />,
    title: 'Street View adventures',
    body: 'Google Street View cars have driven over 16 million km — enough to circle the Earth 400 times — capturing imagery in 100+ countries.',
  },
  {
    icon: <GIcon d="M21 11.18V9.72c0-.47-.16-.92-.46-1.28L16.6 3.72c-.38-.46-.94-.72-1.54-.72H8.94c-.6 0-1.16.26-1.54.72L3.46 8.44c-.3.36-.46.81-.46 1.28v1.46c0 .63.3 1.22.8 1.6v6.72c0 .83.67 1.5 1.5 1.5h13.4c.83 0 1.5-.67 1.5-1.5v-6.72c.5-.38.8-.97.8-1.6zM12 17.5c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zm6.08-7.67L12 16 5.92 9.83l3.18-3.83h5.8l3.18 3.83z" color="#4285F4" />,
    title: 'AI-powered routing',
    body: 'Google uses DeepMind AI to predict traffic conditions up to an hour ahead, reducing estimated travel times by up to 50% in some cities.',
  },
  {
    icon: <GIcon d="M20 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 4l-8 5-8-5V6l8 5 8-5v2z" color="#EA4335" />,
    title: 'Gmail\'s April Fools launch',
    body: 'Gmail launched on April 1, 2004, with 1 GB of free storage — so generous that many thought it was an April Fools\' joke.',
  },
  {
    icon: <GIcon d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z" color="#34A853" />,
    title: 'Google Earth\'s resolution',
    body: 'Google Earth covers over 36 million sq. miles in high-resolution imagery. You can explore ocean floors, Mars, and even the Moon.',
  },
  {
    icon: <GIcon d="M7 2v11h3v9l7-12h-4l4-8z" color="#FBBC04" />,
    title: '8.5 billion searches/day',
    body: 'Google processes approximately 8.5 billion searches every single day — that\'s about 99,000 queries every second around the clock.',
  },
  {
    icon: <GIcon d="M12 7V3H2v18h20V7H12zM6 19H4v-2h2v2zm0-4H4v-2h2v2zm0-4H4V9h2v2zm0-4H4V5h2v2zm4 12H8v-2h2v2zm0-4H8v-2h2v2zm0-4H8V9h2v2zm0-4H8V5h2v2zm10 12h-8v-2h2v-2h-2v-2h2v-2h-2V9h8v10zm-2-8h-2v2h2v-2zm0 4h-2v2h2v-2z" color="#4285F4" />,
    title: 'Started in a garage',
    body: 'Larry Page and Sergey Brin started Google in Susan Wojcicki\'s garage in Menlo Park, California, in September 1998.',
  },
  {
    icon: <GIcon d="M12 22C6.49 22 2 17.51 2 12S6.49 2 12 2s10 4.04 10 9c0 3.31-2.69 6-6 6h-1.77c-.28 0-.5.22-.5.5 0 .12.05.23.13.33.41.47.64 1.06.64 1.67A2.5 2.5 0 0112 22zm0-18c-4.41 0-8 3.59-8 8s3.59 8 8 8c.28 0 .5-.22.5-.5a.54.54 0 00-.14-.35c-.41-.46-.63-1.05-.63-1.65a2.5 2.5 0 012.5-2.5H16c2.21 0 4-1.79 4-4 0-3.86-3.59-7-8-7zm-5.5 9a1.5 1.5 0 100-3 1.5 1.5 0 000 3zm3-4a1.5 1.5 0 100-3 1.5 1.5 0 000 3zm5 0a1.5 1.5 0 100-3 1.5 1.5 0 000 3zm3 4a1.5 1.5 0 100-3 1.5 1.5 0 000 3z" color="#EA4335" />,
    title: 'First Google Doodle',
    body: 'The very first Google Doodle was a Burning Man festival stick figure in 1998, placed behind the second "o" as an out-of-office message.',
  },
  {
    icon: <GIcon d="M11.39 4.17a1 1 0 011.22 0l8.08 6.26a1 1 0 01.31 1.2l-3.08 7.53a1 1 0 01-.93.62H7.01a1 1 0 01-.93-.62l-3.08-7.53a1 1 0 01.31-1.2l8.08-6.26zM12 15a2 2 0 100-4 2 2 0 000 4z" color="#34A853" />,
    title: 'Carbon-neutral since 2007',
    body: 'Google has been carbon-neutral since 2007 and matched 100% of its electricity with renewable energy purchases since 2017.',
  },
];

/** Pipeline stages that correspond to real backend processing steps */
const PIPELINE_STAGES = [
  { label: 'Checking cache for pre-computed data',    pct: 8  },
  { label: 'Downloading road network from OSMnx',     pct: 25 },
  { label: 'Computing VIIRS nightlight features',     pct: 42 },
  { label: 'Analyzing crime density (KDE)',            pct: 55 },
  { label: 'Merging weather & temporal features',      pct: 68 },
  { label: 'Training safety scoring model (XGBoost)',  pct: 80 },
  { label: 'Annotating road segments with scores',     pct: 90 },
  { label: 'Building heatmap overlay',                 pct: 97 },
];

const FACT_ROTATE_MS = 5000;
const STAGE_ADVANCE_MS = 4500;

const HeatmapLoadingModal = memo(function HeatmapLoadingModal({ loading }) {
  const [visible, setVisible] = useState(false);
  const [closing, setClosing] = useState(false);
  const [factIndex, setFactIndex] = useState(0);
  const [stageIndex, setStageIndex] = useState(0);
  const factTimer = useRef(null);
  const stageTimer = useRef(null);

  // Randomize fact order on mount
  const shuffledFacts = useMemo(() => {
    const arr = [...GOOGLE_FACTS];
    for (let i = arr.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [arr[i], arr[j]] = [arr[j], arr[i]];
    }
    return arr;
  }, []);

  // Show modal when loading starts
  useEffect(() => {
    if (loading) {
      setVisible(true);
      setClosing(false);
      setFactIndex(0);
      setStageIndex(0);
    } else if (visible) {
      // Loading finished — play closing animation
      setStageIndex(PIPELINE_STAGES.length); // jump to 100%
      const t = setTimeout(() => {
        setClosing(true);
        const t2 = setTimeout(() => {
          setVisible(false);
          setClosing(false);
        }, 420);
        return () => clearTimeout(t2);
      }, 600);
      return () => clearTimeout(t);
    }
  }, [loading]);

  // Auto-rotate facts
  useEffect(() => {
    if (!visible || closing) return;
    factTimer.current = setInterval(() => {
      setFactIndex((i) => (i + 1) % shuffledFacts.length);
    }, FACT_ROTATE_MS);
    return () => clearInterval(factTimer.current);
  }, [visible, closing, shuffledFacts.length]);

  // Auto-advance pipeline stages (simulated progress that maps to real steps)
  useEffect(() => {
    if (!visible || closing) return;
    stageTimer.current = setInterval(() => {
      setStageIndex((i) => {
        // Don't go past the last stage — it will jump to 100 when loading becomes false
        if (i >= PIPELINE_STAGES.length - 1) {
          clearInterval(stageTimer.current);
          return i;
        }
        return i + 1;
      });
    }, STAGE_ADVANCE_MS);
    return () => clearInterval(stageTimer.current);
  }, [visible, closing]);

  if (!visible) return null;

  const currentStage = stageIndex < PIPELINE_STAGES.length
    ? PIPELINE_STAGES[stageIndex]
    : { label: 'Heatmap ready!', pct: 100 };
  const fact = shuffledFacts[factIndex % shuffledFacts.length];
  const progressPct = currentStage.pct;

  return (
    <div
      id="heatmap-loading-modal-backdrop"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 3000,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'rgba(28, 25, 23, 0.45)',
        backdropFilter: 'blur(6px)',
        WebkitBackdropFilter: 'blur(6px)',
        padding: '16px',
        animation: closing
          ? 'heatmapModalFadeOut 400ms ease-in forwards'
          : 'heatmapModalFadeIn 300ms ease-out',
      }}
    >
      <div
        id="heatmap-loading-modal"
        style={{
          width: '100%',
          maxWidth: 460,
          background: 'linear-gradient(160deg, #FEFCF8 0%, #F8FAFF 40%, #FEFCF8 100%)',
          borderRadius: 20,
          border: '1.5px solid rgba(226, 219, 210, 0.8)',
          boxShadow: '0 8px 40px rgba(48, 40, 28, 0.18), 0 1px 3px rgba(48, 40, 28, 0.08)',
          padding: '28px 24px 24px',
          display: 'flex',
          flexDirection: 'column',
          gap: 20,
          animation: closing
            ? 'heatmapModalSlideOut 400ms ease-in forwards'
            : 'heatmapModalSlideIn 350ms cubic-bezier(0.16, 1, 0.3, 1)',
          maxHeight: '90vh',
          overflowY: 'auto',
        }}
      >
        {/* ── Header ── */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{
            width: 40, height: 40, borderRadius: 12,
            background: 'linear-gradient(135deg, #1A73E8 0%, #4285F4 100%)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            boxShadow: '0 2px 8px rgba(26, 115, 232, 0.3)',
            flexShrink: 0,
          }}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="white">
              <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z" />
            </svg>
          </div>
          <div>
            <h2 style={{
              fontSize: 17, fontWeight: 800, color: '#1C1917',
              letterSpacing: '-0.3px', margin: 0, lineHeight: 1.2,
            }}>
              Generating Safety Heatmap
            </h2>
            <p style={{
              fontSize: 11, fontWeight: 600, color: '#9C9284',
              letterSpacing: '0.06em', textTransform: 'uppercase',
              margin: '3px 0 0',
            }}>
              Analyzing road network
            </p>
          </div>
        </div>

        {/* ── Info banner: why it takes time ── */}
        <div style={{
          background: 'rgba(26, 115, 232, 0.06)',
          border: '1.5px solid rgba(26, 115, 232, 0.15)',
          borderRadius: 14,
          padding: '12px 14px',
          display: 'flex',
          gap: 10,
          alignItems: 'flex-start',
        }}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="#1A73E8" style={{ flexShrink: 0, marginTop: 1 }}>
            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z" />
          </svg>
          <p style={{
            fontSize: 11.5, color: '#3C4043', lineHeight: 1.55,
            margin: 0, fontWeight: 500,
          }}>
            Heatmap generation takes a moment because Luma downloads the full road network
            for your area, computes per-segment safety features using satellite nightlight
            data, crime density models, and weather — then trains an ML model to score
            every road in real time.
          </p>
        </div>

        {/* ── Segmented Progress Bar ── */}
        <div>
          {/* Bar track */}
          <div style={{
            width: '100%', height: 8, borderRadius: 99,
            background: '#EAE4DC',
            overflow: 'hidden',
            position: 'relative',
          }}>
            {/* Segment markers */}
            {PIPELINE_STAGES.slice(0, -1).map((stage, i) => (
              <div key={i} style={{
                position: 'absolute',
                left: `${stage.pct}%`,
                top: 0, bottom: 0,
                width: 2,
                background: 'rgba(255,255,255,0.8)',
                zIndex: 2,
              }} />
            ))}
            {/* Fill */}
            <div style={{
              height: '100%',
              width: `${progressPct}%`,
              borderRadius: 99,
              background: progressPct >= 100
                ? 'linear-gradient(90deg, #34A853 0%, #0D652D 100%)'
                : 'linear-gradient(90deg, #1A73E8 0%, #4285F4 60%, #669DF6 100%)',
              transition: 'width 800ms cubic-bezier(0.4, 0, 0.2, 1), background 400ms ease',
              position: 'relative',
              zIndex: 1,
            }}>
              {/* Shimmer on active bar */}
              {progressPct < 100 && (
                <div style={{
                  position: 'absolute', inset: 0, borderRadius: 99,
                  background: 'linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.3) 50%, transparent 100%)',
                  backgroundSize: '200% 100%',
                  animation: 'shimmer 1.5s ease-in-out infinite',
                }} />
              )}
            </div>
          </div>

          {/* Stage label + percentage */}
          <div style={{
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            marginTop: 8, gap: 8,
          }}>
            <p
              key={`stage-${stageIndex}`}
              style={{
                fontSize: 11.5, fontWeight: 600,
                color: progressPct >= 100 ? '#0D652D' : '#5F6368',
                margin: 0, lineHeight: 1.3,
                animation: 'fadeIn 250ms ease-out',
                flex: 1,
              }}
            >
              {progressPct >= 100 && (
                <svg width="12" height="12" viewBox="0 0 24 24" fill="#34A853"
                  style={{ verticalAlign: '-1px', marginRight: 4 }}>
                  <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z" />
                </svg>
              )}
              {currentStage.label}
            </p>
            <span style={{
              fontSize: 12, fontWeight: 700,
              color: progressPct >= 100 ? '#0D652D' : '#1A73E8',
              fontVariantNumeric: 'tabular-nums',
              flexShrink: 0,
            }}>
              {progressPct}%
            </span>
          </div>
        </div>

        {/* ── Pipeline step checklist ── */}
        <div style={{
          display: 'flex', flexDirection: 'column', gap: 4,
          maxHeight: 120, overflowY: 'auto',
        }}
          className="scrollbar-hide"
        >
          {PIPELINE_STAGES.map((stage, i) => {
            const done = i < stageIndex || progressPct >= 100;
            const active = i === stageIndex && progressPct < 100;
            return (
              <div key={i} style={{
                display: 'flex', alignItems: 'center', gap: 8,
                padding: '5px 10px',
                borderRadius: 10,
                background: done ? 'rgba(52, 168, 83, 0.06)' : active ? 'rgba(26, 115, 232, 0.06)' : 'transparent',
                transition: 'all 300ms ease',
              }}>
                <div style={{
                  width: 18, height: 18, borderRadius: '50%',
                  background: done ? '#34A853' : active ? '#1A73E8' : '#E8E2D9',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  flexShrink: 0,
                  transition: 'all 300ms ease',
                }}>
                  {done ? (
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="white">
                      <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z" />
                    </svg>
                  ) : active ? (
                    <div style={{
                      width: 8, height: 8, borderRadius: '50%',
                      border: '2px solid white',
                      borderTopColor: 'transparent',
                      animation: 'heatmapSpin 0.8s linear infinite',
                    }} />
                  ) : (
                    <div style={{
                      width: 5, height: 5, borderRadius: '50%',
                      background: '#B8B0A4',
                    }} />
                  )}
                </div>
                <span style={{
                  fontSize: 11, fontWeight: done ? 600 : 500,
                  color: done ? '#0D652D' : active ? '#1A73E8' : '#9C9284',
                  transition: 'color 300ms ease',
                }}>
                  {stage.label}
                </span>
              </div>
            );
          })}
        </div>

        {/* ── Divider ── */}
        <div style={{ height: 1, background: '#EAE4DC', borderRadius: 1 }} />

        {/* ── Fun Fact Card ── */}
        <div style={{
          borderRadius: 14,
          border: '1.5px solid #E2DBD2',
          background: 'linear-gradient(145deg, #F8FAFF 0%, #FEFCF8 55%, #F5F2EC 100%)',
          padding: '14px 16px',
          display: 'flex',
          flexDirection: 'column',
          gap: 8,
          boxShadow: '0 1px 6px rgba(48,40,28,0.04)',
          minHeight: 100,
        }}>
          {/* Fact header */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <p style={{
              fontSize: 9, fontWeight: 700, color: '#5F6368',
              textTransform: 'uppercase', letterSpacing: '0.12em', margin: 0,
            }}>
              Did you know? · Google Facts
            </p>
            <div style={{ display: 'flex', gap: 3 }}>
              {shuffledFacts.slice(0, 6).map((_, i) => (
                <div key={i} style={{
                  width: factIndex % 6 === i ? 12 : 4,
                  height: 4,
                  borderRadius: 99,
                  background: factIndex % 6 === i ? '#1A73E8' : '#D8D2C8',
                  transition: 'all 280ms ease',
                }} />
              ))}
            </div>
          </div>

          {/* Fact content */}
          <div key={`fact-${factIndex}`} style={{ animation: 'fadeIn 320ms ease-out' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              {fact.icon}
              <h3 style={{
                fontSize: 13.5, fontWeight: 800, color: '#1C1917',
                margin: 0, letterSpacing: '-0.02em', lineHeight: 1.25,
              }}>
                {fact.title}
              </h3>
            </div>
            <p style={{
              fontSize: 11.5, color: '#5F6368', lineHeight: 1.55,
              margin: 0, fontWeight: 500,
            }}>
              {fact.body}
            </p>
          </div>
        </div>

        {/* ── Footer note ── */}
        <p style={{
          fontSize: 10, color: '#B8B0A4', margin: 0,
          textAlign: 'center', fontWeight: 500,
        }}>
          Subsequent loads are cached and near-instant
        </p>
      </div>
    </div>
  );
});

export default HeatmapLoadingModal;
