"""Per-outlet control endpoints (scaffolded; disabled at v0.1).

These return HTTP 501 Not Implemented when
`OUTLET_CONTROL_ENABLED=false` (the default). The route shape is
fixed so the public OpenAPI surface doesn't change when v0.2 wires
real implementations behind these endpoints.
"""

from fastapi import APIRouter, HTTPException, status

from app.config import settings

router = APIRouter()


def _ensure_enabled() -> None:
    if not settings.outlet_control_enabled:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=(
                "Outlet control is disabled. Set OUTLET_CONTROL_ENABLED=true to enable "
                "(implementation lands in v0.2)."
            ),
        )


@router.post(
    "/outlets/{outlet_number}/on",
    tags=["Outlets"],
    summary="Turn an outlet ON (Phase 2)",
)
async def outlet_on(outlet_number: int) -> dict:
    """Power the outlet on. Returns 501 unless `OUTLET_CONTROL_ENABLED=true`."""
    _ensure_enabled()
    # Phase 2: route to actual SNMP set / web-UI command here.
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Outlet control implementation pending v0.2.",
    )


@router.post(
    "/outlets/{outlet_number}/off",
    tags=["Outlets"],
    summary="Turn an outlet OFF (Phase 2)",
)
async def outlet_off(outlet_number: int) -> dict:
    _ensure_enabled()
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Outlet control implementation pending v0.2.",
    )


@router.post(
    "/outlets/{outlet_number}/cycle",
    tags=["Outlets"],
    summary="Power-cycle an outlet (Phase 2)",
)
async def outlet_cycle(outlet_number: int) -> dict:
    _ensure_enabled()
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Outlet control implementation pending v0.2.",
    )
