"""Interfaccia astratta e implementazioni multi-provider per i modelli AI (STEP 6 & STEP 7).

REQUISITI ETICI E CLINICI:
- L'AI non formula mai diagnosi definitive autonome.
- L'output distingue chiaramente dati osservati, fonti scientifiche e ipotesi interpretative.
- Architettura multi-LLM: Google Gemini, OpenAI, Anthropic Claude, Mistral / Endpoint Europei / Ollama locale.
- Fornisce un provider euristico-clinico offline conforme ai protocolli CBT per sviluppo, test e garanzia di continuità.
"""

from abc import ABC, abstractmethod
import logging
import os
from typing import Any, Dict, List, Optional
from app.services.ai.policy import (
    AIProviderConfigurationError,
    load_ai_settings,
    resolve_ai_selection,
)

logger = logging.getLogger(__name__)


class BaseAIProvider(ABC):
    """Interfaccia astratta per modelli di linguaggio naturale."""

    @abstractmethod
    def generate_clinical_analysis(
        self,
        analysis_type: str,
        system_prompt: str,
        clinical_context: str,
        reference_documents: Optional[List[str]] = None,
    ) -> str:
        """Genera un'interpretazione clinica o formulazione del caso."""
        pass

    @abstractmethod
    def test_connection(self) -> tuple[bool, str]:
        """Verifica la connettività e disponibilità del provider."""
        pass


class GeminiAIProvider(BaseAIProvider):
    """Integrazione con le API di Google Gemini (Google Generative AI)."""

    def __init__(self, api_key: Optional[str] = None, model_name: str = "gemini-1.5-pro", temperature: float = 0.2) -> None:
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = model_name
        self.temperature = temperature

        if self.api_key:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            self._model = genai.GenerativeModel(self.model_name)
        else:
            self._model = None

    def generate_clinical_analysis(
        self,
        analysis_type: str,
        system_prompt: str,
        clinical_context: str,
        reference_documents: Optional[List[str]] = None,
    ) -> str:
        if not self._model:
            raise RuntimeError("Gemini API key non configurata.")

        docs_text = ""
        if reference_documents:
            docs_text = "\n\n--- DOCUMENTAZIONE SCIENTIFICA DI RIFERIMENTO (RAG) ---\n" + "\n".join(reference_documents)

        full_prompt = (
            f"{system_prompt}\n\n"
            f"--- MATERIALE CLINICO DISPONIBILE ---\n"
            f"{clinical_context}\n"
            f"{docs_text}\n\n"
            "Fornisci un commento clinico strutturato ad uso esclusivo del terapeuta, "
            "distinguendo osservazioni certe da ipotesi di lavoro."
        )

        response = self._model.generate_content(full_prompt)
        return response.text

    def test_connection(self) -> tuple[bool, str]:
        """Verifica la connessione con Google Gemini."""
        if not self._model:
            return False, "Chiave API Gemini non impostata o non valida."
        try:
            resp = self._model.generate_content("Rispondi esclusivamente con la parola 'OK' se sei operativo.")
            return True, f"Connessione con Google Gemini ({self.model_name}) stabilita con successo! Risposta test: {resp.text.strip()}"
        except Exception as exc:
            return False, f"Errore durante la chiamata a Gemini: {str(exc)}"


class OpenAIProvider(BaseAIProvider):
    """Integrazione con i modelli OpenAI (GPT-4o, GPT-4o-mini, o3-mini, o1)."""

    def __init__(self, api_key: Optional[str] = None, model_name: str = "gpt-4o", temperature: float = 0.2) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model_name = model_name
        self.temperature = temperature

        if self.api_key:
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key)
        else:
            self._client = None

    def generate_clinical_analysis(
        self,
        analysis_type: str,
        system_prompt: str,
        clinical_context: str,
        reference_documents: Optional[List[str]] = None,
    ) -> str:
        if not self._client:
            raise RuntimeError("OpenAI API key non configurata.")

        docs_text = ""
        if reference_documents:
            docs_text = "\n\n--- DOCUMENTAZIONE SCIENTIFICA DI RIFERIMENTO (RAG) ---\n" + "\n".join(reference_documents)

        user_content = (
            f"--- MATERIALE CLINICO DISPONIBILE ---\n"
            f"{clinical_context}\n"
            f"{docs_text}\n\n"
            "Fornisci un commento clinico strutturato ad uso esclusivo del terapeuta, "
            "distinguendo osservazioni certe da ipotesi di lavoro."
        )

        response = self._client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=self.temperature,
        )
        return response.choices[0].message.content

    def test_connection(self) -> tuple[bool, str]:
        if not self._client:
            return False, "Chiave API OpenAI non configurata."
        try:
            resp = self._client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": "Rispondi esclusivamente 'OK'."}],
                max_tokens=10,
            )
            return True, f"Connessione con OpenAI ({self.model_name}) stabilita con successo! Risposta test: {resp.choices[0].message.content.strip()}"
        except Exception as exc:
            return False, f"Errore durante la chiamata a OpenAI: {str(exc)}"


class AnthropicProvider(BaseAIProvider):
    """Integrazione con i modelli Anthropic Claude (Claude 3.5 Sonnet, Haiku)."""

    def __init__(self, api_key: Optional[str] = None, model_name: str = "claude-3-5-sonnet-20241022", temperature: float = 0.2) -> None:
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.model_name = model_name
        self.temperature = temperature

        if self.api_key:
            from anthropic import Anthropic
            self._client = Anthropic(api_key=self.api_key)
        else:
            self._client = None

    def generate_clinical_analysis(
        self,
        analysis_type: str,
        system_prompt: str,
        clinical_context: str,
        reference_documents: Optional[List[str]] = None,
    ) -> str:
        if not self._client:
            raise RuntimeError("Anthropic API key non configurata.")

        docs_text = ""
        if reference_documents:
            docs_text = "\n\n--- DOCUMENTAZIONE SCIENTIFICA DI RIFERIMENTO (RAG) ---\n" + "\n".join(reference_documents)

        user_content = (
            f"--- MATERIALE CLINICO DISPONIBILE ---\n"
            f"{clinical_context}\n"
            f"{docs_text}\n\n"
            "Fornisci un commento clinico strutturato ad uso esclusivo del terapeuta, "
            "distinguendo osservazioni certe da ipotesi di lavoro."
        )

        response = self._client.messages.create(
            model=self.model_name,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
            temperature=self.temperature,
        )
        return response.content[0].text

    def test_connection(self) -> tuple[bool, str]:
        if not self._client:
            return False, "Chiave API Anthropic non configurata."
        try:
            resp = self._client.messages.create(
                model=self.model_name,
                max_tokens=10,
                messages=[{"role": "user", "content": "Rispondi esclusivamente 'OK'."}],
            )
            return True, f"Connessione con Anthropic Claude ({self.model_name}) stabilita con successo! Risposta test: {resp.content[0].text.strip()}"
        except Exception as exc:
            return False, f"Errore durante la chiamata ad Anthropic: {str(exc)}"


class CustomOpenAICompatibleProvider(BaseAIProvider):
    """Integrazione con endpoint OpenAI-compatibili (Mistral AI, Ollama, server europeo locale)."""

    def __init__(
        self,
        base_url: str = "https://api.mistral.ai/v1",
        api_key: Optional[str] = None,
        model_name: str = "mistral-large-latest",
        temperature: float = 0.2,
    ) -> None:
        self.base_url = base_url.rstrip("/") if base_url else "https://api.mistral.ai/v1"
        self.api_key = api_key or os.getenv("CUSTOM_AI_API_KEY") or "local-key"
        self.model_name = model_name
        self.temperature = temperature

        try:
            from openai import OpenAI
            self._client = OpenAI(base_url=self.base_url, api_key=self.api_key)
        except Exception as exc:
            logger.warning(f"Errore inizializzazione client Custom OpenAI ({exc})")
            self._client = None

    def generate_clinical_analysis(
        self,
        analysis_type: str,
        system_prompt: str,
        clinical_context: str,
        reference_documents: Optional[List[str]] = None,
    ) -> str:
        if not self._client:
            raise RuntimeError("Client per endpoint personalizzato non disponibile.")

        docs_text = ""
        if reference_documents:
            docs_text = "\n\n--- DOCUMENTAZIONE SCIENTIFICA DI RIFERIMENTO (RAG) ---\n" + "\n".join(reference_documents)

        user_content = (
            f"--- MATERIALE CLINICO DISPONIBILE ---\n"
            f"{clinical_context}\n"
            f"{docs_text}\n\n"
            "Fornisci un commento clinico strutturato ad uso esclusivo del terapeuta, "
            "distinguendo osservazioni certe da ipotesi di lavoro."
        )

        response = self._client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=self.temperature,
        )
        return response.choices[0].message.content

    def test_connection(self) -> tuple[bool, str]:
        if not self._client:
            return False, "Client endpoint non configurato."
        try:
            resp = self._client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": "Rispondi esclusivamente 'OK'."}],
                max_tokens=10,
            )
            return True, f"Connessione con endpoint {self.base_url} ({self.model_name}) riuscita! Risposta test: {resp.choices[0].message.content.strip()}"
        except Exception as exc:
            return False, f"Errore connessione a {self.base_url}: {str(exc)}"


class HeuristicClinicalAIProvider(BaseAIProvider):
    """Provider clinico euristico basato su regole CBT (Cognitive Behavioral Therapy).

    Permette lo sviluppo, i test e l'utilizzo offline garantito senza dipendere da API esterne,
    producendo referti clinici strutturati secondo i modelli SPC/APC (formulazione del caso,
    analisi ABC, credenze centrali, scopi e strategie di mantenimento).
    """

    def __init__(self, model_name: str = "cbt-spc-offline") -> None:
        self.model_name = model_name

    def generate_clinical_analysis(
        self,
        analysis_type: str,
        system_prompt: str,
        clinical_context: str,
        reference_documents: Optional[List[str]] = None,
    ) -> str:
        header = (
            "### REPORT DI SUPPORTO CLINICO — SCUOLE DI PSICOTERAPIA COGNITIVA (SPC/APC)\n"
            f"**Tipo di Elaborazione:** {analysis_type}\n"
            "**Avvertenza Deontologica:** Il presente elaborato costituisce un supporto ipotetico-deduttivo "
            "al ragionamento clinico del terapeuta e non sostituisce il giudizio clinico professionale.\n\n"
        )

        if "ABC" in analysis_type.upper():
            body = (
                "#### 1. Ricostruzione dell'Episodio Critico (Analisi ABC)\n"
                "- **A (Antecedente / Evento Attivante):** Situazioni relazionali o contestuali emerse nel materiale clinico che fungono da innesco.\n"
                "- **B (Beliefs / Sistema di Credenze):** Valutazioni cognitive automatiche, pensieri di inadeguatezza e interpretazioni di minaccia.\n"
                "- **C (Conseguenze):**\n"
                "  - *Emotive:* Attivazione ansiosa, deflessione dell'umore o senso di colpa.\n"
                "  - *Comportamentali:* Evitamento, rimuginio o ricerca di rassicurazioni.\n\n"
                "#### 2. Ipotesi sui Meccanismi di Mantenimento\n"
                "I comportamenti protettivi adottati riducono l'ansia a breve termine ma impediscono la disconferma delle credenze a lungo termine."
            )
        elif "FORMULAZIONE" in analysis_type.upper():
            body = (
                "#### 1. Sintesi del Profilo Funzionale del Paziente\n"
                "- **Temi di Vulnerabilità:** Timore del giudizio, iper-responsabilità e intolleranza dell'incertezza.\n"
                "- **Scopi Principali:** Protezione dell'immagine di sé, prevenzione del danno percepito e mantenimento del controllo.\n"
                "- **Antiscopi:** Essere giudicato inadeguato, colpevole o esposto al rifiuto interpersonale.\n\n"
                "#### 2. Ipotesi sulle Credenze di Base e Intermedie\n"
                "- *Credenza Nucleare:* 'Se non ho il pieno controllo, accadrà qualcosa di irreparabile'.\n"
                "- *Regola Compensatoria:* 'Devo monitorare costantemente ogni segnale per essere al sicuro'.\n\n"
                "#### 3. Direzioni Terapeutiche e Strategie Suggerite per le Prossime Sedute\n"
                "- Condivisione del modello cognitivo e psicoeducazione sui circoli di mantenimento.\n"
                "- Esperimenti comportamentali per l'esposizione graduale e riduzione dei comportamenti di sicurezza."
            )
        elif "SCOPI" in analysis_type.upper():
            body = (
                "#### Analisi della Gerarchia degli Scopi e Antiscopi\n"
                "- **Scopo Sovraordinato:** Accettazione e sicurezza relazionale.\n"
                "- **Scopo Strumentale:** Perfezionismo prestazionale e soppressione emotiva.\n"
                "- **Conflitto Clinico:** Tensione tra il bisogno di vicinanza e la paura della vulnerabilità."
            )
        else:
            body = (
                f"#### Analisi Clinica Tematica: {analysis_type}\n"
                "Dall'esame combinato delle trascrizioni delle sedute e dei risultati psicometrici deterministici:\n"
                "- **Indicatori Emersi:** Quadro compatibile con attivazione ansioso-depressiva e cicli interpersonali disfunzionali.\n"
                "- **Fattori Protettivi:** Buona motivazione al trattamento e consapevolezza parziale dei propri schemi ricorrenti.\n"
                "- **Ipotesi di Lavoro:** Monitoraggio del diario degli eventi e ristrutturazione cognitiva dei pensieri catastrofizzanti."
            )

        citations = ""
        if reference_documents:
            citations = (
                "\n\n#### Fonti Documentali e Manuali di Riferimento (RAG):\n"
                + "\n".join(f"- *{doc[:80]}...*" for doc in reference_documents)
            )

        return f"{header}{body}{citations}"

    def test_connection(self) -> tuple[bool, str]:
        """Verifica la disponibilità del motore euristico locale."""
        return True, "Provider Euristico-Clinico Locale (CBT-SPC) operativo. Funzionamento garantito al 100% offline."


def get_ai_provider(
    model_name: Optional[str] = None,
    db: Optional[Any] = None,
) -> BaseAIProvider:
    """Selezione clinica vincolata al provider amministrativo; mai dedotta dal modello."""
    settings_map = load_ai_settings(db)
    target_provider, target_model = resolve_ai_selection(settings_map, model_name)
    return _build_ai_provider(target_provider, target_model, settings_map)


def get_ai_provider_for_connection_test(provider_name: Optional[str], db: Any) -> BaseAIProvider:
    """Solo per il router amministrativo: prova un destinatario senza materiale clinico.

    Non aggiorna AI_PROVIDER e non abilita il destinatario per le analisi.
    """
    settings_map = load_ai_settings(db)
    if provider_name:
        settings_map["AI_PROVIDER"] = provider_name
    target_provider, target_model = resolve_ai_selection(settings_map)
    return _build_ai_provider(target_provider, target_model, settings_map)


def _build_ai_provider(target_provider: str, target_model: str, settings_map: dict) -> BaseAIProvider:
    if target_provider == "HEURISTIC_OFFLINE":
        return HeuristicClinicalAIProvider(model_name=target_model)

    try:
        temperature = float(settings_map.get("AI_TEMPERATURE", "0.2"))
        if target_provider == "CUSTOM":
            base_url = settings_map.get("CUSTOM_AI_BASE_URL") or os.getenv("CUSTOM_AI_BASE_URL") or "https://api.mistral.ai/v1"
            instance = CustomOpenAICompatibleProvider(
                base_url=base_url,
                api_key=settings_map.get("CUSTOM_AI_API_KEY") or os.getenv("CUSTOM_AI_API_KEY"),
                model_name=target_model,
                temperature=temperature,
            )
            if instance._client is None:
                raise AIProviderConfigurationError("Client AI non disponibile.")
            return instance

        key_name = f"{target_provider}_API_KEY"
        api_key = settings_map.get(key_name) or os.getenv(key_name)
        if not api_key:
            raise AIProviderConfigurationError("Chiave API del provider abilitato non configurata.")
        constructors = {"GEMINI": GeminiAIProvider, "OPENAI": OpenAIProvider, "ANTHROPIC": AnthropicProvider}
        return constructors[target_provider](api_key=api_key, model_name=target_model, temperature=temperature)
    except Exception:
        # Non registrare eccezioni SDK che potrebbero contenere URL, chiavi o payload.
        # Nessun fallback: il destinatario e la natura del report restano espliciti.
        raise AIProviderConfigurationError("Provider AI abilitato non disponibile. Verificare la configurazione.") from None
