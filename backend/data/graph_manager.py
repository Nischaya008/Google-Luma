"""
Graph data management using NetworkX and OSMnx.
Responsible for downloading, processing, caching, and serving routing road networks.
"""
import logging
import networkx as nx
import osmnx as ox
from pathlib import Path
from typing import Optional, List
import math

# Configure module logger
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

class GraphManager:
    """
    Manages loading, updating, and querying the spatial graph.
    """
    def __init__(self, cache_dir: str = "./data/graph"):
        """
        Initializes the GraphManager.
        
        Args:
            cache_dir (str): Directory where graph files are stored locally.
        """
        self.cache_dir = Path(cache_dir)
        # Ensure the cache directory exists
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.graph: Optional[nx.MultiDiGraph] = None
        
        # Configure OSMnx performance/cache settings
        ox.settings.use_cache = True
        ox.settings.log_console = False

    def _impute_edge_attributes(self, G: nx.MultiDiGraph) -> nx.MultiDiGraph:
        """
        Imputes missing edge speeds and calculates base travel times.
        
        Args:
            G (nx.MultiDiGraph): Unprocessed NetworkX graph object.
            
        Returns:
            nx.MultiDiGraph: Graph with populated edge speed/time properties.
        """
        logger.info("Imputing edge speeds and travel times...")
        
        # Fallback speeds based on standard highway types (in km/h)
        # This acts as a fallback when maxspeed tags are missing from OSM data
        fallback_speeds = {
            'residential': 30,
            'secondary': 50,
            'tertiary': 40,
            'primary': 60,
            'motorway': 100,
            'unclassified': 30,
            'default': 30
        }
        
        # Adds speed_kph attribute to edges based on fallback / existing data
        G = ox.add_edge_speeds(G, hwy_speeds=fallback_speeds)
        
        # Calculates base_travel_time (seconds) based on length (meters) / speed_kph
        G = ox.add_edge_travel_times(G)
        
        return G

    def load_or_create_graph(self, city_name: str) -> nx.MultiDiGraph:
        """
        Downloads a city's road network, extracts nodes & edges, imputes properties,
        and safely caches it locally to avoid repeated downloads.
        
        Args:
            city_name (str): Full city string (e.g., San Francisco, California, USA).
            
        Returns:
            nx.MultiDiGraph: Processed NetworkX routing graph.
        """
        # Create a safe, deterministic filename from the city name
        safe_name = city_name.replace(", ", "_").replace(" ", "_").lower()
        filepath = self.cache_dir / f"{safe_name}.graphml"

        if filepath.exists():
            logger.info(f"Graph for '{city_name}' found in cache at {filepath}. Loading (this may take a moment)...")
            try:
                self.graph = ox.load_graphml(filepath)
                logger.info(f"Successfully loaded graph: {len(self.graph.nodes)} nodes, {len(self.graph.edges)} edges.")
                return self.graph
            except Exception as e:
                logger.error(f"Failed to load cached graph: {e}. Will attempt re-download...")
        
        logger.info(f"Graph for '{city_name}' not found locally. Downloading from OSM (Drive network)...")
        try:
            # 1. Download drive-able road network. 
            # Note: Simplify=True automatically ensures correct topology and length attributes
            G = ox.graph_from_place(city_name, network_type="drive", simplify=True)
            
            # 2. Add speed and base travel time attributes
            G = self._impute_edge_attributes(G)
            
            # 3. Cache logically to disk
            logger.info(f"Saving graph to {filepath}...")
            ox.save_graphml(G, filepath=filepath)
            logger.info(f"Successfully cached new graph: {len(G.nodes)} nodes, {len(G.edges)} edges.")
            
            self.graph = G
            return self.graph
        except Exception as e:
            logger.error(f"Failed to generate graph for '{city_name}': {e}")
            raise RuntimeError(f"Graph generation failed. Please verify the city name: '{city_name}'. Error: {e}")

    def load_graph_dynamically(self, lat1: float, lng1: float, lat2: Optional[float] = None, lng2: Optional[float] = None, radius_km_override: Optional[float] = None) -> nx.MultiDiGraph:
        """
        Downloads or loads a road network around a specific coordinate or encompassing two coordinates.
        Calculates a center point and a safe radius to ensure the entire route is covered.
        
        Args:
            radius_km_override: If provided, use this radius instead of computing from coordinates.
                               Used by cache warming to download larger city-covering graphs.
        """
        if lat2 is not None and lng2 is not None:
            center_lat = (lat1 + lat2) / 2.0
            center_lng = (lng1 + lng2) / 2.0
            
            # Calculate distance using Haversine
            R = 6371.0 # Radius of earth in km
            dlat = math.radians(lat2 - lat1)
            dlng = math.radians(lng2 - lng1)
            a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2)**2
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            dist_km = R * c
            
            # 0.75x multiplier covers both endpoints; cap at 15km to stay within Overpass limits
            radius_km = max(5.0, min(15.0, dist_km * 0.75))
            logger.info(f"Calculated distance: {dist_km:.2f}km. Setting radius to: {radius_km:.2f}km")
        else:
            center_lat = lat1
            center_lng = lng1
            radius_km = radius_km_override if radius_km_override else 5.0
            
        # Round the center to ~2 decimal places for cache sharing (approx 1.1km grid)
        # This will reuse graphs if requests are nearby
        round_lat = round(center_lat, 2)
        round_lng = round(center_lng, 2)
        cache_name = f"dynamic_{round_lat}_{round_lng}_{int(radius_km)}km.graphml"
        filepath = self.cache_dir / cache_name
        
        radius_meters = int(radius_km * 1000)
        
        logger.info(f"Graph Bounds Initialization - Center: ({center_lat:.6f}, {center_lng:.6f}), Radius: {radius_meters}m")

        graph_loaded = False
        if filepath.exists():
            logger.info(f"Graph for center ({round_lat}, {round_lng}), r={radius_meters}m found in cache. Loading...")
            try:
                self.graph = ox.load_graphml(filepath)
                graph_loaded = True
            except Exception as e:
                logger.error(f"Failed to load cached dynamic graph: {e}. Re-downloading...")
                
        if not graph_loaded:
            logger.info(f"Downloading dynamic graph for center {center_lat}, {center_lng} with radius {radius_meters}m...")
            
            # Configure OSMnx for reliable downloads
            import osmnx
            osmnx.settings.timeout = 300
            
            # For large areas (>7km), use tiled download to avoid Overpass API limits
            TILE_RADIUS_M = 5000  # 5km per tile — safe for any city density
            
            if radius_meters > 7000:
                G = self._download_tiled_graph(center_lat, center_lng, radius_km, TILE_RADIUS_M)
            else:
                G = self._download_single_graph(center_lat, center_lng, radius_meters)
            
            G = self._impute_edge_attributes(G)
            
            logger.info(f"Saving dynamic graph to {filepath}...")
            ox.save_graphml(G, filepath=filepath)
            self.graph = G

        # Validate that both source and destination nodes exist in graph
        if lat2 is not None and lng2 is not None:
            try:
                node1 = ox.distance.nearest_nodes(self.graph, X=lng1, Y=lat1)
                node2 = ox.distance.nearest_nodes(self.graph, X=lng2, Y=lat2)
                
                if node1 not in self.graph.nodes or node2 not in self.graph.nodes:
                    raise ValueError("Resolved node IDs are missing from the graph.")
                
                logger.info(f"Validated nodes in graph: Source Node ID {node1}, Dest Node ID {node2}")
            except Exception as e:
                logger.error("Source or destination nodes could not be validated in the graph.")
                raise RuntimeError(f"Node validation failed. Coordinates may be unroutable or graph is empty: {e}")
                
        return self.graph

    def _download_single_graph(self, center_lat: float, center_lng: float, radius_m: int) -> nx.MultiDiGraph:
        """Download a single graph tile (for areas ≤ 7km radius)."""
        try:
            G = ox.graph_from_point(
                (center_lat, center_lng), dist=radius_m,
                network_type="drive", simplify=True,
            )
            logger.info(f"Single tile: {len(G.nodes)} nodes, {len(G.edges)} edges")
            return G
        except Exception as e:
            raise RuntimeError(f"Graph download failed for ({center_lat}, {center_lng}), r={radius_m}m: {e}")

    def _download_tiled_graph(
        self, center_lat: float, center_lng: float,
        radius_km: float, tile_radius_m: int = 5000,
    ) -> nx.MultiDiGraph:
        """
        Download a large area by splitting into overlapping tiles.
        
        For a 15km radius area, this generates ~9-13 tile centers in a grid,
        downloads each as a separate 5km-radius graph (well within Overpass limits),
        and merges them into one unified graph.
        
        Each tile is individually retried (2 attempts) so one flaky download
        doesn't kill the entire operation.
        """
        import time
        
        # Generate tile centers in a grid pattern
        # Convert tile spacing to degrees (with 20% overlap for seamless merging)
        tile_spacing_deg = (tile_radius_m * 0.8 * 2) / 111000.0  # ~80% of diameter
        
        # How many tiles in each direction from center
        n_tiles = max(1, int(math.ceil(radius_km * 1000 / (tile_radius_m * 1.6))))
        
        tile_centers = []
        for dy in range(-n_tiles, n_tiles + 1):
            for dx in range(-n_tiles, n_tiles + 1):
                t_lat = center_lat + dy * tile_spacing_deg
                t_lng = center_lng + dx * tile_spacing_deg / math.cos(math.radians(center_lat))
                
                # Only include tiles within the target radius
                dlat = (t_lat - center_lat) * 111000
                dlng = (t_lng - center_lng) * 111000 * math.cos(math.radians(center_lat))
                dist = math.sqrt(dlat**2 + dlng**2)
                
                if dist <= radius_km * 1000 + tile_radius_m:
                    tile_centers.append((t_lat, t_lng))
        
        logger.info(
            f"Tiled download: {len(tile_centers)} tiles of {tile_radius_m}m radius "
            f"to cover {radius_km}km area around ({center_lat:.4f}, {center_lng:.4f})"
        )
        
        merged_graph = None
        success_count = 0
        
        for i, (t_lat, t_lng) in enumerate(tile_centers):
            for attempt in range(1, 3):  # 2 attempts per tile
                try:
                    G_tile = ox.graph_from_point(
                        (t_lat, t_lng), dist=tile_radius_m,
                        network_type="drive", simplify=True,
                    )
                    
                    if merged_graph is None:
                        merged_graph = G_tile
                    else:
                        merged_graph = nx.compose(merged_graph, G_tile)
                    
                    success_count += 1
                    logger.info(
                        f"  Tile {i+1}/{len(tile_centers)} ✓ "
                        f"({len(G_tile.nodes)} nodes, running total: {len(merged_graph.nodes)})"
                    )
                    break  # Success — move to next tile
                    
                except Exception as e:
                    if attempt < 2:
                        logger.warning(f"  Tile {i+1} attempt {attempt} failed: {e}. Retrying in 5s...")
                        time.sleep(5)
                    else:
                        logger.warning(f"  Tile {i+1} SKIPPED after 2 attempts: {e}")
            
            # Brief pause between tiles to be respectful to Overpass
            if i < len(tile_centers) - 1:
                time.sleep(1)
        
        if merged_graph is None or len(merged_graph.nodes) == 0:
            raise RuntimeError(
                f"All {len(tile_centers)} tile downloads failed for "
                f"({center_lat}, {center_lng}), r={radius_km}km"
            )
        
        logger.info(
            f"Tiled download complete: {success_count}/{len(tile_centers)} tiles merged → "
            f"{len(merged_graph.nodes)} nodes, {len(merged_graph.edges)} edges"
        )
        
        return merged_graph

    def get_nearest_node(self, lat: float, lng: float) -> int:
        """
        Finds the physically closest graph node ID to geographical coordinates.
        
        Args:
            lat (float): Latitude
            lng (float): Longitude
            
        Returns:
            int: The nearest node ID.
        """
        if self.graph is None:
            raise ValueError("Graph uninitialized. Call load_or_create_graph() first.")
            
        return ox.distance.nearest_nodes(self.graph, X=lng, Y=lat)
    
    def calculate_shortest_path(self, orig_node: int, dest_node: int, weight: str = "travel_time") -> List[int]:
        """
        Computes the optimal path utilizing standard Dijkstra's algorithm.
        
        Args:
            orig_node (int): Origin node ID.
            dest_node (int): Destination node ID.
            weight (str): Edge optimization attribute ('length', 'travel_time', etc.)
            
        Returns:
            List[int]: Sequence of node IDs comprising the shortest path.
        """
        if self.graph is None:
            raise ValueError("Graph uninitialized. Call load_or_create_graph() first.")
            
        try:
            path = nx.shortest_path(self.graph, orig=orig_node, dest=dest_node, weight=weight)
            return path
        except nx.NetworkXNoPath:
            logger.error(f"No path found between node {orig_node} and node {dest_node}.")
            raise nx.NetworkXNoPath("No valid path exists between the requested nodes.")
