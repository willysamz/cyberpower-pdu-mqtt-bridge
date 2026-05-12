"""Unit tests for the Controller — outlet-control safety gates + SNMP set call."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.controller import (
    ControlDisabledError,
    Controller,
    OutletNotAllowedError,
)
from app.models import OutletCommand


def _settings(*, enabled: bool = True, allow: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        outlet_control_enabled=enabled,
        outlet_control_allow=allow,
        mqtt_topic_prefix="pdu",
    )


def _make_controller(*, enabled: bool = True, allow: str = "") -> Controller:
    snmp = AsyncMock()
    mqtt = AsyncMock()
    poller = SimpleNamespace(trigger_immediate_poll=lambda: None)
    poller.trigger_immediate_poll = AsyncMock(side_effect=lambda: None)  # type: ignore[assignment]
    # `trigger_immediate_poll` is sync in the real Poller; SimpleNamespace
    # callable just needs to be invokable. Use a no-op sync lambda for that.
    poller.trigger_immediate_poll = lambda: None  # type: ignore[assignment]
    ctrl = Controller(
        snmp=snmp, mqtt=mqtt, poller=poller, settings=_settings(enabled=enabled, allow=allow)
    )
    return ctrl


class TestParseAllow:
    def test_empty_means_empty_set(self) -> None:
        assert Controller._parse_allow("") == set()

    def test_whitespace_only_means_empty(self) -> None:
        assert Controller._parse_allow("   ") == set()

    def test_csv_parses(self) -> None:
        assert Controller._parse_allow("1,3,8") == {1, 3, 8}

    def test_handles_spaces(self) -> None:
        assert Controller._parse_allow(" 1 , 2 , 3 ") == {1, 2, 3}

    def test_skips_bad_tokens(self) -> None:
        assert Controller._parse_allow("1,foo,3") == {1, 3}


class TestSetOutletGates:
    @pytest.mark.asyncio
    async def test_disabled_raises(self) -> None:
        ctrl = _make_controller(enabled=False)
        with pytest.raises(ControlDisabledError):
            await ctrl.set_outlet(3, OutletCommand.ON)
        ctrl.snmp.set_int.assert_not_called()

    @pytest.mark.asyncio
    async def test_disallowed_outlet_raises(self) -> None:
        ctrl = _make_controller(enabled=True, allow="8")
        with pytest.raises(OutletNotAllowedError):
            await ctrl.set_outlet(3, OutletCommand.ON)
        ctrl.snmp.set_int.assert_not_called()

    @pytest.mark.asyncio
    async def test_allowed_outlet_issues_set(self) -> None:
        ctrl = _make_controller(enabled=True, allow="3,8")
        await ctrl.set_outlet(3, OutletCommand.ON)
        ctrl.snmp.set_int.assert_awaited_once()
        oid, value = ctrl.snmp.set_int.await_args[0]
        assert oid.endswith(".3")
        assert value == 1  # ON

    @pytest.mark.asyncio
    async def test_empty_allow_means_any_outlet_ok(self) -> None:
        ctrl = _make_controller(enabled=True, allow="")
        await ctrl.set_outlet(7, OutletCommand.OFF)
        ctrl.snmp.set_int.assert_awaited_once()
        _, value = ctrl.snmp.set_int.await_args[0]
        assert value == 2  # OFF


class TestSetOutletSideEffects:
    @pytest.mark.asyncio
    async def test_publishes_optimistic_state_on_on(self) -> None:
        ctrl = _make_controller()
        await ctrl.set_outlet(2, OutletCommand.ON)
        ctrl.mqtt.publish.assert_awaited_once()
        topic, value = ctrl.mqtt.publish.await_args[0]
        assert topic == "pdu/outlet/2/state"
        assert value == "ON"
        assert ctrl.mqtt.publish.await_args.kwargs["retain"] is True

    @pytest.mark.asyncio
    async def test_publishes_optimistic_state_on_off(self) -> None:
        ctrl = _make_controller()
        await ctrl.set_outlet(2, OutletCommand.OFF)
        topic, value = ctrl.mqtt.publish.await_args[0]
        assert value == "OFF"

    @pytest.mark.asyncio
    async def test_reboot_does_not_publish_state(self) -> None:
        ctrl = _make_controller()
        await ctrl.set_outlet(2, OutletCommand.REBOOT)
        ctrl.mqtt.publish.assert_not_called()
        # SNMP set still happens
        _, value = ctrl.snmp.set_int.await_args[0]
        assert value == 3  # REBOOT

    @pytest.mark.asyncio
    async def test_cancel_does_not_publish_state(self) -> None:
        ctrl = _make_controller()
        await ctrl.set_outlet(2, OutletCommand.CANCEL)
        ctrl.mqtt.publish.assert_not_called()
        _, value = ctrl.snmp.set_int.await_args[0]
        assert value == 4  # CANCEL
