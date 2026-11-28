---
name: setup
description: Set up nouez after installing or updating the plugin - the waiter's allow rules, the status line, and the phone dispatcher (recommended). Run when the user types /nouez:setup.
disable-model-invocation: true
---

# Set up nouez

nouez runs from `${CLAUDE_PLUGIN_DATA}/app/server.py`, a copy the plugin keeps in one place across
updates. Below, `NOUEZ` stands for `py -3 -I "${CLAUDE_PLUGIN_DATA}/app/server.py"`. If
`${CLAUDE_PLUGIN_DATA}` wasn't filled in above, the folder is the one under
`~/.claude/plugins/data/` whose name starts with `nouez-`.

1. Run `NOUEZ setup --dry-run` and show the user what it would change in Claude Code's user
   settings: the waiter's allow rules (so a consultant's reply comes back without a prompt each time)
   and, when they have no status line, nouez's (it passes Claude Code's usage to nouez). Ask whether
   to go ahead and whether they want the status line. On a yes, run `NOUEZ setup`, with
   `--statusline` if they want it. It backs up the settings file before changing it, and keeps a
   status line of the user's own.
   The dry run also says whether the marketplace nouez came from auto-updates. When it says it is
   off and `setup --auto-update` turns it on, ask in the same question whether to turn it on, saying
   that it then updates every plugin from that marketplace by itself, not only nouez, and that
   updates then arrive without a review step, so only for a marketplace they trust; on a yes, add
   `--auto-update`. When it says something else decides it (a policy, a variable, no entry for the
   marketplace), pass on what it says, with its steps.
2. If it says a clone of nouez is registered as `consultants` too, ask the user whether to remove
   it. If it names environment variables the clone's registration sets, tell the user first that
   the plugin doesn't get them, and on their yes set each switch it names the same way with
   `NOUEZ settings set NAME on` (or `off`) before removing the clone. On a yes, run
   `claude mcp remove --scope user consultants`, then `NOUEZ setup` again, which takes the clone's
   waiter rules out of the user settings (backed up first). The clone's folder stays.
3. Run `NOUEZ doctor` and report its problems and notes in a few lines, each with its fix.
4. Run `NOUEZ dispatcher status`. If a phone dispatcher is installed, it may still run an older
   copy (a clone, or this plugin before an update): run `NOUEZ dispatcher setup --dry-run` and
   `NOUEZ dispatcher install --dry-run`, each with the folder it was installed with (`--folder`),
   show the user both, and on a yes run them without `--dry-run`, setup first. Setup gives the
   dispatcher's folder its permission rules under the plugin's tool names, and replaces a CLAUDE.md
   an earlier nouez wrote there (backed up first); install ends the chats the dispatcher has open,
   so say so first. Claude Code's sandbox can refuse setup's change to the dispatcher folder's
   `.claude/settings.json`: when the sandbox is on, tell the user, then run setup (not its dry run)
   outside it (the shell tool's option to run a command without the sandbox). If setup says the
   folder's CLAUDE.md was edited, show the user that note and offer its steps: the dispatcher's
   instructions then say what the plugin allows from the phone.
   If none is installed, recommend one and ask whether to set it up: it is nouez's main feature, a
   session that stays running on this computer from each sign-in, so the Claude app on the phone can
   open a session in any project, make a folder for a new one, and list and close sessions, with
   nothing started by hand at the computer. Without it, the phone reaches only Remote Control
   sessions and servers the user starts at the computer, each in its own project, and none after a
   restart.
   It is asked, not done, because it needs one run in a terminal by the user and then starts at each
   sign-in. On a yes, run `NOUEZ dispatcher setup --dry-run`, show it, then `NOUEZ dispatcher setup` (outside the sandbox, as above) and follow the steps it
   prints: the one-time run in a terminal is for the user, since only they can answer Claude Code's
   questions there.
5. Give the user the setup guide's link that `NOUEZ setup` prints last, for each step in detail.
   Tell the user to run /reload-plugins in this session, or start a new one: that puts the new
   nouez in place. Their other open sessions on the plugin then move to it by themselves, at their
   next nouez call made while nothing of nouez's runs there. If step 2 removed a clone's
   registration, say that sessions opened before it still run the clone's nouez until each is
   reopened.
