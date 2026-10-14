"""Router per l'Area Terapeuta: gestione pazienti, cartelle, test, sedute e AI (STEP 2, 3, 4, 6, 7)."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.core.auth import require_therapist
from app.core.security import generate_pseudonym_code, generate_secure_token, hash_token
from app.db.models.admin_config import ClinicalAnalysisButton, ScientificDocument
from app.db.models.clinical import ClinicalAnalysis, ClinicalRecord, TherapySession
from app.db.models.patient import ConsentRecord, PatientIdentity
from app.db.models.test_engine import TestAssignment, TestDefinition, TestResponse, TestScore, TestStatus
from app.db.models.user import Therapist, User
from app.db.session import get_db
from app.services.ai.provider import get_ai_provider
from app.services.documents import extract_text_from_file
from app.services.encryption import encryption_service

router = APIRouter(prefix="/therapist", tags=["Area Terapeuta"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_therapist_profile(user: User, db: Session) -> Therapist:
    """Recupera o crea il profilo professionale del terapeuta associato all'utente."""
    profile = db.query(Therapist).filter(Therapist.user_id == user.id).first()
    if not profile:
        profile = Therapist(
            user_id=user.id,
            full_name=user.email.split("@")[0].replace(".", " ").title(),
            license_number="In fase di registrazione",
        )
        db.add(profile)
        db.commit()
    return profile


@router.get("/dashboard", response_class=HTMLResponse, summary="Dashboard Terapeuta")
def therapist_dashboard(
    request: Request,
    user: User = Depends(require_therapist),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    profile = get_therapist_profile(user, db)

    # Recupera i pazienti del terapeuta
    patients_db = db.query(PatientIdentity).filter(PatientIdentity.therapist_id == profile.id).all()
    
    # Decifra i nomi anagrafici per la visualizzazione autorizzata
    patients_list = []
    for p in patients_db:
        rec = db.query(ClinicalRecord).filter(ClinicalRecord.patient_id == p.id).first()
        patients_list.append({
            "id": p.id,
            "first_name": encryption_service.decrypt_text(p.encrypted_first_name),
            "last_name": encryption_service.decrypt_text(p.encrypted_last_name),
            "pseudonym_code": rec.pseudonym_code if rec else "N/D",
            "date_of_birth": p.date_of_birth,
            "created_at": p.created_at,
            "tests_count": len(rec.test_assignments) if rec else 0,
            "sessions_count": len(rec.sessions) if rec else 0,
        })

    return templates.TemplateResponse(
        request=request,
        name="therapist/dashboard.html",
        context={
            "user": user,
            "therapist": profile,
            "patients": patients_list,
        },
    )


@router.get("/patients/new", response_class=HTMLResponse, summary="Nuovo Paziente")
def new_patient_page(
    request: Request,
    user: User = Depends(require_therapist),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="therapist/patient_new.html",
        context={"user": user, "error_msg": None},
    )


@router.post("/patients/new", summary="Creazione Paziente con Cifratura Applicativa")
def create_patient(
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    date_of_birth: Optional[str] = Form(None),
    tax_id: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    gdpr_clinical: bool = Form(False),
    gdpr_research: bool = Form(False),
    user: User = Depends(require_therapist),
    db: Session = Depends(get_db),
) -> Response:
    profile = get_therapist_profile(user, db)

    # Parsing data di nascita
    dob_parsed = None
    if date_of_birth:
        try:
            dob_parsed = datetime.strptime(date_of_birth, "%Y-%m-%d").date()
        except ValueError:
            pass

    # CIFRATURA APPLICATIVA IMMEDIATA DEI DATI SENSIBILI
    enc_first = encryption_service.encrypt_text(first_name.strip())
    enc_last = encryption_service.encrypt_text(last_name.strip())
    enc_cf = encryption_service.encrypt_text(tax_id.strip().upper()) if tax_id else None
    enc_email = encryption_service.encrypt_text(email.strip()) if email else None
    enc_phone = encryption_service.encrypt_text(phone.strip()) if phone else None

    # 1. Creazione Identità Anagrafica Separata (PII)
    patient = PatientIdentity(
        therapist_id=profile.id,
        encrypted_first_name=enc_first,
        encrypted_last_name=enc_last,
        encrypted_tax_id=enc_cf,
        encrypted_email=enc_email,
        encrypted_phone=enc_phone,
        date_of_birth=dob_parsed,
        gdpr_clinical_consent=gdpr_clinical,
        gdpr_research_consent=gdpr_research,
    )
    db.add(patient)
    db.flush()

    # 2. Creazione Cartella Clinica Pseudonimizzata
    pseudo_code = generate_pseudonym_code("PR")
    clinical_rec = ClinicalRecord(
        patient_id=patient.id,
        therapist_id=profile.id,
        pseudonym_code=pseudo_code,
    )
    db.add(clinical_rec)

    # 3. Tracciamento Consensi GDPR
    now = datetime.now(timezone.utc)
    db.add(ConsentRecord(
        patient_id=patient.id,
        purpose="CLINICAL_CARE",
        granted=gdpr_clinical,
        information_version="v1.0-SPC",
    ))
    if gdpr_research:
        db.add(ConsentRecord(
            patient_id=patient.id,
            purpose="RESEARCH_OBSERVATORY",
            granted=True,
            information_version="v1.0-SPC",
        ))

    db.commit()
    return RedirectResponse(url=f"/therapist/patients/{patient.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/patients/{patient_id}", response_class=HTMLResponse, summary="Cartella Clinica Paziente")
def patient_detail(
    patient_id: str,
    request: Request,
    invited_token: Optional[str] = None,
    user: User = Depends(require_therapist),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    profile = get_therapist_profile(user, db)

    patient = db.query(PatientIdentity).filter(
        PatientIdentity.id == patient_id,
        PatientIdentity.therapist_id == profile.id,
    ).first()

    if not patient:
        raise HTTPException(status_code=404, detail="Paziente non trovato o accesso non autorizzato.")

    clinical_rec = db.query(ClinicalRecord).filter(ClinicalRecord.patient_id == patient.id).first()
    tests_catalog = db.query(TestDefinition).filter(TestDefinition.is_active == True).all()

    # Decodifica anagrafica autorizzata
    patient_data = {
        "id": patient.id,
        "first_name": encryption_service.decrypt_text(patient.encrypted_first_name),
        "last_name": encryption_service.decrypt_text(patient.encrypted_last_name),
        "pseudonym_code": clinical_rec.pseudonym_code,
        "date_of_birth": patient.date_of_birth,
        "gdpr_clinical": patient.gdpr_clinical_consent,
        "gdpr_research": patient.gdpr_research_consent,
    }

    # Assegnazioni test
    assignments_list = []
    for a in clinical_rec.test_assignments:
        assignments_list.append({
            "id": a.id,
            "test_title": a.test_definition.title,
            "test_code": a.test_definition.code,
            "status": a.status.value,
            "created_at": a.created_at,
            "completed_at": a.completed_at,
            "has_score": a.score is not None,
        })

    # Sedute e Trascrizioni
    sessions_list = []
    for s in clinical_rec.sessions:
        decrypted_trans = ""
        if s.encrypted_transcript:
            decrypted_trans = encryption_service.decrypt_text(s.encrypted_transcript)
        sessions_list.append({
            "id": s.id,
            "session_number": s.session_number,
            "session_date": s.session_date,
            "original_filename": s.original_filename,
            "transcript_preview": decrypted_trans[:200] + "..." if len(decrypted_trans) > 200 else decrypted_trans,
        })

    # Analisi Cliniche Salvate
    analyses_list = []
    for an in clinical_rec.clinical_analyses:
        analyses_list.append({
            "id": an.id,
            "analysis_type": an.analysis_type,
            "prompt_version": an.prompt_version,
            "model_name": an.model_name,
            "created_at": an.created_at,
            "result_text": encryption_service.decrypt_text(an.encrypted_result),
        })

    # Preparazione eventuale messaggio di invito generato
    invite_url = None
    whatsapp_url = None
    if invited_token:
        # Costruisce URL sicuro per il paziente (es. http://127.0.0.1:8000/p/{token})
        base_url = str(request.base_url).rstrip("/")
        invite_url = f"{base_url}/p/{invited_token}"
        wa_message = (
            f"Gentile paziente, per la compilazione dei questionari clinici concordati, "
            f"può accedere tramite questo link sicuro: {invite_url}"
        )
        whatsapp_url = f"https://wa.me/?text={quote(wa_message)}"

    # Pulsanti di Analisi Clinica Dinamici (Configurati dall'Amministratore)
    clinical_buttons = db.query(ClinicalAnalysisButton).filter(
        ClinicalAnalysisButton.is_active == True
    ).order_by(ClinicalAnalysisButton.display_order.asc()).all()

    # Modelli LLM selezionabili dal terapeuta
    available_models = [
        {"id": "", "name": "⚡ Predefinito di Sistema (Configurato dall'Amministratore)"},
        {"id": "gemini-1.5-pro", "name": "Google Gemini 1.5 Pro (Formulazione Complessa)"},
        {"id": "gemini-1.5-flash", "name": "Google Gemini 1.5 Flash (Veloce)"},
        {"id": "gpt-4o", "name": "OpenAI GPT-4o (Avanzato Multimodale)"},
        {"id": "gpt-4o-mini", "name": "OpenAI GPT-4o-mini (Standard Rapido)"},
        {"id": "claude-3-5-sonnet-20241022", "name": "Anthropic Claude 3.5 Sonnet (Accuratezza Clinica)"},
        {"id": "mistral-large-latest", "name": "Mistral AI / Endpoint Europeo"},
        {"id": "cbt-spc-offline", "name": "Motore Clinico Euristico Locale (Offline CBT-SPC)"},
    ]

    return templates.TemplateResponse(
        request=request,
        name="therapist/patient_detail.html",
        context={
            "user": user,
            "therapist": profile,
            "patient": patient_data,
            "clinical_record": clinical_rec,
            "assignments": assignments_list,
            "sessions": sessions_list,
            "analyses": analyses_list,
            "tests_catalog": tests_catalog,
            "clinical_buttons": clinical_buttons,
            "available_models": available_models,
            "invited_token": invited_token,
            "invite_url": invite_url,
            "whatsapp_url": whatsapp_url,
        },
    )


@router.post("/patients/{patient_id}/assign-test", summary="Assegnazione Questionario e Generazione Token")
def assign_test(
    patient_id: str,
    test_id: str = Form(...),
    days_valid: int = Form(7),
    user: User = Depends(require_therapist),
    db: Session = Depends(get_db),
) -> Response:
    profile = get_therapist_profile(user, db)
    patient = db.query(PatientIdentity).filter(
        PatientIdentity.id == patient_id,
        PatientIdentity.therapist_id == profile.id,
    ).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Paziente non trovato.")

    clinical_rec = db.query(ClinicalRecord).filter(ClinicalRecord.patient_id == patient.id).first()
    test_def = db.query(TestDefinition).filter(TestDefinition.id == test_id).first()
    if not test_def:
        raise HTTPException(status_code=404, detail="Test non trovato.")

    # Genera token casuale robusto e il suo hash SHA-256
    raw_token = generate_secure_token(16)
    token_h = hash_token(raw_token)
    expires = datetime.now(timezone.utc) + timedelta(days=days_valid)

    assignment = TestAssignment(
        clinical_record_id=clinical_rec.id,
        test_definition_id=test_def.id,
        access_token_hash=token_h,
        status=TestStatus.PENDING,
        expires_at=expires,
        definition_snapshot=test_def.items_schema,
    )
    db.add(assignment)
    db.commit()

    # Reindirizza mostrando il token appena generato
    return RedirectResponse(
        url=f"/therapist/patients/{patient.id}?invited_token={raw_token}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/patients/{patient_id}/sessions/new", summary="Caricamento Trascrizione Seduta")
async def add_session(
    patient_id: str,
    session_number: int = Form(...),
    session_date: str = Form(...),
    transcript_text: Optional[str] = Form(None),
    transcript_file: Optional[UploadFile] = File(None),
    user: User = Depends(require_therapist),
    db: Session = Depends(get_db),
) -> Response:
    profile = get_therapist_profile(user, db)
    patient = db.query(PatientIdentity).filter(
        PatientIdentity.id == patient_id,
        PatientIdentity.therapist_id == profile.id,
    ).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Paziente non trovato.")

    clinical_rec = db.query(ClinicalRecord).filter(ClinicalRecord.patient_id == patient.id).first()

    extracted = transcript_text or ""
    filename = None
    if transcript_file and transcript_file.filename:
        filename = transcript_file.filename
        content_bytes = await transcript_file.read()
        extracted_from_file = extract_text_from_file(filename, content_bytes)
        extracted = (extracted + "\n\n" + extracted_from_file).strip()

    # Cifratura applicativa del testo estratto
    enc_transcript = encryption_service.encrypt_text(extracted) if extracted else None
    s_date = datetime.strptime(session_date, "%Y-%m-%d").date()

    session_rec = TherapySession(
        clinical_record_id=clinical_rec.id,
        session_number=session_number,
        session_date=s_date,
        original_filename=filename,
        encrypted_transcript=enc_transcript,
    )
    db.add(session_rec)
    db.commit()

    return RedirectResponse(url=f"/therapist/patients/{patient.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/patients/{patient_id}/analyze", summary="Esecuzione Analisi Clinica o Formulazione del Caso")
def run_clinical_analysis(
    patient_id: str,
    analysis_type: str = Form(...),
    custom_instructions: Optional[str] = Form(None),
    llm_model: Optional[str] = Form(None),
    user: User = Depends(require_therapist),
    db: Session = Depends(get_db),
) -> Response:
    profile = get_therapist_profile(user, db)
    patient = db.query(PatientIdentity).filter(
        PatientIdentity.id == patient_id,
        PatientIdentity.therapist_id == profile.id,
    ).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Paziente non trovato.")

    clinical_rec = db.query(ClinicalRecord).filter(ClinicalRecord.patient_id == patient.id).first()

    # Raccoglie il contesto clinico autorizzato (sedute e punteggi test)
    context_parts = [f"Cartella Pseudonimo: {clinical_rec.pseudonym_code}"]

    # Trascrizioni sedute
    for s in clinical_rec.sessions:
        if s.encrypted_transcript:
            trans = encryption_service.decrypt_text(s.encrypted_transcript)
            context_parts.append(f"--- Seduta n. {s.session_number} ({s.session_date}) ---\n{trans[:1500]}")

    # Risultati test completati
    for a in clinical_rec.test_assignments:
        if a.status == TestStatus.COMPLETED and a.score:
            context_parts.append(
                f"--- Test {a.test_definition.title} ---\n"
                f"Punteggi: {a.score.raw_scores}\n"
                f"Sintesi: {a.score.interpretation_summary}"
            )

    full_context = "\n\n".join(context_parts)
    # Cerca la configurazione del pulsante personalizzato dall'amministratore
    button_config = db.query(ClinicalAnalysisButton).filter(
        ClinicalAnalysisButton.name == analysis_type
    ).first()

    prompt_ver = button_config.version if button_config else "1.0-SPC"
    if custom_instructions and custom_instructions.strip():
        sys_prompt = custom_instructions.strip()
    elif button_config and button_config.system_prompt:
        sys_prompt = button_config.system_prompt
    else:
        sys_prompt = (
            "Sei un assistente per psicoterapeuti cognitivisti esperti (SPC/APC). "
            "Analizza il materiale secondo il modello cognitivista standard."
        )

    # Recupera i documenti scientifici e manuali associati per RAG
    scientific_docs = db.query(ScientificDocument).all()
    reference_texts = []
    for doc in scientific_docs:
        reference_texts.append(f"{doc.title}:\n{doc.extracted_text[:1200]}")
    if not reference_texts:
        reference_texts = ["Manuale Cognitivo SPC - Modello di Formulazione del Caso Clinico"]

    chosen_model = llm_model if llm_model and llm_model.strip() else None
    ai_provider = get_ai_provider(model_name=chosen_model, db=db)
    analysis_result = ai_provider.generate_clinical_analysis(
        analysis_type=analysis_type,
        system_prompt=sys_prompt,
        clinical_context=full_context,
        reference_documents=reference_texts,
    )

    # Salvataggio cifrato dell'analisi
    enc_result = encryption_service.encrypt_text(analysis_result)
    analysis_record = ClinicalAnalysis(
        clinical_record_id=clinical_rec.id,
        analysis_type=analysis_type,
        prompt_version=prompt_ver,
        model_name=getattr(ai_provider, "model_name", "Heuristic-CBT-SPC"),
        encrypted_result=enc_result,
    )
    db.add(analysis_record)
    db.commit()

    return RedirectResponse(url=f"/therapist/patients/{patient.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/results/{assignment_id}", response_class=HTMLResponse, summary="Dettaglio Punteggio e Report Clinico")
def view_test_result(
    assignment_id: str,
    request: Request,
    user: User = Depends(require_therapist),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    profile = get_therapist_profile(user, db)
    assignment = db.query(TestAssignment).filter(TestAssignment.id == assignment_id).first()
    if not assignment or not assignment.score:
        raise HTTPException(status_code=404, detail="Risultato non trovato o test non ancora completato.")

    # Controllo appartenenza cartella clinica
    if assignment.clinical_record.therapist_id != profile.id and user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Accesso non autorizzato a questa cartella.")

    score = assignment.score
    response_data = assignment.response.raw_answers if assignment.response else {}

    # Genera report interpretativo clinico con il provider AI
    ai_provider = get_ai_provider()
    clinical_interpretation = ai_provider.generate_clinical_analysis(
        analysis_type=f"Interpretazione Psicometrica {assignment.test_definition.code}",
        system_prompt="Analizza i punteggi psicometrici calcolati deterministicamente in relazione ai cut-off normativi.",
        clinical_context=f"Test: {assignment.test_definition.title}\nPunteggi: {score.raw_scores}\nCut-off: {score.interpretation_summary}",
        reference_documents=[f"Manuale Ufficiale di Scoring {assignment.test_definition.code}"],
    )

    return templates.TemplateResponse(
        request=request,
        name="therapist/result_detail.html",
        context={
            "user": user,
            "therapist": profile,
            "assignment": assignment,
            "score": score,
            "answers": response_data,
            "clinical_interpretation": clinical_interpretation,
        },
    )
