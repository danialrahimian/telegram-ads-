from fastapi import APIRouter

from app.api.v1.routes import accounts, ads, auth, bulk, content, system

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(system.router)
api_router.include_router(accounts.router)
api_router.include_router(ads.router)
api_router.include_router(content.router)
api_router.include_router(bulk.router)
