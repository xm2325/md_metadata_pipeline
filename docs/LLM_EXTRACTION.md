# Open-weight LLM protocol extraction

## Scope

This path adds a concrete OpenAI-compatible backend for the existing exact-span MD protocol
extractor. The default model identifier is `Qwen/Qwen3.6-27B`, the latest open-weight dense Qwen
model available when this implementation was added. The backend is not tied to Qwen: a DeepSeek or
other model can be selected through `MDMETA_LLM_MODEL` when the serving endpoint supports the same
Chat Completions and JSON Schema contract.

A successful model response is still only a candidate. Code rejects a candidate unless:

- its paragraph identifier exists in the submitted input;
- its quote exactly equals the source substring at the returned zero-based offsets;
- every numeric `raw_text` expression occurs in that quote;
- parsed values and units agree with the copied expression;
- ensembles and restraint text occur in the same quote; and
- the final event passes the strict `ProtocolEvent` model.

The model confidence field is not calibrated and must not be used as a replacement for human
annotation or evidence checks.

## Recommended model

Qwen publishes Qwen3.6 open weights under Apache 2.0. The project uses
`Qwen/Qwen3.6-27B` as its default because it is a dense model and is simpler to reason about for a
first controlled extraction benchmark. `Qwen/Qwen3.6-35B-A3B` is a valid alternative when the
serving environment is configured for the sparse model.

Official Qwen serving examples support OpenAI-compatible endpoints through vLLM, SGLang and
Transformers Serve. The backend sends `response_format.type=json_schema`, temperature zero, a fixed
seed by default, and `chat_template_kwargs.enable_thinking=false`. The last option keeps the
extraction response focused on the constrained JSON object; it can be disabled through the
environment when a server or model does not support that argument.

Example vLLM launch:

```bash
vllm serve Qwen/Qwen3.6-27B \
  --port 8000 \
  --max-model-len 65536 \
  --reasoning-parser qwen3
```

The endpoint is then available at `http://127.0.0.1:8000/v1`.

The official Qwen repository documents the current model releases and serving commands:

- <https://github.com/QwenLM/Qwen3.6>
- <https://huggingface.co/collections/Qwen/qwen36>

## DeepSeek alternative

The client is provider-independent. To use a DeepSeek model, start it behind an OpenAI-compatible
server with JSON Schema structured-output support, then set `MDMETA_LLM_MODEL` to the exact model ID.
Do not call a model "latest" in a report unless the exact public model repository and weight revision
were recorded at execution time.

For example:

```bash
export MDMETA_LLM_MODEL=deepseek-ai/DeepSeek-V3-0324
```

Large DeepSeek models may need multi-GPU or distributed inference. A smaller distilled model can be
used for engineering checks, but its results must be reported under its exact model ID and must not
be presented as results from the full model.

## Configuration

```bash
export MDMETA_LLM_BASE_URL=http://127.0.0.1:8000/v1
export MDMETA_LLM_MODEL=Qwen/Qwen3.6-27B
export MDMETA_LLM_API_KEY=
export MDMETA_LLM_TIMEOUT_SECONDS=180
export MDMETA_LLM_MAX_OUTPUT_TOKENS=4096
export MDMETA_LLM_MAX_RETRIES=2
export MDMETA_LLM_RETRY_BACKOFF_SECONDS=1
export MDMETA_LLM_DISABLE_THINKING=true
export MDMETA_LLM_SEED=0
```

`MDMETA_LLM_API_KEY` is optional for an unauthenticated local server. It is sent as a Bearer token
when present and is never written to the audit record.

## Input

`mdmeta-extract-llm` accepts UTF-8 JSONL with one paragraph per line:

```json
{"document_id":"PMC1","section":"Methods","paragraph_id":"p1","text":"The production simulation was run for 100 ns at 300 K in the NPT ensemble."}
```

The pair `(document_id, paragraph_id)` must be unique. Paragraphs are grouped by document and split
into bounded requests. The default is eight paragraphs per model request.

## Run

```bash
mdmeta-extract-llm \
  --input results/llm/paragraphs.jsonl \
  --output results/llm/qwen3.6-27b-events.json \
  --max-paragraphs-per-request 8
```

The output records:

- exact model ID;
- prompt version;
- source input SHA-256;
- accepted events and exact evidence spans;
- request and completion identifiers when supplied by the server;
- prompt, JSON Schema and raw model-response SHA-256 values;
- request latency and attempt count; and
- prompt, completion and total token counts when supplied by the server.

The audit stores hashes rather than the full prompt or API key. The source paragraphs must be
retained separately under the corpus access and licensing policy if the result needs to be
reproduced.

## Required evaluation before performance claims

A model run is not an accuracy result. Before comparing Qwen, DeepSeek, the deterministic extractor
or a hybrid method:

1. freeze the article identifiers, source hashes, model weights/revision, prompt version, JSON Schema,
   decoding parameters and code commit;
2. keep the machine outputs hidden from independent human annotators;
3. complete dual exact-span annotation and adjudication;
4. score strict events, phase-aware fields and duration-plus-phase separately;
5. report precision, recall, F1, article-bootstrap intervals, invalid-output rate, abstention rate,
   latency and token use; and
6. retain error groups for time step, sampling interval, analysis window, phase association and
   unsupported inference.

Until that work is complete, the appropriate claim is that the repository has a concrete,
auditable open-weight LLM inference path, not that Qwen or DeepSeek improves extraction accuracy.
