"""Router per l'Area Ricerca Scientifica (STEP 5)."""

import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
import numpy as np
import pandas as pd
from sqlalchemy.orm import Session
from app.core.auth import require_researcher
from app.db.models.audit import AuditEvent
from app.db.models.research import ResearchDataset, ResearchStudy
from app.db.models.user import User
from app.db.session import get_db

router = APIRouter(prefix="/researcher", tags=["Area Ricerca"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/dashboard", response_class=HTMLResponse, summary="Dashboard Ricercatore")
def researcher_dashboard(
    request: Request,
    user: User = Depends(require_researcher),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    studies = db.query(ResearchStudy).all()
    datasets = db.query(ResearchDataset).all()

    # Calcolo statistiche descrittive aggregate con Pandas / NumPy
    stats_by_test = {}
    if datasets:
        records = []
        for d in datasets:
            tot = d.scores_data.get("total") if isinstance(d.scores_data, dict) else None
            if tot is not None:
                records.append({
                    "test_code": d.test_code,
                    "total_score": float(tot),
                    "age_bracket": d.minified_demographics.get("age_bracket", "N/D") if d.minified_demographics else "N/D",
                })
        
        if records:
            df = pd.DataFrame(records)
            for test_code, group in df.groupby("test_code"):
                vals = group["total_score"].values
                stats_by_test[test_code] = {
                    "count": len(vals),
                    "mean": round(float(np.mean(vals)), 2),
                    "std": round(float(np.std(vals)), 2) if len(vals) > 1 else 0.0,
                    "median": round(float(np.median(vals)), 2),
                    "min": float(np.min(vals)),
                    "max": float(np.max(vals)),
                }

    return templates.TemplateResponse(
        request=request,
        name="researcher/dashboard.html",
        context={
            "user": user,
            "studies": studies,
            "datasets_count": len(datasets),
            "stats_by_test": stats_by_test,
            "k_anonymity_warning": len(datasets) < 5 and len(datasets) > 0,
        },
    )


@router.get("/export/csv", summary="Esportazione Dataset Pseudonimizzato CSV")
def export_csv(
    request: Request,
    test_code: Optional[str] = None,
    user: User = Depends(require_researcher),
    db: Session = Depends(get_db),
) -> Response:
    query = db.query(ResearchDataset)
    if test_code:
        query = query.filter(ResearchDataset.test_code == test_code)
    datasets = query.all()

    if not datasets:
        raise HTTPException(status_code=404, detail="Nessun dato disponibile per l'esportazione.")

    # Costruzione DataFrame minimizzato (zero PII, solo codice pseudonimo e punteggi)
    rows = []
    for d in datasets:
        row = {
            "pseudonym_code": d.pseudonym_code,
            "test_code": d.test_code,
            "age_bracket": d.minified_demographics.get("age_bracket", "N/D") if d.minified_demographics else "N/D",
            "created_at": d.created_at.strftime("%Y-%m-%d"),
        }
        if isinstance(d.scores_data, dict):
            for k, v in d.scores_data.items():
                row[f"score_{k}"] = v
        rows.append(row)

    df = pd.DataFrame(rows)
    csv_bytes = df.to_csv(index=False, sep=";").encode("utf-8")

    # Audit Trail dell'esportazione (GDPR)
    db.add(AuditEvent(
        actor_id=user.id,
        actor_role="RESEARCHER",
        action="RESEARCH_DATASET_EXPORT_CSV",
        resource_type="ResearchDataset",
        technical_details={"rows_exported": len(rows), "test_filter": test_code},
    ))
    db.commit()

    return StreamingResponse(
        io.BytesIO(csv_bytes),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=aip_research_export_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"},
    )


@router.get("/export/excel", summary="Esportazione Dataset Pseudonimizzato Excel")
def export_excel(
    request: Request,
    test_code: Optional[str] = None,
    user: User = Depends(require_researcher),
    db: Session = Depends(get_db),
) -> Response:
    query = db.query(ResearchDataset)
    if test_code:
        query = query.filter(ResearchDataset.test_code == test_code)
    datasets = query.all()

    if not datasets:
        raise HTTPException(status_code=404, detail="Nessun dato disponibile per l'esportazione.")

    rows = []
    for d in datasets:
        row = {
            "pseudonym_code": d.pseudonym_code,
            "test_code": d.test_code,
            "age_bracket": d.minified_demographics.get("age_bracket", "N/D") if d.minified_demographics else "N/D",
            "created_at": d.created_at.strftime("%Y-%m-%d"),
        }
        if isinstance(d.scores_data, dict):
            for k, v in d.scores_data.items():
                row[f"score_{k}"] = v
        rows.append(row)

    df = pd.DataFrame(rows)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Research_Data")
    output.seek(0)

    # Audit Trail
    db.add(AuditEvent(
        actor_id=user.id,
        actor_role="RESEARCHER",
        action="RESEARCH_DATASET_EXPORT_EXCEL",
        resource_type="ResearchDataset",
        technical_details={"rows_exported": len(rows), "test_filter": test_code},
    ))
    db.commit()

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=aip_research_export_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"},
    )
