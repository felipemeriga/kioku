# Claude Tool Use API

Claude supports a tool use pattern that allows the model to request
structured information or trigger actions during a conversation. This is
distinct from function calling in some other APIs — Claude outputs a
structured tool call, the caller executes it, and the result is fed back to
Claude in a subsequent API call.

## Defining Tools

Tools are described in the `tools` parameter of the API request as a list of
JSON Schema objects:

```python
tools = [
    {
        "name": "search_knowledge_base",
        "description": "Search the document knowledge base for relevant passages.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query."
                }
            },
            "required": ["query"]
        }
    }
]
```

The `description` field is critical: Claude uses it to decide when and how
to call the tool. Well-written descriptions that explain what the tool does,
when to use it, and what it returns lead to significantly better tool
selection behavior.

## The Tool Use Flow

1. Caller sends a message with `tools` defined.
2. Claude responds with a `tool_use` content block when it wants to invoke a tool.
3. Caller executes the tool and sends the result back in a `tool_result`
   content block on behalf of the `user` role.
4. Claude continues generating, incorporating the tool result.

Multiple tools can be requested in a single response (parallel tool use).
When this happens, the caller should execute all requested tools and return
all results before continuing.

## Forcing Tool Use

The `tool_choice` parameter controls tool invocation behavior:
- `{"type": "auto"}` — Claude decides whether to call a tool (default).
- `{"type": "any"}` — Claude must call at least one tool.
- `{"type": "tool", "name": "..."}` — Claude must call the named tool.

Forcing a specific tool is useful for structured extraction tasks where you
want Claude to always return a typed schema rather than prose.

## Handling tool_use in the Response

A response with tool use has `stop_reason: "tool_use"`. The `content` array
contains one or more `tool_use` blocks alongside any `text` blocks Claude
generated before deciding to call the tool.

```python
for block in response.content:
    if block.type == "tool_use":
        result = execute_tool(block.name, block.input)
        tool_results.append({
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": result
        })
```

## Best Practices

- **One tool per task** — giving Claude a large tool set increases the chance
  of mis-selection. Define only the tools needed for the current task.
- **Return structured content** — tool results that are valid JSON are easier
  for Claude to parse than prose.
- **Set token budgets** — long tool results can push other context out. Trim
  tool outputs before returning them to the model.
