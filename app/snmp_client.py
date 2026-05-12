"""Thin async wrapper around pysnmp for the polling loop.

Targets pysnmp-lextudio 6.1.x (the maintained fork; upstream pysnmp is
unmaintained). Only SNMPv2c reads are exposed at v0.1 — writes for
outlet control are scaffolded behind a separate code path that's
disabled by default.
"""

from __future__ import annotations

from typing import Any

import structlog
from pysnmp.hlapi.asyncio import (
    CommunityData,
    ContextData,
    Integer,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    getCmd,  # noqa: N813 — pysnmp's public symbols use camelCase
    setCmd,  # noqa: N813
    walkCmd,  # noqa: N813
)

log = structlog.get_logger()


class SnmpError(Exception):
    """Raised for any SNMP failure the caller cares about."""


class SnmpClient:
    """Asyncio SNMP client tuned for one-target polling."""

    def __init__(
        self,
        host: str,
        port: int = 161,
        community: str = "public",
        write_community: str = "",
        snmp_write_version: str = "v2c",
        timeout: float = 5.0,
        retries: int = 1,
    ) -> None:
        self.host = host
        self.port = port
        self.community = community
        # Write community can stay empty when outlet control is disabled.
        # Callers that actually attempt a `set_*` while this is empty get a
        # clear SnmpError instead of a public-community write hitting the PDU.
        self.write_community = write_community
        self.snmp_write_version = snmp_write_version
        self.timeout = timeout
        self.retries = retries
        self._engine = SnmpEngine()

    def _read_auth(self) -> CommunityData:
        """SNMPv2c read community (mpModel=1)."""
        return CommunityData(self.community, mpModel=1)

    def _write_auth(self) -> CommunityData:
        """Write community using the configured SNMP version.

        mpModel=0 -> SNMPv1
        mpModel=1 -> SNMPv2c (default; works on most modern CyberPower firmware)
        """
        if not self.write_community:
            raise SnmpError("no SNMP write community configured (set PDU_WRITE_COMMUNITY)")
        mp_model = 0 if self.snmp_write_version.lower() in ("v1", "1") else 1
        return CommunityData(self.write_community, mpModel=mp_model)

    def _target(self) -> UdpTransportTarget:
        # In pysnmp-lextudio 6.1.x UdpTransportTarget is constructed
        # synchronously; 6.2+ moved this to an async `.create()` classmethod.
        return UdpTransportTarget(
            (self.host, self.port), timeout=self.timeout, retries=self.retries
        )

    async def get(self, oid: str) -> Any:
        """SNMP GET a single OID. Returns the value or None on noSuchObject."""
        error_indication, error_status, _error_index, var_binds = await getCmd(
            self._engine,
            self._read_auth(),
            self._target(),
            ContextData(),
            ObjectType(ObjectIdentity(oid)),
        )

        if error_indication:
            raise SnmpError(f"SNMP GET {oid}: {error_indication}")
        if error_status:
            raise SnmpError(f"SNMP GET {oid}: {error_status.prettyPrint()}")

        for _name, value in var_binds:
            cls_name = value.__class__.__name__
            if cls_name in ("NoSuchObject", "NoSuchInstance", "EndOfMibView"):
                return None
            return value.prettyPrint() if hasattr(value, "prettyPrint") else value
        return None

    async def get_many(self, oids: list[str]) -> dict[str, Any]:
        """SNMP GET a batch of OIDs. Returns a dict {oid: value | None}.

        Issues one GET per OID for v0.1 simplicity. A v0.2 improvement is
        to coalesce these into a single bulk-PDU.
        """
        out: dict[str, Any] = {}
        for oid in oids:
            try:
                out[oid] = await self.get(oid)
            except SnmpError as exc:
                log.warning("snmp_get_failed", oid=oid, error=str(exc))
                out[oid] = None
        return out

    async def walk(self, oid_prefix: str, max_rows: int = 64) -> dict[str, Any]:
        """SNMP-WALK a subtree. Returns a dict {full_oid: value} for each row.

        Stops at `max_rows` to guard against runaway traversal on
        misconfigured devices. Caller can override for very large
        outlet tables.
        """
        results: dict[str, Any] = {}
        rows = 0
        prefix_str = oid_prefix.lstrip(".")

        # walkCmd is an async generator in pysnmp-lextudio 6.1.x, scoped to
        # the subtree starting at the seed OID. We additionally bound it by
        # max_rows and an explicit prefix check (defensive against agents
        # that don't honour `lexicographicMode`).
        async for error_indication, error_status, _error_index, var_binds in walkCmd(
            self._engine,
            self._read_auth(),
            self._target(),
            ContextData(),
            ObjectType(ObjectIdentity(oid_prefix)),
            lexicographicMode=False,
        ):
            if error_indication:
                raise SnmpError(f"SNMP WALK {oid_prefix}: {error_indication}")
            if error_status:
                raise SnmpError(f"SNMP WALK {oid_prefix}: {error_status.prettyPrint()}")
            for name, value in var_binds:
                name_str = str(name).lstrip(".")
                if not (name_str == prefix_str or name_str.startswith(prefix_str + ".")):
                    return results
                cls_name = value.__class__.__name__
                if cls_name in ("NoSuchObject", "NoSuchInstance", "EndOfMibView"):
                    continue
                results[name_str] = value.prettyPrint() if hasattr(value, "prettyPrint") else value
            rows += 1
            if rows >= max_rows:
                break

        return results

    async def set_int(self, oid: str, value: int) -> None:
        """SNMP SET an integer value at `oid` using the write community.

        Raises `SnmpError` if no write community is configured or if the
        PDU returns any non-`noError` response. Returns nothing on success.
        """
        error_indication, error_status, _error_index, var_binds = await setCmd(
            self._engine,
            self._write_auth(),
            self._target(),
            ContextData(),
            ObjectType(ObjectIdentity(oid), Integer(value)),
        )

        if error_indication:
            raise SnmpError(f"SNMP SET {oid}={value}: {error_indication}")
        if error_status:
            raise SnmpError(f"SNMP SET {oid}={value}: {error_status.prettyPrint()}")
        log.info("snmp_set_succeeded", oid=oid, value=value, var_binds=str(var_binds))
