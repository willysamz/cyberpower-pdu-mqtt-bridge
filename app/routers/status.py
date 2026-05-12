"""Most-recent PDU snapshot exposed as JSON."""

from fastapi import APIRouter

from app.config import settings
from app.dependencies import get_poller
from app.models import StatusResponse

router = APIRouter()


@router.get(
    "/status",
    response_model=StatusResponse,
    tags=["Status"],
    summary="Current PDU snapshot",
)
async def get_status() -> StatusResponse:
    """Return the most recent cached SNMP snapshot.

    Updated every `POLL_INTERVAL` seconds by the background poller.
    """
    poller = get_poller()
    return StatusResponse(
        bridge_state=poller.state,
        pdu_host=settings.pdu_host,
        poll_interval_seconds=settings.poll_interval,
        last_snapshot=poller.last_snapshot,
    )
