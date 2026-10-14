"""Motore deterministico di calcolo psicometrico e scoring normativo (STEP 4).

REGOLA NON NEGOZIABILE:
Nessun modello linguistico (LLM) calcola punteggi numerici.
Tutte le elaborazioni matematiche, inversioni, scale, cut-off e percentili
sono eseguite in modo deterministico e riproducibile da codice Python puro.
Non viene utilizzato eval() né exec().
"""

import math
from typing import Any, Dict, List, Optional, Tuple, Union


class ScoringError(Exception):
    """Eccezione sollevata quando le risposte fornite non rispettano lo schema o sono incomplete."""
    pass


def calculate_inverted_value(val: int, min_val: int, max_val: int) -> int:
    """Calcola il valore invertito secondo la formula psicometrica standard:

    valore_invertito = minimo + massimo - valore_originale
    Esempio scala 1-4: val=1 -> 1+4-1 = 4. val=4 -> 1+4-4 = 1.
    """
    if val < min_val or val > max_val:
        raise ScoringError(f"Valore {val} fuori dal range consentito [{min_val}, {max_val}].")
    return min_val + max_val - val


class PsychometricScoringEngine:
    """Interprete deterministico per schemi di test psicometrici."""

    @staticmethod
    def score_test(
        items_schema: Dict[str, Any],
        scoring_rules: Dict[str, Any],
        answers: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Calcola i punteggi grezzi, le sottoscale e i cut-off normativi in modo deterministico.

        Args:
            items_schema: Definizione degli item del test (id, min, max, invertiti, opzioni).
            scoring_rules: Regole di scoring, scale, sottoscale, formule e cut-off.
            answers: Dizionario di risposte fornite {item_id: valore}.

        Returns:
            Dizionario strutturato contenente:
            - raw_scores: punteggi totali e per scala
            - subscales: punteggi delle sottoscale
            - clinical_cutoffs: soglie superate ed etichette cliniche
            - validity: indicatori di validità
            - engine_version: versione dell'algoritmo
        """
        items_def = {item["id"]: item for item in items_schema.get("items", [])}
        if not items_def:
            raise ScoringError("Lo schema del test non definisce alcun item valido.")

        processed_values: Dict[str, float] = {}

        # 1. Elaborazione e validazione deterministica di ciascun item
        for item_id, item_info in items_def.items():
            if item_id not in answers:
                raise ScoringError(f"Risposta mancante per l'item obbligatorio: {item_id}")

            raw_val = answers[item_id]
            min_val = item_info.get("min", 0)
            max_val = item_info.get("max", 3)
            is_inverted = item_info.get("inverted", False)

            # Supporto per risposte singole numeriche
            if isinstance(raw_val, (int, float)):
                numeric_val = int(raw_val)
                if numeric_val < min_val or numeric_val > max_val:
                    raise ScoringError(f"Item {item_id}: valore {numeric_val} fuori dai limiti [{min_val}, {max_val}].")
                
                final_val = calculate_inverted_value(numeric_val, min_val, max_val) if is_inverted else numeric_val
                processed_values[item_id] = float(final_val)

            # Supporto per risposte multiple con aggregazione esplicita
            elif isinstance(raw_val, list):
                rule = item_info.get("multiple_aggregation", "SUM").upper()
                if not raw_val:
                    processed_values[item_id] = 0.0
                elif rule == "SUM":
                    processed_values[item_id] = float(sum(raw_val))
                elif rule == "MAX":
                    processed_values[item_id] = float(max(raw_val))
                elif rule == "COUNT":
                    processed_values[item_id] = float(len(raw_val))
                elif rule == "ANY":
                    processed_values[item_id] = 1.0 if any(raw_val) else 0.0
                else:
                    processed_values[item_id] = float(sum(raw_val))
            else:
                raise ScoringError(f"Tipo di risposta non valido per item {item_id}: {type(raw_val)}")

        # 2. Calcolo Scale e Sottoscale
        raw_scores: Dict[str, float] = {}
        subscales_scores: Dict[str, float] = {}

        # Calcolo Totale principale
        total_items = scoring_rules.get("total_items") or list(items_def.keys())
        total_sum = sum(processed_values[iid] for iid in total_items if iid in processed_values)
        raw_scores["total"] = total_sum

        # Calcolo sottoscale specifiche definite nelle regole
        defined_subscales = scoring_rules.get("subscales", {})
        for sub_name, sub_config in defined_subscales.items():
            if isinstance(sub_config, list):
                sub_items = sub_config
                op = "SUM"
            else:
                sub_items = sub_config.get("items", [])
                op = sub_config.get("operation", "SUM").upper()

            item_vals = [processed_values[iid] for iid in sub_items if iid in processed_values]
            if not item_vals:
                subscales_scores[sub_name] = 0.0
                continue

            if op == "SUM":
                subscales_scores[sub_name] = sum(item_vals)
            elif op == "MEAN":
                subscales_scores[sub_name] = round(sum(item_vals) / len(item_vals), 2)
            elif op == "COUNT_GT_ZERO":
                subscales_scores[sub_name] = sum(1 for v in item_vals if v > 0)
            elif op == "PERCENTAGE":
                max_possible = len(item_vals) * items_def[sub_items[0]].get("max", 1)
                subscales_scores[sub_name] = round((sum(item_vals) / max_possible) * 100, 1) if max_possible > 0 else 0.0
            else:
                subscales_scores[sub_name] = sum(item_vals)

        # 3. Valutazione Cut-off e Norme Cliniche
        cutoffs_config = scoring_rules.get("cutoffs", [])
        clinical_severity = "NON_VALUTABILE"
        clinical_description = "Nessun cut-off configurato"

        for cut in cutoffs_config:
            # cut: {"min": 0, "max": 13, "severity": "MINIMA", "label": "Minima depressione"}
            target_metric = cut.get("metric", "total")
            metric_val = raw_scores["total"] if target_metric == "total" else subscales_scores.get(target_metric, 0)
            min_c = cut.get("min", -math.inf)
            max_c = cut.get("max", math.inf)

            if min_c <= metric_val <= max_c:
                clinical_severity = cut.get("severity", "NON_DEFINITA")
                clinical_description = cut.get("label", "")
                break

        return {
            "raw_scores": raw_scores,
            "subscales": subscales_scores,
            "clinical_cutoffs": {
                "severity": clinical_severity,
                "description": clinical_description,
                "total_score": total_sum,
            },
            "validity": {
                "complete": len(answers) == len(items_def),
                "items_answered": len(answers),
                "total_items": len(items_def),
            },
            "engine_version": "1.0.0-deterministic",
        }


# ==============================================================================
# CATALOGO DEGLI STRUMENTI CLINICI STANDARD SPC/APC
# ==============================================================================

def get_bdi2_definition() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Restituisce la definizione ufficiale e verificata del Beck Depression Inventory-II (BDI-II).

    21 item, scala 0-3. Range totale: 0-63.
    Cut-off ufficiali:
    - 0-13: Minima depressione (Minimal)
    - 14-19: Depressione lieve (Mild)
    - 20-28: Depressione moderata (Moderate)
    - 29-63: Depressione grave (Severe)
    Sottoscale:
    - Somatico-Affettiva: item 4, 11, 12, 13, 15, 16, 17, 18, 19, 20, 21
    - Cognitiva: item 1, 2, 3, 5, 6, 7, 8, 9, 10, 14
    """
    items = []
    bdi_questions = [
        "Tristezza", "Pessimismo", "Fallimento", "Perdita di piacere", "Senso di colpa",
        "Sentimenti di punizione", "Disistima di sé", "Autocritica", "Ideazione suicidaria", "Pianto",
        "Agitazione", "Perdita di interesse", "Indecisione", "Svalutazione", "Perdita di energia",
        "Alterazioni nel sonno", "Irritabilità", "Alterazioni nell'appetito", "Difficoltà di concentrazione",
        "Fatica o spossatezza", "Perdita di interesse per il sesso"
    ]
    for i, q in enumerate(bdi_questions, start=1):
        items.append({
            "id": f"bdi_{i}",
            "number": i,
            "text": q,
            "min": 0,
            "max": 3,
            "inverted": False,
            "options": [
                {"value": 0, "label": "Assente / Normale"},
                {"value": 1, "label": "Lieve"},
                {"value": 2, "label": "Moderato"},
                {"value": 3, "label": "Grave / Severo"},
            ]
        })

    items_schema = {"items": items}

    scoring_rules = {
        "total_items": [f"bdi_{i}" for i in range(1, 22)],
        "subscales": {
            "cognitiva": {
                "items": ["bdi_1", "bdi_2", "bdi_3", "bdi_5", "bdi_6", "bdi_7", "bdi_8", "bdi_9", "bdi_10", "bdi_14"],
                "operation": "SUM",
            },
            "somatico_affettiva": {
                "items": ["bdi_4", "bdi_11", "bdi_12", "bdi_13", "bdi_15", "bdi_16", "bdi_17", "bdi_18", "bdi_19", "bdi_20", "bdi_21"],
                "operation": "SUM",
            },
        },
        "cutoffs": [
            {"min": 0, "max": 13, "severity": "MINIMA", "label": "Minima depressione (0-13)"},
            {"min": 14, "max": 19, "severity": "LIEVE", "label": "Depressione lieve (14-19)"},
            {"min": 20, "max": 28, "severity": "MODERATA", "label": "Depressione moderata (20-28)"},
            {"min": 29, "max": 63, "severity": "GRAVE", "label": "Depressione grave (29-63)"},
        ]
    }
    return items_schema, scoring_rules


def get_stai_y1_definition() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Restituisce la definizione dello State-Trait Anxiety Inventory (STAI-Y1 - Ansia di Stato).

    20 item, scala 1-4.
    Item invertiti: 1, 2, 5, 8, 10, 11, 15, 16, 19, 20.
    Range totale: 20-80.
    Soglia clinica indicativa: >= 40.
    """
    inverted_items = {1, 2, 5, 8, 10, 11, 15, 16, 19, 20}
    items = []
    stai_prompts = [
        "Mi sento calmo", "Mi sento sicuro", "Sono teso", "Mi sento sotto pressione", "Mi sento a mio agio",
        "Mi sento turbato", "Sono preoccupato per possibili sventure", "Mi sento riposato", "Mi sento ansioso", "Mi sento a mio agio",
        "Mi sento fiducioso", "Mi sento nervoso", "Mi sento agitato", "Mi sento indeciso", "Sono rilassato",
        "Mi sento soddisfatto", "Sono preoccupato", "Mi sento confuso", "Mi sento sereno", "Mi sento piacevolmente"
    ]
    for i, p in enumerate(stai_prompts, start=1):
        items.append({
            "id": f"stai_{i}",
            "number": i,
            "text": p,
            "min": 1,
            "max": 4,
            "inverted": i in inverted_items,
            "options": [
                {"value": 1, "label": "Per nulla"},
                {"value": 2, "label": "Un poco"},
                {"value": 3, "label": "Abbastanza"},
                {"value": 4, "label": "Moltissimo"},
            ]
        })

    items_schema = {"items": items}
    scoring_rules = {
        "total_items": [f"stai_{i}" for i in range(1, 21)],
        "cutoffs": [
            {"min": 20, "max": 39, "severity": "NORMALE", "label": "Ansia nei limiti della norma (20-39)"},
            {"min": 40, "max": 59, "severity": "MODERATA", "label": "Ansia clinicamente significativa moderata (40-59)"},
            {"min": 60, "max": 80, "severity": "ELEVATA", "label": "Ansia clinicamente significativa elevata (60-80)"},
        ]
    }
    return items_schema, scoring_rules
