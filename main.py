import os

from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware

app = FastAPI()

# Configure allowed hosts from environment variable
# Default to localhost for local development
# Railway health-check host is added via ALLOWED_HOSTS env var at deploy time
allowed_hosts_str = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1")
allowed_hosts = [host.strip() for host in allowed_hosts_str.split(",")]

app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)


@app.get("/health")
def health():
    return {"status": "ok"}
