"""Export endpoints — CSV download / clipboard payload."""

from __future__ import annotations

import csv
import html
import io
from collections import OrderedDict
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from wia.core import review as review_core
from wia.core.types import Review, TimeEntry
from wia.storage import entries as repo

router = APIRouter()

DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _week_days(week_of: str | None) -> list[str]:
    if not week_of:
        return []
    try:
        monday = date.fromisoformat(week_of)
    except ValueError:
        return []
    return [(monday + timedelta(days=i)).isoformat() for i in range(7)]


def _hhmm(hours: float) -> str:
    if not hours:
        return ""
    total_minutes = round(hours * 60)
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def _confidence(value: object) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _group_by_category(entries: list[TimeEntry]) -> OrderedDict[str, list[TimeEntry]]:
    groups: OrderedDict[str, list[TimeEntry]] = OrderedDict()
    for entry in entries:
        key = entry.category or "Uncategorized"
        groups.setdefault(key, []).append(entry)
    return groups


def _group_daily(entries: list[TimeEntry], days: list[str]) -> dict[str, float]:
    return {d: sum(e.daily_hours.get(d, 0) for e in entries) for d in days}


def _group_total(entries: list[TimeEntry]) -> float:
    return sum(e.duration_hours for e in entries)


def _entries_csv(week_of: str | None) -> str:
    entries = repo.list_entries(week_of=week_of)
    days = _week_days(week_of)
    buf = io.StringIO()
    writer = csv.writer(buf)
    header = ["category", "label", "duration_hours", "confidence", "week_of", *days]
    writer.writerow(header)
    # Group rows by category so the CSV mirrors the UI layout.
    for category, group in _group_by_category(entries).items():
        for e in group:
            row = [
                category,
                e.label,
                f"{e.duration_hours:.2f}",
                _confidence(e.confidence),
                e.week_of or "",
                *[f"{e.daily_hours.get(d, 0):.2f}" for d in days],
            ]
            writer.writerow(row)
    return buf.getvalue()


def _entries_markdown(week_of: str | None) -> str:
    entries = repo.list_entries(week_of=week_of)
    days = _week_days(week_of)

    if not entries:
        return f"# WIA Briefing — week of {week_of or '(all)'}\n\n_No entries._\n"

    lines: list[str] = []
    lines.append(f"# WIA Briefing — week of {week_of or '(all)'}\n")
    total = sum(e.duration_hours for e in entries)
    lines.append(f"**Total:** {_hhmm(total)} ({total:.2f}h) across {len(entries)} entries\n")

    header = ["Category", "Label", *DAY_LABELS, "Total", "Confidence"]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"] * len(header)) + "|")

    for category, group in _group_by_category(entries).items():
        # Category summary row.
        cat_daily = _group_daily(group, days)
        cat_total = _group_total(group)
        summary = [
            f"**{category}**",
            f"_{len(group)} item{'s' if len(group) != 1 else ''}_",
            *[f"**{_hhmm(cat_daily[d])}**" if cat_daily[d] else "" for d in days],
            f"**{_hhmm(cat_total)}**",
            "",
        ]
        lines.append("| " + " | ".join(summary) + " |")
        for e in group:
            row = [
                "",
                e.label.replace("|", "\\|"),
                *[_hhmm(e.daily_hours.get(d, 0)) for d in days],
                _hhmm(e.duration_hours),
                _confidence(e.confidence),
            ]
            lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    return "\n".join(lines)


def _entries_html(week_of: str | None) -> str:
    """Render a Word-friendly HTML table of the briefing.

    Word picks up ``text/html`` from the clipboard and renders the table with
    its own styles, so we use a clean ``<table border>`` with inline styles.
    """
    entries = repo.list_entries(week_of=week_of)
    days = _week_days(week_of)
    week_label = week_of or "(all)"

    if not entries:
        return (
            f"<h2>WIA Briefing — week of {html.escape(week_label)}</h2>"
            "<p><em>No entries.</em></p>"
        )

    total = sum(e.duration_hours for e in entries)
    parts: list[str] = []
    parts.append(f"<h2>WIA Briefing — week of {html.escape(week_label)}</h2>")
    parts.append(
        f"<p><strong>Total:</strong> {_hhmm(total)} ({total:.2f}h) "
        f"across {len(entries)} entries</p>"
    )

    cell = (
        'style="border:1px solid #999;padding:4px 8px;'
        'font-family:Calibri,Arial,sans-serif;font-size:11pt;"'
    )
    th = (
        'style="border:1px solid #999;padding:4px 8px;background:#f2f2f2;'
        'font-family:Calibri,Arial,sans-serif;font-size:11pt;text-align:left;"'
    )
    num = (
        'style="border:1px solid #999;padding:4px 8px;text-align:right;'
        'font-family:Consolas,monospace;font-size:10.5pt;"'
    )

    parts.append('<table style="border-collapse:collapse;">')
    parts.append("<thead><tr>")
    parts.append(f"<th {th}>Category</th><th {th}>Label</th>")
    for label in DAY_LABELS:
        parts.append(f"<th {th}>{label}</th>")
    parts.append(f"<th {th}>Total</th><th {th}>Confidence</th>")
    parts.append("</tr></thead><tbody>")

    for category, group in _group_by_category(entries).items():
        cat_daily = _group_daily(group, days)
        cat_total = _group_total(group)
        parts.append('<tr style="background:#fafafa;">')
        parts.append(
            f'<td {cell}><strong>{html.escape(category)}</strong></td>'
            f'<td {cell}><em>{len(group)} item{"s" if len(group) != 1 else ""}</em></td>'
        )
        for d in days:
            parts.append(f"<td {num}><strong>{_hhmm(cat_daily[d])}</strong></td>")
        parts.append(f"<td {num}><strong>{_hhmm(cat_total)}</strong></td>")
        parts.append(f"<td {cell}></td>")
        parts.append("</tr>")
        for e in group:
            parts.append("<tr>")
            parts.append(f"<td {cell}></td><td {cell}>{html.escape(e.label)}</td>")
            for d in days:
                parts.append(f"<td {num}>{_hhmm(e.daily_hours.get(d, 0))}</td>")
            parts.append(f"<td {num}>{_hhmm(e.duration_hours)}</td>")
            parts.append(f"<td {cell}>{html.escape(_confidence(e.confidence))}</td>")
            parts.append("</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


@router.get("/csv")
async def export_csv(week_of: str | None = None) -> StreamingResponse:
    csv_text = _entries_csv(week_of)
    filename = f"wia-briefing-{week_of or 'all'}.csv"
    return StreamingResponse(
        iter([csv_text]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/csv/text")
async def export_csv_text(week_of: str | None = None) -> dict[str, str]:
    """Returns CSV as a JSON string for the pywebview save bridge."""
    return {"text": _entries_csv(week_of)}


@router.get("/markdown")
async def export_markdown(week_of: str | None = None) -> dict[str, str]:
    """Returns a Markdown-formatted briefing."""
    return {"text": _entries_markdown(week_of)}


@router.get("/html")
async def export_html(week_of: str | None = None) -> dict[str, str]:
    """Returns a Word-pasteable HTML table plus a Markdown fallback."""
    return {
        "html": _entries_html(week_of),
        "text": _entries_markdown(week_of),
    }


@router.get("/clipboard")
async def export_clipboard(week_of: str | None = None) -> dict[str, str]:
    """Backwards-compatible alias for the Markdown export."""
    return {"text": _entries_markdown(week_of)}


# ---------------------------------------------------------------------------
# Review exports — monthly / annual 1:1 docs
# ---------------------------------------------------------------------------

SECTION_LABELS = {
    "achievements": "Achievements",
    "focus": "Focus areas",
    "challenges": "Challenges",
    "asks": "Asks / opportunities",
}


def _load_review(period: str) -> Review:
    try:
        kind, year, month = review_core.parse_period(period)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if kind == "month":
        assert month is not None
        return review_core.build_monthly_review(year, month)
    return review_core.build_yearly_review(year)


def _review_markdown(rv: Review) -> str:
    if rv.status == "no-data":
        return f"# WIA Review — {rv.period_label}\n\n_No data for this period yet._\n"

    lines: list[str] = []
    lines.append(f"# WIA Review — {rv.period_label}\n")
    lines.append(
        f"**{rv.totals.total_hours:.0f}h** logged across "
        f"{rv.totals.weeks_observed} week"
        f"{'s' if rv.totals.weeks_observed != 1 else ''} "
        f"({rv.period_start} → {rv.period_end}).\n"
    )

    lines.append("## Headline metrics")
    lines.append(f"- Meetings: **{rv.totals.meetings_hours:.0f}h** "
                 f"({rv.totals.meeting_ratio * 100:.0f}% of total)")
    lines.append(f"- Focus: **{rv.totals.focus_hours:.0f}h**")
    lines.append(f"- Collaboration: **{rv.totals.collaboration_hours:.0f}h**")
    if rv.delta:
        lines.append(
            f"- vs. previous period: "
            f"{rv.delta.total_hours_delta:+.0f}h total · "
            f"{rv.delta.meetings_ratio_delta * 100:+.0f}pp meeting share · "
            f"{rv.delta.focus_hours_delta:+.0f}h focus"
        )
    lines.append("")

    if rv.categories:
        lines.append("## Category breakdown")
        lines.append("| Category | Hours | % | Items |")
        lines.append("|---|---:|---:|---:|")
        for c in rv.categories:
            lines.append(
                f"| {c.category} | {c.hours:.0f} | {c.percent:.0f}% | {c.entry_count} |"
            )
        lines.append("")

    if rv.top_labels:
        lines.append("## Top initiatives")
        for t in rv.top_labels:
            cat = f" · _{t.category}_" if t.category else ""
            lines.append(
                f"- **{t.label}** — {t.hours:.0f}h across "
                f"{t.weeks_active} week{'s' if t.weeks_active != 1 else ''}{cat}"
            )
        lines.append("")

    if rv.insights:
        lines.append("## Insights")
        for ins in rv.insights:
            lines.append(f"- **{ins.title}** — {ins.detail}")
        lines.append("")

    if rv.talking_points:
        lines.append("## 1:1 talking points")
        grouped: dict[str, list[str]] = {key: [] for key in SECTION_LABELS}
        for p in rv.talking_points:
            grouped.setdefault(p.section, []).append(p.text)
        for section, label in SECTION_LABELS.items():
            items = grouped.get(section) or []
            if not items:
                continue
            lines.append(f"### {label}")
            for text in items:
                lines.append(f"- {text}")
            lines.append("")

    return "\n".join(lines)


def _review_html(rv: Review) -> str:
    if rv.status == "no-data":
        return (
            f"<h2>WIA Review — {html.escape(rv.period_label)}</h2>"
            "<p><em>No data for this period yet.</em></p>"
        )

    body_font = "font-family:Calibri,Arial,sans-serif;font-size:11pt;"
    cell = f'style="border:1px solid #999;padding:4px 8px;{body_font}"'
    th = (
        f'style="border:1px solid #999;padding:4px 8px;background:#f2f2f2;'
        f'{body_font}text-align:left;"'
    )
    num = (
        'style="border:1px solid #999;padding:4px 8px;text-align:right;'
        'font-family:Consolas,monospace;font-size:10.5pt;"'
    )

    parts: list[str] = []
    parts.append(f"<h2>WIA Review — {html.escape(rv.period_label)}</h2>")
    parts.append(
        f"<p><strong>{rv.totals.total_hours:.0f}h</strong> across "
        f"{rv.totals.weeks_observed} weeks "
        f"({html.escape(rv.period_start)} → {html.escape(rv.period_end)}).</p>"
    )
    parts.append("<p>")
    parts.append(
        f"Meetings <strong>{rv.totals.meetings_hours:.0f}h</strong> "
        f"({rv.totals.meeting_ratio * 100:.0f}%) · "
        f"Focus <strong>{rv.totals.focus_hours:.0f}h</strong> · "
        f"Collaboration <strong>{rv.totals.collaboration_hours:.0f}h</strong>"
    )
    if rv.delta:
        parts.append(
            f"<br><em>vs. previous period:</em> "
            f"{rv.delta.total_hours_delta:+.0f}h total, "
            f"{rv.delta.meetings_ratio_delta * 100:+.0f}pp meeting share, "
            f"{rv.delta.focus_hours_delta:+.0f}h focus"
        )
    parts.append("</p>")

    if rv.categories:
        parts.append("<h3>Category breakdown</h3>")
        parts.append('<table style="border-collapse:collapse;">')
        parts.append(
            f"<thead><tr><th {th}>Category</th><th {th}>Hours</th>"
            f"<th {th}>%</th><th {th}>Items</th></tr></thead><tbody>"
        )
        for c in rv.categories:
            parts.append(
                f"<tr><td {cell}>{html.escape(c.category)}</td>"
                f"<td {num}>{c.hours:.0f}</td>"
                f"<td {num}>{c.percent:.0f}%</td>"
                f"<td {num}>{c.entry_count}</td></tr>"
            )
        parts.append("</tbody></table>")

    if rv.top_labels:
        parts.append("<h3>Top initiatives</h3><ul>")
        for t in rv.top_labels:
            cat = f" — <em>{html.escape(t.category)}</em>" if t.category else ""
            parts.append(
                f"<li><strong>{html.escape(t.label)}</strong>{cat} — "
                f"{t.hours:.0f}h across {t.weeks_active} week"
                f"{'s' if t.weeks_active != 1 else ''}</li>"
            )
        parts.append("</ul>")

    if rv.insights:
        parts.append("<h3>Insights</h3><ul>")
        for ins in rv.insights:
            parts.append(
                f"<li><strong>{html.escape(ins.title)}</strong> — "
                f"{html.escape(ins.detail)}</li>"
            )
        parts.append("</ul>")

    if rv.talking_points:
        parts.append("<h3>1:1 talking points</h3>")
        grouped: dict[str, list[str]] = {key: [] for key in SECTION_LABELS}
        for p in rv.talking_points:
            grouped.setdefault(p.section, []).append(p.text)
        for section, label in SECTION_LABELS.items():
            items = grouped.get(section) or []
            if not items:
                continue
            parts.append(f"<h4>{html.escape(label)}</h4><ul>")
            for text in items:
                parts.append(f"<li>{html.escape(text)}</li>")
            parts.append("</ul>")

    return "".join(parts)


@router.get("/review/markdown")
async def export_review_markdown(period: str) -> dict[str, str]:
    """Markdown-formatted review for ``period`` (``YYYY-MM`` or ``YYYY``)."""
    return {"text": _review_markdown(_load_review(period))}


@router.get("/review/html")
async def export_review_html(period: str) -> dict[str, str]:
    """Word-pasteable review export with a Markdown fallback."""
    rv = _load_review(period)
    return {"html": _review_html(rv), "text": _review_markdown(rv)}
