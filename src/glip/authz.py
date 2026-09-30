from __future__ import annotations

from fastapi import HTTPException

from .auth import Principal


PROJECT_CAPABILITIES = frozenset({
    "project.create",
    "project.update",
    "project.archive",
    "project.restore",
})

ACCESS_CAPABILITIES = frozenset({
    "membership.list",
    "membership.invite",
    "invitation.list",
    "invitation.rotate",
    "invitation.reissue",
    "invitation.revoke",
})

ROLE_CAPABILITIES: dict[str, frozenset[str]] = {
    "owner": PROJECT_CAPABILITIES | ACCESS_CAPABILITIES,
    "admin": PROJECT_CAPABILITIES | ACCESS_CAPABILITIES,
    "architect": frozenset({"project.create", "project.update"}),
    "member": frozenset({"project.create", "project.update"}),
}


def capabilities_for(role: str | None) -> list[str]:
    return sorted(
        ROLE_CAPABILITIES.get(
            str(role or "").strip().lower(),
            frozenset(),
        )
    )


def require_capability(principal: Principal, capability: str) -> None:
    allowed = ROLE_CAPABILITIES.get(
        str(principal.role or "").strip().lower(),
        frozenset(),
    )
    if capability not in allowed:
        raise HTTPException(status_code=403, detail="capability_required")
