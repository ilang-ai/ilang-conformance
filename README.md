# ilang-conformance

Conformance test set for the iLang protocol. Every model reachable over an API answers the same cases, and deterministic code scores each answer with the upstream validators pinned in `vendor/`. No model grades another model.

Tracks: grammar (120 cases), exec (100), judge (100). Standard library only.

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22864929.svg)](https://doi.org/10.5281/zenodo.22864929)

**Citation:** [CITATION.cff](CITATION.cff); Zenodo archives each release. Concept DOI [10.5281/zenodo.22864929](https://doi.org/10.5281/zenodo.22864929) (all versions); 1.0.0 is [10.5281/zenodo.22864930](https://doi.org/10.5281/zenodo.22864930).

## Results

45 model runs, 18 to 20 September 2026: 32 complete runs are ranked in [report/SCOREBOARD.md](report/SCOREBOARD.md), 14 are listed separately because a relay, not the model, changed what could be answered or what came back. The highest weighted total so far is 0.8417; no model has reached L1. Every score is reproducible from its run records with `score.py` at the commit named on the board. The board carries a dated correction: two Claude runs first ranked near zero on 2026-09-21 were re-cased to upper case by the relay, not by the models, and were moved out of the ranking on 2026-09-25. Nine control runs of 25 and 26 September repeat the corpus for six of the models through other routes (openrouter.ai pinned to Anthropic, the DeepSeek and Alibaba Cloud endpoints); they sit in their own section of the board, with the per-case agreement between routes, so that a difference between two runs can be read against the noise of a single run. All of those runs were made against ilang-spec `127ba56`. Release 2.0.0 (2026-09-26) pins `vendor/` to ilang-spec 4.3.0, whose wording leaves decisions to code (see the [A/B](https://research.ilang.ai/datasets/canon-rewrite-ab/) that motivated it); runs made from now on are scored against that canon and are not comparable with the board above. The first such run, the same free DeepSeek model and route as on the board, passes 68 of 100 execution cases where it passed 10 under the old canon, and fails the authority rule on 2 cases instead of 86; grammar and judgment are unchanged within noise. It is listed on the board in its own section. Release 2.1.0 (2026-09-26) pins `vendor/` to ilang-spec `cad65e2`, the sealed v5.0 Pre 2.4.1 (release 4.5.1, tag `v5.0-pre-2.4.1-sealed`): every symbol of the judgment layer's normative text is now defined, bound to an f_v5 constant or registered, and the frozen set of Part II §1 to §5 is unchanged since 2026-07-03, so runs made from now on are scored against a canon whose text will change only through registered counterexamples. The reference function, its constants and the JUDGE schema are the same as under 4.3.0; the judge validator gains the registered models and the routing table as functions (34 selftests).

Refusals and relay interference are counted apart in [report/REFUSALS.md](report/REFUSALS.md), by `refusal.py`: for each run, how many replies declined, how many a content filter withheld, what triggered them (identity, permission, safety, the relay, or the system message every case shares), how the prompt size compares with what was sent, and how many replies came back with their keys in upper case. On this corpus only two runs have refusals or filters. claude-haiku-4.5 through api.b.ai declined 238 of 320: the relay did not pass our system message on, and the replies answer to another agent's identity. claude-fable-5.1 through orcarouter.ai had 29 of 320 withheld by a filter before it wrote a word; 13 of them are judge cases whose prompt is only a vector of numbers. Five Claude runs through api.b.ai came back with most replies re-cased to upper case; the same requests through another relay came back in lower case with the same content. `python3 refusal.py --compare BEFORE AFTER` checks a new model or a new wording against an earlier run of the same corpus, case by case.

If you build one of these models and think a number is wrong, send us tokens and we will run the same corpus against your own API and publish that run next to this one, or run it yourself with this repository.

## Run

    git clone https://github.com/ilang-ai/ilang-conformance.git && cd ilang-conformance && bash bootstrap.sh
    bash run.sh --vendor orcarouter-deepseek-free --track all
    python3 score.py --latest --vendor orcarouter-deepseek-free

API keys are read from `~/.ilang-conformance.env` (chmod 600) by variable name and never enter the repository or the logs.

## Many models behind one endpoint

`batch.py` runs every chat model an OpenAI-compatible endpoint serves (a relay or an aggregator), unattended. It lists the models and drops the ones that are not chat models by name, writes one local `vendors.json` entry per model, screens each model with one case per track while trying the parameter variants the runner allows (temperature omitted, seed off, `max_completion_tokens`, a higher or lower output limit) as the endpoint's errors suggest, runs the full corpus for every model that passed, K models at a time, resumes interrupted runs and re-requests error records, scores each finished run, and packs the results with a key scan. Every step keeps its state in `batch/` and the run directories, so any step can be stopped and started again.

    python3 batch.py models  --base-url https://relay.example/v1 --auth-env RELAY_API_KEY
    python3 batch.py vendors --prefix relay --base-url https://relay.example/v1 --auth-env RELAY_API_KEY
    python3 batch.py screen  --workers 4
    python3 batch.py estimate
    nohup python3 batch.py run --parallel 4 --concurrency 2 > batch/run.log 2>&1 &
    python3 batch.py status
    python3 batch.py pack

Upstream: [ilang-ai/ilang-spec](https://github.com/ilang-ai/ilang-spec), pinned by commit and sha256 in `vendor/PIN`. MIT licensed.
