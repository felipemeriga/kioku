"""Resume one provider deletion per request; retain metadata until all values are gone."""

from fastapi.responses import JSONResponse

from services.root_access.provider import InfisicalProvider, ProviderUnavailable
from services.root_access.store import fail


def delete_resource_step(store, owner, root, resource):
    store.root(owner, root)
    store.one("access_resources", owner, root, resource)
    params = {"p_owner": owner, "p_root": str(root), "p_resource": str(resource)}
    try:
        refs = store.sb.rpc("begin_access_resource_deletion", params).execute().data
    except Exception as exc:
        if "resource_busy" in str(getattr(exc, "message", "")):
            fail("resource_busy", 409)
        fail("binding_changed", 409)
    if refs:
        try:
            InfisicalProvider().delete(refs[0])
        except ProviderUnavailable:
            fail("provider_unavailable", 503)
        try:
            remaining = (
                store.sb.rpc("ack_access_resource_deletion", {**params, "p_ref": refs[0]})
                .execute()
                .data
            )
        except Exception:
            fail("resource_deleting", 409)
        if remaining:
            return JSONResponse(status_code=202, content={"deleted": False, "remaining": remaining})
    try:
        store.sb.rpc("finish_access_resource_deletion", params).execute()
    except Exception:
        fail("resource_deleting", 409)
    return {"deleted": True}
