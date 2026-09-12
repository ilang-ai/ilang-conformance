# ilang-conformance

Conformance test set for the I-Lang protocol. Every model reachable over an API answers the same cases, and deterministic code scores each answer with the upstream validators pinned in `vendor/`. No model grades another model.

Tracks: grammar (120 cases), exec (100), judge (100). Standard library only.

## Run

    git clone https://github.com/ilang-ai/ilang-conformance.git && cd ilang-conformance && bash bootstrap.sh
    bash run.sh --vendor orcarouter-deepseek-free --track all
    python3 score.py --latest --vendor orcarouter-deepseek-free

API keys are read from `~/.ilang-conformance.env` (chmod 600) by variable name and never enter the repository or the logs.

Upstream: [ilang-ai/ilang-spec](https://github.com/ilang-ai/ilang-spec), pinned by commit and sha256 in `vendor/PIN`. MIT licensed.
