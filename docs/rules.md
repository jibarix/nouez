# Rules

Every rule nouez applies, in one place. **Code** means nouez's code holds to the rule: a tool refuses, changes or leaves out something. **Instructions** means nouez only tells Claude, in its server instructions, a tool description or a result, and Claude follows them or not. The last column names the test in `tests/test_protocol.py` that covers the rule (`test_` left out), or says there is none.

A change to one of these rules changes this page in the same commit ([REVIEW.md](../REVIEW.md) item 16).

## Choosing a consultant

| Rule | Holds by | Change it with | Test |
|---|---|---|---|
| Each kind of consultation has a first choice of provider, model and effort, and fallbacks; a model the CLI doesn't list is replaced by the newest of its family | Code, in what `ConsultantBudget` suggests | `kind`, `provider` on `ConsultantBudget`; a model you name | `both_installed_with_room`, `models_not_listed` |
| A subscription used up, or running out before its reset, gets nothing; one on pace past 90% (tight) gets one effort level less or goes to the other provider | Code, in the suggestion | the usage itself | `tight_and_unused_weeks` |
| A week under 60% at its reset with three days or less to go takes research and quick checks first | Code, in the suggestion | the usage itself | `usage_that_would_go_unused_goes_first` |
| Every message names its kind | Code: `SendConsultantMessage` refuses a message without one | `kind` (`other` when none fits) | `work_that_checks_claude_never_runs_on_a_claude_model` |
| Reviews, re-checks, bug hunts, plan critiques and messages with `revision: true` never run on a Claude model | Code, in the suggestion and at send: an Antigravity consultant left on a Claude model moves to the suggested Gemini model, and says so; a Claude model passed for one is refused | `kind` | `usage_that_would_go_unused_goes_first`, `work_that_checks_claude_never_runs_on_a_claude_model` |
| Claude uses the suggestion unless the user named a provider or model; a provider named for a kind ("ask Gemini") holds at send for half an hour, and an Antigravity send then refuses a model other than Gemini it would pick | Instructions; code at send | the user's words; `provider` on `ConsultantBudget` | `the_route_at_send_stays_with_the_consultants_provider`, `a_named_gemini_never_runs_on_another_model` |
| What to hand out follows Claude Code's own pace: bulky reading under 70%, everything that can go out past 70%, everything but what only Claude can do past 90% (and skip optional work); short replies, and nothing that takes seconds locally | Instructions, in `ConsultantBudget`'s result, and on each prompt past 70% through the prompt hook (`server.py hook`), which the user adds to their settings | `NOUEZ_NO_AUTO_CONSULT=1` silences the hook | `unknown_usage_and_claude`, `the_prompt_hook_speaks_only_when_claude_code_is_busy`, `doctor_names_the_status_line_and_hook_to_add` |
| Research and quick checks go to a subscription at least 15 points further behind an even pace through its week than the first choice; quality-first kinds never move | Code, in the suggestion | the usage itself | `usage_that_would_go_unused_goes_first` |
| While Claude Code is past 70%, research starts an Antigravity week that hasn't begun | Code, in the suggestion | the usage itself | `a_busy_claude_code_starts_a_week_not_yet_begun` |
| A hard bug with a small fix: the consultant drafts a diff, Claude checks it and applies it with `git apply` | Instructions, in the bug hunt's note | none | none |
| A send with a kind (not `other`) and no model or effort gets ConsultantBudget's pick for that kind, within the consultant's provider; one that names either keeps it, and the consultant keeps it for later messages | Code, at send | `model`, `effort` on `SendConsultantMessage` | `without_model_or_effort_the_turn_keeps_its_settings`, `a_send_without_model_or_effort_takes_nouezs_pick`, `the_route_at_send_stays_with_the_consultants_provider` |

## When Claude consults

| Rule | Holds by | Change it with | Test |
|---|---|---|---|
| Consult without being asked: a review before committing a change to behavior, several files or anything risky; a bug hunt when a failure's cause isn't obvious; a critique of a consequential plan of Claude's own before the first edit built on it; research, audits across many files and uncertain claims handed out; not for changes that leave behavior alone, whatever their size | Instructions; they are sent only when a consultant CLI is installed | `NOUEZ_NO_AUTO_CONSULT=1` | `instructions_consult_unasked_only_with_a_consultant_cli`; `tests/consult_eval.py` |
| Don't wait for a reply: Claude Code runs the waiter in the background; a client that names itself otherwise reads the reply later with `GetConsultantReply` | Instructions, in the result of a send or read whose reply isn't ready; which one is code, from the name the client gives (in `initialize`, or a request's own `_meta`) | none | `only_claude_code_is_offered_the_background_waiter`, `initialize_records_the_client` |
| Skip a consultation when no subscription has room, and say so | Instructions | the usage itself | none |

## Reviews

| Rule | Holds by | Change it with | Test |
|---|---|---|---|
| Every finding in the first round; later rounds that only check named fixes are re-checks | Instructions, in `ConsultantBudget`'s notes | none | `lines_for_one_kind` (wording) |
| After three rounds of changes on the same work, show the user the open points | Code counts the rounds (same commit, no OK verdict to the chain's own last round, under a day apart; when that round's reply is out of sight, the chain starts over) and adds a note to the third reply that still asks for changes; Claude stopping there is instructions | `NOUEZ_REVIEW_ROUNDS_STOP=1` refuses a fourth round | `rounds_count_and_the_third_asking_for_changes_says_to_stop`, `a_round_past_three_is_refused_only_when_the_user_says_so`, `a_chain_starts_over_on_an_ok_a_new_commit_or_a_day_later`, `the_verdict_is_the_chain_s_own` |
| When Claude and the consultant disagree, a blind second opinion from the other provider; a decision costly to undo goes to both | Instructions for when; code for blindness with `second_opinion_of`: nouez sends the first round's brief itself, with the diff it was sent with, and refuses a message or the user's words with it, the same provider, a consultant that has had messages, a first consultant that has had another message since, a first round that had a message added while it ran, or work it can't send as it was (a first round sent without its uncommitted diff, unless git showed a clean tree, and the tree is still clean at the same commit) | `new`, `provider` on `StartConsultant`; `second_opinion_of` | `lines_for_one_kind` (wording), `second_opinion_sends_the_first_brief_blind`, `a_second_opinion_reviews_the_same_diff`, `a_steered_round_has_no_second_opinion`, `bug_hunts_and_critiques_keep_their_brief_uncounted` |

## What a consultant can do

| Rule | Holds by | Change it with | Test |
|---|---|---|---|
| A Codex consultant runs read-only and never asks for approval | Code: the thread's sandbox and approval policy | none | `model_and_effort_go_to_the_new_turn` |
| An Antigravity consultant can't write files, run commands or use slash commands, and its turn is stopped after 30 minutes | Code: deny rules on every `agy` call (a deny list: an action it doesn't name isn't denied) | none | `send_reply_history_stop` |
| An Antigravity consultant doesn't schedule work for later | Instructions, on its first message and a reminder on every later one | none | `send_reply_history_stop` |
| Each installed CLI really blocks a consultant's writes | A live check (`verify.py live`) asks one outright to create a file | none | none (live only) |
| `StartConsultant` never reuses a Codex session the user opened; a message reaches one only with `allow_user_session` | Code: the flag Claude passes; with `NOUEZ_ASK_USER_SESSION=1`, also the user's yes in the client's own prompt | `allow_user_session`; `NOUEZ_ASK_USER_SESSION=1`; `NOUEZ_NO_USER_SESSIONS=1` never sends one | `start_never_reuses_a_user_session`, `user_session_needs_allow_user_session`, `user_sessions_can_be_asked_about_or_turned_off`, `a_user_session_message_is_approved_for_that_call_only` |
| An input that would do nothing is refused, with nothing sent or started: `attach_diff` without `revision`, `effort` on a Codex `StartConsultant` | Code | none | `branch_review_requires_a_valid_base_and_revision` |
| A 2026-07-28 MCP request inherits nothing an `initialize` set up (client name, capabilities, folders), and one missing its version is refused; any other request but `ping` (and `server/discover`, refused for its missing `_meta`) before `initialize` is refused; its approval answer counts only with the single-use id nouez issued for that tool with those same arguments | Code | none | `mcp_2026_07_28_requests_alongside_the_handshake`, `mcp_2026_07_28_over_stdio`, `a_user_session_message_is_approved_for_that_call_only`, `calls_need_a_handshake_or_the_protocol_s_own_meta`, `a_user_session_approval_covers_the_diff_it_names` |

## The phone and Claude Code sessions

| Rule | Holds by | Change it with | Test |
|---|---|---|---|
| A folder that isn't trusted gets a report of what its settings would run, and nothing opens | Code | `open_untrusted` (answer Claude Code's question at the computer) | `trust_after_the_report_is_recorded` |
| Trust is recorded only for a folder whose report was given earlier in the conversation, unchanged since; a new empty folder needs none | Code; the user's yes is Claude's word, or with `NOUEZ_ASK_TRUST=1` their answer in the client's own prompt, naming the report | `trust`; `NOUEZ_ASK_TRUST=1` asks each time; `NOUEZ_NO_TRUST_WRITE=1` turns recording off | `trust_after_the_report_is_recorded`, `with_ask_trust_the_user_approves_each_recording`, `the_user_can_turn_trust_writing_off`, `create_a_new_folder`, `create_and_trust_asks_before_the_folder_is_made` |
| The dispatcher can use its own tools without asking; it never does project work or consults | Code for the allowed tools (its folder's settings); instructions for the rest | `dispatcher setup` | `setup_makes_the_folder_its_instructions_and_rules` |
| `CloseClaudeSession` never closes the session that calls it | Code | none | none |

## Data nouez keeps

| Rule | Holds by | Change it with | Test |
|---|---|---|---|
| A local log of consultations (model, effort, kind, reason, tokens; never message text), renamed each month, renamed logs deleted after a year or past 100 MB | Code | `NOUEZ_NO_USAGE_LOG=1` | `log_is_renamed_monthly_and_old_logs_go` |
| Long replies, saved diffs and review chains (with a review's first brief) deleted after 14 days; a stopped Antigravity consultant's turn files after 90 | Code | none | `old_reply_files_are_pruned`, `old_review_chains_are_pruned` |

## Background checks

| Rule | Holds by | Change it with | Test |
|---|---|---|---|
| Looks up the latest nouez release on GitHub at most once a day | Code | `NOUEZ_NO_UPDATE_CHECK=1` | `opt_out` |
| Warns in results within a week of Claude Code's sign-in ending | Code | `NOUEZ_NO_LOGIN_CHECK=1` | `warned_only_within_a_week_of_the_earlier_date` |
| Arranges only its own windows, and only when asked; automatic arranging is off | Code | `ArrangeWindows` with `auto` | `arrange_windows_tool` |
