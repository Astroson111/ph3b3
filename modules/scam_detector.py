import os
import re
import logging
import requests

log = logging.getLogger("ph3b3.scam")

# Pre-scan patterns checked before the LLM call.
# Each tuple: (compiled regex, human-readable label injected into the prompt)
# Ordered from highest-alarm to softer signals.
_RED_FLAG_PATTERNS = [
    # Threat/fear language
    (re.compile(r'\barrest\b',                                re.I), "threat of arrest"),
    (re.compile(r'\bdeportation\b',                           re.I), "threat of deportation"),
    (re.compile(r'\baccount\s+(?:will\s+be\s+)?(?:closed|suspended|blocked|terminated)\b', re.I),
                                                                     "threat of account closure"),
    (re.compile(r'\bwarrant\b',                               re.I), "threat language (warrant)"),
    # Remote access requests
    (re.compile(r'\bremote\s+access\b',                       re.I), "remote computer access request"),
    (re.compile(r'\bteamviewer\b',                            re.I), "remote computer access request (TeamViewer)"),
    (re.compile(r'\banydesk\b',                               re.I), "remote computer access request (AnyDesk)"),
    # Payment method red flags
    (re.compile(r'\bwire\s+transfer\b',                       re.I), "payment method red flag: wire transfer"),
    (re.compile(r'\bgift\s+cards?\b',                         re.I), "payment method red flag: gift cards"),
    (re.compile(r'\bcrypto(?:currency)?\b',                   re.I), "payment method red flag: cryptocurrency"),
    (re.compile(r'\bzelle\b',                                 re.I), "payment method red flag: Zelle (irreversible)"),
    (re.compile(r'\bvenmo\b',                                 re.I), "payment method red flag: Venmo (irreversible)"),
    # Government impersonation
    (re.compile(r'\b(?:IRS|internal\s+revenue\s+service)\b',  re.I), "government impersonation: IRS"),
    (re.compile(r'\bsocial\s+security(?:\s+administration)?\b',re.I),"government impersonation: Social Security"),
    (re.compile(r'\bmedicare\b',                              re.I), "government impersonation: Medicare"),
    (re.compile(r'\bfbi\b',                                   re.I), "government/law enforcement impersonation: FBI"),
    # Urgency pressure
    (re.compile(r'\bact\s+now\b',                             re.I), "urgency pressure: act now"),
    (re.compile(r'\blimited\s+time\b',                        re.I), "urgency pressure: limited time"),
    (re.compile(r'\bwithin\s+(?:24|48|72)\s+hours?\b',        re.I), "urgency pressure: artificial deadline"),
    (re.compile(r'\btoday\s+only\b',                          re.I), "urgency pressure: today only"),
    # Fake selection / lottery
    (re.compile(r"you'?ve?\s+been\s+selected",                re.I), "fake selection / you've been chosen"),
    (re.compile(r"you'?ve?\s+won\b",                          re.I), "prize or lottery scam signal"),
    (re.compile(r'\bclaim\s+your\s+prize\b',                  re.I), "prize or lottery scam signal"),
    (re.compile(r'\bcongratulations.*(?:won|winner|selected)', re.I), "prize or lottery scam signal"),
    # Phishing / link bait
    (re.compile(r'\bclick\s+(?:this|the|here|below)?\s*link\b', re.I), "phishing link"),
    (re.compile(r'\bverify\s+your\s+(?:account|identity|information)\b', re.I),
                                                                     "account verification phishing"),
    (re.compile(r'\bconfirm\s+your\s+(?:account|identity|details)\b', re.I),
                                                                     "account verification phishing"),
    # Isolation tactics
    (re.compile(r"\bdon'?t\s+tell\s+(?:anyone|your|them)\b",  re.I), "isolation tactic: don't tell anyone"),
    (re.compile(r'\bkeep\s+this\s+(?:secret|between\s+us)\b', re.I), "isolation tactic: secrecy demand"),
    (re.compile(r"\bdon'?t\s+contact\s+(?:police|bank|family)\b", re.I),
                                                                     "isolation tactic: cut off support"),
    # Personal info harvesting
    (re.compile(r'\bsocial\s+security\s+number\b',            re.I), "personal info harvest: SSN"),
    (re.compile(r'\bbank\s+account\s+(?:number|details)\b',   re.I), "personal info harvest: bank account"),
    (re.compile(r'\bpassword\b',                              re.I), "personal info harvest: password request"),
    # Too good to be true
    (re.compile(r'\b(?:guaranteed|risk.?free)\s+(?:income|earnings|profits?|returns?)\b', re.I),
                                                                     "too good to be true: guaranteed returns"),
    (re.compile(r'\bwork\s+from\s+home\b.*\$\d{3,}',          re.I), "too good to be true: work-from-home income claim"),
]


class ScamDetector:
    def __init__(self):
        self.ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self.model = os.getenv("PH3B3_HEAVY_MODEL", os.getenv("PH3B3_MODEL", "hermes3"))
        log.info("Scam detector ready.")

    def _pre_scan(self, text: str) -> list[str]:
        """Return deduplicated list of human-readable red-flag labels found in text."""
        seen: set[str] = set()
        hits: list[str] = []
        for pattern, label in _RED_FLAG_PATTERNS:
            if label not in seen and pattern.search(text):
                hits.append(label)
                seen.add(label)
        return hits

    def _llm_analyze(self, text: str, pre_flags: list[str]) -> str:
        excerpt = text[:4000]

        flag_note = ""
        if pre_flags:
            labels = ", ".join(f'"{f}"' for f in pre_flags)
            flag_note = (
                f"\n\nAUTOMATIC DETECTION NOTE: The following red-flag patterns were found verbatim "
                f"in the text before you saw it: {labels}. "
                f"These must be reflected in your TACTICS DETECTED section."
            )

        prompt = (
            "You are Ph3b3, a protective AI running offline on a private machine called Nyx. "
            "Your job right now is to analyze the text below for scam and manipulation tactics. "
            "This tool exists for one reason: to protect people who cannot afford to lose "
            "what scammers are trying to take.\n\n"

            "ABSOLUTE RULES — never break these:\n"
            "1. Do not blame the recipient. Ever. These tactics are engineered by professionals "
            "and routinely fool intelligent, careful people. If it feels relevant, say so.\n"
            "2. Plain English only. No jargon, no acronyms, no security-industry vocabulary.\n"
            "3. If the content looks genuinely clean, say so clearly and confidently. "
            "False alarms destroy the trust that makes this tool useful.\n"
            "4. Do not be alarmist. Rate what you actually see.\n\n"

            "LIKELIHOOD SCALE — use exactly one:\n"
            "  Clean         — no meaningful red flags; this looks legitimate\n"
            "  Suspicious    — some signals worth noting but could be legitimate; caution advised\n"
            "  Likely Scam   — multiple strong indicators; treat as a scam unless proven otherwise\n"
            "  Run. Just run. — active, imminent danger; financial loss or account/identity compromise "
            "is the clear goal; do not engage\n\n"

            "TACTIC CATEGORIES to look for (report only what you actually see):\n"
            "  urgency pressure, authority impersonation, too good to be true, isolation tactics, "
            "payment method red flags, personal info harvesting, threat or fear language, "
            "romance or trust building, fake legitimacy signals\n\n"

            f"TEXT TO ANALYZE:\n{excerpt}"
            f"{flag_note}\n\n"

            "Respond in EXACTLY this format — nothing before or after:\n\n"
            "LIKELIHOOD: [Clean / Suspicious / Likely Scam / Run. Just run.]\n\n"
            "TACTICS DETECTED:\n"
            "- [Each tactic found, in plain English, one per line. If none: '- None detected']\n\n"
            "WHAT THEY WANT:\n"
            "[One direct line: what the sender is actually after — money, account access, "
            "personal information, emotional control, or some combination]\n\n"
            "WHAT TO DO RIGHT NOW:\n"
            "[2 to 4 plain sentences. Concrete, direct, no fluff. What action to take immediately.]\n\n"
            "VERDICT: [One sentence. Honest. Protective. If it's dangerous, say so plainly.]"
        )

        try:
            resp = requests.post(
                f"{self.ollama_host}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.2, "num_ctx": 6144},
                },
                timeout=120,
            )
            resp.raise_for_status()
            return resp.json().get("response", "").strip()
        except Exception as e:
            log.error(f"Scam analysis LLM call failed: {e}")
            return f"Analysis error — could not reach local model: {e}"

    def analyze(self, text: str) -> str:
        text = text.strip()
        if not text:
            return "No text provided to analyze."
        if len(text) < 10:
            return "Text too short to analyze meaningfully."

        pre_flags = self._pre_scan(text)
        log.info(f"Scam pre-scan: {len(pre_flags)} flag(s) detected before LLM call")
        return self._llm_analyze(text, pre_flags)

    def check_identity_exposure(self, exposed: str, context: str = "") -> str:
        exposed = exposed.strip()
        if not exposed:
            return "No exposed items listed — nothing to assess."

        context_line = f"\nHow it happened: {context.strip()}" if context.strip() else ""

        prompt = (
            "You are Ph3b3, a protective AI running offline on a private machine called Nyx. "
            "Someone's personal information has been exposed and they need to know what to do. "
            "Your job is to give them a calm, clear, practical recovery plan.\n\n"

            "ABSOLUTE RULES — never break these:\n"
            "1. Calm tone throughout. Panic makes the situation worse and leads to mistakes. "
            "Acknowledge that this is stressful, then move immediately to what can be done.\n"
            "2. These situations are recoverable. Say so plainly in the verdict. "
            "Identity exposure is serious but it is not the end — millions of people have been "
            "through this and come out the other side.\n"
            "3. Plain English only. No jargon. If you use an acronym, explain it.\n"
            "4. Be specific. Name the actual agencies, actual phone numbers if you know them, "
            "actual websites. Vague advice is useless when someone is scared.\n"
            "5. Do not store, repeat back, or quote the exposed information unnecessarily. "
            "Assess it, then move to action.\n\n"

            f"WHAT WAS EXPOSED: {exposed}"
            f"{context_line}\n\n"

            "Respond in EXACTLY this format — nothing before or after:\n\n"
            "RISK PER ITEM:\n"
            "[item]: [what someone can actually do with this — plain English, one line each]\n\n"
            "PRIORITY ACTIONS:\n"
            "1. [Most urgent action — specific, concrete, doable today]\n"
            "2. [Second action]\n"
            "3. [Third action]\n"
            "[Continue as needed — stop when the list is complete, not before]\n\n"
            "WHO TO CONTACT:\n"
            "[Agency or service]: [why, and how to reach them — include phone or website]\n"
            "[List every relevant one. If SSN was exposed: FTC, all three credit bureaus, SSA, IRS. "
            "If bank account: the bank directly. If email/password: every account using that password.]\n\n"
            "FREEZE RECOMMENDATIONS:\n"
            "[What to freeze or flag, step by step. Credit freeze is free and strong — say so. "
            "Explain the difference between a freeze and a fraud alert if both are relevant.]\n\n"
            "VERDICT: [One calm sentence. Acknowledge what happened. Confirm it's recoverable. "
            "No false cheer, no catastrophizing.]"
        )

        try:
            resp = requests.post(
                f"{self.ollama_host}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.2, "num_ctx": 6144},
                },
                timeout=120,
            )
            resp.raise_for_status()
            return resp.json().get("response", "").strip()
        except Exception as e:
            log.error(f"Identity exposure check LLM call failed: {e}")
            return f"Analysis error — could not reach local model: {e}"


# ── VALUES AUDIT ──────────────────────────────────────────────────────────────
#
# This module makes deliberate value choices. They are documented here so they
# can be examined, challenged, and updated — not buried in implementation.
#
# NO VICTIM BLAMING
#   Scam tactics are professionally engineered. Romance scams run for months.
#   IRS impersonators study real IRS language. The techniques that work on
#   "smart people" are the same techniques — they are just run longer, or
#   with better targeting. Framing the output around what the sender did,
#   not what the recipient failed to notice, is the only ethical position.
#   It also has a practical effect: blame shuts down action. A person who
#   feels stupid will not report, will not call their bank, will not ask for
#   help. Clear, non-judgmental output leaves room for them to act.
#
# TTS FOR "RUN. JUST RUN."
#   People who are already in a scam — who have sent money, given access,
#   or shared information — are often in a dissociated or anxious state.
#   Reading text under stress is harder than hearing a voice. The spoken
#   alert is not a gimmick. It changes the physics of whether the message
#   lands. It is reserved for the highest tier only: using it for "Suspicious"
#   would be a boy-who-cried-wolf failure. It fires once, immediately, and
#   says the minimum necessary.
#
# OFFLINE-ONLY
#   Scam messages frequently contain the most sensitive information people
#   possess: SSNs, account numbers, addresses, medical information. Sending
#   this text to any cloud service for analysis would be a secondary privacy
#   violation — trading one exposure risk for another. The pre-scan runs on
#   regex before any model sees the data. The LLM call goes only to the local
#   Ollama instance on Nyx. Nothing leaves the machine.
#
# FALSE POSITIVE COST
#   A scam detector that cries wolf on legitimate mail trains users to ignore
#   it — and then misses the real thing. The four-level scale exists precisely
#   to avoid collapsing "this looks a little weird" and "this will take your
#   savings" into the same response. "Clean" must mean something, or the tool
#   is useless. The prompt explicitly instructs the LLM to say clean is clean.
#
# FOUR-LEVEL SCALE
#   "Suspicious" exists for content that has soft signals but plausible
#   legitimacy — a real bank CAN send urgent-sounding emails about account
#   activity. Jumping straight to "Likely Scam" on these erodes trust.
#   "Run. Just run." is reserved for cases where the goal is unambiguously
#   financial extraction, identity theft, or account takeover — where
#   engagement of any kind increases risk.
#
# WHAT THIS TOOL CANNOT DO
#   It cannot verify whether a sender is who they claim to be. It cannot
#   check whether a link is live or malicious. It cannot detect sophisticated
#   long-game tactics that look clean in a single message. It analyzes text
#   only. The verdict is a tool for decision-making, not a guarantee.
#
# ─────────────────────────────────────────────────────────────────────────────
