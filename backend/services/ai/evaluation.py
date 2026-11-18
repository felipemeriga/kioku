"""RAGAS judge backed by owner-scoped subscription completions."""

import asyncio

from langchain_core.outputs import Generation, LLMResult
from ragas.llms.base import BaseRagasLLM

from services.ai.scope import ExecutionScope, execution_scope
from services.llm import Task, complete


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
        generations = []
        with execution_scope(self.scope):
            for _ in range(n):
                response = complete(
                    task=Task.EVAL_JUDGE,
                    messages=[{"role": "user", "content": prompt.to_string()}],
                    max_tokens=2048,
                )
                text = "".join(block.text for block in response.content)
                generations.append(Generation(text=text))
        return LLMResult(generations=[generations])

    async def agenerate_text(self, prompt, n=1, temperature=None, stop=None, callbacks=None):
        return await asyncio.to_thread(self.generate_text, prompt, n, temperature, stop, callbacks)
