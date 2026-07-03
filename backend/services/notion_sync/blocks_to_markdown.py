"""Convert a tree of Notion blocks into markdown.

Attachments (image/pdf/file) are represented as placeholder tokens that a later
pass replaces with vision-extracted descriptions. This keeps this module pure
and unit-testable without network access.
"""

from __future__ import annotations


def blocks_to_markdown(blocks: list[dict]) -> str:
    """Render a list of Notion blocks (with pre-fetched `children`) as markdown."""
    lines = _render(blocks, depth=0)
    return "\n".join(lines).strip() + "\n"


def _render(blocks: list[dict], depth: int) -> list[str]:
    out: list[str] = []
    numbered_index = 0

    for block in blocks:
        btype = block.get("type", "")
        if btype != "numbered_list_item":
            numbered_index = 0
        rendered = _render_one(block, depth, numbered_index + 1)
        if btype == "numbered_list_item":
            numbered_index += 1
        if rendered is None:
            continue
        out.extend(rendered)
        if block.get("has_children"):
            out.extend(_render(block.get("children", []), depth + 1))

    return out


def _render_one(block: dict, depth: int, numbered_index: int) -> list[str] | None:
    btype = block.get("type", "")
    indent = "  " * depth

    if btype == "paragraph":
        text = _rich_text(block[btype])
        return [f"{indent}{text}", ""] if text else [""]

    if btype in ("heading_1", "heading_2", "heading_3"):
        level = int(btype[-1])
        return [f"{indent}{'#' * level} {_rich_text(block[btype])}", ""]

    if btype == "bulleted_list_item":
        return [f"{indent}- {_rich_text(block[btype])}"]

    if btype == "numbered_list_item":
        return [f"{indent}{numbered_index}. {_rich_text(block[btype])}"]

    if btype == "to_do":
        checked = block[btype].get("checked", False)
        marker = "[x]" if checked else "[ ]"
        return [f"{indent}- {marker} {_rich_text(block[btype])}"]

    if btype == "quote":
        return [f"{indent}> {_rich_text(block[btype])}", ""]

    if btype == "callout":
        icon = block[btype].get("icon", {}).get("emoji", "")
        prefix = f"{icon} " if icon else ""
        return [f"{indent}> {prefix}{_rich_text(block[btype])}", ""]

    if btype == "code":
        lang = block[btype].get("language", "")
        code = _rich_text(block[btype])
        return [f"{indent}```{lang}", code, f"{indent}```", ""]

    if btype == "divider":
        return [f"{indent}---", ""]

    if btype == "toggle":
        return [f"{indent}<details><summary>{_rich_text(block[btype])}</summary>", ""]

    if btype == "image":
        url = _file_url(block.get("image", {}))
        return [f"{indent}[[NOTION_IMAGE:{url}]]", ""]

    if btype == "pdf":
        url = _file_url(block.get("pdf", {}))
        return [f"{indent}[[NOTION_PDF:{url}]]", ""]

    if btype == "file":
        url = _file_url(block.get("file", {}))
        name = block.get("file", {}).get("name", "")
        return [f"{indent}[[NOTION_FILE:{name}|{url}]]", ""]

    if btype == "bookmark":
        url = block[btype].get("url", "")
        caption = _rich_text_field(block[btype].get("caption", []))
        label = caption or url
        return [f"{indent}[{label}]({url})", ""]

    return None


def _rich_text(block_body: dict) -> str:
    return _rich_text_field(block_body.get("rich_text", []))


def _rich_text_field(fragments: list[dict]) -> str:
    return "".join(f.get("plain_text", "") for f in fragments)


def _file_url(file_block: dict) -> str:
    ftype = file_block.get("type")
    if ftype == "external":
        return file_block.get("external", {}).get("url", "")
    if ftype == "file":
        return file_block.get("file", {}).get("url", "")
    return ""
