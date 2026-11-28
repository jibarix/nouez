---
name: uninstall
description: Remove what nouez's setup added outside the plugin - the phone dispatcher, the waiter's allow rules and nouez's status line - before uninstalling the plugin. Run when the user types /nouez:uninstall.
disable-model-invocation: true
---

# Remove nouez's setup

`NOUEZ` stands for `py -3 -I "${CLAUDE_PLUGIN_DATA}/app/server.py"`. If `${CLAUDE_PLUGIN_DATA}`
wasn't filled in above, the folder is the one under `~/.claude/plugins/data/` whose name starts
with `nouez-`.

1. Run `NOUEZ dispatcher status`. If a phone dispatcher is installed, say that removing it ends the
   chats it has open, then run `NOUEZ dispatcher uninstall --dry-run`, show it, and on a yes run
   `NOUEZ dispatcher uninstall`. The dispatcher's folder and its CLAUDE.md stay.
2. Run `NOUEZ setup --remove --dry-run` and show the user what it would take out of Claude Code's
   user settings: the waiter's allow rules, a status line that runs this nouez, and the
   marketplace's auto-update when `setup --auto-update` turned it on, nothing else. On
   a yes, run `NOUEZ setup --remove`. It backs up the settings file first.
3. Tell the user the last step is theirs to choose: `claude plugin uninstall <the plugin's id>` in
   a terminal (the id is `nouez@` and the marketplace's name, as `claude plugin list` shows it),
   which may also delete the plugin's data folder (the copy nouez ran from and its approvals). nouez's
   settings, cache and usage log stay, in `%LOCALAPPDATA%\nouez`; say so. Offer to run the uninstall;
   run it only on a yes.
