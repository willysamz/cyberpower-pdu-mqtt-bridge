"""FastAPI app entry point with lifespan-managed poller + MQTT session."""

import asyncio
import re
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import structlog
from fastapi import FastAPI

from app import __version__
from app.config import settings
from app.controller import (
    ControlDisabledError,
    Controller,
    OutletNotAllowedError,
)
from app.dependencies import set_controller, set_poller, set_startup_time
from app.models import OutletCommand
from app.mqtt_client import MqttClient
from app.poller import Poller
from app.routers import health, outlets, status, system
from app.snmp_client import SnmpClient, SnmpError

LOG_LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
_renderer = (
    structlog.processors.JSONRenderer() if settings.log_json else structlog.dev.ConsoleRenderer()
)
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _renderer,  # type: ignore[list-item]
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        LOG_LEVELS.get(settings.log_level.upper(), 20)
    ),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)
log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Start MQTT session + background poller; tear them down on shutdown."""
    set_startup_time(datetime.now(UTC))
    log.info(
        "starting_bridge",
        version=__version__,
        pdu_host=settings.pdu_host,
        mqtt_host=settings.mqtt_host,
        poll_interval=settings.poll_interval,
    )

    snmp = SnmpClient(
        host=settings.pdu_host,
        port=settings.pdu_port,
        community=settings.pdu_community,
        write_community=settings.pdu_write_community,
        snmp_write_version=settings.pdu_snmp_write_version,
        timeout=settings.pdu_snmp_timeout,
        retries=settings.pdu_snmp_retries,
    )
    mqtt = MqttClient(
        host=settings.mqtt_host,
        port=settings.mqtt_port,
        username=settings.mqtt_username,
        password=settings.mqtt_password,
        client_id=settings.mqtt_client_id,
        keepalive=settings.mqtt_keepalive,
        qos=settings.mqtt_qos,
        availability_topic=f"{settings.mqtt_topic_prefix.strip('/')}/bridge/available",
    )
    poller = Poller(snmp=snmp, mqtt=mqtt, settings=settings)
    set_poller(poller)
    controller = Controller(snmp=snmp, mqtt=mqtt, poller=poller, settings=settings)
    set_controller(controller)

    # Run the MQTT session for the lifetime of the app; the poller publishes
    # through `mqtt` and pulls from `snmp` inside that session.
    mqtt_ctx = mqtt.session()
    await mqtt_ctx.__aenter__()
    await poller.start()
    command_task = asyncio.create_task(
        _command_subscriber(mqtt, controller, settings.mqtt_topic_prefix)
    )

    try:
        yield
    finally:
        log.info("shutting_down_bridge")
        command_task.cancel()
        await poller.stop()
        await mqtt_ctx.__aexit__(None, None, None)


_OUTLET_TOPIC_RE = re.compile(r"^[^/]+/outlet/(?P<n>\d+)/set$")


async def _command_subscriber(mqtt: MqttClient, controller: Controller, topic_prefix: str) -> None:
    """Subscribe to outlet command topics and route messages to the Controller.

    Topic shape:  {prefix}/outlet/{N}/set     payload: ON | OFF | REBOOT | CANCEL
    """
    prefix = topic_prefix.strip("/")
    sub_topic = f"{prefix}/outlet/+/set"
    await mqtt.subscribe(sub_topic)
    log.info("command_subscriber_started", topic=sub_topic)
    async for msg in mqtt.messages:
        topic_str = str(msg.topic)
        m = _OUTLET_TOPIC_RE.match(topic_str)
        if not m:
            log.warning("command_subscriber_unmatched_topic", topic=topic_str)
            continue
        outlet = int(m.group("n"))
        raw = msg.payload
        if isinstance(raw, bytes | bytearray):
            payload = bytes(raw).decode("utf-8", errors="replace").strip().upper()
        elif isinstance(raw, str):
            payload = raw.strip().upper()
        else:
            log.warning("command_subscriber_bad_payload", topic=topic_str, type=type(raw).__name__)
            continue
        try:
            cmd = OutletCommand(payload)
        except ValueError:
            log.warning(
                "command_subscriber_unknown_command",
                topic=topic_str,
                payload=payload,
            )
            continue
        try:
            await controller.set_outlet(outlet, cmd)
        except ControlDisabledError as exc:
            log.warning("command_rejected_disabled", outlet=outlet, error=str(exc))
        except OutletNotAllowedError as exc:
            log.warning("command_rejected_not_allowed", outlet=outlet, error=str(exc))
        except SnmpError as exc:
            log.warning("command_snmp_failed", outlet=outlet, error=str(exc))


app = FastAPI(
    title="CyberPower PDU MQTT Bridge",
    description=(
        "SNMP→MQTT bridge for CyberPower switched/monitored PDUs with "
        "Home Assistant auto-discovery."
    ),
    version=__version__,
    lifespan=lifespan,
)

app.include_router(health.router, tags=["Health"])
app.include_router(system.router, prefix="/api", tags=["System"])
app.include_router(status.router, prefix="/api", tags=["Status"])
app.include_router(outlets.router, prefix="/api", tags=["Outlets"])


@app.get("/", tags=["Meta"])
async def root() -> dict:
    return {
        "name": "cyberpower-pdu-mqtt-bridge",
        "version": __version__,
        "docs": "/docs",
    }


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.server_host,
        port=settings.server_port,
        reload=False,
    )
