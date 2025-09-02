from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

class ForceBuyPayload(BaseModel):
    amount_usd: float

class ForceSellPayload(BaseModel):
    trade_id: str
    percentage: float

from fastapi import Request, HTTPException

@router.post("/force_buy")
async def force_buy_endpoint(request: Request, payload: ForceBuyPayload):
    """
    Endpoint to receive and process a force buy command.
    """
    bot = request.app.state.bot
    try:
        # This is a synchronous call within an async endpoint,
        # which is fine for quick operations. If it were long,
        # it should be run in a thread pool.
        result = bot.process_force_buy(payload.amount_usd)
        if result.get("status") == "error":
            raise HTTPException(status_code=400, detail=result.get("message"))
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {str(e)}")


@router.post("/force_sell")
async def force_sell_endpoint(request: Request, payload: ForceSellPayload):
    """
    Endpoint to receive and process a force sell command.
    """
    bot = request.app.state.bot
    try:
        result = bot.process_force_sell(payload.trade_id, payload.percentage)
        if result.get("status") == "error":
            raise HTTPException(status_code=400, detail=result.get("message"))
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An internal error occurred: {str(e)}")
