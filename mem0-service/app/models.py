from pydantic import BaseModel


class AddReq(BaseModel):
    user_id: str
    folder_id: str
    content: str
    scope: str = "episodic"
    category: str = "note"
    tags: list[str] | None = None
    written_by: str | None = None


class SearchReq(BaseModel):
    user_id: str
    folder_id: str
    query: str
    scope: str | None = None
    limit: int | None = None


class ListReq(BaseModel):
    user_id: str
    folder_id: str
    scope: str | None = None
    limit: int | None = None
