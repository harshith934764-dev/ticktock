import os,secrets
from fastapi import APIRouter,HTTPException,Request
from database import get_db
from videos import current_user_id
router=APIRouter(prefix="/api/payments",tags=["payments"])
PACKAGES={100:99,550:499,1200:999}
@router.get("/packages")
def packages(): return [{"diamonds":d,"amount_inr":a,"currency":"INR"} for d,a in PACKAGES.items()]
@router.post("/order")
async def order(request:Request):
    uid=current_user_id(request)
    if not uid: raise HTTPException(401,"Login required")
    d=await request.json(); diamonds=int(d.get("diamonds",0))
    if diamonds not in PACKAGES: raise HTTPException(400,"Invalid package")
    provider="razorpay" if os.getenv("RAZORPAY_KEY_ID") and os.getenv("RAZORPAY_KEY_SECRET") else "manual"
    oid="tt_"+secrets.token_urlsafe(18); amount=PACKAGES[diamonds]
    with get_db() as db:
        db.execute("INSERT INTO payment_orders(user_id,provider,provider_order_id,amount,currency,status) VALUES(?,?,?,?,?,?)",
                   (uid,provider,oid,amount,"INR","created"))
    return {"provider":provider,"order_id":oid,"amount":amount,"currency":"INR","diamonds":diamonds,
            "message":"Real payment fulfillment requires verified provider webhooks."}
@router.post("/webhook")
async def webhook(request:Request): return {"received":True,"credited":False}
