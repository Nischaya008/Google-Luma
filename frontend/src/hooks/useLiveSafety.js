import { useState, useCallback, useRef, useEffect } from 'react';
import { analyzeCameraFrame, resetCVHistory } from '../services/api';

/**
 * Frame capture interval in milliseconds.
 * 2 seconds balances real-time feel with server load.
 * Each frame is ~30-50KB as base64 JPEG at 70% quality.
 */
const FRAME_INTERVAL_MS = 2000;

/** Max dimension for captured frames — keeps bandwidth low */
const CAPTURE_WIDTH = 640;

/**
 * Custom hook managing the live camera safety analysis lifecycle.
 *
 * Handles:
 *   - Camera stream open/close (rear-facing)
 *   - Periodic frame capture (canvas → base64 JPEG)
 *   - Backend API calls for CV analysis
 *   - State management for scores, explanations, anomalies
 *   - Cleanup on unmount (stops stream, clears intervals)
 *
 * @param {Object} params
 * @param {number|null} params.routeSafetyScore - Pre-computed ML safety for blending
 * @param {boolean} params.enabled - Whether the camera feed is active
 */
export default function useLiveSafety({ routeSafetyScore = null, enabled = false }) {
  const [cvScore, setCvScore] = useState(null);
  const [finalScore, setFinalScore] = useState(null);
  const [explanation, setExplanation] = useState('');
  const [isAnomaly, setIsAnomaly] = useState(false);
  const [anomalyLabel, setAnomalyLabel] = useState('');
  const [features, setFeatures] = useState(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState(null);
  const [frameCount, setFrameCount] = useState(0);

  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const streamRef = useRef(null);
  const intervalRef = useRef(null);
  const analyzingRef = useRef(false);
  const routeScoreRef = useRef(routeSafetyScore);

  // Keep route score ref in sync without re-triggering effects
  useEffect(() => {
    routeScoreRef.current = routeSafetyScore;
  }, [routeSafetyScore]);

  /** Start the rear-facing camera stream */
  const startCamera = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: { ideal: 'environment' },
          width: { ideal: 1280 },
          height: { ideal: 720 },
        },
        audio: false,
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
      }
      setError(null);
      return true;
    } catch (err) {
      console.error('Camera access failed:', err);
      setError('Camera access denied. Please allow camera permissions.');
      return false;
    }
  }, []);

  /** Stop camera stream and clear intervals */
  const stopCamera = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  /** Capture current frame as base64 JPEG */
  const captureFrame = useCallback(() => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas || video.readyState < 2) return null;

    const aspect = video.videoWidth / video.videoHeight;
    canvas.width = CAPTURE_WIDTH;
    canvas.height = Math.round(CAPTURE_WIDTH / aspect);

    const ctx = canvas.getContext('2d');
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    // 70% JPEG quality — ~30-50KB per frame
    return canvas.toDataURL('image/jpeg', 0.7);
  }, []);

  /** Analyze a single frame — called by the interval */
  const analyzeFrame = useCallback(async () => {
    // Skip if previous frame still processing (prevents queue buildup)
    if (analyzingRef.current) return;

    const frameData = captureFrame();
    if (!frameData) return;

    analyzingRef.current = true;
    setAnalyzing(true);

    try {
      const result = await analyzeCameraFrame(
        frameData,
        routeScoreRef.current,
      );

      setCvScore(result.cv_safety_score);
      setFinalScore(result.final_blended_score);
      setExplanation(result.ai_explanation);
      setIsAnomaly(result.is_anomaly);
      setAnomalyLabel(result.anomaly_label);
      setFeatures({
        brightness: result.brightness,
        crowdCount: result.crowd_count,
        vehicleCount: result.vehicle_count,
        infraCount: result.infrastructure_count,
        brightnessUniformity: result.brightness_uniformity,
      });
      setFrameCount((c) => c + 1);
      setError(null);
    } catch (err) {
      // Don't set error for transient network failures — keep feed running
      console.error('Frame analysis failed:', err);
    } finally {
      analyzingRef.current = false;
      setAnalyzing(false);
    }
  }, [captureFrame]);

  // Main lifecycle: start/stop camera and analysis loop
  useEffect(() => {
    if (!enabled) {
      stopCamera();
      return;
    }

    let mounted = true;

    (async () => {
      // Reset anomaly history for fresh session
      try {
        await resetCVHistory();
      } catch (e) {
        // Non-critical — continue without reset
      }

      const started = await startCamera();
      if (!started || !mounted) return;

      // Wait for video element to receive data
      const video = videoRef.current;
      if (video) {
        await new Promise((resolve) => {
          if (video.readyState >= 2) resolve();
          else video.onloadeddata = resolve;
        });
      }

      if (!mounted) return;

      // Start periodic analysis
      intervalRef.current = setInterval(() => {
        if (mounted) analyzeFrame();
      }, FRAME_INTERVAL_MS);
    })();

    return () => {
      mounted = false;
      stopCamera();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled]);

  return {
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
  };
}
