from __future__ import annotations

import json
import os
from typing import Any

import httpx


class ChatProviderError(RuntimeError):
    pass


def chat_status() -> dict[str, Any]:
    mode = os.getenv("GLIP_CHAT_MODE", "disabled").strip().lower()
    model = os.getenv("GLIP_CHAT_MODEL", "gpt-5.6-luna").strip()
    configured = bool(os.getenv("GLIP_OPENAI_API_KEY", "").strip()) if mode == "openai" else mode == "mock"
    return {
        "mode": mode,
        "configured": configured,
        "model": model if mode == "openai" else None,
    }


def _extract_output_text(payload: dict[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    parts: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                parts.append(content["text"])
    text = "\n".join(x.strip() for x in parts if x.strip()).strip()
    if not text:
        raise ChatProviderError("chat_provider_empty_response")
    return text


def generate_reply(
    *,
    messages: list[dict[str, str]],
    project_context: dict[str, Any] | None,
    request_id: str,
    correlation_id: str,
) -> tuple[str, str, str]:
    mode = os.getenv("GLIP_CHAT_MODE", "disabled").strip().lower()
    environment = os.getenv("GLIP_ENVIRONMENT", "development").strip().lower()

    if mode == "mock":
        if environment not in {"development", "test"}:
            raise ChatProviderError("chat_mock_forbidden_outside_dev")
        last = messages[-1]["content"] if messages else ""
        return f"GLIP Intelligence (mock): {last}", "mock", "mock"

    if mode != "openai":
        raise ChatProviderError("chat_provider_disabled")

    api_key = os.getenv("GLIP_OPENAI_API_KEY", "").strip()
    if not api_key:
        raise ChatProviderError("chat_provider_not_configured")

    model = os.getenv("GLIP_CHAT_MODEL", "gpt-5.6-luna").strip() or "gpt-5.6-luna"

    context_json = json.dumps(
        project_context or {"scope": "tenant_general", "constraints": ["no_external_write"]},
        ensure_ascii=False,
        separators=(",", ":"),
    )

    instructions = (
        "Você é GLIP Intelligence, assistente interno da plataforma GLIP para escritórios de arquitetura. "
        "Responda em português do Brasil, de forma objetiva e operacional. "
        "Use somente o contexto autorizado fornecido. "
        "Não invente dados ausentes. Diferencie fato, hipótese e sugestão quando necessário. "
        "Não execute nem alegue executar ações externas, pagamentos, aprovações, envios ou alterações. "
        "Neste MVP você é somente leitura. "
        "Quando a pergunta estiver vinculada a um projeto, priorize tarefas, cronograma, memória, "
        "conhecimento e demais dados do contexto desse projeto.\n\n"
        f"CONTEXTO_AUTORIZADO_GLIP={context_json}"
    )

    payload = {
        "model": model,
        "store": False,
        "instructions": instructions,
        "input": [
            {"role": m["role"], "content": m["content"]}
            for m in messages
            if m.get("role") in {"user", "assistant"} and str(m.get("content") or "").strip()
        ],
        "max_output_tokens": 1400,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Client-Request-Id": request_id,
    }

    try:
        with httpx.Client(timeout=45.0) as http:
            response = http.post(
                "https://api.openai.com/v1/responses",
                headers=headers,
                json=payload,
            )
    except Exception as exc:
        raise ChatProviderError("chat_provider_unreachable") from exc

    if response.status_code >= 400:
        raise ChatProviderError(f"chat_provider_http_{response.status_code}")

    try:
        data = response.json()
    except Exception as exc:
        raise ChatProviderError("chat_provider_invalid_json") from exc

    return _extract_output_text(data), "openai", model
