-- ============================================================================
-- Google Luma Cache Schema
-- Run this SQL in Supabase Dashboard → SQL Editor → New Query → Run
-- ============================================================================

-- Base road network graph registry
-- Stores metadata about cached OSMnx graphs; actual .graphml.gz lives in Storage
CREATE TABLE IF NOT EXISTS region_graphs (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    center_lat FLOAT NOT NULL,
    center_lon FLOAT NOT NULL,
    radius_km INT NOT NULL,
    node_count INT,
    edge_count INT,
    storage_path TEXT NOT NULL,
    file_size_bytes BIGINT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '30 days'),
    UNIQUE(center_lat, center_lon, radius_km)
);

-- Static features cache (lighting, crime, POI, vegetation — excludes weather/time)
-- Links to a region_graph; actual .parquet.gz lives in Storage
CREATE TABLE IF NOT EXISTS cached_features (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    graph_id UUID REFERENCES region_graphs(id) ON DELETE CASCADE,
    storage_path TEXT NOT NULL,
    edge_count INT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '24 hours'),
    UNIQUE(graph_id)
);

-- Computed route cache (keyed by origin/dest/mode/time/weather)
CREATE TABLE IF NOT EXISTS route_cache (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    origin_lat FLOAT NOT NULL,
    origin_lon FLOAT NOT NULL,
    dest_lat FLOAT NOT NULL,
    dest_lon FLOAT NOT NULL,
    mode TEXT NOT NULL,
    time_context TEXT NOT NULL,           -- 'day' or 'night'
    weather_bucket TEXT NOT NULL DEFAULT 'clear',
    route_geometry JSONB NOT NULL,
    estimated_time_seconds FLOAT,
    average_safety_score FLOAT,
    total_cost FLOAT,
    graph_id UUID REFERENCES region_graphs(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '1 hour')
);
CREATE INDEX IF NOT EXISTS idx_route_lookup
    ON route_cache(origin_lat, origin_lon, dest_lat, dest_lon, mode, time_context);

-- POI cache (OSM Overpass results per bounding box)
CREATE TABLE IF NOT EXISTS poi_cache (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    bbox_key TEXT UNIQUE NOT NULL,
    poi_count INT,
    poi_data JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '7 days')
);

-- VIIRS pre-sampled brightness tile registry
CREATE TABLE IF NOT EXISTS viirs_tiles (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    city_name TEXT UNIQUE NOT NULL,
    center_lat FLOAT,
    center_lon FLOAT,
    bbox_north FLOAT,
    bbox_south FLOAT,
    bbox_east FLOAT,
    bbox_west FLOAT,
    grid_resolution_m INT DEFAULT 50,
    storage_path TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ML model registry (XGBoost models per region)
CREATE TABLE IF NOT EXISTS ml_models (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    region_key TEXT NOT NULL,
    model_type TEXT DEFAULT 'xgboost',
    storage_path TEXT NOT NULL,
    training_edges INT,
    feature_importance JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(region_key, model_type)
);

-- KDE model registry (crime density models)
CREATE TABLE IF NOT EXISTS kde_models (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    data_hash TEXT UNIQUE NOT NULL,
    bandwidth FLOAT,
    point_count INT,
    storage_path TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Enable Row Level Security (optional — service_role bypasses RLS)
-- ALTER TABLE region_graphs ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE cached_features ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE route_cache ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE poi_cache ENABLE ROW LEVEL SECURITY;
