"""
Resume workspace: upload, version, edit, download.

Design decisions worth knowing:

* Nothing is ever overwritten. Every save creates a new ResumeVersion row and flips which
  one is active. An AI rewrite can't destroy your original, and "which version got more
  replies" stays answerable.

* LaTeX is the source of truth when present. If you upload .tex, the agent edits the
  LaTeX itself — which means its output is a document you can actually compile and send,
  not just text you'd have to re-format by hand.

* PDF is import-only. Text can be pulled out of a PDF, but there's no reliable route back
  to a formatted PDF from that text — the structure simply isn't in the file. Uploading
  .tex is what makes the round trip work, and the UI says so.
"""
import io
import shutil
import subprocess
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.resume_parser import ResumeParseError, latex_to_text, parse_upload
from app.db import get_db
from app.deps import get_current_claims
from app.models import ResumeVersion, UserProfile

router = APIRouter(prefix="/resume", tags=["resume"])

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # a resume is never 5 MB; this is an abuse guard


class VersionOut(BaseModel):
    id: str
    label: str
    source_format: str
    origin: str
    is_active: bool
    has_latex: bool
    tailored_for_posting_id: str | None
    change_summary: str | None
    created_at: str
    preview: str

    class Config:
        from_attributes = True


def _to_out(version: ResumeVersion) -> VersionOut:
    return VersionOut(
        id=version.id,
        label=version.label,
        source_format=version.source_format,
        origin=version.origin,
        is_active=version.is_active,
        has_latex=bool(version.content_latex),
        tailored_for_posting_id=version.tailored_for_posting_id,
        change_summary=version.change_summary,
        created_at=version.created_at.isoformat(),
        preview=(version.content_text or "")[:200],
    )


def _activate(db: Session, user_id: str, version: ResumeVersion) -> None:
    """Exactly one active version per user, and the profile mirrors it.

    The mirror exists because the agents' get_resume tool reads UserProfile — keeping it
    in sync here means the tool never has to know about versioning at all.
    """
    db.query(ResumeVersion).filter(
        ResumeVersion.user_id == user_id, ResumeVersion.id != version.id
    ).update({"is_active": False})
    version.is_active = True

    profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
    if profile is None:
        profile = UserProfile(user_id=user_id)
        db.add(profile)
    profile.resume_text = version.content_text
    profile.resume_latex = version.content_latex


@router.get("/versions", response_model=list[VersionOut])
def list_versions(claims: dict = Depends(get_current_claims), db: Session = Depends(get_db)):
    versions = (
        db.query(ResumeVersion)
        .filter(ResumeVersion.user_id == claims["sub"])
        .order_by(ResumeVersion.created_at.desc())
        .all()
    )
    return [_to_out(v) for v in versions]


@router.get("/active")
def get_active(claims: dict = Depends(get_current_claims), db: Session = Depends(get_db)):
    version = (
        db.query(ResumeVersion)
        .filter(ResumeVersion.user_id == claims["sub"], ResumeVersion.is_active.is_(True))
        .first()
    )
    if not version:
        return {"exists": False, "content_text": "", "content_latex": None}

    return {
        "exists": True,
        "id": version.id,
        "label": version.label,
        "content_text": version.content_text,
        "content_latex": version.content_latex,
        "source_format": version.source_format,
    }


@router.post("/upload", response_model=VersionOut, status_code=status.HTTP_201_CREATED)
async def upload_resume(
    file: UploadFile = File(...),
    label: str | None = None,
    claims: dict = Depends(get_current_claims),
    db: Session = Depends(get_db),
):
    data = await file.read()

    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File larger than 5 MB")
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty file")

    try:
        text, latex, detected = parse_upload(file.filename or "", data)
    except ResumeParseError as exc:
        # 400 with the parser's own message: these errors are actionable by the user
        # ("it's a scanned PDF", "save as .docx"), so surfacing them verbatim is right.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    if not text.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No readable text found in that file")

    version = ResumeVersion(
        user_id=claims["sub"],
        label=label or f"{detected}-upload-{file.filename}"[:80],
        content_text=text,
        content_latex=latex,
        source_format=detected,
        origin="upload",
    )
    db.add(version)
    db.flush()
    _activate(db, claims["sub"], version)
    db.commit()
    db.refresh(version)

    return _to_out(version)


class SaveRequest(BaseModel):
    content_text: str
    content_latex: str | None = None
    label: str | None = None


@router.post("/save", response_model=VersionOut, status_code=status.HTTP_201_CREATED)
def save_edit(
    payload: SaveRequest,
    claims: dict = Depends(get_current_claims),
    db: Session = Depends(get_db),
):
    """Manual edit from the editor — saved as a NEW version, never in place."""
    count = db.query(ResumeVersion).filter(ResumeVersion.user_id == claims["sub"]).count()

    text = payload.content_text
    if payload.content_latex and not text.strip():
        text = latex_to_text(payload.content_latex)

    version = ResumeVersion(
        user_id=claims["sub"],
        label=payload.label or f"edit-{count + 1}",
        content_text=text,
        content_latex=payload.content_latex,
        source_format="tex" if payload.content_latex else "txt",
        origin="manual_edit",
    )
    db.add(version)
    db.flush()
    _activate(db, claims["sub"], version)
    db.commit()
    db.refresh(version)

    return _to_out(version)


class AgentSaveRequest(BaseModel):
    content_text: str
    content_latex: str | None = None
    label: str | None = None
    change_summary: str | None = None
    tailored_for_posting_id: str | None = None


@router.post("/agent-save", response_model=VersionOut, status_code=status.HTTP_201_CREATED)
def agent_save(
    payload: AgentSaveRequest,
    claims: dict = Depends(get_current_claims),
    db: Session = Depends(get_db),
):
    """Where the resume_tailor agent writes its output.

    Separate from /save so the origin is recorded honestly as `ai_tailored` — you can
    always tell which versions a model wrote and which you wrote. The new version becomes
    active, and the previous one is one click away in the version list.
    """
    version = ResumeVersion(
        user_id=claims["sub"],
        label=payload.label or "ai-tailored",
        content_text=payload.content_text,
        content_latex=payload.content_latex,
        source_format="tex" if payload.content_latex else "txt",
        origin="ai_tailored",
        change_summary=payload.change_summary,
        tailored_for_posting_id=payload.tailored_for_posting_id,
    )
    db.add(version)
    db.flush()
    _activate(db, claims["sub"], version)
    db.commit()
    db.refresh(version)
    return _to_out(version)


@router.post("/versions/{version_id}/activate", response_model=VersionOut)
def activate_version(
    version_id: str,
    claims: dict = Depends(get_current_claims),
    db: Session = Depends(get_db),
):
    """Roll back to any previous version — the payoff of never overwriting."""
    version = (
        db.query(ResumeVersion)
        .filter(ResumeVersion.id == version_id, ResumeVersion.user_id == claims["sub"])
        .first()
    )
    if not version:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Version not found")

    _activate(db, claims["sub"], version)
    db.commit()
    db.refresh(version)
    return _to_out(version)


def _compile_latex_to_pdf(latex: str) -> bytes | None:
    """Compile LaTeX to PDF if a TeX engine is available; None if not installed.

    Returning None rather than raising lets the caller degrade to offering the .tex file,
    which is genuinely useful on its own (Overleaf compiles it in one paste). Shipping a
    full TeX distribution in this image would add gigabytes for a feature most users
    won't hit.

    tectonic first: it's a single binary that fetches only the packages a document needs,
    which is far lighter than a full texlive install.
    """
    engine = shutil.which("tectonic") or shutil.which("pdflatex")
    if not engine:
        return None

    with tempfile.TemporaryDirectory() as tmp:
        tex_path = Path(tmp) / "resume.tex"
        tex_path.write_text(latex, encoding="utf-8")

        command = (
            [engine, "--outdir", tmp, str(tex_path)]
            if "tectonic" in engine
            else [engine, "-interaction=nonstopmode", "-output-directory", tmp, str(tex_path)]
        )
        try:
            subprocess.run(command, cwd=tmp, capture_output=True, timeout=90)
        except (subprocess.TimeoutExpired, OSError):
            return None

        pdf_path = Path(tmp) / "resume.pdf"
        return pdf_path.read_bytes() if pdf_path.exists() else None


@router.get("/download")
def download_resume(
    fmt: str = Query("tex", pattern="^(tex|txt|pdf)$"),
    claims: dict = Depends(get_current_claims),
    db: Session = Depends(get_db),
):
    version = (
        db.query(ResumeVersion)
        .filter(ResumeVersion.user_id == claims["sub"], ResumeVersion.is_active.is_(True))
        .first()
    )
    if not version:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No active resume")

    if fmt == "txt":
        return Response(
            content=version.content_text,
            media_type="text/plain",
            headers={"Content-Disposition": 'attachment; filename="resume.txt"'},
        )

    if fmt == "tex":
        if not version.content_latex:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "This version has no LaTeX. Upload a .tex file, or ask the assistant to "
                "convert your resume to LaTeX first.",
            )
        return Response(
            content=version.content_latex,
            media_type="application/x-tex",
            headers={"Content-Disposition": 'attachment; filename="resume.tex"'},
        )

    # fmt == "pdf"
    if not version.content_latex:
        raise HTTPException(status.HTTP_409_CONFLICT, "PDF export needs a LaTeX version")

    pdf = _compile_latex_to_pdf(version.content_latex)
    if pdf is None:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            "No TeX engine installed in this container. Download the .tex and compile it "
            "(Overleaf works in one paste), or install tectonic to enable PDF export.",
        )

    return StreamingResponse(
        io.BytesIO(pdf),
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="resume.pdf"'},
    )
