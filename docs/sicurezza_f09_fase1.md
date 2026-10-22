**AIP — F09, fase 1: contenimento dell’area ricerca**

Data: 22 ottobre 2026. Base: `main` a `86537f6905ef79a0b6c55760801239eff9c17049`, dopo la PR #4/F06.

**Esito e perimetro**

Il ruolo RESEARCHER consentiva dashboard ed export globali senza assegnazioni agli studi. Anche ADMIN passava il controllo. Il completamento di un questionario con consenso generico alla ricerca trasferiva il risultato al primo studio attivo, creandone uno generale se necessario. I percorsi di lettura non controllavano consenso corrente, revoche o ammissibilità del dataset.

Questa PR sospende tali percorsi nell’applicazione finché non esiste una fonte verificabile di autorizzazioni per operatore, studio e protocollo. **È un contenimento di F09, non la realizzazione del sistema definitivo né la chiusura della vulnerabilità sull’intera infrastruttura.** Non si presume che RLS protegga le connessioni applicative o la Data API.

Nessuna nuova tabella, colonna, migrazione, dipendenza o configurazione infrastrutturale. La revisione Alembic del codice resta `f04a1`. Nessuna modifica a credenziali, policy RLS, Supabase o Render; nessun merge o deploy effettuato. L’ispezione remota descritta sotto è stata soltanto in lettura sui metadati, senza leggere righe cliniche.

**Funzioni temporaneamente disabilitate**

| Percorso/funzione | Comportamento nella fase 1 |
|---|---|
| `GET /researcher/dashboard` | Dopo autenticazione valida, 403 con messaggio di sospensione e `Cache-Control: no-store`. Nessuna lettura di studi o dataset, nessun conteggio o aggregato. |
| `GET /researcher/export/csv` | 403 prima di leggere dati o costruire il file. Nessun allegato e nessun evento di export riuscito. |
| `GET /researcher/export/excel` | Identico blocco dell’export CSV. |
| Conferimento al completamento questionario | Eliminato il percorso implicito: nessun inserimento in `research_datasets`, indipendentemente dal consenso generico registrato. |
| Creazione/associazione automatica dello studio | Eliminata: nessun primo studio attivo e nessuno studio generale di ripiego. |

Il blocco vale anche per ADMIN e per eventuali account RESEARCHER già esistenti. Parametri come `study_id`, `authorized`, `consent_verified`, `role` o `user_id` non concedono accessi. Lo stato attivo dello studio e il vecchio `consent_verified=True` non costituiscono un’autorizzazione dell’operatore.

Senza sessione valida, con sessione scaduta, account inattivo o MFA non verificata rimane il rifiuto 401 dell’autenticazione esistente. Il login ricercatore continua a creare la sessione e a reindirizzare al proprio percorso, che mostra la risposta di sospensione. Non esiste un interruttore amministrativo o una variabile d’ambiente per riaprire gli export globali.

Il vecchio template della dashboard non è più raggiunto dal router. I dati legacy non vengono cancellati, aggiornati o riclassificati: non sono leggibili attraverso questi endpoint. File già scaricati e pagine conservate prima della correzione non sono recuperabili dal blocco.

**Funzioni mantenute e confini del codice**

Compilazione, risposte grezze, scoring, cut-off, stato COMPLETED, blocco del reinvio e consultazione dei risultati da parte del terapeuta restano nel percorso clinico. L’assenza di un’autorizzazione alla ricerca non impedisce di completare il questionario.

Creazione del paziente, registrazione dei flag di consenso esistenti, cartelle, sedute, gestione amministrativa, sessioni, MFA e policy dei provider F06 mantengono i loro percorsi. Il flag generico di ricerca rimane un dato storico dell’attuale modello; non viene interpretato come partecipazione a un protocollo o come dimostrazione della base giuridica GDPR.

- `app/services/research.py`: policy indipendente da FastAPI e dal database. L’identità autenticata non viene considerata un grant; in questa fase ogni richiesta è negata.
- `app/routers/researcher.py`: unico adapter HTTP condiviso dai tre percorsi; usa l’autenticazione esistente e traduce il diniego in 403. Eliminati query globali, aggregazioni e serializzazioni legacy.
- `app/routers/patient.py`: rimosso il solo conferimento implicito. Il commit delle risposte e dei punteggi clinici non coinvolge le tabelle ricerca.

Non si modifica `require_role` per gli altri router: l’assenza di un bypass amministrativo riguarda l’area ricerca e non limita la governance dell’applicazione.

**Verifica in sola lettura di Supabase e Render**

Il workspace Render è stato confermato dall’utente. Il servizio ispezionato corrisponde al repository `ivanpavesi/spc-aip`, ramo `main`. Nel momento dell’ispezione auto-deploy e preview delle PR risultavano disabilitati. Non sono stati letti log applicativi, modificati segreti o eseguiti comandi sul servizio.

Il connettore Render disponibile espone metadati del servizio, ma non la lettura delle variabili d’ambiente né una shell. L’ambiente di lavoro non dispone di una credenziale Render per un percorso alternativo. **Il ruolo effettivamente utilizzato da AIP su Render non è stato identificato con certezza.** L’utente ha confermato che anche la precedente ispezione delle connessioni non permetteva di attribuirlo ad AIP e ha autorizzato a lasciarne il completamento alla fase successiva.

La verifica Supabase tramite cataloghi ha rilevato:

| Evidenza | Risultato |
|---|---|
| Identità della connessione di verifica | `current_user=postgres`, `session_user=postgres`. Questo identifica il connettore amministrativo, non il processo Render. |
| Tabelle ordinarie in `public` | 19, tutte di proprietà di `postgres`. |
| RLS | Abilitata soltanto su `alembic_version`; `FORCE ROW LEVEL SECURITY` non abilitato. Nessuna policy in `public`. |
| `postgres` | `rolsuper=false`, `rolbypassrls=true`; privilegi sulle 19 tabelle. Il fatto che non sia superuser non rende efficace RLS per questo ruolo. |
| `service_role` | `rolbypassrls=true`; lettura e scrittura sulle 18 tabelle applicative. |
| `anon` e `authenticated` | `rolbypassrls=false`, USAGE su `public`, SELECT/INSERT/UPDATE/DELETE sulle 18 tabelle applicative, tutte prive di RLS. Sono presenti anche privilegi TRUNCATE e TRIGGER a livello SQL; ciò non significa che PostgREST esponga operazioni HTTP equivalenti. |
| `authenticator` | Nessun SELECT/INSERT/UPDATE/DELETE diretto sulle tabelle; può assumere i ruoli `anon`, `authenticated` e `service_role`. Non basta quindi verificare i suoi privilegi diretti. |
| Ruoli dedicati AIP | Nell’inventario non è emerso un ruolo applicativo dedicato riconoscibile come AIP. Questo non dimostra che Render usi `postgres`. |
| Connessioni osservate | La fotografia dei soli metadati non permette di attribuire con certezza una connessione ad AIP. Non sono stati letti testi SQL delle connessioni. |

Sono stati interrogati `pg_class`, `pg_namespace`, `pg_roles`, `pg_auth_members`, `pg_db_role_setting`, `pg_policies`, `pg_stat_activity` e funzioni di verifica dei privilegi. Nessuna lettura di password, hash delle password, chiavi API o contenuti delle tabelle applicative.

**Data API: privilegi accertati e verifica HTTP ancora aperta**

Le 18 tabelle applicative per cui i cataloghi consentono lettura e scrittura a `anon` e `authenticated` sono:

```text
audit_events                 auth_sessions
clinical_analyses            clinical_analysis_buttons
clinical_records             consent_records
patient_identities           research_datasets
research_studies             scientific_documents
system_settings              test_assignments
test_definitions             test_responses
test_scores                  therapists
therapy_sessions             users
```

`alembic_version` non ha gli stessi privilegi per tali ruoli ed è l’unica con RLS abilitata.

Queste 18 tabelle sono **potenzialmente accessibili tramite Data API se `public` è uno schema esposto e l’API è abilitata**, con una chiave pubblicabile/anon valida ed eventuali altri controlli del gateway. Il cookie AIP non governa questo percorso. I privilegi SQL e l’assenza di RLS sono accertati; la raggiungibilità HTTP effettiva non è stata dimostrata e non va presentata come tale.

Non sono emerse impostazioni persistite `pgrst.db_schemas`/`pgrst.db_pre_request` nelle impostazioni dei ruoli/database esaminate. La loro assenza non dimostra che la Data API sia disabilitata o che non esista una configurazione esterna. La richiesta esplorativa al gateway REST, senza credenziali e senza selezione di dati, non è riuscita per un errore del proxy dell’ambiente. Non sono state recuperate chiavi per tentare letture applicative.

Prima di definire nuove policy RLS occorrerà completare:

1. Identità SQL della connessione realmente usata da AIP, con query dalla connessione già configurata del processo, senza stampare DATABASE_URL o credenziali:

   ```sql
   SELECT current_user, session_user, r.rolsuper, r.rolbypassrls
   FROM pg_roles AS r
   WHERE r.rolname = current_user;
   ```

2. Privilegi effettivi, proprietà delle tabelle, ereditarietà dei ruoli e possibilità di `SET ROLE` di tale identità. Un ruolo proprietario o con BYPASSRLS non costituisce un confine affidabile per le policy.
3. Stato della Data API e schemi esposti nella configurazione Supabase; eventuali controlli pre-request del gateway.
4. Prove HTTP autorizzate senza dati clinici, con richieste HEAD/limite zero sui nomi delle tabelle e credenziali mantenute fuori da output, cronologia e repository. Nessuna prova di scrittura in produzione.
5. Decisione separata sui privilegi troppo ampi dei ruoli API e sull’identità applicativa, con collaudo su dati sintetici prima di ogni modifica infrastrutturale.

**Limite materiale:** il blocco FastAPI non revoca GRANT, non abilita RLS e non protegge da accessi SQL o da un’eventuale Data API esposta. Le verifiche aperte e i privilegi accertati devono rimanere evidenti nel successivo rilascio; questa PR non certifica il database come protetto.

**Ripristino nella seconda fase**

Il ripristino richiederà un modulo applicativo condiviso da conferimento, dashboard ed export. Non si riattiveranno i vecchi metodi globali sostituendo il diniego con un semplice controllo di ruolo.

Requisiti funzionali approvati dall’utente, da mantenere nella fase 2:

- **D1:** assegnazioni esplicite ricercatore/studio e permessi distinti; amministratore gestore dei permessi, senza accesso automatico ai dati.
- **D2:** partecipazione e conferimento riferiti a un protocollo specifico; nessuna associazione automatica a studi.
- **D3:** documentazione di partecipazione, consensi e revoche, distinguendo il consenso alla partecipazione dalla base giuridica GDPR del trattamento. Un booleano non sostituisce tale distinzione.
- **D4:** effetti delle revoche sui dati già raccolti quando richiesto da protocollo e regole applicabili; nessuna riabilitazione automatica dello storico con un nuovo consenso. Definire periodi, concorrenza e rilascio degli export.
- **D5:** stati distinti per raccolta, analisi, sospensione e archiviazione, con matrice delle operazioni per stato; il vecchio `is_active` non è sufficiente.
- **D6:** pseudonimi specifici per studio, export individuali disabilitati per default, soglie configurabili sui partecipanti distinti e protezioni dalla reidentificazione, comprese le differenze fra aggregati.
- **D7:** esclusione del legacy privo di provenienza e autorizzazioni verificabili, senza dedurre l’ammissibilità dal solo `consent_verified`.

Le scelte tecniche successive comprenderanno repository con query limitate prima della lettura, proiezioni minimizzate, gestione transazionale delle revoche e audit, eventuale lettore DB dedicato e RLS coerente con l’identità effettivamente utilizzata. Nuovo schema e configurazioni verranno proposti nella fase 2 e non sono introdotti qui.

Il recupero dei dati storici non è automatico: richiederà provenienza e condizioni di utilizzo documentate. La semplice riapertura dell’area ricerca non dovrà avviare un conferimento retrospettivo di tutti i questionari completati durante la sospensione.

**Verifiche di regressione**

La suite aggiornata verifica:

- Dashboard, CSV ed Excel per tutti i ruoli, anche con studi attivi, flag legacy positivi, identificativi di altri studi e parametri di autorizzazione falsificati. Controllo delle istruzioni SQL eseguite: nessuna lettura delle tabelle ricerca prima del diniego.
- Anonimi, sessioni scadute, utenti inattivi e sessioni MFA non verificate: 401, senza allegati o dati.
- Governance amministrativa disponibile; promozione a ADMIN insufficiente per aprire gli export.
- Otto combinazioni del percorso clinico: consenso generico sì/no e nessuno studio/studio attivo/inattivo/più studi. Risposte, punteggi, completamento e consultazione clinica funzionano; nessuna creazione o alimentazione di studi.
- I test MFA usano la pagina autenticata di configurazione MFA come riscontro positivo di sessione valida, dato che la dashboard ricerca ora deve rispondere 403. Le verifiche negative delle sessioni sulla ricerca restano 401. Nessun codice MFA modificato.

| Verifica | Risultato |
|---|---|
| Regressioni sul commit precedente `86537f6` | Cinque fallimenti attesi: dashboard ricercatore, CSV ricercatore ed Excel admin rispondono 200 invece di 403; le compilazioni con consenso generico, senza studio o con studio attivo, creano dataset invece di lasciare il conteggio invariato. |
| Controlli mirati su codice corretto | 91 passati: ricerca, flusso paziente, ruoli e sicurezza MFA. |
| Suite completa | **249 passati, 0 falliti, 0 errori, 0 saltati**, inclusi browser Chromium e migrazioni/concorrenza su SQLite e PostgreSQL 16 locale. Report XML: `/tmp/aip-f09-regression.xml`. |
| Controlli del repository e dipendenze | `git diff --check` e `python -m pip check` superati. Non equivalgono a una scansione delle vulnerabilità delle dipendenze. |

La suite precedente aveva 192 casi: il nuovo totale comprende 51 casi dell’area ricerca in sostituzione dell’unico test positivo globale e otto combinazioni cliniche in sostituzione dell’unico percorso precedente, per un incremento netto di 57. I test di export positivo torneranno con le autorizzazioni effettive della fase 2; il comportamento globale precedente non viene mantenuto come requisito.

Tutti i dati dei test sono sintetici. PostgreSQL di test è temporaneo, locale su loopback e distinto da Supabase; i browser intercettano gli URL e non invocano servizi applicativi reali.

Riproduzione in un ambiente locale di test con Docker, Chromium, Playwright e dipendenze Python disponibili:

```sh
docker run --name aip-f09-postgres \
  -e POSTGRES_USER=aip_test -e POSTGRES_PASSWORD=synthetic-f09-password \
  -e POSTGRES_DB=aip_f09_test -p 127.0.0.1:55409:5432 -d postgres:16-alpine
# Attendere l’esito positivo di pg_isready sul container locale.
CHROMIUM_PATH=/usr/bin/chromium \
F04_TEST_POSTGRES_URL=postgresql+psycopg2://aip_test:synthetic-f09-password@127.0.0.1:55409/aip_f09_test \
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
.venv/bin/python -m pytest -q -o faulthandler_timeout=30 --junitxml=/tmp/aip-f09-regression.xml
docker rm -f aip-f09-postgres
```

La password del comando è esclusivamente sintetica per il container di test. I test PostgreSQL rifiutano host non locali e nomi di database senza suffisso `_test`. Il container usato per la verifica è stato eliminato al termine.

**Indicazioni operative per un futuro rilascio autorizzato**

Questa PR contiene soltanto codice, test e documentazione: non richiede migrazioni o nuovi segreti. Dopo un eventuale merge e deploy autorizzati separatamente, verificare con account sintetici il 403 sui tre percorsi, il 401 con sessione non valida, l’accesso admin e il completamento clinico senza conferimento ricerca.

Un rollback al vecchio router riaprirebbe dashboard ed export globali e il conferimento implicito; in caso di problemi mantenere il blocco ricerca e correggere il percorso clinico interessato. Non cancellare dati legacy o cambiare policy/credenziali come effetto collaterale del rollback.
