"""
Health check endpoints for service monitoring.
"""
from fastapi import APIRouter
from models.schemas import HealthResponse

router = APIRouter()

@router.get("/", response_model=HealthResponse)
async def health_check():
    """
    Basic health check endpoint to verify service is running.
    Useful for load balancers and orchestration tools (like Docker/Kubernetes).
    """
    return HealthResponse(status="healthy", message="Google Luma backend is operational.")
