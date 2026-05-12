"""Per-outlet control endpoints (real implementations in v0.2)."""

from fastapi import APIRouter, HTTPException, status

from app.dependencies import get_controller
from app.models import OutletCommand

router = APIRouter()


async def _exec(outlet_number: int, command: OutletCommand) -> dict:
    """Hand off to the Controller, translating its exceptions to HTTP."""
    from app.controller import ControlDisabledError, OutletNotAllowedError
    from app.snmp_client import SnmpError

    controller = get_controller()
    try:
        await controller.set_outlet(outlet_number, command)
    except ControlDisabledError as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc
    except OutletNotAllowedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except SnmpError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"SNMP set failed: {exc}",
        ) from exc
    return {"outlet": outlet_number, "command": command.value, "result": "submitted"}


@router.post(
    "/outlets/{outlet_number}/on",
    tags=["Outlets"],
    summary="Turn an outlet ON",
)
async def outlet_on(outlet_number: int) -> dict:
    """Power the outlet on (SNMP value 1)."""
    return await _exec(outlet_number, OutletCommand.ON)


@router.post(
    "/outlets/{outlet_number}/off",
    tags=["Outlets"],
    summary="Turn an outlet OFF",
)
async def outlet_off(outlet_number: int) -> dict:
    """Power the outlet off (SNMP value 2)."""
    return await _exec(outlet_number, OutletCommand.OFF)


@router.post(
    "/outlets/{outlet_number}/cycle",
    tags=["Outlets"],
    summary="Power-cycle (reboot) an outlet",
)
async def outlet_cycle(outlet_number: int) -> dict:
    """Power-cycle the outlet (SNMP value 3). The PDU sequences off→on internally."""
    return await _exec(outlet_number, OutletCommand.REBOOT)
