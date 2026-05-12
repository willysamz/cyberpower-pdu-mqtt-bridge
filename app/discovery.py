"""Home Assistant MQTT discovery payload + topic builders.

HA's MQTT discovery convention is:
    {prefix}/{component}/{node_id}/{object_id}/config
…with a JSON payload describing the entity. State / availability /
command topics are referenced by name from the payload.

We publish discovery payloads once at startup (retained) so HA picks
them up immediately and on every subsequent re-connect.
"""

from __future__ import annotations

import re
from typing import Any

from app.models import OutletReading, PduIdentity


def _slug(value: str) -> str:
    """Lowercase alphanumeric+underscore slug for IDs / topics."""
    value = value.strip().lower()
    return re.sub(r"[^a-z0-9_]+", "_", value).strip("_") or "pdu"


def device_block(device_id: str, device_name: str, identity: PduIdentity) -> dict[str, Any]:
    """The `device` field that's repeated on every entity payload — pins
    them all to one HA device card."""
    block: dict[str, Any] = {
        "identifiers": [device_id],
        "name": device_name,
        "manufacturer": "CyberPower",
    }
    if identity.model:
        block["model"] = identity.model
    elif identity.sys_descr:
        block["model"] = identity.sys_descr
    if identity.firmware:
        block["sw_version"] = identity.firmware
    if identity.serial:
        block["serial_number"] = identity.serial
    return block


def bank_load_amps_payload(
    *,
    discovery_prefix: str,
    device_id: str,
    device_name: str,
    state_topic: str,
    availability_topic: str,
    identity: PduIdentity,
) -> tuple[str, dict[str, Any]]:
    """Discovery topic + payload for the whole-PDU load (amps) sensor."""
    object_id = f"{device_id}_total_load_amps"
    topic = f"{discovery_prefix}/sensor/{object_id}/config"
    payload: dict[str, Any] = {
        "name": "Total Load",
        "unique_id": object_id,
        "state_topic": state_topic,
        "device_class": "current",
        "unit_of_measurement": "A",
        "state_class": "measurement",
        "availability_topic": availability_topic,
        "payload_available": "online",
        "payload_not_available": "offline",
        "device": device_block(device_id, device_name, identity),
    }
    return topic, payload


def bank_load_watts_payload(
    *,
    discovery_prefix: str,
    device_id: str,
    device_name: str,
    state_topic: str,
    availability_topic: str,
    identity: PduIdentity,
) -> tuple[str, dict[str, Any]]:
    """Whole-PDU power (watts) sensor."""
    object_id = f"{device_id}_total_load_watts"
    topic = f"{discovery_prefix}/sensor/{object_id}/config"
    payload: dict[str, Any] = {
        "name": "Total Power",
        "unique_id": object_id,
        "state_topic": state_topic,
        "device_class": "power",
        "unit_of_measurement": "W",
        "state_class": "measurement",
        "availability_topic": availability_topic,
        "payload_available": "online",
        "payload_not_available": "offline",
        "device": device_block(device_id, device_name, identity),
    }
    return topic, payload


def bank_voltage_payload(
    *,
    discovery_prefix: str,
    device_id: str,
    device_name: str,
    state_topic: str,
    availability_topic: str,
    identity: PduIdentity,
) -> tuple[str, dict[str, Any]]:
    """Input voltage sensor (typically 120 V in NA, 230 V in EU)."""
    object_id = f"{device_id}_voltage"
    topic = f"{discovery_prefix}/sensor/{object_id}/config"
    payload: dict[str, Any] = {
        "name": "Input Voltage",
        "unique_id": object_id,
        "state_topic": state_topic,
        "device_class": "voltage",
        "unit_of_measurement": "V",
        "state_class": "measurement",
        "availability_topic": availability_topic,
        "payload_available": "online",
        "payload_not_available": "offline",
        "device": device_block(device_id, device_name, identity),
    }
    return topic, payload


def legacy_outlet_state_topic(*, discovery_prefix: str, device_id: str, outlet_number: int) -> str:
    """The v0.1.x `binary_sensor` discovery topic. We publish an empty
    payload here once at startup to retire the read-only entity in HA
    after the v0.2 upgrade. After that, the corresponding `switch` topic
    below takes over."""
    object_id = f"{device_id}_outlet_{outlet_number}_state"
    return f"{discovery_prefix}/binary_sensor/{object_id}/config"


def outlet_switch_payload(
    *,
    discovery_prefix: str,
    device_id: str,
    device_name: str,
    state_topic: str,
    command_topic: str,
    availability_topic: str,
    identity: PduIdentity,
    outlet: OutletReading,
) -> tuple[str, dict[str, Any]]:
    """Per-outlet `switch` — read state + write ON/OFF from HA.

    HA renders this as a toggle on the device card. The state topic stays
    `pdu/outlet/N/state` (same as v0.1.x); the new command topic is
    `pdu/outlet/N/set`. We mark `optimistic: false` so HA only reports
    the actual SNMP-confirmed state — the bridge publishes an optimistic
    state update on successful write + triggers an immediate poll, so the
    HA UI catches up within ~1 s.
    """
    object_id = f"{device_id}_outlet_{outlet.number}"
    topic = f"{discovery_prefix}/switch/{object_id}/config"
    name = outlet.name.strip() if outlet.name else f"Outlet {outlet.number}"
    payload: dict[str, Any] = {
        "name": name,
        "unique_id": object_id,
        "state_topic": state_topic,
        "command_topic": command_topic,
        "payload_on": "ON",
        "payload_off": "OFF",
        "optimistic": False,
        "device_class": "outlet",
        "availability_topic": availability_topic,
        "payload_available": "online",
        "payload_not_available": "offline",
        "device": device_block(device_id, device_name, identity),
    }
    return topic, payload


def outlet_cycle_button_payload(
    *,
    discovery_prefix: str,
    device_id: str,
    device_name: str,
    command_topic: str,
    availability_topic: str,
    identity: PduIdentity,
    outlet: OutletReading,
) -> tuple[str, dict[str, Any]]:
    """Per-outlet `button` that publishes REBOOT on press.

    Maps to SNMP value 3 — the PDU sequences off → delay → on internally.
    """
    object_id = f"{device_id}_outlet_{outlet.number}_cycle"
    topic = f"{discovery_prefix}/button/{object_id}/config"
    name = (outlet.name.strip() if outlet.name else f"Outlet {outlet.number}") + " Cycle"
    payload: dict[str, Any] = {
        "name": name,
        "unique_id": object_id,
        "command_topic": command_topic,
        "payload_press": "REBOOT",
        "device_class": "restart",
        "availability_topic": availability_topic,
        "payload_available": "online",
        "payload_not_available": "offline",
        "device": device_block(device_id, device_name, identity),
    }
    return topic, payload


def outlet_load_payload(
    *,
    discovery_prefix: str,
    device_id: str,
    device_name: str,
    state_topic: str,
    availability_topic: str,
    identity: PduIdentity,
    outlet: OutletReading,
) -> tuple[str, dict[str, Any]]:
    """Per-outlet load (amps) sensor."""
    object_id = f"{device_id}_outlet_{outlet.number}_load_amps"
    topic = f"{discovery_prefix}/sensor/{object_id}/config"
    name = (outlet.name.strip() if outlet.name else f"Outlet {outlet.number}") + " Load"
    payload: dict[str, Any] = {
        "name": name,
        "unique_id": object_id,
        "state_topic": state_topic,
        "device_class": "current",
        "unit_of_measurement": "A",
        "state_class": "measurement",
        "availability_topic": availability_topic,
        "payload_available": "online",
        "payload_not_available": "offline",
        "device": device_block(device_id, device_name, identity),
    }
    return topic, payload


def derive_device_id(configured: str, identity: PduIdentity) -> str:
    """Pick a stable device_id used in unique_id + the device block.

    Priority:
      1. Explicit `HA_DEVICE_ID` from config (if non-empty)
      2. SNMP sysName
      3. Constant fallback
    """
    if configured:
        return _slug(configured)
    if identity.sys_name:
        return _slug(identity.sys_name)
    return "cyberpower_pdu"
