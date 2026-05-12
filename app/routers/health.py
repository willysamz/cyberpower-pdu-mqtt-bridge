"""Liveness + readiness probes."""

from datetime import UTC, datetime

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.config import settings
from app.dependencies import get_poller, get_startup_time
from app.models import BridgeState, HealthResponse

router = APIRouter()


@router.get(
    "/healthz/live",
    status_code=status.HTTP_200_OK,
    tags=["Health"],
    summary="Liveness probe",
)
async def liveness() -> JSONResponse:
    """Liveness probe — returns 200 as long as the process is up."""
    return JSONResponse({"status": "ok"})


@router.get(
    "/healthz/ready",
    response_model=HealthResponse,
    tags=["Health"],
    summary="Readiness probe",
)
async def readiness() -> HealthResponse:
    """Readiness probe — returns the current bridge → PDU connection state."""
    poller = get_poller()
    startup = get_startup_time()
    uptime = (datetime.now(UTC) - startup).total_seconds()

    if poller.state == BridgeState.CONNECTED:
        overall = "ok"
    elif poller.state == BridgeState.INITIALIZING:
        overall = "degraded"
    else:
        overall = "error"

    return HealthResponse(
        status=overall,  # type: ignore[arg-type]
        bridge_state=poller.state,
        pdu_host=settings.pdu_host,
        mqtt_host=settings.mqtt_host,
        last_poll=poller.last_poll,
        uptime_seconds=uptime,
    )
