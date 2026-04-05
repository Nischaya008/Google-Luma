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


class CVAnalyzeRequest(BaseModel):
    """Payload for real-time camera frame analysis."""
    frame_base64: str = Field(
        ...,
        description="Base64-encoded JPEG/PNG frame from mobile camera",
    )
    route_safety_score: Optional[float] = Field(
        default=None,
        description="Pre-computed ML route safety score [0, 1] for blending",
    )
    lat: Optional[float] = Field(
        default=None,
        description="Current latitude of the user (for geo-context)",
    )
    lon: Optional[float] = Field(
        default=None,
        description="Current longitude of the user (for geo-context)",
    )


class CVAnalyzeResponse(BaseModel):
    """Response from real-time camera safety analysis."""
    cv_safety_score: float = Field(
        ..., description="Pure CV-derived safety score [0, 1]",
    )
    final_blended_score: float = Field(
        ..., description="Blended score: 0.7*ML + 0.3*CV [0, 1]",
    )
    brightness: float = Field(
        ..., description="Mean brightness from HSV analysis [0, 1]",
    )
    brightness_uniformity: float = Field(
        default=0.5, description="Lighting uniformity [0, 1]",
    )
    crowd_count: int = Field(
        default=0, description="Number of people detected in frame",
    )
    vehicle_count: int = Field(
        default=0, description="Number of vehicles detected in frame",
    )
    infrastructure_count: int = Field(
        default=0, description="Number of infrastructure elements detected",
    )
    is_anomaly: bool = Field(
        default=False, description="Whether this frame is flagged as anomalous",
    )
    anomaly_label: str = Field(
        default="", description="Human-readable anomaly description",
    )
    ai_explanation: str = Field(
        default="", description="Real-time AI explanation referencing feed elements",
    )
    features: Dict[str, Any] = Field(
        default_factory=dict, description="Raw normalized feature scores",
    )
