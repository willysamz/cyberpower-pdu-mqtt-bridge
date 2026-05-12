"""FastAPI app entry point with lifespan-managed poller + MQTT session."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import structlog
from fastapi import FastAPI

from app import __version__
from app.config import settings
from app.dependencies import set_poller, set_startup_time
from app.mqtt_client import MqttClient
from app.poller import Poller
from app.routers import health, outlets, status, system
from app.snmp_client import SnmpClient

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

    # Run the MQTT session for the lifetime of the app; the poller publishes
    # through `mqtt` and pulls from `snmp` inside that session.
    mqtt_ctx = mqtt.session()
    await mqtt_ctx.__aenter__()
    await poller.start()

    try:
        yield
    finally:
        log.info("shutting_down_bridge")
        await poller.stop()
        await mqtt_ctx.__aexit__(None, None, None)


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
