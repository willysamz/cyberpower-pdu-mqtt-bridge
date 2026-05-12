"""Singletons + shared state, set during the FastAPI lifespan."""

from datetime import UTC, datetime

from app.controller import Controller
from app.poller import Poller

_poller: Poller | None = None
_controller: Controller | None = None
_startup_time: datetime | None = None


def set_poller(poller: Poller) -> None:
    global _poller
    _poller = poller


def get_poller() -> Poller:
    if _poller is None:
        raise RuntimeError("Poller not initialized")
    return _poller


def set_controller(controller: Controller) -> None:
    global _controller
    _controller = controller


def get_controller() -> Controller:
    if _controller is None:
        raise RuntimeError("Controller not initialized")
    return _controller


def set_startup_time(time: datetime) -> None:
    global _startup_time
    _startup_time = time


def get_startup_time() -> datetime:
    if _startup_time is None:
        return datetime.now(UTC)
    return _startup_time
