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
    legacy_outlet_state_topic,
    outlet_cycle_button_payload,
    outlet_load_payload,
    outlet_switch_payload,
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
        self._immediate_event = asyncio.Event()
        self._discovery_published = False
        self._legacy_discovery_retired = False
        self._outlet_count_cached: int | None = None
        self._device_id: str | None = None
        # Per-outlet name cache, populated when discovery is published.
        # Used to detect outlet renames and re-publish discovery.
        self._published_names: dict[int, str | None] = {}

    def trigger_immediate_poll(self) -> None:
        """Signal the run loop to skip the sleep and poll right now.

        Called by the Controller after a successful SNMP set so HA sees
        the actual SNMP-confirmed state within ~1 s rather than waiting
        out the remaining poll-interval seconds. Fire-and-forget; thread/
        task safe (just sets an asyncio.Event).
        """
        self._immediate_event.set()

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

            # Sleep until poll_interval elapses OR an immediate-poll signal
            # arrives (Controller fires this after a successful SNMP set).
            self._immediate_event.clear()
            stop_task = asyncio.create_task(self._stop_event.wait())
            immediate_task = asyncio.create_task(self._immediate_event.wait())
            done, pending = await asyncio.wait(
                {stop_task, immediate_task},
                timeout=self.settings.poll_interval,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
            # If neither event fired, the timeout naturally falls through and we
            # loop on to the next poll. Same for the immediate-poll case.
            if not done:  # pragma: no cover
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

        # HA discovery — full pass on first cycle; thereafter only re-publish
        # the per-outlet payloads whose name has changed (so renames in the
        # PDU's web UI flow through without a pod restart).
        if self.settings.ha_discovery_enabled:
            if not self._discovery_published:
                await self._publish_discovery(snapshot, full=True)
                self._discovery_published = True
            else:
                await self._republish_renamed_outlets(snapshot)

    async def _publish_discovery(self, snapshot: PollSnapshot, *, full: bool) -> None:
        """Emit HA-discovery payloads.

        On `full=True` (first publish): retires v0.1.x binary_sensor entities
        with empty payloads, then emits bank + switch + button entities for
        the whole device.
        """
        device_id = derive_device_id(self.settings.ha_device_id, snapshot.identity)
        self._device_id = device_id
        prefix = self.settings.mqtt_topic_prefix.strip("/")
        availability_topic = self.mqtt.availability_topic

        # Retire v0.1.x `binary_sensor` discovery topics by publishing empty
        # payloads — HA treats an empty config as "remove this entity".
        # One-shot per pod lifetime; safe to repeat (retained payloads stay
        # empty so the entity stays gone).
        if full and not self._legacy_discovery_retired:
            for outlet in snapshot.outlets:
                legacy_topic = legacy_outlet_state_topic(
                    discovery_prefix=self.settings.ha_discovery_prefix,
                    device_id=device_id,
                    outlet_number=outlet.number,
                )
                await self.mqtt.publish(legacy_topic, b"", retain=True)
            self._legacy_discovery_retired = True

        # --- bank-level entities ---
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

        # --- per-outlet entities ---
        for outlet in snapshot.outlets:
            await self._publish_outlet_discovery(
                outlet,
                device_id=device_id,
                availability_topic=availability_topic,
                prefix=prefix,
                identity=snapshot.identity,
            )
            self._published_names[outlet.number] = outlet.name

        log.info(
            "ha_discovery_published",
            device_id=device_id,
            outlets=len(snapshot.outlets),
        )

    async def _publish_outlet_discovery(
        self,
        outlet: OutletReading,
        *,
        device_id: str,
        availability_topic: str,
        prefix: str,
        identity: PduIdentity,
    ) -> None:
        """Emit `switch`, optional load-sensor, and `button` discovery for one outlet."""
        # Switch (state + command)
        topic, payload = outlet_switch_payload(
            discovery_prefix=self.settings.ha_discovery_prefix,
            device_id=device_id,
            device_name=self.settings.ha_device_name,
            state_topic=f"{prefix}/outlet/{outlet.number}/state",
            command_topic=f"{prefix}/outlet/{outlet.number}/set",
            availability_topic=availability_topic,
            identity=identity,
            outlet=outlet,
        )
        await self.mqtt.publish(topic, payload, retain=True)

        # Reboot button — same command_topic as the switch; payload `REBOOT`.
        topic, payload = outlet_cycle_button_payload(
            discovery_prefix=self.settings.ha_discovery_prefix,
            device_id=device_id,
            device_name=self.settings.ha_device_name,
            command_topic=f"{prefix}/outlet/{outlet.number}/set",
            availability_topic=availability_topic,
            identity=identity,
            outlet=outlet,
        )
        await self.mqtt.publish(topic, payload, retain=True)

        # Optional per-outlet load (only on Switched-Metered-by-Outlet PDUs)
        if outlet.load_amps is not None:
            topic, payload = outlet_load_payload(
                discovery_prefix=self.settings.ha_discovery_prefix,
                device_id=device_id,
                device_name=self.settings.ha_device_name,
                state_topic=f"{prefix}/outlet/{outlet.number}/load_amps",
                availability_topic=availability_topic,
                identity=identity,
                outlet=outlet,
            )
            await self.mqtt.publish(topic, payload, retain=True)

    async def _republish_renamed_outlets(self, snapshot: PollSnapshot) -> None:
        """If any outlet's name has changed since the last publish, re-emit its
        discovery payloads so HA picks up the new friendly name."""
        if not self._device_id:
            return
        prefix = self.settings.mqtt_topic_prefix.strip("/")
        availability_topic = self.mqtt.availability_topic
        for outlet in snapshot.outlets:
            prev = self._published_names.get(outlet.number)
            if prev != outlet.name:
                log.info(
                    "outlet_name_changed",
                    outlet=outlet.number,
                    previous=prev,
                    current=outlet.name,
                )
                await self._publish_outlet_discovery(
                    outlet,
                    device_id=self._device_id,
                    availability_topic=availability_topic,
                    prefix=prefix,
                    identity=snapshot.identity,
                )
                self._published_names[outlet.number] = outlet.name


def _to_str(value: object) -> str | None:
    """Coerce SNMP pretty-printed values to a Python str (or None)."""
    if value is None:
        return None
    s = str(value).strip()
    return s or None
