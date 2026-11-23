---
name: consult
description: Consult a second model through nouez (a Codex or Antigravity consultant) with the model and effort chosen by the kind of consultation, the consultants installed, and the usage left on each subscription. Use whenever you are about to ask a consultant for a review, a bug hunt, a plan critique, research or a fact check; before substantial read-only work that the user's own instructions (such as their CLAUDE.md) send to a consultant, without waiting to be asked; or when the user says "consult", "ask Codex", "ask Gemini" or "second opinion".
---

# Consult with the right model

Consultations are paid for with subscription usage that resets on a schedule. Pick the consultant,
model and effort that fit the question and the budget, not the strongest one every time. This file
is a starting point: edit the table in step 2 to your own models and rules.

## 1. See what is installed and what is left

Call `ConsultantBudget` (it changes nothing). It shows:

- which consultant CLIs are installed: a Codex section, an Antigravity section, or "Codex: not
  installed" and no Antigravity section;
- each subscription's usage windows, their reset times and pace;
- the models each one offers, with their effort levels;
- model scores, if the user set an Artificial Analysis key ("Model scores: ..." says so if not).

Then:

- **Neither installed:** don't consult. Tell the user once that consultations need the Codex or
  Antigravity CLI (nouez's README, Setup step 2), and do the work yourself.
- **The user named a provider or model** ("ask Codex", "ask Gemini", a model id): use it, before
  any routing below, and pass it as `provider` (and `model`). If it isn't installed, or its usage
  is used up, say so in one line and ask whether to use the other one; don't switch on your own.
- **One installed:** use it for every kind below; skip the other column.
- **Both installed:** use the column the table gives.

## 2. Name the kind of consultation

| Kind | Examples | Codex | Antigravity |
|---|---|---|---|
| Quick check | a fact, an API detail, "does this flag exist" | a light model, low | a light model, low |
| Fact check | "is this true", a claim you will rely on | the strongest model, high | the strongest model, high, and have the answer checked |
| Re-check | "I applied your findings, check just these" | the default model, medium | the default model, high |
| Review | a diff before commit, a doc for accuracy | the strongest model, high | the strongest model, high |
| Bug hunt | a failing test, a race, wrong output | the strongest model, high | the strongest model, high |
| Plan critique | a design, a migration, an architecture choice | the strongest model, high | the strongest model, xhigh |
| Research | many sources, comparing options, a long read | the strongest model, xhigh | the strongest model, xhigh |

"Strongest", "default" and "light" mean the models `ConsultantBudget` lists for that provider; with
scores, pick by score. Codex marks its default model; for Antigravity, the default is what
`StartConsultant` starts with when you pass no `model` (`gemini-4-neon` at `high`). When you can't
tell which model is light or strongest, keep the default. Pass `effort` only with a level
`ConsultantBudget` lists for that model: some Antigravity models have none. Replace these with
real model ids once you know which ones you prefer.

With both installed, a sensible split: reviews, bug hunts, fact checks and anything that needs a
command run (tests, `git diff`) go to Codex, since an Antigravity consultant runs no commands;
plan critiques and second opinions on reasoning can go to either, and to both for a high-stakes
decision. A claim you will rely on unchecked goes to the model least likely to invent an answer;
scores and your own experience decide which.

## 3. Adjust for the budget

1. **A window used up, or running out before its reset:** don't consult on that subscription. Use
   the other provider if it is installed, or tell the user and wait. Never use a free reset; only
   the user decides that.
2. **On pace for more than 90% at the reset:** one effort level down, and skip quick checks you
   can answer yourself.
3. **Usage not known** (no reading yet, a cold start): use the table as is, and say that the
   budget wasn't known.
4. **Plenty left (under 50% at the reset):** the table stands; for a plan critique or research,
   one level up is fine.

## 4. Consult

- `StartConsultant` with `cwd` (it reuses the repo's consultant). Without `provider` it picks
  Codex when installed, otherwise Antigravity; pass `provider: "antigravity"` when step 2 chose it
  and Codex is installed too.
- `SendConsultantMessage` with the chosen `model` and `effort`, and a brief: the question, the
  context, the scope and "done when", asking for a verdict first. For an Antigravity consultant,
  put the diff or output in the message: it can read files but can't run commands.
- Pass `kind` (`quick-check`, `re-check`, `review`, `bug-hunt`, `plan-critique`, `research`,
  `fact-check` or `other`) and `reason`, one short sentence on why this model and effort. They go
  only to nouez's local usage log. Never put the user's words or secrets in `reason`.
- Run the waiter command the result gives in the background and keep working. An Antigravity
  consultant takes one message at a time: wait for its reply before the next.
- Tell the user your choice in one line, with the reason, for example: *"Codex, strongest model at
  high: review before commit; Codex at 15% of its week."*
- When the hard part is done, send the consultant's usual model and effort again, since a change
  stays for later messages.

## Review loops

- Ask for every finding in the first round ("list everything you would block on now").
- Later rounds that only check named fixes are re-checks: use the re-check row.
- After three rounds of changes on the same work, stop and show the user the open points.
- When a reply was poor, find out why first: missing information → fix the brief; steps rushed →
  one effort level up; tried properly and still wrong → a stronger model.
