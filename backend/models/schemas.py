"""
Pydantic API schema validation structures exactly maintaining rigorous frontend contracts natively securely.
"""
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    message: str

class Coordinate(BaseModel):
    """Geodeisic point abstraction explicitly natively wrapping outputs securely limit."""
    lat: float
    lon: float

class RouteRequest(BaseModel):
    """Payload targeting explicit physics navigation bounds natively bindings."""
    source: List[float] = Field(..., min_length=2, max_length=2, description="[lat, lon]")
    destination: List[float] = Field(..., min_length=2, max_length=2, description="[lat, lon]")
    mode: str = Field(default="safest", pattern="^(fastest|safest|balanced)$")
    travel_profile: str = Field(
        default="driving",
        pattern="^(driving|foot)$",
        description="OSRM profile: driving (car) or foot (walking)",
    )

class RoutePayload(BaseModel):
    """Maps purely standard geometric attributes natively for spatial visualization."""
    mode: str
    route_geometry: List[Coordinate]
    estimated_time_seconds: float
    distance_meters: float = Field(default=0.0, description="Real distance from OSRM in meters")
    average_safety_score: float
    total_cost: float
    ai_insight: Optional[str] = Field(default="", description="Qualitative safety contextualization from LLM")

class CompareRoutesResponse(BaseModel):
    """Exhaustive API wrapper matching all configuration bindings simultaneously."""
    origin: Coordinate
    destination: Coordinate
    routes: List[RoutePayload]
    rankings: Dict[str, List[str]]
    tradeoff_metrics: Dict[str, Dict[str, float]]
    travel_profile: str = Field(
        default="driving",
        description="OSRM profile used: driving or foot",
    )
