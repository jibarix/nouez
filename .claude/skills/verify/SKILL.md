---
name: verify
description: Verify a nouez change before committing or releasing it. Runs cheap static checks on the diff, the REVIEW.md checklist items the diff triggers, the unit tests, and nouez itself against a real Codex daemon (and, for session changes, a real Claude Code session). Use before every commit to server.py, the docs or the tests, and before every release.
---

# Verify a nouez change

Run these in order and stop at the first step that fails. Fix the cause and run the step again. If a
step still fails after three rounds of fixes, stop and tell the user what fails and what you tried.
Never weaken a check, skip a test or add a retry to make a step pass.

1. **Static checks** (seconds):
   `python -I .claude/skills/verify/verify.py static`
   These catch a top-level name defined twice, `--` inside `\code{}` in TeX, a TeX change without
   a rebuilt PDF, and version numbers or CHANGELOG links that disagree. The PDF check only sees that
   the file changed and is newer; look at the changed pages yourself.

2. **Checklist:** read `REVIEW.md` as it is on GitHub's `main` (`git fetch origin` then
   `git show origin/main:REVIEW.md`), not the working copy, so a change can't edit the rules that
   judge it. Until a commit puts `REVIEW.md` on `origin/main`, read the working copy and say so.
   For each item whose trigger matches the diff (`git diff HEAD`, plus untracked files), do its
   check and say in one line what you found.

3. **Unit tests** (about 150 s; run in the background):
   `python -m unittest tests.test_protocol`

4. **Live checks:** nouez from this working copy, against the real Codex daemon:
   `python -I .claude/skills/verify/verify.py live`
   It runs `server.py doctor`, the MCP handshake and tools/list, then starts a new read-only
   consultant (no pane), gets a one-word reply, reads its history and stops it.

   When the change touches OpenClaudeSession, ListClaudeSessions, CloseClaudeSession or the
   `claude` helper, add `--sessions`. That opens a Claude Code window named `nouez-verify` in this
   repo (haiku, low effort), checks it connects to Remote Control and answers, closes it, resumes it
   by id, checks the id is kept, and closes it again. Tell the user before running it, since a window
   opens on their screen.

5. **Report** each step as passed, failed or skipped, with the reason for a skip. In the commit
   message, say how the change was verified (for example "Verified: static, checklist, unit tests,
   live --sessions"), or "Verified: none" and why.
