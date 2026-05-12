# Home Assistant integration

The bridge publishes Home Assistant MQTT-discovery messages to your
broker on first poll. HA picks them up automatically (no YAML
required) once the MQTT integration is wired up against the same
broker.

## What you get

After the bridge runs one full poll cycle, HA creates a single
device named after `HA_DEVICE_NAME` (default: "CyberPower PDU") with
this entity set:

| Entity | What it is |
|---|---|
| `binary_sensor.<device_id>_outlet_<n>_state` | One per outlet. `on` when the outlet is powered. |
| `sensor.<device_id>_outlet_<n>_load_amps` | Per-outlet current draw (amps). |
| `sensor.<device_id>_total_load_amps` | Whole-PDU load (amps). |
| `sensor.<device_id>_total_load_watts` | Apparent power (amps × volts). |
| `sensor.<device_id>_voltage` | PDU input voltage. |

Entity name in HA falls back to "Outlet 1", "Outlet 2", etc. if
you haven't set custom outlet names in the PDU's web UI. Set them
there and they propagate automatically — the bridge re-publishes
discovery payloads each restart.

## Setting up HA's MQTT integration

If your HA install doesn't yet have the MQTT integration:

1. Settings → Devices & Services → **Add Integration** → "MQTT".
2. Broker hostname: the address the broker is reachable on from
   your HA pod (e.g. `mqtt.mqtt.svc.cluster.local`, `192.168.1.x`,
   etc.).
3. Port: `1883` (or whatever your broker uses).
4. Username / password: blank if the broker is anonymous; otherwise
   fill them in.

Once the broker is connected and the bridge has run, HA's MQTT
integration page should show one new device (the PDU) under
"Discovered".

## Example automation

```yaml
- alias: "Alert: rack PDU drawing more than 5 amps"
  trigger:
    - platform: numeric_state
      entity_id: sensor.cyberpower_pdu_total_load_amps
      above: 5.0
      for: "00:00:30"
  action:
    - service: notify.mobile_app
      data:
        message: >-
          Rack PDU load is {{ states('sensor.cyberpower_pdu_total_load_amps') }} A
          (over 5 A for 30s). Check what's running hot.
```

## Why MQTT discovery and not a dedicated HA integration?

A bespoke Home Assistant custom_component would give nicer UI
(slider for outlet thresholds, etc.) but requires HACS-style
installation, restart on update, and tracks HA breaking changes.
MQTT discovery is portable: any home automation system that
understands HA-style MQTT discovery (Home Assistant, Domoticz,
etc.) consumes the same topics, and the bridge stays a single
container with no HA-version coupling.
