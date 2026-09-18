# ilang-conformance

Conformance test set for the I-Lang protocol. Every model reachable over an API answers the same cases, and deterministic code scores each answer with the upstream validators pinned in `vendor/`. No model grades another model.

Tracks: grammar (120 cases), exec (100), judge (100). Standard library only.

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
