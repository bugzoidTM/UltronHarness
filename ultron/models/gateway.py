"""Gateway model-agnostic: provedores locais trocáveis sem dependência no núcleo cognitivo."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from ultron.configuration import Settings

T = TypeVar("T", bound=BaseModel)


@dataclass(slots=True)
class Usage:
    prompt_tokens: int = 0
    output_tokens: int = 0


@dataclass(slots=True)
class ModelResponse:
    content: str
    tool_calls: list[dict[str, Any]]
    usage: Usage
    latency_ms: int
    model: str
    finish_reason: str
    local: bool


class LLMProvider(Protocol):
    async def generate(self, messages: list[dict[str, str]], **kwargs: Any) -> ModelResponse: ...
    async def health(self) -> dict[str, Any]: ...


class OpenAICompatibleProvider:
    def __init__(self, endpoint: str, model: str, timeout: int = 120):
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.timeout = timeout

    async def generate(self, messages: list[dict[str, str]], **kwargs: Any) -> ModelResponse:
        started = perf_counter()
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.2),
        }
        if kwargs.get("json_schema"):
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "structured_response", "strict": True, "schema": kwargs["json_schema"]},
            }
        elif kwargs.get("json_mode"):
            payload["response_format"] = {"type": "json_object"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.endpoint}/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()
        choice = data["choices"][0]
        usage = data.get("usage", {})
        return ModelResponse(
            content=choice.get("message", {}).get("content", ""),
            tool_calls=choice.get("message", {}).get("tool_calls", []),
            usage=Usage(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)),
            latency_ms=int((perf_counter() - started) * 1000),
            model=data.get("model", self.model),
            finish_reason=choice.get("finish_reason", "stop"),
            local=True,
        )

    async def health(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                response = await client.get(f"{self.endpoint}/models")
                response.raise_for_status()
            return {
                "available": True,
                "provider": "openai-compatible",
                "model": self.model,
                "local": True,
            }
        except httpx.HTTPError as exc:
            return {
                "available": False,
                "provider": "openai-compatible",
                "model": self.model,
                "local": True,
                "detail": str(exc),
            }


class OllamaProvider:
    def __init__(self, endpoint: str, model: str, timeout: int = 120):
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.timeout = timeout

    async def generate(self, messages: list[dict[str, str]], **kwargs: Any) -> ModelResponse:
        started = perf_counter()
        options = {"temperature": kwargs.get("temperature", 0.2)}
        if kwargs.get("max_tokens") is not None:
            options["num_predict"] = int(kwargs["max_tokens"])
        if kwargs.get("seed") is not None:
            options["seed"] = int(kwargs["seed"])
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": options,
        }
        if kwargs.get("json_schema"):
            payload["format"] = kwargs["json_schema"]
        elif kwargs.get("json_mode"):
            payload["format"] = "json"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.endpoint}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
        return ModelResponse(
            content=data.get("message", {}).get("content", ""),
            tool_calls=data.get("message", {}).get("tool_calls", []),
            usage=Usage(data.get("prompt_eval_count", 0), data.get("eval_count", 0)),
            latency_ms=int((perf_counter() - started) * 1000),
            model=data.get("model", self.model),
            finish_reason=data.get("done_reason", "stop"),
            local=True,
        )

    async def health(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                response = await client.get(f"{self.endpoint}/api/tags")
                response.raise_for_status()
                models = [item.get("name") for item in response.json().get("models", [])]
            return {
                "available": self.model in models,
                "provider": "ollama",
                "model": self.model,
                "models": models,
                "local": True,
            }
        except httpx.HTTPError as exc:
            return {
                "available": False,
                "provider": "ollama",
                "model": self.model,
                "local": True,
                "detail": str(exc),
            }


class FallbackProvider:
    """Modo offline de contingência; não finge ser LLM e mantém o plano de controle testável."""

    model = "local-fallback"

    async def generate(self, messages: list[dict[str, str]], **kwargs: Any) -> ModelResponse:
        message = messages[-1]["content"] if messages else ""
        content = (
            "O runtime LLM local ainda não está ativo. O UltronPro permanece operacional em modo "
            "determinístico; configure Ollama ou llama.cpp para cognição generativa local.\n\n"
            f"Entrada recebida: {message[:1000]}"
        )
        return ModelResponse(content, [], Usage(), 0, self.model, "fallback", True)

    async def health(self) -> dict[str, Any]:
        return {
            "available": True,
            "provider": "fallback",
            "model": self.model,
            "local": True,
            "generative": False,
        }


class ModelGateway:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.registry = settings.raw["models"]["registry"]
        self.primary_name = settings.raw["models"]["primary"]

    def configured_models(self) -> list[dict[str, Any]]:
        result = []
        for name, config in self.registry.items():
            result.append({"name": name, **config, "primary": name == self.primary_name})
        return result

    def provider(self, name: str | None = None) -> LLMProvider:
        selected = name or self.primary_name
        config = self.registry.get(selected)
        if not config:
            raise ValueError(f"Modelo não registrado: {selected}")
        provider = config.get("provider")
        if provider == "ollama":
            return OllamaProvider(
                config["endpoint"], config["model"], self.settings.raw["models"]["timeout_seconds"]
            )
        if provider == "llamacpp":
            return OpenAICompatibleProvider(
                config["endpoint"], config["model"], self.settings.raw["models"]["timeout_seconds"]
            )
        return FallbackProvider()

    async def generate(
        self, messages: list[dict[str, str]], model_name: str | None = None, **kwargs: Any
    ) -> ModelResponse:
        return await self.provider(model_name).generate(messages, **kwargs)

    async def structured(
        self,
        schema: type[T],
        messages: list[dict[str, str]],
        model_name: str | None = None,
        *,
        on_response: Callable[[ModelResponse, bool], Awaitable[None]] | None = None,
        on_decision: Callable[[bool, bool, int, str | None], Awaitable[None]] | None = None,
        repair_attempts: int | None = None,
        **kwargs: Any,
    ) -> T:
        attempts = 2 if repair_attempts is None else max(0, int(repair_attempts))
        schema_json = schema.model_json_schema()
        current_messages = list(messages)
        response: ModelResponse | None = None
        validation_error: ValidationError | ValueError | None = None
        for attempt in range(attempts + 1):
            response = await self.generate(
                current_messages,
                model_name,
                json_mode=True,
                json_schema=schema_json,
                **kwargs,
            )
            if on_response:
                await on_response(response, attempt > 0)
            try:
                parsed = schema.model_validate_json(response.content)
                if on_decision:
                    await on_decision(attempt == 0, True, attempt, None)
                return parsed
            except (ValidationError, ValueError) as exc:
                validation_error = exc
                if attempt >= attempts:
                    if on_decision:
                        await on_decision(False, False, attempt, type(exc).__name__)
                    raise
                error_summary = self._validation_summary(exc)
                compact_schema = json.dumps(schema_json, ensure_ascii=False, separators=(",", ":"))[:4000]
                current_messages = [
                    *messages,
                    {"role": "assistant", "content": response.content[:6000]},
                    {
                        "role": "user",
                        "content": (
                            "A resposta anterior não validou. Retorne somente JSON válido para o schema solicitado. "
                            f"Resumo do erro: {error_summary}. Schema compacto: {compact_schema}"
                        ),
                    },
                ]
        if validation_error is not None:
            raise validation_error
        raise RuntimeError("Structured output não produziu resposta.")

    @staticmethod
    def _validation_summary(error: ValidationError | ValueError) -> str:
        if isinstance(error, ValidationError):
            issues = [f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in error.errors()[:5]]
            return "; ".join(issues)[:1200]
        return str(error)[:1200]

    async def health(self, name: str | None = None) -> dict[str, Any]:
        if name:
            return await self.provider(name).health()
        results = {
            model["name"]: await self.provider(model["name"]).health()
            for model in self.configured_models()
        }
        return results
