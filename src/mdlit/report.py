from __future__ import annotations

import html
from pathlib import Path

from .models import MDRecord


def write_html_report(record: MDRecord, path: str | Path) -> None:
    rows = []
    for fact in record.facts:
        statuses = ", ".join(f"{v.validator}: {v.status}" for v in fact.validation) or "not checked"
        evidence = "<br>".join(
            f"<code>{html.escape(e.quote)}</code><br><small>{html.escape(e.section)} / {html.escape(e.paragraph_id)} "
            f"[{e.start_char}:{e.end_char}] · sha256:{e.context_sha256[:12]}…</small>"
            for e in fact.evidence
        )
        rows.append(
            "<tr>"
            f"<td>{html.escape(fact.field_name)}</td>"
            f"<td>{html.escape(str(fact.normalized_value))} {html.escape(fact.unit or '')}</td>"
            f"<td>{html.escape(fact.phase or '')}</td>"
            f"<td>{fact.confidence:.2f}</td>"
            f"<td>{evidence}</td>"
            f"<td>{html.escape(statuses)}</td>"
            "</tr>"
        )
    event_rows = (
        "".join(
            "<tr>"
            f"<td>{event.order}</td><td>{html.escape(event.phase)}</td>"
            f"<td>{event.duration_value or ''} {html.escape(event.duration_unit or '')}</td>"
            f"<td>{event.temperature_k or ''}</td><td>{event.pressure_bar or ''}</td>"
            f"<td>{html.escape(event.ensemble or '')}</td><td>{event.time_step_ps or ''}</td>"
            f"<td>{event.replicates or ''}</td><td>{html.escape(event.completeness)}</td>"
            "</tr>"
            for event in record.protocol_events
        )
        or '<tr><td colspan="9">No protocol events were formed.</td></tr>'
    )
    mapping_rows = (
        "".join(
            "<tr>"
            f"<td>{html.escape(m.pdb_id)}</td><td>{html.escape(m.uniprot_accession)}</td>"
            f"<td>{html.escape(m.chain_id)}</td><td>{m.pdb_start or ''}–{m.pdb_end or ''}</td>"
            f"<td>{m.uniprot_start or ''}–{m.uniprot_end or ''}</td>"
            "</tr>"
            for m in record.mappings
        )
        or '<tr><td colspan="5">No live mapping was requested or returned.</td></tr>'
    )
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MD literature audit — {html.escape(record.article.document_id)}</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:1200px;margin:2rem auto;padding:0 1rem;line-height:1.45}}
table{{border-collapse:collapse;width:100%;margin:1rem 0 2rem}}th,td{{border:1px solid #bbb;padding:.55rem;vertical-align:top}}th{{background:#f3f3f3;text-align:left}}
code{{white-space:normal}}.notice{{border-left:4px solid #555;padding:.75rem 1rem;background:#f7f7f7}}
</style></head><body>
<h1>MD literature metadata audit</h1>
<div class="notice"><strong>Evidence rule:</strong> extracted values remain separate from external validation. This report does not silently fill missing literature fields.</div>
<p><strong>Document:</strong> {html.escape(record.article.document_id)}<br>
<strong>Title:</strong> {html.escape(record.article.title or "not available")}<br>
<strong>Source:</strong> {html.escape(record.article.source_uri)}<br>
<strong>Generated:</strong> {record.generated_at.isoformat()}</p>
<h2>Extracted facts</h2>
<table><thead><tr><th>Field</th><th>Normalized value</th><th>Phase</th><th>Confidence</th><th>Evidence</th><th>Validation</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table>
<h2>Protocol events</h2>
<table><thead><tr><th>Order</th><th>Phase</th><th>Duration</th><th>Temperature K</th><th>Pressure bar</th><th>Ensemble</th><th>Time step ps</th><th>Replicates</th><th>Status</th></tr></thead><tbody>{event_rows}</tbody></table>
<h2>PDB–UniProt mappings</h2>
<table><thead><tr><th>PDB</th><th>UniProt</th><th>Chain</th><th>PDB residues</th><th>UniProt residues</th></tr></thead><tbody>{mapping_rows}</tbody></table>
<h2>MDDB partial export status</h2>
<pre>{html.escape(str(record.to_mddb_partial()))}</pre>
</body></html>"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8")
