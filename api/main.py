from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import subprocess
import json
import os
import signal
import sys

# Add project root to sys.path to allow imports from other directories
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scripts.get_bot_data import get_bot_data


app = FastAPI()

running_bots = {}

@app.get("/api/bot-info")
async def get_bot_info(mode: str):
    if mode not in ["test", "trade"]:
        raise HTTPException(status_code=400, detail="Invalid mode. Use 'test' or 'trade'.")

    try:
        data = get_bot_data(mode)
        if "error" in data:
            raise HTTPException(status_code=500, detail=data["error"])
        return JSONResponse(content=data)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {e}")

@app.post("/api/start-bot")
async def start_bot(mode: str):
    if mode not in ["test", "trade"]:
        raise HTTPException(status_code=400, detail="Invalid mode. Use 'test' or 'trade'.")

    if mode in running_bots:
        raise HTTPException(status_code=400, detail=f"Bot in '{mode}' mode is already running.")

    try:
        env = os.environ.copy()
        env["BOT_MODE"] = mode
        command = ["python", "jules_bot/main.py"]
        process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        running_bots[mode] = process
        return {"message": f"Bot in '{mode}' mode started successfully.", "pid": process.pid}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start bot: {e}")

@app.post("/api/stop-bot")
async def stop_bot(mode: str):
    if mode not in ["test", "trade"]:
        raise HTTPException(status_code=400, detail="Invalid mode. Use 'test' or 'trade'.")

    if mode not in running_bots:
        raise HTTPException(status_code=400, detail=f"Bot in '{mode}' mode is not running.")

    try:
        process = running_bots[mode]
        os.kill(process.pid, signal.SIGTERM)
        process.wait()
        del running_bots[mode]

        return {"message": f"Bot in '{mode}' mode stopped successfully."}
    except Exception as e:
        # Even if killing the process fails, we remove it from our list
        if mode in running_bots:
            del running_bots[mode]
        raise HTTPException(status_code=500, detail=f"Failed to stop bot: {e}. The bot process may still be running.")