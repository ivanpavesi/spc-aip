"""Inizializzazione dei dati iniziali (Seeding) per sviluppo e catalogo test."""

import logging
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.security import hash_password
from app.db.models.test_engine import TestDefinition
from app.db.models.user import Therapist, User, UserRole
from app.services.scoring.engine import get_bdi2_definition, get_stai_y1_definition

logger = logging.getLogger(__name__)


def seed_database(db: Session) -> None:
    """Popola il catalogo applicativo; aggiunge account demo solo in sviluppo/test."""
    # 1. Popolamento Catalogo Test
    bdi = db.query(TestDefinition).filter(TestDefinition.code == "BDI-II").first()
    if not bdi:
        bdi_schema, bdi_rules = get_bdi2_definition()
        bdi_def = TestDefinition(
            code="BDI-II",
            title="Beck Depression Inventory - II (BDI-II)",
            version="1.0.0",
            description="Questionario di autovalutazione composto da 21 item per misurare la severità della depressione clinica.",
            items_schema=bdi_schema,
            scoring_rules=bdi_rules,
            is_active=True,
        )
        db.add(bdi_def)
        logger.info("Catalogo test: BDI-II creato con successo.")

    stai = db.query(TestDefinition).filter(TestDefinition.code == "STAI-Y1").first()
    if not stai:
        stai_schema, stai_rules = get_stai_y1_definition()
        stai_def = TestDefinition(
            code="STAI-Y1",
            title="State-Trait Anxiety Inventory (STAI-Y1 - Ansia di Stato)",
            version="1.0.0",
            description="Strumento per la misurazione dell'ansia contingente o di stato attraverso 20 item su scala Likert a 4 punti.",
            items_schema=stai_schema,
            scoring_rules=stai_rules,
            is_active=True,
        )
        db.add(stai_def)
        logger.info("Catalogo test: STAI-Y1 creato con successo.")

    # 2. Account demo: il controllo è anche nel punto di ingresso diretto.
    seed_demo_users(db)

    # 3. Pulsanti di Analisi Clinica Preconfigurati (Scuole di Psicoterapia Cognitiva SPC/APC)
    from app.db.models.admin_config import ClinicalAnalysisButton, SystemSetting

    default_buttons = [
        {
            "name": "Formulazione del Caso",
            "description": "Formulazione clinica secondo il modello cognitivista standard SPC/APC.",
            "display_order": 1,
            "system_prompt": (
                "Sei un supervisore clinico esperto delle Scuole di Psicoterapia Cognitiva (SPC/APC). "
                "Genera una formulazione del caso clinico strutturata secondo il modello cognitivista:\n"
                "1. Sintesi del funzionamento e profilo cognitivo-comportamentale\n"
                "2. Vulnerabilità storica ed eventi scatenanti/attivanti\n"
                "3. Credenze di base (core beliefs) e credenze intermedie\n"
                "4. Gerarchia degli scopi compromessi e antiscopi\n"
                "5. Circoli viziosi e strategie protettive/di mantenimento\n"
                "6. Obiettivi prioritari di intervento e tecniche raccomandate."
            ),
        },
        {
            "name": "Analisi ABC",
            "description": "Ricostruzione dell'episodio critico (Antecedente, Beliefs, Conseguenze).",
            "display_order": 2,
            "system_prompt": (
                "Ricostruisci in dettaglio uno o più episodi critici emersi dal materiale clinico:\n"
                "- A (Antecedente / Evento Attivante): contesto oggettivo e innesco interno/esterno\n"
                "- B (Beliefs / Pensieri Automatici): interpretazioni, valutazioni di minaccia e significato attribuito\n"
                "- C (Conseguenze): reazioni emotive, modificazioni fisiologiche e risposte comportamentali\n"
                "- Circolo di mantenimento: come C rinforza e conferma la credenza B iniziale."
            ),
        },
        {
            "name": "Emozioni e Cognizioni Problematiche",
            "description": "Analisi delle emozioni critiche e credenze metacognitive associate.",
            "display_order": 3,
            "system_prompt": (
                "Analizza le emozioni problematiche identificate (ansia, tristezza, colpa, vergogna, rabbia) "
                "e le credenze metacognitive sul funzionamento e sull'incontrollabilità delle proprie emozioni."
            ),
        },
        {
            "name": "Scopi e Antiscopi",
            "description": "Gerarchia degli scopi, antiscopi e conflitti motivazionali.",
            "display_order": 4,
            "system_prompt": (
                "Identifica la gerarchia degli scopi del paziente secondo il modello di Castelfranchi e Miceli:\n"
                "- Scopi sovraordinati (es. sicurezza, valore personale, autonomia, affiliazione)\n"
                "- Scopi strumentali\n"
                "- Antiscopi (stati temuti primari da evitare a ogni costo)\n"
                "- Conflitti motivazionali tra scopi incompatibili."
            ),
        },
        {
            "name": "Credenze e Strategie di Mantenimento",
            "description": "Credenze centrali e comportamenti protettivi disfunzionali.",
            "display_order": 5,
            "system_prompt": (
                "Metti in luce le credenze nucleari disfunzionali e i meccanismi di mantenimento cognitivo e comportamentale "
                "(evitamenti, condotte di rassicurazione, rimuginio, attenzione selettiva)."
            ),
        },
        {
            "name": "Analisi Relazione Terapeutica",
            "description": "Cicli interpersonali disfunzionali e monitoraggio dell'alleanza terapeutica.",
            "display_order": 6,
            "system_prompt": (
                "Analizza la dinamica della relazione terapeutica secondo il modello dei cicli interpersonali (Safran e Muran):\n"
                "- Comportamenti interpersonali del paziente in seduta\n"
                "- Reazioni emotive suscitate nel terapeuta (controtransfert cognitivo)\n"
                "- Potenziali indicatori di rottura dell'alleanza e suggerimenti per la riparazione."
            ),
        },
        {
            "name": "Valutazione Andamento Trattamento",
            "description": "Confronto evolutivo tra le fasi del trattamento e trend psicometrici.",
            "display_order": 7,
            "system_prompt": (
                "Sintetizza l'evoluzione clinica del paziente confrontando le prime sedute con quelle più recenti "
                "e l'andamento dei punteggi psicometrici somministrati nel tempo."
            ),
        },
    ]

    for btn_data in default_buttons:
        existing_btn = db.query(ClinicalAnalysisButton).filter(ClinicalAnalysisButton.name == btn_data["name"]).first()
        if not existing_btn:
            new_btn = ClinicalAnalysisButton(
                name=btn_data["name"],
                description=btn_data["description"],
                system_prompt=btn_data["system_prompt"],
                display_order=btn_data["display_order"],
                version="1.0-SPC",
                is_active=True,
            )
            db.add(new_btn)

    # 4. Impostazioni Globali di Sistema (AI & Provider)
    default_settings = [
        ("AI_PROVIDER", "HEURISTIC_OFFLINE", "Provider AI predefinito: HEURISTIC_OFFLINE o GEMINI"),
        ("GEMINI_MODEL", "gemini-1.5-pro", "Modello LLM utilizzato per le elaborazioni cliniche avanzate"),
        ("AI_TEMPERATURE", "0.2", "Temperatura di campionamento (0.0 - 1.0)"),
        (
            "AI_SYSTEM_PREAMBLE",
            "Sei un assistente AI clinico specializzato per le Scuole di Psicoterapia Cognitiva (SPC/APC). "
            "Fornisci commenti clinici rigorosi e strutturati, distinguendo sempre i dati empirici dalle ipotesi di lavoro.",
            "Preambolo di sistema generale inviato ai modelli AI",
        ),
    ]

    for key, val, desc in default_settings:
        existing_setting = db.query(SystemSetting).filter(SystemSetting.key == key).first()
        if not existing_setting:
            db.add(SystemSetting(key=key, value=val, description=desc))

    db.commit()


def seed_demo_users(db: Session) -> None:
    """Crea solo account mancanti in sviluppo/test, senza modificare utenze esistenti."""
    if settings.ENVIRONMENT not in {"development", "testing"}:
        return

    # 2. Utenze dimostrative iniziali (sviluppo)
    admin_user = db.query(User).filter(User.email == "admin@spc.it").first()
    if not admin_user:
        admin_user = User(
            email="admin@spc.it",
            hashed_password=hash_password("admin"),
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add(admin_user)

    therapist_user = db.query(User).filter(User.email == "terapeuta@spc.it").first()
    if not therapist_user:
        therapist_user = User(
            email="terapeuta@spc.it",
            hashed_password=hash_password("terapeuta"),
            role=UserRole.THERAPIST,
            is_active=True,
        )
        db.add(therapist_user)
        db.flush()

        therapist_profile = Therapist(
            user_id=therapist_user.id,
            full_name="Dott. Mario Rossi",
            license_number="12345/Lazio",
            order_region="Lazio",
        )
        db.add(therapist_profile)

    researcher_user = db.query(User).filter(User.email == "ricercatore@spc.it").first()
    if not researcher_user:
        researcher_user = User(
            email="ricercatore@spc.it",
            hashed_password=hash_password("ricercatore"),
            role=UserRole.RESEARCHER,
            is_active=True,
        )
        db.add(researcher_user)
