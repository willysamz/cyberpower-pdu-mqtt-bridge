"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="",
        env_nested_delimiter="__",
        case_sensitive=False,
    )

    # --- PDU / SNMP target ---
    # Required: address of the CyberPower PDU. Public-repo default is the
    # documentation example; deployments must override.
    pdu_host: str = "192.0.2.1"
    pdu_port: int = 161
    pdu_community: str = "public"
    pdu_snmp_version: str = "2c"  # only 2c is supported at v0.1
    pdu_snmp_timeout: float = 5.0
    pdu_snmp_retries: int = 1

    # --- Polling cadence ---
    poll_interval: float = 15.0  # seconds between polls

    # --- Mains voltage assumption ---
    # CyberPower's voltage OID layout varies across firmware revisions; some
    # PDUs don't expose it at all. To keep `watts = amps × volts` honest, the
    # bridge derives watts from this constant rather than querying the PDU.
    # Override to 230.0 for UK/EU, 240.0 for some homelab 240V circuits, etc.
    mains_voltage: float = 120.0

    # --- MQTT broker ---
    mqtt_host: str = "mqtt"
    mqtt_port: int = 1883
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    mqtt_client_id: str = "cyberpower-pdu-mqtt-bridge"
    mqtt_topic_prefix: str = "pdu"
    mqtt_keepalive: int = 60
    mqtt_qos: int = 0  # 0|1|2

    # --- Home Assistant MQTT discovery ---
    ha_discovery_enabled: bool = True
    ha_discovery_prefix: str = "homeassistant"
    ha_device_name: str = "CyberPower PDU"
    # Stable device identifier; if blank, the poller derives it from SNMP sysName.
    ha_device_id: str = ""

    # --- Outlet control ---
    # Master switch. When False (the default), the bridge subscribes to MQTT
    # command topics but rejects every command; REST endpoints return 501.
    outlet_control_enabled: bool = False
    # CSV of outlet numbers that are *permitted* to be actuated when control
    # is enabled. Empty string = all outlets allowed. Example: "1,3,8".
    outlet_control_allow: str = ""
    # SNMP write community (typically `private` on CyberPower; check
    # Configuration -> Security -> SNMPv1 in the PDU's web UI).
    # Defaults to the empty string so a misconfigured deploy fails fast
    # rather than silently using a publicly-known community on a write.
    pdu_write_community: str = ""
    # SNMP version used for the write. `v2c` works on most modern CyberPower
    # firmware; override to `v1` if the agent rejects v2c sets.
    pdu_snmp_write_version: str = "v2c"

    # --- HTTP server ---
    server_host: str = "0.0.0.0"  # noqa: S104 — binding all interfaces is intended inside a pod
    server_port: int = 8080

    # --- Logging ---
    log_level: str = "INFO"
    log_json: bool = True


settings = Settings()
