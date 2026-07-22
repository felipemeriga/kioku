"""Scope resolution utilities."""

from fastapi import HTTPException

from db.client import get_supabase_thread_safe as get_supabase


def resolve_root_folder_id(folder_id: str, user_id: str) -> str:
    """Walk up the folder tree to find the root folder ID.

    Args:
        folder_id: Any folder ID in the tree.
        user_id: The user who owns the folder.

    Returns:
        The root folder ID (where parent_id IS NULL).

    Raises:
        HTTPException: If folder not found or max depth exceeded.
    """
    sb = get_supabase()
    current_id = folder_id
    max_depth = 10

    for _ in range(max_depth):
        result = (
            sb.table("folders")
            .select("id, parent_id")
            .eq("id", current_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Folder not found")

        parent_id = result.data[0]["parent_id"]
        if parent_id is None:
            return result.data[0]["id"]
        current_id = parent_id

    raise HTTPException(status_code=400, detail="Folder tree too deep")


def validate_scope_folder(scope_folder_id: str, user_id: str) -> None:
    """Validate that a folder ID belongs to the user. Root or sub-folder both OK.

    Sub-folder scoping is what lets Mem0 + GitHub integrations bind to
    subprojects like 'personal/agentic-rag' — matches the relaxed validation
    already applied to Mem0/GitHub configs.

    Raises HTTPException if folder is missing or not owned by the user.
    """
    sb = get_supabase()
    result = (
        sb.table("folders")
        .select("id")
        .eq("id", scope_folder_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Scope folder not found")
