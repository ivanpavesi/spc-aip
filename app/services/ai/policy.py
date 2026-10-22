"""Policy di destinazione AI: nessun SDK e nessun accesso alla rete.

AI_PROVIDER è un vincolo amministrativo. Il modello richiesto dal terapeuta
non può cambiare il destinatario dei dati clinici.
"""

from app.db.models.admin_config import SystemSetting


SUPPORTED_PROVIDERS = {
    "HEURISTIC_OFFLINE": {
        "label": "Motore Clinico Euristico Locale (Offline CBT-SPC)",
        "models": ["cbt-spc-offline"],
    },
    "GEMINI": {
        "label": "Google Gemini",
        "models": ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-2.0-flash"],
    },
    "OPENAI": {
        "label": "OpenAI",
        "models": ["gpt-4o", "gpt-4o-mini", "o3-mini", "o1"],
    },
    "ANTHROPIC": {
        "label": "Anthropic Claude",
        "models": ["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022"],
    },
    "CUSTOM": {
        "label": "Mistral AI / Endpoint Europeo / Ollama Locale",
        "models": ["mistral-large-latest", "mistral-small-latest", "llama3.3:70b"],
    },
}


class AIProviderPolicyError(ValueError):
    """Il modello richiesto non è autorizzato dalla configurazione corrente."""


class AIProviderConfigurationError(RuntimeError):
    """Configurazione non disponibile: nessun provider alternativo implicito."""


def load_ai_settings(db=None) -> dict[str, str]:
    # Senza DB si consente solo il default locale, anche in presenza di API key.
    if db is None:
        return {}
    try:
        return {row.key: row.value for row in db.query(SystemSetting).all()}
    except Exception:
        raise AIProviderConfigurationError("Configurazione AI non disponibile.") from None


def _provider_models(settings_map: dict[str, str]) -> tuple[str, str, list[str]]:
    provider = settings_map.get("AI_PROVIDER", "HEURISTIC_OFFLINE").strip().upper()
    if provider not in SUPPORTED_PROVIDERS:
        raise AIProviderConfigurationError("Provider AI configurato non valido.")
    models = list(SUPPORTED_PROVIDERS[provider]["models"])
    # Un amministratore può configurare anche un nuovo modello o un alias custom.
    configured = settings_map.get(f"{provider}_MODEL", "").strip() if provider != "HEURISTIC_OFFLINE" else ""
    default = configured or models[0]
    if default not in models:
        models.append(default)
    return provider, default, models


def resolve_ai_selection(settings_map: dict[str, str], model_name: str | None = None) -> tuple[str, str]:
    provider, default, allowed = _provider_models(settings_map)
    requested = (model_name or "").strip() or default
    if requested == "heuristic" and provider == "HEURISTIC_OFFLINE":
        requested = "cbt-spc-offline"
    if requested not in allowed:
        raise AIProviderPolicyError("Modello AI non consentito dal provider abilitato dall'amministratore.")
    return provider, requested


def available_ai_models(db) -> list[dict[str, str]]:
    provider, default, models = _provider_models(load_ai_settings(db))
    return [
        {"id": "", "name": f"Predefinito di sistema ({default})"},
        *[{"id": model, "name": f"{SUPPORTED_PROVIDERS[provider]['label']} · {model}"} for model in models],
    ]
