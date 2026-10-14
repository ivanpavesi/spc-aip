# Documento Architetturale — STEP 1: Fondazioni e Privacy

## 1. Principi Guida del Progetto
1. **Python-first**: Struttura progettata per essere trasparente, leggibile e manutenibile da un terapeuta che apprende Python.
2. **Separazione dei Dati (Privacy by Design - GDPR)**: 
   - I dati identificativi diretti del paziente (`PatientIdentity`) sono conservati in una tabella dedicata e con campi cifrati applicativamente (Fernet).
   - La cartella clinica (`ClinicalRecord`) è separata e referenziata per la ricerca scientifica unicamente tramite un codice pseudonimo casuale (`pseudonym_code`, es. `PR-XXXX`).
   - I dati clinici non contengono riferimenti in chiaro all'identità anagrafica.
3. **Crittografia Applicativa (Application-Level Encryption)**:
   - I dati sensibili (nome, cognome, email, codice fiscale, trascrizioni e note cliniche) vengono cifrati con Fernet prima del salvataggio nel database.
   - La chiave risiede nelle variabili d'ambiente (`APP_ENCRYPTION_KEY`) e MAI nel database o nel codice sorgente.
   - Non esiste fallback a testo in chiaro: un fallimento crittografico blocca l'operazione sollevando un'eccezione esplicita.
4. **Hashing Irreversibile per i Token**:
   - I token generati per l'accesso del paziente non sono salvati nel database.
   - Viene memorizzato solo il loro hash SHA-256 (`access_token_hash`), prevenendo accessi abusivi anche in caso di compromissione del database.

## 2. Diagramma Entità e Relazioni (ER)

```text
+-------------------+       +-----------------------+
|       User        | 1---1 |       Therapist       |
| (Operatore SPC)   |       | (Iscrizione Ordine)   |
+-------------------+       +-----------------------+
                                  | 1             | 1
                                  |               |
                                  v N             v N
                        +-------------------+   +--------------------+
                        |  PatientIdentity  |   |   ClinicalRecord   |
                        | (PII Cifrata)     |   | (Pseudonimizzata)  |
                        +-------------------+   +--------------------+
                           | 1           | 1      | 1            | 1
                           |             +--------+              |
                           v N                    |              v N
                        +----------------+        |        +--------------------+
                        | ConsentRecord  |        |        |   TherapySession   |
                        | (Consensi GDPR)|        |        | (Trascrizioni)     |
                        +----------------+        |        +--------------------+
                                                  v N
                                        +--------------------+
                                        |   TestAssignment   |
                                        | (Hash Token Paz.)  |
                                        +--------------------+
                                           | 1            | 1
                                           v 1            v 1
                                  +----------------+ +----------------+
                                  |  TestResponse  | |   TestScore    |
                                  | (Risposte Raw) | | (Punti Verific)|
                                  +----------------+ +----------------+
```

## 3. Conformità agli Standard di Sicurezza
- **Header di Sicurezza**: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `X-XSS-Protection: 1; mode=block`, `Referrer-Policy: strict-origin-when-cross-origin`.
- **Prevenzione Data Leak**: Nei log di sistema (`audit_events`) e nelle risposte 500 non vengono mai esposti contenuti sanitari, diagnosi o stack trace interni.
