# cyberpower-pdu-mqtt-bridge

SNMP → MQTT bridge for **CyberPower** switched / monitored PDUs
with Home Assistant auto-discovery.

Polls your PDU over SNMPv2c, publishes per-outlet state + load + bank
totals to MQTT, and emits Home Assistant MQTT-discovery messages so
HA registers the device automatically.

## Features

- Per-outlet on/off state + current draw (amps)
- Per-outlet derived watts (apparent power; amps × volts)
- Whole-PDU load + voltage
- Home Assistant MQTT-discovery (no HA YAML needed)
- LWT-driven availability topic
- FastAPI control plane: `/healthz/live`, `/healthz/ready`,
  `/api/status`, `/api/system`, `/api/version`, `/api/pdu`,
  plus scaffolded `/api/outlets/{n}/{on|off|cycle}` (returns 501
  until `OUTLET_CONTROL_ENABLED=true` lands in v0.2)
- Multi-arch container image (`linux/amd64`, `linux/arm64`) on
  GitHub Container Registry
- Helm chart published to gh-pages

## Tested hardware

- **CyberPower PDU41001** running firmware 1.3.2

Other PDU41xxx / PDU81xxx units that use the same
`enterprises.3808.1.1.6` (`epdu2`) MIB branch should work
out-of-the-box. PRs adding support for other CyberPower model
families (or other vendors) welcome.

## Quick Start

### Docker

```bash
docker run --rm -p 8080:8080 \
  -e PDU_HOST=<your PDU's IP> \
  -e MQTT_HOST=<your broker's hostname> \
  ghcr.io/willysamz/cyberpower-pdu-mqtt-bridge:latest
```

The bridge polls every 15 s by default, publishes to `pdu/...` topics
on your broker, and registers HA-discovery topics under
`homeassistant/sensor/...` and `homeassistant/binary_sensor/...`.

### Helm

```bash
helm repo add cyberpower-pdu-mqtt-bridge \
  https://willysamz.github.io/cyberpower-pdu-mqtt-bridge

helm install pdu cyberpower-pdu-mqtt-bridge/cyberpower-pdu-mqtt-bridge \
  --set pdu.host=192.0.2.10 \
  --set mqtt.host=mqtt.mqtt.svc.cluster.local
```

See [`chart/values.yaml`](chart/values.yaml) for the full set of
configurable options.

## Configuration (env vars)

| Var | Default | Purpose |
|---|---|---|
| `PDU_HOST` | `192.0.2.1` | **required** — IP/hostname of the PDU |
| `PDU_PORT` | `161` | SNMP UDP port |
| `PDU_COMMUNITY` | `public` | SNMP v2c community |
| `PDU_SNMP_TIMEOUT` | `5.0` | seconds per SNMP request |
| `POLL_INTERVAL` | `15` | seconds between polls |
| `MQTT_HOST` | `mqtt` | **required** — broker hostname |
| `MQTT_PORT` | `1883` | broker TCP port |
| `MQTT_USERNAME` | (empty) | broker auth — optional |
| `MQTT_PASSWORD` | (empty) | broker auth — optional |
| `MQTT_TOPIC_PREFIX` | `pdu` | root for state topics |
| `HA_DISCOVERY_ENABLED` | `true` | publish HA-discovery payloads |
| `HA_DISCOVERY_PREFIX` | `homeassistant` | HA discovery topic root |
| `HA_DEVICE_NAME` | `CyberPower PDU` | name shown in HA's device card |
| `HA_DEVICE_ID` | (auto from SNMP `sysName`) | stable id used in `unique_id` |
| `OUTLET_CONTROL_ENABLED` | `false` | Phase 2 — disabled at v0.1 |
| `LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `LOG_JSON` | `true` | structured JSON logs vs human-readable |

## Architecture

```
CyberPower PDU                      Home Assistant
       │                                  ▲
       │  SNMPv2c (UDP/161, read-only)    │ MQTT discovery + state
       ▼                                  │
   ┌─────────────────────────────────────┴────────────┐
   │  cyberpower-pdu-mqtt-bridge                       │
   │  ┌─────────────┐  ┌─────────────┐                 │
   │  │ Poller loop │→ │ MqttClient  │→ broker → HA   │
   │  └─────────────┘  └─────────────┘                 │
   │  ┌────────────────────────────────────────────┐  │
   │  │ FastAPI: /healthz, /api/status, /api/pdu   │  │
   │  └────────────────────────────────────────────┘  │
   └───────────────────────────────────────────────────┘
```

The Poller runs as a lifespan-managed asyncio task, polling the PDU
every `POLL_INTERVAL` seconds, parsing the responses through
`app/cyberpower.py`, and publishing to MQTT. Status snapshots are
cached and exposed on the REST API; HA's MQTT integration consumes
the discovery + state topics directly.

## Documentation

- [`docs/cyberpower-mibs.md`](docs/cyberpower-mibs.md) — exact OIDs we read
- [`docs/home-assistant.md`](docs/home-assistant.md) — HA setup walkthrough

## Development

```bash
make install        # create .venv, install deps
make dev            # hot-reload uvicorn on :8080
make test           # pytest
make lint           # ruff + mypy
make build          # docker image
make helm-lint      # helm lint chart/
```

## Releasing

Bumps are driven by tag pushes; the `release.yml` workflow validates
that the tag matches `VERSION`, builds the multi-arch image, and
packages + indexes the Helm chart.

```bash
make bump-patch     # 0.1.0 → 0.1.1
git add -A && git commit -m "chore: release v0.1.1"
git tag v0.1.1
git push origin main --tags
```

## License

[MIT](LICENSE)
