"""RAGAS judge backed by owner-scoped subscription completions."""

import asyncio
import json
import re

from langchain_core.outputs import Generation, LLMResult
from ragas.llms.base import BaseRagasLLM
from ragas.metrics._answer_relevance import ResponseRelevanceOutput
from ragas.metrics._context_precision import Verification
from ragas.metrics._context_recall import ContextRecallClassifications
from ragas.metrics._faithfulness import (
    NLIStatementInput,
    NLIStatementOutput,
    StatementGeneratorOutput,
)

from services.ai.client import ExecutionError
from services.ai.facade import native_completion
from services.ai.scope import ExecutionScope, execution_scope
from services.llm import MODEL_FOR_TASK, Task

_NLI_BATCH_SIZE = 8
_SCHEMA_MARKER = "following schema as specified in JSON Schema:\n"
_JSON_STRING = re.compile(r'"(?:[^"\\]|\\.)*"')
_DELIMITER_ESCAPES = str.maketrans({char: f"\\u{ord(char):04x}" for char in "{}[]"})


def _closed_judge_schema(schema: dict) -> dict:
    definitions = schema.get("$defs", {})

    def close(node: dict) -> dict:
        if "$ref" in node:
            return close(definitions[node["$ref"].removeprefix("#/$defs/")])
        result = {key: value for key, value in node.items() if key != "$defs"}
        if "properties" in node:
            result["properties"] = {
                name: close(field) for name, field in node["properties"].items()
            }
            result["additionalProperties"] = False
        if "items" in node:
            result["items"] = close(node["items"])
        return result

    return close(schema)


_RAGAS_SCHEMAS = {}
for output_model in (
    StatementGeneratorOutput,
    NLIStatementOutput,
    ResponseRelevanceOutput,
    Verification,
    ContextRecallClassifications,
):
    signature = output_model.model_json_schema()
    _RAGAS_SCHEMAS[signature["title"]] = (signature, _closed_judge_schema(signature))


def _judge_schema(prompt: str) -> dict:
    # Read only the metric's signature before examples or retrieved text. Match
    # the installed RAGAS model rather than permitting a prompt-defined schema.
    header, marker, signature = prompt.partition(_SCHEMA_MARKER)
    if marker and "\nNow perform the same with the following input" not in header:
        try:
            declared, _ = json.JSONDecoder().raw_decode(signature)
            expected, native = _RAGAS_SCHEMAS[declared["title"]]
        except (ValueError, KeyError, TypeError):
            pass
        else:
            if declared == expected:
                return native
    raise ExecutionError("unsupported_ragas_judge_schema")


def _ragas_json(typed_json: str) -> str:
    # RAGAS's extractor counts brackets even inside JSON strings. Escape
    # string delimiters without changing any decoded model values.
    return _JSON_STRING.sub(lambda match: match[0].translate(_DELIMITER_ESCAPES), typed_json)


def _native_json(content: str, schema: dict, *, ordered_statements: bool = False) -> str:
    system = "Return the requested JSON object directly in data.value."
    if ordered_statements:
        system += " Copy each input statement verbatim and keep its input order."
    response = native_completion(
        operation=Task.EVAL_JUDGE.value,
        model=MODEL_FOR_TASK[Task.EVAL_JUDGE],
        messages=[{"role": "user", "content": content}],
        system=system,
        max_tokens=2048,
        tools=None,
        judge_schema=schema,
    )
    return "".join(block.text for block in response.content)


def _judge_statements(content: str, schema: dict) -> str:
    # RAGAS expects exactly one verdict for each claim from its statement
    # generator. Large single-shot verdict lists can exceed the native output
    # ceiling. Keep the full evidence in each request and every verdict in order.
    header, separator, payload = content.rpartition("\ninput: ")
    suffix = "\nOutput: "
    if not separator or not payload.endswith(suffix):
        raise ExecutionError("invalid_ragas_nli_input")
    try:
        data = NLIStatementInput.model_validate_json(payload.removesuffix(suffix))
    except ValueError:
        raise ExecutionError("invalid_ragas_nli_input") from None
    if not data.statements:
        raise ExecutionError("invalid_ragas_nli_input")

    verdicts = []
    for offset in range(0, len(data.statements), _NLI_BATCH_SIZE):
        statements = data.statements[offset : offset + _NLI_BATCH_SIZE]
        batch = data.model_copy(update={"statements": statements})
        array = {**schema["properties"]["statements"], "minItems": len(statements)}
        array["maxItems"] = len(statements)
        batch_schema = {**schema, "properties": {"statements": array}}
        prompt = header + separator + batch.model_dump_json(indent=4) + suffix
        output = _native_json(prompt, batch_schema, ordered_statements=True)
        result = NLIStatementOutput.model_validate_json(output)
        if [item.statement for item in result.statements] != statements:
            raise ExecutionError("incomplete_ragas_nli_verdicts")
        verdicts.extend(result.statements)
    return NLIStatementOutput(statements=verdicts).model_dump_json()


class SubscriptionJudge(BaseRagasLLM):
    def __init__(self, scope: ExecutionScope):
        super().__init__()
        if not scope.owner_id:
            raise PermissionError("Evaluation requires authenticated owner scope")
        self.scope = scope

    def is_finished(self, response):
        return bool(response.generations) and all(
            generation.text.strip() for group in response.generations for generation in group
        )

    def generate_text(self, prompt, n=1, temperature=None, stop=None, callbacks=None):
        if not 1 <= n <= 4:
            raise ValueError("Evaluation supports one to four bounded completions")
        content = prompt.to_string()
        schema = _judge_schema(content)
        generations = []
        with execution_scope(self.scope):
            for _ in range(n):
                if schema["title"] == "NLIStatementOutput":
                    text = _judge_statements(content, schema)
                else:
                    text = _native_json(content, schema)
                generations.append(Generation(text=_ragas_json(text)))
        return LLMResult(generations=[generations])

    async def agenerate_text(self, prompt, n=1, temperature=None, stop=None, callbacks=None):
        return await asyncio.to_thread(self.generate_text, prompt, n, temperature, stop, callbacks)
