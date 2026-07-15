nextflow.enable.dsl = 2

params.paragraphs = null
params.reference = null
params.deterministic = null
params.outdir = 'results/nextflow'
params.max_paragraphs_per_request = 1
params.bootstrap_iterations = 2000
params.seed = 3997

process EXTRACT_LLM {
    tag "LLM extraction"
    publishDir params.outdir, mode: 'copy', overwrite: true

    input:
    path paragraphs

    output:
    path 'llm-events.json', emit: events

    script:
    """
    mdmeta-extract-llm \
      --input ${paragraphs} \
      --output llm-events.json \
      --max-paragraphs-per-request ${params.max_paragraphs_per_request}
    """
}

process COMPARE_SYSTEMS {
    tag "deterministic vs LLM vs hybrid"
    publishDir params.outdir, mode: 'copy', overwrite: true

    input:
    path llm_events
    path reference
    path deterministic

    output:
    path 'comparison.json'
    path 'comparison.md'

    script:
    """
    python scripts/compare_extraction_systems.py \
      --reference ${reference} \
      --system deterministic=${deterministic} \
      --system llm=${llm_events} \
      --hybrid hybrid deterministic llm \
      --baseline deterministic \
      --bootstrap-iterations ${params.bootstrap_iterations} \
      --seed ${params.seed} \
      --output comparison.json \
      --markdown comparison.md
    """
}

workflow {
    if (!params.paragraphs) {
        error 'Required parameter: --paragraphs /path/to/frozen-paragraphs.jsonl'
    }

    paragraphs_ch = Channel.fromPath(params.paragraphs, checkIfExists: true)
    llm_events = EXTRACT_LLM(paragraphs_ch)

    if (params.reference && params.deterministic) {
        reference_ch = Channel.fromPath(params.reference, checkIfExists: true)
        deterministic_ch = Channel.fromPath(params.deterministic, checkIfExists: true)
        COMPARE_SYSTEMS(llm_events.events, reference_ch, deterministic_ch)
    }
}
