# Rapporto tecnico — F03: Cross-Site Scripting nel link di invito

Data: 22 ottobre 2026. Repository: `ivanpavesi/spc-aip`.
Base: `ac16d9eab5a47160f5d7a9304fa1eb1e13ba566c`, ultima versione di `main` verificata sia tramite connettore GitHub sia con `git fetch origin main`; include il merge della PR #1 (F01/F02).
Ramo dedicato: `fix/f03-invitation-link-xss`. Destinazione della PR: `main`.

## Vulnerabilità confermata

`patient_detail` accettava il parametro query `invited_token` e lo concatenava al link `/p/{token}`. Il template interpolava `invite_url` nella stringa JavaScript di un attributo `onclick` del pulsante «Copia Link Invito».

L'autoescaping HTML di Jinja2 non è un escaping JavaScript: il browser decodifica le entità nell'attributo prima di interpretare l'handler. Un apice contenuto nel parametro poteva chiudere la stringa e introdurre istruzioni arbitrarie. Si tratta di XSS riflesso, attivato dal clic di un operatore autenticato su una cartella alla quale ha accesso.

Riproduzione eseguita esclusivamente in Chromium locale, usando il template originale letto da `origin/main`, contesto sintetico e parametro `');window.__f03_xss=1;//`. Il marcatore valeva `0` prima del clic e `1` dopo: esecuzione confermata. La prova temporanea sul codice vulnerabile non fa parte della suite di regressione. Nessuna richiesta è stata inviata a Render.

## Correzione

- Eliminato l'handler inline del pulsante di copia e ogni interpolazione del link in codice JavaScript.
- Introdotto uno script statico che registra il clic con `addEventListener`, legge `input.value` e passa il valore direttamente a `navigator.clipboard.writeText`. I dati non attraversano `eval`, costruzione di funzioni o sink HTML.
- Il campo conserva l'autoescaping Jinja2 nell'attributo HTML quotato. L'uso di `textContent` mantiene anche i messaggi come testo.
- Il router codifica `invited_token` con `quote(..., safe='')`, per mantenerlo nel segmento del percorso senza introdurre query, frammenti o separatori. I token generati dall'applicazione restano invariati.
- Il messaggio «Copiato!» compare soltanto quando la promessa della Clipboard API è risolta. Durante la copia il pulsante è disabilitato. In caso di rifiuto o API assente, il campo viene selezionato e il messaggio di stato invita alla copia manuale; il pulsante viene riabilitato.
- La pagina senza invito non genera errori: lo script verifica la presenza degli elementi prima di registrare il listener.

L'intervento non modifica funzionalità cliniche, scoring, modello dati, schema o migrazioni, generazione/hash/scadenza dei token, crittografia, configurazione, credenziali o dipendenze applicative. I test usano esclusivamente il database SQLite in memoria della suite, account dimostrativi locali, dati sintetici e le chiavi effimere già predisposte dalle fixture F01/F02.

## File modificati

| File | Modifica |
| --- | --- |
| `app/routers/therapist.py` | Codifica del token nel percorso URL. |
| `app/templates/therapist/patient_detail.html` | Rimozione dell'handler vulnerabile, identificatore del pulsante, messaggio accessibile di stato e caricamento dello script statico. |
| `app/static/js/invitation-link.js` | Copia tramite listener, gestione asincrona del risultato e alternativa manuale. |
| `tests/test_invitation_links.py` | Regressioni HTTP, generazione/apertura del questionario e verifica browser. |
| `tests/browser/invitation_links.cjs` | Harness Playwright per pagine reali renderizzate dal TestClient; tutte le richieste intercettate o bloccate. |
| `docs/sicurezza_f03.md` | Rapporto tecnico, riproducibilità e rischi residui. |

## Ricognizione degli altri template

Esaminati tutti i **15 template HTML**, cercando handler `on*`, schemi `javascript:`, interpolazioni negli script, `safe`, `innerHTML`, `outerHTML`, `document.write` ed `eval`. Non sono state individuate altre interpolazioni Jinja di dati dinamici dentro handler JavaScript o blocchi script. Non risultano altri casi dello stesso schema F03 nel codice esaminato.

Rimangono **10 handler inline statici**, lasciati fuori perimetro:

| Template | Utilizzi residui |
| --- | --- |
| `therapist/patient_detail.html` | `onchange` del selettore LLM: `syncSelectedModel(this.value)`. |
| `home.html` | `onerror` del logo, con URL di fallback costante. |
| `auth/login.html` | Tre `onclick` con argomenti dimostrativi costanti per `fillCreds`. |
| `admin/test_edit.html` | Un `onsubmit` di conferma con messaggio costante. |
| `admin/dashboard.html` | Tre `onsubmit` di conferma con messaggi costanti e un `onchange` che invia il form. |

Restano inoltre script inline statici per configurazione Tailwind, compilazione del login demo e sincronizzazione del modello LLM. Questi casi non sono evidenza dello stesso XSS da interpolazione; l'eventuale rimozione generale degli script inline e adozione di una CSP restrittiva richiedono un intervento separato. Nessuna altra vulnerabilità è stata corretta incidentalmente.

## Test e risultati

Ambiente: Python 3.12.14, Node.js 24.19.0, Playwright 1.62.1, Chromium 154.0.8037.57. Nessuna dipendenza di produzione aggiunta.

| Verifica | Risultato |
| --- | --- |
| `CHROMIUM_PATH=/usr/bin/chromium .venv/bin/python -m pytest tests/test_invitation_links.py -q -o faulthandler_timeout=30` | **9 passed**, inclusa la verifica browser. |
| `CHROMIUM_PATH=/usr/bin/chromium .venv/bin/python -m pytest -q -o faulthandler_timeout=30` | **95 passed**, nessun test saltato. |
| `.venv/bin/python -m pip check` | Nessuna dipendenza incompatibile. |
| `node --check app/static/js/invitation-link.js` e `node --check tests/browser/invitation_links.cjs` | Sintassi valida. |
| `git diff --check` | Nessun errore di whitespace. |

Copertura nuova:

- Sei payload sintetici: apici singoli/doppi, tentativi di introdurre tag/handler HTML, chiusura di script, entità HTML e caratteri di URL/escape/controllo; inoltre un token ordinario.
- Verifica del valore HTML decodificato, assenza di `onclick` sul pulsante, assenza di handler iniettati, integrità del messaggio WhatsApp, assenza di query/frammenti aggiunti e disponibilità dello script via `/static`.
- Assegnazione reale tramite endpoint, estrazione del token dal redirect, visualizzazione del link e apertura anonima del questionario BDI-II. La suite esistente verifica anche compilazione, scoring e blocco del reinvio.
- **15 scenari browser**: link generato, sei payload via router, sei payload passati direttamente al template, pagina senza invito e copia/lettura con la Clipboard API reale di Chromium. Nei 13 scenari con invito sono verificati anche promessa pendente, successo, permessi negati e API assente, con controllo della selezione manuale e dell'assenza di falso successo.
- Nei test con payload si controllano valore copiato, marcatore XSS non eseguito, assenza di dialoghi inattesi ed errori JavaScript. I test diretti al template dimostrano che la rimozione del sink JavaScript protegge anche senza la codifica URL del router; i ritorni a capo letterali sono normalizzati dagli input di testo secondo il comportamento del browser.

Il browser riceve l'HTML prodotto dal TestClient attraverso `route.fulfill`, insieme allo script statico servito dall'applicazione. Ogni altra richiesta (CDN incluse) è bloccata, senza contattare un sito applicativo reale. La Clipboard API è simulata per i casi di errore e attesa; un ulteriore scenario usa l'API reale di Chromium con permessi espliciti e legge soltanto il link sintetico appena scritto.

Il primo avvio nella sandbox con rete ristretta si è bloccato nel runtime del TestClient ed è stato terminato. Come già osservato nella verifica F01/F02, il runtime di test ha richiesto i permessi di rete della sandbox; le esecuzioni completate non hanno interrogato servizi applicativi esterni.

### Riproducibilità del test browser

La suite Python continua a funzionare con le dipendenze esistenti. Il solo test browser viene esplicitamente saltato se Node.js o il modulo Playwright non sono disponibili; per riprodurre tutti i 95 test occorrono anche Playwright e Chromium. Esempio con installazione isolata degli strumenti di test:

```sh
npm install --prefix /tmp/aip-f03-browser --no-save --package-lock=false playwright@1.62.1
NODE_PATH=/tmp/aip-f03-browser/node_modules CHROMIUM_PATH=/usr/bin/chromium \
  .venv/bin/python -m pytest -q -o faulthandler_timeout=30
```

`CHROMIUM_PATH` può indicare un Chromium installato localmente. In alternativa installare il browser di Playwright con `/tmp/aip-f03-browser/node_modules/.bin/playwright install chromium` e omettere `CHROMIUM_PATH`. Il test browser deve risultare **passed**, non **skipped**, nella verifica completa.

## Rischi residui e limiti

- Nessuna verifica è stata eseguita sull'installazione Render, su PostgreSQL reale o su dati/credenziali reali. Il risultato riguarda il codice e i flussi locali verificati.
- La disponibilità della copia automatica dipende dal contesto sicuro e dai permessi del browser; il percorso manuale gestisce il rifiuto o l'assenza dell'API. La verifica browser riguarda Chromium, non tutti i browser o i clipboard manager del sistema operativo.
- Il parametro query rimane un dato non attendibile: la visualizzazione del messaggio non dimostra che il token appartenga a un invito valido. L'autorizzazione all'apertura del questionario continua a dipendere dai controlli esistenti sul token. Non sono stati aggiunti controlli di autenticità a questa notifica.
- La costruzione dell'origine da `request.base_url`, la gestione dei proxy/Host, la presenza del token nella query/storia e la policy generale CSP/CDN restano fuori da F03 e non sono stati modificati né verificati come vulnerabilità distinte.

Nessun merge, deploy o modifica dei servizi online è stato eseguito. La correzione è destinata alla revisione tramite PR prima di qualsiasi pubblicazione dell'applicazione.
