"""Background poll loop: SNMP → publish to MQTT (+ HA discovery)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from app import cyberpower as cp
from app.discovery import (
    bank_load_amps_payload,
    bank_load_watts_payload,
    bank_voltage_payload,
    derive_device_id,
    outlet_load_payload,
    outlet_state_payload,
)
from app.models import (
    BankReading,
    BridgeState,
    OutletReading,
    OutletState,
    PduIdentity,
    PollSnapshot,
)

if TYPE_CHECKING:
    from app.config import Settings
    from app.mqtt_client import MqttClient
    from app.snmp_client import SnmpClient

log = structlog.get_logger()


class Poller:
    """Polls the PDU on a fixed cadence and publishes to MQTT.

    The cached snapshot is exposed via `last_snapshot` for the
    /api/status REST endpoint to read.
    """

    def __init__(
        self,
        snmp: SnmpClient,
        mqtt: MqttClient,
        settings: Settings,
    ) -> None:
        self.snmp = snmp
        self.mqtt = mqtt
        self.settings = settings

        self.state: BridgeState = BridgeState.INITIALIZING
        self.last_snapshot: PollSnapshot | None = None
        self.last_poll: datetime | None = None
        self.last_error: str | None = None

        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._discovery_published = False
        self._outlet_count_cached: int | None = None
        self._device_id: str | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except TimeoutError:
                self._task.cancel()

    async def _run(self) -> None:
        # Small initial jitter to avoid hammering at startup
        await asyncio.sleep(1)
        while not self._stop_event.is_set():
            try:
                snapshot = await self.poll_once()
                await self._publish(snapshot)
                self.state = BridgeState.CONNECTED
                self.last_error = None
            except Exception as exc:  # broad: any failure → degraded but keep looping
                self.state = BridgeState.UNREACHABLE
                self.last_error = str(exc)
                log.warning("poll_cycle_failed", error=str(exc))

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.settings.poll_interval)
            except TimeoutError:
                continue

    async def poll_once(self) -> PollSnapshot:
        """One SNMP poll cycle. Builds a snapshot. Does not publish."""
        identity = await self._poll_identity()
        outlet_count = await self._discover_outlet_count()
        bank = await self._poll_bank()
        outlets = await self._poll_outlets(outlet_count, bank.voltage)
        snapshot = PollSnapshot(
            timestamp=datetime.now(UTC),
            identity=identity,
            bank=bank,
            outlets=outlets,
        )
        self.last_snapshot = snapshot
        self.last_poll = snapshot.timestamp
        return snapshot

    async def _poll_identity(self) -> PduIdentity:
        # Only the two SNMPv2-MIB OIDs are reliably present across CyberPower
        # PDU firmware revisions. The vendor-specific identity OIDs
        # (`enterprises.3808.1.1.6.2.*`) return `noSuchName` on this PDU's
        # firmware (1.3.2 on PDU41001) so we don't ask for them.
        oids = await self.snmp.get_many([cp.OID_SYS_DESCR, cp.OID_SYS_NAME])
        return PduIdentity(
            sys_descr=_to_str(oids.get(cp.OID_SYS_DESCR)),
            sys_name=_to_str(oids.get(cp.OID_SYS_NAME)),
        )

    async def _poll_bank(self) -> BankReading:
        oids = await self.snmp.get_many([cp.OID_BANK_STATUS_LOAD_DECIAMPS])
        amps = cp.deciamps_to_amps(oids.get(cp.OID_BANK_STATUS_LOAD_DECIAMPS))
        volts = self.settings.mains_voltage
        watts = cp.watts_from_amps_volts(amps, volts)
        return BankReading(load_amps=amps, voltage=volts, load_watts=watts)

    async def _discover_outlet_count(self) -> int:
        """Cache the outlet count after the first successful enumeration.

        We walk the outletName subtree (one row per outlet) and count rows.
        """
        if self._outlet_count_cached is not None:
            return self._outlet_count_cached

        rows = await self.snmp.walk(cp.OID_OUTLET_NAME_BASE, max_rows=32)
        if not rows:
            log.warning("no_outlets_discovered_via_walk", base=cp.OID_OUTLET_NAME_BASE)
            return 0
        self._outlet_count_cached = len(rows)
        log.info("discovered_outlets", count=self._outlet_count_cached)
        return self._outlet_count_cached

    async def _poll_outlets(self, count: int, voltage: float | None) -> list[OutletReading]:
        # `voltage` is unused on Switched-series PDUs (no per-outlet load to derive watts from);
        # it stays in the signature for forward-compat with Metered-by-Outlet models.
        _ = voltage
        out: list[OutletReading] = []
        for n in range(1, count + 1):
            oids = await self.snmp.get_many(
                [
                    cp.outlet_oid(cp.OID_OUTLET_NAME_BASE, n),
                    cp.outlet_oid(cp.OID_OUTLET_STATE_BASE, n),
                ]
            )
            name = _to_str(oids.get(cp.outlet_oid(cp.OID_OUTLET_NAME_BASE, n)))
            state_raw = oids.get(cp.outlet_oid(cp.OID_OUTLET_STATE_BASE, n))
            state = OutletState(cp.parse_outlet_state(state_raw))
            out.append(
                OutletReading(
                    number=n,
                    name=name,
                    state=state,
                    load_amps=None,  # PDU41001 (Switched series) has no per-outlet metering
                    load_watts=None,
                )
            )
        return out

    async def _publish(self, snapshot: PollSnapshot) -> None:
        """Publish state topics + (once) HA discovery topics."""
        prefix = self.settings.mqtt_topic_prefix.strip("/")

        # Per-outlet state and load
        for outlet in snapshot.outlets:
            await self.mqtt.publish(
                f"{prefix}/outlet/{outlet.number}/state", outlet.state.value, retain=True
            )
            if outlet.load_amps is not None:
                await self.mqtt.publish(
                    f"{prefix}/outlet/{outlet.number}/load_amps",
                    f"{outlet.load_amps:.1f}",
                    retain=True,
                )
            if outlet.load_watts is not None:
                await self.mqtt.publish(
                    f"{prefix}/outlet/{outlet.number}/load_watts",
                    f"{outlet.load_watts:.1f}",
                    retain=True,
                )

        # Bank totals
        if snapshot.bank.load_amps is not None:
            await self.mqtt.publish(
                f"{prefix}/total/load_amps", f"{snapshot.bank.load_amps:.1f}", retain=True
            )
        if snapshot.bank.load_watts is not None:
            await self.mqtt.publish(
                f"{prefix}/total/load_watts",
                f"{snapshot.bank.load_watts:.1f}",
                retain=True,
            )
        if snapshot.bank.voltage is not None:
            await self.mqtt.publish(
                f"{prefix}/total/voltage", f"{snapshot.bank.voltage:.1f}", retain=True
            )

        # HA discovery — once per process lifetime, after we have identity
        if self.settings.ha_discovery_enabled and not self._discovery_published:
            await self._publish_discovery(snapshot)
            self._discovery_published = True

    async def _publish_discovery(self, snapshot: PollSnapshot) -> None:
        device_id = derive_device_id(self.settings.ha_device_id, snapshot.identity)
        self._device_id = device_id
        prefix = self.settings.mqtt_topic_prefix.strip("/")
        availability_topic = self.mqtt.availability_topic

        topic, payload = bank_load_amps_payload(
            discovery_prefix=self.settings.ha_discovery_prefix,
            device_id=device_id,
            device_name=self.settings.ha_device_name,
            state_topic=f"{prefix}/total/load_amps",
            availability_topic=availability_topic,
            identity=snapshot.identity,
        )
        await self.mqtt.publish(topic, payload, retain=True)

        topic, payload = bank_load_watts_payload(
            discovery_prefix=self.settings.ha_discovery_prefix,
            device_id=device_id,
            device_name=self.settings.ha_device_name,
            state_topic=f"{prefix}/total/load_watts",
            availability_topic=availability_topic,
            identity=snapshot.identity,
        )
        await self.mqtt.publish(topic, payload, retain=True)

        topic, payload = bank_voltage_payload(
            discovery_prefix=self.settings.ha_discovery_prefix,
            device_id=device_id,
            device_name=self.settings.ha_device_name,
            state_topic=f"{prefix}/total/voltage",
            availability_topic=availability_topic,
            identity=snapshot.identity,
        )
        await self.mqtt.publish(topic, payload, retain=True)

        for outlet in snapshot.outlets:
            topic, payload = outlet_state_payload(
                discovery_prefix=self.settings.ha_discovery_prefix,
                device_id=device_id,
                device_name=self.settings.ha_device_name,
                state_topic=f"{prefix}/outlet/{outlet.number}/state",
                availability_topic=availability_topic,
                identity=snapshot.identity,
                outlet=outlet,
            )
            await self.mqtt.publish(topic, payload, retain=True)

            # Only publish per-outlet load discovery if THIS poll cycle saw
            # an actual deciamps value — Switched-series PDUs (like PDU41001)
            # don't expose per-outlet load and we don't want unavailable HA
            # entities cluttering the device card.
            if outlet.load_amps is not None:
                topic, payload = outlet_load_payload(
                    discovery_prefix=self.settings.ha_discovery_prefix,
                    device_id=device_id,
                    device_name=self.settings.ha_device_name,
                    state_topic=f"{prefix}/outlet/{outlet.number}/load_amps",
                    availability_topic=availability_topic,
                    identity=snapshot.identity,
                    outlet=outlet,
                )
                await self.mqtt.publish(topic, payload, retain=True)

        log.info(
            "ha_discovery_published",
            device_id=device_id,
            outlets=len(snapshot.outlets),
        )


def _to_str(value: object) -> str | None:
    """Coerce SNMP pretty-printed values to a Python str (or None)."""
    if value is None:
        return None
    s = str(value).strip()
    return s or None
