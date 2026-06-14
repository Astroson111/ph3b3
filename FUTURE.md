# FUTURE.md

This file is not a roadmap. It is a record of intent — what we want to build, what we don't yet know how to build responsibly, and what we are committing not to build until the people it's for are in the room.

---

## Elderly Accessibility

Ph3b3 already does some things that could genuinely matter for older adults. Voice-first interaction that doesn't time out. Scam detection that speaks out loud instead of expecting you to read a warning. A benefits decoder for documents designed to confuse people. No dark patterns. No data leaving the machine. No one reading over your shoulder. No subscription renewing quietly in the background.

That's not a feature list for this community. That's infrastructure that happens to align with what some older adults need. The distinction matters. Infrastructure isn't design.

### What could be built

A few directions worth thinking through — not committing to, thinking through:

**Scam detection that's actually designed for voice.** The current implementation flags patterns and speaks a verdict. That's a start. But a phone scam in real time, with a voice on the other end applying pressure, is a different problem than analyzing a screenshot of a suspicious email. What does real-time audio monitoring look like? What does the alert sound like when someone is mid-call and confused and scared? We don't know. That's the point.

**Benefits navigation.** Medicare. Medicaid. Social Security. Supplemental programs that vary by state. Documents written by lawyers for compliance, not by humans for reading. Ph3b3 can decode documents — but decoding a PDF someone scanned with their phone camera is different from walking someone through an enrollment decision. The current benefits decoder isn't designed for that. It would need to be.

**Memory that doesn't require technical management.** Ph3b3 has local persistent memory. But "edit the memory file" is not a usable interface for most people. If Ph3b3 is going to remember that someone's doctor changed, or that they're not supposed to eat grapefruit with a new medication, the memory system has to be designed for that use case from the ground up — not bolted on.

**A setup experience that doesn't require a developer.** Right now, getting Ph3b3 running requires git, pip, and a .env file. That's not a barrier for the builder. It's a wall for most of the people this section is about. Someone has to set it up for them. That relationship — between the person using it and the person who set it up — has privacy and autonomy implications that need to be thought through carefully.

### What we don't know

Whether voice-first is actually preferred. Hearing loss is common. Some people will want large text, not speech. Some will want a button, not a wake word. Some will want to hand the device to a family member and have that family member interact. Some will not want family members involved at all. We don't know the distribution of these preferences and we're not going to assume one.

Whether the current voice is comfortable for extended listening. Alba en_GB was chosen for this project for reasons that have nothing to do with elderly accessibility. Pace, pitch, accent, and clarity all affect comprehension in ways that vary by person and by hearing profile. We haven't tested this. We should not ship anything targeting this community without testing it.

Whether the interaction patterns that feel natural to the builder feel natural to anyone else. Ph3b3 was built by one person who needed it. That person is not 75. That person doesn't have early-stage cognitive decline. That person doesn't have macular degeneration or arthritis that makes touching a keyboard painful. We have no data on any of this.

What the actual barriers are. We can guess — scams, isolation, benefits complexity, medical information overload. We might be wrong. We've seen enough "built for seniors" products that solved the wrong problem with confidence to know that guessing is not design.

Whether any of this helps without the setup problem being solved first. The most thoughtfully designed voice interface in the world doesn't help if the person using it had to rely on a family member to install it — and that family member now has physical access to the system and its memory.

### What consultation looks like before anything ships

Not a survey. Not a focus group run by someone who has never done this before. Not "we asked three older relatives and they seemed fine with it."

Occupational therapists who specialize in aging and assistive technology. Gerontologists. Audiologists, specifically about TTS voice design for users with age-related hearing changes. Low-vision specialists if any visual interface is added. Dementia care specialists if memory-support or reminder features are developed — because designing for early cognitive decline requires specific expertise and specific ethics.

Organizations led by older adults, not just serving them. There's a difference. AARP exists, but so do local senior advocacy organizations, senior centers run by and for their communities, elder law clinics. These are the rooms to be in.

Most importantly: direct co-design sessions with older adults who represent a range of technical comfort, cognitive ability, hearing and vision profiles, and living situations. Not their adult children. Not their doctors. Them.

### The standard

Nothing in this section ships without community voices in the design process.

Not "we consulted community voices and then built it." Community voices in the design process. Before wireframes. Before code. Before the feature has a name. If the consultation happens after the feature is designed, it's not consultation — it's validation-seeking.

If we can't do this right, we don't do it. The scam detector that ships today is useful. A badly designed "elderly mode" could be patronizing, inaccessible, or harmful. We'd rather ship nothing than ship something that treats older adults as a demographic to optimize for rather than people to build with.

---

## Autism Accessibility

The #ActuallyAutistic community has watched people build "for" them for decades. Communication devices designed without autistic input that required behaviors that caused pain. "Social skills" trainers built by neurotypicals who treated autism as a set of deficits to be corrected. Apps marketed as tools that were actually surveillance. Research conducted on autistic people without autistic researchers in the room.

Ph3b3 will not continue that tradition.

This section is not a feature announcement. It is a record of what we think might align, what we know we don't know, and what we're committing to before any of this moves forward.

### What Ph3b3's architecture naturally aligns with

Some of this is intentional. Some of it is incidental. All of it needs validation from the people it's supposed to serve before we claim it's actually useful.

**Predictable.** Ph3b3 doesn't push overnight UI changes. Doesn't enshittify. Doesn't decide unilaterally to change how it responds because a model update went out. The LLM is local and version-controlled. The behavior is consistent. For people whose nervous systems rely on predictability to function, an AI that changes its patterns arbitrarily isn't a tool — it's a stressor.

**Patient.** Ph3b3 doesn't have a session timeout that disconnects mid-sentence. Doesn't escalate if a request takes a long time to formulate. Doesn't get confused and defensive when asked to repeat something. Doesn't treat a pause as disengagement. These are baseline behaviors, not special features.

**Literal.** The current prompt system can be configured to avoid idioms, sarcasm, and ambiguous phrasing. Whether it actually does this reliably is an empirical question. But the architecture supports it, and the user controls it.

**User-controlled.** No attention hijacking. No dark patterns. No feature that activates without the user knowing. No behavioral manipulation. The user sets the rules for how Ph3b3 behaves. This isn't framed as a disability accommodation — it's how the whole system is designed. The difference matters. A system that treats control as default is different from a system that adds a "special mode" for users who need it.

**Private.** Things people rehearse, scripts they're working on, communication strategies they use — these are deeply personal. A tool that sends this data to a cloud service is not a tool that can be trusted for this use case. Everything Ph3b3 does stays on the machine. No exceptions built into the current architecture.

**Potentially useful for scripting and preparation.** Phone calls are a documented source of difficulty for many autistic people — not because of any deficit, but because they require real-time processing of ambiguous audio without visual cues, on someone else's timeline. Ph3b3 can draft scripts. Can help someone prepare for a specific conversation. Can simulate an interaction and let someone practice it. Whether this is actually helpful or creates new pressure is something we don't know and won't assume.

### What we don't know

The autistic community is not monolithic. This should not need to be said in 2026, but it still does: there is no single autistic experience, no single set of preferences, no single communication style, no single relationship with technology. A feature that one person finds essential, another may find insulting or harmful. A design choice that reduces friction for one person may create new friction for another. We are not going to design for an imagined average autistic user.

We don't know whether the current interaction patterns cause friction we haven't noticed. Ph3b3 was not designed with autistic users in mind. The defaults might be fine. They might be actively difficult. We don't know.

We don't know what the line is between a tool that supports communication and a tool that pressures masking. An AI that helps someone prepare a script for a phone call could be genuinely useful. It could also inadvertently reinforce the message that the way the person naturally communicates is insufficient and needs to be corrected. This is not a hypothetical concern — it's a documented harm pattern in autism technology. We do not know how to avoid it without autistic people in the room telling us.

We don't know what features are actually wanted. We have guesses. Scripting support. Literal communication settings. Sensory-aware notification design if notifications are added. These might be exactly right. They might be beside the point. They might be the things that have already been tried and failed. We don't know.

We don't know which features would be used to support autonomy and which might be used by others — family members, employers, institutions — in ways that undermine it. This is not paranoia. It is a pattern with documented history in assistive technology. The setup process and permission model matter enormously here.

### Who needs to be in the room before anything ships

Autistic self-advocates. Not parents of autistic children. Not clinicians who treat autistic people. Not researchers who study autism. Autistic people, speaking for themselves, with their own opinions about what they need.

The #ActuallyAutistic community has been doing this work. ASAN — the Autistic Self Advocacy Network — exists and has positions on technology and accessibility that were developed by autistic people. There are autistic developers, autistic researchers, autistic designers. These are the people to find and listen to, not as validators of decisions already made, but as collaborators before decisions are made.

People with varying support needs. The voices most often included in autism technology design are those of autistic people who are easiest to include in design processes — people who communicate in ways that are most legible to neurotypical designers. This systematically excludes the people who most need well-designed tools. This is a structural problem in the field and we are not automatically immune to it.

### The standard

Community consultation is not a checkbox. It is the foundation.

No feature is labeled an "autism tool," marketed as one, or designed as one without autistic people designing it. Not reviewing it after the fact. Designing it.

No deficit framing. A tool that helps someone navigate a phone call is a communication tool. Not a "social skills trainer." Not a compensation mechanism. Not a therapy adjunct. The framing matters because it shapes what gets built, and it shapes how the person using it feels about themselves.

If the right people aren't in the room, the room isn't ready. That's not a delay. That's the work.

The autistic community has been burned by people who meant well and built badly. Meaning well is not enough. Ph3b3 will not add to that record.

---

*This file will be updated as the project develops. If you are someone this section is about — an older adult, an autistic person — and you want to be part of building it: the door is open. The repository is at github.com/astroson/ph3b3_v2. The builder is reachable.*
