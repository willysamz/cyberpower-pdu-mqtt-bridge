"""CyberPower ePDU MIB OID constants and parsers.

This module pins the OIDs we read from a CyberPower switched/monitored PDU
and translates the raw SNMP varbind values into the typed `models.OutletReading`
/ `BankReading` / `PduIdentity` shapes the rest of the app speaks.

Reference: CyberPower's `CyberPower_MIB_v2.7.mib` (enterprises.3808). All OIDs
below sit under `1.3.6.1.4.1.3808.1.1.6` (epdu2) which is the modern monitored
PDU branch CyberPower uses on PDU41xxx / PDU81xxx hardware.

Some OIDs are guarded with `# verified-on:` comments noting hardware we've
seen them work on; PRs adding other models are welcome.

The bridge tolerates an OID returning no value (None / NoSuchObject) — the
corresponding field in the snapshot becomes `None` rather than raising.
"""

from __future__ import annotations

from typing import Any

# Standard SNMPv2-MIB
OID_SYS_DESCR = "1.3.6.1.2.1.1.1.0"
OID_SYS_NAME = "1.3.6.1.2.1.1.5.0"

# Bank-level status table (enterprises.3808.1.1.6.3.4.1.*.{bank_idx})
# bank_idx=1 covers the whole PDU on single-bank PDUs.
# .5  -> load (deciamps, e.g. 8 = 0.8 A)
# .6  -> alarm threshold (deciamps; not published)
# .9  -> firmware-dependent (sometimes voltage decivolts, sometimes other) —
#         intentionally not published; see `Settings.mains_voltage` and
#         `docs/cyberpower-mibs.md` for the reasoning.
OID_BANK_STATUS_LOAD_DECIAMPS = "1.3.6.1.4.1.3808.1.1.6.3.4.1.5.1"

# Outlet config table (enterprises.3808.1.1.6.5.1.1.*.{outlet_idx})
# .3 -> outletName (string, user-set in PDU UI; defaults to "Outlet 1" …)
OID_OUTLET_NAME_BASE = "1.3.6.1.4.1.3808.1.1.6.5.1.1.3"

# Outlet status table (enterprises.3808.1.1.6.5.2.1.*.{outlet_idx})
# .3 -> outletStatus    1=on, 2=off, 3=pendingOff, 4=pendingOn (we collapse to ON/OFF/UNKNOWN)
# .4 -> outletCurrent   deciamps
OID_OUTLET_STATE_BASE = "1.3.6.1.4.1.3808.1.1.6.5.2.1.3"
OID_OUTLET_LOAD_DECIAMPS_BASE = "1.3.6.1.4.1.3808.1.1.6.5.2.1.4"


def deciamps_to_amps(raw: Any) -> float | None:
    """Convert CyberPower's deciamp Gauge32 to float amps.

    The PDU reports current as tenths of an amp (e.g. value 8 = 0.8 A).
    """
    if raw is None:
        return None
    try:
        return int(raw) / 10.0
    except (TypeError, ValueError):
        return None


def parse_outlet_state(raw: Any) -> str:
    """Map CyberPower's outletStatus integer to our OutletState enum value.

    1 = on
    2 = off
    3 = pendingOff (still on, command queued) → ON
    4 = pendingOn  (still off, command queued) → OFF
    other → UNKNOWN
    """
    if raw is None:
        return "UNKNOWN"
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return "UNKNOWN"
    if v in (1, 3):
        return "ON"
    if v in (2, 4):
        return "OFF"
    return "UNKNOWN"


def outlet_oid(base: str, index: int) -> str:
    """Build a per-outlet OID by appending the outlet index to a base."""
    return f"{base}.{index}"


def watts_from_amps_volts(amps: float | None, volts: float | None) -> float | None:
    """Derive watts from amps × volts when the PDU doesn't expose watts directly.

    Many CyberPower switched PDUs only expose deciamps; we synthesize watts
    as a useful approximation (apparent power, not real power — same caveats
    as any non-power-factor-aware PDU calculation).
    """
    if amps is None or volts is None:
        return None
    return round(amps * volts, 1)
