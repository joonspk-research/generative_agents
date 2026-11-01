"""
Multi-provider chat + embedding client.

Supports:
  - openai
  - anthropic
  - openai_compatible (Together, OpenRouter, local servers via base_url)
"""
import re
import time
from typing import List, Optional

from utils import *
from sim_logging import get_logger
from llm import usage
import run_env

log = get_logger("llm")


def _chat_model_name(override: Optional[str] = None) -> str:
  if override:
    return override
  return globals().get("chat_model", "gpt-4o")


def _embedding_model_name(override: Optional[str] = None) -> str:
  if override:
    return override
  return globals().get("embedding_model", "text-embedding-3-small")


def _openai_client(base_url: Optional[str] = None, api_key: Optional[str] = None):
  from openai import OpenAI
  kwargs = {}
  if api_key:
    kwargs["api_key"] = api_key
  if base_url:
    kwargs["base_url"] = base_url
  return OpenAI(**kwargs)


def chat_completion(messages,
                    model: Optional[str] = None,
                    temperature: float = 0.7,
                    max_tokens: int = 1024,
                    stop=None,
                    provider: Optional[str] = None) -> str:
  """
  messages: list of {"role": "system"|"user"|"assistant", "content": str}
  Returns assistant text content.
  """
  provider = (provider or globals().get("llm_provider", "openai")).lower()
  # Staging runs use a cheaper model for every chat call (run_env.py).
  model = run_env.chat_model(_chat_model_name(model))
  prompt_chars = sum(len(m.get("content") or "") for m in messages)
  t0 = time.time()
  log.debug("chat_completion start provider=%s model=%s msgs=%s chars=%s",
            provider, model, len(messages), prompt_chars)
  try:
    if provider == "anthropic":
      out, tokens = _anthropic_chat(messages, model, temperature, max_tokens, stop)
    elif provider == "openai_compatible":
      out, tokens = _openai_chat(
        messages, model, temperature, max_tokens, stop,
        api_key=globals().get("openai_compatible_api_key") or globals().get("openai_api_key"),
        base_url=globals().get("openai_compatible_base_url") or None,
      )
    else:
      out, tokens = _openai_chat(
        messages, model, temperature, max_tokens, stop,
        api_key=globals().get("openai_api_key"),
        base_url=None,
      )
    dt = time.time() - t0
    usage.record("chat", provider, model, *tokens, secs=dt)
    log.info("chat_completion ok provider=%s model=%s %.2fs out_chars=%s "
             "tokens_in=%s tokens_out=%s", provider, model, dt, len(out or ""),
             tokens[0], tokens[1])
    return out
  except Exception as e:
    usage.record("chat", provider, model, secs=time.time() - t0, ok=False,
                 error=e)
    log.exception("chat_completion FAILED provider=%s model=%s after %.2fs",
                  provider, model, time.time() - t0)
    raise


def _openai_chat(messages, model, temperature, max_tokens, stop, api_key, base_url):
  client = _openai_client(base_url=base_url, api_key=api_key)
  kwargs = {
    "model": model,
    "messages": messages,
    "temperature": temperature,
    "max_tokens": max_tokens,
  }
  if stop:
    kwargs["stop"] = stop
  resp = client.chat.completions.create(**kwargs)
  u = resp.usage
  details = getattr(u, "prompt_tokens_details", None) if u else None
  tokens = (getattr(u, "prompt_tokens", 0), getattr(u, "completion_tokens", 0),
            getattr(details, "cached_tokens", 0) or 0)
  return resp.choices[0].message.content or "", tokens


def _anthropic_chat(messages, model, temperature, max_tokens, stop):
  import anthropic
  client = anthropic.Anthropic(api_key=globals().get("anthropic_api_key"))
  system_parts = [m["content"] for m in messages if m.get("role") == "system"]
  converted = []
  for m in messages:
    role = m.get("role")
    if role == "system":
      continue
    if role not in ("user", "assistant"):
      role = "user"
    converted.append({"role": role, "content": m["content"]})
  if not converted:
    converted = [{"role": "user", "content": ""}]
  kwargs = {
    "model": model,
    "messages": converted,
    "temperature": temperature,
    "max_tokens": max_tokens,
  }
  if system_parts:
    kwargs["system"] = "\n\n".join(system_parts)
  if stop:
    kwargs["stop_sequences"] = stop if isinstance(stop, list) else [stop]
  resp = client.messages.create(**kwargs)
  parts = []
  for block in resp.content:
    if getattr(block, "type", None) == "text":
      parts.append(block.text)
  u = resp.usage
  tokens = (getattr(u, "input_tokens", 0), getattr(u, "output_tokens", 0),
            getattr(u, "cache_read_input_tokens", 0) or 0)
  return "".join(parts), tokens


def get_embedding_vector(text: str, model: Optional[str] = None) -> List[float]:
  provider = globals().get("embedding_provider", "openai").lower()
  model = _embedding_model_name(model)
  text = (text or "this is blank").replace("\n", " ")
  t0 = time.time()

  if provider == "anthropic":
    # Anthropic has no embeddings API comparable to OpenAI; fall back to OpenAI.
    provider = "openai"

  try:
    if provider == "openai_compatible":
      client = _openai_client(
        base_url=globals().get("openai_compatible_base_url") or None,
        api_key=globals().get("openai_compatible_api_key") or globals().get("openai_api_key"),
      )
    else:
      client = _openai_client(api_key=globals().get("openai_api_key"))

    resp = client.embeddings.create(input=[text], model=model)
    vec = resp.data[0].embedding
    usage.record("embedding", provider, model,
                 getattr(resp.usage, "prompt_tokens", 0), secs=time.time() - t0)
    log.debug("embedding ok provider=%s model=%s %.2fs dims=%s",
              provider, model, time.time() - t0, len(vec))
    return vec
  except Exception as e:
    usage.record("embedding", provider, model, secs=time.time() - t0,
                 ok=False, error=e)
    log.exception("embedding FAILED provider=%s model=%s after %.2fs",
                  provider, model, time.time() - t0)
    raise


def extract_json_output(text: str):
  """
  Pull a JSON object from model text and return the 'output' field when present.
  Falls back to the whole parsed object.
  """
  import json
  if text is None:
    raise ValueError("empty response")
  cleaned = text.strip()
  cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
  cleaned = re.sub(r"\s*```$", "", cleaned)
  # Prefer outermost object containing "output"
  start = cleaned.find("{")
  end = cleaned.rfind("}")
  if start == -1 or end == -1 or end <= start:
    raise ValueError("no json object found")
  obj = json.loads(cleaned[start:end + 1])
  if isinstance(obj, dict) and "output" in obj:
    out = obj["output"]
    # The prompts' examples quote the value ({"output": "5"}) and the clean-up
    # functions expect text, but some models (e.g. gpt-4o-mini) answer with a
    # bare number ({"output": 8}). Lists and objects are left as they are.
    if isinstance(out, (int, float)) and not isinstance(out, bool):
      out = str(out)
    return out
  return obj
