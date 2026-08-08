FROM python:3.11-slim

WORKDIR /app

# TeX engine for resume PDF export.
#
# texlive-latex-EXTRA is the important one and was initially missed. The agent's prompt
# names article/geometry/enumitem/hyperref as safe, but `enumitem` and `titlesec` — which
# essentially every resume template uses for bullet spacing and section headings — live in
# -extra, not -recommended. The result was a real compile failure on a perfectly ordinary
# resume: the code promised a package the image didn't have.
#
# Lesson worth keeping: if you tell a model which packages are available, the image has to
# actually contain them. The constraint and the environment must agree, or the constraint
# is a lie that surfaces as a user-facing error.
#
# Still NOT full texlive (several GB). This set covers standard resume templates; anything
# more exotic still downloads as .tex and compiles in Overleaf.
RUN apt-get update && apt-get install -y --no-install-recommends \
        texlive-latex-base \
        texlive-latex-recommended \
        texlive-latex-extra \
        texlive-fonts-recommended \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
