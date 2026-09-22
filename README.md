# ilang-conformance

Conformance test set for the iLang protocol. Every model reachable over an API answers the same cases, and deterministic code scores each answer with the upstream validators pinned in `vendor/`. No model grades another model.

Tracks: grammar (120 cases), exec (100), judge (100). Standard library only.

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22864929.svg)](https://doi.org/10.5281/zenodo.22864929)

**Citation:** [CITATION.cff](CITATION.cff); Zenodo archives each release. Concept DOI [10.5281/zenodo.22864929](https://doi.org/10.5281/zenodo.22864929) (all versions); 1.0.0 is [10.5281/zenodo.22864930](https://doi.org/10.5281/zenodo.22864930).

## Results

45 model runs, 18 to 20 September 2026: 34 complete runs are ranked in [report/SCOREBOARD.md](report/SCOREBOARD.md), 12 are listed separately because a relay, not the model, changed what could be answered. The highest weighted total so far is 0.8417; no model has reached L1. Every score is reproducible from its run records with `score.py` at the commit named on the board.

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
