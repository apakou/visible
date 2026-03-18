import os
import logging

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.database import get_db, init_db_if_sqlite
from app.insurer_export import export_claims_json, export_declarations_csv
from app.scheduler import start_scheduler
from app.webhook import router as webhook_router

logger = logging.getLogger(__name__)

app = FastAPI(title="Visbl MVP v2", version="2.0.0")

app.include_router(webhook_router)


@app.on_event("startup")
async def on_startup():
    init_db_if_sqlite()
    logger.info("Starting scheduler on application startup")
    start_scheduler()


@app.get("/health")
async def health():
    logger.debug("Health check requested")
    return {"status": "ok", "version": "2.0.0"}


# ── Admin: export inventory declarations as CSV for insurer ──
# Protected by a simple API key header (set EXPORT_API_KEY in .env)
@app.get("/export/declarations", response_class=PlainTextResponse)
async def export_declarations(
    month: str = None, x_api_key: str = Header(None), db: Session = Depends(get_db)
):
    if x_api_key != os.getenv("EXPORT_API_KEY"):
        logger.warning("Forbidden declarations export attempt with invalid API key")
        raise HTTPException(status_code=403, detail="Forbidden")
    logger.info("Exporting declarations", extra={"month": month})
    return export_declarations_csv(db, month)


# ── Admin: export all claims as JSON for insurer ──
@app.get("/export/claims", response_class=PlainTextResponse)
async def export_claims(x_api_key: str = Header(None), db: Session = Depends(get_db)):
    if x_api_key != os.getenv("EXPORT_API_KEY"):
        logger.warning("Forbidden claims export attempt with invalid API key")
        raise HTTPException(status_code=403, detail="Forbidden")
    logger.info("Exporting claims")
    return export_claims_json(db)


# ── Admin: fetch a single owner's policy status (internal use) ──
@app.get("/owners/{phone}/policy")
async def get_owner_policy(
    phone: str, x_api_key: str = Header(None), db: Session = Depends(get_db)
):
    from app.models import Owner, Policy

    if x_api_key != os.getenv("EXPORT_API_KEY"):
        logger.warning(
            "Forbidden owner policy lookup with invalid API key", extra={"phone": phone}
        )
        raise HTTPException(status_code=403, detail="Forbidden")
    owner = db.query(Owner).filter(Owner.phone_number == phone).first()
    if not owner:
        logger.info("Owner not found for policy lookup", extra={"phone": phone})
        raise HTTPException(status_code=404, detail="Owner not found")
    policy = (
        db.query(Policy)
        .filter(Policy.owner_id == owner.id, Policy.status == "active")
        .first()
    )
    if not policy:
        logger.info(
            "No active policy found for owner", extra={"phone": phone, "owner_id": owner.id}
        )
        return {"owner": owner.name, "policy": None}
    return {
        "owner": owner.name,
        "policy_number": policy.policy_number,
        "status": policy.status,
        "premium_ghs": policy.premium_pesewas / 100,
        "payout_cap_ghs": policy.payout_cap_pesewas / 100,
        "cover_end": str(policy.cover_end_date),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
