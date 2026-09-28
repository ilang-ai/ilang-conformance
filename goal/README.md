# goal-check

`goal_check.py` reads the `::RUBRIC` of an engineering book written in iLang, runs every item that carries an
executable check, and exits with 0 only when every item passes. A loop that works towards the book runs it after
each round and stops on the exit code. Python 3.12 or later, standard library only.

    python goal/goal_check.py BOOK.md
    python goal/goal_check.py BOOK.md --list

`--list` shows the items and what would run, and runs nothing.

## How an item is written

An item is a sentence and, after it, the check that decides it. Both forms that books use are read:

    ::RUBRIC{A1: the page answers at its address|check:status|url:https://research.ilang.ai/protocol/agent-input/|expect:200}

    ::RUBRIC{id:r1|objective:g1|threshold:1.0|mode:weighted}
      R:rows|weight:0.6|check:count|url:https://research.ilang.ai/protocol/agent-input/|regex:"<tr[ >]"|expect:10
      R:tone|weight:0.4|check:human

A value that holds `|`, `{`, `}` or a space at its edge goes between double quotes. Inside the quotes `\"` is a
quote, `\\` a backslash and `\n` a new line, as in the specification (v3.0 section 2.4); any other
backslash stays, so a regular expression is written as it is. Every name of an item is used once in a book.

## Kinds of check

| check | fields | the item passes when |
|---|---|---|
| `status` | `url`, `expect` (200) | the address answers with that status, redirects followed |
| `count` | `url` or `path`; `pattern` or `regex`; `in` (`source` or `text`); `expect` (`>=1`) | the number of places the pattern is found meets `expect`. `in:text` counts in the text a reader sees, without scripts and styles |
| `json` | `url` or `path`; `in` (`document` or `jsonld`); `expect` | the document parses. With `in:jsonld`, every JSON-LD block of the page parses and the number of blocks meets `expect` (`>=1`) |
| `links` | `url` or `path`; `allow`; `scope` (`external` or `all`) | every link answers below 400, or with a status listed in `allow` |
| `file` | `path`, `sha256` | the file is there, with that hash when one is given |
| `cmd` | `run`, `expect` (0), `stdout` | the command ends with that exit code and its output holds the text of `stdout` |
| `human` | | never by itself: the item waits for a person |

The value in brackets is the one used when the field is absent. `expect` is a number or a comparison: `0`, `10`,
`>=1`, `<5`. `path` and `run` are relative to `--root`, the current directory when absent.

A `count`, `json` or `links` check reads a page only when it answers 200. An error page holds none of the words a
check looks for, and a count of zero on it would pass for the wrong reason. For the same reason a check that
something is absent from the answer of a service is worth a second item that checks the service answered: the
example has `A6a` next to `A6`.

An item without `check`, or with a `check` that names none of these kinds, waits for a person, as `human` does.
Books written before this program name their checks freely (`check:all_tests_pass`), and they are read as they
are.

## Items that wait for a person

Each item ends as `pass`, `fail` or `unknown`, the three results the specification gives a grader (SPEC-v4.0
section 5), and `unknown` never counts as done. An item that code cannot decide stays `unknown` until a person
states the result:

    ::EVIDENCE{id:e1|deliverable:A7|kind:manual_check|ref:rich-results-2026-09-27.png|verified_by:@OWNER|result:pass}

`deliverable` is the name of the item and `result` is `pass` or `fail`. The line stands in the book, or in a file
kept apart from it and named with `--records`. A line whose `verified_by` is `@AGENT`, `@SELF` or `@TOOL` states
nothing: the one who did the work does not confirm it. When two lines speak of the same item, the later one
stands. A statement decides only the items that code cannot decide; it does not overrule a check that ran.

## An item whose premise is wrong

A book is written before the work, and some of its items turn out to ask for something that is not the case: an
address the owner has since changed, a count that was never right. Such an item fails on every round whatever
the agent does, and a loop that waits for 0 never ends. The agent can dispute it:

    ::STATUS{@TASK|item:A1|state:blocked|need:owner_decision|detail:the page was published on another site|by:@AGENT|authority:proposal}

The check of a disputed item still runs. If it fails, the item is reported as `unknown` with the reason of the
dispute and with what the check saw, and it no longer counts as a failure. A dispute is a proposal: it can stop
the loop and hand the item to the owner of the book, it can never produce 0. The owner settles it by rewriting
the item in the book or taking it out.

## Exit codes

| code | meaning | what a loop does |
|---|---|---|
| 0 | every item passes | stops |
| 1 | at least one item fails | works another round |
| 2 | nothing fails, at least one item waits for a person | stops and hands over |
| 3 | the book cannot be checked: no rubric, a name used twice, a check that is not well formed, an untrusted block that never closes | gives the book back to its author; nothing was run |

## The record of a run

Each run adds one line to `BOOK.goal-log.jsonl`, or to the file named with `--log`; `--no-log` writes nothing, and
`--json` prints the record instead of the table. The record holds the time, the hash of the book, a hash of the
items alone, the result of each item with what the check saw, and the exit code. When the items differ from those
of the run before, the run says so. An agent that changes the acceptance instead of the work shows in the log.
The output of a command is printed when the item fails and is not recorded.

## What the program does not do

- It runs no command of a book unless the person who starts it passes `--allow-cmd`, and it reaches no private or
  local address unless that person passes `--allow-private`. A book is a document, and someone else may have
  written it. The rule on addresses is a look at what the name resolves to before the request and at every
  redirect. It is not a sandbox.
- It reads nothing between `::UNTRUSTED` and `::END_UNTRUSTED`. Content from outside does not set the acceptance
  of a book. A block that never closes stops the reading with exit code 3, so that no item after it is dropped
  without a word.
- It reads `verified_by` and `by` as they are written and cannot know who typed the line. In the words of the
  specification, authority fields are not self-authenticating. Keep the records where the agent under check
  cannot write, or read the diff.
- It reads `::RUBRIC` only. `NON_GOALS` and `::BUDGET` are not checked.
- A run that ends with 0 is what a grader reports about the items. In the specification only the runtime commits
  `complete`.

## Example

[examples/agent-input-page.md](examples/agent-input-page.md) holds the acceptance of two published pages: a
statement on the homepage of ilang.ai, and the page
[Agent Input Authority Mapping](https://research.ilang.ai/protocol/agent-input/). Of its 16 items, 11 carry a
check and 5 wait for a person. The run of 28 September 2026 is in
[examples/agent-input-page.run-2026-09-28.json](examples/agent-input-page.run-2026-09-28.json): 11 pass, none
fails, 5 wait, exit code 2. One of the nine links of the page answers 403 to a program and is let through by the
item, and the record names it.

The book the example comes from had 15 items, written as sentences before the work. Three of them had a premise
that did not hold: the address of the page, which was published on another site; a count of nine JSON-LD blocks
on a homepage that carries eight; an entry in a navigation menu that has no entry of that kind. In the example
they are written the way the work was accepted, and the check of the W3C result is written as two items.

## Tests

    PYTHONIOENCODING=utf-8 python3 -m unittest discover -s tests -p "test_goal_check.py" -v

The tests open no socket. The page they look at is the published page as it was served on 28 September 2026,
kept in `tests/fixtures/goal/`.
