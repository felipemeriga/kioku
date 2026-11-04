"""Lossless transport wrapper for native StructuredOutput tool input schemas."""

from copy import deepcopy


def native_schema(schema):
    """Tool schemas require an object root without top-level composition keywords.

    Keep the caller's entire schema under `result`, relocating document-local JSON
    pointers. `$id` subresources keep their own local reference scope unchanged.
    The caller's original schema is always validated again after exact unwrapping.
    """

    def relocate(value, resource=False):
        if isinstance(value, list):
            return [relocate(item, resource) for item in value]
        if not isinstance(value, dict):
            return deepcopy(value)
        resource = resource or "$id" in value
        result = {}
        for key, item in value.items():
            if (
                not resource
                and key in {"$ref", "$dynamicRef"}
                and isinstance(item, str)
                and (item == "#" or item.startswith("#/"))
            ):
                result[key] = "#/properties/result" + item[1:]
            else:
                result[key] = relocate(item, resource)
        return result

    return {
        "type": "object",
        "properties": {"result": relocate(schema)},
        "required": ["result"],
        "additionalProperties": False,
    }


def unwrap_native_output(value):
    if not isinstance(value, dict) or set(value) != {"result"}:
        raise ValueError("native structured output must contain exactly the result wrapper")
    return value["result"]
