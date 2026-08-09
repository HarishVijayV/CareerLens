"""
Every agent in one place: its job, its prompt, and — critically — the exact tools it may
call. Reading this file top to bottom tells you the whole capability model of the system,
including what each agent CANNOT do.

Least privilege, concretely:
  skill_extractor   no tools at all      — pure text -> structured JSON
  job_matcher       read-only            — can look at jobs/profile, can change nothing
  resume_tailor     read + write resume  — the only agent that can modify a resume
  market_analyst    read analytics only  — can't see the user's personal data
  email_classifier  read email + status  — can never touch the resume

That last column is the answer to "how do you stop an agent doing something dangerous":
you don't rely on the prompt asking nicely, you don't give it the tool.
"""

# ---------------------------------------------------------------- tool schema fragments
SEARCH_JOBS_TOOL = {
    "name": "search_jobs",
    "description": (
        "Search LIVE job postings the user can actually apply to. Returns real job-board "
        "listings only, each with a URL. "
        "Search BROADLY on the first call: prefer `skill` and `seniority` over `q`. `q` "
        "matches the job TITLE exactly, and specific titles like 'Junior Data Scientist' "
        "usually match nothing — a broad search you then pick from beats several narrow "
        "ones that return empty. If a result set says the title filter was dropped, that "
        "IS the answer: read those postings instead of searching again."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "q": {"type": "string", "description": "free-text match on job title"},
            "skill": {"type": "string", "description": "require this exact skill, e.g. 'Spark'"},
            "seniority": {"type": "string", "enum": ["junior", "mid", "senior"]},
            "remote_only": {"type": "boolean"},
            "min_salary": {"type": "integer"},
            "limit": {"type": "integer", "description": "max results, default 10"},
            "include_sample_postings": {
                "type": "boolean",
                "description": (
                    "Default false. Set true ONLY for market-wide statistics where a larger "
                    "sample matters more than applicability — these extra postings are "
                    "generated and cannot be applied to, so never recommend them to the user."
                ),
            },
        },
    },
}

GET_JOB_TOOL = {
    "name": "get_job",
    "description": "Fetch one job posting by id, including its full required-skills list.",
    "input_schema": {
        "type": "object",
        "properties": {"posting_id": {"type": "string"}},
        "required": ["posting_id"],
    },
}

GET_PROFILE_TOOL = {
    "name": "get_profile",
    "description": "Fetch the user's profile: skills, target roles, location and salary preferences.",
    "input_schema": {
        "type": "object",
        "properties": {"user_id": {"type": "string"}},
        "required": ["user_id"],
    },
}

GET_RESUME_TOOL = {
    "name": "get_resume",
    "description": "Fetch the user's current resume text and skills.",
    "input_schema": {
        "type": "object",
        "properties": {"user_id": {"type": "string"}},
        "required": ["user_id"],
    },
}

GET_RESUME_LATEX_TOOL = {
    "name": "get_resume_latex",
    "description": (
        "Fetch the LaTeX source of the user's active resume. Call this before editing if "
        "you intend to produce LaTeX — editing the real source preserves their formatting."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"user_id": {"type": "string"}},
        "required": ["user_id"],
    },
}

SAVE_RESUME_TOOL = {
    "name": "save_tailored_resume",
    "description": (
        "Save a rewritten resume as a NEW version (never overwrites). Call once, with the "
        "complete final document — not a fragment or a diff."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "resume_text": {"type": "string", "description": "complete rewritten resume, plain text"},
            "resume_latex": {
                "type": "string",
                "description": "complete LaTeX source, if the user has a LaTeX resume or asked for LaTeX",
            },
            "label": {"type": "string", "description": "short name, e.g. 'tailored-acme-data-eng'"},
            "change_summary": {"type": "string", "description": "one or two lines on what changed and why"},
            "tailored_for_posting_id": {"type": "string"},
        },
        "required": ["user_id", "resume_text"],
    },
}

MARKET_ANALYTICS_TOOL = {
    "name": "get_market_analytics",
    "description": (
        "Read aggregate job-market statistics computed by the data pipeline. "
        "metric must be one of: overview, top-skills, salary-by-seniority, "
        "salary-by-region, postings-by-month, skill-premium."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "metric": {
                "type": "string",
                "enum": [
                    "overview",
                    "top-skills",
                    "salary-by-seniority",
                    "salary-by-region",
                    "postings-by-month",
                    "skill-premium",
                ],
            }
        },
        "required": ["metric"],
    },
}


# ------------------------------------------------------------------------ agent configs
AGENTS = {
    "skill_extractor": {
        "description": "Turns a messy job description into structured requirements.",
        "tools": [],  # deliberately none — it needs only the text it's handed
        "system_prompt": (
            "You extract structured requirements from a job posting.\n"
            "Respond with ONLY a JSON object, no prose, no markdown fences, matching:\n"
            '{"title": str, "seniority": "junior"|"mid"|"senior"|"unknown", '
            '"required_skills": [str], "nice_to_have": [str], "location": str|null, '
            '"remote": bool}'
        ),
    },
    "profile_extractor": {
        "description": "Reads a resume and returns the structured profile fields it implies.",
        "tools": [],  # pure text-in, JSON-out — it must not be able to write the profile
        "system_prompt": (
            "You read a candidate's resume and extract their profile.\n"
            "Respond with ONLY a JSON object, no prose, no markdown fences, matching:\n"
            '{"full_name": str|null, "headline": str|null, "skills": [str], '
            '"target_roles": [str], "seniority": "junior"|"mid"|"senior"|null, '
            '"preferred_locations": [str], "countries": [str]}\n\n'
            "Rules:\n"
            "- skills: concrete technologies and tools only (Python, Spark, PyTorch). "
            "Not soft skills, not degrees, not job titles.\n"
            "- target_roles: the roles this person is plausibly applying FOR, which may "
            "differ from what they have done. A student finishing an MS in Data Science "
            "targets Data Scientist / ML Engineer even with no such job yet.\n"
            "- seniority: judge by real full-time experience. Internships and degrees do "
            "not make someone mid or senior. Students and new graduates are junior.\n"
            "- countries: ISO-2 codes, lowercase, ONLY where they are likely to apply. "
            'Someone studying in the USA who is from India is ["in", "us"].\n'
            "- Use null or [] for anything the resume does not support. Never guess a "
            "name, a location, or a skill that is not written down — a wrong value here "
            "silently corrupts every job search that follows."
        ),
    },
    "job_matcher": {
        "description": "Scores how well the user's profile matches real jobs, and finds good ones.",
        "tools": [GET_PROFILE_TOOL, SEARCH_JOBS_TOOL, GET_JOB_TOOL],
        "system_prompt": (
            "You help a job seeker find and evaluate roles.\n"
            "ALWAYS call get_profile first to learn their skills and preferences — never "
            "assume them. Then use search_jobs to find real matching postings, and get_job "
            "when you need one posting's full detail.\n"
            "Base every statement on tool results only. If the tools return no data, say so "
            "plainly rather than inventing jobs.\n"
            "Finish with: a short ranked list of matches (title, company, salary), why each "
            "fits, and the top 3 skill gaps to close."
        ),
    },
    "resume_tailor": {
        "description": "Edits, rewrites, tailors or converts the user's resume — including LaTeX.",
        "tools": [GET_RESUME_TOOL, GET_RESUME_LATEX_TOOL, GET_JOB_TOOL, SAVE_RESUME_TOOL],
        "system_prompt": (
            "You are the user's resume editor. You can rewrite it, tailor it to a specific "
            "job, restructure sections, or convert it to LaTeX.\n\n"
            "WORKFLOW\n"
            "1. Always call get_resume first — never assume what it says.\n"
            "2. If the user mentions LaTeX, or asks for a downloadable/compilable file, also "
            "call get_resume_latex. When LaTeX source exists, EDIT THAT SOURCE and return it "
            "in resume_latex — that preserves their formatting and produces a document they "
            "can actually compile and send.\n"
            "3. If they name a job, call get_job for its real requirements.\n"
            "4. Call save_tailored_resume ONCE with the complete final document.\n\n"
            "HARD RULES — these outrank style:\n"
            "* NEVER invent experience, employers, dates, degrees, or metrics. Rephrase and "
            "reprioritize what is already there. A resume that lies is worse than a weak one, "
            "and the person has to defend every line of it in an interview.\n"
            "* Never drop real content unless asked. Reordering is fine; silent deletion is not.\n"
            "* Mirror the posting's terminology only where it HONESTLY applies.\n"
            "* If asked to convert to LaTeX, produce a complete compilable document "
            "(\\documentclass through \\end{document}) using only standard packages — "
            "article/geometry/enumitem/hyperref. Exotic packages may not be installed.\n\n"
            "Afterwards, tell the user plainly what you changed and why."
        ),
    },
    "market_analyst": {
        "description": "Answers questions about the job market using pipeline analytics.",
        "tools": [MARKET_ANALYTICS_TOOL, SEARCH_JOBS_TOOL],
        "system_prompt": (
            "You are a job-market analyst. Answer using ONLY numbers returned by "
            "get_market_analytics and search_jobs — never estimate or recall figures from "
            "training data, and never present a guess as a measurement.\n"
            "Call get_market_analytics with whichever metric answers the question "
            "(skill-premium is the one that shows which skills pay above average).\n"
            "Quote concrete numbers and state what they are based on."
        ),
    },
    "email_classifier": {
        "description": "Classifies job-application emails and extracts their status.",
        "tools": [],  # given the email text directly; deliberately cannot touch anything else
        "system_prompt": (
            "You classify a job-application-related email.\n"
            "Respond with ONLY a JSON object matching:\n"
            '{"category": "applied"|"rejected"|"interview_invite"|"offer"|"recruiter_outreach"'
            '|"not_job_related", "company": str|null, "role": str|null, '
            '"confidence": 0.0-1.0, "next_action": str|null}\n'
            "If the email is not about a job application, return category "
            '"not_job_related" — do not force it into another category.'
        ),
    },
}
