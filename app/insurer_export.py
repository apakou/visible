import csv
import io
import json

from sqlalchemy.orm import Session

from app.models import Claim, InventoryDeclaration, Owner


def export_declarations_csv(db: Session, month: str = None) -> str:
    """Export all submitted declarations as CSV string."""
    query = db.query(InventoryDeclaration, Owner).join(Owner)
    if month:
        query = query.filter(InventoryDeclaration.declaration_month == month)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "policy_owner",
            "phone",
            "month",
            "total_value_ghs",
            "days_logged",
            "consistency_score",
            "submitted",
        ]
    )
    for decl, owner in query.all():
        writer.writerow(
            [
                owner.name,
                owner.phone_number,
                decl.declaration_month,
                decl.total_stock_value_ghs,
                decl.days_logged,
                decl.consistency_score,
                decl.submitted_to_insurer,
            ]
        )
    return output.getvalue()


def export_claims_json(db: Session) -> str:
    """Export all claims as JSON string."""
    claims = db.query(Claim).all()
    data = [
        {
            "claim_ref": c.claim_reference,
            "event": c.event_type,
            "event_date": str(c.event_date),
            "payout_ghs": (c.payout_pesewas or 0) / 100,
            "status": c.status,
        }
        for c in claims
    ]
    return json.dumps(data, indent=2)
