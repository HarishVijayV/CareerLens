FROM python:3.11-slim

WORKDIR /app

# TeX engine for resume PDF export. texlive-latex-recommended + fonts-recommended is a
# few hundred MB — a real cost, and worth it here because "download a PDF I can actually
# send" is the point of the resume feature; shipping only .tex would push that work back
# onto the user.
#
# NOT full texlive (several GB). These packages cover article/geometry/enumitem/hyperref,
# which is exactly what the resume_tailor agent is instructed to limit itself to.
# If a resume needs something exotic, the .tex download still works and Overleaf compiles
# it in one paste.
RUN apt-get update && apt-get install -y --no-install-recommends \
        texlive-latex-base \
        texlive-latex-recommended \
        texlive-fonts-recommended \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
