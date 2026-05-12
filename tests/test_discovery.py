"""Unit tests for HA discovery payload + topic builders."""

from app.discovery import (
    _slug,
    bank_load_amps_payload,
    derive_device_id,
    outlet_state_payload,
)
from app.models import OutletReading, OutletState, PduIdentity


def _identity() -> PduIdentity:
    return PduIdentity(
        sys_descr="CPS Power Distributed Unit",
        sys_name="PDU41001",
        model="PDU41001",
        firmware="1.3.2",
        serial="NLVPU7000742",
    )


class TestSlug:
    def test_lowercases_and_underscores(self) -> None:
        assert _slug("My PDU") == "my_pdu"

    def test_strips_punctuation(self) -> None:
        assert _slug("Rack-PDU #1") == "rack_pdu_1"

    def test_empty_falls_back(self) -> None:
        assert _slug("") == "pdu"


class TestDeriveDeviceId:
    def test_uses_configured_when_set(self) -> None:
        assert derive_device_id("Rack PDU", _identity()) == "rack_pdu"

    def test_falls_back_to_sysname(self) -> None:
        assert derive_device_id("", _identity()) == "pdu41001"

    def test_constant_fallback_when_nothing_known(self) -> None:
        assert derive_device_id("", PduIdentity(sys_name=None, sys_descr=None)) == "cyberpower_pdu"


class TestBankLoadAmpsPayload:
    def test_topic_and_payload_shape(self) -> None:
        topic, payload = bank_load_amps_payload(
            discovery_prefix="homeassistant",
            device_id="pdu41001",
            device_name="Rack PDU",
            state_topic="pdu/total/load_amps",
            availability_topic="pdu/bridge/available",
            identity=_identity(),
        )
        assert topic == "homeassistant/sensor/pdu41001_total_load_amps/config"
        assert payload["unique_id"] == "pdu41001_total_load_amps"
        assert payload["state_topic"] == "pdu/total/load_amps"
        assert payload["device_class"] == "current"
        assert payload["unit_of_measurement"] == "A"
        assert payload["state_class"] == "measurement"
        assert payload["device"]["manufacturer"] == "CyberPower"
        assert payload["device"]["model"] == "PDU41001"
        assert payload["device"]["sw_version"] == "1.3.2"
        assert payload["device"]["serial_number"] == "NLVPU7000742"
        assert payload["device"]["identifiers"] == ["pdu41001"]


class TestOutletStatePayload:
    def test_uses_outlet_name_when_set(self) -> None:
        outlet = OutletReading(number=1, name="Frigate Server", state=OutletState.ON, load_amps=0.4)
        topic, payload = outlet_state_payload(
            discovery_prefix="homeassistant",
            device_id="pdu41001",
            device_name="Rack PDU",
            state_topic="pdu/outlet/1/state",
            availability_topic="pdu/bridge/available",
            identity=_identity(),
            outlet=outlet,
        )
        assert topic == "homeassistant/binary_sensor/pdu41001_outlet_1_state/config"
        assert payload["name"] == "Frigate Server"
        assert payload["payload_on"] == "ON"
        assert payload["payload_off"] == "OFF"

    def test_falls_back_to_indexed_name(self) -> None:
        outlet = OutletReading(number=3, name=None, state=OutletState.OFF)
        _, payload = outlet_state_payload(
            discovery_prefix="homeassistant",
            device_id="pdu41001",
            device_name="Rack PDU",
            state_topic="pdu/outlet/3/state",
            availability_topic="pdu/bridge/available",
            identity=_identity(),
            outlet=outlet,
        )
        assert payload["name"] == "Outlet 3"
