"""Outlet-control orchestrator (v0.2+).

The controller is the layer between MQTT commands / REST writes and the
SNMP write to the PDU. It enforces the safety gates
(`OUTLET_CONTROL_ENABLED`, `OUTLET_CONTROL_ALLOW`), executes the SNMP
set, publishes an optimistic state update, and triggers an immediate
poll so HA confirms the new state quickly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from app import cyberpower as cp
from app.models import OutletCommand
from app.snmp_client import SnmpError

if TYPE_CHECKING:
    from app.config import Settings
    from app.mqtt_client import MqttClient
    from app.poller import Poller
    from app.snmp_client import SnmpClient

log = structlog.get_logger()


class ControlDisabledError(Exception):
    """Raised when control is requested but `OUTLET_CONTROL_ENABLED=false`."""


class OutletNotAllowedError(Exception):
    """Raised when the outlet number is not in `OUTLET_CONTROL_ALLOW`."""


class Controller:
    """Wires MQTT command messages + REST writes to SNMP outlet sets."""

    def __init__(
        self,
        snmp: SnmpClient,
        mqtt: MqttClient,
        poller: Poller,
        settings: Settings,
    ) -> None:
        self.snmp = snmp
        self.mqtt = mqtt
        self.poller = poller
        self.settings = settings
        self._allow_set = self._parse_allow(settings.outlet_control_allow)

    @staticmethod
    def _parse_allow(csv: str) -> set[int]:
        """Parse `OUTLET_CONTROL_ALLOW` into a set of outlet numbers.

        Empty string → empty set, treated as 'all outlets allowed'.
        """
        if not csv.strip():
            return set()
        result: set[int] = set()
        for tok in csv.split(","):
            tok = tok.strip()
            if not tok:
                continue
            try:
                result.add(int(tok))
            except ValueError:
                log.warning("outlet_control_allow_bad_token", token=tok)
        return result

    def _check_allowed(self, outlet: int) -> None:
        if not self.settings.outlet_control_enabled:
            raise ControlDisabledError("outlet control disabled (set OUTLET_CONTROL_ENABLED=true)")
        # Empty allow-list means everything allowed.
        if self._allow_set and outlet not in self._allow_set:
            raise OutletNotAllowedError(
                f"outlet {outlet} not in OUTLET_CONTROL_ALLOW ({sorted(self._allow_set)})"
            )

    async def set_outlet(self, outlet: int, command: OutletCommand | str) -> None:
        """Actuate one outlet. Raises if guarded; otherwise:

        1. SNMP-set the command integer on `OID_OUTLET_COMMAND_BASE.{n}`.
        2. Publish an optimistic state update to `pdu/outlet/N/state`.
        3. Trigger an immediate poll so HA reflects the actual SNMP-confirmed
           state within ~1 s (handles cases where the SNMP set was a no-op).
        """
        cmd = OutletCommand(command) if not isinstance(command, OutletCommand) else command
        self._check_allowed(outlet)

        value = cp.OUTLET_COMMAND_VALUES[cmd.value]
        oid = cp.outlet_oid(cp.OID_OUTLET_COMMAND_BASE, outlet)

        log.info("outlet_control_received", outlet=outlet, command=cmd.value)
        try:
            await self.snmp.set_int(oid, value)
        except SnmpError as exc:
            # Leave HA state untouched; the next poll cycle will re-publish
            # the actual SNMP-confirmed state.
            log.warning(
                "snmp_set_failed",
                outlet=outlet,
                command=cmd.value,
                oid=oid,
                error=str(exc),
            )
            raise

        # Optimistic state — only ON/OFF map to a state. REBOOT eventually
        # ends in ON (PDU sequences off → delay → on); we don't fake an
        # intermediate state here, instead letting the poll see the real
        # transitions.
        prefix = self.settings.mqtt_topic_prefix.strip("/")
        if cmd in (OutletCommand.ON, OutletCommand.OFF):
            await self.mqtt.publish(f"{prefix}/outlet/{outlet}/state", cmd.value, retain=True)
            log.info("outlet_state_published", outlet=outlet, state=cmd.value)

        # Nudge the poll loop to confirm reality. The poller's
        # `trigger_immediate_poll()` is fire-and-forget.
        self.poller.trigger_immediate_poll()
