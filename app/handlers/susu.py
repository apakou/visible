import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import InventoryLog, Owner, SusuGroup, SusuMember
from app.twilio_client import send_whatsapp


def create_group(
    leader: Owner, group_name: str, market_location: str, db: Session
) -> SusuGroup:
    """Called during leader onboarding. Creates the SUSU group and returns a join code."""
    group = SusuGroup(
        group_name=group_name,
        leader_phone=leader.phone_number,
        market_location=market_location,
    )
    db.add(group)
    db.commit()
    db.refresh(group)

    # Generate a short human-readable group code based on the group id
    group_code = f"VISBL-{group.id:04d}"

    send_whatsapp(
        leader.phone_number,
        f"SUSU group created ✓\n"
        f"Group name: {group_name}\n"
        f"Market: {market_location}\n"
        f"Share this code with your members: {group_code}\n"
        f"They enter it during Visbl registration.",
    )
    return group


def enroll_member(member: Owner, group_code: str, db: Session) -> bool:
    """Called during member onboarding when they enter a SUSU group code.
    group_code format: VISBL-0001
    Returns True if enrolled, False if code not found.
    """
    try:
        group_id = int(group_code.split("-")[1])
    except (IndexError, ValueError):
        return False

    group = db.query(SusuGroup).filter(SusuGroup.id == group_id).first()
    if not group:
        return False

    # Avoid duplicate enrollment
    existing = (
        db.query(SusuMember)
        .filter(
            SusuMember.group_id == group.id,
            SusuMember.owner_id == member.id,
        )
        .first()
    )
    if existing:
        return True  # Already enrolled

    membership = SusuMember(group_id=group.id, owner_id=member.id)
    db.add(membership)
    group.member_count = (group.member_count or 0) + 1
    db.commit()

    # Notify the group leader
    send_whatsapp(
        group.leader_phone,
        f"New member joined your SUSU group ✓\n"
        f"{member.name or member.phone_number} has enrolled in {group.group_name}.\n"
        f"Group now has {group.member_count} member(s).",
    )
    return True


async def handle_group_status(
    leader: Owner, parsed: dict, raw_message: str, db: Session
):
    """Leader sends 'group status' — returns member count, active policies, lagging loggers."""
    phone = leader.phone_number

    group = db.query(SusuGroup).filter(SusuGroup.leader_phone == phone).first()
    if not group:
        send_whatsapp(
            phone,
            "You are not registered as a SUSU group leader. Contact Visbl to set up your group.",
        )
        return {"status": "not_a_leader"}

    members = (
        db.query(SusuMember)
        .filter(
            SusuMember.group_id == group.id,
            SusuMember.status == "active",
        )
        .all()
    )

    # Flag members who have not logged in the last 3 days
    cutoff = datetime.utcnow() - timedelta(days=3)
    lagging = []
    for m in members:
        recent = (
            db.query(InventoryLog)
            .filter(
                InventoryLog.owner_id == m.owner_id,
                InventoryLog.logged_at >= cutoff,
            )
            .first()
        )
        if not recent:
            owner = db.query(Owner).filter(Owner.id == m.owner_id).first()
            lagging.append(owner.name or owner.phone_number)

    lag_text = (
        ("\nNeeds a reminder:\n" + "\n".join(f"  - {n}" for n in lagging))
        if lagging
        else "\nAll members logged recently ✅"
    )

    send_whatsapp(
        phone,
        f"SUSU Group: {group.group_name}\n"
        f"Market: {group.market_location}\n"
        f"Active members: {len(members)}\n"
        f"{lag_text}",
    )
    return {
        "status": "group_status_sent",
        "member_count": len(members),
        "lagging": len(lagging),
    }
