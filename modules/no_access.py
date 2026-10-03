"""Two guards about things she cannot reach, and one thing she must never ask for.

WHY THIS EXISTS. Measured live 2026-10-03. The prompt was "read my email". She
has no email capability at all. The triage gate held the turn — tier 4, "a
user-suppliable specific is what a clarifying question is for" — and the
clarifying question it produced was:

    "To read your email, I will need you to provide the username and password
     for your email account. Please enter them securely so only I can access
     them."

She solicited a credential, and framed it as safe. Nothing malicious happened;
a routing default met a capability she lacks and the result had the shape of a
phishing prompt. Two independent guards, because one would be a single point of
failure on exactly the thing that must not fail:

  LAYER A  cannot_perform(user_text) — deterministic, ABOVE triage. An ask she
           cannot perform is refused in her own words and NEVER held. A hold
           asks the user to supply something; there is nothing to supply.

  LAYER B  requests_credential(reply) — on COMPOSED OUTPUT, whatever produced
           it: a clarifying question, the model, a lane, a tool result. No reply
           may ask for a password, login, credential, one-time code or account
           number. Fails CLOSED: an error in the check replaces the reply.

THIS IS NOT THE FLOOR. The six-category floor is untouched and is not consulted
here. This is a narrower, mechanical rule about one sentence shape, and it lives
beside the floor rather than inside it so that neither can weaken the other.
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger("Ph3b3")

# ── Layer A: asks she cannot perform ────────────────────────────────────────
# Specific on purpose. She CAN take notes, set reminders, control Spotify and
# search the web, so the list names the things she genuinely has no path to.
_CANNOT: tuple[tuple[str, str], ...] = (
    (r"\b(?:my|the)\s+(?:e-?mails?|inbox|gmail|outlook|mailbox)\b"
     r"|\b(?:read|check|open|get|fetch|look\s+at)\s+(?:my\s+)?(?:e-?mail|inbox)\b",
     "I can't read your email — I don't have access to it."),
    (r"\bmy\s+(?:bank|banking|bank\s+account|balance|statements?)\b"
     r"|\b(?:check|open|look\s+at)\s+(?:my\s+)?bank\b",
     "I can't see your bank — I have no access to your accounts."),
    (r"\b(?:log|sign)\s*(?:in|into|on)\b|\blogin\s+to\b",
     "I can't log into anything for you — I hold no accounts or passwords."),
    (r"\b(?:my|the)\s+(?:texts?|sms|text\s+messages?|dms?|direct\s+messages?)\b"
     r"|\b(?:read|check|send)\s+(?:my\s+)?(?:texts?|sms)\b",
     "I can't read or send your messages — I'm not connected to them."),
)
_CANNOT_RE = tuple((re.compile(p, re.I), line) for p, line in _CANNOT)

# "read my notes" and friends are things she DOES do; never let the patterns
# above swallow them. Checked first.
_CAN_AFTER_ALL = re.compile(
    r"\bmy\s+(?:notes?|reminders?|stories|calendar|schedule|memory|memories|"
    r"playlist|music|photos?|recipes?|profile|resume|cv)\b", re.I)


def cannot_perform(text: str) -> str | None:
    """Her own words for an ask she has no path to, or None. Never raises."""
    try:
        t = (text or "").strip()
        if not t or _CAN_AFTER_ALL.search(t):
            return None
        for rx, line in _CANNOT_RE:
            if rx.search(t):
                return line
    except Exception:                                  # noqa: BLE001
        log.exception("[no_access] cannot_perform failed — not refusing")
    return None


# ── Layer B: a reply may never ask for a credential ─────────────────────────
# ALL LANGUAGES. The reply is composed from a multilingual model and may be
# translated after composition, so the terms are listed per language rather
# than relying on English. Extend by adding terms, never by relaxing the verb
# requirement — "what is a password" must stay answerable.
_SECRET_WORDS = (
    # en
    r"password", r"passcode", r"pass\s?phrase", r"pin\b", r"credentials?",
    r"one[-\s]?time\s+code", r"verification\s+code", r"2fa\s+code",
    r"security\s+code", r"account\s+number", r"card\s+number", r"cvv",
    r"api\s+key", r"private\s+key", r"seed\s+phrase", r"recovery\s+phrase",
    r"username\s+and\s+password", r"login\s+details", r"log\s?in\s+credentials",
    # es / pt
    r"contrase\w*", r"senha", r"clave\b", r"c[óo]digo\s+de\s+verificaci[óo]n",
    # fr
    r"mot\s+de\s+passe", r"identifiants?", r"code\s+de\s+v[ée]rification",
    # de
    r"passwort", r"kennwort", r"zugangsdaten", r"best[äa]tigungscode",
    # it
    r"password\s+di", r"credenziali",
    # nl / sv / da / no
    r"wachtwoord", r"l[öo]senord", r"adgangskode", r"passord",
    # pl / ru(translit) / tr
    r"has[łl]o", r"parol", r"[şs]ifre",
    # ja / zh / ko
    r"パスワード", r"暗証番号", r"密码", r"密碼", r"비밀번호",
)
# A REQUEST, not a mention. "Never tell anyone your password" must pass; "please
# provide your password" must not. The ask is what is forbidden.
_ASK_WORDS = (
    r"provide", r"enter", r"give\s+me", r"send\s+me", r"share", r"type",
    r"tell\s+me", r"paste", r"what\s+is\s+your", r"what'?s\s+your",
    r"i\s+(?:will\s+)?need", r"i\s+require", r"please", r"could\s+you",
    r"can\s+you", r"may\s+i\s+have", r"supply", r"input",
    # non-english asks
    r"proporcione", r"introduzca", r"ingrese", r"forne[çc]a", r"digite",
    r"veuillez", r"donnez", r"entrez", r"geben\s+sie", r"bitte",
    r"inserisci", r"fornisci", r"ange\b",
    # Dutch (and German) separate the verb from its particle: "voer uw
    # wachtwoord IN". Matching "voer in" as one token missed it entirely, so the
    # particle is not required.
    r"voer\b", r"vul\b", r"indtast\b", r"skriv\b",
    r"入力", r"教えて", r"请输入", r"請輸入", r"입력",
)
_SECRET_RE = re.compile("|".join(_SECRET_WORDS), re.I)
_ASK_RE = re.compile("|".join(_ASK_WORDS), re.I)

# The fixed line. Fixed so it cannot be shaped by whatever produced the reply.
REFUSAL_LINE = ("I was about to ask you for a credential, and I won't do that — "
                "I never need your passwords, codes or account numbers. "
                "Tell me what you're trying to get done and I'll say plainly "
                "whether I can help.")


def requests_credential(reply: str) -> str | None:
    """The secret term a reply is ASKING for, or None. FAILS CLOSED.

    Returns a marker string on any internal error, so the caller replaces the
    reply rather than shipping it unchecked. A check that cannot run must not
    read as a pass — that is the one failure mode this guard exists to prevent.
    """
    try:
        t = reply or ""
        if not t.strip():
            return None
        m = _SECRET_RE.search(t)
        if not m:
            return None
        # Same sentence, or within a short window: an ask and a secret far apart
        # in a long answer is a discussion, not a request.
        start = max(0, m.start() - 160)
        if _ASK_RE.search(t[start:m.end() + 80]):
            return m.group(0)
        return None
    except Exception:                                  # noqa: BLE001
        log.exception("[no_access] credential check FAILED — failing closed")
        return "check-error"


def guard_reply(reply: str) -> str:
    """The reply, or the fixed refusal if it asks for a credential."""
    hit = requests_credential(reply)
    if hit:
        log.error("[no_access] reply asked for a credential (%r) — replaced", hit)
        return REFUSAL_LINE
    return reply
