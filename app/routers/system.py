"""System info endpoints."""

from datetime import UTC, datetime

from fastapi import APIRouter

from app import __version__
from app.config import settings
from app.dependencies import get_poller, get_startup_time

router = APIRouter()


@router.get("/system", tags=["System"], summary="Bridge identity + uptime")
async def get_system() -> dict:
    """Identity for the bridge process itself (separate from the PDU)."""
    return {
        "name": "cyberpower-pdu-mqtt-bridge",
        "version": __version__,
        "uptime_seconds": (datetime.now(UTC) - get_startup_time()).total_seconds(),
        "pdu_host": settings.pdu_host,
        "mqtt_host": settings.mqtt_host,
        "outlet_control_enabled": settings.outlet_control_enabled,
    }


@router.get("/version", tags=["System"], summary="Just the version string")
async def get_version() -> dict:
    return {"version": __version__}


@router.get("/pdu", tags=["System"], summary="Most-recent PDU identity (from SNMP)")
async def get_pdu_identity() -> dict:
    """The CyberPower PDU's own identity, as read via SNMP on the last poll."""
    poller = get_poller()
    snap = poller.last_snapshot
    if snap is None:
        return {"identity": None, "last_poll": None}
    return {"identity": snap.identity.model_dump(), "last_poll": snap.timestamp}
