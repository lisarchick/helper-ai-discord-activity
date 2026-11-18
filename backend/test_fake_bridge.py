# Fake bridge for visual lipsync testing (dev tool, not shipped).
import asyncio, json
import websockets

WORDS = [
    {"offset_ms": 100, "duration_ms": 420, "word": "Привет"},
    {"offset_ms": 560, "duration_ms": 380, "word": "Меня"},
    {"offset_ms": 980, "duration_ms": 340, "word": "зовут"},
    {"offset_ms": 1360, "duration_ms": 480, "word": "Алиса"},
]

async def run():
    clients = set()
    async def handler(ws):
        clients.add(ws)
        try:
            await ws.send(json.dumps({"type": "state", "status": "idle", "voice": "ru-RU-SvetlanaNeural", "emotion": "neutral", "history": []}))
            async for m in ws:
                pass
        except Exception:
            pass
        finally:
            clients.discard(ws)
    async with websockets.serve(handler, "127.0.0.1", 8765):
        print("fake bridge on 8765", flush=True)
        while True:
            await asyncio.sleep(4)
            for c in list(clients):
                try:
                    await c.send(json.dumps({"type": "answer_start", "text": "Привет! Меня зовут Алиса, и я очень рада тебя видеть.", "emotion": "joy"}))
                    await c.send(json.dumps({"type": "words", "items": WORDS}))
                except Exception:
                    pass
            await asyncio.sleep(3)
            for c in list(clients):
                try:
                    await c.send(json.dumps({"type": "answer_end"}))
                    await c.send(json.dumps({"type": "emotion", "value": "neutral"}))
                except Exception:
                    pass

asyncio.run(run())
