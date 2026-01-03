"""
GEMP Game Analytics API

FastAPI service for querying card performance statistics.
"""

import logging
import os
from pathlib import Path
from contextlib import contextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import mysql.connector
from mysql.connector import pooling

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/app/logs/api.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Database connection pool
_db_pool = None


def get_db_pool():
    """Get or create database connection pool."""
    global _db_pool
    if _db_pool is None:
        _db_pool = pooling.MySQLConnectionPool(
            pool_name="analytics_pool",
            pool_size=5,
            host=os.environ.get('GEMP_DB_HOST', 'localhost'),
            port=int(os.environ.get('GEMP_DB_PORT', 3306)),
            user=os.environ.get('GEMP_DB_USER', 'gemp'),
            password=os.environ.get('GEMP_DB_PASSWORD', ''),
            database=os.environ.get('GEMP_DB_NAME', 'gemp_db'),
        )
    return _db_pool


def get_db_connection():
    """Get a connection from the pool."""
    return get_db_pool().get_connection()


def get_db_cursor():
    """Get a cursor (for use as FastAPI dependency)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        yield cursor
    finally:
        cursor.close()
        conn.close()


# Create FastAPI app
app = FastAPI(
    title="GEMP Analytics API",
    description="Card performance statistics for Lord of the Rings TCG balance analysis",
    version="1.0.0",
)

# CORS middleware - allow GEMP frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://localhost:8001",
        "https://play.lotrtcgpc.net",
        "https://gemp.lotrtcgpc.net",
        "https://test.lotrtcgpc.net",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health check
@app.get("/health")
def health_check():
    """Health check endpoint."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        cursor.close()
        conn.close()
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {"status": "unhealthy", "database": str(e)}


# Import and register routers
from .routes import cards_router, patches_router, admin_router

app.include_router(cards_router, prefix="/api")
app.include_router(patches_router, prefix="/api")
app.include_router(admin_router, prefix="/api")


# Static files - serve dashboard
static_dir = Path(__file__).parent.parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# Root serves dashboard
@app.get("/")
def root():
    """Serve the analytics dashboard."""
    index_path = static_dir / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"message": "GEMP Analytics API", "docs": "/docs"}


# Admin page
@app.get("/admin")
def admin_page():
    """Serve the admin page."""
    admin_path = static_dir / "admin.html"
    if admin_path.exists():
        return FileResponse(admin_path)
    return {"message": "Admin page not found", "docs": "/docs"}
