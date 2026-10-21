# Scuole di Psicoterapia Cognitiva (SPC / APC)
## Artificial Intelligence Platform (AIP) — Manuale Completo

Piattaforma web professionale per la valutazione psicometrica deterministica, la gestione delle cartelle cliniche, la somministrazione di questionari, l'interpretazione clinica assistita da AI e l'analisi di dati di ricerca pseudonimizzati.

L'architettura è rigorosamente **Python-first**: semplice da comprendere, mantenere ed estendere per un terapeuta o ricercatore che apprende Python.

---

## 1. Organizzazione del Progetto

```text
aip/
├── app/
│   ├── main.py                  # Entry point FastAPI, middleware di sicurezza, registrazione router
│   ├── core/
│   │   ├── config.py            # Impostazioni d'ambiente tipizzate (.env)
│   │   ├── security.py          # Hashing PBKDF2/SHA-256, codici pseudonimi e TOTP
│   │   └── auth.py              # Gestione sessioni HttpOnly, dipendenze RBAC per ruoli
│   ├── db/
│   │   ├── base.py              # DeclarativeBase SQLAlchemy 2 e TimestampMixin
│   │   ├── session.py           # Gestione connessioni al database (PostgreSQL Supabase / SQLite dev)
│   │   ├── seeds.py             # Inizializzazione automatica test (BDI-II, STAI-Y1) e account demo
│   │   └── models/              # Modelli del database conformi a Privacy by Design (GDPR)
│   │       ├── user.py          # User, AuthSession e Therapist
│   │       ├── patient.py       # PatientIdentity (PII cifrata con Fernet) e ConsentRecord
│   │       ├── clinical.py      # ClinicalRecord (pseudonimizzata PR-XXXX), TherapySession, ClinicalAnalysis
│   │       ├── test_engine.py   # TestDefinition, TestAssignment, TestResponse, TestScore
│   │       ├── research.py      # ResearchStudy e ResearchDataset (minimizzati per la ricerca)
│   │       └── audit.py         # AuditEvent (tracciamento accessi ed esportazioni senza dati sanitari)
│   ├── schemas/                 # Validazione dati Pydantic (user, patient, clinical)
│   ├── routers/
│   │   ├── public.py            # Homepage (/), verifica codice paziente (/patient/verify), /health
│   │   ├── auth.py              # Login per operatori, setup 2FA (TOTP) e logout
│   │   ├── therapist.py         # Gestione pazienti, assegnazione test, WhatsApp invite, sedute, AI
│   │   ├── patient.py           # Compilazione questionari online (/p/{token}) e invio risposte
│   │   ├── researcher.py        # Statistiche descrittive con Pandas, export CSV ed Excel
│   │   └── admin.py             # Governance catalogo test, utenze e audit trail
│   ├── services/
│   │   ├── encryption.py        # Crittografia applicativa Fernet/MultiFernet per campi sanitari
│   │   ├── documents.py         # Estrazione testo da trascrizioni (.txt, .docx, .pdf)
│   │   ├── scoring/
│   │   │   └── engine.py        # Motore psicometrico deterministico (BDI-II, STAI-Y1, cut-off, sottoscale)
│   │   └── ai/
│   │       └── provider.py      # Architettura AI modulare (Gemini e Heuristic Clinical CBT offline)
│   ├── templates/               # Pagine web HTML con Jinja2, TailwindCSS e HTMX
│   └── static/                  # Stili custom e logo istituzionale SPC/APC
├── alembic/                     # Migrazioni controllate del database
├── tests/                       # Suite di 26 test automatici con Pytest (100% superati)
├── docs/                        # Documentazione architetturale dettagliata
├── .env.example                 # Modello configurazione documentato in italiano
├── pyproject.toml               # Configurazione dipendenze e pytest
└── README.md                    # Questo manuale operativo
```

---

## 2. Come avviare la piattaforma su Windows

### Prerequisiti
- Python 3.11+ installato su Windows.
- PowerShell.

### Avvio Rapido

1. **Apri PowerShell** ed entra nella cartella `aip`:
   ```powershell
   cd d:\AI_Platform_Test\aip
   ```

2. **Avvia il server**:
   ```powershell
   .\.venv\Scripts\uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
   ```

3. **Apri il browser su**: [http://127.0.0.1:8000](http://127.0.0.1:8000)

---

## 3. Account Dimostrativi Preconfigurati (Sviluppo Locale)

Soltanto con `ENVIRONMENT=development` o `testing`, all'avvio il database crea i seguenti account dimostrativi **se mancanti**. Password, ruoli, stato e profili esistenti non vengono ripristinati. In produzione il bootstrap mantiene catalogo e configurazioni applicative, senza creare o modificare gli account demo:

| Ruolo | Username / Email | Password | Accesso Diretto |
|---|---|---|---|
| **Amministratore** | `admin` *(o `admin@spc.it`)* | `admin` | [Accedi come Amministratore](http://127.0.0.1:8000/auth/login?role=ADMIN) |
| **Terapeuta** | `terapeuta` *(o `terapeuta@spc.it`)* | `terapeuta` | [Accedi come Terapeuta](http://127.0.0.1:8000/auth/login?role=THERAPIST) |
| **Ricercatore** | `ricercatore` *(o `ricercatore@spc.it`)* | `ricercatore` | [Accedi come Ricercatore](http://127.0.0.1:8000/auth/login?role=RESEARCHER) |

> 💡 **Nota di usabilità:** Nella schermata di login è presente un box **"Credenziali di Prova Rapide (1-Click)"** che permette di compilare automaticamente i campi con un solo tocco! Inoltre puoi inserire direttamente `admin`, `terapeuta` o `ricercatore` nel campo username senza digitare `@spc.it`.

---

### Configurazione delle chiavi e avvio produttivo

`APP_ENCRYPTION_KEY` deve essere impostata esplicitamente in ogni ambiente: non esiste più una chiave Fernet di fallback. Per un **nuovo database di sviluppo**, generarla una sola volta con `Fernet.generate_key()` e conservarla nel proprio `.env` escluso da Git. La suite di test usa chiavi effimere e database isolati.

Con `ENVIRONMENT=production`, la configurazione blocca l'avvio prima dell'accesso al database se `APP_SECRET_KEY` manca, è dimostrativa/prevedibile, ha meno di 32 caratteri o coincide con la chiave Fernet; anche `APP_ENCRYPTION_KEY` deve essere valida, canonica e diversa dai valori pubblicati nel vecchio codice/template. I database SQLite dimostrativi `aip_dev.db` e in memoria sono riservati a sviluppo/test. Impostare esplicitamente l'ambiente corretto: il default resta `development` per lo sviluppo locale.

**Database esistenti:** conservare le chiavi correnti. Se una chiave in uso viene rifiutata, questa modifica richiede di fermare il rilascio: non sostituirla per superare il controllo. Servono un piano separato di compatibilità, backup verificato, migrazione e ripristino prima di qualsiasi rotazione. Il codice non ruota chiavi né migra ciphertext. Gli eventuali account demo già presenti in produzione richiedono una verifica e una bonifica manuale autorizzata; questo intervento non ne cambia le credenziali.

Per dettagli, verifiche e limiti vedere [il rapporto F01/F02](docs/sicurezza_f01_f02.md).

---

## 4. Flusso Operativo Completo

### A. Percorso Terapeuta
1. Accedi con `terapeuta@spc.it`.
2. Dalla Dashboard clicca su **Nuovo Paziente**:
   - Inserisci nome, cognome, data di nascita e codice fiscale.
   - I dati anagrafici vengono **immediatamente cifrati** con Fernet.
   - Viene generata una cartella clinica con codice pseudonimo casuale (es. `PR-7A8B9C0D`).
3. Dalla scheda paziente:
   - Seleziona un questionario (es. *Beck Depression Inventory - II*) e clicca **Assegna e Genera Invito**.
   - Il sistema genera un codice casuale e ti mostra il **Link Invito** e il pulsante **Invia invito via WhatsApp** precompilato.
4. Sezione **Sedute e Trascrizioni**:
   - Puoi registrare una nuova seduta caricando file `.txt`, `.docx` o `.pdf` (il testo estratto viene cifrato nel database).
5. Sezione **Analisi Clinica e Formulazione del Caso (AI)**:
   - Clicca sui pulsanti di analisi preconfigurati (*Formulazione del Caso*, *Analisi ABC*, *Scopi e Antiscopi*, ecc.) o scrivi una richiesta libera nel prompt per ricevere un report clinico strutturato.

### B. Percorso Paziente
1. Il paziente riceve il link (es. `http://127.0.0.1:8000/p/<token>`) oppure inserisce il codice nella homepage nella card **Accesso Paziente**.
2. Compila il questionario interattivo responsive.
3. Clicca su **Invia definitivamente le risposte**.
4. Il sistema esegue lo **scoring deterministico Python**, calcola punteggi e cut-off clinici, aggiorna lo stato a `COMPLETED` e blocca ulteriori invii (idempotenza).
5. Se il paziente ha espresso il consenso alla ricerca, alimenta automaticamente l'osservatorio pseudonimizzato.

### C. Percorso Ricercatore
1. Accedi con `ricercatore@spc.it`.
2. Visualizza la tabella delle **Statistiche Descrittive Aggregate** (N campioni, Media, Deviazione Standard, Mediana, Min e Max per ciascun test) calcolate con Pandas e NumPy.
3. Scarica i dataset pseudonimizzati cliccando su **Esporta CSV** o **Esporta Excel** (l'operazione viene registrata nel registro di audit).

### D. Percorso Amministratore (Governance di Sistema)
1. Accedi con `admin` (password: `admin`).
2. **Scheda "Utenze & Ruoli"**:
   - Creazione rapida di nuovi utenti (`THERAPIST`, `RESEARCHER`, `ADMIN`) con profilo professionale automatico.
   - Modifica del ruolo tramite selettore immediato.
   - Reset della password dell'utente e revoca immediata delle sessioni aperte.
   - Reset del secondo fattore 2FA (TOTP) in caso di smarrimento del dispositivo dell'operatore.
   - Attivazione e disattivazione dell'account con blocco accessi.
3. **Scheda "Catalogo Questionari"**:
   - Creazione guidata di nuovi strumenti psicometrici (`/admin/tests/new`) con schema JSON degli item e formule di scoring deterministico.
   - Modifica di test esistenti, aggiornamento cut-off normativi e subscale (`/admin/tests/{id}`).
   - Associazione di manuali e guide di scoring in formato PDF/DOCX/TXT.
4. **Scheda "Pulsanti Analisi Clinica (SPC/APC)"**:
   - Personalizzazione dei pulsanti clinici rapidi mostrati nella cartella del paziente.
   - Modifica in-line dei prompt di sistema (orientati a formulazione del caso, analisi ABC, scopi/antiscopi, circoli di mantenimento, cicli interpersonali).
   - Abilitazione, disabilitazione e ordinamento delle elaborazioni disponibili per i terapeuti.
5. **Scheda "Configurazione AI & Modelli" (Architettura Multi-LLM)**:
   - Configurazione multi-provider: Google Gemini, OpenAI (GPT-4o, o3-mini), Anthropic Claude (Claude 3.5 Sonnet/Haiku), Mistral AI / Endpoint Europeo / Ollama Locale e Motore Euristico Locale (Offline CBT-SPC).
   - Inserimento e aggiornamento sicuro delle chiavi API e modelli per ciascun provider.
   - Regolazione della temperatura di campionamento e preambolo deontologico istituzionale.
   - Diagnostica live con pulsanti di test connessione individuali per ogni provider.
6. **Scheda "Manuali & Documenti RAG"**:
   - Caricamento di manuali clinici, linee guida e articoli scientifici (.pdf, .docx, .txt).
   - Estrazione ed indicizzazione automatica del testo per arricchire il contesto delle formulazioni AI.
7. **Scheda "Audit Trail"**:
   - Ispezione cronologica di tutti gli eventi di sicurezza, accessi e modifiche di configurazione.

---

## 5. Esecuzione dei Test Automatici

La suite completa di 33 test verifica tutti i moduli e l'integrazione end-to-end:

```powershell
cd d:\AI_Platform_Test\aip
.\.venv\Scripts\pytest -v
```

**Esito:** 33 passed su 33 test (100% success rate).

---

## 6. Riservatezza dei Dati Sanitari (GDPR)

1. **Separazione Anagrafica / Clinica**: L'anagrafica (`PatientIdentity`) è archiviata in modo indipendente dalla cartella clinica (`ClinicalRecord`), collegata solo per la ricerca tramite codice pseudonimo `PR-XXXX`.
2. **Crittografia Applicativa**: I campi nominativi, codice fiscale, trascrizioni delle sedute e referti AI sono cifrati con Fernet (`app/services/encryption.py`). Nessun dato sanitario viene memorizzato in chiaro.
3. **Token Hash**: I token dei pazienti sono memorizzati solo tramite hash SHA-256 nel database.
4. **Scoring Deterministico**: Nessun modello di intelligenza artificiale calcola punteggi numerici. I calcoli matematici sono eseguiti esclusivamente da funzioni Python testate e riproducibili.
5. **Audit Trail**: Le esportazioni dei dati e gli accessi sono tracciati senza registrare contenuti sanitari o diagnosi.
