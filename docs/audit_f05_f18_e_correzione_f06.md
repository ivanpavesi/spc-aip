# AIP — Riesame F05–F18 e correzione circoscritta F06

Data: **22 ottobre 2026**. Repository: **ivanpavesi/spc-aip**.

## Esito e provenienza dell'audit

L'audit originale è stato recuperato dalla chat Codex **«Esegui audit sicurezza AIP Platform»**, ID `01a15f85-0f18-734b-ac70-5cd7528da040`. Esaminava il commit `aad391484f4367937027813ffd9ac4c30dc1d8b9`. Le sigle e le gravità riportate sotto sono quelle originali; lo stato attuale deriva da una nuova lettura del codice e da verifiche locali con dati sintetici.

Il confronto è stato effettuato con `origin/main`, aggiornato da GitHub e verificato al commit **`2804040663690fb2fda5f0e9255be5a3a1d79635`**. Il ramo della correzione è `security/f06-enforce-ai-provider-policy`.

**È corretto il bypass della scelta amministrativa del provider AI, parte di F06. F06 nel suo complesso resta parzialmente aperta**, perché comprende anche minimizzazione dei dati, controllo degli endpoint e governance dei fornitori. Non vengono dichiarate risolte le altre vulnerabilità.

Nessun merge, deploy, intervento su Render/Supabase, cambiamento della 2FA o del recupero account. Nessun provider AI reale chiamato, nessun servizio a pagamento e nessun dato clinico reale utilizzato.

## Inventario verificato sul main di riferimento

I numeri di riga di questa tabella si riferiscono al **main di riferimento**, non alle posizioni eventualmente spostate dalla PR. Il dettaglio dei percorsi rende possibile ricontrollare ogni conclusione. «Presente» indica evidenza nel codice o in un test locale; non indica una compromissione della produzione.

| ID e gravità originale | Problema, impatto e stato su main | File coinvolti e punti di verifica |
|---|---|---|
| **F05 — Alta** | **Presente, con mitigazione parziale F04.** Risposte agli item, punteggi, classificazioni e dataset di ricerca sono JSON in chiaro; anche data di nascita, metadati delle sedute e API key restano leggibili tramite SQL. Un dump logico espone questi contenuti senza la chiave Fernet. F04 cifra i nuovi segreti TOTP, ma il lettore accetta ancora il formato legacy: non si può più affermare che tutti i segreti TOTP siano in chiaro. | `app/db/models/test_engine.py:180,213,218,223`; `app/db/models/research.py:90`; `app/db/models/patient.py:62`; `app/db/models/clinical.py` (`TherapySession`); `app/routers/admin.py:747`; `app/routers/auth.py:188`; `app/core/security.py:116`. |
| **F06 — Alta** | **Presente.** Le trascrizioni decifrate possono contenere nomi nel testo libero. La selezione del modello può cambiare il provider nonostante `AI_PROVIDER=HEURISTIC_OFFLINE`, se una chiave è disponibile. L'endpoint custom accetta destinazioni HTTP/interne senza controlli specifici: il possibile abuso di richieste server verso servizi interni richiede il controllo della configurazione amministrativa e non è stato sfruttato. | `app/routers/therapist.py:380,404,442`; `app/services/ai/provider.py:381`; `app/routers/admin.py:747`. |
| **F07 — Alta per integrità clinica** | **Presente.** Il provider locale restituisce testi clinici predefiniti che non dipendono dal caso. Contesti sintetici diversi producono lo stesso report. Su main anche alcuni errori di configurazione provocano questo fallback: un testo dimostrativo può essere scambiato per una valutazione del paziente. | `app/services/ai/provider.py:302,381`; `app/routers/therapist.py:445,485`. |
| **F08 — Alta per affidabilità clinica** | **Presente la semplificazione; validità da verificare.** BDI-II usa etichette tematiche e opzioni generiche; STAI-Y1 contiene item duplicati/incompleti, incluso «Mi sento piacevolmente». Punteggi aritmeticamente corretti non dimostrano equivalenza allo strumento clinico dichiarato. | `app/services/scoring/engine.py:171,232`; `app/db/seeds.py` (catalogo); `app/templates/patient/questionnaire.html`. |
| **F09 — Alta** | **Presente.** Il solo ruolo ricercatore dà accesso globale: mancano appartenenze agli studi. Dashboard ed export non filtrano per consenso verificato o studio attivo; non ricontrollano revoche. CSV ed Excel di un record sintetico senza consenso verificato, appartenente a studio inattivo, restituiscono 200. Pseudonimo, date e piccoli gruppi favoriscono la reidentificazione. Il perimetro autorizzativo desiderato deve essere formalizzato. | `app/routers/researcher.py:26,74,123`; `app/routers/patient.py:206`; `app/db/models/research.py`; `app/db/models/patient.py:96`; `app/templates/researcher/dashboard.html`. |
| **F10 — Medio-alta** | **Presente.** File letti per intero e parser nello stesso processo web, senza limiti applicativi adeguati a byte, pagine, espansione DOCX, testo estratto o durata. Possibile saturazione di memoria/CPU, particolarmente rilevante su Render Free. Verificata solo estrazione innocua di TXT sintetico da 2 MiB, senza provocare esaurimento delle risorse. | `app/routers/therapist.py:358`; `app/routers/admin.py:843`; `app/services/documents.py:10`. |
| **F11 — Media** | **Presente fuori dai flussi MFA.** F04 aggiunge protezioni CSRF alle operazioni MFA, non a tutti i form. Un POST amministrativo sintetico con `Origin` estranea e senza token CSRF crea un utente. La prova HTTP non dimostra da sola un attacco completo nel browser: `SameSite=Lax` mitiga molti POST fra siti, ma non tutte le situazioni. | `app/routers/admin.py:106,747`; `app/routers/auth.py`; `app/core/mfa.py` (`same_origin`, protezione limitata a MFA); `app/templates/admin/dashboard.html`; `app/main.py:36`. |
| **F12 — Media** | **Presente, con mitigazione parziale F04.** Password di tre caratteri ancora ammesse. Mancano limiti generali per il login con password, controllo password compromesse e scadenza per inattività; sessioni di sette giorni. F04 limita i tentativi MFA, senza risolvere il guessing delle password. | `app/core/security.py:47`; `app/routers/auth.py:64`; `app/core/auth.py:14`; `app/core/mfa.py` (`attempt`). |
| **F13 — Media** | **Presente, riprodotta.** Il GET controlla `expires_at`; il POST controlla solo lo stato `PENDING`. Un token già scaduto, mai aperto con GET, consente ancora l'invio: HTTP 200 e stato `COMPLETED`. Può alterare la raccolta dei dati dopo il termine autorizzato. | `app/routers/patient.py:75,103,120`; `app/db/models/test_engine.py:123`. |
| **F14 — Medio-alta per integrità** | **Presente, riprodotta.** Lo snapshot conserva gli item, ma lo scoring usa le regole correnti del catalogo. Modificare `total_items` dopo l'assegnazione cambia il totale di 21 risposte pari a uno da 21 a 1. Il risultato perde riproducibilità clinica. | `app/routers/therapist.py:322`; `app/routers/patient.py:137`; `app/routers/admin.py:509`; `app/db/models/test_engine.py:135`. |
| **F15 — Media** | **Presente, con miglioramenti F04.** Ora esistono eventi MFA; mancano ancora audit sistematici degli accessi clinici, degli invii ai provider e delle compilazioni. La prova di invio non genera audit. Il logging SQL in sviluppo può includere parametri sensibili; l'immutabilità dei log non è garantita dal modello applicativo. Questo ostacola la ricostruzione degli accessi abusivi. | `app/core/mfa.py:16`; `app/routers/auth.py`; `app/routers/admin.py:36`; `app/routers/researcher.py:105`; `app/routers/patient.py`; `app/routers/therapist.py`; `app/db/session.py:12`; `app/db/models/audit.py`. |
| **F16 — Media** | **Presente.** Token nei percorsi e nella query string possono finire in cronologia e access log. Mancano `Cache-Control: no-store`, CSP e validazione applicativa degli host; gli inviti dipendono da `request.base_url`. Le pagine cliniche caricano JavaScript di terzi, fra cui Tailwind non versionato e senza SRI. F03 ha corretto l'iniezione nel pulsante, non queste esposizioni. | `app/routers/therapist.py:242,328`; `app/templates/base.html:9`; `app/main.py:36`; `app/routers/patient.py`. |
| **F17 — Media, con rischio operativo alto** | **Parzialmente mitigata, ancora aperta.** F01/F02 proteggono meglio bootstrap e configurazione produttiva; F04 aggiunge una migrazione effettiva. Tuttavia la migrazione amministrativa storica è ancora vuota e il processo web usa `create_all()`/seed. Container root, strumenti di compilazione, dipendenze/base image non bloccate e assenza di prove di ripristino restano problemi. Il DB dichiarato a `f04a1` non prova che la catena storica ricostruisca da sola tutte le tabelle amministrative. | `alembic/versions/84d60c0c67b2_add_admin_config_tables.py:21`; `alembic/versions/f04a1_secure_totp_lifecycle.py`; `app/db/session.py:50`; `app/core/config.py`; `Dockerfile`; `requirements.txt`; `pyproject.toml`; `render.yaml`. |
| **F18 — Media** | **Presente.** Il ramo del risultato di un altro terapeuta usa `UserRole.ADMIN` senza importarlo: riprodotto `NameError`, senza esposizione del risultato. Eccezioni DB possono comparire nelle risposte di salvataggio e health check; quest'ultimo mantiene `status=ok` anche con DB guasto. La pagina 500 afferma senza evidenza che nessun dato è compromesso. | `app/routers/therapist.py:478`; `app/routers/patient.py:240`; `app/routers/public.py:53`; `app/main.py:79`. |

Per consultare il codice esatto di main: [albero del commit verificato](https://github.com/ivanpavesi/spc-aip/tree/2804040663690fb2fda5f0e9255be5a3a1d79635). Questi rilievi non attribuiscono CVE specifiche e non verificano le protezioni infrastrutturali effettive.

## Perché intervenire prima sul bypass F06

La cifratura protegge un dato mentre è archiviato; per elaborarlo l'applicazione deve decifrarlo. **Decidere a chi inviare il testo decifrato è quindi un controllo di accesso ai dati**, non una preferenza grafica.

Su main un normale terapeuta può inviare `llm_model=gpt-4o`: il server deduce OpenAI dal nome e scavalca la modalità offline. Basta che la chiave sia già presente nel DB o nell'ambiente. La verifica ha usato un client fittizio: non prova che in produzione esistano chiavi o siano avvenuti trasferimenti.

Questo è l'intervento più urgente scelto per questa PR perché riguarda l'uscita di trascrizioni potenzialmente identificative, richiede privilegi ordinari e può essere corretto senza una migrazione ampia. **F09 e F05 restano sullo stesso livello alto di attenzione**: F09 consente letture/esportazioni eccessive agli utenti di ricerca; F05 espone dati e segreti in caso di lettura logica del DB. L'ordine operativo proposto non riduce le loro gravità originali.

## Correzione implementata e comportamento atteso

- Nuovo modulo `app/services/ai/policy.py`: legge la configurazione e risolve provider/modello, senza chiamare SDK o rete. La policy è condivisa fra selettore HTML e POST, senza duplicare le decisioni nei due punti.
- `AI_PROVIDER` determina il destinatario. Non si ricava più dal prefisso del modello inviato nel form. Sono ammessi i modelli del catalogo di quel provider e il modello espressamente configurato dall'amministratore, inclusi alias custom. Non si abilita un fornitore solo perché esiste la sua chiave.
- Il POST autorizza prima la cartella del terapeuta, poi il destinatario AI, **prima di decifrare le trascrizioni**. Modello incompatibile: 403, nessuna istanza esterna, nessuna analisi salvata.
- Configurazione illeggibile/sconosciuta, chiave assente, temperatura non valida o inizializzazione fallita: errore controllato 503, senza fallback a un report locale. Con configurazione AI invalida anche il selettore nella cartella risponde 503: occorre correggere la configurazione amministrativa. Questa limitazione è intenzionale e documentata.
- Il selettore del terapeuta mostra solo le scelte compatibili. Una pagina aperta prima di un cambio del provider viene ricontrollata al successivo POST.
- Il test di connessione amministrativo ha un ingresso separato, protetto da `require_admin`: può provare un altro provider con il messaggio tecnico esistente, senza contesto clinico e senza cambiare `AI_PROVIDER`.
- Le chiamate alla factory senza DB restano esclusivamente locali. Il dettaglio del risultato psicometrico continua a usare questo percorso: questa PR non introduce nuovi trasferimenti remoti nei GET.

Esempi comprensibili:

| Configurazione | Richiesta del terapeuta | Risultato dopo la correzione |
|---|---|---|
| Offline, anche con API key presenti | `gpt-4o` | Rifiuto 403 prima della decifratura. |
| Offline | Predefinito oppure `cbt-spc-offline` | Percorso locale esistente. |
| OpenAI abilitato | `gpt-4o-mini` | Solo il client OpenAI autorizzato. |
| OpenAI abilitato | Modello Gemini, custom o sconosciuto | Rifiuto 403. |
| Provider esterno abilitato ma senza chiave/client valido | Predefinito | Errore 503; nessun report locale sostitutivo. |

**Migrazioni DB: nessuna.** Non cambiano modelli SQLAlchemy, tabelle, colonne o revisione Alembic: resta `f04a1`. Si leggono impostazioni già esistenti. Non occorrono nuovi segreti, risorse cloud o acquisti.

Il rollback del solo codice è tecnicamente possibile perché lo schema resta identico, ma riaprirebbe il bypass e quindi richiederebbe una decisione esplicita in una successiva attività autorizzata.

## Verifiche e risultati

Tutti i test usano identità, trascrizioni, chiavi e punteggi sintetici. Gli SDK esterni sono sostituiti nei nuovi test. I dati applicativi di test sono in SQLite in memoria; i casi F04 già esistenti usano anche SQLite temporaneo e PostgreSQL 16 in un container locale su loopback, con schemi casuali eliminati al termine.

| Verifica | Risultato |
|---|---|
| Suite iniziale su main, prima della correzione | 130 passati, 1 fallito per Chromium non trovato nel percorso predefinito di Playwright, 8 saltati per PostgreSQL di test non configurato. |
| Nuova regressione sul codice vulnerabile | Fallimento atteso: il POST restituisce 303 invece di 403, confermando il bypass con provider fittizio. |
| Regressioni dedicate F06 | **53 passate**: matrice di selezioni fra tutti i provider, nomi sconosciuti, modello amministrativo, chiavi ambientali, errori DB/SDK, blocco prima della decifratura, selettore, modifica della policy, test amministrativo separato e isolamento fra terapeuti. |
| Suite completa con Chromium e PostgreSQL locale | **192 passati, 0 falliti, 0 errori, 0 saltati**: 139 casi esistenti e 53 nuovi. Include browser F03 e migrazioni/concorrenza MFA su SQLite/PostgreSQL. |
| Probe aggiuntivi temporanei del riesame | **8 passati**: confermano difetti residui F05, minimizzazione F06, F07, F09, F10, F11, F12, F13/F14/F15/F18. In questi probe «passato» significa difetto ancora presente, non risolto. |
| Dipendenze installate | `python -m pip check`: nessuna dipendenza incompatibile; non equivale a scansione CVE. |
| Controllo patch | `git diff --check`: nessun errore. |

Il controllo F06 autorizzato verifica il passaggio del solo testo sintetico al client fittizio e la cifratura del risultato salvato. I percorsi esistenti di login/ruoli, amministrazione, creazione paziente, assegnazione, compilazione, scoring, ricerca, upload, analisi locale e MFA sono coperti dalla suite. Non sono state provate credenziali o disponibilità di provider reali, né effettuate verifiche sulla produzione.

Riproduzione della suite completa in un ambiente locale di test con Docker, Chromium, Node/Playwright e dipendenze Python già disponibili:

```sh
docker run --name aip-f06-postgres \
  -e POSTGRES_USER=aip_test -e POSTGRES_PASSWORD=synthetic-f06-password \
  -e POSTGRES_DB=aip_f06_test -p 127.0.0.1:55406:5432 -d postgres:16-alpine
# Attendere che pg_isready confermi la disponibilità del DB locale.
CHROMIUM_PATH=/usr/bin/chromium \
F04_TEST_POSTGRES_URL=postgresql+psycopg2://aip_test:synthetic-f06-password@127.0.0.1:55406/aip_f06_test \
.venv/bin/python -m pytest -q -o faulthandler_timeout=30 --junitxml=/tmp/aip-f06-regression.xml
docker rm -f aip-f06-postgres
```

Le credenziali sopra sono esclusivamente dimostrative per il container locale. Non usare URL di produzione. I report XML della sessione sono `/tmp/aip-f06-regression.xml` e `/tmp/aip-f06-audit/probes.xml`; i probe separati sono in `/tmp/aip-f06-audit/test_remaining_findings.py`, non nella suite versionata, perché verificano intenzionalmente comportamenti ancora vulnerabili.

## Limiti rimasti, inclusa la parte non corretta di F06

La selezione amministrativa ora è vincolante, ma **un provider autorizzato riceve ancora il testo libero non redatto**. Un nome sintetico è rimasto nel payload di una prova con client fittizio. Restano da definire minimizzazione/redazione, autorizzazioni per organizzazione e finalità, tracciamento dei trasferimenti, criteri degli endpoint custom, eventuali richieste verso rete interna e contratti/retention/localizzazione dei fornitori. Una scelta nell'interfaccia non dimostra da sola l'idoneità giuridica del destinatario.

Resta F07 quando si sceglie esplicitamente il provider locale: i report sono ancora dimostrativi e predefiniti. La rimozione del fallback implicito riduce un percorso del problema, ma non ne completa la soluzione. Anche F08 necessita di validazione clinica indipendente e verifica delle licenze, oltre ai test software.

I test automatici dimostrano i comportamenti osservati; non certificano sicurezza complessiva, conformità GDPR o raggiungimento OWASP ASVS Level 2.

## Roadmap proposta, non implementata nella PR

Le priorità sotto sono una proposta attuale, distinta dalle gravità storiche dell'inventario.

| Priorità | Intervento successivo | Criterio pratico di completamento |
|---|---|---|
| **P0, prima di dati reali** | **F09**: permessi espliciti per studio/finalità, controllo di studio attivo e ammissibilità dei dati a ogni dashboard/export, gestione revoche; separare privilegi tecnici e clinici. | Utente di uno studio non vede né esporta dati di un altro; record non ammissibili esclusi anche dopo revoca. Definire prima il modello autorizzativo atteso. |
| **P0, prima di dati reali** | **F05**: inventario dei campi, cifratura autenticata di risposte/punteggi/contenuti clinici, protezione delle API key, ciclo delle chiavi e migrazione dei valori legacy. | Un dump logico sintetico non contiene i contenuti da proteggere; migrazione e rollback provati. Non cifrare alla cieca i campi che servono per filtri e relazioni. |
| **P0, prima di invii reali** | Completare **F06**: minimizzazione, destinatari approvati, policy endpoint custom, governance fornitori e audit degli invii. | Test negativi di destinazione e payload; decisione di policy e destinatario ricostruibili senza registrare la trascrizione nei log. |
| **P0, prima di impiego clinico** | **F07/F08**: distinguere dimostrazione da elaborazione clinica; validare strumenti, soglie e licenze. | Nessun report predefinito presentato come valutazione del caso; versioni approvate dai responsabili clinici. |
| **P1** | **F13/F14**: scadenza nel POST, transazioni concorrenti, versioni immutabili di item/regole/norme. | Token scaduti respinti; stessa assegnazione produce gli stessi punteggi anche dopo aggiornamenti del catalogo. |
| **P1** | **F11/F12/F10**: CSRF generale, limiti login/password/sessioni, quote upload e parsing isolato. | Richieste prive di autorizzazione d'origine respinte; abuso limitato con test sintetici e soglie misurabili. MFA e recupero account restano fuori dagli interventi finché non saranno autorizzati. |
| **P1** | **F15/F16/F18**: audit minimo completo, errori pubblici generici, cache/log dei token, asset locali/CSP/origine canonica. | Accessi e trasferimenti ricostruibili; pagine cliniche non conservate in cache e dettagli DB non esposti. |
| **P2** | **F17**: ricostruzione completa delle migrazioni, niente DDL dal web, identità DB separate, container non root, lock dipendenze e prove di ripristino. | Installazione da zero e aggiornamento da schema precedente riproducibili; ripristino provato con dati sintetici. |

## Modularizzazione: mantenere un monolite con confini chiari

Non serve introdurre ora microservizi o servizi a pagamento. Il primo confine, introdotto qui, separa **policy di selezione AI** e **adapter dei provider**. Le successive PR dovrebbero estrarre un modulo alla volta, mantenendo API e test dei flussi esistenti.

1. **Autorizzazioni e ricerca:** un servizio applicativo unico per le decisioni su cartella/studio/finalità; query già limitate ai dati consentiti, senza filtri ripetuti nei router.
2. **Protezione dei dati e segreti:** servizio di cifratura tipizzato, classificazione dei campi e gestione versionata delle chiavi; conservare associazioni e indici tecnici senza esporre il contenuto clinico.
3. **Questionari e scoring:** definizioni immutabili e versionate, norme e provenienza dei risultati; separare il calcolo deterministico dalla spiegazione generata.
4. **Gateway AI interno:** unico percorso per autorizzazione, minimizzazione, selezione destinatario, prompt/fonti versionati, quote, timeout e revisione professionale del risultato. «Gateway» qui significa un modulo interno, non un nuovo servizio commerciale.
5. **Documenti e lavori lunghi:** isolare parsing ed elaborazioni con limiti di risorse; introdurre un worker soltanto quando il carico lo richiede.
6. **Audit e operatività:** eventi minimizzati comuni ai moduli, identificatori di correlazione, migrazioni affidabili e monitoraggio degli errori.

L'obiettivo è poter aggiungere un nuovo strumento clinico o provider senza replicare controlli di accesso, cifratura e regole nei router. Ogni modulo deve avere responsabilità esplicite e test sui suoi confini, oltre al percorso completo utente → autorizzazioni → dati → risultato.
