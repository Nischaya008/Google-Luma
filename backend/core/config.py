"""
Application configuration management utilizing pydantic-settings.
All paths, API keys, and tunable parameters are centralized here.
"""
from pydantic_settings import BaseSettings
from typing import Dict, List


class Settings(BaseSettings):
    """
    Application settings derived from environment variables.
    Provides type validation and default values.
    """
    PROJECT_NAME: str = "Google Luma Routing Engine"
    VERSION: str = "0.2.0"
    ENVIRONMENT: str = "development"

    # ML Model configuration
    MODEL_PATH: str = "./data/models/safety_model.xgb"

    # Graph data paths
    GRAPH_DATA_DIR: str = "./data/graph"

    # ── Real Dataset Paths ──────────────────────────────────────────────────
    VIIRS_DATA_PATH: str = "./data/viirs/viirs_night_lights.tif"

    # Crime datasets — all 4 real CSV files
    CRIME_INCIDENTS_PATH: str = "./data/crime/dataset_4.csv"      # 40K individual incidents with city + time
    CRIME_DISTRICT_PATH: str = "./data/crime/dataset_2.csv"       # District-level crime rates (300 districts)
    CRIME_STATE_PATH: str = "./data/crime/dataset_3.csv"          # State-level aggregate (IPC 2022)
    CRIME_GLOBAL_PATH: str = "./data/crime/dataset_1.csv"         # Global country-level trends

    # ── API Keys (loaded from .env) ─────────────────────────────────────────
    OWM_API_KEY: str = ""                    # OpenWeatherMap free-tier key
    GEE_PROJECT_ID: str = ""                 # Google Earth Engine project ID
    GEE_SERVICE_ACCOUNT_KEY: str = ""        # Path to GEE service account JSON
    GEMINI_API_KEY: str = ""                 # Google Gemini API key
    GROQ_API_KEY: str = ""                   # Groq API key for Llama

    # ── Supabase (Postgres + Storage) ────────────────────────────────────────
    DATABASE_PASS: str = ""
    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    SUPABASE_STORAGE_BUCKET: str = "luma-cache"

    # ── Upstash Redis ───────────────────────────────────────────────────────
    REDIS_URL: str = ""
    REDIS_TOKEN: str = ""

    # ── Cache TTLs (seconds) ────────────────────────────────────────────────
    GRAPH_CACHE_TTL: int = 2592000      # 30 days — OSM data changes slowly
    FEATURES_CACHE_TTL: int = 86400     # 24 hours — static features
    ROUTE_CACHE_TTL: int = 3600         # 1 hour — routes change with weather/time
    POI_CACHE_TTL: int = 604800         # 7 days — POIs change weekly at most
    VIIRS_CACHE_TTL: int = 7776000      # 90 days — NASA publishes monthly
    HEATMAP_CACHE_TTL: int = 3600       # 1 hour
    MODEL_CACHE_TTL: int = 86400        # 24 hours

    # ── Pre-warming ─────────────────────────────────────────────────────────
    PRE_WARM_CITIES: str = "Bangalore,Delhi,Mumbai,Chennai,Kolkata,Chandigarh,Kochi,Lucknow"

    # ── Memory Management ───────────────────────────────────────────────────
    MAX_CACHED_GRAPHS: int = 5          # LRU eviction threshold for in-memory graphs

    # Pre-warming radius (km) — covers most intra-city routes
    PRE_WARM_RADIUS_KM: int = 15

    # ── Feature Flags ───────────────────────────────────────────────────────
    CACHE_ENABLED: bool = True           # Master switch for all caching
    REDIS_ENABLED: bool = True           # Toggle Redis layer independently

    # ── Feature Engineering Params ──────────────────────────────────────────
    POI_RADIUS_METERS: float = 100.0
    KDE_BANDWIDTH: float = 0.03              # ~3.3km spatial smoothing — matches city-centroid jitter scale
    NIGHT_START_HOUR: int = 18
    NIGHT_END_HOUR: int = 6

    # Crime severity weights — violent crimes contribute more to KDE than property crimes
    CRIME_SEVERITY_WEIGHTS: Dict[str, float] = {
        "Violent Crime": 3.0,
        "Other Crime": 1.0,
        "Fire Accident": 0.5,
        "Traffic Fatality": 1.5,
    }

    # City centroid coordinates for geocoding dataset_4 cities (lat, lon)
    # These are precise centroids for the 29 cities present in dataset_4
    CITY_COORDINATES: Dict[str, tuple] = {
        "Delhi": (28.6139, 77.2090),
        "Mumbai": (19.0760, 72.8777),
        "Bangalore": (12.9716, 77.5946),
        "Hyderabad": (17.3850, 78.4867),
        "Kolkata": (22.5726, 88.3639),
        "Chennai": (13.0827, 80.2707),
        "Pune": (18.5204, 73.8567),
        "Ahmedabad": (23.0225, 72.5714),
        "Jaipur": (26.9124, 75.7873),
        "Lucknow": (26.8467, 80.9462),
        "Kanpur": (26.4499, 80.3319),
        "Surat": (21.1702, 72.8311),
        "Nagpur": (21.1458, 79.0882),
        "Agra": (27.1767, 78.0081),
        "Ludhiana": (30.9010, 75.8573),
        "Visakhapatnam": (17.6868, 83.2185),
        "Thane": (19.2183, 72.9781),
        "Ghaziabad": (28.6692, 77.4538),
        "Indore": (22.7196, 75.8577),
        "Patna": (25.6093, 85.1376),
        "Bhopal": (23.2599, 77.4126),
        "Meerut": (28.9845, 77.7064),
        "Srinagar": (34.0837, 74.7973),
        "Nashik": (20.0063, 73.7897),
        "Vasai": (19.3919, 72.8397),
        "Varanasi": (25.3176, 82.9739),
        "Kalyan": (19.2437, 73.1355),
        "Faridabad": (28.4089, 77.3178),
        "Rajkot": (22.3039, 70.8022),
        "Chandigarh": (30.7333, 76.7794),
        "Kochi": (9.9312, 76.2673),
    }

    # Approximate city radius in degrees for spatial jitter (larger cities get wider spread)
    CITY_RADIUS_DEG: float = 0.04    # ~4.4 km spread for incident geocoding

    # Road-type-based lighting estimation (used when VIIRS tile unavailable)
    ROAD_LIGHTING_SCORES: Dict[str, float] = {
        "motorway": 0.90,
        "motorway_link": 0.85,
        "trunk": 0.80,
        "trunk_link": 0.75,
        "primary": 0.75,
        "primary_link": 0.70,
        "secondary": 0.65,
        "secondary_link": 0.60,
        "tertiary": 0.50,
        "tertiary_link": 0.45,
        "residential": 0.40,
        "living_street": 0.50,
        "pedestrian": 0.60,
        "service": 0.30,
        "unclassified": 0.25,
        "track": 0.10,
    }

    # Weather cache TTL in seconds
    WEATHER_CACHE_TTL: int = 300     # 5 minutes

    # ── OSRM public router (or self-hosted mirror) ───────────────────────────
    # Long routes with alternatives=true + full geometry + steps can exceed 30s
    # on router.project-osrm.org; read timeout is the usual failure mode.
    #
    # IMPORTANT: router.project-osrm.org returns identical duration/distance for
    # driving vs foot (misconfigured demo). Use a foot-capable mirror for walking.
    OSRM_BASE_URL: str = "https://router.project-osrm.org"
    OSRM_BASE_URL_FOOT: str = "https://routing.openstreetmap.de/routed-foot"
    OSRM_TIMEOUT_CONNECT: float = 15.0
    OSRM_TIMEOUT_READ: float = 120.0
    # Pedestrian ETA sanity: if a "foot" response implies running-speed, rescale.
    WALK_SPEED_MPS: float = 1.39
    WALK_MAX_IMPLIED_SPEED_KMH: float = 12.0

    # OpenStreetMap Overpass — free real-world POI / lamp density (no API key)
    OVERPASS_API_URL: str = "https://overpass-api.de/api/interpreter"
    OVERPASS_TIMEOUT_S: float = 10.0
    AMBIENT_RADIUS_M: int = 450
    AMBIENT_OVERPASS_ENABLED: bool = True
    # Great-circle guard: India→Australia is ~8.9k km with no driving graph; public OSRM returns 400.
    # Threshold below that span catches disconnected intercontinental requests before HTTP.
    # Increase for self-hosted planet / ferry-aware profiles.
    OSRM_MAX_HAVERSINE_KM: float = 8800.0

    # Temporal safety adjustment (multiplicative, see safety_context.apply_temporal_safety_adjustment)
    SAFETY_TEMPORAL_MAX_DRAG: float = 0.12

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# Instantiate global settings
settings = Settings()
