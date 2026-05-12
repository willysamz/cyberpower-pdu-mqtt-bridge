# CyberPower MIB reference

All OIDs the bridge reads from the PDU. Anchored under
`1.3.6.1.4.1.3808.1.1.6` (CyberPower's monitored-PDU MIB branch).
v0.1.0 has been verified against a CyberPower **PDU41001** running
firmware **1.3.2** — a single-bank metered PDU.

## SNMPv2-MIB (standard)

| OID | What we use it for |
|---|---|
| `1.3.6.1.2.1.1.1.0` | `sysDescr` — surfaced in Home Assistant as `device.model` |
| `1.3.6.1.2.1.1.5.0` | `sysName` — falls-back source for `HA_DEVICE_ID` if you don't set it explicitly |

CyberPower's vendor-specific identity OIDs at
`enterprises.3808.1.1.6.2.{2,3,4,5}.0` (hardwareRev / firmwareRev /
serial / model) return `noSuchName` on the firmware version we
tested. The bridge doesn't query them — `sysDescr` + `sysName` are
enough.

## Bank-level status (`epdu.3.4.1.*.1`)

The bank table is indexed by bank number (always `.1` on
single-bank PDUs).

| OID | What we use it for |
|---|---|
| `1.3.6.1.4.1.3808.1.1.6.3.4.1.5.1` | total load in **deciamps** (multiply by 0.1 for amps) → `pdu/total/load_amps` |

`pdu/total/load_watts` is derived as `load_amps × MAINS_VOLTAGE`
(`MAINS_VOLTAGE` is a configurable constant — default 120 V; set it
to 230 / 240 for non-US circuits).

### Why we don't auto-detect voltage

CyberPower's voltage OID location varies across firmware
revisions. On the PDU41001 firmware 1.3.2 we tested:

- `epdu.3.4.1.9.1` → Gauge32 `2415` (looks like 241.5 V — but the
  PDU is connected to a 120 V circuit, so the unit semantics on
  this firmware are unclear).
- `epdu.4.4.1.6.1` → Gauge32 `1194` (the more plausible 119.4 V
  reading — but this is in the older `epdu` branch, not `epdu2`).

Rather than ship a wrong voltage reading, v0.1.0 derives watts
from a user-configured mains voltage. If you have a firmware
revision where you can confirm the voltage OID + scale, please
open an issue.

## Outlet table

Per-outlet status (state + load) is exposed on **switched**
CyberPower PDUs at `epdu2.5.1.1.3.{n}` and `epdu2.5.2.1.{3,4}.{n}`.

The PDU41001 we tested is a **metered-only** unit — it exposes
itself as a single bank with no per-outlet table. The bridge
handles this gracefully (outlet count → 0; only bank totals
published). A switched PDU running the same MIB family should
auto-discover its outlets at runtime; if yours doesn't, please
open an issue with a `snmpwalk` dump of
`1.3.6.1.4.1.3808.1.1.6` so we can add a model profile.

## OIDs we deliberately don't read (yet)

- `epdu2.5.3.*` (outlet control) — writes only. Lands in v0.2 with
  outlet on/off/cycle for switched PDUs.
- `epdu.6.*` (sensor probes — temp/humidity if a probe is plugged
  into the PDU's RJ12 port). Add as an opt-in module if anyone
  has hardware to test against.
- `epdu.7.*` (per-outlet alarms / thresholds). Configuration data,
  not telemetry — not useful for HA entities.

## How to extend

To add support for another vendor / model:

1. Walk the device with `snmpwalk -v2c -c public <host>
   1.3.6.1.4.1.<vendor>` and identify which OIDs hold the data
   you want.
2. Add a new module like `app/<vendor>.py` mirroring
   `app/cyberpower.py`'s shape — OID constants + parser
   functions.
3. Plumb it through `app/poller.py` behind a `PDU_VENDOR=` flag
   (not yet implemented; PR welcome).
