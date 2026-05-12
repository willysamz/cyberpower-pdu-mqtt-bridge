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

# Outlet management table — under the OLDER `epdu` branch (.1.1.3),
# *not* the `epdu2` branch (.1.1.6) where the bank stats live.
# The PDU41001 firmware we tested exposes outlets here, with the
# `epdu2.5.1.*` outlet table missing entirely. Other CyberPower
# switched-PDU MIBs also expose this older branch, so it's the
# more compatible read path.
#
# `enterprises.3808.1.1.3.3.3.1.1.*.{outlet_idx}`
#   .1 -> outlet number (int, 1..N)
#   .2 -> outlet name   (string, user-set in PDU UI; defaults to "OutletN")
#   .4 -> outlet command / current state
#         1 = ON
#         2 = OFF
#         3 = REBOOT-pending
#         4 = CANCEL-pending
#         (This OID is *also* the write target for outlet control —
#          see `docs/cyberpower-mibs.md`. v0.1.x reads only; v0.2 adds
#          write via this same OID gated by OUTLET_CONTROL_ENABLED.)
OID_OUTLET_NAME_BASE = "1.3.6.1.4.1.3808.1.1.3.3.3.1.1.2"
OID_OUTLET_STATE_BASE = "1.3.6.1.4.1.3808.1.1.3.3.3.1.1.4"

# PDU41001 is part of CyberPower's *Switched* series — per-outlet
# on/off but bank-level metering only. The MIB has no per-outlet
# load on this hardware. Other CyberPower *Switched Metered-by-
# Outlet* models do expose it; we'll add that OID under a separate
# constant once we have one to test against.


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
