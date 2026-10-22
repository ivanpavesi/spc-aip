"""Confine autorizzativo della ricerca, indipendente dal trasporto HTTP.

F09 fase 1: non esiste ancora una fonte verificabile di autorizzazioni per
operatore, studio e protocollo. Nessuna identità o ruolo costituisce un grant.
Non introdurre flag di configurazione per riaprire i percorsi legacy.
"""

from typing import NoReturn


class ResearchAccessDenied(PermissionError):
    """Manca un'autorizzazione verificabile per l'accesso alla ricerca."""


def authorize_research_access(*, actor_id: str) -> NoReturn:
    """Nega anche agli admin finché non esiste il modulo di autorizzazione.

    L'identità autenticata serve a definire il confine del futuro servizio;
    non viene interpretata come appartenenza a uno studio. Non legge dati.
    """
    raise ResearchAccessDenied(
        "Area ricerca temporaneamente sospesa: dashboard ed esportazioni "
        "richiedono autorizzazioni esplicite per studio e protocollo, "
        "non ancora disponibili."
    )
