import os

from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware

app = FastAPI()

# Configure allowed hosts from environment variable
# Default includes localhost (dev) and Railway's healthcheck host
# Additional hosts (e.g. custom domains) can be added via ALLOWED_HOSTS env var
allowed_hosts_str = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,healthcheck.railway.app")
allowed_hosts = [host.strip() for host in allowed_hosts_str.split(",")]

app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)


@app.get("/health")
def health():
    return {"status": "ok"}
