nextflow.enable.dsl = 2

params.database = null
params.model_summary = null
params.outdir = 'results/mdmeta-production'
params.git_commit = null
params.expected_articles = null
params.purpose = 'production_triage'
params.confidence_threshold = '0.8'
params.audit_sample_rate = '0.05'
params.audit_salt = 'mdmeta-production-audit-v1'
params.allow_missing_pdbekb = false
params.slurm_account = null
params.slurm_queue = 'small'
params.require_slurm_account = false
params.container_image = null
params.require_container_digest = false


process VERIFY_DATABASE {
    tag "articles=${expected_articles}"
    publishDir "${params.outdir}/database", mode: 'copy', overwrite: true

    input:
    path database, stageAs: 'records.sqlite'
    val expected_articles

    output:
    path 'database-manifest.json'

    script:
    """
    python -m mdmeta.verify \
      --database records.sqlite \
      --expected-articles ${expected_articles} \
      --output database-manifest.json
    """
}


process BUILD_REVIEW_QUEUE {
    tag "purpose=${purpose}"
    publishDir "${params.outdir}/review", mode: 'copy', overwrite: true

    input:
    path database, stageAs: 'records.sqlite'
    path model_summary, stageAs: 'model-summary.json'
    path database_manifest, stageAs: 'database-manifest.json'
    val git_commit
    val purpose
    val confidence_threshold
    val audit_sample_rate
    val audit_salt
    val allow_missing_flag

    output:
    path 'human-review-queue.json'

    script:
    """
    python -m mdmeta.human_review build \
      --database records.sqlite \
      --model-summary model-summary.json \
      --output human-review-queue.json \
      --git-commit ${git_commit} \
      --purpose ${purpose} \
      --confidence-threshold ${confidence_threshold} \
      --audit-sample-rate ${audit_sample_rate} \
      --audit-salt ${audit_salt} \
      ${allow_missing_flag}
    """
}


process EXPORT_GRAPH {
    tag 'neo4j-csv'
    publishDir "${params.outdir}", mode: 'copy', overwrite: true

    input:
    path database, stageAs: 'records.sqlite'
    path database_manifest, stageAs: 'database-manifest.json'

    output:
    path 'graph'

    script:
    """
    mkdir graph
    python -m mdmeta.graph export \
      --database records.sqlite \
      --output-dir graph
    """
}


process VERIFY_OUTPUTS {
    tag 'content-bound-results'
    publishDir "${params.outdir}/verification", mode: 'copy', overwrite: true

    input:
    path database, stageAs: 'records.sqlite'
    path model_summary, stageAs: 'model-summary.json'
    path database_manifest, stageAs: 'database-manifest.json'
    path review_queue, stageAs: 'human-review-queue.json'
    path graph, stageAs: 'graph'

    output:
    path 'review-verification.json'
    path 'graph-verification.json'
    path 'checksums.sha256'
    path 'WORKFLOW_COMPLETE'

    script:
    """
    python -m mdmeta.human_review verify \
      --queue human-review-queue.json \
      --database records.sqlite \
      --model-summary model-summary.json \
      > review-verification.json
    python -m mdmeta.graph verify \
      --output-dir graph \
      --database records.sqlite \
      > graph-verification.json
    sha256sum \
      database-manifest.json \
      human-review-queue.json \
      graph/graph-manifest.json \
      graph/nodes.csv \
      graph/relationships.csv \
      > checksums.sha256
    touch WORKFLOW_COMPLETE
    """
}


workflow {
    if (!params.database) {
        error 'Required parameter --database was not supplied'
    }
    if (!params.model_summary) {
        error 'Required parameter --model_summary was not supplied'
    }
    if (!params.git_commit || !(params.git_commit.toString() ==~ /[0-9a-f]{40}/)) {
        error '--git_commit must be a 40-character lowercase Git commit SHA'
    }
    if (params.expected_articles == null ||
        !(params.expected_articles.toString() ==~ /0|[1-9][0-9]*/)) {
        error '--expected_articles must be a non-negative integer'
    }
    if (!(params.purpose.toString() in ['production_triage', 'benchmark_reference'])) {
        error '--purpose must be production_triage or benchmark_reference'
    }
    if (!(params.confidence_threshold.toString() ==~ /(?:0(?:\.[0-9]+)?|1(?:\.0+)?)/)) {
        error '--confidence_threshold must be between 0 and 1'
    }
    if (!(params.audit_sample_rate.toString() ==~ /(?:0(?:\.[0-9]+)?|1(?:\.0+)?)/)) {
        error '--audit_sample_rate must be between 0 and 1'
    }
    if (!(params.audit_salt.toString() ==~ /[A-Za-z0-9._:-]{1,128}/)) {
        error '--audit_salt must contain 1-128 safe identifier characters'
    }
    if (params.require_slurm_account &&
        (!params.slurm_account ||
         !(params.slurm_account.toString() ==~ /project_[0-9]+/))) {
        error 'The csc profile requires --slurm_account project_NNNNNNN'
    }
    if (!(params.slurm_queue.toString() ==~ /[a-z0-9_-]{1,32}/)) {
        error '--slurm_queue contains unsupported characters'
    }
    if (params.require_slurm_account && params.slurm_queue.toString() != 'small') {
        error 'The csc profile is restricted to the x86_64 small CPU partition'
    }
    if (params.require_container_digest &&
        (!params.container_image ||
         !(params.container_image.toString() ==~ /[^\s@]+@sha256:[0-9a-f]{64}/))) {
        error 'Container profiles require --container_image pinned by @sha256 digest'
    }

    def allow_missing = params.allow_missing_pdbekb.toString().toLowerCase()
    if (!(allow_missing in ['true', 'false'])) {
        error '--allow_missing_pdbekb must be true or false'
    }
    def allow_missing_flag = allow_missing == 'true' ? '--allow-missing-pdbekb' : ''

    database_ch = Channel.value(file(params.database, checkIfExists: true))
    model_summary_ch = Channel.value(file(params.model_summary, checkIfExists: true))

    database_manifest = VERIFY_DATABASE(
        database_ch,
        params.expected_articles.toString(),
    )
    review_queue = BUILD_REVIEW_QUEUE(
        database_ch,
        model_summary_ch,
        database_manifest,
        params.git_commit.toString(),
        params.purpose.toString(),
        params.confidence_threshold.toString(),
        params.audit_sample_rate.toString(),
        params.audit_salt.toString(),
        allow_missing_flag,
    )
    graph = EXPORT_GRAPH(database_ch, database_manifest)
    VERIFY_OUTPUTS(
        database_ch,
        model_summary_ch,
        database_manifest,
        review_queue,
        graph,
    )
}
