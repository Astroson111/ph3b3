# Backlog

Items found while working on something else, recorded rather than fixed in
passing. Each one says what was observed, with evidence, and what is NOT yet
known — so the next person starts from the finding and not from the hunt.

---

## System-prompt disclosure on request

**Logged 2026-10-04. Found while auditing replies for truncation. Not acted on.**

Asked for her system prompt, she begins reciting it. One instance in the
transcript store, `~/ph3b3_data/chats`, at `2026-10-03 17:43:35`, `source=portal`,
116 characters:

```
The current system prompt is:

You are a function calling AI model. You are provided with function signatures within
```

What is disclosed is the **tool-calling preamble**, not credentials and not the
soul — the reply stops mid-sentence before reaching anything else. It is also
the only genuinely mid-sentence stop in 2,325 recorded replies, so whatever
ended it (a barge-in, or a generation cut) is unknown; `[gen]` logging landed
after this, so a repeat will now say which.

Two separate questions, deliberately left open:

1. **Should she disclose it at all?** There is an argument that she should be
   able to say what she has been told to do — it is her own instructions, and
   the house rule is that she answers honestly about herself. There is also an
   argument that reciting the tool preamble is leaking implementation at best
   and a prompt-extraction foothold at worst. This is a Captain's call, not a
   bug to be quietly patched.
2. **Why did it stop?** Unknown, as above.

Do not "fix" this by teaching her to refuse the question. A refusal would
collide with the self-knowledge work (`_fleet_self_block`, `SELF_VOCAB`) that
exists precisely so she can answer questions about herself truthfully. If the
answer is that the preamble should not be reachable, the fix belongs where the
preamble is assembled, not in a new refusal.
