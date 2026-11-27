"""Shared ASGI requests that let fillback tests pause PDF delivery."""

import asyncio
import json

from wenyi_babeldoc_bridge import server


async def post_fillback(payload, *, before_send=None, disconnect=None, spec="2.4"):
    """Drive ASGI directly so a response can pause before Starlette opens its PDF."""
    messages = []
    body = json.dumps(payload).encode()
    sent_input = False

    async def receive():
        nonlocal sent_input
        if not sent_input:
            sent_input = True
            return {"type": "http.request", "body": body}
        if disconnect is None:
            await asyncio.Future()
        else:
            await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if before_send is not None:
            await before_send(message)
        messages.append(message)

    await server.app(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": spec},
            "method": "POST",
            "scheme": "http",
            "path": "/fillback",
            "raw_path": b"/fillback",
            "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
            "extensions": {"http.response.pathsend": {}},
        },
        receive,
        send,
    )
    return messages


def response_body(messages):
    return b"".join(
        message["body"]
        for message in messages
        if message["type"] == "http.response.body"
    )
