"""Pure diff logic — decides added / removed / modified between two doc manifests.

A manifest is a list of {filename, hash} dicts. Manifests come from:
- current: the docs presently in the folder subtree
- previous: what included_hashes was set to on the last summary
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Diff:
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.modified)

    @property
    def count(self) -> int:
        return len(self.added) + len(self.removed) + len(self.modified)


def compute_diff(current: list[dict], previous: list[dict] | None) -> Diff:
    if previous is None:
        return Diff(added=sorted(d["filename"] for d in current))

    prev_by_name: dict[str, str] = {d["filename"]: d.get("hash", "") for d in previous}
    curr_by_name: dict[str, str] = {d["filename"]: d.get("hash", "") for d in current}

    added, removed, modified = [], [], []
    for name, h in curr_by_name.items():
        if name not in prev_by_name:
            added.append(name)
        elif prev_by_name[name] != h:
            modified.append(name)
    for name in prev_by_name:
        if name not in curr_by_name:
            removed.append(name)

    return Diff(added=sorted(added), removed=sorted(removed), modified=sorted(modified))
