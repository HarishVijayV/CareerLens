"""
Tests for resume file parsing — the layer most likely to break silently on a real user's
file, because every resume is formatted differently.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "auth-service"))

from app.core.resume_parser import ResumeParseError, latex_to_text, parse_upload  # noqa: E402

SAMPLE_LATEX = r"""
\documentclass[11pt]{article}
\usepackage{geometry}
% a comment that should vanish
\begin{document}
\begin{center}{\Large \textbf{Harish Vijay V}}\
me@example.com $\cdot$ +91 9677473107\end{center}
\section*{Education}
\textbf{B.Tech CSE (AI)}, Amrita \hfill CGPA: 8.88
\section*{Publications}
\begin{itemize}
  \item \textbf{Multimodal Misogyny Detection} --- NAACL 2025
\end{itemize}
\end{document}
"""


class TestLatexToText:
    def test_keeps_visible_content(self):
        text = latex_to_text(SAMPLE_LATEX)
        assert "Harish Vijay V" in text
        assert "B.Tech CSE (AI)" in text
        assert "Multimodal Misogyny Detection" in text
        assert "8.88" in text

    def test_strips_markup_and_comments(self):
        text = latex_to_text(SAMPLE_LATEX)
        assert "\documentclass" not in text
        assert "\textbf" not in text
        assert "a comment that should vanish" not in text
        assert "{" not in text and "}" not in text

    def test_no_stray_math_delimiters(self):
        """Regression: inline math like $\cdot$ used to leave "$$" behind, which then
        went straight into the agent's prompt as noise."""
        assert "$$" not in latex_to_text(SAMPLE_LATEX)

    def test_items_become_bullets(self):
        assert "- Multimodal" in latex_to_text(SAMPLE_LATEX)


class TestParseUpload:
    def test_tex_returns_both_text_and_latex(self):
        text, latex, fmt = parse_upload("resume.tex", SAMPLE_LATEX.encode())
        assert fmt == "tex"
        assert latex == SAMPLE_LATEX          # raw source preserved for editing
        assert "Harish Vijay V" in text        # readable view for the agents

    def test_plain_text_passes_through(self):
        text, latex, fmt = parse_upload("resume.txt", b"Harish Vijay V\nData Engineer")
        assert fmt == "txt"
        assert latex is None
        assert "Data Engineer" in text

    def test_legacy_doc_rejected_with_actionable_message(self):
        with pytest.raises(ResumeParseError, match="\.docx"):
            parse_upload("resume.doc", b"\xd0\xcf\x11\xe0")

    def test_unknown_extension_rejected(self):
        with pytest.raises(ResumeParseError, match="Unsupported"):
            parse_upload("resume.pages", b"whatever")

    def test_corrupt_pdf_raises_clear_error(self):
        with pytest.raises(ResumeParseError):
            parse_upload("resume.pdf", b"not actually a pdf")
