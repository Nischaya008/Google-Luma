# Google Luma — Complete Technical Guide

> **Safety-Aware Geospatial Navigation Engine**
> A comprehensive reference for understanding every component, model, formula, data source, and design decision in the Google Luma system.

---

## Table of Contents

1. [High-Level Architecture](#1-high-level-architecture)
2. [Application Lifecycle & Startup](#2-application-lifecycle--startup)
3. [The Routing Engine (OSRM)](#3-the-routing-engine-osrm)
4. [The Safety Scoring Pipeline](#4-the-safety-scoring-pipeline)
5. [Data Sources — Where Everything Comes From](#5-data-sources--where-everything-comes-from)
6. [Feature Engineering — The Math Behind Safety](#6-feature-engineering--the-math-behind-safety)
7. [The ML Model — XGBoost Safety Regressor](#7-the-ml-model--xgboost-safety-regressor)
8. [Route Scoring — How a Route Gets Its Safety Score](#8-route-scoring--how-a-route-gets-its-safety-score)
9. [The 3-Tier Cache System](#9-the-3-tier-cache-system)
10. [Real-Time Computer Vision Module](#10-real-time-computer-vision-module)
11. [LLM-Powered Contextual Evaluation](#11-llm-powered-contextual-evaluation)
12. [Ambient Context — OpenStreetMap Overpass](#12-ambient-context--openstreetmap-overpass)
13. [Temporal & Weather Context](#13-temporal--weather-context)
14. [Google Earth Engine Integration (NDVI)](#14-google-earth-engine-integration-ndvi)
15. [The Database Layer — Supabase Postgres](#15-the-database-layer--supabase-postgres)
16. [Frontend Architecture](#16-frontend-architecture)
17. [API Contract — Endpoints & Schemas](#17-api-contract--endpoints--schemas)
18. [Deployment Architecture](#18-deployment-architecture)
19. [Design Decisions & Tradeoffs](#19-design-decisions--tradeoffs)
20. [Complete Data Flow — End to End](#20-complete-data-flow--end-to-end)

---

## 1. High-Level Architecture

Google Luma is a **safety-aware navigation engine** that goes beyond traditional shortest-path routing. For any origin–destination pair, it computes three route variants — **Fastest**, **Balanced**, and **Safest** — each scored using real-world safety data from satellite imagery, crime statistics, urban infrastructure, and live weather conditions.

### System Diagram

```
┌───────────────────────────────────────────────────────────────────┐
│                      FRONTEND (React + Vite)                      │
│  Leaflet Map │ Geocoding │ Route Panel │ Live Camera Safety View  │
└────────────────────────────┬──────────────────────────────────────┘
                             │ HTTPS (JSON API)
                             ▼
┌───────────────────────────────────────────────────────────────────┐
│                   BACKEND (FastAPI + Uvicorn)                     │
│                                                                   │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────────┐   │
│  │ OSRM Router │  │ Safety Model │  │ CV Analyzer (ONNX)      │   │
│  │ (Geometry)  │  │ (XGBoost)    │  │ YOLOS-Tiny Detection    │   │
│  └──────┬──────┘  └──────┬───────┘  └────────────┬────────────┘   │
│         │                │                       │                │
│  ┌──────▼────────────────▼────────────────────────▼────────────┐  │
│  │              Feature Engineering Pipeline                   │  │
│  │  VIIRS │ Crime KDE │ OSM POI │ GEE NDVI │ Weather │ Time    │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                   │
│  ┌───────────────── 3-Tier Cache ────────────────────────────┐    │
│  │  Tier 0: In-Memory LRU Graph Registry                     │    │
│  │  Tier 1: Upstash Redis (hot, <50ms, 5-min TTL)            │    │
│  │  Tier 2: Supabase Postgres + Storage (persistent, <2s)    │    │
│  └───────────────────────────────────────────────────────────┘    │
└───────────────────────────────────────────────────────────────────┘
         │            │             │              │
         ▼            ▼             ▼              ▼
    NASA VIIRS   OSM Overpass   OpenWeatherMap   Groq/Llama 3.1
    (Satellite)  (POI Data)    (Live Weather)   (AI Insights)
```

### Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Backend** | FastAPI 0.109 + Uvicorn | Async Python API server |
| **ML** | XGBoost 2.0.3 | Safety score regression |
| **Graph** | NetworkX 3.2 + OSMnx 1.9 | Road network modeling |
| **CV** | ONNX Runtime + YOLOS-Tiny | Real-time object detection |
| **Spatial** | GeoPandas, Rasterio, Shapely | Geospatial data processing |
| **LLM** | Groq (Llama 3.1 8B Instant) | Contextual safety insights |
| **Cache L1** | Upstash Redis (REST) | Hot ephemeral cache |
| **Cache L2** | Supabase (Postgres + S3) | Persistent warm/cold cache |
| **Frontend** | React 18 + Vite + Leaflet | Interactive map UI |
| **Geocoding** | Open-Meteo + Photon + Nominatim | Address search (3-provider) |

---

## 2. Application Lifecycle & Startup

### Entry Point: `main.py`

The server starts via a **FastAPI lifespan** context manager, not `@app.on_event("startup")`.

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Phase 1: Bind the port IMMEDIATELY (prevents Render timeout)
    logger.info("Google Luma API starting...")

    # Phase 2: Background pre-loading (non-blocking)
    asyncio.create_task(_preload_safety_data())

    yield  # Server is now running

    # Shutdown cleanup
    logger.info("Shutting down...")
```

**Why this pattern matters (for deployment):** Render's free tier performs a port scan within 60 seconds of container start. If the server doesn't bind to `$PORT` in time, it's killed. Heavy imports (OSMnx, XGBoost, Rasterio) can take 15–30 seconds. The lifespan pattern ensures the port is bound **before** any heavy work begins.

### Background Pre-Loading Task

```python
async def _preload_safety_data():
    """Pre-load heavy data in background to avoid cold-start latency."""
    from services.data_loaders import CrimeDataLoader
    from services.cv_analyzer import CVSafetyAnalyzer

    # 1. Load and geocode crime data + fit KDE
    loader = CrimeDataLoader()
    loader.get_kde_model()

    # 2. Download & cache YOLOS-Tiny ONNX model
    analyzer = CVSafetyAnalyzer.get_instance()
    analyzer.ensure_loaded()
```

### Custom CORS Middleware

Google Luma uses a **custom `RawCORSMiddleware`** instead of FastAPI's built-in `CORSMiddleware`. This design is deliberate:

```python
class RawCORSMiddleware(BaseHTTPMiddleware):
    """
    Bomb-proof CORS middleware.
    - Handles preflight OPTIONS automatically
    - Injects Access-Control-Allow-* headers on EVERY response
    - Works even when CORSMiddleware fails silently on 500s
    """
```

**Why:** The built-in middleware sometimes drops CORS headers on error responses (500s), causing the browser to show a CORS error instead of the actual error message. The custom middleware guarantees headers are always present.

---

## 3. The Routing Engine (OSRM)

### What is OSRM?

**Open Source Routing Machine (OSRM)** is a high-performance C++ routing engine that pre-processes OpenStreetMap road data into a contraction hierarchy for near-instant shortest-path queries. Google Luma uses the **public OSRM demo server** (`router.project-osrm.org`) as its geometry provider.

### File: `services/osrm_router.py`

The `OSRMRouter` class handles all route geometry computation.

### Profile Selection

```python
PROFILES = {
    "driving": "car",    # OSRM "car" profile
    "foot":    "foot",   # OSRM "foot" profile
}
```

The user can toggle between **Drive** and **Walk** mode in the frontend. This changes the OSRM profile, which affects:
- Available roads (pedestrians can use footpaths; cars cannot)
- Speed assumptions (affects ETA)
- Route geometry (walking routes take shortcuts through parks, etc.)

### How Routes Are Fetched

#### Step 1: Native OSRM Alternatives

```python
async def _fetch_osrm_routes(self, src, dst, profile, alternatives=3):
    url = f"{self.base_url}/route/v1/{profile}/{src[1]},{src[0]};{dst[1]},{dst[0]}"
    params = {
        "alternatives": alternatives,
        "overview": "full",
        "geometries": "geojson",
        "steps": "true",           # Turn-by-turn directions
        "annotations": "true",     # Per-segment metadata
    }
```

OSRM returns up to `alternatives` (default: 3) route geometries. Each route includes:
- **`geometry`**: Full polyline as GeoJSON coordinates
- **`legs[].steps[]`**: Turn-by-turn navigation instructions
- **`duration`**: Total travel time in seconds
- **`distance`**: Total distance in meters

#### Step 2: Deduplication

OSRM sometimes returns near-identical alternatives. The deduplication algorithm compares routes by **geometry overlap**:

```python
def _are_routes_similar(self, route_a, route_b, threshold=0.75):
    """
    Two routes are "similar" if >75% of route_b's points are
    within 50m of some point on route_a.
    """
    coords_a = route_a["geometry"]["coordinates"]
    coords_b = route_b["geometry"]["coordinates"]

    # Sample every 5th point for speed
    close_count = 0
    for i in range(0, len(coords_b), 5):
        for j in range(0, len(coords_a), 5):
            dist = haversine(coords_b[i], coords_a[j])
            if dist < 50:  # meters
                close_count += 1
                break
    return (close_count / max(1, len(coords_b) // 5)) > threshold
```

#### Step 3: Forced Alternative Generation

If OSRM doesn't return enough distinct routes, Luma **forces** alternatives by injecting perpendicular waypoints:

```python
def _generate_forced_waypoints(self, src, dst, offsets_km=[1.5, 3.0, 5.0]):
    """
    Generate waypoints perpendicular to the src→dst bearing.
    Each offset creates two waypoints (one on each side of the line).
    """
    bearing = self._calculate_bearing(src, dst)
    perp_bearing_left = (bearing - 90) % 360
    perp_bearing_right = (bearing + 90) % 360

    mid_lat = (src[0] + dst[0]) / 2
    mid_lon = (src[1] + dst[1]) / 2

    waypoints = []
    for offset in offsets_km:
        # Haversine destination formula
        wp_left = self._destination_point(mid_lat, mid_lon, perp_bearing_left, offset)
        wp_right = self._destination_point(mid_lat, mid_lon, perp_bearing_right, offset)
        waypoints.extend([wp_left, wp_right])
    return waypoints
```

These waypoints pull the route **away from the direct line** in different directions, then OSRM routes through the waypoint to create genuinely different paths.

### OSRM Step Extraction

For each route, OSRM provides turn-by-turn steps with:

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Road name (e.g., "NH48", "MG Road") |
| `ref` | string | Road reference number |
| `distance_m` | float | Segment distance in meters |
| `duration_s` | float | Segment travel time in seconds |
| `maneuver` | object | Turn type at start of segment |
| `geometry` | GeoJSON | Segment polyline |

---

## 4. The Safety Scoring Pipeline

This is the core innovation of Google Luma. Every road segment on every route is scored for safety on a **[0.0, 1.0] scale** (0 = dangerous, 1 = safe) using multiple real-world data sources.

### Pipeline Overview

```
Route Geometry (OSRM)
        │
        ▼
┌─────────────────────────────────────────────────┐
│            PER-SEGMENT FEATURE EXTRACTION         │
│                                                   │
│  1. LIGHTING  ← VIIRS satellite night radiance    │
│  2. CRIME     ← KDE on geocoded incident datasets │
│  3. POI       ← OSM Overpass (shops, police, etc) │
│  4. ROAD TYPE ← OSM highway classification        │
│  5. WEATHER   ← OpenWeatherMap live API           │
│  6. TIME      ← Solar hour approximation          │
│  7. NDVI      ← Google Earth Engine (vegetation)  │
│  8. FOOTFALL  ← Composite proxy (light+road+POI)  │
│  9. AMBIENT   ← Overpass POI density radius query  │
└─────────────────────┬───────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────┐
│        XGBOOST SAFETY REGRESSOR (per-edge)       │
│  Input: 9 normalized features → Output: [0, 1]   │
└─────────────────────┬───────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────┐
│       LENGTH-WEIGHTED ROUTE AGGREGATION          │
│  75% weighted mean + 25% worst-20% penalty       │
└─────────────────────┬───────────────────────────┘
                      │
                      ▼
           Route Safety Score [0, 1]
```

---

## 5. Data Sources — Where Everything Comes From

### 5.1 Crime Data (4 Datasets)

**File:** `services/data_loaders.py` → `CrimeDataLoader`

| Dataset | File | Records | Coverage | Fields Used |
|---------|------|---------|----------|-------------|
| **Crime Incidents** | `crime_incidents_geocoded.csv` | ~170K | US cities | `latitude`, `longitude`, `crime_type` |
| **District Crime** | `district_crime_processed.csv` | ~18K | India districts | District names → geocoded |
| **State Crime** | `state_crime_processed.csv` | ~6K | India states | State names → geocoded |
| **Global Cities** | `global_crime_index.csv` | ~500 | Worldwide cities | City names → geocoded |

#### Geocoding Pipeline

The district and state datasets don't have coordinates — they have names like "Mumbai" or "Karnataka." The system **geocodes** them on first load:

```python
def _geocode_districts(self, df):
    """Geocode Indian district names to lat/lon using geopy.Nominatim."""
    from geopy.geocoders import Nominatim
    geolocator = Nominatim(user_agent="google-luma")

    for idx, row in df.iterrows():
        location = geolocator.geocode(f"{row['district']}, India")
        if location:
            df.at[idx, 'latitude'] = location.latitude
            df.at[idx, 'longitude'] = location.longitude
```

#### Kernel Density Estimation (KDE)

All crime coordinates are merged into one array and fed into **scikit-learn's `KernelDensity`** estimator:

```python
def _fit_kde(self, all_coords):
    """
    Fit a Gaussian KDE on all crime incident coordinates.

    Bandwidth: Scott's rule-of-thumb ≈ n^(-1/(d+4))
    Kernel: Gaussian (standard for density estimation)
    Metric: Haversine (great-circle distance on Earth)
    """
    from sklearn.neighbors import KernelDensity

    coords_rad = np.radians(all_coords)  # KDE with haversine needs radians

    kde = KernelDensity(
        bandwidth=0.02,       # ~2.2 km effective radius
        metric='haversine',
        kernel='gaussian',
        algorithm='ball_tree',
    )
    kde.fit(coords_rad)
    return kde
```

**What KDE does:** For any point on Earth, it estimates the **probability density** of crime occurring there. High density = historically high crime area. The bandwidth of 0.02 radians (~2.2 km) means crime influence "bleeds" about 2 km in each direction.

#### Formula: Crime Density at Point P

```
crime_density(P) = (1/n·h^d) × Σᵢ K((P - xᵢ) / h)
```

Where:
- `n` = total crime points
- `h` = bandwidth (0.02 radians)
- `K` = Gaussian kernel function
- `xᵢ` = each crime coordinate
- `d` = dimensions (2 for lat/lon)

#### Regional Crime Multiplier

For areas without detailed incident data, the system falls back to a **regional multiplier** based on city-level crime indices:

```python
def get_regional_crime_multiplier(self, city_name):
    """
    Scale crime density based on the global crime index of the nearest city.
    Returns a multiplier [0.5, 2.0].
    """
    if city_name in self.global_index:
        raw = self.global_index[city_name]  # 0-100 scale
        return 0.5 + (raw / 100.0) * 1.5    # Maps [0,100] → [0.5, 2.0]
    return 1.0  # Neutral
```

### 5.2 VIIRS Night Light Satellite Imagery

**Source:** NASA's **Visible Infrared Imaging Radiometer Suite (VIIRS)** Day/Night Band (DNB) monthly composites.

**Format:** GeoTIFF raster, 11.6 GB global file at ~500m/pixel resolution.

**What it measures:** Nighttime surface radiance in nanowatts/cm²/sr. Brighter values indicate:
- Street lighting
- Commercial activity
- Populated areas with electrical infrastructure

#### Pre-Processing Pipeline

**File:** `services/viirs_preprocessor.py`

The 11.6 GB global file is **not shipped to production**. Instead, a one-time offline script clips it into city-level tiles:

```python
def clip_viirs_for_city(city_name, center_lat, center_lon, viirs_path):
    """
    1. Define bounding box: center ± city_radius + 5.5 km padding
    2. Clip the GeoTIFF using rasterio.windows.from_bounds()
    3. Clean: replace negative/nodata values with 0
    4. Save as compressed .npz (numpy)
    5. Upload to Supabase Storage under viirs-tiles/
    """
    with rasterio.open(viirs_path) as src:
        window = from_bounds(west, south, east, north, src.transform)
        data = src.read(1, window=window)
        data = np.maximum(data, 0.0).astype(np.float32)
```

**City coordinates** are defined in `core/config.py`:

```python
CITY_COORDINATES = {
    "Bengaluru": (12.9716, 77.5946),
    "New Delhi": (28.6139, 77.2090),
    "Mumbai": (19.0760, 72.8777),
    "Chennai": (13.0827, 80.2707),
    "Hyderabad": (17.3850, 78.4867),
    # ... 20+ cities
}
```

#### How VIIRS Becomes a Feature

In `feature_engineering.py`, the VIIRS tile is **sampled at each road segment's midpoint**:

```python
def _compute_viirs_lighting(self, midpoints, viirs_tile):
    """
    For each road segment midpoint:
    1. Map lat/lon to pixel coordinates in the tile
    2. Read the radiance value (nW/cm²/sr)
    3. Normalize to [0, 1] using log scaling

    Formula: lighting = clip(log1p(radiance) / log1p(max_radiance), 0, 1)
    """
    brightness = viirs_tile["brightness"]
    bbox = viirs_tile["bbox"]  # [north, south, east, west]

    for lat, lon in midpoints:
        row = int((bbox[0] - lat) / (bbox[0] - bbox[1]) * brightness.shape[0])
        col = int((lon - bbox[3]) / (bbox[2] - bbox[3]) * brightness.shape[1])
        radiance = brightness[row, col]
        score = np.log1p(radiance) / np.log1p(brightness.max())
```

**Fallback when VIIRS is unavailable:** Road type estimates lighting:

| Road Type | Estimated Lighting Score |
|-----------|------------------------|
| motorway | 0.90 |
| primary | 0.80 |
| secondary | 0.65 |
| tertiary | 0.50 |
| residential | 0.40 |
| unclassified | 0.25 |

### 5.3 OpenStreetMap POI Data (Overpass API)

**File:** `services/data_loaders.py` → `POILoader`

Points of Interest represent **eyes on the street** — areas with commercial activity, services, and foot traffic are empirically safer.

```python
def extract_osm_pois(G):
    """
    Query the Overpass API for safety-relevant POIs within the graph bounds.

    Categories queried:
    - amenity=police, hospital, clinic, pharmacy
    - amenity=restaurant, cafe, bar
    - amenity=fuel (24h gas stations = natural surveillance)
    - shop=* (all commercial shops)
    - tourism=hotel, museum
    - highway=street_lamp

    Returns: list of (lat, lon) tuples
    """
    query = f"""
    [out:json][timeout:25];
    (
      node["amenity"~"police|hospital|clinic|pharmacy|restaurant|cafe|fuel"]
        ({south},{west},{north},{east});
      node["shop"]({south},{west},{north},{east});
      node["highway"="street_lamp"]({south},{west},{north},{east});
    );
    out center;
    """
```

**API Endpoint:** `https://overpass-api.de/api/interpreter`

### 5.4 Ambient Overpass Context

**File:** `services/ambient_overpass.py`

A **separate, more targeted** Overpass query that runs per-corridor to capture the immediate surroundings of a route:

```python
QUERY_TEMPLATE = """[out:json][timeout:10];
(
  node["amenity"="police"](around:{radius},{lat},{lon});
  node["amenity"="hospital"](around:{radius},{lat},{lon});
  node["amenity"="clinic"](around:{radius},{lat},{lon});
  node["amenity"="pharmacy"](around:{radius},{lat},{lon});
  node["shop"](around:{radius},{lat},{lon});
  node["amenity"="restaurant"](around:{radius},{lat},{lon});
  node["amenity"="cafe"](around:{radius},{lat},{lon});
  node["amenity"="fuel"](around:{radius},{lat},{lon});
  node["highway"="street_lamp"](around:{radius},{lat},{lon});
);
out;
"""
```

#### Ambient Score Formula

```python
def _counts_to_ambient_score(counts):
    """
    Weighted scoring of detected POI categories.
    Each category is capped and normalized independently.
    """
    police  = min(1.0, counts["police"]  / 2.0)   # 2 stations = max
    medical = min(1.0, counts["medical"] / 2.0)   # 2 facilities = max
    shop    = min(1.0, counts["shop"]    / 28.0)   # 28 shops = max
    food    = min(1.0, counts["food"]    / 18.0)   # 18 restaurants = max
    lamp    = min(1.0, counts["lamp"]    / 24.0)   # 24 lamps = max
    fuel    = min(1.0, counts["fuel"]    / 6.0)    # 6 stations = max

    return (0.20 * police  +
            0.18 * medical +
            0.22 * shop    +
            0.18 * food    +
            0.12 * lamp    +
            0.10 * fuel)
```

**Design rationale:** Police and medical facilities have the highest weights because they directly indicate formal guardianship and emergency access. A single police station within the radius is highly meaningful.

### 5.5 Live Weather (OpenWeatherMap)

**File:** `services/weather_service.py`

**API:** `https://api.openweathermap.org/data/2.5/weather` (free tier, 60 calls/min)

Weather is the **only dynamic feature** that must never be served stale.

#### Cache Hierarchy (Weather-Specific)

```
Tier 1: Redis (5-minute TTL)    ← Shared across instances
Tier 2: In-memory dict (5-min)  ← Per-instance fallback
Tier 3: OWM API (live)          ← Source of truth
```

#### Weather Penalty Formula

```python
def compute_weather_penalty(self, lat, lon):
    """
    Compute [0.0, 1.0] penalty. 0.0 = perfect, 1.0 = worst.
    """
    penalty = 0.0

    # Visibility penalty (meters)
    if visibility < 1000:  penalty += 0.50   # Extremely low
    elif visibility < 3000: penalty += 0.30  # Poor
    elif visibility < 5000: penalty += 0.15  # Moderate

    # Precipitation penalty
    if "thunderstorm" in main: penalty += 0.40
    elif "rain" in main:       penalty += 0.20
    elif "snow" in main:       penalty += 0.30
    elif "fog" in main:        penalty += 0.25

    # Wind penalty
    if wind_speed > 15:        penalty += 0.10

    return min(penalty, 1.0)
```

#### Weather Buckets (for Cache Keying)

Routes are cached **per weather bucket** so a rain storm invalidates only rain-context caches:

| Penalty Range | Bucket |
|--------------|--------|
| 0.0 – 0.1 | `clear` |
| 0.1 – 0.3 | `mild` |
| 0.3 – 0.6 | `rain` |
| 0.6 – 1.0 | `storm` |

---

## 6. Feature Engineering — The Math Behind Safety

**File:** `services/feature_engineering.py` → `SafetyFeatureEngineer`

### The 9 Features

For every edge (road segment) in the graph, the pipeline computes these normalized [0, 1] features:

| # | Feature | Source | Formula | Higher = |
|---|---------|--------|---------|----------|
| 1 | `lighting_score` | VIIRS / road-type fallback | `log1p(radiance) / log1p(max)` | Brighter (safer) |
| 2 | `crime_density` | KDE on merged crime datasets | `clip(exp(log_density) / max_density, 0, 1)` | More crime (less safe) |
| 3 | `poi_density` | OSM POI coords + KDE | `nearby_pois / max(nearby)` | More activity (safer) |
| 4 | `road_class` | OSM highway tag | See lookup table | Higher class (safer) |
| 5 | `is_night` | Astral library (sunrise/sunset) | Binary: 0 or 1 | Night = riskier |
| 6 | `weather_risk` | OWM penalty | Visibility + precip + wind | More severe (riskier) |
| 7 | `footfall_proxy` | Composite | `0.35×light + 0.40×area + 0.25×road` | More foot traffic (safer) |
| 8 | `vegetation_isolation` | GEE NDVI × (1 – POI) | NDVI scaled × inverse urbanity | More isolated (riskier) |
| 9 | `length_m` | Graph edge length | Meters (used for weighting) | — |

### Day/Night Detection

```python
from astral import LocationInfo
from astral.sun import sun

def compute_is_night(self, lat, lon):
    """
    Uses the 'astral' library to compute exact sunrise/sunset
    for the given coordinates and current UTC time.

    Returns: 1 if night, 0 if day
    """
    loc = LocationInfo(latitude=lat, longitude=lon)
    s = sun(loc.observer, date=datetime.now(timezone.utc))
    now = datetime.now(timezone.utc)
    return int(now < s["sunrise"] or now > s["sunset"])
```

### Road Class Normalization

```python
ROAD_CLASS_SCORES = {
    # Major roads: well-maintained, lit, patrolled
    "motorway": 0.95,  "motorway_link": 0.90,
    "trunk": 0.90,     "trunk_link": 0.85,
    "primary": 0.85,   "primary_link": 0.80,

    # Medium roads: moderate infrastructure
    "secondary": 0.70, "secondary_link": 0.65,
    "tertiary": 0.55,  "tertiary_link": 0.50,

    # Local roads: variable quality
    "residential": 0.40,
    "service": 0.30,
    "unclassified": 0.25,
    "track": 0.15,
    "path": 0.10,
}
```

### Edge Midpoint Computation

Each graph edge has a start and end node. The feature is computed at the **midpoint**:

```python
def _compute_edge_midpoints(self, G, gdf_edges):
    """
    For each edge (u, v, key):
      start = (G.nodes[u]['y'], G.nodes[u]['x'])
      end   = (G.nodes[v]['y'], G.nodes[v]['x'])
      mid   = ((start[0]+end[0])/2, (start[1]+end[1])/2)
    """
    midpoints = np.array([
        [(G.nodes[u]['y'] + G.nodes[v]['y']) / 2,
         (G.nodes[u]['x'] + G.nodes[v]['x']) / 2]
        for u, v, _ in G.edges(keys=True)
    ])
    return midpoints
```

### Footfall Proxy Computation

**File:** `services/safety_context.py`

Since actual pedestrian count data requires proprietary mobility feeds, Luma uses a **proxy** combining multiple signals:

```python
def compute_footfall_proxy(point_light, area_light, road_class):
    """
    Proxy for expected human presence along a segment.

    Components:
    - point_light (35%): VIIRS radiance at the segment midpoint
    - area_light  (40%): Average VIIRS radiance in surrounding area
    - road_class  (25%): Higher-class roads draw more traffic

    Formula: footfall = 0.35 × point + 0.40 × area + 0.25 × road
    """
    return 0.35 * point_light + 0.40 * area_light + 0.25 * road_class
```

### Static vs. Dynamic Feature Split

The system **separates static and dynamic features** for caching efficiency:

| Static Features (cached for hours) | Dynamic Features (always live) |
|-------------------------------------|-------------------------------|
| `lighting_score` | `weather_risk` |
| `crime_density` | `is_night` |
| `poi_density` | `footfall_proxy` (depends on time) |
| `vegetation_isolation` | |
| `length_m` | |

Static features are computed once and stored in **Supabase as Parquet files**. Dynamic features are merged at query time.

---

## 7. The ML Model — XGBoost Safety Regressor

**File:** `services/safety_model.py` → `SafetyModel`

### Architecture

- **Model Type:** XGBoost Gradient Boosted Decision Tree Regressor
- **Target:** Continuous safety score [0.0, 1.0]
- **Training:** Per-region (each geographic area gets its own model)
- **Persistence:** Pickle + gzip → Supabase Storage

### Training — Synthetic Label Generation

The model is trained on **heuristic labels** derived from the feature values themselves, not manually labeled data:

```python
def _generate_heuristic_labels(self, features_df):
    """
    Generate synthetic safety labels from real features.

    Formula:
    label = (
        0.25 × lighting_score        # Well-lit = safer
      + 0.25 × (1 - crime_density)   # Low crime = safer
      + 0.15 × poi_density           # Commercial activity = safer
      + 0.10 × road_class            # Major roads = safer
      + 0.10 × (1 - weather_risk)    # Good weather = safer
      + 0.10 × footfall_proxy        # Foot traffic = safer
      + 0.05 × (1 - is_night×0.3)    # Daytime = slightly safer
    )

    Why this works: The model learns non-linear interactions between
    features that a simple weighted average misses. For example, a
    well-lit road with zero POIs at 2am should score lower than the
    linear combination suggests.
    """
```

### Hyperparameters

```python
model = XGBRegressor(
    n_estimators=100,           # Number of boosting rounds
    max_depth=6,                # Maximum tree depth
    learning_rate=0.1,          # Step size shrinkage
    subsample=0.8,              # Random subsampling ratio
    colsample_bytree=0.8,      # Feature subsampling per tree
    min_child_weight=3,         # Minimum leaf node heuristic weight
    reg_alpha=0.1,              # L1 regularization
    reg_lambda=1.0,             # L2 regularization
    objective='reg:squarederror',
    random_state=42,
)
```

### Feature Importance Tracking

After training, the model's feature importances are extracted and stored in Supabase:

```python
importance = dict(zip(feature_names, model.feature_importances_))
# Example output:
# {
#   "lighting_score": 0.23,
#   "crime_density": 0.21,
#   "poi_density": 0.14,
#   "road_class": 0.12,
#   "weather_risk": 0.10,
#   "footfall_proxy": 0.09,
#   "is_night": 0.06,
#   "vegetation_isolation": 0.05,
# }
```

### Model Caching

```
1. Check Supabase ml_models table for existing model
2. If found → download pickle from Storage → decompress → use
3. If not → train on current graph's features → persist to Storage
4. Cache trained model in memory for subsequent requests
```

---

## 8. Route Scoring — How a Route Gets Its Safety Score

**File:** `services/route_scorer.py` → `RouteSafetyScorer`

### Per-Step Safety Scoring

For each OSRM step (road segment), the scorer:

1. **Identifies the graph edges** that the step geometry passes through
2. **Retrieves pre-computed safety scores** for those edges (from XGBoost)
3. **Computes a length-weighted average** of the edge scores for that step

```python
def _score_step(self, step, G, edge_scores):
    """
    Map an OSRM step to graph edges and aggregate their safety scores.

    1. Snap step start/end to nearest graph nodes
    2. Find shortest path between those nodes
    3. Collect safety scores for edges along the path
    4. Length-weighted average of edge scores = step safety score
    """
    start_node = ox.nearest_nodes(G, step["start_lon"], step["start_lat"])
    end_node = ox.nearest_nodes(G, step["end_lon"], step["end_lat"])
    path = nx.shortest_path(G, start_node, end_node, weight="length")

    total_length = 0
    weighted_sum = 0
    for u, v in zip(path[:-1], path[1:]):
        edge_data = G[u][v][0]
        length = edge_data.get("length", 0)
        score = edge_scores.get((u, v, 0), 0.5)
        weighted_sum += score * length
        total_length += length

    return weighted_sum / max(total_length, 1)
```

### Route-Level Aggregation — Risk-Averse Strategy

The overall route safety is **not** a simple average. Google Luma uses a **risk-averse aggregation** that penalizes routes with dangerous segments:

```python
def score_route(self, steps, step_scores):
    """
    Route Safety = 75% × length_weighted_mean + 25% × worst_20_percent_mean

    Why:
    A route that is 90% safe but passes through a 500m death trap
    should NOT score 90%. The 25% penalty on the worst 20% of segments
    ensures that dangerous stretches drag the score down significantly.
    """
    # Length-weighted mean of ALL steps
    total_len = sum(s["distance_m"] for s in steps)
    weighted_mean = sum(
        score * steps[i]["distance_m"] / max(total_len, 1)
        for i, score in enumerate(step_scores)
    )

    # Bottom 20% penalty
    sorted_scores = sorted(step_scores)
    cutoff = max(1, int(len(sorted_scores) * 0.2))
    worst_20 = sorted_scores[:cutoff]
    worst_mean = sum(worst_20) / len(worst_20)

    # Risk-averse blend
    raw_safety = 0.75 * weighted_mean + 0.25 * worst_mean
    return max(0.0, min(1.0, raw_safety))
```

### Temporal Safety Adjustment

**File:** `services/safety_context.py`

After the base safety score is computed, a **temporal drag factor** is applied:

```python
def apply_temporal_safety_adjustment(base_safety, temporal_risk, is_night, max_drag=0.12):
    """
    Down-weight safety during high temporal_risk; stronger at night.

    Multiplicative tail formula:
    adjusted = base_safety × (1 - max_drag × temporal_risk × night_factor)

    Where night_factor = 1.0 at night, 0.55 during day
    max_drag = 0.12 (caps total adjustment at 12%)
    """
    drag = max_drag * temporal_risk * (1.0 if is_night else 0.55)
    return base_safety * (1.0 - drag)
```

#### Temporal Risk by Hour

```python
def _temporal_risk_from_local_hour(h):
    """
    Piecewise risk function of local solar hour:

    08:00 – 19:00 → 0.06  (daytime: minimal risk)
    19:00 – 23:00 → 0.35 to 0.82  (linear ramp: evening transition)
    23:00 – 04:00 → 0.82  (late night: peak risk)
    04:00 – 08:00 → 0.45 to 0.06  (pre-dawn: declining risk)
    """
```

### Multi-Objective Route Labeling

After all three routes are scored, they're labeled by objective:

```python
def _label_routes(self, routes):
    """
    - FASTEST: lowest duration_seconds
    - SAFEST:  highest average_safety_score
    - BALANCED: the remaining route (middle ground)
    """
    sorted_by_time = sorted(routes, key=lambda r: r["duration_seconds"])
    sorted_by_safety = sorted(routes, key=lambda r: r["average_safety_score"], reverse=True)

    fastest = sorted_by_time[0]
    safest = sorted_by_safety[0]
    balanced = [r for r in routes if r not in (fastest, safest)][0]

    fastest["mode"] = "fastest"
    safest["mode"] = "safest"
    balanced["mode"] = "balanced"
```

---

## 9. The 3-Tier Cache System

**File:** `cache/cache_manager.py` → `CacheManager`

The cache is designed to eliminate redundant computation across requests.

### Tier 0: In-Memory Graph Registry

```python
class GraphRegistry:
    """
    LRU cache for loaded NetworkX graphs.
    - Keyed by: "{center_lat}_{center_lon}_{radius}km"
    - Max size: configurable (default: 10 graphs)
    - Stores: graph, features, annotation context
    - Thread-safe: per-region asyncio.Lock
    """
```

**Critical optimization:** The registry stores the **annotation context** — the `time_context` (day/night) and `weather_bucket` (clear/mild/rain/storm) under which the graph was last annotated with safety scores. If the context hasn't changed, subsequent requests skip the **entire ML pipeline** (feature engineering + XGBoost inference + route scoring):

```python
async def check_annotation_context(self, region_key, time_context, weather_bucket):
    """
    If cached graph was annotated under the same time+weather context,
    return it directly. Reduces latency from ~30s to <1s.
    """
```

### Tier 1: Upstash Redis

**File:** `cache/redis_client.py`

- **Transport:** REST-based (not TCP) — works in serverless environments
- **SDK:** `upstash-redis` Python package
- **TTLs:** Route cache = 1 hour, Heatmap = 30 min, Weather = 5 min

```python
class RedisClient:
    """
    REST-based Redis client for Upstash.
    All operations are fault-tolerant — failures return None/False.
    Supports: get/set strings, get_json/set_json, cache-aside pattern.
    """
```

### Tier 2: Supabase Postgres + Storage

**File:** `db/supabase_client.py` + `services/storage_service.py`

| Table | Purpose | Key | Expiry |
|-------|---------|-----|--------|
| `region_graphs` | Graph metadata | `(lat, lon, radius)` | 30 days |
| `cached_features` | Static feature DFs | `graph_id` | 24 hours |
| `route_cache` | Computed routes | `(origin, dest, mode, time)` | 1 hour |
| `poi_cache` | Overpass API results | `bbox_key` | 7 days |
| `viirs_tiles` | VIIRS brightness tiles | `city_name` | Permanent |
| `ml_models` | Trained XGBoost models | `(region_key, model_type)` | Permanent |
| `kde_models` | Crime KDE models | `data_hash` | Permanent |

**Storage (S3-compatible):** Heavy binary data is stored in Supabase Storage:
- **Graphs:** `.graphml.gz` (gzip compressed — 52 MB → ~5 MB)
- **Features:** `.parquet.gz` (Parquet with built-in compression)
- **Models:** `.pkl.gz` (Pickle + gzip)
- **VIIRS Tiles:** `.npz` (NumPy compressed)

### Cache Cascade Flow

```
Request arrives
    │
    ▼
Tier 0: In-memory graph? ──── YES → Check annotation context
    │                                    │
    NO                              SAME context? ── YES → Return cached scores (<1s)
    │                                    │
    ▼                               NO (re-annotate)
Tier 2: Supabase graph? ──── YES → Download from Storage
    │                                    │
    NO                                   ▼
    │                              Load into memory (Tier 0)
    ▼
Tier 3: Fresh download from OSMnx (~30-60s)
    │
    ▼
Upload to Supabase (persist for future users)
    │
    ▼
Load into memory (Tier 0)
```

---

## 10. Real-Time Computer Vision Module

### Overview

The CV module provides **real-time environmental safety analysis** using the device camera during active navigation. It captures frames every 2 seconds, runs object detection, and produces a blended safety score.

### File: `services/cv_analyzer.py` → `CVSafetyAnalyzer`

### YOLOS-Tiny Object Detection (ONNX)

**File:** `services/onnx_detector.py` → `ONNXDetector`

| Property | Value |
|----------|-------|
| **Model** | YOLOS-Tiny (Xenova/yolos-tiny ONNX export) |
| **Architecture** | YOLOS = ViT-based DETR variant (Vision Transformer) |
| **Training Data** | COCO 2017 (80 object classes) |
| **Model Size** | ~7 MB (INT8 quantized) vs ~800 MB for torch+DETR |
| **Runtime** | ONNX Runtime (CPU only — no GPU required) |
| **Input** | Variable-size RGB images, ImageNet normalized |
| **Output** | Detection queries with class logits + bounding boxes |

**Why ONNX instead of PyTorch:**
1. No DLL conflicts on Windows (eliminates `WinError 1114`)
2. ~7 MB vs ~800 MB memory footprint
3. Fits within Render free tier (512 MB RAM)
4. Faster cold start — no torch runtime overhead
5. Same detection quality (COCO-80 classes)

### Model Download & Caching

```python
MODEL_VARIANTS = [
    "onnx/model_quantized.onnx",  # ~7MB  INT8 (recommended)
    "onnx/model_uint8.onnx",      # ~7MB  UINT8 (alternative)
    "onnx/model.onnx",            # ~25MB FP32 (fallback)
]
```

The model is downloaded from **HuggingFace Hub** on first use and cached locally by `huggingface_hub`.

### Inference Pipeline

```
Camera Frame (JPEG 640px, 70% quality, ~30-50KB)
        │
        ▼
1. PREPROCESS
   - Resize to max 512px (preserving aspect ratio)
   - Convert to float32 [0, 1]
   - Normalize: (pixel - ImageNet_mean) / ImageNet_std
     Mean: [0.485, 0.456, 0.406]
     Std:  [0.229, 0.224, 0.225]
   - Transpose: HWC → NCHW

        │
        ▼
2. ONNX INFERENCE
   - Input: [1, 3, H, W] float32 tensor
   - Output:
     - logits: [1, num_queries, 92] (COCO IDs)
     - pred_boxes: [1, num_queries, 4] (normalized [cx, cy, w, h])

        │
        ▼
3. POSTPROCESS
   - Softmax on logits (excluding "no object" class at index 91)
   - Filter by confidence threshold (default: 0.5)
   - Convert boxes: normalized [cx,cy,w,h] → pixel [x1,y1,x2,y2]
   - Filter to safety-relevant labels only

        │
        ▼
4. SAFETY SCORING
   - Count: people, vehicles, infrastructure
   - Brightness: HSV V-channel mean
   - Compute weighted CV score
```

### Safety-Relevant COCO Labels

```python
PEOPLE_LABELS = {"person"}
VEHICLE_LABELS = {"car", "bus", "truck", "motorcycle", "bicycle"}
INFRASTRUCTURE_LABELS = {"traffic light", "fire hydrant", "stop sign", "parking meter", "bench"}
```

### Brightness Analysis (HSV)

```python
def _analyze_brightness(self, image):
    """
    Convert to HSV color space.
    V-channel (Value) = brightness.

    brightness = mean(V) / 255.0          → [0, 1]
    uniformity = max(0, 1 - 2×std(V)/255) → [0, 1]
    """
```

### CV Safety Score Formula

```python
cv_score = (
    0.35 × brightness       +    # Lighting (35%)
    0.30 × crowd_score      +    # Pedestrian presence (30%)
    0.20 × vehicle_score    +    # Vehicle traffic (20%)
    0.15 × structure_score       # Infrastructure (15%)
)
```

Where:
- `crowd_score = min(1.0, people_count / 8)`
- `vehicle_score = min(1.0, vehicle_count / 6)`
- `structure_score = min(1.0, infra_count / 3)`

### Anomaly Detection (Isolation Forest)

**File:** `services/cv_analyzer.py` → `_check_anomaly()`

The system maintains a **rolling window** of feature vectors from recent frames. An **Isolation Forest** (scikit-learn) is fitted on this window to detect anomalous frames — sudden darkness, deserted stretches, etc.

```python
self._anomaly_detector = IsolationForest(
    contamination=0.15,   # 15% expected anomaly rate
    random_state=42,
    n_estimators=50,      # Fewer trees for real-time constraint
)
```

- **Window size:** 30 frames (60 seconds at 2fps)
- **Minimum frames before activation:** 10 (20 seconds)
- **Feature vector:** `[brightness, people_count, vehicle_count, infra_count]`

### Blended Score (CV + Route ML)

**File:** `api/routes/cv.py`

The CV score is blended with the pre-computed ML route safety score:

```python
def blend_scores(cv_score, route_safety_score=None, cv_weight=0.4):
    """
    final = cv_weight × cv_score + (1 - cv_weight) × route_safety_score

    Default: 40% CV + 60% ML route score

    If route_safety_score is None (no route computed), use CV score alone.
    """
    if route_safety_score is None:
        return cv_score
    return cv_weight * cv_score + (1 - cv_weight) * route_safety_score
```

### CV Explainer (Rule-Based)

**File:** `services/cv_explainer.py`

Instead of using an LLM (which would add latency and hallucination risk), the CV module uses **deterministic rule-based templates**:

```python
# Example outputs:
# "Safe corridor — well-lit environment, busy sidewalk with 8 people visible,
#  active traffic (3 cars, 1 bus). traffic light detected nearby."

# "Elevated risk area — very dark area — poor visibility.
#  Concern: no pedestrians in a dark area — isolated, no traffic on a deserted stretch."

# "⚠ POTENTIAL RISK ZONE — Below-average safety — dim lighting.
#  Concern: no pedestrians detected, no vehicles detected nearby."
```

**Why rule-based:**
1. **Deterministic** — no hallucination risk for safety-critical information
2. **Sub-millisecond latency** — critical for 2-second frame cycle
3. **No external API dependency** — works offline
4. **References actual detected objects** ("3 pedestrians", "2 cars")

---

## 11. LLM-Powered Contextual Evaluation

**File:** `services/llm_safety_evaluator.py` → `LLMSafetyEvaluator`

### Purpose

The LLM evaluator provides **qualitative, contextual reasoning** about routes using actual safety data. Unlike the CV explainer (which is rule-based), this uses Groq's hosted Llama 3.1 8B Instant model.

### Provider & Model

| Property | Value |
|----------|-------|
| **Provider** | Groq (groq.com) |
| **Model** | `llama-3.1-8b-instant` |
| **Temperature** | 0.15 (nearly deterministic) |
| **Response Format** | Structured JSON |

### How It Works

1. **Build data-rich summaries** for each route (actual road names, per-step safety scores, distances)
2. **Construct a prompt** with strict rules preventing hallucination
3. **Parse JSON response** containing `ai_insight` and `contextual_modifier`

### Prompt Structure

```python
prompt = f"""You are an expert navigation safety analyst. Analyze these {num_routes} route option(s)
using the ACTUAL safety data provided.

{route_summaries}  # Contains real road names, distances, safety scores

IMPORTANT RULES:
- Reference the ACTUAL road names and safety scores shown above.
- If roads are unnamed, say "unnamed local roads" and reference the safety score.
- Explain WHY this route scores the way it does.
- Do NOT fabricate road names that aren't in the data above.

Respond in valid JSON with key "evaluations" — a list of exactly {num_routes} objects:
1. "ai_insight": 1-2 specific sentences using the real data above.
2. "contextual_modifier": float between -0.10 and +0.10.
"""
```

### Contextual Modifier

The LLM can apply a **±10% adjustment** to the safety score based on geographic knowledge not captured in the data:

```python
# LLM might output:
{
  "ai_insight": "NH48 highway (7.2km) scores 0.72 due to national highway classification
     and strong VIIRS lighting. The unnamed 2.1km stretch near Kengeri scores 0.48 —
     flagged for limited street lighting.",
  "contextual_modifier": -0.03
}

# Applied as:
adjusted_score = raw_safety_score + contextual_modifier
# Bounded to [0.0, 1.0]
```

---

## 12. Ambient Context — OpenStreetMap Overpass

**File:** `services/ambient_overpass.py`

### Cache Strategy

The ambient score is cached using **quantized integer coordinates** (millidegrees) to avoid float hashing issues:

```python
@lru_cache(maxsize=512)
def _cached_ambient_score(lat_q: int, lon_q: int) -> float:
    """
    lat_q/lon_q are millidegree integers: int(round(lat*1000))
    This gives ~100m quantization — stable cache keys without float quirks.
    """
```

### Empty Data Handling

```python
# When OSM has no data for a region (sparse mapping):
if not elements:
    score = max(score, 0.22)  # Floor at 0.22, not 0.0

# WHY: Missing OSM data doesn't mean the area is dangerous —
# it means OSM hasn't been mapped there yet.
# A 0.22 floor prevents false alarms in unmapped regions.
```

---

## 13. Temporal & Weather Context

**File:** `services/safety_context.py`

### Solar Hour Approximation

Instead of depending on timezone databases, Luma uses **solar longitude approximation**:

```python
def approximate_local_hour(lon, utc_now=None):
    """
    Every 15° of longitude ≈ 1 hour offset from UTC.
    Local solar hour = UTC_hour + longitude/15

    Example: Mumbai (lon=72.88°) at 18:00 UTC
    → local ≈ 18 + 72.88/15 = 22.86 (≈10:52 PM local)
    """
    utc_decimal = now.hour + now.minute/60 + now.second/3600
    local = (utc_decimal + lon / 15.0) % 24.0
    return local
```

### Time-of-Day Risk Curve

```
Risk ▲
1.0  │            ┌──────────────────┐
0.82 │            │   PEAK RISK      │
     │       ╱────┘   (23:00-04:00)  └────╲
0.45 │      ╱                              ╲
0.35 │     ╱  EVENING     PRE-DAWN          ╲
     │    ╱  RAMP-UP      DECLINE            ╲
0.06 │───┘  (19:00-23:00)  (04:00-08:00)     └───
     │    DAYTIME (08:00-19:00)
0.0  └────────────────────────────────────────── Hour
     0  4  8  12  16  20  24
```

---

## 14. Google Earth Engine Integration (NDVI)

**File:** `services/earth_engine_service.py`

### What is NDVI?

**Normalized Difference Vegetation Index** measures vegetation density using satellite infrared imagery:

```
NDVI = (NIR - Red) / (NIR + Red)
```

Where:
- **NIR** = Near-Infrared reflectance (Sentinel-2 Band B8)
- **Red** = Red visible light (Sentinel-2 Band B4)

| NDVI Value | Interpretation |
|-----------|---------------|
| < 0.1 | Water, bare ground, urban concrete |
| 0.1 – 0.3 | Sparse vegetation, suburban |
| 0.3 – 0.6 | Moderate vegetation |
| > 0.6 | Dense forest, heavy vegetation |

### Safety Implication

**High vegetation + Low POI density = Isolated rural area = Lower safety at night.**

```python
def compute_vegetation_isolation(self, midpoints, poi_density):
    """
    isolation = vegetation_score × (1 - poi_density)

    Where: vegetation_score = clip((NDVI - 0.1) / 0.7, 0, 1)

    A dense forest with shops nearby → low isolation (safe)
    A dense forest with zero POIs → high isolation (risky at night)
    """
```

### GEE Data Source

- **Satellite:** Copernicus Sentinel-2 Surface Reflectance (Harmonized)
- **Collection:** `COPERNICUS/S2_SR_HARMONIZED`
- **Filter:** Last 30 days, < 30% cloud cover, median composite
- **Resolution:** 100m (reduced from native 10m for API speed)

### Graceful Degradation

GEE is **optional**. If credentials are not configured, the service returns `np.zeros(N)` — vegetation isolation has zero impact on safety scores, and the rest of the pipeline continues normally.

---

## 15. The Database Layer — Supabase Postgres

**File:** `db/schema.sql`

### Schema Overview

```sql
-- Road network graph metadata
region_graphs (
    id UUID PRIMARY KEY,
    center_lat FLOAT, center_lon FLOAT, radius_km INT,
    node_count INT, edge_count INT,
    storage_path TEXT,           -- "graphs/28.62_77.22_5km.graphml.gz"
    expires_at TIMESTAMPTZ      -- Default: NOW() + 30 days
)

-- Cached safety features (links to region_graphs)
cached_features (
    graph_id UUID → region_graphs(id) ON DELETE CASCADE,
    storage_path TEXT,           -- "features/28.62_77.22_5km.parquet.gz"
    edge_count INT,
    expires_at TIMESTAMPTZ      -- Default: NOW() + 24 hours
)

-- Pre-computed route results
route_cache (
    origin_lat, origin_lon, dest_lat, dest_lon,
    mode TEXT,                   -- "fastest" | "balanced" | "safest"
    time_context TEXT,           -- "day" | "night"
    weather_bucket TEXT,         -- "clear" | "mild" | "rain" | "storm"
    route_geometry JSONB,
    average_safety_score FLOAT,
    expires_at TIMESTAMPTZ      -- Default: NOW() + 1 hour
)

-- OSM Overpass results cache
poi_cache (
    bbox_key TEXT UNIQUE,        -- "28.62_28.65_77.55_77.60"
    poi_data JSONB,              -- [{lat, lon}, ...]
    expires_at TIMESTAMPTZ       -- Default: NOW() + 7 days
)

-- Pre-processed VIIRS brightness tiles
viirs_tiles (
    city_name TEXT UNIQUE,       -- "bengaluru"
    storage_path TEXT,           -- "viirs-tiles/bengaluru.npz"
)

-- Trained ML models
ml_models (
    region_key TEXT,             -- "28.62_77.22_5km"
    model_type TEXT,             -- "xgboost"
    storage_path TEXT,           -- "models/28.62_77.22_5km.pkl.gz"
    feature_importance JSONB,
)
```

---

## 16. Frontend Architecture

### Technology

| Component | Technology |
|-----------|-----------|
| **Framework** | React 18 (Vite build tooling) |
| **Map** | Leaflet (via react-leaflet) |
| **State** | React hooks (no Redux/Zustand) |
| **Styling** | Inline styles + utility CSS classes |
| **Geocoding** | 3-provider cascade |

### Component Tree

```
App.jsx
├── TravelModeIsland          ← Drive/Walk toggle
├── Sidebar                    ← Search panel (source + destination)
│   ├── LocationInput (×2)     ← Autocomplete search boxes
│   └── Search/Swap buttons
├── MapView                    ← Leaflet map (full screen)
│   ├── HeatmapLayer          ← Safety heatmap overlay
│   ├── Route polylines        ← Color-coded routes
│   └── Source/Dest markers
├── RoutePanel                 ← Route comparison cards
│   ├── Route card (×3)        ← Fastest/Balanced/Safest
│   └── Live Safety button
├── LiveSafetyView             ← Camera overlay (mobile)
│   ├── Video feed
│   ├── Safety gauge
│   └── Detection annotations
├── RecentRoutesPanel          ← Previously searched routes
├── HeatmapLoadingModal        ← Progress modal during heatmap gen
└── ToastNotification          ← Error/info toasts
```

### Geocoding Service (3-Provider Cascade)

**File:** `services/geocoding.js`

The search box queries **three geocoding providers simultaneously** and merges results:

| Provider | API | Strengths | Bias |
|----------|-----|-----------|------|
| **Open-Meteo** | `geocoding-api.open-meteo.com` | Population-ranked cities | Global |
| **Photon** | `photon.komoot.io` | OSM detail (streets, POIs) | Location-biased |
| **Nominatim** | `nominatim.openstreetmap.org` | Global search (unbounded) | None |

#### Ranking Algorithm

Results are ranked by a composite score:

```javascript
composite = nameTier × 4
           + (shortQuery ? popScore × 2.2 : popScore × 1.4)
           - distPenalty
           + (nominatim && exactMatch ? 0.3 : 0)
```

Where:
- `nameTier`: 3 = exact prefix, 2 = display starts with query, 1 = contains, 0 = no match
- `popScore`: `log10(population + 1)` — major cities bubble up
- `distPenalty`: Haversine distance from bias point / 3500
- Short queries (≤2 chars) emphasize population; longer queries emphasize distance

### State Management: `useRoutes` Hook

**File:** `hooks/useRoutes.js`

Central state management for the entire routing lifecycle:

```javascript
const {
  source,          // { coords: [lat, lon], label: "..." } | null
  destination,     // { coords: [lat, lon], label: "..." } | null
  travelProfile,   // "driving" | "foot"
  routes,          // Array of route objects from backend
  rankings,        // Which route is fastest/safest
  tradeoffs,       // Time/safety tradeoff metrics
  selectedRoute,   // "fastest" | "balanced" | "safest"
  heatmapData,     // Edge safety data for heatmap overlay
  loading,         // Boolean
  error,           // Error message string | null
  findRoutes,      // () => fetch all 3 routes
  loadHeatmap,     // ({ lat, lng }) => fetch heatmap data
} = useRoutes();
```

### Live Safety Hook

**File:** `hooks/useLiveSafety.js`

Manages the camera-based real-time safety analysis:

```javascript
// Frame capture every 2 seconds
const FRAME_INTERVAL_MS = 2000;
const CAPTURE_WIDTH = 640;  // Max dimension

// Camera: rear-facing (environment)
const stream = await navigator.mediaDevices.getUserMedia({
  video: { facingMode: { ideal: 'environment' } },
  audio: false,
});

// Capture: canvas → base64 JPEG at 70% quality (~30-50KB)
const frameData = canvas.toDataURL('image/jpeg', 0.7);

// Send to backend → receive CV analysis results
const result = await analyzeCameraFrame(frameData, routeSafetyScore);
```

### Map Initialization Flow

```
App mounts
    │
    ▼
Start 60-second GPS countdown
    │
    ├── GPS acquired? → Center map on user location
    │                    POST /api/v1/routing/init (pre-warm)
    │
    └── 60s timeout? → Center map on Bengaluru (default)
                        Show "default location" indicator
```

### Safety Score Visualization

```javascript
// Color gradient: Red (0) → Yellow (0.5) → Green (1.0)
function safetyToColor(score) {
    if (score <= 0.5) {
        // Red → Yellow transition
        const ratio = score / 0.5;
        return `rgb(234, ${67 + 121*ratio}, ${53 - 49*ratio})`;
    }
    // Yellow → Green transition
    const ratio = (score - 0.5) / 0.5;
    return `rgb(${249 - 197*ratio}, ${171 - 3*ratio}, ${83*ratio})`;
}
```

### Recent Routes (localStorage)

```javascript
const STORAGE_KEY = 'luma_recent_routes_v1';
const RECENT_ROUTES_MAX = 5;

// Deduplication by coordinate fingerprint
function routeFingerprint(src, dest) {
    return `${src[0].toFixed(4)}:${src[1].toFixed(4)}|${dest[0].toFixed(4)}:${dest[1].toFixed(4)}`;
}
```

---

## 17. API Contract — Endpoints & Schemas

### Base URL

- **Development:** `http://localhost:8000/api/v1/routing`
- **Production:** `https://<deployment-url>/api/v1/routing`

### GET `/routes/compare`

**The main endpoint.** Returns all three route variants with safety scores.

**Query Parameters:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `src_lat` | float | Yes | Source latitude |
| `src_lon` | float | Yes | Source longitude |
| `dest_lat` | float | Yes | Destination latitude |
| `dest_lon` | float | Yes | Destination longitude |
| `travel_profile` | string | No | `"driving"` (default) or `"foot"` |

**Response Shape:**

```json
{
  "routes": [
    {
      "mode": "safest",
      "distance_meters": 12450,
      "duration_seconds": 1820,
      "average_safety_score": 0.73,
      "raw_safety_score": 0.71,
      "safety_score": 0.73,
      "ai_insight": "NH48 scores 0.72 due to national highway classification...",
      "geometry": [[12.93, 77.62], [12.94, 77.63]],
      "steps": [
        {
          "name": "NH48",
          "ref": "NH 48",
          "distance_m": 3200,
          "duration_s": 240,
          "maneuver": { "type": "turn", "modifier": "left" }
        }
      ],
      "step_details": [
        { "safety_score": 0.78, "lighting": 0.85, "crime": 0.12 }
      ],
      "travel_profile": "driving"
    }
  ],
  "rankings": { "safest": "safest", "fastest": "fastest" },
  "tradeoff_metrics": {
    "time_vs_safety": { "fastest_saves_minutes": 4.2, "safest_gains_score": 0.08 }
  }
}
```

### POST `/init`

Pre-warms the system by loading the graph for the user's area.

```
POST /api/v1/routing/init?lat=12.996&lng=77.663
```

### GET `/heatmap`

Returns safety-scored edges for the safety heatmap overlay.

```
GET /api/v1/routing/heatmap?lat=12.996&lng=77.663
```

**Response:**

```json
{
  "edges": [
    {
      "geometry": [[12.93, 77.62], [12.94, 77.63]],
      "safety_score": 0.65,
      "highway": "secondary"
    }
  ],
  "region_center": [12.996, 77.663],
  "edge_count": 4523
}
```

### POST `/cv/analyze`

Real-time camera frame analysis.

```json
{
  "frame_base64": "data:image/jpeg;base64,...",
  "route_safety_score": 0.72
}
```

**Response:**

```json
{
  "cv_safety_score": 0.68,
  "final_blended_score": 0.704,
  "brightness": 0.72,
  "brightness_uniformity": 0.85,
  "crowd_count": 3,
  "vehicle_count": 5,
  "infrastructure_count": 1,
  "is_anomaly": false,
  "anomaly_score": 0.12,
  "ai_explanation": "Safe corridor — well-lit environment, moderate foot traffic...",
  "anomaly_label": "",
  "detections": [
    {"label": "person", "confidence": 0.87, "box": [120, 200, 180, 450]},
    {"label": "car", "confidence": 0.93, "box": [300, 150, 500, 300]}
  ]
}
```

### POST `/cv/reset`

Clears the anomaly detection history (called when starting a new session).

### GET `/health`

```json
{ "status": "healthy" }
```

### Pydantic Schemas

**File:** `models/schemas.py`

```python
class RouteRequest(BaseModel):
    source: List[float]       # [lat, lon]
    destination: List[float]  # [lat, lon]
    mode: str = "balanced"    # "fastest" | "balanced" | "safest"

class CVAnalyzeRequest(BaseModel):
    frame_base64: str
    route_safety_score: Optional[float] = None

class CVAnalyzeResponse(BaseModel):
    cv_safety_score: float
    final_blended_score: float
    brightness: float
    crowd_count: int
    vehicle_count: int
    infrastructure_count: int
    is_anomaly: bool
    ai_explanation: str
    detections: List[dict]
```

---

## 18. Deployment Architecture

### Backend (HuggingFace Space / Render)

```
# Multi-worker Uvicorn configuration
uvicorn main:app
  --host 0.0.0.0
  --port $PORT
  --workers 4           # 4 workers for 2 vCPUs + 16 GB RAM
  --loop uvloop         # High-performance event loop
  --http httptools      # Faster HTTP parsing
```

### Frontend (Vercel)

- **Build:** `npm run build` (Vite production bundle)
- **Hosting:** Vercel Edge Network
- **API Proxy:** `VITE_API_URL` environment variable points to backend

### Environment Variables

| Variable | Service | Purpose |
|----------|---------|---------|
| `OWM_API_KEY` | OpenWeatherMap | Live weather data |
| `GROQ_API_KEY` | Groq | LLM safety evaluation |
| `GEE_PROJECT_ID` | Google Earth Engine | NDVI vegetation data |
| `GEE_SERVICE_ACCOUNT_KEY` | Google Cloud | GEE authentication |
| `SUPABASE_URL` | Supabase | Database URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase | Admin access key |
| `REDIS_URL` | Upstash | Redis REST endpoint |
| `REDIS_TOKEN` | Upstash | Redis auth token |
| `HF_TOKEN` | HuggingFace | Model download auth |
| `VITE_API_URL` | Vite | Backend API base URL |

---

## 19. Design Decisions & Tradeoffs

### Why OSRM (Not Custom Graph Routing)?

| Custom A* on OSMnx Graph | OSRM |
|--------------------------|------|
| Requires graph in memory | Pre-compiled contraction hierarchy |
| ~5-30s per route query | <100ms per route query |
| Limited to loaded region | Global coverage via public server |
| No turn-by-turn directions | Full turn-by-turn with maneuvers |

**Decision:** Use OSRM for **geometry** and **turn-by-turn**, but score with our own safety model. OSRM gives us road-level accuracy instantly; our ML pipeline adds the safety dimension.

### Why Heuristic Labels (Not Human Annotations)?

Human annotation would require:
- 100,000+ road segments labeled
- Local knowledge across dozens of cities
- Regular relabeling as conditions change

**Heuristic labels** are derived from real-world data (VIIRS, crime, POIs) and validated by the XGBoost model's ability to learn non-linear interactions. The model outperforms the linear combination it was trained on because it captures feature interactions (e.g., "dark + no POIs + 2am" is worse than the sum of individual penalties suggests).

### Why ONNX (Not PyTorch DETR)?

| PyTorch + DETR | ONNX Runtime + YOLOS-Tiny |
|----------------|--------------------------|
| ~800 MB memory | ~7 MB model |
| DLL conflicts on Windows | No native dependencies |
| Requires CUDA for speed | CPU-optimized (good enough) |
| Slow cold start | Fast load |

### Why Upstash Redis (Not Hosted Redis)?

Upstash uses a **REST-based protocol** — no TCP connection management needed. This works in serverless, edge, and constrained environments where long-lived connections are impractical.

### Why Separate Static/Dynamic Features?

Static features (lighting, crime, POI, vegetation) change slowly (days/weeks). Dynamic features (weather, time) change constantly. By separating them:

- Static features are computed once and cached for **24 hours**
- Dynamic features are merged fresh on every request
- This reduces repeat-request latency from **~30s to <2s**

---

## 20. Complete Data Flow — End to End

Here is the complete flow from the user tapping "Search" to seeing results:

```
1. USER ACTION
   User types "Koramangala" → "Whitefield" and taps Search

2. FRONTEND (App.jsx → useRoutes → api.js)
   - coordsFromLocation() validates both endpoints
   - fetchAllRoutes() sends GET /routes/compare?src_lat=12.93&src_lon=77.62&...

3. BACKEND RECEIVES REQUEST (routing.py → compare_routes)
   - Parse & validate coordinates
   - Determine travel_profile (driving/foot)

4. CACHE CHECK (CacheManager)
   - Compute region key: "12.93_77.68_5km"
   - Check Redis for pre-computed routes
   - If HIT → return immediately (< 200ms)
   - If MISS → continue

5. GRAPH LOADING (CacheManager → GraphManager)
   - Tier 0: In-memory registry → MISS
   - Tier 2: Supabase region_graphs → check for matching (lat, lon, radius)
     - If found → download .graphml.gz from Storage → decompress → load
     - If not → OSMnx download from Overpass API (~30-60s)
       - Tiled download for areas > 7km radius
       - Upload to Supabase for future users

6. ROUTE GEOMETRY (OSRMRouter)
   - Fetch 3+ alternatives from OSRM
   - Deduplicate by geometry overlap (> 75% similarity → remove)
   - Force alternatives via perpendicular waypoint injection if < 3 unique routes
   - Extract turn-by-turn steps from each route

7. FEATURE ENGINEERING (SafetyFeatureEngineer)
   a. Check if static features are cached (memory → Supabase)
      - If cached → load directly
      - If not → compute:
        i.   VIIRS lighting lookup (Supabase tile → pixel sampling)
        ii.  Crime KDE density (pre-fitted model → score_samples())
        iii. POI density (Overpass → KDE distance)
        iv.  Road class normalization (highway tag → [0, 1])
        v.   GEE NDVI vegetation isolation (optional)
   b. Merge dynamic features:
      - Weather penalty (OWM live → penalty formula)
      - is_night (astral sunrise/sunset)
      - Footfall proxy (0.35×light + 0.40×area + 0.25×road)

8. ML SCORING (SafetyModel)
   - Check if trained model exists (Supabase ml_models)
   - If not → train XGBoost on heuristic labels → persist
   - Run inference: features_df → model.predict() → [0, 1] per edge

9. ROUTE SCORING (RouteSafetyScorer)
   - For each OSRM step → snap to graph edges → lookup edge scores
   - Per-step: length-weighted average of edge scores
   - Per-route: 75% weighted mean + 25% worst-20% penalty
   - Apply temporal adjustment (hour-of-day risk)

10. AMBIENT CONTEXT (AmbientOverpassService)
    - Query Overpass for corridor center POIs
    - Compute ambient score (police, medical, shops, food, lamps, fuel)
    - Blend into route safety score

11. LLM EVALUATION (LLMSafetyEvaluator)
    - Build data-rich summaries (road names, per-step scores)
    - Send to Groq → Llama 3.1 8B Instant
    - Parse JSON: ai_insight + contextual_modifier (±0.10)
    - Apply modifier to safety_score

12. ROUTE LABELING
    - Sort by time → label fastest
    - Sort by safety → label safest
    - Remaining → label balanced

13. CACHE STORAGE
    - Store in Redis (1-hour TTL)
    - Store in Supabase route_cache (persist)
    - Update annotation context in memory

14. RESPONSE
    - Return JSON with routes[], rankings, tradeoff_metrics
    - ~2-5s for cached graph, ~30-60s for fresh graph

15. FRONTEND RENDER
    - Draw 3 color-coded polylines on Leaflet map
    - Show route comparison cards (time, distance, safety %)
    - Display AI insight text
    - User can toggle heatmap, start LiveSafety camera, or navigate
```

---

## Summary of All External APIs Used

| API | Provider | Auth | Purpose | Rate Limit |
|-----|----------|------|---------|-----------|
| OSRM Route | project-osrm.org | None (public) | Route geometry & directions | Best-effort |
| Overpass API | overpass-api.de | None (public) | OSM POI data extraction | ~10K/day |
| OpenWeatherMap | openweathermap.org | API key | Live weather conditions | 60 calls/min (free) |
| Groq | groq.com | API key | LLM contextual evaluation | 30 RPM (free) |
| Google Earth Engine | earthengine.google.com | Service account | Sentinel-2 NDVI vegetation | Quota-based |
| HuggingFace Hub | huggingface.co | Token (optional) | YOLOS-Tiny model download | Unlimited |
| Nominatim | nominatim.openstreetmap.org | None | Global geocoding search | 1 req/s |
| Photon | photon.komoot.io | None | OSM-based geocoding | Best-effort |
| Open-Meteo | open-meteo.com | None | Population-ranked geocoding | Unlimited |
| Supabase | supabase.com | Service role key | Database + object storage | Plan-based |
| Upstash Redis | upstash.com | REST token | Hot cache layer | Plan-based |

---

## Key Python Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `fastapi` | 0.109.2 | Web framework |
| `uvicorn` | 0.27.1 | ASGI server |
| `xgboost` | 2.0.3 | Safety ML model |
| `osmnx` | 1.9.1 | Road network download & processing |
| `networkx` | 3.2.1 | Graph data structure & algorithms |
| `scikit-learn` | 1.4.0 | KDE, Isolation Forest, preprocessing |
| `geopandas` | 0.14.3 | Geospatial DataFrames |
| `rasterio` | 1.3.9 | GeoTIFF raster I/O (VIIRS) |
| `numpy` | 1.26.4 | Numerical computing |
| `pandas` | 2.2.0 | Tabular data processing |
| `astral` | 3.2 | Sunrise/sunset calculations |
| `shap` | 0.44.1 | Model explainability |
| `onnxruntime` | >=1.14.0 | YOLOS-Tiny inference |
| `huggingface_hub` | >=0.20.0 | Model download |
| `Pillow` | >=10.0.0 | Image processing |
| `groq` | latest | Groq API client |
| `supabase` | >=2.0.0 | Database/storage client |
| `upstash-redis` | >=1.0.0 | Redis REST client |
| `geopy` | >=2.4.0 | Geocoding |
| `requests` | >=2.31.0 | HTTP client |
| `pyarrow` | >=15.0.0 | Parquet I/O |
| `earthengine-api` | latest | Google Earth Engine |

---

*This guide covers every component, model, formula, data source, algorithm, and design decision in Google Luma. For a national-level presentation, focus on the **safety scoring pipeline** (Sections 4–8), the **multi-source real-world data** (Section 5), and the **real-time CV module** (Section 10) — these are the strongest differentiators.*
