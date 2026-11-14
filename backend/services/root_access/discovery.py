"""Metadata-only agent discovery; provider access is deliberately absent."""

import re
import unicodedata

from services.root_access.store import PUBLIC_BINDING, AccessStore


def normalized(value):
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", str(value).casefold())
        if not unicodedata.combining(c)
    )


def discover_resources(sb, owner, root, query="", environment=None, account=None):
    if (
        not isinstance(query, str)
        or len(query) > 500
        or any(
            v is not None and (not isinstance(v, str) or len(v) > 120)
            for v in (environment, account)
        )
    ):
        raise ValueError("Invalid search filters")
    store = AccessStore(sb)
    store.root(owner, root)
    resources = (
        store.query(
            "access_resources",
            owner,
            root,
            "id,name,description,type,aliases,shared,account,region",
        )
        .order("name")
        .execute()
        .data
    )
    envs = store.query("root_environments", owner, root, "id,name,slug,sensitivity").execute().data
    bindings = (
        store.query("access_bindings", owner, root, PUBLIC_BINDING)
        .eq("enabled", True)
        .execute()
        .data
    )
    matching_envs = {
        e["id"]
        for e in envs
        if environment is None
        or normalized(environment) in {normalized(e["name"]), normalized(e["slug"])}
    }
    terms = set(re.findall(r"[\w-]+", normalized(query)))
    results = []
    for resource in resources:
        text = normalized(
            " ".join(
                [
                    resource["name"],
                    resource["description"],
                    " ".join(resource["aliases"]),
                    resource["account"],
                    resource["region"],
                ]
            )
        )
        if terms and not all(t in text for t in terms):
            continue
        if account is not None and normalized(resource["account"]) != normalized(account):
            continue
        available = [
            b
            for b in bindings
            if b["resource_id"] == resource["id"]
            and (environment is None or b["environment_id"] in matching_envs or resource["shared"])
        ]
        if available:
            results.append({**resource, "bindings": [store.public_binding(b) for b in available]})
    return {
        "root_id": str(root),
        "environments": envs,
        "resources": results,
        "requires_explicit_selection": len(results) > 1,
        "hint": (
            "Select exact binding IDs and revisions. Credentials are used only by the "
            "enrolled Kioku CLI; MCP never returns values."
        ),
    }


def environment_guide(sb, owner, root):
    store = AccessStore(sb)
    store.root(owner, root)
    rows = (
        store.query("root_access_guides", owner, root, "markdown,revision").limit(1).execute().data
    )
    return {"root_id": str(root), **(rows[0] if rows else {"markdown": "", "revision": 0})}
