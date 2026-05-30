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
        content_type = response.headers.get("content-type", "")
        
        if "text/event-stream" in content_type or response_text.startswith("data:"):
            if not response_text.startswith("data:"):
                try:
                    import json
                    data = json.loads(response_text)
                    if "error" in data:
                        error_msg = data.get("error", {}).get("message") or "Unknown API error"
                        return None, f"AI request failed: {error_msg}", None
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
                    if "error" in chunk:
                        error_msg = chunk.get("error", {}).get("message")
                        if error_msg:
                            return None, f"AI request failed: {error_msg}", None
                    delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                    if delta:
                        full_content.append(delta)
                except Exception:
                    continue
            content = "".join(full_content)
        else:
            data = response.json()
            if "error" in data:
                error_msg = data.get("error", {}).get("message") or "Unknown API error"
                return None, f"AI request failed: {error_msg}", None
            content = data.get("choices", [{}])[0].get("message", {}).get("content")
            
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
    return "timed out" in error_lower or "request failed" in error_lower


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
