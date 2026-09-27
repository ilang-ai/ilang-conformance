# Recomputing the published results

Scripts that recompute, from the raw run records, the numbers published in `report/` and `controls/`, and the
evidence of two checks that are not runs of the corpus. Python 3.12 or later, standard library only.

## The records

The raw records are archived apart from this repository: DOI
[10.5281/zenodo.22987356](https://doi.org/10.5281/zenodo.22987356), one zip per run, 55 runs and 17,600 records.
Unpack them into one directory, so that it holds `<run>/grammar/`, `<run>/exec/`, `<run>/judge/` and
`<run>/MANIFEST.sha256` for each run, and pass that directory as `--runs`.

## The scripts

| file | what it does |
|---|---|
| `reproduce_all.py` | runs `score.py` and `refusal.py` on every run and `controls/compare_arms.py` on the control arms, and compares each result with the published file |
| `paper_checks.py` | recomputes the figures that those three scripts do not print: the language split of the corpus, the check of the user-message hashes, the runs sent without a temperature, the replies that name a foreign product, the kinds of the filtered cases, the hosts per run, the agreement of the same-route replicate |
| `pii_scan.py` | lists every address-like and telephone-like string in the records |

    python paper/reproduce_all.py --runs DIR
    python paper/paper_checks.py --runs DIR \
        --replicate-a paper/replicate/run-2026-09-18-score.json \
        --replicate-b paper/replicate/run-2026-09-24-score.json
    python paper/pii_scan.py --runs DIR

## Which release reproduces what

The prompt-size ratio divides the prompt tokens a provider reported by the length of the system message, and the
system message is built from the specification vendored in the checkout. A release that vendors a later
specification therefore recomputes the scores and the counts, and gives other ratios.

| checkout | `reproduce_all.py` reports |
|---|---|
| release 1.2.0 (`6afa99d`), which vendors the specification the runs of September 2026 were made with | identical, byte for byte, for the 54 runs it publishes and for the arm comparison |
| release 2.1.0 and later | identical but for the specification, for all 55 runs and for the arm comparison: `spec_pin` in `score.json` and `prompt_size` in `refusal.json` are set aside, everything else is equal |

To run the scripts on release 1.2.0, check it out in a separate work tree and copy this directory into it:

    git worktree add ../conformance-1.2.0 v1.2.0
    cp -r paper ../conformance-1.2.0/
    cd ../conformance-1.2.0 && python paper/reproduce_all.py --runs DIR

## `replicate/`

The `score.json` of two runs of the same model through the same route six days apart
(deepseek-v4-flash-free through orcarouter.ai, 18 and 24 September 2026, the same specification), and the record
manifest of the second. The first is `report/orcarouter-deepseek-free-20260918-050901/score.json`; both are
published with the dataset at
[research.ilang.ai/datasets/canon-rewrite-ab/](https://research.ilang.ai/datasets/canon-rewrite-ab/). Of the second
run the per-case scores and the manifest are available, not the replies: its agreement with the first run and the
exact tests can be recomputed, and it cannot be scored again from replies.

## `replay/`

On 25 September 2026 the system and user messages of two requests (judge-0003 and exec-0003) were sent to
claude-sonnet-4-6 and claude-opus-4-7 through a third relay, aisa.one, to see whether the upper-cased replies of
api.b.ai came from the models. Four replays, with an output limit of 2,048 tokens.

| file | what it is |
|---|---|
| `messages.json` | the system and user messages of the two requests; their hashes are the ones the records of the board runs carry |
| `probe.py` | the first run, with temperature 0: the two sonnet replays answered, the two opus requests got HTTP 400 |
| `probe_opus.py` | the second run, the two opus requests without a temperature |
| `output-claude-sonnet-4-6.json` | what the first run printed for the two sonnet replays |
| `output-claude-opus-4-7.json` | what the second run saved for the two opus replays |

Of each reply the probes kept the served model name, the prompt tokens, the share of upper-case letters and the
first 200 characters, not the whole reply. The scripts are the ones that were run, with the key now read from the
environment variable `RELAY_API_KEY` and the message file named `messages.json`.
