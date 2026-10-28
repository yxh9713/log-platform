from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class LoginBodyLimit:
    """Bound login bodies before JSON parsing, including chunked requests."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        limits = {"/v1/login": 8192, "/v1/shipments": 65536}
        if scope["type"] != "http" or scope["path"] not in limits:
            await self.app(scope, receive, send)
            return
        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > limits[scope["path"]]:
                await JSONResponse(
                    {
                        "message": "Login request is too large"
                        if scope["path"] == "/v1/login"
                        else "Shipment request is too large"
                    },
                    status_code=413,
                    headers={"Cache-Control": "no-store"},
                )(scope, receive, send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {
                    "type": "http.request",
                    "body": b"".join(chunks),
                    "more_body": False,
                }
            return await receive()

        await self.app(scope, replay, send)
