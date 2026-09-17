from fastapi import APIRouter,WebSocket,WebSocketDisconnect
from auth import serializer
router=APIRouter(tags=["realtime"])
connections={}
@router.websocket("/ws/notifications")
async def socket(ws:WebSocket):
    token=ws.query_params.get("token","")
    try: uid=int(serializer.loads(token,max_age=60*60*24*30)["user_id"])
    except Exception:
        await ws.close(code=1008); return
    await ws.accept(); connections.setdefault(uid,set()).add(ws)
    try:
        while True: await ws.receive_text()
    except WebSocketDisconnect: connections.get(uid,set()).discard(ws)
async def push_notification(uid,payload):
    for ws in list(connections.get(uid,set())):
        try: await ws.send_json(payload)
        except Exception: connections.get(uid,set()).discard(ws)
