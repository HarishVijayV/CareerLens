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
    "description": "Search real job postings in the warehouse. Use this to find jobs matching criteria.",
    "input_schema": {
        "type": "object",
        "properties": {
            "q": {"type": "string", "description": "free-text match on job title"},
            "skill": {"type": "string", "description": "require this exact skill, e.g. 'Spark'"},
            "seniority": {"type": "string", "enum": ["junior", "mid", "senior"]},
            "remote_only": {"type": "boolean"},
            "min_salary": {"type": "integer"},
            "limit": {"type": "integer", "description": "max results, default 10"},
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

SAVE_RESUME_TOOL = {
    "name": "save_tailored_resume",
    "description": "Save a rewritten resume to the user's profile. Only call this once you have a final version.",
    "input_schema": {
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "resume_text": {"type": "string", "description": "the complete rewritten resume"},
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
        "description": "Rewrites the user's resume for one specific job.",
        "tools": [GET_RESUME_TOOL, GET_JOB_TOOL, SAVE_RESUME_TOOL],
        "system_prompt": (
            "You tailor a resume to one specific job posting.\n"
            "Steps: call get_resume for the current resume, call get_job for the target "
            "role's real requirements, then rewrite.\n"
            "RULES — these matter more than style:\n"
            "1. Never invent experience, employers, dates, or metrics. Rephrase and "
            "reprioritize what is already there; a resume that lies is worse than a weak one.\n"
            "2. Mirror the posting's terminology where it honestly applies (many companies "
            "filter on keywords).\n"
            "3. Lead with the bullets most relevant to THIS job.\n"
            "Call save_tailored_resume once, with the final full text, then summarize what "
            "you changed and why."
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
