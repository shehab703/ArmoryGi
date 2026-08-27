"""
HTML preview for weapon reports (used by Reports workspace).
"""
from __future__ import annotations

import base64
from collections import defaultdict
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from utils import weapon_reports as wr

REPORT_KIND_DATA_EXPORT = "data_export"
REPORT_KIND_INDIVIDUAL = "individual"
REPORT_KIND_MULTI_COMPARE = "multi_compare"
REPORT_KIND_BY_CATEGORY = "by_category"
REPORT_KIND_FULL_SPECS = "full_specs"

DEFAULT_UI_LABELS = {
    "Report preview": "Report preview",
    "Report type": "Report type",
    "Records": "Records",
    "Specifications": "Specifications",
    "Field": "Field",
    "Value": "Value",
    "Gallery": "Gallery",
    "No images on file.": "No images on file.",
    "Range / effects diagram": "Range / effects diagram",
    "Included in export: real map snapshot with effects overlays.": "Included in export: real map snapshot with effects overlays.",
}


def _img_data_uri(path: str, max_bytes: int = 1_200_000) -> str:
    try:
        p = Path(path)
        if not p.is_file():
            return ""
        raw = p.read_bytes()
        if len(raw) > max_bytes:
            raw = raw[:max_bytes]
        suf = p.suffix.lower().lstrip(".") or "png"
        if suf == "jpg":
            suf = "jpeg"
        b64 = base64.b64encode(raw).decode("ascii")
        return f"data:image/{suf};base64,{b64}"
    except OSError:
        return ""


def _style() -> str:
    return """
    <style>
      body { font-family: Segoe UI, Roboto, Arial, sans-serif; background:#0b1018; color:#e6edf3;
             margin:0; padding:16px; line-height:1.45; }
      h1 { color:#58d8ff; font-size:1.35rem; margin:0 0 12px 0; }
      h2 { color:#9bdcff; font-size:1.05rem; margin:18px 0 8px 0; border-bottom:1px solid #234; padding-bottom:4px;}
      .intro { background:#121b28; border:1px solid #2a3f55; padding:10px 12px; border-radius:6px; margin-bottom:14px;
                white-space:pre-wrap; }
      table { border-collapse:collapse; width:100%; margin:8px 0 16px 0; font-size:0.88rem; }
      th, td { border:1px solid #345; padding:6px 8px; text-align:left; vertical-align:top; }
      th { background:#152536; color:#9ad; }
      tr:nth-child(even) td { background:#0f1622; }
      .muted { color:#8a9bb0; font-size:0.85rem; }
      .gallery { display:flex; flex-wrap:wrap; gap:10px; margin:10px 0; }
      .gallery img { max-width:220px; max-height:160px; border-radius:6px; border:1px solid #345; }
      .pill { display:inline-block; background:#1a2a40; padding:2px 8px; border-radius:10px; margin:2px; font-size:0.8rem;}
    </style>
    """


def build_preview_html(
    report_kind: str,
    weapons: Sequence[Dict[str, Any]],
    *,
    meta: Optional[Dict[str, Any]] = None,
    include_map: bool = False,
    include_sections: Optional[Dict[str, bool]] = None,
    max_gallery_images: int = 8,
    lang_manager=None,
) -> str:
    """Build self-contained HTML for QTextBrowser / QWebEngineView preview."""
    meta = meta or {}
    include_sections = include_sections or {}
    tr = lang_manager.tr if lang_manager else (lambda s: s)
    tr_data = lang_manager.tr_data if lang_manager else (lambda v: v)

    use_title = include_sections.get("title", True)
    use_intro = include_sections.get("intro", True)
    use_closing = include_sections.get("closing", True)
    use_specs = include_sections.get("specs", True)
    use_gallery = include_sections.get("gallery", True)

    title = (meta.get("document_title") or "").strip() or tr("Report preview")
    intro = (meta.get("introduction") or "").strip() if use_intro else ""
    closing = (meta.get("closing_notes") or "").strip() if use_closing else ""

    parts: List[str] = ["<!DOCTYPE html><html><head><meta charset='utf-8'>", _style(), "</head><body>"]
    if use_title:
        parts.append(f"<h1>{escape(title)}</h1>")
    if intro:
        parts.append(f"<div class='intro'>{escape(intro)}</div>")
    parts.append(
        f"<p class='muted'>{escape(tr('Report type'))}: {escape(report_kind)} &nbsp;|&nbsp; "
        f"{escape(tr('Records'))}: {len(weapons)}</p>"
    )

    if report_kind == REPORT_KIND_DATA_EXPORT:
        if not weapons:
            parts.append("<p>No rows.</p>")
        else:
            keys = list(weapons[0].keys())
            parts.append("<h2>Sample (first 12 columns, first 20 rows)</h2><table><tr>")
            show_keys = keys[:12]
            for k in show_keys:
                parts.append(f"<th>{escape(k)}</th>")
            parts.append("</tr>")
            for row in weapons[:20]:
                parts.append("<tr>")
                for k in show_keys:
                    v = row.get(k)
                    if isinstance(v, (list, dict)):
                        v = str(v)[:80] + "…"
                    parts.append(f"<td>{escape(str(v) if v is not None else '')}</td>")
                parts.append("</tr>")
            parts.append("</table>")

    elif report_kind == REPORT_KIND_INDIVIDUAL:
        w = weapons[0] if weapons else {}
        if not w:
            parts.append("<p class='muted'>Select a weapon in the list to preview this report.</p>")
        else:
            if use_specs:
                parts.append(f"<h2>{escape(tr('Specifications'))}</h2><table>")
                parts.append(f"<tr><th>{escape(tr('Field'))}</th><th>{escape(tr('Value'))}</th></tr>")
                for key, lab in wr.INDIVIDUAL_SPEC_ROWS:
                    label = tr(lab)
                    val = w.get(key)
                    if key in {"category", "country", "status", "guidance", "propulsion", "warhead_type", "platform", "manufacturer"}:
                        val = tr_data(val)
                    parts.append(
                        f"<tr><td>{escape(label)}</td><td>{escape(str(val if val is not None else ''))}</td></tr>"
                    )
                parts.append("</table>")
            if use_gallery:
                parts.append(f"<h2>{escape(tr('Gallery'))}</h2><div class='gallery'>")
                shown = 0
                for p in wr.collect_image_paths(w):
                    if shown >= max_gallery_images:
                        break
                    uri = _img_data_uri(p)
                    if uri:
                        parts.append(f"<img src='{uri}' alt='' />")
                        shown += 1
                if not shown:
                    parts.append(f"<span class='muted'>{escape(tr('No images on file.'))}</span>")
                parts.append("</div>")
            if include_map:
                parts.append(f"<h2>{escape(tr('Range / effects diagram'))}</h2>")
                parts.append(
                    f"<p class='muted'>{escape(tr('Included in export: real map snapshot with effects overlays.'))}</p>"
                )

    elif report_kind == REPORT_KIND_MULTI_COMPARE:
        selected_spec_fields = [str(k) for k in (meta.get("spec_fields") or []) if str(k).strip()]
        selected_rows = wr._resolve_spec_rows({"spec_fields": selected_spec_fields}, lang_manager=lang_manager) if selected_spec_fields else wr._resolve_spec_rows(None, lang_manager=lang_manager)
        for w in weapons:
            parts.append(f"<h2>{escape(str(w.get('weapon_name','')))}</h2>")
            chip_parts = []
            for key, label in selected_rows[:5]:
                val = w.get(key)
                if key in {"category", "country", "status", "guidance", "propulsion", "warhead_type", "platform", "manufacturer"}:
                    val = tr_data(val)
                chip_parts.append(f"<span class='pill'>{escape(str(label))}: {escape(str(val if val is not None else ''))}</span>")
            parts.append(f"<p>{''.join(chip_parts)}</p>")
            parts.append("<div class='gallery'>")
            n = 0
            for p in wr.collect_image_paths(w):
                if n >= 4:
                    break
                uri = _img_data_uri(p)
                if uri:
                    parts.append(f"<img src='{uri}' alt='' />")
                    n += 1
            parts.append("</div>")

    elif report_kind == REPORT_KIND_BY_CATEGORY:
        by_cat: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for w in weapons:
            by_cat[str(w.get("category") or "Uncategorized")].append(w)
        for cat in sorted(by_cat.keys(), key=lambda s: s.lower()):
            parts.append(f"<h2>{escape(cat)}</h2><table><tr>")
            parts.append("<th>Weapon</th><th>Model</th><th>Country</th><th>Range</th><th>Status</th></tr>")
            for w in sorted(by_cat[cat], key=lambda x: str(x.get("weapon_name", "")).lower()):
                parts.append(
                    "<tr>"
                    f"<td>{escape(str(w.get('weapon_name','')))}</td>"
                    f"<td>{escape(str(w.get('model','')))}</td>"
                    f"<td>{escape(str(w.get('country','')))}</td>"
                    f"<td>{escape(str(w.get('range_km','')))}</td>"
                    f"<td>{escape(str(w.get('status','')))}</td>"
                    "</tr>"
                )
            parts.append("</table>")

    elif report_kind == REPORT_KIND_FULL_SPECS:
        parts.append("<h2>Catalog (summary)</h2><p class='muted'>Export includes full spec blocks per weapon.</p><table><tr>")
        for _, lab in wr.FULL_SPEC_COLUMNS[:10]:
            parts.append(f"<th>{escape(lab)}</th>")
        parts.append("</tr>")
        keys = [k for k, _ in wr.FULL_SPEC_COLUMNS[:10]]
        for w in weapons[:40]:
            parts.append("<tr>")
            for k in keys:
                v = w.get(k)
                s = str(v) if v is not None else ""
                if len(s) > 120:
                    s = s[:117] + "…"
                parts.append(f"<td>{escape(s)}</td>")
            parts.append("</tr>")
        if len(weapons) > 40:
            parts.append(f"<tr><td colspan='{len(keys)}' class='muted'>… {len(weapons) - 40} more rows in export …</td></tr>")
        parts.append("</table>")

    if closing:
        parts.append(f"<h2>Closing / appendix</h2><div class='intro'>{escape(closing)}</div>")
    parts.append("</body></html>")
    return "".join(parts)
