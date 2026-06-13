import json
import os
import logging
import requests
from pathlib import Path

log = logging.getLogger("ph3b3.resume")

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False
    log.warning("beautifulsoup4 not installed — URL scraping unavailable")

_SCRAPE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

PROFILE_PATH = Path.home() / "ph3b3_data" / "candidate_profile.json"

_EMPTY_PROFILE: dict = {
    "skills": [],
    "experience": [],
    "certifications": [],
    "projects": [],
    "notes": [],
}

# Terms whose presence in a posting is automatically worth flagging
_RED_FLAG_TERMS = [
    "rockstar", "ninja", "guru", "unicorn", "10x engineer",
    "self-starter", "fast-paced", "wear many hats", "unlimited pto",
    "competitive salary", "like a family", "startup mentality",
    "hustle", "scrappy", "unlimited growth", "culture fit",
    "work hard play hard", "entrepreneurial spirit",
]


class ResumeModule:
    def __init__(self):
        self.ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self.model = os.getenv("PH3B3_HEAVY_MODEL", os.getenv("PH3B3_MODEL", "hermes3"))
        log.info("Resume module ready.")

    def _is_url(self, source: str) -> bool:
        return source.strip().startswith(("http://", "https://"))

    def _fetch_text(self, url: str) -> str:
        if not BS4_AVAILABLE:
            return "[URL scraping unavailable — beautifulsoup4 not installed. Paste the job text directly.]"

        if "linkedin.com" in url:
            return "[LinkedIn requires authentication to scrape. Paste the job description text directly.]"

        try:
            resp = requests.get(url, headers=_SCRAPE_HEADERS, timeout=15, allow_redirects=True)
            resp.raise_for_status()
        except requests.RequestException as e:
            return f"[Could not fetch URL: {e}]"

        soup = BeautifulSoup(resp.text, "lxml")

        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "iframe", "noscript"]):
            tag.decompose()

        # Try to find the main job content block before falling back to full page text
        for selector in [
            '[class*="job-description"]', '[class*="jobDescription"]',
            '[class*="job-details"]',    '[id*="job-description"]',
            '[class*="description"]',    "article",
            "main",                      '[role="main"]',
        ]:
            target = soup.select_one(selector)
            if target:
                text = target.get_text(separator="\n", strip=True)
                if len(text) > 200:
                    return text

        return soup.get_text(separator="\n", strip=True)

    def _auto_flags(self, text: str) -> list[str]:
        lower = text.lower()
        return [f'"{term}"' for term in _RED_FLAG_TERMS if term in lower]

    def _llm_extract(self, text: str, auto_flags: list[str]) -> str:
        excerpt = text[:4500]

        flag_note = ""
        if auto_flags:
            flag_note = (
                f"\n\nNote: the following red-flag terms were detected verbatim in the posting: "
                f"{', '.join(auto_flags)}. Make sure they appear in your RED FLAGS section."
            )

        prompt = (
            "You are a blunt, experienced technical recruiter who has read thousands of job postings "
            "and seen every corporate HR trick. Analyze the job posting below and extract each field. "
            "Do NOT invent salary information — if no salary or range is stated, write 'Not disclosed'. "
            "Treat buzzwords like 'rockstar', 'ninja', 'guru', 'passionate', 'self-starter', "
            "'fast-paced', 'wear many hats', 'unlimited PTO', 'competitive salary' (without a number), "
            "and 'like a family' as red flags, not requirements. "
            "The VERDICT must be one sentence — honest, dry, no corporate cheerleading.\n\n"
            f"JOB POSTING:\n{excerpt}"
            f"{flag_note}\n\n"
            "Respond in EXACTLY this format, nothing before or after:\n\n"
            "JOB TITLE: [title or Unknown]\n"
            "COMPANY: [company name or Unknown]\n"
            "LOCATION: [city/state, remote, hybrid, or Unknown]\n"
            "SALARY: [stated range, or 'Not disclosed']\n\n"
            "HARD REQUIREMENTS:\n"
            "- [each must-have on its own line]\n\n"
            "SOFT REQUIREMENTS:\n"
            "- [each nice-to-have on its own line, or '- None stated']\n\n"
            "RED FLAGS:\n"
            "- [specific concerns — vague language, missing salary, buzzword abuse, unrealistic scope, signs of dysfunction]\n\n"
            "CULTURE SIGNALS:\n"
            "- [what the language actually reveals between the lines]\n\n"
            "VERDICT: [one sentence]"
        )

        try:
            resp = requests.post(
                f"{self.ollama_host}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.3, "num_ctx": 6144},
                },
                timeout=120,
            )
            resp.raise_for_status()
            return resp.json().get("response", "").strip()
        except Exception as e:
            log.error(f"LLM extraction failed: {e}")
            return f"Extraction error: {e}"

    def extract_job_posting(self, source: str) -> str:
        source = source.strip()
        if not source:
            return "No job posting provided."

        if self._is_url(source):
            log.info(f"Fetching job URL: {source[:80]}")
            text = self._fetch_text(source)
            if text.startswith("["):
                return text
        else:
            text = source

        if len(text) < 50:
            return "Job posting text too short to analyze."

        auto_flags = self._auto_flags(text)
        return self._llm_extract(text, auto_flags)

    # ------------------------------------------------------------------
    # Profile persistence
    # ------------------------------------------------------------------

    def _load_profile(self) -> dict:
        if not PROFILE_PATH.exists():
            return {k: list(v) if isinstance(v, list) else v for k, v in _EMPTY_PROFILE.items()}
        try:
            return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Profile load failed: {e} — returning empty profile")
            return {k: list(v) if isinstance(v, list) else v for k, v in _EMPTY_PROFILE.items()}

    def _save_profile(self, profile: dict) -> None:
        PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        PROFILE_PATH.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")

    def _format_profile(self, profile: dict) -> str:
        lines: list[str] = []

        if profile["skills"]:
            lines.append("SKILLS:\n  " + ", ".join(profile["skills"]))
        else:
            lines.append("SKILLS: (none on file)")

        lines.append("")

        if profile["experience"]:
            lines.append("EXPERIENCE:")
            for exp in profile["experience"]:
                dur = f" ({exp.get('duration', '')})" if exp.get("duration") else ""
                lines.append(f"  {exp['role']} @ {exp['org']}{dur}")
                for b in exp.get("bullets", []):
                    lines.append(f"    • {b}")
        else:
            lines.append("EXPERIENCE: (none on file)")

        lines.append("")

        if profile["certifications"]:
            lines.append("CERTIFICATIONS:")
            for cert in profile["certifications"]:
                yr = f" ({cert['year']})" if cert.get("year") else ""
                issuer = f" — {cert['issuer']}" if cert.get("issuer") else ""
                lines.append(f"  • {cert['name']}{issuer}{yr}")
        else:
            lines.append("CERTIFICATIONS: (none on file)")

        lines.append("")

        if profile["projects"]:
            lines.append("PROJECTS:")
            for proj in profile["projects"]:
                tech = f" [{', '.join(proj['tech'])}]" if proj.get("tech") else ""
                desc = f": {proj['description']}" if proj.get("description") else ""
                lines.append(f"  {proj['name']}{tech}{desc}")
                for b in proj.get("bullets", []):
                    lines.append(f"    • {b}")
        else:
            lines.append("PROJECTS: (none on file)")

        lines.append("")

        if profile["notes"]:
            lines.append("NOTES:")
            for note in profile["notes"]:
                lines.append(f"  • {note}")

        return "\n".join(lines).strip()

    # ------------------------------------------------------------------
    # Profile tool handlers
    # ------------------------------------------------------------------

    def profile_get(self) -> str:
        profile = self._load_profile()
        return self._format_profile(profile)

    def profile_add_skill(self, skill: str) -> str:
        profile = self._load_profile()
        incoming = [s.strip() for s in skill.split(",") if s.strip()]
        added = [s for s in incoming if s not in profile["skills"]]
        profile["skills"].extend(added)
        self._save_profile(profile)
        if added:
            return f"Added: {', '.join(added)}"
        return "All skills already on file — nothing added."

    def profile_add_experience(self, role: str, org: str, duration: str = "", bullets: list[str] | None = None) -> str:
        profile = self._load_profile()
        profile["experience"].append({
            "role": role,
            "org": org,
            "duration": duration,
            "bullets": bullets or [],
        })
        self._save_profile(profile)
        return f"Experience added: {role} @ {org}"

    def profile_add_certification(self, name: str, issuer: str = "", year: int | None = None) -> str:
        profile = self._load_profile()
        profile["certifications"].append({"name": name, "issuer": issuer, "year": year})
        self._save_profile(profile)
        return f"Certification added: {name}"

    def profile_add_project(self, name: str, description: str = "", tech: list[str] | None = None, bullets: list[str] | None = None) -> str:
        profile = self._load_profile()
        profile["projects"].append({
            "name": name,
            "description": description,
            "tech": tech or [],
            "bullets": bullets or [],
        })
        self._save_profile(profile)
        return f"Project added: {name}"

    def profile_add_note(self, note: str) -> str:
        profile = self._load_profile()
        profile["notes"].append(note.strip())
        self._save_profile(profile)
        return f"Note saved."

    # ------------------------------------------------------------------
    # Match engine
    # ------------------------------------------------------------------

    def match_candidate_to_job(self, job_analysis: str) -> str:
        profile = self._load_profile()
        if not any(profile[k] for k in ("skills", "experience", "certifications", "projects")):
            return (
                "Candidate profile is empty. Add skills, experience, and projects first "
                "using profile_add_skill, profile_add_experience, and profile_add_project."
            )

        profile_text = self._format_profile(profile)
        prompt = (
            "You are a technical hiring manager running an honest candidate-job match. "
            "Do not be encouraging for its own sake. Call gaps what they are.\n\n"
            f"CANDIDATE PROFILE:\n{profile_text}\n\n"
            f"JOB ANALYSIS:\n{job_analysis[:3000]}\n\n"
            "Respond in EXACTLY this format, nothing before or after:\n\n"
            "MATCH SCORE: [X]/[Y] hard requirements met\n\n"
            "GAPS:\n"
            "- [requirement]: [MET / PARTIAL / MISSING] — [one honest line]\n\n"
            "LEAD WITH:\n"
            "[One short paragraph — given this specific posting, what is the strongest angle "
            "for this candidate's application? What to emphasize at the top of the resume and in a cover note.]\n\n"
            "TAILORED BULLETS:\n"
            "- [For each hard requirement the candidate MEETS: one achievement-framed bullet "
            "grounded strictly in their actual profile. Do not invent experience.]\n\n"
            "VERDICT: [WORTH APPLYING / STRETCH / SKIP] — [one sentence reason]"
        )

        try:
            resp = requests.post(
                f"{self.ollama_host}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.3, "num_ctx": 8192},
                },
                timeout=150,
            )
            resp.raise_for_status()
            return resp.json().get("response", "").strip()
        except Exception as e:
            log.error(f"Match analysis failed: {e}")
            return f"Match analysis error: {e}"

    # ------------------------------------------------------------------
    # Bullet drafter
    # ------------------------------------------------------------------

    def draft_resume_section(self, requirement: str, profile_entry: str) -> str:
        prompt = (
            "Write exactly one resume bullet point that addresses the job requirement using the candidate info provided.\n\n"
            f"JOB REQUIREMENT: {requirement}\n"
            f"CANDIDATE INFO: {profile_entry}\n\n"
            "Rules — follow all of them:\n"
            "- Start with a strong past-tense action verb (Led, Built, Designed, Reduced, Migrated, Automated, etc.)\n"
            "- Include specific numbers, scale, or measurable impact if the candidate info supports it — do NOT invent them\n"
            "- No hollow adjectives (not 'successfully', not 'effectively', not 'passionate')\n"
            "- One line only — no line breaks\n"
            "- Achievement-framed: what was accomplished and what it meant, not what duties were held\n"
            "- Never start with 'Responsible for', 'Assisted with', 'Helped', or 'Worked on'\n\n"
            "Respond with ONLY the bullet text. No dash, no asterisk, no label, no preamble."
        )

        try:
            resp = requests.post(
                f"{self.ollama_host}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.4, "num_ctx": 4096},
                },
                timeout=60,
            )
            resp.raise_for_status()
            raw = resp.json().get("response", "").strip()
            raw = raw.lstrip("•-* ").strip()
            return f"• {raw}"
        except Exception as e:
            log.error(f"Bullet draft failed: {e}")
            return f"Draft error: {e}"
