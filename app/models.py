"""Pydantic models for API + internal data."""

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class OutletState(str, Enum):
    """On/off state of a single outlet."""

    ON = "ON"
    OFF = "OFF"
    UNKNOWN = "UNKNOWN"


class OutletCommand(str, Enum):
    """Commands that can be sent to actuate an outlet (v0.2+)."""

    ON = "ON"
    OFF = "OFF"
    REBOOT = "REBOOT"
    CANCEL = "CANCEL"


class BridgeState(str, Enum):
    """Bridge connection state to the PDU."""

    INITIALIZING = "initializing"
    CONNECTED = "connected"
    UNREACHABLE = "unreachable"
    ERROR = "error"


class PduIdentity(BaseModel):
    """Identifying info about the PDU itself."""

    sys_descr: str | None = None
    sys_name: str | None = None
    model: str | None = None
    firmware: str | None = None
    serial: str | None = None


class OutletReading(BaseModel):
    """A single outlet's most recent reading."""

    number: int = Field(ge=1, description="1-indexed outlet position")
    name: str | None = None
    state: OutletState = OutletState.UNKNOWN
    load_amps: float | None = Field(None, description="Outlet current draw in amps")
    load_watts: float | None = Field(None, description="Outlet load in watts (if PDU exposes it)")


class BankReading(BaseModel):
    """Whole-PDU (bank) readings."""

    load_amps: float | None = None
    load_watts: float | None = None
    voltage: float | None = None


class PollSnapshot(BaseModel):
    """A complete snapshot from one SNMP poll cycle."""

    timestamp: datetime
    identity: PduIdentity
    bank: BankReading
    outlets: list[OutletReading]


class HealthResponse(BaseModel):
    """Readiness/liveness response body."""

    status: Literal["ok", "degraded", "error"]
    bridge_state: BridgeState
    pdu_host: str
    mqtt_host: str
    last_poll: datetime | None = None
    uptime_seconds: float


class ErrorResponse(BaseModel):
    """Generic error response."""

    error: str
    message: str


class StatusResponse(BaseModel):
    """The current cached snapshot exposed at /api/status."""

    bridge_state: BridgeState
    pdu_host: str
    poll_interval_seconds: float
    last_snapshot: PollSnapshot | None = None
