from fastapi import Depends, FastAPI, Header, HTTPException

from app.config import settings

app = FastAPI(title="kioku mem0 service")


def require_token(authorization: str = Header(default="")):
    if authorization != f"Bearer {settings.service_token}":
        raise HTTPException(status_code=401, detail="bad token")


@app.get("/health")
def health(_=Depends(require_token)):
    return {"ok": True}
