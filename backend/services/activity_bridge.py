"""
Activity Bridge — FastAPI + WebSocket hub connecting the Discord bot backend
to the Discord Activity frontend.

Events broadcast to all connected Activity clients (JSON):
  { "type": "status",  "value": "idle" | "listening" | "thinking" | "speaking" | "stopped" }
  { "type": "answer_start", "text": "...", "emotion": "joy", "voice": "..." }
  { "type": "word", "offset_ms": 1230, "duration_ms": 210, "word": "привет" }
  { "type": "answer_end" }
  { "type": "emotion", "value": "surprise" }   # touch-zone reactions (client->server echo not needed)
  { "type": "history", "items": [ {"role": "user"|"alisa", "text": "...", "ts": ...} ] }
  { "type": "voice", "value": "ru-RU-SvetlanaNeural" }
  { "type": "stop" }                            # speech interrupted

Inbound messages from the Activity UI:
  { "type": "stop" }          # Stop button in the UI
  { "type": "set_voice", "value": "ru-RU-SvetlanaNeural" }
  { "type": "request_state" } # resend current status/history
"""

import asyncio
import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger("helper_bot.bridge")


class ActivityBridge:
    def __init__(self) -> None:
        self.app = FastAPI(title="Helper Activity Bridge")
        # The Activity is served through a cloudflared HTTPS tunnel -> allow all origins.
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
        self.clients: Set[WebSocket] = set()
        self.state: Dict[str, Any] = {
            "status": "idle",
            "voice": None,
            "emotion": "neutral",
            "history": [],  # [{role, text, ts}]
        }
        # Callback set by the bot cog: called on inbound control messages.
        self.on_control: Optional[Callable[[dict], Any]] = None

        @self.app.websocket("/ws")
        async def ws_endpoint(ws: WebSocket) -> None:
            await ws.accept()
            self.clients.add(ws)
            logger.info("Activity client connected (%d total)", len(self.clients))
            try:
                await ws.send_text(
                    json.dumps(
                        {
                            "type": "state",
                            "status": self.state["status"],
                            "voice": self.state["voice"],
                            "emotion": self.state["emotion"],
                            "history": self.state["history"][-30:],
                        },
                        ensure_ascii=False,
                    )
                )
                while True:
                    raw = await ws.receive_text()
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    await self._handle_inbound(msg)
            except WebSocketDisconnect:
                pass
            finally:
                self.clients.discard(ws)
                logger.info("Activity client disconnected (%d total)", len(self.clients))

        @self.app.get("/health")
        async def health() -> dict:
            return {"ok": True, "clients": len(self.clients)}

    async def _handle_inbound(self, msg: dict) -> None:
        mtype = msg.get("type")
        if mtype == "request_state":
            await self.broadcast(
                {
                    "type": "state",
                    "status": self.state["status"],
                    "voice": self.state["voice"],
                    "emotion": self.state["emotion"],
                    "history": self.state["history"][-30:],
                }
            )
            return
        if self.on_control is not None:
            try:
                result = self.on_control(msg)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("Error in bridge control handler")

    # ---------------------------------------------------------------- broadcast

    async def broadcast(self, payload: dict) -> None:
        if not self.clients:
            return
        raw = json.dumps(payload, ensure_ascii=False)
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(raw)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    async def set_status(self, value: str) -> None:
        self.state["status"] = value
        await self.broadcast({"type": "status", "value": value})

    async def set_voice(self, value: str) -> None:
        self.state["voice"] = value
        await self.broadcast({"type": "voice", "value": value})

    async def push_history(self, role: str, text: str) -> None:
        self.state["history"].append(
            {"role": role, "text": text, "ts": int(time.time())}
        )
        self.state["history"] = self.state["history"][-60:]
        await self.broadcast(
            {
                "type": "history",
                "items": self.state["history"][-30:],
            }
        )


bridge = ActivityBridge()
