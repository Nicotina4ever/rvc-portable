"""Accessori condivisi dalle rotte API (stato applicativo)."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from ..core.engine import Engine
from ..core.jobs import JobQueue
from ..events import EventBus
from ..paths import AppPaths
from ..settings import SettingsManager


def paths(request: Request) -> AppPaths:
    return request.app.state.paths


def settings_manager(request: Request) -> SettingsManager:
    return request.app.state.settings_manager


def engine(request: Request) -> Engine:
    return request.app.state.engine


def jobs(request: Request) -> JobQueue:
    return request.app.state.job_queue


def watcher(request: Request) -> Any:
    return request.app.state.watcher


def bus(request: Request) -> EventBus:
    return request.app.state.bus


def token(request: Request) -> str:
    return request.app.state.token


def port(request: Request) -> int:
    return request.app.state.port
