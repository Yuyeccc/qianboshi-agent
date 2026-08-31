# -*- coding: utf-8 -*-
"""
贵模型优先封装（2026-08-22 用户要求）：
analysis 类产出优先调用 premium（fluxionai gpt-5.6），失败/截断/空输出时
fallback analysis_model。2026-08-27 起全线统一 deepseek-v4-flash。
routine 类产出不受影响（flash）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _read_premium_key(llm: dict[str, Any]) -> str | None:
    """读取 premium API key（配置文件路径）。"""
    premium = llm.get("premium") or {}
    key_file = premium.get("api_key_file")
    if not key_file:
        return None
    try:
        return Path(key_file).read_text(encoding="utf-8").strip()
    except Exception:
        return None


def call_premium(
    llm: dict[str, Any],
    messages: list[dict[str, str]],
    tools: list[dict[str, Any]] | None = None,
    temperature: float = 0.3,
    max_tokens: int | None = None,
    timeout: int = 150,
) -> dict[str, Any] | None:
    """
    调用 premium（fluxionai gpt-5.6）。返回 OpenAI 兼容响应 dict；
    失败/超时/空输出/截断(length) 返回 None（由调用方 fallback）。
    """
    import requests

    premium = llm.get("premium") or {}
    if not premium.get("enabled", True):
        return None
    api_base = premium.get("api_base")
    model = premium.get("model", "gpt-5.6-sol")
    key = _read_premium_key(llm)
    if not api_base or not key:
        return None

    # fluxionai 长输出必 524 超时：max_tokens 有安全上限（3500）
    cap = int(premium.get("max_tokens", 3500))
    if max_tokens is None:
        max_tokens = cap
    else:
        max_tokens = min(int(max_tokens), cap)

    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    url = f"{api_base.rstrip('/')}/chat/completions"

    try:
        resp = requests.post(url, headers=headers, json=body, timeout=timeout)
        if resp.status_code >= 400:
            return None
        data = resp.json()
    except Exception:
        return None

    try:
        choice = data["choices"][0]
        msg = choice.get("message") or {}
        finish = choice.get("finish_reason", "")
        content = msg.get("content") or ""
        # 截断或空输出视为"不行"，交给 fallback
        if finish == "length":
            return None
        if not content and not msg.get("tool_calls"):
            return None
    except Exception:
        return None

    return data


def call_analysis_llm(
    llm: dict[str, Any],
    messages: list[dict[str, str]],
    temperature: float = 0.3,
    max_tokens: int | None = None,
    json_mode: bool = False,
    timeout: int = 150,
) -> tuple[str, str]:
    """
    统一入口：premium(gpt-5.6-sol) 优先，失败/截断 fallback analysis_model。
    （2026-08-27 用户最终指令：可用模型仅 flash 与 gpt-5.6-sol，禁用 v4-pro——太贵）
    analysis_model 已配置为 flash，因此兜底永远不会落到 pro。
    返回 (content, used_model)。json_mode=True 时请求 response_format=json_object。
    """
    import requests

    # 1) premium 优先（gpt-5.6-sol）
    premium_resp = call_premium(
        llm, messages, temperature=temperature, max_tokens=max_tokens, timeout=timeout
    )
    if premium_resp is not None:
        try:
            content = premium_resp["choices"][0]["message"].get("content") or ""
            if content.strip():
                return content.strip(), llm.get("premium", {}).get("model", "gpt-5.6-sol")
        except Exception:
            pass

    # 2) fallback analysis_model（=deepseek-v4-flash，pro 已禁）
    body: dict[str, Any] = {
        "model": llm["analysis_model"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": min(int(llm.get("max_tokens", 8192)), max_tokens or 8192),
        "thinking": {"type": "disabled"},  # deepseek 推理模型必须关思考
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {llm['api_key']}",
        "Content-Type": "application/json",
    }
    url = f"{llm['api_base'].rstrip('/')}/chat/completions"

    resp = requests.post(url, headers=headers, json=body, timeout=timeout)
    if resp.status_code >= 400 and json_mode and "response_format" in body:
        body.pop("response_format", None)
        resp = requests.post(url, headers=headers, json=body, timeout=timeout)
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"].get("content", "")
    return content, llm["analysis_model"]
