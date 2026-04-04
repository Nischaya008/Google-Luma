import { useState, useEffect, useRef, useMemo } from 'react';
import { normalizeLatLonPair } from '../utils/geo';
import { fetchGeocodingSuggestions } from '../services/geocoding';

function useDebounce(value, delay) {
  const [debouncedValue, setDebouncedValue] = useState(value);
  useEffect(() => {
    const handler = setTimeout(() => setDebouncedValue(value), delay);
    return () => clearTimeout(handler);
  }, [value, delay]);
  return debouncedValue;
}

function DotLoader() {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3 }}>
      {[0, 150, 300].map((delay, i) => (
        <span
          key={i}
          style={{
            display: 'block', width: 5, height: 5, borderRadius: '50%',
            background: '#1A73E8',
            animation: `dotBounce 0.9s ${delay}ms ease-in-out infinite`,
          }}
        />
      ))}
    </span>
  );
}

function ResultSkeleton() {
  return (
    <div style={{ padding: '12px 16px' }}>
      {[1, 0.7, 0.5].map((w, i) => (
        <div key={i} style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: i < 2 ? 12 : 0 }}>
          <div style={{
            width: 36, height: 36, borderRadius: '50%', flexShrink: 0,
            background: 'linear-gradient(90deg, #EDE9E1 25%, #E2DDD5 50%, #EDE9E1 75%)',
            backgroundSize: '200% 100%', animation: 'shimmer 1.4s ease-in-out infinite',
          }} />
          <div style={{ flex: 1 }}>
            <div style={{
              height: 12, borderRadius: 6, width: `${w * 100}%`, marginBottom: 6,
              background: 'linear-gradient(90deg, #EDE9E1 25%, #E2DDD5 50%, #EDE9E1 75%)',
              backgroundSize: '200% 100%', animation: 'shimmer 1.4s ease-in-out infinite',
            }} />
            <div style={{
              height: 9, borderRadius: 6, width: `${Math.max(w - 0.15, 0.3) * 100}%`,
              background: 'linear-gradient(90deg, #EDE9E1 25%, #E2DDD5 50%, #EDE9E1 75%)',
              backgroundSize: '200% 100%', animation: 'shimmer 1.4s ease-in-out infinite',
            }} />
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * @param {object} p
 * @param {string} p.placeholder
 * @param p.value
 * @param {function} p.onLocationSelect
 * @param {boolean} p.isActive
 * @param {function} p.onClick
 * @param {{ lat: number, lon: number, strategy?: string }} p.searchBias — proximity + remote-endpoint bias
 */
export default function AddressAutocomplete({
  placeholder,
  value,
  onLocationSelect,
  isActive,
  onClick,
  searchBias,
}) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const [focused, setFocused] = useState(false);
  const debouncedQuery = useDebounce(query, 320);
  const wrapperRef = useRef(null);
  const inputRef = useRef(null);
  const justSelected = useRef(false);

  const biasKey = useMemo(
    () => `${searchBias?.lat?.toFixed(4)}_${searchBias?.lon?.toFixed(4)}_${searchBias?.strategy || ''}`,
    [searchBias]
  );

  useEffect(() => {
    if (value) {
      if (typeof value === 'string') setQuery(value);
      else if (value?.label) setQuery(value.label);
      else if (Array.isArray(value)) setQuery(`${value[0].toFixed(4)}, ${value[1].toFixed(4)}`);
    } else {
      setQuery('');
      justSelected.current = false;
    }
  }, [value]);

  useEffect(() => {
    if (justSelected.current) {
      justSelected.current = false;
      return;
    }

    if (!debouncedQuery || debouncedQuery.trim().length < 1) {
      setResults([]);
      setShowDropdown(false);
      return;
    }

    const selectedLabel = value?.label || (typeof value === 'string' ? value : null);
    if (selectedLabel && debouncedQuery === selectedLabel) return;

    const bias = searchBias && Number.isFinite(searchBias.lat) && Number.isFinite(searchBias.lon)
      ? searchBias
      : { lat: 12.996, lon: 77.663 };

    const controller = new AbortController();

    async function run() {
      setLoading(true);
      try {
        const mapped = await fetchGeocodingSuggestions(debouncedQuery, bias, controller.signal);
        setResults(mapped);
        setShowDropdown(true);
      } catch (e) {
        if (e.name !== 'AbortError') console.error('Geocoding error:', e);
      } finally {
        setLoading(false);
      }
    }

    run();
    return () => controller.abort();
  }, [debouncedQuery, biasKey, value]);

  useEffect(() => {
    const handler = (e) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target)) {
        setShowDropdown(false);
        setFocused(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const handleSelect = (place) => {
    const lat = parseFloat(place.lat);
    const lon = parseFloat(place.lon);
    const pair = normalizeLatLonPair(lat, lon);
    if (!pair) return;

    const parts = place.display_name.split(',').map((s) => s.trim());
    const label = parts.slice(0, 4).join(', ');

    justSelected.current = true;

    setQuery(label);
    setShowDropdown(false);
    setResults([]);
    onLocationSelect({ coords: pair, label });
  };

  const hasValue = !!value;
  const showLoader = loading;
  const showClear = hasValue && !loading;

  const inputBg = isActive || focused ? '#EEF4FD' : hasValue ? '#F4F0EA' : '#F7F4EF';
  const inputBorder = isActive || focused ? '#A8C5F5' : hasValue ? '#D8D2C8' : 'transparent';

  return (
    <div ref={wrapperRef} style={{ position: 'relative', width: '100%' }} onClick={onClick}>
      <style>{`
        @keyframes dotBounce {
          0%, 80%, 100% { transform: translateY(0); }
          40% { transform: translateY(-5px); }
        }
        @keyframes shimmer {
          0% { background-position: -200% 0; }
          100% { background-position: 200% 0; }
        }
        @keyframes luma-fadeUp {
          from { opacity: 0; transform: translateY(6px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>

      <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
        <input
          ref={inputRef}
          type="text"
          placeholder={placeholder}
          value={query}
          onChange={(e) => {
            justSelected.current = false;
            setQuery(e.target.value);
            if (!isActive) onClick();
          }}
          onFocus={() => {
            setFocused(true);
            if (results.length > 0 && !justSelected.current) setShowDropdown(true);
          }}
          onBlur={() => setFocused(false)}
          style={{
            width: '100%',
            minWidth: 0,
            paddingTop: 10, paddingBottom: 10, paddingLeft: 12, paddingRight: 40,
            fontSize: 13.5,
            fontWeight: 500,
            color: '#1C1917',
            background: inputBg,
            border: `1.5px solid ${inputBorder}`,
            borderRadius: 12,
            outline: 'none',
            transition: 'background 200ms, border-color 200ms',
            cursor: 'text',
            textOverflow: 'ellipsis',
            overflow: 'hidden',
            whiteSpace: 'nowrap',
          }}
        />

        <div style={{ position: 'absolute', right: 10, display: 'flex', alignItems: 'center', pointerEvents: 'none' }}>
          {showLoader && <DotLoader />}
          {showClear && (
            <button
              style={{
                pointerEvents: 'auto',
                width: 22, height: 22,
                borderRadius: '50%',
                background: '#E8E2D9',
                border: 'none',
                cursor: 'pointer',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                transition: 'background 150ms',
                flexShrink: 0,
              }}
              onMouseEnter={(e) => { e.currentTarget.style.background = '#D9D2C8'; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = '#E8E2D9'; }}
              onClick={(e) => {
                e.stopPropagation();
                justSelected.current = false;
                setQuery('');
                setResults([]);
                setShowDropdown(false);
                onLocationSelect(null);
              }}
              aria-label="Clear"
            >
              <svg width="10" height="10" viewBox="0 0 24 24" fill="#6B6259">
                <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z" />
              </svg>
            </button>
          )}
        </div>
      </div>

      {showDropdown && (
        <div style={{
          position: 'absolute',
          zIndex: 1100,
          left: -14,
          right: -14,
          top: 'calc(100% + 8px)',
          background: '#FEFCF8',
          border: '1.5px solid #E2DBD2',
          borderRadius: 16,
          boxShadow: '0 -10px 40px rgba(48,40,28,0.16)',
          overflow: 'hidden',
          animation: 'luma-fadeUp 0.18s ease-out',
        }}>
          {searchBias?.strategy === 'remote_endpoint' && (
            <div style={{
              padding: '9px 14px',
              fontSize: 10,
              fontWeight: 700,
              color: '#1557B0',
              background: '#E8F0FE',
              borderBottom: '1px solid #D7E3FC',
              letterSpacing: '0.04em',
            }}>
              Searching near your other stop (different city / far away)
            </div>
          )}
          {loading && results.length === 0 && <ResultSkeleton />}

          {results.length > 0 && (
            <ul style={{ listStyle: 'none', margin: 0, padding: '6px 0', maxHeight: 320, overflowY: 'auto' }}>
              {results.map((place, idx) => (
                <li
                  key={place.place_id}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    handleSelect(place);
                  }}
                  style={{
                    padding: '11px 14px',
                    cursor: 'pointer',
                    borderBottom: idx < results.length - 1 ? '1px solid #F0EBE2' : 'none',
                    transition: 'background 150ms',
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = '#F5F0E8'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
                >
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 11 }}>
                    <div style={{
                      width: 32, height: 32, borderRadius: '50%',
                      background: '#EDE9E1',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      flexShrink: 0,
                    }}>
                      <svg width="15" height="15" viewBox="0 0 24 24" fill="#8D8578">
                        <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z" />
                      </svg>
                    </div>
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div style={{ fontSize: 13, fontWeight: 600, color: '#1C1917', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', lineHeight: 1.35 }}>
                        {place.name || place.display_name.split(',')[0]}
                      </div>
                      <div style={{ fontSize: 11, color: '#9C9284', fontWeight: 500, marginTop: 3, lineHeight: 1.45, whiteSpace: 'normal' }}>
                        {place.display_name}
                      </div>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}

          {!loading && results.length === 0 && debouncedQuery?.length >= 1 && (
            <div style={{ padding: '22px 16px', textAlign: 'center' }}>
              <p style={{ fontSize: 13, color: '#9C9284', fontWeight: 600 }}>No places found</p>
              <p style={{ fontSize: 11, color: '#B0A899', marginTop: 4 }}>Try different spelling or a landmark</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
