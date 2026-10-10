"""Markdown report rendering."""

from __future__ import annotations

import json
from datetime import date as _date

from .score import TIER_TITLES, tier_of

TIER_ORDER = ["must_read", "worth_reading", "other"]


def _fmt_date(value: str) -> str:
    """Elsevier-style feeds stamp the *issue* date, which can be in the future."""
    if not value:
        return "未知"
    return f"{value}（在线预发表）" if value > _date.today().isoformat() else value


def _link(item) -> str:
    if getattr(item, "url", ""):
        return item.url
    if getattr(item, "doi", ""):
        return f"https://doi.org/{item.doi}"
    return ""


def _doi_link(doi: str) -> str:
    return f"[{doi}](https://doi.org/{doi})" if doi else "—"


def _truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut + " …"


def _frontmatter(
    *,
    day: str,
    cfg: dict,
    counts: dict,
    statuses: list[dict],
    fetched_total: int,
    matched_total: int,
    new_count: int,
    listed: int,
    generated_at: str,
    scope: str = "",
) -> list[str]:
    """YAML front matter, so Obsidian properties and Dataview can query reports.

    Lists are emitted with ``json.dumps`` - JSON is a subset of YAML, so quoting
    stays correct even when a keyword label contains a colon or a quote.

    ``scope`` is set on the per-discipline reports that live in their own
    subdirectory; it makes those files filterable apart from the main report.
    """
    topics = [k.get("label", "") for k in cfg.get("keywords", [])]
    journals = {s["journal"] for s in statuses}
    failed = [s for s in statuses if not s["ok"]]
    lines = [
        "---",
        f"date: {day}",
        f"generated: {generated_at}",
    ]
    if scope:
        lines.append(f"scope: {json.dumps(scope, ensure_ascii=False)}")
    lines.extend([
        f"window_days: {cfg.get('window', {}).get('days', 3)}",
        f"fetched: {fetched_total}",
        f"matched: {matched_total}",
        f"new_count: {new_count}",
        f"listed: {listed}",
        f"must_read: {counts['must_read']}",
        f"worth_reading: {counts['worth_reading']}",
        f"other: {counts['other']}",
        f"journals: {len(journals)}",
        f"sources_failed: {len(failed)}",
        f"topics: {json.dumps(topics, ensure_ascii=False)}",
        f"tags: {json.dumps(['journal-alert'] + ([scope] if scope else []), ensure_ascii=False)}",
        "---",
        "",
    ])
    return lines


def _source_status_section(statuses: list[dict], mode: str) -> list[str]:
    """Render the data-source footer: ``full`` table, ``summary``, or nothing."""
    failed = [s for s in statuses if not s["ok"]]
    if mode == "none":
        return []
    if mode == "summary":
        # Only interesting when something broke - otherwise it is one quiet line
        # at the bottom instead of a 45-row table on every single report.
        if not statuses:
            return []
        journals = len({s["journal"] for s in statuses})
        if not failed:
            return [f"> ✅ 数据源：{journals} 本刊、{len(statuses)} 条通道全部正常。", ""]
        out = [
            "## 数据源状态",
            "",
            f"> ⚠️ {journals} 本刊中 **{len(failed)}** 条通道本次抓取失败，其余正常；失败不影响其他来源。",
            "",
            "| 期刊 | 数据源 | 条数 | 说明 |",
            "|---|---|---|---|",
        ]
        for status in failed:
            note = (status.get("note") or "").replace("|", "/")
            out.append(f"| {status['journal']} | {status['source']} | {status['items']} | {note} |")
        out.append("")
        return out
    # full
    out = ["## 数据源状态", "", "| 期刊 | 数据源 | 状态 | 条数 | 说明 |", "|---|---|---|---|---|"]
    for status in statuses:
        state = "✅" if status["ok"] else "❌"
        note = (status.get("note") or "").replace("|", "/")
        out.append(
            f"| {status['journal']} | {status['source']} | {state} | {status['items']} | {note} |"
        )
    out.append("")
    if failed:
        out.append(f"⚠️ 有 {len(failed)} 个数据源本次抓取失败，上面表格已标明原因；失败不影响其他来源。")
    else:
        out.append("✅ 全部数据源抓取正常。")
    out.append("")
    return out


def build_markdown(
    *,
    day: str,
    cfg: dict,
    entries: list[dict],
    statuses: list[dict],
    fetched_total: int,
    matched_total: int,
    new_count: int = 0,
    seen_before: int = 0,
    generated_at: str,
    entries_total: int | None = None,
    all_entries: list[dict] | None = None,
    scope: str = "",
) -> str:
    project = cfg.get("project", {}).get("name", "文献日报")
    # Tier counts always describe the *whole* matched set, never just the rows we
    # were told to list - otherwise a capped report would claim "必读 10" while
    # the push notification (which counts every new item) says something else.
    counted = all_entries if all_entries is not None else entries
    counts = {tier: 0 for tier in TIER_ORDER}
    for entry in counted:
        counts[tier_of(entry["scored"].score, cfg.get("tiers", {}))] += 1

    keyword_labels = " / ".join(k.get("label", "") for k in cfg.get("keywords", []))
    lines: list[str] = []
    if cfg.get("output", {}).get("frontmatter", True):
        lines.extend(
            _frontmatter(
                day=day,
                cfg=cfg,
                counts=counts,
                statuses=statuses,
                fetched_total=fetched_total,
                matched_total=matched_total,
                new_count=new_count,
                listed=len(entries),
                generated_at=generated_at,
                scope=scope,
            )
        )
    lines.append(f"# {project} · {scope} · {day}" if scope else f"# {project} · {day}")
    lines.append("")
    lines.append(
        f"> 本次运行：抓取 **{fetched_total}** 篇 ｜ 关键词命中 **{matched_total}** 篇 ｜ "
        f"新增 **{new_count}** 篇（其中 {seen_before} 篇此前已读过）"
    )
    if entries_total is not None and entries_total > len(entries):
        lines.append(
            f"> 命中 **{entries_total}** 篇，按重要度只列出前 **{len(entries)}** 篇"
            f"（其余 {entries_total - len(entries)} 篇仍留在历史库；"
            f"调大 `output.max_entries` 后执行 `run.py --rerender` 即可恢复）"
        )
    else:
        lines.append(
            f"> 本日报累计收录 **{len(entries)}** 篇（当天多次运行会自动合并，不重复推送）"
        )
    capped = entries_total is not None and entries_total > len(entries)
    lines.append(
        f"> 必读 **{counts['must_read']}** ｜ 值得一读 **{counts['worth_reading']}** ｜ "
        f"其他相关 **{counts['other']}**" + ("（按全部命中统计）" if capped else "")
    )
    lines.append(f"> 关注方向：{keyword_labels}")
    lines.append(f"> 时间窗：近 {cfg.get('window', {}).get('days', 3)} 天 ｜ 生成时间：{generated_at}")
    if scope:
        lines.append(
            f"> 📁 本文件是 **{scope}** 学科的专属日报，只收录该学科命中的文献；"
            "其余学科见各自的子目录。"
        )
    lines.append("")

    if not entries:
        lines.append("## 今日无新增命中")
        lines.append("")
        lines.append("所有抓取到的文献都已在历史记录中出现过，或没有文献同时满足关键词与时间窗条件。")
        lines.append("")
    for tier in TIER_ORDER:
        bucket = [e for e in entries if tier_of(e["scored"].score, cfg.get("tiers", {})) == tier]
        if not bucket:
            continue
        lines.append(f"## {TIER_TITLES[tier]}（{len(bucket)}）")
        lines.append("")
        for index, entry in enumerate(bucket, 1):
            item = entry["item"]
            scored = entry["scored"]
            url = _link(item)
            heading = f"[{item.title}]({url})" if url else item.title
            lines.append(f"### {index}. {heading}")
            lines.append("")
            meta = [
                f"**期刊**：{item.journal}",
                f"**日期**：{_fmt_date(item.date)}",
            ]
            if item.doi:
                meta.append(f"**DOI**：{_doi_link(item.doi)}")
            lines.append("- " + " ｜ ".join(meta))
            hits = "、".join(f"{m.label}（{'标题' if m.field_name == 'title' else '摘要'}：{m.term}）" for m in scored.matches)
            lines.append(f"- **匹配**：{hits} ｜ **得分**：{scored.score}")
            if item.authors:
                lines.append(f"- **作者**：{', '.join(item.authors[:6])}{' 等' if len(item.authors) > 6 else ''}")
            if item.abstract:
                lines.append("")
                lines.append(f"> {_truncate(item.abstract, 700)}")
            lines.append("")
        lines.append("---")
        lines.append("")

    mode = str(cfg.get("output", {}).get("source_status", "full")).lower()
    if mode not in ("full", "summary", "none"):
        mode = "full"
    lines.extend(_source_status_section(statuses, mode))
    lines.append("---")
    lines.append("")
    lines.append(f"*由 journal-alert 自动生成 · {generated_at} · 历史库 `state/seen.sqlite`*")
    lines.append("")
    return "\n".join(lines)


def build_digest(
    *,
    day: str,
    cfg: dict,
    entries: list[dict],
    fetched_total: int,
    matched_total: int,
    max_items: int,
    max_chars: int,
) -> tuple[str, str]:
    """Return ``(title, markdown_body)`` for a push notification.

    Layout rules - both are deliberate, and both have bitten us:

    * one blank line **between** entries, so each item is its own paragraph.
      Without it Markdown runs every entry together into a single block and
      WeChat shows one long line of concatenated text.
    * two trailing spaces **inside** an entry, which is Markdown's hard line
      break. A bare newline is a "soft" break and most renderers collapse it
      into a space, which would glue the title to the journal/date line.
    """
    project = cfg.get("project", {}).get("name", "文献日报")
    must = [e for e in entries if tier_of(e["scored"].score, cfg.get("tiers", {})) == "must_read"]
    must_ids = {id(e) for e in must}
    rest = [e for e in entries if id(e) not in must_ids]
    title = f"{project} {day}：新增 {len(entries)} 篇，必读 {len(must)} 篇"

    blocks: list[str] = []
    shown = 0
    for entry in (must + rest):
        if shown >= max_items:
            break
        item = entry["item"]
        url = _link(item)
        star = "🔥" if id(entry) in must_ids else "·"
        hits = "、".join(entry["scored"].labels)
        if url:
            head = f"{star} [{_truncate(item.title, 120)}]({url})"
        else:
            head = f"{star} {_truncate(item.title, 120)}"
        meta = f"　　{item.journal} · {item.date} · 匹配 {hits}"
        blocks.append(f"{head}  \n{meta}")
        shown += 1

    lines = [f"抓取 {fetched_total} 篇 · 命中 {matched_total} 篇 · 新增 **{len(entries)}** 篇"]
    for block in blocks:
        lines.append("")
        lines.append(block)
    if len(entries) > shown:
        lines.append("")
        lines.append(f"…… 其余 {len(entries) - shown} 篇见本地日报。")

    body = "\n".join(lines)
    if len(body) > max_chars:
        # Cut back to a paragraph boundary so we never truncate mid-entry.
        cut = body[:max_chars].rsplit("\n\n", 1)[0] or body[:max_chars].rsplit("\n", 1)[0]
        body = cut + "\n\n……（已截断，完整内容见本地 Markdown 日报）"
    return title, body
