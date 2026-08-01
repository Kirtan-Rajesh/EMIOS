import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.db import init_db, close_db
from app.core.logging_config import setup_logging
from app.api.endpoints import router as api_router

setup_logging()

app = FastAPI(
    title="EMIOS API - Enterprise Migration Intelligence Operating System",
    description="Backend API powering the digital twin visualization, cascading risk simulator, and multi-agent migration planner.",
    version="1.0.0"
)

# Set up CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In development, allow all origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

import time
import logging

logger = logging.getLogger("emios")

@app.middleware("http")
async def log_latency_middleware(request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time
    logger.info(
        f"Request: {request.method} {request.url.path} | "
        f"Status: {response.status_code} | "
        f"Latency: {duration:.4f}s"
    )
    return response

from fastapi.responses import JSONResponse
from app.core.exceptions import EMIOSException

@app.exception_handler(EMIOSException)
async def emios_exception_handler(request, exc: EMIOSException):
    return JSONResponse(
        status_code=400,
        content={
            "status": "error",
            "error_code": exc.error_code,
            "message": exc.message
        }
    )

@app.on_event("startup")
async def startup_event():
    init_db()

@app.on_event("shutdown")
async def shutdown_event():
    close_db()

# Register API routes
app.include_router(api_router, prefix="/api")

# Serve Frontend static files
import os
from fastapi.staticfiles import StaticFiles
frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=settings.PORT, reload=True)
