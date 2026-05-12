"""Unit tests for the CyberPower OID parsers."""

from app.cyberpower import (
    OUTLET_COMMAND_VALUES,
    deciamps_to_amps,
    outlet_oid,
    parse_outlet_state,
    watts_from_amps_volts,
)


class TestDeciampsToAmps:
    def test_typical_value(self) -> None:
        assert deciamps_to_amps(8) == 0.8

    def test_zero(self) -> None:
        assert deciamps_to_amps(0) == 0.0

    def test_string_int(self) -> None:
        # SNMP pretty-printed Gauge32 comes back as a string
        assert deciamps_to_amps("12") == 1.2

    def test_none(self) -> None:
        assert deciamps_to_amps(None) is None

    def test_garbage(self) -> None:
        assert deciamps_to_amps("not a number") is None


class TestParseOutletState:
    def test_on(self) -> None:
        assert parse_outlet_state(1) == "ON"

    def test_off(self) -> None:
        assert parse_outlet_state(2) == "OFF"

    def test_pending_off_treated_as_on(self) -> None:
        # State 3 = pendingOff (still drawing power) — call it ON for HA.
        assert parse_outlet_state(3) == "ON"

    def test_pending_on_treated_as_off(self) -> None:
        # State 4 = pendingOn (still off until the command lands) — OFF.
        assert parse_outlet_state(4) == "OFF"

    def test_string_input(self) -> None:
        assert parse_outlet_state("1") == "ON"
        assert parse_outlet_state("2") == "OFF"

    def test_none(self) -> None:
        assert parse_outlet_state(None) == "UNKNOWN"

    def test_unexpected_value(self) -> None:
        assert parse_outlet_state(99) == "UNKNOWN"


class TestOutletOid:
    def test_builds_indexed_oid(self) -> None:
        assert outlet_oid("1.3.6.1.4.1.3808.1.1.6.5.1.1.3", 5) == (
            "1.3.6.1.4.1.3808.1.1.6.5.1.1.3.5"
        )


class TestWattsFromAmpsVolts:
    def test_typical(self) -> None:
        assert watts_from_amps_volts(0.8, 119.6) == 95.7

    def test_zero_load(self) -> None:
        assert watts_from_amps_volts(0.0, 119.6) == 0.0

    def test_missing_amps(self) -> None:
        assert watts_from_amps_volts(None, 119.6) is None

    def test_missing_volts(self) -> None:
        assert watts_from_amps_volts(0.8, None) is None


class TestOutletCommandValues:
    def test_all_four_commands_mapped(self) -> None:
        # The 4 verbs the CyberPower MIB accepts on the outlet-command OID.
        # gportay/cyberpower-pdu and the CyberPower MIB both use these ints.
        assert OUTLET_COMMAND_VALUES["ON"] == 1
        assert OUTLET_COMMAND_VALUES["OFF"] == 2
        assert OUTLET_COMMAND_VALUES["REBOOT"] == 3
        assert OUTLET_COMMAND_VALUES["CANCEL"] == 4
        assert set(OUTLET_COMMAND_VALUES.keys()) == {"ON", "OFF", "REBOOT", "CANCEL"}
