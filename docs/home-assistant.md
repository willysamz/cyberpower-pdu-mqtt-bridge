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
| `switch.<device_id>_outlet_<n>` | One per outlet. State is `on` when the outlet is powered. Toggle it to actuate the outlet — works when `OUTLET_CONTROL_ENABLED=true` (else read-only). |
| `button.<device_id>_outlet_<n>_cycle` | Power-cycle (reboot) the outlet. Publishes `REBOOT` to the same command topic. |
| `sensor.<device_id>_outlet_<n>_load_amps` | Per-outlet current draw — only on PDU models that expose per-outlet metering (Switched-Metered-by-Outlet). Missing on Switched-only PDUs like the PDU41001. |
| `sensor.<device_id>_total_load_amps` | Whole-PDU load (amps). |
| `sensor.<device_id>_total_load_watts` | Apparent power (amps × volts; uses `MAINS_VOLTAGE` config). |
| `sensor.<device_id>_voltage` | Input voltage (constant from `MAINS_VOLTAGE`; the PDU's voltage OID isn't reliable across firmware revs). |

Entity name in HA falls back to "Outlet 1", "Outlet 2", etc. if
you haven't set custom outlet names in the PDU's web UI. Set them
there and the bridge picks up the change on its next poll and
re-publishes the discovery payload, so the HA-side friendly name
updates live (no pod restart needed).

### Upgrading from v0.1.x

v0.1.x exposed read-only `binary_sensor.<device_id>_outlet_<n>_state`
entities. v0.2 retires those (the bridge publishes an empty
discovery payload to their config topic, which HA reads as a
delete) and emits new `switch` + `button` entities in their place.

If you had HA automations referencing the old `binary_sensor.*`
entities, update them to the new `switch.*` IDs after the upgrade.

## Outlet control configuration

Set on the bridge side:

- `OUTLET_CONTROL_ENABLED=true` — master switch (default `false`).
- `OUTLET_CONTROL_ALLOW="3,8"` — optional allowlist of outlet
  numbers that can be actuated. Empty string = all outlets allowed.
  Useful for limiting blast radius during the first production
  test.
- `PDU_WRITE_COMMUNITY=private` — the SNMP community with
  Read/Write access on your PDU. Check it under **Configuration
  → Security → SNMPv1** in the PDU's web UI.
- `PDU_SNMP_WRITE_VERSION=v2c` — works on most modern firmware;
  override to `v1` if the agent rejects v2c sets.

If `OUTLET_CONTROL_ENABLED=false`, the switch entities still
appear in HA but toggling them is rejected at the bridge — the
SNMP write never fires, and HA's `optimistic=false` setting on
the switch means the position reverts to whatever the next poll
reports.

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
