# CyberPower MIB reference

All OIDs the bridge reads from the PDU. Spans **two** CyberPower
MIB branches:

- `enterprises.3808.1.1.6` (`epdu2`) — bank-level status
- `enterprises.3808.1.1.3` (`epdu`, the older branch) — per-outlet
  management table. Empirically present on more firmware revisions
  than the equivalent `epdu2.5.*` outlet table, so we prefer it.

Verified against a CyberPower **PDU41001** running firmware
**1.3.2** — a Switched-series 8-outlet PDU (per-outlet on/off
control + bank-level metering only; no per-outlet metering).

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

## Outlet management table (`epdu.3.3.3.1.1.*`)

The bridge enumerates outlets by walking the `epdu` branch (older
MIB), which is more reliably populated across CyberPower firmware
than the newer `epdu2` branch.

| OID | What we use it for |
|---|---|
| `1.3.6.1.4.1.3808.1.1.3.3.3.1.1.2.{n}` | outlet **name** (string; user-set in PDU UI, defaults to "OutletN") |
| `1.3.6.1.4.1.3808.1.1.3.3.3.1.1.4.{n}` | outlet **state / command** — `1=ON, 2=OFF, 3=REBOOT, 4=CANCEL`. This OID is also the v0.2 write target for outlet control. |

For each outlet we publish:

- `pdu/outlet/{n}/state` → `ON` / `OFF` (retained)
- `homeassistant/binary_sensor/{device_id}_outlet_{n}_state/config` (retained discovery)

### Why not the `epdu2.5.*` outlet table?

CyberPower's newer MIB at `enterprises.3808.1.1.6.5.{1,2}.*` is
defined but **empty** on PDU41001 firmware 1.3.2 — the outlet
data only lives on the older `epdu` branch. Other models in the
same family behave the same way. The older branch also covers
older PDU31xxx/PDU71xxx hardware.

### No per-outlet load on PDU41001

PDU41001 is a **Switched** series PDU — per-outlet on/off control
but bank-level metering only. CyberPower's *Switched Metered-
by-Outlet* models (a different series) expose a per-outlet load
table; the bridge doesn't query for it today, but will once
someone with that hardware contributes the OID.

## OIDs we deliberately don't read (yet)

- `epdu.6.*` (sensor probes — temp/humidity if a probe is plugged
  into the PDU's RJ12 port). Add as an opt-in module if anyone
  has hardware to test against.
- `epdu.7.*` (per-outlet alarms / thresholds). Configuration data,
  not telemetry — not useful for HA entities.

## Outlet control (v0.2+)

The same OID we *read* for outlet state — `epdu.3.3.3.1.1.4.{n}`
— is **writable** via `snmpset` with the **`private`** community
(not `public`). Write integer values:

| Value | Effect |
|---|---|
| `1` | ON |
| `2` | OFF |
| `3` | REBOOT (PDU sequences off → delay → on internally) |
| `4` | CANCEL (cancels a pending command issued above) |

Write is gated by **two** env vars on the bridge side:

- `OUTLET_CONTROL_ENABLED` — master switch. False (the default)
  rejects every command with a 501.
- `OUTLET_CONTROL_ALLOW` — CSV of outlet numbers permitted to be
  actuated when enabled. Empty string (default) means *all*
  outlets are allowed; `"1,3,8"` restricts to those three.

Plus one credential:

- `PDU_WRITE_COMMUNITY` — the SNMP community string with write
  access on the PDU. Defaults to `""` in code so a forgotten
  config fails fast rather than silently writing with a wrong
  community. Set to `"private"` (CyberPower factory default) or
  whatever your unit has configured.
- `PDU_SNMP_WRITE_VERSION` — `v2c` (default) or `v1`. CyberPower
  firmware varies; if v2c writes are rejected, switch to v1.

Verify in your PDU's web UI under **Configuration → Security →
SNMPv1**: the community you use for writes must have access type
**Read/Write**, and (depending on configuration) its IP filter
must either be `0.0.0.0` (any host) or include the bridge pod's
source IP.

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
