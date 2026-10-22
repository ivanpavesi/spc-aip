# Rapporto tecnico — F04: ciclo di vita dell'autenticazione TOTP

Data: 22 ottobre 2026. Repository: `ivanpavesi/spc-aip`.
Base verificata con connettore GitHub e `git fetch origin main`: `e52e9e29c633c1496e0d7a403175453003ff4a22`, merge della PR #2; comprende anche la PR #1 (F01/F02).
Ramo: `fix/f04-secure-totp`. Destinazione: `main`.

L'attività riguarda esclusivamente F04. Non costituisce una valutazione complessiva della sicurezza di AIP né una certificazione ASVS Level 2. Nessun accesso a Render, Supabase o dati di produzione; nessun merge o deploy. Credenziali, chiavi, ruoli, fattori e sessioni online non sono stati letti o modificati. Tutte le prove utilizzano dati sintetici e chiavi effimere di test.

## 1. Vulnerabilità confermate

| Evidenza nella versione di partenza | Conseguenza |
| --- | --- |
| `get_current_user_optional` carica l'utente senza controllare `AuthSession.mfa_verified`. | Le sessioni create prima dell'attivazione mantengono accesso alle risorse protette senza il secondo fattore. |
| `GET /auth/totp/setup` genera e salva un segreto se assente e passa sempre quello dell'utente al template. | Un GET modifica lo stato; anche dopo l'attivazione è possibile visualizzare nuovamente il fattore già attivo. |
| `verify_totp_code` esegue soltanto una verifica PyOTP con tolleranza ±1 intervallo, senza consumo persistente. | Lo stesso codice può autenticare più volte, anche tramite richieste concorrenti e processi diversi; la finestra di accettazione supera 30 secondi. |
| Login condizionato da `totp_enabled and totp_secret`. | Un account con flag attivo e segreto assente salta completamente la verifica, creando persino una sessione marcata come verificata. |
| Attivazione senza nuova password, enrollment senza scadenza e reset amministrativo senza ulteriore autenticazione. | Una sessione sottratta può associare o rimuovere un fattore. Il precedente reset ha un evento di audit, ma non verifica di nuovo l'identità dell'amministratore, non revoca le sessioni del destinatario e lascia l'accesso con sola password. |

Queste conclusioni derivano dall'esame del codice e da test locali; non da tentativi sull'installazione online.

## 2. Soluzione e motivazioni tecniche

### Enrollment e sostituzione

1. Il GET mostra lo stato e il modulo. Non genera, modifica o restituisce segreti, inclusi quelli legacy abbandonati.
2. Il POST di avvio richiede password attuale, sessione valida e token CSRF legato al cookie. Controlla anche `Origin` e `Sec-Fetch-Site` quando presenti. Se il fattore è già attivo, richiede e consuma un nuovo codice del fattore attuale.
3. Genera un nuovo seed Base32 tramite PyOTP/CSPRNG (32 caratteri, 160 bit) e lo conserva cifrato nei campi provvisori della sola sessione. La password è appena verificata; la conferma deve avvenire entro **cinque minuti** e nella medesima sessione.
4. Ruota il token di sessione dopo la reautenticazione. Il nuovo seed compare soltanto nella risposta di avvio, con `Cache-Control: no-store` e `Pragma: no-cache`. Nessun segreto viene inserito in URL o script. GET successivi ed errori non lo ristampano. Per rivedere una chiave provvisoria persa occorre iniziare una nuova procedura autenticata.
5. Il POST di conferma verifica il codice del nuovo seed, attiva il fattore e registra il contatore già consumato. Incrementa la versione MFA e revoca tutte le vecchie sessioni del solo account interessato. Crea una nuova sessione con cookie ruotato, versione corrente e `mfa_verified=True`.
6. In caso di sostituzione, il fattore precedente rimane attivo fino al completamento della conferma. Nessun passaggio intermedio lascia l'account privo di MFA.

Il segreto del fattore attivo non viene mai esposto dai percorsi di configurazione. Nella sostituzione viene mostrato esclusivamente il **nuovo** seed ancora provvisorio.

### Verifica, consumo e concorrenza

- Codici accettati: esattamente sei cifre ASCII. Il server usa esclusivamente il proprio orologio, con intervallo di **30 secondi**; nessuna accettazione degli intervalli precedente o successivo. Il telefono e l'host devono avere l'ora sincronizzata.
- `totp_last_counter` è persistente: un codice è accettato solo se il suo contatore supera quello già consumato. Il controllo e la scrittura sono un `UPDATE` condizionale sul database, senza mutex in memoria.
- Login, avvio/conferma enrollment e reset acquisiscono un lock tramite aggiornamento condizionale dell'utente. La condizione verifica versione MFA, password hash e stato attivo, poi rilegge l'account. Un login iniziato prima della modifica del fattore riceve un conflitto anziché creare una sessione basata sul vecchio stato. Il reset può interessare anche un destinatario disattivato, senza riattivarlo.
- Il lock dura fino al commit. Consumo, versione, revoca/creazione sessioni ed eventi di successo condividono la transazione. Un rollback prima della creazione della sessione annulla anche il consumo del codice.
- Un budget per account limita gli errori MFA e di reautenticazione: cinque tentativi falliti provocano un blocco di cinque minuti. Stato e blocco sono persistenti e condivisi tra processi. Un codice corretto al quinto tentativo azzera il budget senza lasciare un blocco residuo.
- Errori, replay, blocchi, configurazioni incoerenti, avvio, attivazione, verifiche e recuperi vengono registrati tramite `AuditEvent`. I metadati contengono identificativi tecnici e, dove disponibile, IP; mai password, seed, codici OTP o cookie.

### Autorizzazione delle sessioni e configurazioni incomplete

Ogni risorsa che usa le dependency di autenticazione esistenti controlla ora la versione MFA. Per un account con TOTP attivo richiede anche un segreto leggibile/valido e `mfa_verified=True`.

`totp_required` parte da `false` per tutti gli account esistenti. Diventa `true` soltanto dopo attivazione o reset esplicito di quell'account. Se il fattore è richiesto ma non ancora configurato, il login con password produce una sessione limitata alla configurazione e al logout; dashboard e funzionalità riservate restituiscono 401. Il redirect verso la configurazione **non** attribuisce accesso alle risorse applicative.

Un account con `totp_enabled=True` ma seed assente, malformato o non decifrabile viene rifiutato al login e alle risorse protette, anche se una sessione afferma che MFA è verificata. Il recupero richiede il percorso amministrativo o quello riservato all'operatore server.

### Reset amministrativo e recupero dell'unico amministratore

Il reset HTTP richiede:

- amministratore attivo con propria MFA configurata e sessione verificata;
- conferma attuale della password e **nuovo** OTP dell'amministratore;
- CSRF valido e conferma esplicita di verifica indipendente dell'identità del destinatario;
- destinatario diverso dall'attore.

Il reset elimina il fattore del destinatario, cancella contatore e stato provvisorio tramite revoca delle sessioni, incrementa la versione e impone un nuovo enrollment prima dell'accesso. Registra attore, destinatario e conferma del canale indipendente. Ruota anche il cookie dell'amministratore che ha effettuato la reautenticazione; le altre sessioni dell'amministratore non sono revocate. Un amministratore senza MFA continua ad accedere normalmente, ma deve configurarla prima di resettare i fattori altrui.

Per la perdita del fattore dell'unico amministratore esiste `python -m app.cli.recover_totp`: **nessun endpoint HTTP**. È destinato a un operatore già autorizzato alla shell e al database. Richiede UUID confermato interattivamente, password attuale tramite `getpass` e riferimento tecnico a un ticket approvato. Ammette soltanto amministratori attivi. Il recupero registra l'evento `MFA_OPERATOR_RECOVERY`, revoca le sessioni del solo account e impone subito un nuovo enrollment. Non cambia password, ruolo, stato attivo o chiavi.

Il possesso di una sessione web non consente di invocare il comando. La verifica d'identità e l'approvazione del ticket sono controlli operativi: il software registra la conferma/riferimento, ma non verifica il contenuto del ticket né l'identità reale della persona.

### Riferimento ad ASVS 5.0

Testo di riferimento: [release ufficiale v5.0.0](https://github.com/OWASP/ASVS/tree/v5.0.0/5.0/en), capitoli V6, V7 e V16.

| Requisito pertinente | Risposta nell'intervento F04 |
| --- | --- |
| 6.3.4, percorsi di autenticazione coerenti e documentati | Login, enrollment limitato, reset web e recupero server descritti qui; gate MFA applicato alle dependency condivise. |
| 6.4.4, verifica d'identità nel recupero | Nuova autenticazione dell'amministratore, conferma di canale indipendente; per il recupero server, identità e ticket approvato da verificare operativamente. |
| 6.5.1, uso singolo | Contatore persistente, aggiornamento condizionale, prove concorrenti su due database. |
| 6.5.3, generazione imprevedibile | Seed nuovi tramite CSPRNG; nessuna sostituzione automatica dei seed legacy. |
| 6.5.5, durata massima TOTP 30 secondi | Accettazione del solo intervallo corrente; test esplicito dei confini temporali. |
| 7.2.4 e 7.5.1, rotazione e reautenticazione | Rotazione token dopo reautenticazione e attivazione; password e, quando già attivo, secondo fattore prima di modificare MFA. |
| 7.4.1 e 7.4.3, cessazione e revoca sessioni | Revoca delle sessioni precedenti del destinatario con controllo aggiuntivo della versione. |
| V16, audit del ciclo MFA | Eventi nel sistema di audit già esistente, senza credenziali o segreti. Non è stata valutata la protezione/inoltro dell'intera infrastruttura di logging. |

**Deroga controllata a 6.3.3:** ASVS Level 2 richiede MFA per accedere all'applicazione. Per il vincolo esplicito di continuità degli account già online, questa PR non la impone globalmente e non pretende conformità integrale L2. La mitigazione transitoria consiste in opt-in verificato, gate effettivo per chi ha MFA attiva, obbligo di nuova configurazione dopo reset e MFA richiesta per i reset amministrativi web. Serve un successivo piano approvato, con inventario account, recupero collaudato e scadenze di enrollment, per completare il rollout obbligatorio. La sola PR F04 non soddisfa quella parte dell'obiettivo L2.

## 3. File e migrazione

| File | Intervento |
| --- | --- |
| `app/core/auth.py` | Gate MFA/versione, dependency esclusiva per enrollment limitato, rotazione e cookie condiviso. |
| `app/core/security.py` | Validazione del formato, contatore RFC 6238, durata 30 secondi, lettura sicura di seed legacy e cifrati. |
| `app/core/mfa.py` | Transazioni, consumo persistente, budget tentativi, CSRF, audit e revoca mirata. |
| `app/routers/auth.py` | Login fail-closed, avvio autenticato, conferma con scadenza e attivazione atomica. |
| `app/routers/admin.py` | Pagina di conferma e reset protetto con audit e nuovo enrollment obbligatorio. |
| `app/db/models/user.py` | Stato persistente MFA e seed nuovi cifrati in campo `Text`. |
| `app/templates/auth/totp_setup.html` | Nuova password, fattore attuale per sostituzione, visualizzazione singola del nuovo seed e conferma. |
| `app/templates/admin/totp_reset.html` | Conferma identità e credenziali dell'amministratore. |
| `app/templates/admin/dashboard.html`, `app/templates/base.html` | Accesso al reset protetto e alla sicurezza del proprio account. |
| `app/cli/__init__.py`, `app/cli/recover_totp.py` | Recupero amministratore riservato alla shell. |
| `alembic/env.py` | Connessione iniettata per verificare migrazioni in schemi di test isolati. |
| `alembic/versions/f04a1_secure_totp_lifecycle.py` | Migrazione esplicita da `84d60c0c67b2` a `f04a1`. |
| `tests/conftest.py` | Orologio TOTP deterministico, senza congelare le scadenze di sessioni/enrollment. |
| `tests/test_auth_and_roles.py`, `tests/test_admin.py` | Aggiornamento delle precedenti aspettative insicure al nuovo flusso. |
| `tests/test_totp_security.py`, `tests/test_totp_databases.py` | Regressioni di sicurezza, migrazioni e transazioni concorrenti. |
| `docs/sicurezza_f04.md` | Questo rapporto e le procedure operative. |

La migrazione aggiunge `mfa_version`, `totp_required`, `totp_last_counter`, `mfa_failures`, `mfa_locked_until` a `users`; aggiunge versione, seed provvisorio cifrato e data di verifica password a `auth_sessions`. Valori iniziali: versione zero per utenti/sessioni, MFA non obbligatoria, nessun contatore o blocco preesistente. Non esegue backfill di credenziali, segreti o sessioni.

Su PostgreSQL amplia `users.totp_secret` da `VARCHAR(64)` a `TEXT`, mantenendo i valori. SQLite non applica il limite dichiarato di VARCHAR: non viene ricostruita la tabella con foreign key. I nuovi seed hanno prefisso `enc:` e sono cifrati tramite l'attuale `APP_ENCRYPTION_KEY`; i vecchi Base32 continuano a funzionare senza conversione automatica.

Il downgrade è verificato in assenza di seed F04 attivi; se ne trova, si interrompe **prima** di perdere dati o tornare a un codice incapace di leggerli. Dopo la prima attivazione F04 non è sicuro tornare al vecchio codice. Non decifrare e riscrivere i seed per forzare un rollback.

## 4. Test ed esiti

Ambiente di test: Python 3.12.14, SQLite 3.53.1, SQLAlchemy 2.1.6, PyOTP 2.10.0, FastAPI 0.158.0, pytest 9.1.1, PostgreSQL 16 in container effimero con database `aip_f04_test`, fuso PostgreSQL `Europe/Rome` e schemi casuali per test. Browser F03: Playwright 1.62.1, Chromium 154.0.8037.57. Nessuna connessione a un database non locale è ammessa dal fixture PostgreSQL. Le prove HTTP hanno sessioni/connessioni indipendenti dove richiesto dalla concorrenza.

| Verifica | Esito finale |
| --- | --- |
| `F04_TEST_POSTGRES_URL=… CHROMIUM_PATH=/usr/bin/chromium .venv/bin/python -m pytest -q -o faulthandler_timeout=30 --junitxml=/tmp/aip-f04-regression.xml` | **139 passed**, **0 failed**, **0 errors**, **0 skipped**. |
| F01/F02: `test_bootstrap_security.py`, `test_production_config.py` (incluse nella suite completa) | **9 + 43 passed**. |
| F03: `test_invitation_links.py` (incluso browser isolato) | **9 passed**, inclusi i 15 scenari Chromium del relativo harness. |
| F04: `test_totp_security.py` | **28 passed**. |
| F04: `test_totp_databases.py` | **16 passed**: otto casi SQLite e otto casi PostgreSQL, nessuno saltato. |
| `.venv/bin/python -m pip check` | Nessuna dipendenza incompatibile. |
| `python -m compileall -q app alembic`, `node --check` sui due script F03 | Sintassi valida. |
| `git diff --check` | Nessun errore di whitespace. |

Non restano test saltati o non eseguibili nel perimetro locale della suite. I collaudi sulla configurazione reale di Render/Supabase e su altri browser non sono stati eseguiti, per i vincoli dell'attività; restano verifiche operative prima del rilascio, non test dichiarati superati.

Copertura aggiunta:

- attivazione, cifratura del nuovo seed, conferma con codice corretto e accesso successivo;
- password errata, assenza/errore CSRF, origine ostile, OTP errati o con formato non valido;
- seed non recuperabile da GET prima/dopo attivazione, né dagli errori; nessuna mutazione di stato attraverso GET;
- enrollment legato alla sessione, password verificata da meno di cinque minuti, rifiuto di conferme scadute;
- rotazione cookie, revoca delle altre sessioni del destinatario, rifiuto di `mfa_verified=False` e di versioni obsolete;
- configurazioni attive senza seed o con seed corrotto; account con MFA richiesta e configurazione incompleta;
- compatibilità degli account senza MFA e dei fattori Base32 legacy;
- sostituzione con verifica del vecchio fattore, mantenuto fino alla conferma del nuovo;
- codice monouso nel login, nell'attivazione e nelle successive verifiche; scadenza esatta di 30 secondi;
- rate limit persistente, scadenza del blocco, successo al quinto tentativo senza blocco residuo;
- reset web, rifiuto di utenti non admin, di admin senza MFA, di self-reset e di verifiche insufficienti;
- recupero server con password/ticket, rifiuto non-admin, nuova configurazione e ritorno all'accesso amministrativo;
- migrazione da schema precedente con snapshot di credenziali/ruoli/seed/sessioni invariati, downgrade/upgrade e blocco del downgrade distruttivo;
- due login HTTP concorrenti con lo stesso codice: un solo successo e una sola sessione;
- due conferme enrollment concorrenti: una sola attivazione;
- snapshot di login obsoleto dopo cambio fattore, rollback del consumo in caso di mancato commit della sessione;
- flusso HTTP completo su schema migrato SQLite e PostgreSQL: enrollment, login cifrato, recupero e nuovo enrollment;
- scadenza dell'enrollment corretta anche con timestamp PostgreSQL non UTC.

Le migrazioni storiche non creano tutte le tabelle non autenticative presenti nei modelli. I test del flusso completo riproducono anche il `create_all` già eseguito dal normale avvio per le sole tabelle assenti, senza nascondere o sostituire le modifiche di schema F04, che sono applicate da Alembic. Questo disallineamento storico non è stato corretto fuori perimetro.

Durante lo sviluppo, la prima esecuzione estesa ha rilevato un errore nel nuovo harness: avviare contemporaneamente il lifespan di più TestClient faceva riutilizzare il motore SQLite globale; il runtime ha subito un segmentation fault. Il fixture ora separa la costruzione dello schema dall'avvio dei client concorrenti e usa soltanto le connessioni isolate dei test. Altre prove intermedie hanno guidato l'aggiornamento dei vecchi test, la gestione dei cookie di test e l'orologio deterministico. Gli esiti finali riportati sopra riguardano l'esecuzione completata dopo le correzioni.

### Riproducibilità

Installare le dipendenze Python del repository e gli strumenti browser indicati nel rapporto F03. Avviare un PostgreSQL locale di test, per esempio:

```sh
docker run -d --name aip-f04-postgres \
  -e POSTGRES_USER=aip_test -e POSTGRES_PASSWORD=synthetic-f04-password \
  -e POSTGRES_DB=aip_f04_test -p 127.0.0.1:55404:5432 postgres:16-alpine
F04_TEST_POSTGRES_URL=postgresql+psycopg2://aip_test:synthetic-f04-password@127.0.0.1:55404/aip_f04_test \
CHROMIUM_PATH=/usr/bin/chromium \
  .venv/bin/python -m pytest -q -o faulthandler_timeout=30
```

Le credenziali nell'esempio sono esclusivamente sintetiche per il container locale. Senza `F04_TEST_POSTGRES_URL` i casi PostgreSQL sono esplicitamente **skipped**, non passati. Senza Node/Playwright il browser F03 è esplicitamente **skipped**; occorre installarlo per riprodurre la verifica completa. Al termine eliminare il container di test con `docker rm -f aip-f04-postgres`. Nessuna dipendenza applicativa è stata aggiunta.

## 5. Rischi residui e limiti

- La MFA non è obbligatoria per tutti: la deroga a 6.3.3 è esplicita e richiede un piano successivo. Il reset web richiede invece MFA all'attore.
- I seed legacy rimangono nel formato precedente finché il titolare non sostituisce volontariamente il fattore. La PR evita una conversione massiva che dipenderebbe dalle condizioni del database online e dalla disponibilità della chiave. I nuovi seed sono cifrati; è essenziale conservare la chiave corrente e il suo backup autorizzato.
- Il recupero server si affida alla sicurezza degli accessi infrastrutturali, alla password e alla verifica d'identità/ticket. Chi controlla server e database ha privilegi superiori all'applicazione. Il comando non è un'alternativa remota a MFA e non consente recupero se è persa anche la password: quello richiede una procedura distinta, fuori F04.
- Il rate limit per account riduce i tentativi sui codici, ma può essere usato per provocare un blocco temporaneo da chi conosce la password. Non sostituisce una difesa generale da credential stuffing, né una valutazione dell'intera politica password/sessioni.
- La rimozione della tolleranza temporale richiede ora corretta su host e dispositivo. Un codice in scadenza va rigenerato; un codice già usato non può autenticare una seconda scheda o autorizzare un reset nello stesso intervallo.
- Le revoche si applicano alle richieste successive al commit. Una richiesta già autorizzata e in esecuzione non viene interrotta retroattivamente.
- I seed provvisori scaduti restano cifrati nella sessione fino a nuova configurazione, revoca o eliminazione della sessione; non sono riutilizzabili dopo cinque minuti. La pulizia periodica delle sessioni storiche non è stata introdotta qui.
- La migrazione richiede DDL sul database e un lock per l'ampliamento della colonna PostgreSQL. Durata su volumi reali, privilegi e comportamento operativo di Render/Supabase non sono stati misurati. Usare staging e una finestra controllata; nessun deploy online è stato provato.
- Recupero, audit e schema non rendono sicura l'intera piattaforma: CSP/CDN, protezione infrastrutturale del logging, altre vulnerabilità e policy globali rimangono fuori da questa attività.

## 6. Impatto sugli utenti già esistenti

| Stato prima della PR | Dopo migrazione e nuovo codice |
| --- | --- |
| Admin/operatore senza MFA | Password, ruolo, stato e sessioni restano validi. Nessun obbligo globale. Può iniziare volontariamente l'enrollment. |
| MFA attiva e coerente, sessione verificata | Accesso conservato; seed e app esistenti compatibili. Nuovi login richiedono OTP corrente non già consumato. |
| MFA attiva, sessione non verificata | Nessun accesso alle risorse protette; occorre un nuovo login con password e OTP. È la correzione della sessione pre-attivazione. |
| Flag attivo ma seed assente/corrotto | Accesso rifiutato; recupero controllato prima di riprendere l'utilizzo. Verificare questi casi prima del rilascio. |
| Configurazione legacy mai completata | GET non la espone. Il titolare verifica la password e avvia una nuova procedura; nessuna attivazione automatica. |
| Reset esplicito del fattore | Revocate solo le sessioni del destinatario; accesso limitato al nuovo enrollment finché non completato. |
| Account demo disattivati | Nessuna riattivazione o modifica di credenziali. Comportamento F01 preservato. |

Il default zero delle versioni evita una revoca indiscriminata al deploy. Non eseguire modifiche massime ai flag o alle sessioni come preparazione della migrazione.

## 7. Procedura controllata per merge e aggiornamento Render

Questi passaggi sono destinati all'operatore autorizzato **dopo revisione della PR**. Non sono stati eseguiti sulla produzione.

1. **Impedire un deploy involontario:** sospendere l'auto-deploy da `main` prima del merge. La configurazione Render attuale avvia Uvicorn senza migrazioni: `create_all` non aggiunge colonne alle tabelle esistenti. Non distribuire prima il nuovo codice.
2. Predisporre staging PostgreSQL separato con dati sintetici e chiavi di staging. Eseguire la suite completa e provare enrollment, secondo login, reset e comando di recupero. Verificare NTP/ora del telefono, corretto HTTPS/proxy e cookie `Secure` sulla reale configurazione di staging.
3. Verificare un backup e il ripristino del database, oltre alla disponibilità protetta delle **chiavi attuali** e della password amministrativa. Non rigenerare `APP_SECRET_KEY` o `APP_ENCRYPTION_KEY`. Verificare l'accesso alla shell e il ticket/processo d'identità necessari al recupero **prima** di attivare MFA sull'unico admin.
4. Con controlli in sola lettura svolti dall'operatore, inventariare gli admin attivi e lo stato MFA, senza stampare seed/password. Confermare almeno un admin con password nota e fattore coerente oppure senza MFA. Se l'unico admin ha MFA incoerente, o se non è verificabile il recupero, **sospendere il rilascio** e concordare il recupero assistito: non disattivare MFA né cancellare sessioni preventivamente.
5. Verificare `alembic current`, tabelle, colonne, tipi e vincoli del database. La revisione attesa è `84d60c0c67b2`. Se `alembic_version` manca perché l'installazione è nata con `create_all`, non eseguire alla cieca le migrazioni iniziali su tabelle esistenti. Confrontare lo schema con la revisione storica e con quello avviato da AIP; solo dopo verifica documentata l'operatore può applicare un `alembic stamp 84d60c0c67b2`, che registra metadati senza modificare account. Se esiste un'altra revisione o un disallineamento delle tabelle autenticative, fermarsi e preparare un adeguamento distinto.
6. Approvare e integrare la PR in una finestra concordata. Preparare l'artefatto F04 senza avviarlo contro lo schema precedente. Impedire modifiche di autenticazione durante il passaggio, drenare le richieste e attendere almeno 31 secondi senza vecchi worker attivi, perché i contatori dei codici consumati prima di F04 non sono ricostruibili; non lasciare worker vecchi e nuovi operativi contemporaneamente. Questa attività non effettua il merge.
7. Dall'artefatto F04 e dall'ambiente corretto, eseguire una sola volta `python -m alembic upgrade f04a1`, senza passare URL/chiavi in log o in ticket. Verificare `alembic current` e il risultato DDL. Non eseguire seed manuali, reset globali o conversioni dei fattori.
8. Avviare solo il codice F04 su Render con le configurazioni correnti. Verificare health check, login dell'admin già esistente con password personalizzata, accesso alle dashboard consentite e account demo ancora inattivi. Per admin senza MFA, verificare che non venga imposto un enrollment inatteso.
9. Attivare MFA sull'amministratore soltanto con la procedura del paragrafo seguente. Controllare audit, login con un nuovo codice, rifiuto del replay e revoca dei soli cookie precedenti dell'account usato nella prova.
10. Prima di qualsiasi attivazione F04, il downgrade a `84d60c0c67b2` è possibile previa verifica delle condizioni e test in staging. Dopo aver creato un fattore cifrato F04, mantenere il codice capace di leggerlo e applicare una correzione successiva: il downgrade viene deliberatamente bloccato. Un ripristino da backup è una decisione operativa separata, con valutazione dei dati intervenuti nel frattempo; non una procedura automatica.

Se gli strumenti disponibili nel piano Render non consentono di eseguire la migrazione prima dell'avvio, predisporre un job amministrativo controllato oppure un comando di pre-deploy verificato in staging, senza aggiungerlo alla cieca allo startup. Lasciare l'auto-deploy sospeso fino al completamento del passaggio e delle verifiche.

## 8. Attivazione sicura della 2FA dell'amministratore

1. Collaudare **prima** su un admin sintetico il comando di recupero e l'intero ritorno all'accesso. Confermare un canale disponibile per l'operatore infrastrutturale, la password attuale dell'admin e l'UUID corretto. Se non è disponibile una shell autorizzata o un altro admin verificato con MFA, rinviare l'attivazione: una seconda scheda non è una garanzia di recupero, perché le vecchie sessioni saranno revocate.
2. Accedere con l'account esistente e la sua password personalizzata. Non usare credenziali dimostrative, non cambiare password o ruoli, non riattivare gli altri account.
3. Aprire **Sicurezza account · 2FA**, confermare nuovamente la password e iniziare. Associare il nuovo seed a un'app con ora automatica. Se previsto dalla politica dell'organizzazione, predisporre in questo momento il backup cifrato del fattore in un archivio approvato e separato; non inserirlo in screenshot, email, ticket o log.
4. Confermare un codice corrente entro cinque minuti. Prima della conferma l'account conserva il comportamento precedente; in caso di errore/scadenza si può riavviare la procedura con password senza avere ancora attivato il nuovo fattore.
5. Dopo il successo, la sessione corrente viene sostituita da una verificata e le altre sessioni dell'account vengono revocate. Aprire la dashboard e controllare l'evento `MFA_ACTIVATED`.
6. Conservare la sessione appena verificata, attendere **il successivo codice di 30 secondi** e provare un secondo login in una finestra privata. Non riusare quello di attivazione. Verificare poi che un GET della configurazione non mostri il seed attivo. Solo dopo questo secondo login terminare la sessione usata per la configurazione.
7. Per una futura sostituzione, usare password e un nuovo codice del vecchio fattore. Non resettare preventivamente il fattore funzionante.

In caso di perdita dell'app, un altro amministratore già verificato può effettuare il reset protetto dopo verifica indipendente dell'identità. Se è l'unico admin, l'operatore autorizzato procede soltanto dopo approvazione del ticket e verifica d'identità tramite canale indipendente:

```sh
python -m app.cli.recover_totp --user-id UUID_CONFERMATO --ticket SEC-1234
```

Il comando chiede di digitare l'UUID e poi la password in un prompt nascosto. Non inserire password o seed negli argomenti della shell. Dopo il recupero, l'amministratore deve accedere con la password attuale e completare subito un nuovo enrollment; nessuna dashboard è autorizzata nel frattempo. Controllare l'evento `MFA_OPERATOR_RECOVERY` e la nuova attivazione. Se password, chiave o accesso infrastrutturale non sono disponibili, fermarsi e attivare il processo distinto di recupero dell'installazione, senza creare account demo o indebolire i controlli MFA.
