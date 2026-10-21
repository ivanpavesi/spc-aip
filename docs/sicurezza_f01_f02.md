# Prima fase di messa in sicurezza: F01 e F02

Data: 21 ottobre 2026. Base verificata: `aad391484f4367937027813ffd9ac4c30dc1d8b9` (`main`). Ramo: `security/f01-f02-bootstrap-keys`.

## Perimetro e risultato

L'intervento riguarda esclusivamente il bootstrap degli account dimostrativi (F01) e la configurazione crittografica (F02). Non introduce migrazioni, rotazioni automatiche o modifiche ai dati cifrati. Nessun servizio di produzione è stato contattato; i test usano soltanto dati sintetici, SQLite in memoria/file temporanei e chiavi generate per i test. Non sono stati eseguiti merge o deploy.

F01: il catalogo dei questionari, i pulsanti clinici e le impostazioni applicative continuano a essere inizializzati in tutti gli ambienti. La creazione degli account demo è confinata a `development`/`testing`, con controllo anche nella funzione dedicata. Un account esistente non viene modificato, comprese password, ruolo, stato, TOTP e profilo professionale. La configurazione produttiva rifiuta il database SQLite dimostrativo `aip_dev.db` e i database in memoria.

F02: la chiave Fernet predefinita è rimossa. Occorre una chiave esplicita anche per lo sviluppo. In produzione, il caricamento di `Settings` blocca l'import/avvio dell'applicazione prima dell'accesso al database se i segreti sono assenti o non sicuri:

- `APP_SECRET_KEY`: almeno 32 caratteri, senza spazi esterni, diversa da segnaposto riconoscibili, valori palesemente ripetuti e dalla chiave Fernet.
- `APP_ENCRYPTION_KEY`: codifica base64 URL-safe canonica di esattamente 32 byte; rifiuto dei valori pubblicati nel vecchio codice e template e di chiavi palesemente ripetute/a bassa diversità.
- Il servizio crittografico applica la stessa validazione anche a chiavi esplicite e fallback; una chiave primaria vuota non attiva più un fallback implicito.
- Gli errori di validazione e la rappresentazione di `Settings` non riportano i segreti.

I valori Fernet pubblicati restano nel codice esclusivamente come elenco di rifiuto; non vengono utilizzati come fallback. Fernet e il formato dei ciphertext restano invariati. Il supporto MultiFernet esistente è preservato, senza invocare automaticamente `rotate_token`.

## File modificati

| File | Motivazione |
| --- | --- |
| `app/core/config.py` | Validazione produttiva dei segreti e dei database demo; nessuna chiave Fernet implicita; errori senza valori sensibili. |
| `app/db/seeds.py` | Separazione del bootstrap applicativo dagli account demo e rimozione dei reset delle password. |
| `app/services/encryption.py` | Validazione condivisa, anche per fallback; rifiuto di chiavi vuote esplicite senza sostituzioni silenziose. |
| `.env.example` | Rimozione dei segreti dimostrativi utilizzabili; istruzioni per valorizzazione esplicita e conservazione delle chiavi esistenti. |
| `tests/conftest.py` | Chiave Fernet effimera generata per la suite, al posto del vecchio valore pubblico. |
| `tests/test_bootstrap_security.py` | Test F01 su avvii ripetuti, database vuoti/parziali, credenziali e profili personalizzati, chiamate dirette e ambienti non ammessi. |
| `tests/test_production_config.py` | Test positivi/negativi F02, startup produttivo locale, compatibilità dei ciphertext, fallback e blocco prima dell'accesso al database. |
| `README.md` | Comportamento aggiornato del bootstrap e istruzioni sulle chiavi e sui database esistenti. |
| `docs/sicurezza_f01_f02.md` | Questo rapporto con verifiche, limiti e rischi residui. |

## Test e verifiche eseguiti

Ambiente: Python 3.12.14, dipendenze della `.venv` già predisposta. Nessuna modifica alle dipendenze.

| Comando/verifica | Risultato |
| --- | --- |
| `.venv/bin/python -m pytest -q -o faulthandler_timeout=30` | **86 passed**, 16,71 secondi. Intera suite disponibile, inclusi i nuovi test negativi. |
| `.venv/bin/python -m pip check` | Nessuna dipendenza incompatibile. |
| `git diff --check` | Nessun errore di whitespace. |

Il primo tentativo della suite, precedente alle modifiche, e il successivo tentativo sui test HTTP sono rimasti bloccati nel portale di thread AnyIO usato da Starlette `TestClient`, sotto la restrizione di rete della sandbox. I processi sono stati terminati. Con i permessi di rete necessari al runtime di test, i quattro test delle route e poi l'intera suite sono terminati con successo. Il permesso non è stato usato per interrogare servizi applicativi esterni.

La suite verifica in particolare:

- In produzione, zero utenti/profili demo su database vuoto, anche dopo due inizializzazioni; catalogo completo e senza duplicati.
- Nei tre ambienti, gli hash delle password già personalizzate restano identici; ruoli, disattivazione, TOTP e profilo non vengono alterati.
- In sviluppo/test, gli account mancanti restano disponibili con le credenziali demo, senza sovrascrivere quelli già presenti.
- Chiamata diretta al seed demo in produzione/ambiente sconosciuto: nessuna operazione sul database.
- Segreti mancanti, vuoti, dimostrativi, ripetuti, malformati e non indipendenti: configurazione produttiva rifiutata.
- Chiavi demo rifiutate anche come fallback del servizio crittografico in produzione.
- Import reale dell'applicazione con configurazione produttiva non sicura: errore e nessun file database creato.
- Due lifespan reali FastAPI in modalità `production`, su file SQLite temporaneo: `/healthz` risponde, catalogo disponibile, nessun account demo creato.
- Lettura di ciphertext sintetico già prodotto da Fernet con una chiave valida esplicita, oltre ai test esistenti di cifratura, manomissione, chiave errata e MultiFernet.

Non rimangono test della suite locale non eseguibili. Non sono state eseguite verifiche su PostgreSQL/Supabase reali, dati clinici, chiavi in uso o servizi di produzione, come richiesto. Il risultato locale non certifica la configurazione di un'installazione reale.

## Rischi residui e condizioni per una futura adozione

1. Se un'installazione usa una delle chiavi pubbliche ora rifiutate, l'avvio produttivo viene intenzionalmente bloccato. **Non sostituire la chiave per aggirare il controllo**: i dati esistenti diventerebbero illeggibili senza la chiave corretta. Occorre un'attività distinta con inventario dei dati/chiavi, compatibilità, backup verificati, migrazione controllata e prova di ripristino. Questa PR non esegue tale attività.
2. Gli account demo eventualmente già presenti in produzione non sono rimossi, disabilitati o resettati automaticamente. È necessaria una verifica e una bonifica manuale autorizzata, comprensiva dell'eventuale revoca delle sessioni, prima dell'adozione produttiva.
3. I controlli riconoscono formato, valori pubblici e alcuni schemi palesemente deboli: non possono provare che un segreto arbitrario sia stato generato casualmente o non sia stato esposto. Le chiavi devono provenire da un generatore crittografico ed essere custodite nell'ambiente appropriato.
4. È indispensabile impostare `ENVIRONMENT=production` nell'installazione produttiva. Il default `development` è preservato per il flusso locale; la configurazione Render esistente specifica già `production` e non è stata modificata.
5. Su una nuova installazione produttiva gli utenti devono essere predisposti mediante una procedura amministrativa autorizzata distinta; questa PR non introduce un nuovo canale di bootstrap privilegiato.

Le altre vulnerabilità non sono state affrontate in questa attività.

## Stato della consegna per revisione

Le modifiche e il rapporto sono committati sul ramo locale dedicato. La pubblicazione del ramo è bloccata: `git push` restituisce HTTP 403 (`Permission denied`), mentre il connettore GitHub restituisce HTTP 403 (`Resource not accessible by integration`) alla creazione dell'albero Git. Il connettore consente la lettura del repository ma non questa scrittura. Nessuna pull request è stata aperta e nessun ramo remoto è stato aggiornato. Sono forniti anche una patch applicabile e il testo completo della PR; l'apertura richiede un accesso GitHub con permessi effettivi di scrittura su `ivanpavesi/spc-aip`.
