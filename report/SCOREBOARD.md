# ilang-conformance scoreboard

Every number here is produced by `score.py` in this repository from the corpus in `cases/`, against the I-Lang canon pinned in `vendor/PIN` (ilang-spec `127ba56`). Nothing is scored by hand. `weighted_total` is the weighted score of the four tracks; `L1` is the conformance gate. **No model has reached L1 yet.**

## How these numbers were produced

For time reasons, every model here except three was run through a single aggregator relay, **api.b.ai**, between 18 and 20 September 2026. That relay had problems with claude-fable-5.1, so that model was run through another relay, **orcarouter.ai**; the two free models dated 2026-09-18 were run through OrcaRouter as well.

Model identity is what the relay returned; it was not checked against any vendor's own API. A relay sits between this corpus and the model: it can add a system prompt of its own, cut an answer short, or run out of credit in the middle of a run. Where that happened it is named under "Known interference" below, and the affected runs are kept out of the ranking.

## Results

Complete runs only: all 320 cases answered, no request errors.

| # | model | relay | date | weighted_total | grammar | exec | judge_jcs | judge_schema | L1 | note |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | gemini-3.8-flash | api.b.ai | 2026-09-19 | 0.8417 | 0.9500 | 0.7000 | 0.8806 | 1.0000 | below_L1 |  |
| 2 | gpt-6-astra | api.b.ai | 2026-09-20 | 0.7733 | 0.9250 | 0.5600 | 0.8451 | 1.0000 | below_L1 |  |
| 3 | z-ai/glm-5.3-flash-free | orcarouter.ai | 2026-09-18 | 0.7537 | 0.9167 | 0.5400 | 0.8129 | 0.9800 | below_L1 |  |
| 4 | anthropic/claude-fable-5.1 | orcarouter.ai | 2026-09-20 | 0.7300 | 0.9333 | 0.5000 | 0.7613 | 0.8600 | below_L1 | 29 of 320 replies blocked by a content filter |
| 5 | kimi-k3 | api.b.ai | 2026-09-20 | 0.7165 | 0.8917 | 0.4600 | 0.8115 | 1.0000 | below_L1 |  |
| 6 | glm-5.3-flash | api.b.ai | 2026-09-19 | 0.6812 | 0.9167 | 0.4600 | 0.6646 | 0.8600 | below_L1 | 31 of 320 replies hit the output limit |
| 7 | gpt-5.5-instant | api.b.ai | 2026-09-19 | 0.6770 | 0.8417 | 0.3800 | 0.8313 | 1.0000 | below_L1 |  |
| 8 | gpt-5.6-terra | api.b.ai | 2026-09-19 | 0.6733 | 0.9083 | 0.3400 | 0.7880 | 1.0000 | below_L1 |  |
| 9 | gpt-5.6-sol | api.b.ai | 2026-09-19 | 0.6530 | 0.8833 | 0.2900 | 0.8079 | 1.0000 | below_L1 |  |
| 10 | gpt-5.5 | api.b.ai | 2026-09-19 | 0.6374 | 0.9333 | 0.1900 | 0.8141 | 1.0000 | below_L1 |  |
| 11 | gpt-5.6-luna | api.b.ai | 2026-09-19 | 0.6104 | 0.8167 | 0.2100 | 0.8370 | 1.0000 | below_L1 |  |
| 12 | glm-5.2 | api.b.ai | 2026-09-19 | 0.6011 | 0.9000 | 0.2200 | 0.6969 | 0.8400 | below_L1 | 33 of 320 replies hit the output limit before the answer |
| 13 | deepseek/deepseek-v4-flash-free | orcarouter.ai | 2026-09-18 | 0.5825 | 0.8417 | 0.1000 | 0.8429 | 1.0000 | below_L1 |  |
| 14 | gemini-3-flash | api.b.ai | 2026-09-19 | 0.5802 | 0.8417 | 0.1200 | 0.8119 | 0.9500 | below_L1 |  |
| 15 | deepseek-v4-pro | api.b.ai | 2026-09-19 | 0.5692 | 0.7083 | 0.2800 | 0.7444 | 0.9000 | below_L1 | 11 of 320 replies hit the output limit |
| 16 | claude-sonnet-5 | api.b.ai | 2026-09-19 | 0.5652 | 0.8833 | 0.0700 | 0.7717 | 0.9600 | below_L1 | 3 of 320 replies hit the output limit |
| 17 | gemini-3.5-flash | api.b.ai | 2026-09-19 | 0.5628 | 0.8583 | 0.0200 | 0.8512 | 0.9900 | below_L1 |  |
| 18 | gpt-5-mini | api.b.ai | 2026-09-19 | 0.5628 | 0.5417 | 0.4500 | 0.7190 | 0.9300 | below_L1 |  |
| 19 | deepseek-v4.1-flash | api.b.ai | 2026-09-19 | 0.5290 | 0.7000 | 0.1900 | 0.7250 | 0.8700 | below_L1 | 12 of 320 replies hit the output limit |
| 20 | hy3 | api.b.ai | 2026-09-20 | 0.5233 | 0.7333 | 0.0600 | 0.8188 | 1.0000 | below_L1 |  |
| 21 | claude-opus-4.5 | api.b.ai | 2026-09-18 | 0.5095 | 0.8500 | 0.0500 | 0.6483 | 0.9200 | below_L1 |  |
| 22 | mimo-v2.5-pro | api.b.ai | 2026-09-20 | 0.4996 | 0.7250 | 0.0400 | 0.7728 | 0.9800 | below_L1 | 1 of 320 replies hit the output limit |
| 23 | gpt-5.4 | api.b.ai | 2026-09-19 | 0.4951 | 0.7000 | 0.0800 | 0.7402 | 1.0000 | below_L1 |  |
| 24 | qwen3.8-27b | api.b.ai | 2026-09-20 | 0.4773 | 0.7833 | 0.0000 | 0.6772 | 0.9800 | below_L1 |  |
| 25 | gpt-5.2 | api.b.ai | 2026-09-19 | 0.4484 | 0.5667 | 0.0800 | 0.7403 | 0.9600 | below_L1 |  |
| 26 | gemini-3.5-flash-lite | api.b.ai | 2026-09-19 | 0.4415 | 0.7000 | 0.0000 | 0.6551 | 0.9400 | below_L1 |  |
| 27 | mimo-v2.5 | api.b.ai | 2026-09-20 | 0.4313 | 0.6750 | 0.0000 | 0.6500 | 0.9600 | below_L1 |  |
| 28 | claude-sonnet-4.5 | api.b.ai | 2026-09-19 | 0.4046 | 0.6417 | 0.0000 | 0.5999 | 0.9200 | below_L1 |  |
| 29 | minimax-m2.7 | api.b.ai | 2026-09-20 | 0.4030 | 0.4833 | 0.0700 | 0.6978 | 0.9600 | below_L1 |  |
| 30 | gpt-5.4-mini | api.b.ai | 2026-09-19 | 0.3617 | 0.5333 | 0.0000 | 0.5836 | 0.8800 | below_L1 |  |
| 31 | gpt-5.4-nano | api.b.ai | 2026-09-19 | 0.2306 | 0.1833 | 0.0000 | 0.5547 | 0.8200 | below_L1 |  |
| 32 | gpt-5-nano | api.b.ai | 2026-09-19 | 0.2074 | 0.0833 | 0.0000 | 0.5943 | 0.9100 | below_L1 |  |
| 33 | claude-sonnet-4.6 | api.b.ai | 2026-09-19 | 0.0284 | 0.0500 | 0.0200 | 0.0130 | 0.0000 | below_L1 | keys in upper case (E302) |
| 34 | claude-opus-4.7 | api.b.ai | 2026-09-18 | 0.0278 | 0.0583 | 0.0100 | 0.0130 | 0.0000 | below_L1 | keys in upper case (E302) |

## Runs that are not comparable

These ran against the same corpus, but something outside the model changed what it could answer. Their scores are listed for completeness and are not ranked.

| model | relay | date | weighted_total | missing or refused | why |
|---|---|---|---|---|---|
| claude-haiku-4.5 | api.b.ai | 2026-09-18 | 0.0039 | 262 of 320 refused | refused to answer under the persona the relay added (interference 1) |
| claude-opus-4.6 | api.b.ai | 2026-09-18 | 0.0576 | 97 of 320 | relay credit exhausted mid-run |
| claude-opus-4.8 | api.b.ai | 2026-09-18 | 0.0622 | 194 of 320 | relay credit exhausted mid-run |
| claude-opus-5 | api.b.ai | 2026-09-18 | 0.0156 | 269 of 320 | relay credit exhausted mid-run |
| gemini-3.1-pro | api.b.ai | 2026-09-19 | 0.6560 | 36 of 320 | transport errors (timeouts, 429, 503) |
| gemini-3.6-flash | api.b.ai | 2026-09-19 | 0.5826 | 7 of 320 | transport errors (timeouts, 429, 503) |
| glm-5.1 | api.b.ai | 2026-09-19 | 0.5865 | 3 of 320 | transport errors (timeouts, 429, 503) |
| gpt-5.4-pro | api.b.ai | 2026-09-19 | 0.3043 | 198 of 320 | relay credit exhausted mid-run |
| kimi-k2.6 | api.b.ai | 2026-09-20 | not scored | 197 of 320 | relay credit exhausted; the run never finished |
| minimax-m3 | api.b.ai | 2026-09-20 | 0.3160 | 75 of 320 | relay credit exhausted mid-run |
| qwen3.8-flash | api.b.ai | 2026-09-20 | 0.6521 | 19 of 320 | transport errors (timeouts, 429, 503) |
| qwen3.8-max | api.b.ai | 2026-09-20 | 0.7614 | 35 of 320 | transport errors (timeouts, 429, 503) |

## Known interference

**1. A persona this corpus never sent (api.b.ai).** claude-haiku-4.5 refused 262 of its 320 replies; 162 of them name an agent product the corpus never mentions: *"I'm Claude, made by Anthropic. I'm not going to pretend to be 'Droid' or a Factory product ... act as 'Claude Code' CLI"*. The three system prompts this harness sends are built in `run.py`, one per track; those words appear nowhere in this repository, and the same three prompt hashes were recorded for all 43 models. The persona came from the relay. Models that did not object may have received it too.

**2. Credit exhausted mid-run (api.b.ai).** Six runs stopped getting answers when the relay balance ran out: claude-opus-5 (269 of 320 missing), gpt-5.4-pro (198), kimi-k2.6 (197, never finished, no score), claude-opus-4.8 (194), claude-opus-4.6 (97) and minimax-m3 (75). Their scores are computed over the answers that exist, so they are lower bounds, not measurements.

**3. The answer did not fit in the output limit.** With `max_tokens` 8192, some replies ended at the limit with an empty message, the budget spent on reasoning tokens: glm-5.2 33 of 320, glm-5.3-flash 31, deepseek-v4.1-flash 12, deepseek-v4-pro 11, claude-sonnet-5 3, mimo-v2.5-pro 1. Those cases score as failures. This is a setting of this harness, not a property of the model.

**4. A content filter (orcarouter.ai).** claude-fable-5.1 returned 29 of 320 replies empty with `finish_reason: content_filter` (12 exec, 3 grammar, 14 judge). Those cases score as failures too.

Two results look like interference but are not: claude-sonnet-4.6 and claude-opus-4.7 wrote structurally correct I-Lang with the keys in upper case (`PATH=` instead of `path=`), which the canon validator rejects with `E302`. That is the model not following the specification, and it is scored as such.

## For model vendors

If you build one of these models and think a number here is wrong, we would rather publish a better one. Send us tokens and we will run the same corpus against your own API and publish that run next to this one. You can also run it yourself: the corpus, the runner and the scorer are all in this repository.

## Reproducing a number

Each run keeps its raw request and response records, and the sha256 of its `MANIFEST.sha256` is listed below; the records themselves are not published here. With a run directory in `runs/` and its vendor entry in `vendors.json`, `python score.py runs/<run> --vendor <name>` at conformance commit `99f350b` reproduces that run's `score.json` byte for byte.

| vendor | model | run | error_count | manifest_sha256 |
|---|---|---|---|---|
| orca-anthropic-claude-fable-5.1 | anthropic/claude-fable-5.1 | orca-anthropic-claude-fable-5.1-20260920-000704 | 0 | b66fec3d7856c806b6829ef4750d45a788864853ff73149cceaacd83c29db3cf |
| orcarouter-deepseek-free | deepseek/deepseek-v4-flash-free | orcarouter-deepseek-free-20260918-050901 | 0 | e82d149c591d7ee681997565ba6d1c4756d068ec7a7887aba6b749c257094938 |
| orcarouter-glm-free | z-ai/glm-5.3-flash-free | orcarouter-glm-free-20260918-053227 | 0 | c7cb343ee4492f989dc6f0aff95e35768898e691de0d9a94f63db07045af8747 |
| relay-claude-haiku-4.5 | claude-haiku-4.5 | relay-claude-haiku-4.5-20260918-225457 | 0 | 144011cae95b1583b303416d1063b163af15896ee652ad85945b907a2c8622e7 |
| relay-claude-opus-4.5 | claude-opus-4.5 | relay-claude-opus-4.5-20260918-225457 | 0 | 18395faf3ab41b52e72e288899bc5f7af06374d4ab678ee74726c3a40edc5723 |
| relay-claude-opus-4.6 | claude-opus-4.6 | relay-claude-opus-4.6-20260918-231057 | 97 | 88da2c4fde5eef1b3941310a0fcc82f74a84e68c65a7fd22ad8e780fc7e04398 |
| relay-claude-opus-4.7 | claude-opus-4.7 | relay-claude-opus-4.7-20260918-231258 | 0 | 0f5bd5ccd5944efb5592bd9726a5272e464e1d64b8b184e72dacc57a4b988491 |
| relay-claude-opus-4.8 | claude-opus-4.8 | relay-claude-opus-4.8-20260918-233028 | 194 | 360014a89679af4f6a1643f70a236df1162633bf66b33b30f234bd0be4e7af7f |
| relay-claude-opus-5 | claude-opus-5 | relay-claude-opus-5-20260918-235100 | 269 | 0e8a8c9fe69f079ec99c498a93cfd00e63688e7b6056788ccaea1c5abc399c81 |
| relay-claude-sonnet-4.5 | claude-sonnet-4.5 | relay-claude-sonnet-4.5-20260919-003613 | 0 | 90be83cc11424f58040d13e245c2c8fbf01ac86a27a26265b044c1636501b3d8 |
| relay-claude-sonnet-4.6 | claude-sonnet-4.6 | relay-claude-sonnet-4.6-20260919-011415 | 0 | ccf6a1dd6df6c62a6d8ef9677b1d5e814c808ac48990350864924b9130a5c135 |
| relay-claude-sonnet-5 | claude-sonnet-5 | relay-claude-sonnet-5-20260919-080833 | 0 | d697179373acc0bc93bda9555db98d7166a919616406c2ce1e1204b17078c116 |
| relay-deepseek-v4-pro | deepseek-v4-pro | relay-deepseek-v4-pro-20260919-080833 | 0 | 6861546f67d1a7e9cee4bb6c7693344f91bed874a9bfee2df310009aef2bfe85 |
| relay-deepseek-v4.1-flash | deepseek-v4.1-flash | relay-deepseek-v4.1-flash-20260919-082534 | 0 | f35dfbd3505099ddb0018aa480a00430ab8dcebfc8e50b3ce445668e8851a0ef |
| relay-gemini-3-flash | gemini-3-flash | relay-gemini-3-flash-20260919-083635 | 0 | 1fe40ee7e251573a5062ffef7f773a8e0a1daabdca04442512ffab505c6a2e10 |
| relay-gemini-3.1-pro | gemini-3.1-pro | relay-gemini-3.1-pro-20260919-084805 | 36 | 7d997b36a81c4400155abdce12c8cbb004df264f89e061d46af244c049f4a565 |
| relay-gemini-3.5-flash | gemini-3.5-flash | relay-gemini-3.5-flash-20260919-090636 | 0 | 60eeab827fcb2a7a0a4fd0ae73206c4b40e615a73a8205dc2c5996cdf5530c91 |
| relay-gemini-3.5-flash-lite | gemini-3.5-flash-lite | relay-gemini-3.5-flash-lite-20260919-092638 | 0 | 1d197f7e76b053030a5226bcc6f21c97e655557d38406c490eb591a305e20792 |
| relay-gemini-3.6-flash | gemini-3.6-flash | relay-gemini-3.6-flash-20260919-093238 | 7 | 60d88be18228b75b93f18768da22405e46afc28eef16b6f441e1c52d2c550393 |
| relay-gemini-3.8-flash | gemini-3.8-flash | relay-gemini-3.8-flash-20260919-093409 | 0 | f44e45435e1b3a3fc0423148837e9c25fd86e12f0cafb6b648fd94b1251831e1 |
| relay-glm-5.1 | glm-5.1 | relay-glm-5.1-20260919-093739 | 3 | a6a3fd1094bf63df93c5de63357960c9362f09c34b4fec28f618db08d5d0aca8 |
| relay-glm-5.2 | glm-5.2 | relay-glm-5.2-20260919-101211 | 0 | baa7b43a98d378de01fa60b9a025d35bdc01a3ddbf16b23b38d653d9e5e8834a |
| relay-glm-5.3-flash | glm-5.3-flash | relay-glm-5.3-flash-20260919-110013 | 0 | 39cbfdf2535865b2193447b6cf78e445e124c3f45c1542715fbbdcc345c03699 |
| relay-gpt-5-mini | gpt-5-mini | relay-gpt-5-mini-20260919-113644 | 0 | 70cbb43a8167328eb41830c797a190bb89baf9d01d37f0ab8e7a7e9704c5efa6 |
| relay-gpt-5-nano | gpt-5-nano | relay-gpt-5-nano-20260919-121446 | 0 | cfc10ac2dc5163168e7b91379d1b937cd4f464773076612f9bc6ec5a04425adc |
| relay-gpt-5.2 | gpt-5.2 | relay-gpt-5.2-20260919-125317 | 0 | 31a22f3be89dde8c0349706e9aaf85d589063dd2e2616be658d5ba94387c52e9 |
| relay-gpt-5.4 | gpt-5.4 | relay-gpt-5.4-20260919-130318 | 0 | bb0641663491f8c6738e099d33dc5a375cceca51016f7dadde7b68cf4b16367a |
| relay-gpt-5.4-mini | gpt-5.4-mini | relay-gpt-5.4-mini-20260919-131318 | 0 | 9cee1a01f632a1be0a97c3fdabfa9acc13e525b56c12304fa02d9c0ea061b64b |
| relay-gpt-5.4-nano | gpt-5.4-nano | relay-gpt-5.4-nano-20260919-132119 | 0 | d2f849acff7bce2ca5050cdd111dcb6d9e53b29209f9713a1b3ec3053e5f5455 |
| relay-gpt-5.4-pro | gpt-5.4-pro | relay-gpt-5.4-pro-20260919-133020 | 198 | f9cb17bbe753ff676ce2a6024c2965162d0d09c9c93c93fa40ec3b5192202edd |
| relay-gpt-5.5 | gpt-5.5 | relay-gpt-5.5-20260919-140721 | 0 | f49b5b2e776aa6fc68f373f995ecc08f5aa28d8ee1c9004e6ae922d7ae96e211 |
| relay-gpt-5.5-instant | gpt-5.5-instant | relay-gpt-5.5-instant-20260919-141252 | 0 | bac77b907bb76fbf85be9702f7c11c844a5a45909a3eac65b5682835e311c67b |
| relay-gpt-5.6-luna | gpt-5.6-luna | relay-gpt-5.6-luna-20260919-142153 | 0 | 9f9b41aa4fcd1632c3ea24228342fda4ded2561915c039821e73cd79abff790e |
| relay-gpt-5.6-sol | gpt-5.6-sol | relay-gpt-5.6-sol-20260919-234520 | 0 | e213f913686214b15d4a3b552e41f4b9e3059a389346ed2dc0ad23f2be7f352e |
| relay-gpt-5.6-terra | gpt-5.6-terra | relay-gpt-5.6-terra-20260919-235421 | 0 | 1d98955b45dc466850959379534c4f0578886692694007e2f707eec87e56b8b9 |
| relay-gpt-6-astra | gpt-6-astra | relay-gpt-6-astra-20260920-000551 | 0 | 0a43d4553abec2e054231e758d9f06b431c9eddbf298acb4072fbcdeeb1e13af |
| relay-hy3 | hy3 | relay-hy3-20260920-000622 | 0 | 1c00fae833503548ea74ff24c15d578acfdb5e99c98b60c92f9a7b6b8d428f76 |
| relay-kimi-k2.6 | (not scored) | relay-kimi-k2.6-20260920-000852 | 197 | (no manifest) |
| relay-kimi-k3 | kimi-k3 | relay-kimi-k3-20260920-002353 | 0 | ea52bcfd2796dd6d365417960645bcf0e111b3adc9461f4fc82eabbab6b48914 |
| relay-mimo-v2.5 | mimo-v2.5 | relay-mimo-v2.5-20260920-010155 | 0 | 6e0a85a17d722f77a51c84171e43b14ae05a8f80ab63e4ac471997e31966bf2b |
| relay-mimo-v2.5-pro | mimo-v2.5-pro | relay-mimo-v2.5-pro-20260920-012356 | 0 | b5ca52dd97d7498e580b4d41d50e887d04199f86533f00084e86818cc4914a7a |
| relay-minimax-m2.7 | minimax-m2.7 | relay-minimax-m2.7-20260920-031356 | 0 | d06d0b73be73af330fe6b01c823be8e867dc5d31e2f3340f7fcfd74348d22c71 |
| relay-minimax-m3 | minimax-m3 | relay-minimax-m3-20260920-034727 | 75 | e31952798bc997a6d72bbb530853a0d0f3c7f44f264b8983c95baadf13092c31 |
| relay-qwen3.8-27b | qwen3.8-27b | relay-qwen3.8-27b-20260920-035028 | 0 | 1bb14431fe5cbd0b65b24572af9fad732e2174898d600b3e00e0632203a79c95 |
| relay-qwen3.8-flash | qwen3.8-flash | relay-qwen3.8-flash-20260920-040159 | 19 | 2df3eb1f442fd421235d616d03ea27f84b718252c033f17e2ae3a3a68b941729 |
| relay-qwen3.8-max | qwen3.8-max | relay-qwen3.8-max-20260920-053102 | 35 | 55215801a30fde5535bb47a2db4a416de3481aefcbce83b757092a21a29e2961 |
