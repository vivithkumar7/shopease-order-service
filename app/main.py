from fastapi import FastAPI, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.database.connection import engine
from app.routers.order_item_routes import router as order_item_router
from app.routers.order_routes import router as order_router

app = FastAPI(
    title="ShopEase Order Management Service",
    description="Independent Order Management Microservice",
    version="1.0.0"
)
app.include_router(order_router)
app.include_router(order_item_router)


@app.get("/")
def home():
    return {
        "message": "Welcome to ShopEase Order Management Service",
        "status": "running",
        "service": "Order Management Service"
    }

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "shopease-Order-Service"
    }


@app.get("/health/ready")
def readiness_check():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable",
        ) from exc
    return {"status": "ready", "service": "shopease-order-service"}