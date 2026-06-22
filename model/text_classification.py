# Relevance scoring for bidding titles.
#
# Uses an OpenAI-compatible Chat Completions API so a single code path can talk
# to several providers. Titles are scored in batches (one API call per ~20
# titles) and the providers are tried in order until one succeeds, so if the
# primary model is down / out of quota the scoring automatically falls back to a
# cheaper backup model.
#
# Configure whichever keys you have in Streamlit secrets. Each provider's
# concrete model is auto-discovered at runtime (newest matching lightweight
# model), so the names below are just the defaults used if discovery fails:
#   GROQ_API_KEY   = "..."           # primary  -> Groq lightweight llama (free, fast)
#   GEMINI_API_KEY = "..."           # fallback -> Google gemini flash
#   OPENAI_API_KEY = "sk-..."        # fallback -> gpt mini
import json
import re
import openai
import streamlit as sl


BATCH_SIZE = 20

# The scoring rubric, shared by every provider.
_RUBRIC = (
    "You are a classification AI that determines the relevance of Traditional Chinese bidding titles "
    "to Molecular Devices' products (plate readers: SpectraMax series; cell imaging: ImageXpress series) "
    "and their direct competitors in the Taiwan market.\n"
    "Competitors include: BioTek/Agilent (Cytation, Epoch, Synergy), Thermo Fisher (VarioSkan, Multiskan), "
    "BMG Labtech (PHERAstar, CLARIOstar, FLUOstar), PerkinElmer/Revvity (EnVision, VICTOR), "
    "Tecan plate readers, ZEISS cell imaging systems, Bio-Rad (ddPCR, gel imaging), Biochrom.\n"
    "Score each title from 0 to 100, where 100 = highly relevant and 0 = completely irrelevant.\n"
    "Titles unrelated to biology or instrument procurement are likely irrelevant.\n\n"
    "Calibration examples:\n"
    "- '流式細胞儀項目' -> 80\n"
    "- '超微量分光光度計壹台' -> 80\n"
    "- '化學試劑採購' -> 30\n"
    "- '數位病理影像教學管理系統*1式' -> 0\n"
    "- '螢光顯微鏡' -> 70\n"
    "- '分光光度計水質分析儀' -> 70\n"
    "- '多功能微盤分光光譜儀' -> 100\n"
    "- '基因定序採購' -> 0\n"
    "- 'SpectraMax微盤分析儀' -> 100\n"
    "- 'Cytation細胞影像讀盤儀' -> 100\n"
    "- 'PHERAstar FSX多功能微盤儀' -> 100\n"
    "- 'ImageXpress高內涵細胞影像系統' -> 100\n"
    "- 'ZEISS細胞影像系統' -> 90\n"
    "- 'VarioSkan酵素免疫分析儀' -> 100\n"
    "- '高解析質譜儀採購' -> 0\n"
    "- '試劑耗材採購' -> 10\n"
)

# Output instructions for batch scoring.
_SYSTEM_PROMPT = (
    _RUBRIC
    + "\nYou will receive a numbered list of titles (one per line, formatted as 'N. title').\n"
    "Return ONLY a JSON object mapping each item number (as a string) to its integer score.\n"
    'Example for two titles: {"0": 90, "1": 10}\n'
    "Do not include any explanation, markdown, or extra text."
)

# Provider chain, tried in order. base_url=None uses OpenAI's default endpoint;
# the others are OpenAI-compatible gateways.
#
# "model"  = hardcoded default, used only if live discovery fails.
# "prefer" = ordered regex patterns; at runtime we query the provider's live
#            model list and pick the newest id matching the highest-priority
#            pattern, so when a provider rotates model versions (e.g. Groq
#            replacing llama-3.1-8b-instant with a newer light model) the app
#            follows along automatically without a code change.
_PROVIDER_DEFS = [
    {"name": "Groq", "secret": "GROQ_API_KEY",
     "model": "llama-3.1-8b-instant",
     "base_url": "https://api.groq.com/openai/v1",
     "prefer": [r"llama-?[\d.]+-8b-instant", r"llama.*8b.*instant",
                r"llama.*8b", r"instant", r"gemma2?-9b"]},
    {"name": "Gemini", "secret": "GEMINI_API_KEY",
     "model": "gemini-2.0-flash",
     "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
     "prefer": [r"^gemini-[\d.]+-flash-lite$", r"^gemini-[\d.]+-flash$",
                r"flash-lite", r"[\d.]+-flash$", r"flash"]},
    {"name": "OpenAI", "secret": "OPENAI_API_KEY",
     "model": "gpt-4.1-mini", "base_url": None,
     "prefer": [r"^gpt-[\d.]+-mini$", r"^gpt-4o-mini$",
                r"gpt-.*-mini$", r"nano", r"mini"]},
]

# Name of the provider that produced the most recent successful scores.
_LAST_PROVIDER = None

# Diagnostics from the most recent score_titles() run, surfaced in the UI so a
# scoring failure shows *why* (missing keys, auth/quota errors, ...) instead of
# only a generic warning. print() output goes to Streamlit Cloud logs, which the
# user rarely sees.
_LAST_DIAGNOSTICS = {"configured": [], "missing": [], "errors": []}


def get_last_provider():
    """Return the provider name used for the latest successful scoring, or None."""
    return _LAST_PROVIDER


def get_diagnostics():
    """Return diagnostics from the latest scoring run.

    {"configured": [provider names with a key],
     "missing":    [provider names without a key],
     "errors":     ["provider: message", ...]}
    """
    return _LAST_DIAGNOSTICS


def _secret(name):
    try:
        return sl.secrets[name]
    except Exception:
        return None


def _available_providers():
    providers = []
    for p in _PROVIDER_DEFS:
        key = _secret(p["secret"])
        if key:
            providers.append({**p, "api_key": key})
    return providers


# Resolved model id per provider label, cached for the session so we query each
# provider's model list at most once.
_MODEL_CACHE = {}


def _resolve_model(provider):
    """Pick the model to use for a provider.

    Queries the provider's live /models list and returns the newest id matching
    the highest-priority preference pattern. Falls back to the hardcoded default
    if discovery fails or nothing matches. Cached per provider for the session.
    """
    label = provider["name"]
    if label in _MODEL_CACHE:
        return _MODEL_CACHE[label]

    default = provider["model"]
    try:
        client = openai.OpenAI(api_key=provider["api_key"], base_url=provider["base_url"])
        # Strip any "models/" prefix (Gemini returns ids like "models/gemini-...").
        ids = [m.id.split("/")[-1] for m in client.models.list().data]
    except Exception as e:
        print(f"[{label}] model discovery failed, using default '{default}': {e}")
        return default

    chosen = default
    for pattern in provider.get("prefer", []):
        matches = [m for m in ids if re.search(pattern, m, re.I)]
        if matches:
            # Highest id sorts last -> reverse to prefer the newest-looking one.
            chosen = sorted(matches, reverse=True)[0]
            break

    _MODEL_CACHE[label] = chosen
    if chosen != default:
        print(f"[{label}] auto-selected model '{chosen}' (default was '{default}')")
    return chosen


def _parse_batch_scores(raw, n):
    """Parse a model response into a list of n scores (ints or None)."""
    if not raw:
        return None
    text = raw.strip()
    # Strip ```json ... ``` fences if present.
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except (ValueError, TypeError):
            return None

    scores = [None] * n
    if isinstance(data, dict):
        items = data.items()
    elif isinstance(data, list):
        items = enumerate(data)
    else:
        return None

    for key, value in items:
        try:
            idx = int(key)
            score = int(float(value))
        except (ValueError, TypeError):
            continue
        if 0 <= idx < n:
            scores[idx] = max(0, min(100, score))
    return scores


def _score_chunk(titles, provider):
    """Score a single chunk with one provider. Raises on API error."""
    client = openai.OpenAI(api_key=provider["api_key"], base_url=provider["base_url"])
    model = _resolve_model(provider)
    user_msg = "\n".join(f"{i}. {t}" for i, t in enumerate(titles))
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]
    # Ask for guaranteed-JSON output; some gateways reject the param, so fall
    # back to a plain call (the parser already tolerates fenced / prose replies).
    try:
        response = client.chat.completions.create(
            model=model,
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=messages,
        )
    except openai.BadRequestError:
        response = client.chat.completions.create(
            model=model,
            temperature=0.2,
            messages=messages,
        )
    raw = response.choices[0].message.content
    return _parse_batch_scores(raw, len(titles))


def score_titles(titles, progress_callback=None):
    """Score a sequence of titles.

    Returns a list of scores (int 0-100, or None) aligned with the input.
    Non-string / blank titles are skipped (None). Providers are tried in order;
    if one raises an API error it is disabled for the rest of this run and the
    next provider is used.

    progress_callback, if given, is called after each batch as
    progress_callback(done, total) where done/total count valid titles.
    """
    global _LAST_PROVIDER, _LAST_DIAGNOSTICS
    titles = list(titles)
    scores = [None] * len(titles)

    # Reset diagnostics for this run: record which providers have keys.
    configured = [p["name"] for p in _PROVIDER_DEFS if _secret(p["secret"])]
    missing = [p["name"] for p in _PROVIDER_DEFS if not _secret(p["secret"])]
    _LAST_DIAGNOSTICS = {"configured": configured, "missing": missing, "errors": []}

    # Only send real, non-empty string titles to the API.
    valid = [(i, t.strip()) for i, t in enumerate(titles)
             if isinstance(t, str) and t.strip()]
    if not valid:
        return scores

    providers = _available_providers()
    if not providers:
        msg = "未設定任何模型 API 金鑰 (OPENAI_API_KEY / GEMINI_API_KEY / GROQ_API_KEY)。"
        print(msg)
        _LAST_DIAGNOSTICS["errors"].append(msg)
        return scores

    dead = set()
    for start in range(0, len(valid), BATCH_SIZE):
        batch = valid[start:start + BATCH_SIZE]
        batch_titles = [t for _, t in batch]
        chunk_scores = None

        for provider in providers:
            if provider["name"] in dead:
                continue
            try:
                chunk_scores = _score_chunk(batch_titles, provider)
            except openai.OpenAIError as e:
                # Auth/quota/connection issues persist -> stop using this provider.
                msg = f"{provider['name']}: {e}"
                print(f"[{provider['name']}] API error, disabling for this run: {e}")
                _LAST_DIAGNOSTICS["errors"].append(msg)
                dead.add(provider["name"])
                continue
            except Exception as e:
                # Bad/unparseable response -> just try the next provider.
                msg = f"{provider['name']} (unexpected): {e}"
                print(f"[{provider['name']}] unexpected error: {e}")
                _LAST_DIAGNOSTICS["errors"].append(msg)
                continue

            if chunk_scores is not None:
                _LAST_PROVIDER = f"{provider['name']} ({_resolve_model(provider)})"
                break

        if chunk_scores:
            for (orig_idx, _), score in zip(batch, chunk_scores):
                scores[orig_idx] = score

        if progress_callback:
            try:
                progress_callback(min(start + len(batch), len(valid)), len(valid))
            except Exception:
                pass

    return scores


def gpt_classification(prompt):
    """Backward-compatible single-title scorer."""
    return score_titles([prompt])[0]


if __name__ == "__main__":
    print(score_titles([
        "高解析微區光譜儀",
        "微盤光譜",
        "細胞蛋白",
        "辦公桌椅採購",
        "SpectraMax微盤分析儀",
    ]))
