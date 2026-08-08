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
    has_original: bool

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
        has_original=bool(version.original_file),
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
        "has_original_pdf": version.source_format == "pdf" and bool(version.original_file),
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
        # Keep the original bytes: PDF extraction is lossy, so this is the only faithful
        # copy of what the user actually uploaded, and it's what /preview serves back.
        original_file=data,
        original_filename=file.filename,
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


class LatexCompileError(Exception):
    """Compilation ran but produced no PDF — carries the compiler's own error lines."""


def _compile_latex_to_pdf(latex: str) -> bytes:
    """Compile LaTeX to a PDF.

    Raises FileNotFoundError if no TeX engine is installed, and LatexCompileError with the
    compiler's actual message if the document itself is broken.

    Those two cases MUST be distinguished. An earlier version returned None for both, so a
    document with one bad package reported "No TeX engine installed" — sending you off to
    install software that was already there while the real error (a single line in the
    LaTeX log) stayed hidden. An error message that names the wrong cause is worse than no
    message.

    tectonic is preferred when present: it downloads only the packages a document needs,
    so it compiles more documents than a minimal texlive install.
    """
    engine = shutil.which("tectonic") or shutil.which("pdflatex")
    if not engine:
        raise FileNotFoundError("No TeX engine installed")

    with tempfile.TemporaryDirectory() as tmp:
        tex_path = Path(tmp) / "resume.tex"
        tex_path.write_text(latex, encoding="utf-8")

        command = (
            [engine, "--outdir", tmp, str(tex_path)]
            if "tectonic" in engine
            # -interaction=nonstopmode stops pdflatex prompting on error and hanging
            # forever waiting for input that will never arrive in a container.
            else [engine, "-interaction=nonstopmode", "-halt-on-error",
                  "-output-directory", tmp, str(tex_path)]
        )

        try:
            result = subprocess.run(command, cwd=tmp, capture_output=True, timeout=120)
        except subprocess.TimeoutExpired:
            raise LatexCompileError("Compilation timed out after 120s (possible infinite loop)")

        pdf_path = Path(tmp) / "resume.pdf"
        if pdf_path.exists():
            return pdf_path.read_bytes()

        # No PDF: surface the lines that actually explain why. LaTeX logs are enormous and
        # mostly noise; the lines starting with "!" are the real errors.
        output = (result.stdout or b"").decode("utf-8", errors="replace")
        errors = [ln for ln in output.splitlines() if ln.startswith("!") or "Undefined" in ln]
        detail = "\n".join(errors[:6]) or output[-600:] or "unknown error"
        raise LatexCompileError(detail)


@router.delete("/versions/{version_id}")
def delete_version(
    version_id: str,
    claims: dict = Depends(get_current_claims),
    db: Session = Depends(get_db),
):
    """Delete a resume version.

    Two guards, both about not leaving the account in a broken state:

    1. The ACTIVE version can't be deleted directly. Deleting it would leave the agents'
       get_resume tool pointing at nothing. Activate a different version first — that's an
       explicit choice about what your resume now is, rather than a silent side effect.

    2. The LAST remaining version can't be deleted either, since the profile mirror would
       be left dangling. Upload a replacement first.
    """
    version = (
        db.query(ResumeVersion)
        .filter(ResumeVersion.id == version_id, ResumeVersion.user_id == claims["sub"])
        .first()
    )
    if not version:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Version not found")

    total = db.query(ResumeVersion).filter(ResumeVersion.user_id == claims["sub"]).count()
    if total <= 1:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This is your only resume. Upload a replacement before deleting it.",
        )

    if version.is_active:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This version is active. Select a different version first, then delete this one.",
        )

    db.delete(version)
    db.commit()
    return {"deleted": True, "label": version.label}


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
    #
    # If the user uploaded a PDF, serve THAT rather than refusing. Previously an uploaded
    # PDF had no LaTeX, so "download PDF" failed on a resume that literally started life
    # as a PDF — a confusing dead end.
    if version.source_format == "pdf" and version.original_file:
        return StreamingResponse(
            io.BytesIO(version.original_file),
            media_type="application/pdf",
            headers={"Content-Disposition": 'inline; filename="resume.pdf"'},
        )

    if not version.content_latex:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This version has no LaTeX to compile. Ask the assistant to "
            "\"convert my resume to LaTeX\" first, then export.",
        )

    try:
        pdf = _compile_latex_to_pdf(version.content_latex)
    except FileNotFoundError:
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            "No TeX engine in this container. Download the .tex and compile it "
            "(Overleaf works in one paste).",
        )
    except LatexCompileError as exc:
        # 422, not 501: the document is the problem, not the server. The compiler's own
        # message goes back so the assistant can be asked to fix that specific line.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"LaTeX failed to compile:\n{exc}\n\n"
            "Ask the assistant to fix it, or simplify the preamble to standard packages "
            "(article, geometry, enumitem, hyperref).",
        )

    return StreamingResponse(
        io.BytesIO(pdf),
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="resume.pdf"'},
    )
