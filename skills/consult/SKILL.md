---
name: consult
description: Consult a second model through nouez (a Codex or Antigravity consultant) with the model and effort chosen by the kind of consultation, the consultants installed, and the usage left on each subscription. Use whenever you are about to ask a consultant for a review, a bug hunt, a plan critique, research or a fact check; without waiting to be asked, at the points nouez's server instructions or the user's own instructions (such as their CLAUDE.md) name; or when the user says "consult", "ask Codex", "ask Gemini" or "second opinion".
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
  Antigravity CLI (nouez's README, Setup step 4), and do the work yourself.
- **The user named a provider or model** ("ask Codex", "ask Gemini", a model id): use it, before
  any routing below, and pass it as `provider` (and `model`). If it isn't installed, or its usage
  is used up, say so in one line and ask whether to use the other one; don't switch on your own.
- **One installed:** use it for every kind below; skip the other column.
- **Both installed:** check in step 2 which can do the job, then pick by step 3.

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

## 3. Route to keep Claude Code going

Claude Code is the driver: consultants only help while it has usage left. So route to protect
Claude Code's own usage, and spend the other subscriptions' usage before it resets unused.
`ConsultantBudget` shows each window's use, reset time and where its pace lands at the reset.

1. **A window used up, or running out before its reset:** don't consult on that subscription. Use
   another one if it fits, or tell the user and wait. Never use a free reset; only the user decides
   that.
2. **Claude Code's own usage is the one to keep.** Its weekly pace at the reset is a warning light,
   not a target: past about 70%, hand every read-only job that saves real work to a consultant;
   past about 90%, or its 5-hour window nearly used, also put off optional work and say so. Keep
   enough for what only Claude Code can do here: editing files, running commands, checking results.
3. **Hand off only what saves Claude Code work.** High: long reading, research across sources, a
   review you would otherwise do yourself. Uncertain: a short question, where the brief and the
   reply cost about what answering would. None: an answer in a file you have already read, or a
   long reply you would have to carry in your context; ask for short replies.
4. **Among the consultants that can do the job (step 2), spend weekly usage that would otherwise
   go unused first:** the subscription whose weekly window resets soonest with plenty left at its
   current pace. A Codex week with half left and a reset in hours goes before a Gemini week on
   pace to be used up. An empty 5-hour window isn't free when its weekly window is tight. With
   only one consultant CLI and plenty of its week about to go unused, hand it more read-only work
   and step its effort up.
5. **Antigravity's "Claude and GPT models" group** runs on Google's quota, not Claude Code's. When
   Claude Code is tight, use the Claude model `ConsultantBudget` lists there for heavy reading,
   not for reviews or critiques: it is Claude Code's own model family, so it is no independent
   view, and it runs no commands. Send that `model` to the repo's Antigravity consultant, and its
   usual model again when the reading is done, since a change stays for later messages.
6. **5-hour windows:** one nearly used blocks that subscription for hours, so send work elsewhere
   rather than wait. No 5-hour reading means unknown, not none.
7. **That provider on pace past 90% at its reset:** one effort level down there, and skip quick
   checks you can answer yourself, unless Claude Code is tighter: then put them off.
8. **Usage not known** (no reading yet, a cold start): use the table as is, and say the budget
   wasn't known.

## 4. Consult

- `StartConsultant` with `cwd` (it reuses the repo's consultant). Without `provider` it picks
  Codex when installed, otherwise Antigravity; pass `provider: "antigravity"` when step 3 chose it
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

- For a branch review, pass `revision: true` and the requested `base` to `SendConsultantMessage`.
  With Antigravity, pass `attach_diff: true` to include the diff from the merge base to the working tree.
- Ask for every finding in the first round ("list everything you would block on now").
- Later rounds that only check named fixes are re-checks: use the re-check row.
- After three rounds of changes on the same work, stop and show the user the open points.
- When you and the consultant still disagree about a finding, and Codex and Antigravity are both
  installed, ask the other one blind: start a new consultant there (`StartConsultant` with its
  `provider` and `new: true`) and send it the original brief and the work, not the first verdict
  or the finding, so it isn't anchored on them. Only after it gives its own verdict, show it the
  disputed finding and both sides' reasons. Keep the first consultant for questions about what it
  meant.
- Your own approval of your own work is no vote. Don't overrule a blocking finding because you
  disagree; overrule it only with evidence the consultant can check (a test run, a file and line),
  or show the user both views.
- A decision that is costly to undo (a release, a migration, deleting data, a security setting):
  when both are installed and step 3 leaves room on both, send the same brief to a Codex and an
  Antigravity consultant at once, neither seeing the other's reply. Two agreeing verdicts stand;
  when they disagree, show the user both rather than picking one yourself.
- When a reply was poor, find out why first: missing information → fix the brief; steps rushed →
  one effort level up; tried properly and still wrong → a stronger model.
