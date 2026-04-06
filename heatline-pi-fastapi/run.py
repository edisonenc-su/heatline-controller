import uvicorn

from app.config import settings


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.pi_api_host,
        port=settings.pi_api_port,
        reload=settings.pi_api_reload,
    )
