"""Ensure the folder chain <root>/notion/<page ancestors>/ exists in Supabase.

Idempotent: reuses existing folders by (parent_id, name); creates the rest.
Returns the leaf folder id (where the page's chunks live) and a human-readable
parent path for contextual headers.
"""

from __future__ import annotations


def ensure_notion_folder_path(
    supabase,
    *,
    user_id: str,
    root_folder_id: str,
    ancestor_titles: list[str],
) -> tuple[str, str]:
    """
    ancestor_titles: page titles in order from the mapped Notion root's direct
    children down to (but excluding) the page being ingested. The page's own
    title is NOT included — documents themselves carry the page title elsewhere.
    """
    parent_id = _get_or_create_folder(
        supabase, user_id=user_id, name="notion", parent_id=root_folder_id
    )
    for title in ancestor_titles:
        parent_id = _get_or_create_folder(
            supabase, user_id=user_id, name=title, parent_id=parent_id
        )
    parent_path = " / ".join(ancestor_titles)
    return parent_id, parent_path


def _get_or_create_folder(supabase, *, user_id: str, name: str, parent_id: str) -> str:
    existing = (
        supabase.table("folders").select("id").eq("parent_id", parent_id).eq("name", name).execute()
    )
    rows = existing.data or []
    if rows:
        return rows[0]["id"]

    inserted = (
        supabase.table("folders")
        .insert({"user_id": user_id, "name": name, "parent_id": parent_id})
        .execute()
    )
    return inserted.data[0]["id"]
