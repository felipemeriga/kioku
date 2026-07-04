"""Folder-summary service: nightly, incremental, hierarchical orientation docs.

Public entry points:
- generate_folder_summary(...): one-shot summarizer for a single folder (auto/full/delta)
- list_folder_ids_with_docs(...): used by the nightly cron to enumerate work
"""

from .builder import generate_folder_summary
from .repo import list_folder_ids_with_docs
from .schema import FolderSummary

__all__ = ["FolderSummary", "generate_folder_summary", "list_folder_ids_with_docs"]
