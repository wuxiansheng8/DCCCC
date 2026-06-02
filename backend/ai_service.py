import logging
import httpx

logger = logging.getLogger(__name__)

AI_RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


def chat_completions_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/chat/completions"


async def generate_chinese_summary(
    api_key: str,
    base_url: str,
    model: str,
    message_text: str,
    author_name: str,
    channel_name: str,
):
    if not api_key or not base_url or not model or not message_text:
        return None, "AI configuration or message content is missing"

    content, error, _status_code = await request_chinese_translation(api_key, base_url, model, message_text)
    return content, error


async def request_chinese_translation(
    api_key: str,
    base_url: str,
    model: str,
    message_text: str,
):
    prompt = (
        "把下面英文原文直接翻译成中文。\n"
        "只输出译文。\n"
        "不要解释、不要总结、不要改写、不要补充任何原文没有的内容。\n\n"
        f"{message_text}"
    )

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                chat_completions_url(base_url),
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "你是翻译器，只输出中文译文，不添加任何额外内容。",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.1,
                },
            )
        if response.status_code != 200:
            return None, f"AI request returned HTTP {response.status_code}", response.status_code
        
        response_text = response.text.strip()
        content_type = response.headers.get("content-type", "").lower()
        
        # 针对不规范中转 API（如 SkyBridge）的兼容处理：
        # 只要响应正文是以 "{" 或 "[" 开头，说明是标准的普通 JSON（不可能是 SSE 流），不按流式解析
        looks_like_json = response_text.startswith(("{", "["))
        is_stream = response_text.startswith("data:") or (
            "text/event-stream" in content_type and not looks_like_json
        )
        
        if is_stream:
            if not response_text.startswith("data:"):
                try:
                    import json
                    data = json.loads(response_text)
                    if isinstance(data, dict):
                        if "error" in data:
                            error_obj = data.get("error")
                            error_msg = error_obj.get("message") if isinstance(error_obj, dict) else str(error_obj)
                            return None, f"AI request failed: {error_msg or 'Unknown API error'}", None
                except Exception:
                    pass

            full_content = []
            for line in response_text.splitlines():
                line = line.strip()
                if not line.startswith("data:") or line == "data: [DONE]":
                    continue
                try:
                    import json
                    chunk = json.loads(line[5:].strip())
                    if isinstance(chunk, dict):
                        if "error" in chunk:
                            error_obj = chunk.get("error")
                            error_msg = error_obj.get("message") if isinstance(error_obj, dict) else str(error_obj)
                            if error_msg:
                                return None, f"AI request failed: {error_msg}", None
                        choices = chunk.get("choices")
                        if isinstance(choices, list) and len(choices) > 0:
                            delta = choices[0].get("delta", {})
                            if isinstance(delta, dict):
                                delta_content = delta.get("content", "")
                                if delta_content:
                                    full_content.append(delta_content)
                except Exception:
                    continue
            content = "".join(full_content)
        else:
            try:
                data = response.json()
            except Exception as exc:
                return None, f"Failed to parse JSON response: {exc} | Raw response: {response.text[:200]}", None
                
            # 强制检查 data 类型，防止后续 choices = data.get("choices") 对字符串/列表调用 get 报错
            if not isinstance(data, dict):
                return None, f"AI request returned unknown format: {response.text[:300]}", None
                
            if "error" in data:
                error_obj = data.get("error")
                error_msg = error_obj.get("message") if isinstance(error_obj, dict) else str(error_obj)
                return None, f"AI request failed: {error_msg or 'Unknown API error'}", None
                
            choices = data.get("choices")
            raw_content = ""
            if isinstance(choices, list) and len(choices) > 0:
                first_choice = choices[0]
                if isinstance(first_choice, dict):
                    # 优先匹配主流 Chat 格式
                    message = first_choice.get("message")
                    if isinstance(message, dict):
                        raw_content = message.get("content") or ""
                    elif isinstance(message, list) and len(message) > 0:
                        first_msg = message[0]
                        if isinstance(first_msg, dict):
                            raw_content = first_msg.get("content") or ""
                        elif isinstance(first_msg, str):
                            for item in message:
                                if isinstance(item, str) and item.startswith("content:"):
                                    raw_content = item[8:]
                                    break
                            else:
                                try:
                                    idx = message.index("content")
                                    if idx + 1 < len(message):
                                        raw_content = message[idx + 1]
                                except ValueError:
                                    pass
                    
                    # 兼容旧版本或文本补全接口的 "text" 字段作为兜底
                    if not raw_content:
                        raw_content = first_choice.get("text") or ""
                        
            elif isinstance(choices, dict):
                message = choices.get("message")
                if isinstance(message, dict):
                    raw_content = message.get("content") or ""
            content = raw_content
            
        if not content:
            return None, "AI response did not contain content", None
        return content.strip(), None, None
    except httpx.TimeoutException:
        return None, "AI request timed out", None
    except httpx.RequestError as exc:
        return None, f"AI request failed: {exc}", None
    except Exception as exc:
        logger.exception("AI summary failed")
        return None, f"AI summary failed: {exc}", None


def is_retryable_ai_error(error: str | None, status_code: int | None) -> bool:
    if status_code in AI_RETRYABLE_STATUS_CODES:
        return True
    if not error:
        return False
    error_lower = error.lower()
    return (
        "timed out" in error_lower
        or "request failed" in error_lower
        or "failed" in error_lower
        or "did not contain content" in error_lower
        or "unknown format" in error_lower
        or "empty" in error_lower
    )


async def get_api_balance(api_key: str, base_url: str):
    if not api_key or not base_url:
        return None, "AI API Key or Base URL is missing"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                f"{base_url.rstrip('/')}/user/balance",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        if response.status_code != 200:
            return None, f"Balance request returned HTTP {response.status_code}"
        return response.json(), None
    except httpx.TimeoutException:
        return None, "Balance request timed out"
    except httpx.RequestError as exc:
        return None, f"Balance request failed: {exc}"
    except Exception as exc:
        logger.exception("Balance request failed")
        return None, f"Balance request failed: {exc}"
