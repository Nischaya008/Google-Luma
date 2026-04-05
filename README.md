# Google Luma: Fear-Free Night Navigator

An AI-powered navigation system that prioritizes psychological safety over Estimated Time of Arrival (ETA).

<p align="center">
  <img src="https://github.com/Nischaya008/Google-Luma/blob/main/assets/Heatmap.png?raw=true" 
       alt="GoogleLuma Banner" 
       width="600">
</p>

---

## Brief Summary

Modern navigation systems optimize for speed, often routing users through unsafe environments such as poorly lit roads, isolated areas, or high-crime zones especially during nighttime. Google Luma introduces a **Safety Score** as a primary routing metric, replacing traditional ETA-based optimization.

The system computes safety at the road-segment level using an XGBoost-based regression model trained on multi-modal geospatial features including VIIRS satellite lighting data, KDE-based crime density, POI-derived footfall proxies, weather risk, and real-time computer vision signals. By integrating these signals into a multi-objective routing pipeline, Google Luma generates routes that are both **statistically and perceptually safer**, while maintaining practical constraints on travel time.

---

## Problem Statement

### What?
An AI-driven routing system that prioritizes **psychological and structural safety** over shortest distance or time.

### Why?
Conventional routing algorithms (A*, Dijkstra variants) optimize purely for traversal cost, ignoring human-centric risk factors. At night, this results in routing through unsafe corridors such as:
- Dark alleys
- Low-footfall zones
- High crime-density regions

### For Whom?
- Women and solo travelers  
- Night-shift workers  
- Tourists unfamiliar with local geography  

### Real-World Insight
Urban safety is **spatio-temporal**. A road safe at 7 PM may become unsafe at 3 AM. Static heuristics fail to capture this dynamic risk landscape.

<p align="center">
  <img src="https://github.com/Nischaya008/Google-Luma/blob/main/assets/Route.png?raw=true" 
       alt="GoogleLuma Banner" 
       width="600">
</p>

---

## Impact

- Improves corridor lighting exposure by ~40% compared to fastest routes  
- Reduces traversal through high-risk zones significantly  
- Eliminates cognitive load of unsafe navigation  

This system directly addresses **urban mobility inequity**, especially for vulnerable populations.

---

## Use of AI

### 1. XGBoost Regression
- Captures non-linear feature interactions
- Provides explainability via feature importance

### 2. Computer Vision (YOLOS-tiny via ONNX)
- Detects environmental safety signals in real time

### 3. Isolation Forest
- Detects anomalous unsafe environments

### 4. LLM (Groq)
- Generates human-readable safety explanations

### Why AI is Necessary
Safety is inherently non-linear and context-dependent. Rule-based systems fail to model temporal interactions such as:
- Lighting importance increasing at night
- Footfall relevance varying with time

<p align="center">
  <img src="https://github.com/Nischaya008/Google-Luma/blob/main/assets/Flowchart.png?raw=true" 
       alt="GoogleLuma Banner" 
       width="600">
</p>

---

## Design Idea and Approach

### System Overview

Google Luma operates as a multi-layered asynchronous pipeline:

1. **Topology Engine (OSRM)**
   - Generates k=3 geometrically diverse routes using perpendicular waypoint forcing.

2. **Feature Engineering Layer**
   - Enriches edges with:
     - VIIRS lighting intensity
     - KDE crime density
     - POI-based footfall proxies
     - Weather risk
     - Vegetation isolation

3. **Safety Scoring Engine**
   - XGBoost regression model computes safety score per edge.
   - Live CV feed augments predictions:
     ```text
     Final Score = 0.70 * Model + 0.30 * CV
     ```

### Core Algorithm Design

#### Graph Model
The road network is modeled as a directed multigraph:
```text
G = (V, E)
```

#### Safety Score Function
```text
S(e) = f(lighting, crime_density, footfall, poi_density, weather, vegetation, time)
```

#### Routing Cost Function
```text
Cost = α * Duration + β * (1 - SafetyScore)
```

#### Route Constraints
- Maximum detour: 1.8× shortest path
- Pareto-based route selection
- Spatial diversity enforced via perpendicular offsets

---

## Scalability & Architecture

- Graph size: ~150K–250K edges per city  
- Memory constraint: ~512MB  
- Stateless APIs with externalized computation  
- 3-tier caching ensures O(1) retrieval under load  

### Technologies Used

- **Backend:** FastAPI (asynchronous, non-blocking ML inference)
- **Routing:** OSRM (eliminates O(n²) graph overhead)
- **Geospatial:** NetworkX, OSMnx, GeoPandas, Shapely
- **Machine Learning:**
  - XGBoost (primary safety model)
  - ONNX Runtime (YOLOS-tiny for CV)
  - Isolation Forest (anomaly detection)
- **Caching & State:**
  - Upstash Redis (hot layer)
  - Supabase PostgreSQL + Storage (warm/cold)
- **Frontend:** React + Vite + Leaflet

<p align="center">
  <img src="https://github.com/Nischaya008/Google-Luma/blob/main/assets/Tech_Stack.png?raw=true" 
       alt="GoogleLuma Banner" 
       width="600">
</p>

---

## Data Strategy

- **VIIRS Night Lights:** 11.6GB raster → compressed `.npz` tiles  
- **Crime Data:** KDE-smoothed density maps  
- **OSM Data:** POIs used as footfall proxies  
- **Weather:** Real-time risk scoring  

### Missing Data Handling
- Percentile clipping (5–95%)
- Probabilistic fallback for missing lighting

---

## Evaluation & Testing

### 1. Model Performance (Empirical Evaluation)

Synthetic evaluation conducted on 10,000 road segments:

#### Feature Importance
```text
is_night               : 49.7%
lighting_score         : 25.1%
crime_density          : 7.7%
footfall_proxy         : 6.5%
weather_risk           : 5.8%
poi_density            : 2.6%
vegetation_isolation   : 2.5%
length_m               : 0.1%
```

#### Regression Metrics
- **MAE:** 0.0031  
- **MSE:** ~0.0000  
- **R² Score:** 0.9983  
- **Inference Time (10k edges):** 8.03 ms  

These results demonstrate:
- Near-perfect regression fit
- High sensitivity to temporal and lighting features
- Real-time inference capability

### 2. System Performance (Latency & Scalability)

#### Multi-Tier Cache Latency
| Layer | Latency |
|------|--------|
| In-Memory (LRU) | 1–5 ms |
| Redis (Hot Cache) | 45–80 ms |
| Supabase (Warm) | 200–400 ms |
| Dynamic OSMnx (Fallback) | 2.5–4.5 s |

#### End-to-End Performance
- Cache hit: <200 ms  
- Fresh query: <3 s  
- Cold start (graph init): ~40 s  

#### Throughput
- Supports ~40 QPS on free-tier infrastructure

### 3. Routing Evaluation Metrics

- **Route Deviation Factor:** ≤ 1.8× baseline  
- **Safety Gradient:** High variance between routes ensures meaningful differentiation  
- **Observed Behavior:**  
  - Fastest routes → low-lit shortcuts  
  - Safest routes → arterial, well-lit corridors  

### 4. Failure Modes

| Scenario | Issue | Mitigation |
|----------|------|-----------|
| Large OSRM geometry | Frontend overload | Route sampling |
| Sparse data regions | Weak safety signal | Probabilistic fallback |
| CV false positives | Overestimation of safety | Weighted blending |

---

## Privacy & Security

- No user identifiers stored  
- Coordinates anonymized via bounding boxes  
- CV frames processed in-memory only  
- No persistent storage of image data  

---

## Feasibility

- Built within 72 hours using open datasets  
- Fully deployable on free-tier infrastructure  
- No GPU dependency due to ONNX optimization  
- Scales horizontally via region-based sharding  

---

## Alternatives Considered

| Approach | Issue |
|--------|------|
| A* with dynamic weights | High latency (>40s) |
| Graph Neural Networks | GPU-heavy, marginal gain |
| PyTorch DETR | 800MB footprint, deployment infeasible |

---

## How to Run

### Backend
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

---

## Repository Structure

```text
GoogleLuma/
├── backend/
├── frontend/
├── docs/
```

---

## Future Work

- Client-side CV inference (ONNX Web / TFJS)
- RLHF-based route adaptation
- Audio-based safety navigation
- Integration with ride-sharing APIs

---

## References

- OpenStreetMap (OSM)
- NOAA VIIRS Nighttime Lights
- Public Crime Datasets (Kaggle, Govt portals)
- Spatial Syntax Theory (Jacobs, 1961)

---

## Appendix

- Coordinate System: EPSG:4326
- Multi-objective optimization via Pareto frontier
- Route constraint: distance ≤ 1.8× shortest path
