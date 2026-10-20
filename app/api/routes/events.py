"""Server-Sent Events: log, job, monitor, config, engine."""

from __future__ import annotations

import json

import anyio.to_thread
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ... import __version__
from .. import deps

router = APIRouter(tags=["events"])

HEARTBEAT_S = 15.0


def _format(event) -> str:
    data = json.dumps(event.get("data") or {}, ensure_ascii=False)
    return "id: %s\nevent: %s\ndata: %s\n\n" % (
        event.get("id", 0),
        event.get("type", "message"),
        data,
    )


@router.get("/api/events")
async def stream_events(request: Request, since: int = 0):
    bus = deps.bus(request)
    session_token = deps.token(request)

    async def generator():
        subscription = bus.subscribe()
        try:
            hello = {
                "id": 0,
                "type": "hello",
                "data": {
                    "version": __version__,
                    "last_event_id": bus.last_id,
                    "token": session_token,
                    "since": since,
                },
            }
            yield _format(hello)
            for past in bus.replay_since(since):
                yield _format(past)
            idle = 0.0
            while True:
                if await request.is_disconnected():
                    break
                event = await anyio.to_thread.run_sync(subscription.get, 0.5)
                if event is None:
                    idle += 0.5
                    if idle >= HEARTBEAT_S:
                        idle = 0.0
                        yield ": ping\n\n"
                    continue
                idle = 0.0
                yield _format(event)
        finally:
            subscription.close()

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/events/history")
def history(request: Request, since: int = 0):
    bus = deps.bus(request)
    return {"last_id": bus.last_id, "events": bus.replay_since(since)}
