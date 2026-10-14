"""Test automatici per il modulo di crittografia applicativa (Fernet / MultiFernet)."""

import pytest
from cryptography.fernet import Fernet
from app.services.encryption import (
    EncryptionService,
    EncryptionError,
    DecryptionError,
    EncryptionConfigurationError,
)


def test_encryption_and_decryption_success():
    """Verifica il ciclo completo di cifratura e decifratura di dati testuali."""
    key = Fernet.generate_key().decode()
    service = EncryptionService(primary_key=key)

    original_text = "Mario Rossi - CF: RSSMRA80A01H501U - Anamnesi clinica riservata"
    ciphertext = service.encrypt_text(original_text)

    # Il ciphertext non deve contenere il testo originale in chiaro
    assert original_text not in ciphertext
    assert isinstance(ciphertext, str)
    assert len(ciphertext) > len(original_text)

    # Decifratura corretta
    decrypted_text = service.decrypt_text(ciphertext)
    assert decrypted_text == original_text


def test_encryption_is_non_deterministic():
    """Verifica che lo stesso testo cifrato due volte produca ciphertext diversi (IV e timestamp casuali)."""
    key = Fernet.generate_key().decode()
    service = EncryptionService(primary_key=key)

    plaintext = "Dato clinico sensibile"
    c1 = service.encrypt_text(plaintext)
    c2 = service.encrypt_text(plaintext)

    assert c1 != c2
    assert service.decrypt_text(c1) == plaintext
    assert service.decrypt_text(c2) == plaintext


def test_decryption_with_wrong_key_fails():
    """Verifica che decifrare con una chiave errata sollevi DecryptionError senza rivelare il testo."""
    key1 = Fernet.generate_key().decode()
    key2 = Fernet.generate_key().decode()

    service1 = EncryptionService(primary_key=key1)
    service2 = EncryptionService(primary_key=key2)

    ciphertext = service1.encrypt_text("Paziente con disturbo d'ansia")

    with pytest.raises(DecryptionError):
        service2.decrypt_text(ciphertext)


def test_tampered_ciphertext_fails():
    """Verifica che una modifica accidentale o dolosa del ciphertext sia rilevata dal MAC."""
    key = Fernet.generate_key().decode()
    service = EncryptionService(primary_key=key)

    ciphertext = service.encrypt_text("Note cliniche del terapeuta")
    # Manomettiamo alcuni caratteri a metà del token
    tampered = ciphertext[:15] + ("A" if ciphertext[15] != "A" else "B") + ciphertext[16:]

    with pytest.raises(DecryptionError):
        service.decrypt_text(tampered)


def test_empty_string_handling():
    """Verifica che le stringhe vuote vengano gestite coerentemente."""
    key = Fernet.generate_key().decode()
    service = EncryptionService(primary_key=key)

    assert service.encrypt_text("") == ""
    assert service.decrypt_text("") == ""


def test_none_value_rejection():
    """Verifica che valori None sollevino eccezioni esplicite e non vengano ignorati."""
    key = Fernet.generate_key().decode()
    service = EncryptionService(primary_key=key)

    with pytest.raises(EncryptionError):
        service.encrypt_text(None)  # type: ignore

    with pytest.raises(DecryptionError):
        service.decrypt_text(None)  # type: ignore


def test_invalid_key_format_raises_configuration_error():
    """Verifica che chiavi non conformi a Fernet (es. non base64 o di lunghezza errata) siano rifiutate."""
    with pytest.raises(EncryptionConfigurationError):
        EncryptionService(primary_key="chiave_corta_non_valida")

    with pytest.raises(EncryptionConfigurationError):
        EncryptionService(primary_key="not-valid-base64@@@!123456789012345678901234")


def test_key_rotation_support():
    """Verifica il supporto alla rotazione delle chiavi senza interruzione del servizio."""
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()

    # Servizio con la vecchia chiave
    old_service = EncryptionService(primary_key=old_key)
    ciphertext_old = old_service.encrypt_text("Dato archiviato con vecchia chiave")

    # Nuovo servizio configurato con la nuova chiave come primaria e la vecchia come fallback
    rotating_service = EncryptionService(primary_key=new_key, fallback_keys=[old_key])

    # Deve essere in grado di decifrare il dato creato con la vecchia chiave
    assert rotating_service.decrypt_text(ciphertext_old) == "Dato archiviato con vecchia chiave"

    # La rotazione aggiorna il token alla nuova chiave primaria
    rotated_ciphertext = rotating_service.rotate_token(ciphertext_old)
    assert rotated_ciphertext != ciphertext_old

    # Il token ruotato può ora essere decifrato da un servizio che conosce SOLO la nuova chiave
    strictly_new_service = EncryptionService(primary_key=new_key)
    assert strictly_new_service.decrypt_text(rotated_ciphertext) == "Dato archiviato con vecchia chiave"
