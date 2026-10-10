"""Static card-wall page: every report in ``reports/`` becomes one HTML file.

Why re-parse the Markdown instead of keeping a second database: the ``reports/``
directory already *is* the archive (``output.keep_days`` prunes it, nothing else
does), and a full rebuild of a year of reports takes a few hundred milliseconds.
Deriving the page from them means the page can never drift out of sync with the
reports, and a failed fetch never leaves it half-written.

The emitted file is deliberately self-contained - no CDN, no webfont, no image
host, no external request of any kind. That keeps it working when opened
straight from disk via ``file://`` and makes it publishable by GitHub Pages
exactly as written.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from .score import TIER_TITLES

#: Report section headings (``## 必读（16）``) keyed by tier id.
TIER_SECTIONS = {title: tier for tier, title in TIER_TITLES.items()}

#: Palette slots used by the stylesheet. Known labels keep their semantic
#: colour; anything else falls back to the neutral slot.
THEME_KEYS = ("air", "rs", "chem", "bgc", "gis")
THEME_BY_TOPIC = {
    "空气污染": "air",
    "遥感": "rs",
    "大气化学": "chem",
    "生物地球化学": "bgc",
    "城市地理信息系统": "gis",
}

#: Journal -> short badge label. Long names would wrap and wreck the cover.
JOURNAL_ABBR = {
    "Atmospheric Chemistry and Physics": "ACP",
    "Atmospheric Environment": "Atmos Environ",
    "Remote Sensing of Environment": "RSE",
    "Environmental Science & Technology": "ES&T",
    "Environmental Research Letters": "ERL",
    "Geophysical Research Letters": "GRL",
    "Journal of Geophysical Research: Atmospheres": "JGR-A",
    "Science Advances": "Sci Adv",
    "Nature Communications": "Nat Commun",
    "Nature Climate Change": "Nat Clim Chang",
    "Nature Geoscience": "Nat Geosci",
    "Nature Sustainability": "Nat Sustain",
    "Nature Cities": "Nat Cities",
}

#: Feeds split subscripts into a separate token ("CO 2", "NO x"), which reads
#: badly in a card title. Repair the common ones.
CHEM_FIXES = (
    ("PM 2.5", "PM2.5"), ("PM 10", "PM10"), ("PM 1", "PM1"),
    ("H 2 O 2", "H₂O₂"), ("N 2 O", "N₂O"), ("CH 4", "CH₄"), ("NH 3", "NH₃"),
    ("CO 2", "CO₂"), ("SO 2", "SO₂"), ("SO 4", "SO₄"), ("NO x", "NOₓ"),
    ("NO 2", "NO₂"), ("NO 3", "NO₃"), ("O 3", "O₃"), ("O 2", "O₂"), ("H 2 O", "H₂O"),
)

_ENTRY_RE = re.compile(r"^\s*###\s+\d+\.\s*\[(.+?)\]\((.+?)\)", re.MULTILINE)
_FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)


def _clean(text: str) -> str:
    """Normalise feed text for display (subscripts, stray punctuation spaces)."""
    if not text:
        return ""
    for src, dst in CHEM_FIXES:
        text = text.replace(src, dst)
    text = re.sub(r"\s+([,;.)\]])", r"\1", text)
    text = re.sub(r"([(\[])\s+", r"\1", text)
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\s+:\s+", ": ", text)
    return text.strip()


def _field(block: str, name: str, *, stop: str = "｜") -> str:
    """Read one ``- **名称**：值`` bullet, stopping at the ``｜`` separator."""
    match = re.search(rf"\*\*{name}\*\*：\s*(.+?)(?:\s*{stop}|\s*$)", block, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _sort_date(value: str) -> str:
    """Strip the ``（在线预发表）`` suffix so dates compare as plain ISO strings."""
    return (value or "").split("（")[0].strip()


def parse_report(path: Path) -> tuple[dict, list[dict]]:
    """Parse one Markdown report into ``(meta, entries)``.

    A malformed report yields whatever could be read rather than raising: one
    bad file in a year of archives must not take the whole page down.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    day = path.stem

    meta: dict = {"date": day, "topics": [], "generated": ""}
    front = _FRONTMATTER_RE.match(text)
    body = text
    if front:
        body = text[front.end():]
        for line in front.group(1).splitlines():
            key, _, value = line.partition(":")
            key, value = key.strip(), value.strip()
            if key == "topics":
                meta["topics"] = [t.strip().strip('"') for t in value.strip("[]").split(",") if t.strip()]
            elif key in ("generated", "fetched", "matched", "new_count"):
                meta[key] = value

    entries: list[dict] = []
    # Split on "## <section>" headings; part 0 is the preamble.
    parts = re.split(r"^##\s+(.+?)\s*$", body, flags=re.MULTILINE)
    for index in range(1, len(parts) - 1, 2):
        heading, content = parts[index], parts[index + 1]
        tier = next(
            (t for title, t in TIER_SECTIONS.items() if heading.startswith(title)),
            None,
        )
        if tier is None:
            continue  # e.g. "## 数据源状态"
        for block in re.split(r"^(?=###\s+\d+\.\s)", content, flags=re.MULTILINE):
            match = _ENTRY_RE.match(block)
            if not match:
                continue
            entry = _parse_entry(block, match)
            entry["tier"] = tier
            entry["tierLabel"] = TIER_TITLES[tier]
            entry["reportDate"] = day
            entries.append(entry)
    return meta, entries


def _parse_entry(block: str, match: re.Match) -> dict:
    title, url = _clean(match.group(1)), match.group(2).strip()

    doi = ""
    doi_match = re.search(r"\*\*DOI\*\*：\s*\[(.+?)\]", block)
    if doi_match:
        doi = doi_match.group(1).strip()

    # "**匹配**：空气污染（标题：no2）、遥感（标题：tropomi） ｜ **得分**：27"
    # One article routinely hits several keyword groups at once, and the report
    # joins them with "、". It belongs to *every* one of them - reading only the
    # first label silently drops about a quarter of the classification.
    raw_match = _field(block, "匹配")
    pairs = re.findall(r"([^、（）]+?)（(标题|摘要)：(.+?)）", raw_match)
    topics = [label.strip() for label, _, _ in pairs if label.strip()]
    if not topics and raw_match:
        topics = [raw_match.strip()]
    where = "、".join(f"{field}：{term}" for _, field, term in pairs)

    score_text = _field(block, "得分")
    score = int(score_text) if score_text.isdigit() else None

    authors_raw = re.search(r"\*\*作者\*\*：\s*(.+?)\s*$", block, re.MULTILINE)
    authors_text = _clean(authors_raw.group(1)) if authors_raw else ""
    more = authors_text.endswith("等")
    authors = [a.strip() for a in re.sub(r"\s*等\s*$", "", authors_text).split(",") if a.strip()]

    abstract = " ".join(q.strip() for q in re.findall(r"^>\s?(.+)$", block, re.MULTILINE)).strip()

    journal = _field(block, "期刊")
    return {
        "title": title,
        "url": url,
        "doi": doi,
        "journal": journal,
        "jabbr": JOURNAL_ABBR.get(journal, journal or "—"),
        "pubdate": _field(block, "日期"),
        # ``topic`` is the primary label (the first group that hit, i.e. config
        # order) and drives the cover chip and the section grouping; ``topics``
        # carries every match and drives filtering.
        "topic": topics[0] if topics else "其他",
        "topics": topics or ["其他"],
        "matchTerm": pairs[0][2].strip() if pairs else "",
        "matchWhere": where,
        "score": score,
        "authors": authors,
        "authorMore": more,
        "abstract": _clean(abstract),
    }


def collect(reports_dir: Path, topic_labels: list[str] | None = None
            ) -> tuple[list[dict], list[dict], list[str]]:
    """Parse every report into ``(articles, reports, topics)``.

    Reports are walked newest first and an article is kept only on its first
    sighting, so a paper that shows up in several days' reports appears once,
    with the freshest metadata.

    ``topic_labels`` is ``config.json``'s keyword order and wins outright. That
    matters when a topic has just been added: no report on disk mentions it yet,
    but it still has to get a tab, otherwise the category is invisible until the
    next report happens to contain it. Labels seen only in the reports are
    appended afterwards, so a report from an older config still renders.
    """
    # rglob, not glob: a day is now one top-level file plus one file per
    # discipline subdirectory. Sorting by stem keeps days in order regardless
    # of which folder a file sits in.
    paths = sorted(reports_dir.rglob("*.md"), key=lambda p: p.stem, reverse=True)
    by_day: dict[str, dict] = {}
    articles: list[dict] = []
    topics: list[str] = [t for t in (topic_labels or []) if t]
    seen: set[str] = set()

    for path in paths:
        meta, entries = parse_report(path)
        # Several files share a date now, so the day's row accumulates instead
        # of being appended once per file.
        day = by_day.setdefault(meta["date"], {"date": meta["date"], "generated": "", "count": 0})
        day["count"] += len(entries)
        day["generated"] = max(day["generated"], meta.get("generated", "") or "")
        for label in meta.get("topics", []):
            if label and label not in topics:
                topics.append(label)
        for entry in entries:
            key = (entry["doi"] or entry["title"]).lower()
            if key in seen:
                continue
            seen.add(key)
            for label in entry["topics"]:
                if label != "其他" and label not in topics:
                    topics.append(label)
            entry["tkey"] = THEME_BY_TOPIC.get(entry["topic"], "other")
            articles.append(entry)

    # Sort here as well as in the browser: the ids below are array positions,
    # so they must be handed out *after* the final order is fixed.
    articles.sort(key=lambda a: (a["score"] or 0, _sort_date(a["pubdate"])), reverse=True)
    for index, entry in enumerate(articles):
        entry["id"] = index

    reports = sorted(by_day.values(), key=lambda r: r["date"], reverse=True)
    return articles, reports, topics


def build_html(articles: list[dict], reports: list[dict], topics: list[str],
               *, project: str, generated_at: str) -> str:
    """Render the self-contained page."""
    payload = json.dumps(
        {
            "articles": articles,
            "reports": reports,
            "topics": topics,
            "themeKeys": list(THEME_KEYS),
            "topicTheme": THEME_BY_TOPIC,
            "generated": generated_at,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    # Keep the payload safe to sit inside a <script> element.
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")

    return (
        _TEMPLATE
        .replace("/*__DATA__*/", payload)
        .replace("__PROJECT__", html.escape(project))
        .replace("__GEN__", generated_at)
        .replace("__TOTAL__", str(len(articles)))
    )


def write_cards(reports_dir: Path, out_path: Path, *, project: str = "文献日报",
                topic_labels: list[str] | None = None, log=None) -> Path | None:
    """Build the page from ``reports_dir`` into ``out_path``.

    Returns the written path, or ``None`` when there is nothing to publish.
    """
    articles, reports, topics = collect(Path(reports_dir), topic_labels)
    if not articles:
        if log:
            log.info("cards page skipped: no reports found in %s", reports_dir)
        return None

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    out_path.write_text(
        build_html(articles, reports, topics, project=project, generated_at=generated_at),
        encoding="utf-8",
        newline="\n",
    )
    if log:
        log.info("cards page written: %s (%d articles from %d reports)",
                 out_path, len(articles), len(reports))
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the static card-wall page from reports/")
    parser.add_argument("--reports", default="reports", help="directory holding the Markdown reports")
    parser.add_argument("--out", default="docs/index.html", help="output HTML path")
    parser.add_argument("--project", default="文献日报", help="project name shown in the header")
    parser.add_argument("--config", default="config.json",
                        help="config.json, read only to get the keyword label order")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    topic_labels: list[str] = []
    cfg_path = Path(args.config)
    if cfg_path.is_file():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            topic_labels = [k.get("label", "") for k in cfg.get("keywords", [])]
        except (OSError, json.JSONDecodeError) as exc:
            print(f"警告：{cfg_path} 读取失败（{exc}），改用日报里的标签顺序。")

    written = write_cards(Path(args.reports), Path(args.out),
                          project=args.project, topic_labels=topic_labels)
    if written is None:
        print(f"没有在 {args.reports} 找到任何日报，未生成页面。")
        return 1
    print(f"已生成 {written}")
    return 0


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>__PROJECT__ · 文献卡片墙</title>
<style>
:root{
  --bg:#f1f2f4; --card:#fff; --ink:#1c1c1e; --ink2:#63636d; --ink3:#9d9da8;
  --line:#eeeef2; --red:#ff2442; --radius:16px;
  --sh:0 1px 2px rgba(16,16,24,.05), 0 6px 20px rgba(16,16,24,.06);
  --sh-hover:0 2px 6px rgba(16,16,24,.07), 0 14px 34px rgba(16,16,24,.12);
  --air-a:#ffb27a; --air-b:#ff5f7e;
  --rs-a:#63b3ff;  --rs-b:#3a5ce0;
  --chem-a:#c3a0ff; --chem-b:#7048e8;
  --bgc-a:#6ee0a8;  --bgc-b:#0b9e73;
  --gis-a:#5ed6c4;  --gis-b:#0d8f9e;
  --other-a:#c9ccd4; --other-b:#8b90a0;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{
  background:var(--bg); color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
  -webkit-font-smoothing:antialiased; text-rendering:optimizeLegibility; padding-bottom:56px;
}
a{color:inherit;text-decoration:none}
svg.ic{display:block;flex:none}

.topbar{
  position:sticky; top:0; z-index:60; background:rgba(241,242,244,.84);
  backdrop-filter:saturate(180%) blur(16px); -webkit-backdrop-filter:saturate(180%) blur(16px);
  border-bottom:1px solid rgba(0,0,0,.05);
}
.topbar-in{max-width:1560px;margin:0 auto;padding:14px 22px 0}
.brand{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.logo{
  width:30px;height:30px;border-radius:9px;flex:none;
  background:linear-gradient(135deg,var(--red),#ff7a59);
  display:grid;place-items:center;color:#fff;font-weight:800;font-size:15px;
  box-shadow:0 3px 10px rgba(255,36,66,.32);
}
.brand h1{font-size:17px;margin:0;font-weight:800;letter-spacing:.2px}
.brand .sub{font-size:12.5px;color:var(--ink3);margin-left:2px}
.brand .spacer{flex:1}
.kpi{display:flex;gap:6px;flex-wrap:wrap}
.kpi span{font-size:12px;color:var(--ink2);background:#fff;border:1px solid var(--line);padding:3px 9px;border-radius:999px;white-space:nowrap}
.kpi b{color:var(--red);font-weight:700}

.controls{max-width:1560px;margin:0 auto;padding:12px 22px;display:flex;flex-direction:column;gap:10px}
.row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.tabs{display:flex;gap:8px;overflow-x:auto;padding-bottom:2px;scrollbar-width:none}
.tabs::-webkit-scrollbar{display:none}
.tab{
  border:1px solid var(--line);background:#fff;color:var(--ink2);
  font-size:13.5px;font-weight:600;padding:7px 14px;border-radius:999px;cursor:pointer;
  white-space:nowrap;transition:.16s;display:flex;align-items:center;gap:7px;font-family:inherit;
}
.tab svg{width:15px;height:15px;stroke-width:1.9}
.tab:hover{border-color:#dcdce4;transform:translateY(-1px)}
.tab .n{font-size:11.5px;color:var(--ink3);font-weight:600}
.tab.on{background:var(--ink);border-color:var(--ink);color:#fff}
.tab.on .n{color:rgba(255,255,255,.66)}
.tab.on svg{stroke-width:2}
.search{
  flex:1;min-width:180px;max-width:340px;border:1px solid var(--line);background:#fff;border-radius:999px;
  padding:8px 15px;font-size:13.5px;outline:none;font-family:inherit;color:var(--ink);transition:.16s;
}
.search:focus{border-color:#ffc2cc;box-shadow:0 0 0 3px rgba(255,36,66,.09)}
.search::placeholder{color:var(--ink3)}
.seg{display:flex;background:#fff;border:1px solid var(--line);border-radius:999px;padding:2px}
.seg button{border:0;background:transparent;font-size:12.5px;padding:5px 12px;border-radius:999px;cursor:pointer;color:var(--ink2);font-family:inherit;transition:.16s}
.seg button.on{background:var(--ink);color:#fff;font-weight:600}
.count{font-size:12.5px;color:var(--ink3);margin-left:auto;white-space:nowrap}

.grouphead{max-width:1560px;margin:24px auto 0;padding:0 22px;display:flex;align-items:center;gap:10px}
.grouphead h2{font-size:15.5px;margin:0;font-weight:800;display:flex;align-items:center;gap:8px}
.grouphead h2 svg{width:18px;height:18px;stroke-width:1.9}
.grouphead .bar{flex:1;height:1px;background:linear-gradient(90deg,var(--line),transparent)}
.grouphead .gn{font-size:12.5px;color:var(--ink3);font-weight:600}
.g-air h2{color:#e8455f} .g-rs h2{color:#3a5ce0} .g-chem h2{color:#7048e8} .g-bgc h2{color:#0b9e73} .g-gis h2{color:#0d8f9e}

.wall{max-width:1560px;margin:0 auto;padding:14px 22px 0;columns:4;column-gap:16px}
@media(max-width:1380px){.wall{columns:3}}
@media(max-width:1000px){.wall{columns:2}}
@media(max-width:620px){
  .wall{columns:1}
  .topbar-in,.controls,.wall,.grouphead{padding-left:14px;padding-right:14px}
  .kpi{display:none}
}
.card{
  break-inside:avoid; -webkit-column-break-inside:avoid; page-break-inside:avoid;
  background:var(--card);border-radius:var(--radius);overflow:hidden;
  box-shadow:var(--sh);margin:0 0 16px;cursor:pointer;
  transition:transform .18s cubic-bezier(.2,.8,.2,1),box-shadow .18s;
  display:inline-block;width:100%;vertical-align:top;
}
.card:hover{transform:translateY(-3px);box-shadow:var(--sh-hover)}

.cover{position:relative;height:108px;overflow:hidden}
.cover::after{
  content:"";position:absolute;inset:0;pointer-events:none;
  background-image:radial-gradient(rgba(255,255,255,.3) 1px,transparent 1px);
  background-size:14px 14px;opacity:.45;
}
.t-air .cover{background:linear-gradient(135deg,var(--air-a),var(--air-b))}
.t-rs  .cover{background:linear-gradient(135deg,var(--rs-a),var(--rs-b))}
.t-chem .cover{background:linear-gradient(135deg,var(--chem-a),var(--chem-b))}
.t-bgc .cover{background:linear-gradient(135deg,var(--bgc-a),var(--bgc-b))}
.t-gis .cover{background:linear-gradient(135deg,var(--gis-a),var(--gis-b))}
.t-other .cover{background:linear-gradient(135deg,var(--other-a),var(--other-b))}
.cover .icon{position:absolute;right:12px;top:50%;transform:translateY(-50%);color:#fff;opacity:.28;width:76px;height:76px;z-index:1}
.cover .icon svg{width:100%;height:100%;stroke-width:1.25}
.cover .jr{
  position:absolute;left:12px;bottom:11px;right:60px;color:#fff;font-size:13px;font-weight:800;
  letter-spacing:.3px;text-shadow:0 1px 6px rgba(0,0,0,.25);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;z-index:2;
}
.cover .tp{
  position:absolute;left:12px;top:10px;background:rgba(255,255,255,.95);color:#2a2a30;
  font-size:11px;font-weight:700;padding:3px 9px;border-radius:999px;z-index:2;
  box-shadow:0 1px 4px rgba(0,0,0,.1);
}
.cover .sc{
  position:absolute;right:12px;top:10px;background:rgba(0,0,0,.28);color:#fff;font-size:11px;
  font-weight:700;padding:3px 9px;border-radius:999px;z-index:2;backdrop-filter:blur(4px);
  font-variant-numeric:tabular-nums;
}
.tier{position:absolute;left:0;bottom:0;height:3px;width:100%;z-index:2}
.tier.must_read{background:#ff2442}
.tier.worth_reading{background:#ffab2e}
.tier.other{background:rgba(255,255,255,.6)}

.body{padding:12px 14px 11px}
.title{font-size:14.5px;font-weight:700;line-height:1.42;margin:0 0 7px;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.excerpt{font-size:12.5px;line-height:1.62;color:var(--ink2);margin:0;display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden}
.excerpt.none{color:var(--ink3);font-style:italic;font-size:12px;-webkit-line-clamp:2}
.tagrow{display:flex;gap:6px;flex-wrap:wrap;margin-top:9px}
.tag{font-size:11px;padding:2px 8px;border-radius:6px;background:#f4f5f7;color:var(--ink2);font-weight:600;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tag.must_read{background:#ffe9ed;color:#e01b39}
.tag.worth_reading{background:#fff4e3;color:#c67a00}
.tag.other{background:#f0f1f4;color:#7c8090}
.tag.match{background:#eef4ff;color:#3a5ce0}
.tag.cross{background:#e6f7f5;color:#0d8f9e}

.foot{display:flex;align-items:center;gap:8px;padding:9px 14px;border-top:1px solid var(--line);background:#fcfcfd}
.av{width:22px;height:22px;border-radius:50%;flex:none;color:#fff;display:grid;place-items:center;font-size:11px;font-weight:800}
.t-air .av{background:linear-gradient(135deg,var(--air-a),var(--air-b))}
.t-rs .av{background:linear-gradient(135deg,var(--rs-a),var(--rs-b))}
.t-chem .av{background:linear-gradient(135deg,var(--chem-a),var(--chem-b))}
.t-bgc .av{background:linear-gradient(135deg,var(--bgc-a),var(--bgc-b))}
.t-gis .av{background:linear-gradient(135deg,var(--gis-a),var(--gis-b))}
.t-other .av{background:linear-gradient(135deg,var(--other-a),var(--other-b))}
.au{font-size:12px;color:var(--ink2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;min-width:0}
.dt{font-size:11.5px;color:var(--ink3);white-space:nowrap;font-variant-numeric:tabular-nums}

.empty{max-width:1560px;margin:70px auto;text-align:center;color:var(--ink3);font-size:14px}
.empty svg{width:44px;height:44px;margin:0 auto 12px;stroke-width:1.5;opacity:.5;display:block}

.mask{position:fixed;inset:0;background:rgba(20,20,26,.5);z-index:100;display:none;align-items:center;justify-content:center;padding:24px;backdrop-filter:blur(3px);-webkit-backdrop-filter:blur(3px)}
.mask.on{display:flex;animation:fade .16s ease}
@keyframes fade{from{opacity:0}to{opacity:1}}
.modal{background:#fff;border-radius:20px;max-width:760px;width:100%;max-height:86vh;overflow:auto;box-shadow:0 24px 70px rgba(0,0,0,.3);animation:pop .2s cubic-bezier(.2,.9,.3,1.2)}
@keyframes pop{from{opacity:0;transform:translateY(14px) scale(.98)}to{opacity:1;transform:none}}
.mhead{position:relative;padding:18px 22px 16px;color:#fff;overflow:hidden}
.mhead::after{content:"";position:absolute;inset:0;pointer-events:none;background-image:radial-gradient(rgba(255,255,255,.26) 1px,transparent 1px);background-size:16px 16px;opacity:.4}
.mhead .mj{font-size:12.5px;font-weight:700;opacity:.95;position:relative;z-index:2;letter-spacing:.3px}
.mhead h3{font-size:18px;line-height:1.42;margin:8px 0 0;position:relative;z-index:2;font-weight:800;text-shadow:0 1px 8px rgba(0,0,0,.18);padding-right:26px}
.mmeta{display:flex;gap:8px;flex-wrap:wrap;position:relative;z-index:2;margin-top:11px}
.mmeta span{background:rgba(255,255,255,.95);color:#2a2a30;font-size:11.5px;font-weight:700;padding:3px 10px;border-radius:999px}
.mclose{position:absolute;right:14px;top:14px;z-index:3;border:0;cursor:pointer;width:30px;height:30px;border-radius:50%;background:rgba(0,0,0,.22);color:#fff;font-size:16px;line-height:1;display:grid;place-items:center;font-family:inherit}
.mclose:hover{background:rgba(0,0,0,.36)}
.mbody{padding:18px 22px 22px}
.sec-t{font-size:11.5px;font-weight:800;color:var(--ink3);letter-spacing:.8px;margin:0 0 8px}
.abs{font-size:14px;line-height:1.78;color:#33333a;margin:0 0 20px;white-space:pre-wrap}
.authors{font-size:13.5px;line-height:1.7;color:var(--ink2);margin:0 0 18px}
.kv{font-size:12.5px;color:var(--ink2);line-height:1.9;margin:0 0 18px}
.kv code{background:#f4f5f7;padding:2px 7px;border-radius:5px;font-size:12px;color:#3a3a44}
.linkrow{display:flex;gap:9px;flex-wrap:wrap}
.btn{display:inline-flex;align-items:center;gap:6px;font-size:13.5px;font-weight:700;padding:9px 17px;border-radius:999px;border:1px solid var(--line);background:#fff;color:var(--ink);cursor:pointer;font-family:inherit;transition:.16s}
.btn:hover{border-color:#d8d8e0;transform:translateY(-1px)}
.btn.pri{background:var(--red);border-color:var(--red);color:#fff;box-shadow:0 3px 12px rgba(255,36,66,.28)}
.btn.pri:hover{background:#f01a38}
</style>
</head>
<body>

<div class="topbar">
  <div class="topbar-in">
    <div class="brand">
      <div class="logo">J</div>
      <h1>__PROJECT__ · 文献卡片墙</h1>
      <span class="sub">journal-alert · 日报可视化</span>
      <div class="spacer"></div>
      <div class="kpi">
        <span>总文献 <b>__TOTAL__</b></span>
        <span>数据源 <b id="kpi-days">—</b> 天日报</span>
        <span>更新 <b>__GEN__</b></span>
      </div>
    </div>
  </div>
  <div class="controls">
    <div class="tabs" id="tabs"></div>
    <div class="row">
      <input class="search" id="q" type="search" placeholder="搜索标题 / 摘要 / 作者 / 期刊…">
      <div class="seg" id="seg">
        <button data-t="all" class="on" type="button">全部等级</button>
        <button data-t="must_read" type="button">必读</button>
        <button data-t="worth_reading" type="button">值得一读</button>
        <button data-t="other" type="button">其他相关</button>
      </div>
      <div class="seg" id="sortseg">
        <button data-s="score" class="on" type="button">按得分</button>
        <button data-s="date" type="button">按日期</button>
        <button data-s="journal" type="button">按期刊</button>
      </div>
      <div class="count" id="count"></div>
    </div>
  </div>
</div>

<div id="wall-wrap"></div>

<div class="mask" id="mask">
  <div class="modal" id="modal" onclick="event.stopPropagation()"></div>
</div>

<script type="application/json" id="DATA">/*__DATA__*/</script>
<script>
(function(){
  var D = JSON.parse(document.getElementById('DATA').textContent);
  var A = D.articles;
  var TOPICS = D.topics;

  /* Inline SVG rather than emoji: emoji depend on a colour-emoji font being
     installed, and the missing-glyph box is worse than no icon at all. */
  var P = {
    all:   '<rect x="3" y="3" width="7.5" height="7.5" rx="2"/><rect x="13.5" y="3" width="7.5" height="7.5" rx="2"/><rect x="3" y="13.5" width="7.5" height="7.5" rx="2"/><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="2"/>',
    air:   '<path d="M3 7.5h9.6a2.6 2.6 0 1 0-2.6-2.6"/><path d="M3 12h13.2a2.6 2.6 0 1 1-2.6 2.6"/><path d="M3 16.5h6.8"/>',
    rs:    '<circle cx="12" cy="12" r="8.6"/><ellipse cx="12" cy="12" rx="3.7" ry="8.6"/><path d="M3.4 12h17.2"/>',
    chem:  '<path d="M9.5 2.8h5"/><path d="M10.6 2.8v5.8L6.3 16.9a2 2 0 0 0 1.8 3h7.8a2 2 0 0 0 1.8-3L15.4 8.6V2.8"/><path d="M7.9 13.6h8.2"/>',
    bgc:   '<path d="M20.6 3.4C20.6 12 15.7 16.1 9.5 16.1H4.1C4.1 7.5 9 3.4 15.2 3.4h5.4z"/><path d="M4.1 20.6c2.2-5.8 6.1-9.1 11.3-10.5"/>',
    gis:   '<path d="M9 3.4 3.5 5.8v14.8L9 18.2l6 2.4 5.5-2.4V3.4L15 5.8 9 3.4z"/><path d="M9 3.4v14.8"/><path d="M15 5.8v14.8"/>',
    other: '<path d="M14 3H7.6A2 2 0 0 0 5.6 5v14a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2V7.6L14 3z"/><path d="M14 3v4.6h4.6"/>',
    search:'<circle cx="11" cy="11" r="7"/><path d="M20.2 20.2l-4.3-4.3"/>'
  };
  function svg(k, cls){
    return '<svg class="'+(cls||'ic')+'" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
         + 'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'+(P[k]||P.other)+'</svg>';
  }

  var state = { topic:'all', tier:'all', sort:'score', q:'' };

  /* An article can hit several keyword groups at once. a.topics holds every
     match (used for filtering); a.topic is the primary one (used for the cover
     chip and the section grouping, so nothing is listed twice). */
  var THEME = D.topicTheme || {};
  function topicsOf(a){ return a.topics && a.topics.length ? a.topics : [a.topic]; }

  var tabs = document.getElementById('tabs');
  var C = {all:A.length};
  TOPICS.forEach(function(t){ C[t]=0; });
  A.forEach(function(a){
    topicsOf(a).forEach(function(t){ if(C[t]!==undefined) C[t]++; });
  });

  var tabDefs = [{k:'all',label:'全部',icon:'all'}].concat(
    TOPICS.map(function(t){ return {k:t,label:t,icon:THEME[t]||'other'}; })
  );
  tabDefs.forEach(function(d){
    var b = document.createElement('button');
    b.className = 'tab' + (d.k==='all'?' on':'');
    b.type = 'button';
    var n = d.k==='all' ? C.all : (C[d.k]||0);
    b.innerHTML = svg(d.icon) + '<span>'+d.label+'</span><span class="n">'+n+'</span>';
    b.onclick = function(){
      state.topic = d.k;
      [].forEach.call(tabs.children, function(x){ x.classList.toggle('on', x===b); });
      render();
    };
    tabs.appendChild(b);
  });

  document.getElementById('seg').onclick = function(e){
    var b = e.target.closest('button'); if(!b) return;
    state.tier = b.dataset.t;
    [].forEach.call(this.children, function(x){ x.classList.toggle('on', x===b); });
    render();
  };
  document.getElementById('sortseg').onclick = function(e){
    var b = e.target.closest('button'); if(!b) return;
    state.sort = b.dataset.s;
    [].forEach.call(this.children, function(x){ x.classList.toggle('on', x===b); });
    render();
  };
  var qt;
  document.getElementById('q').oninput = function(e){
    clearTimeout(qt);
    var v = e.target.value.trim().toLowerCase();
    qt = setTimeout(function(){ state.q = v; render(); }, 130);
  };

  function esc(s){
    return String(s==null?'':s).replace(/[&<>"']/g, function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }
  function trunc(s,n){ s=s||''; return s.length>n ? s.slice(0,n)+'…' : s; }
  function initial(name){
    if(!name) return '?';
    var m = /[A-Za-z]/.exec(name);
    return m ? m[0].toUpperCase() : name.slice(0,1);
  }
  function isFuture(d){ return (d||'').indexOf('（在线预发表）') >= 0; }
  function dateOf(a){ return (a.pubdate||a.reportDate||'').replace('（在线预发表）','').slice(0,10); }
  document.getElementById('kpi-days').textContent = D.reports.length;

  function select(){
    var q = state.q;
    var out = A.filter(function(a){
      if(state.topic!=='all' && topicsOf(a).indexOf(state.topic)<0) return false;
      if(state.tier!=='all' && a.tier!==state.tier) return false;
      if(q){
        var hay = (a.title+' '+a.abstract+' '+a.authors.join(' ')+' '+a.journal+' '+a.doi).toLowerCase();
        if(hay.indexOf(q)<0) return false;
      }
      return true;
    });
    if(state.sort==='date'){
      out.sort(function(x,y){ return dateOf(y).localeCompare(dateOf(x)) || ((y.score||0)-(x.score||0)); });
    } else if(state.sort==='journal'){
      out.sort(function(x,y){ return x.journal.localeCompare(y.journal) || ((y.score||0)-(x.score||0)); });
    } else {
      out.sort(function(x,y){ return ((y.score||0)-(x.score||0)) || dateOf(y).localeCompare(dateOf(x)); });
    }
    return out;
  }

  function cardHTML(a){
    var tags = '<span class="tag '+a.tier+'">'+esc(a.tierLabel)+'</span>'
             + '<span class="tag">'+esc(a.jabbr)+'</span>';
    if(a.score!=null) tags += '<span class="tag">得分 '+a.score+'</span>';
    if(a.matchTerm) tags += '<span class="tag match" title="命中位置：'+esc(a.matchWhere)+'">命中 '+esc(a.matchTerm)+'</span>';
    topicsOf(a).filter(function(t){ return t!==a.topic; }).slice(0,2).forEach(function(t){
      tags += '<span class="tag cross">也属 '+esc(t)+'</span>';
    });

    var ab = a.abstract
      ? '<p class="excerpt">'+esc(trunc(a.abstract,200))+'</p>'
      : '<p class="excerpt none">日报未收录摘要'+(a.matchTerm?'（命中词 '+esc(a.matchTerm)+'）':'')+' · 点击看原文</p>';

    var au = esc(a.authors[0] || '佚名') + (a.authors.length>1 ? ' 等 '+(a.authors.length-1)+' 位' : '');

    return '<article class="card t-'+a.tkey+'" data-id="'+a.id+'" tabindex="0">'
      + '<div class="cover">'
      +   '<div class="tp">'+esc(a.topic)+'</div>'
      +   (a.score!=null ? '<div class="sc">★ '+a.score+'</div>' : '')
      +   '<div class="icon">'+svg(a.tkey)+'</div>'
      +   '<div class="jr">'+esc(a.jabbr)+'</div>'
      +   '<div class="tier '+a.tier+'"></div>'
      + '</div>'
      + '<div class="body">'
      +   '<h3 class="title">'+esc(a.title)+'</h3>'
      +   ab
      +   '<div class="tagrow">'+tags+'</div>'
      + '</div>'
      + '<div class="foot">'
      +   '<div class="av">'+esc(initial(a.authors[0]))+'</div>'
      +   '<div class="au">'+au+'</div>'
      +   '<div class="dt">'+esc(dateOf(a))+(isFuture(a.pubdate)?' · 预发表':'')+'</div>'
      + '</div>'
      + '</article>';
  }

  var wrap = document.getElementById('wall-wrap');
  var countEl = document.getElementById('count');
  var TIER_NAME = {must_read:'必读', worth_reading:'值得一读', other:'其他相关'};

  function render(){
    var list = select();
    var scope = (state.topic==='all' ? '全部学科' : state.topic)
              + (state.tier==='all' ? '' : ' · '+TIER_NAME[state.tier]);
    countEl.textContent = scope + ' ｜ ' + list.length + ' / ' + A.length + ' 篇';

    if(!list.length){
      wrap.innerHTML = '<div class="empty">'+svg('search')+'没有匹配的文献，换个关键词或学科试试</div>';
      return;
    }

    var html = '';
    if(state.topic==='all' && state.tier==='all' && !state.q && state.sort==='score'){
      TOPICS.forEach(function(t){
        var g = list.filter(function(a){ return a.topic===t; });
        if(!g.length) return;
        var key = THEME[t] || 'other';
        var related = list.filter(function(a){ return topicsOf(a).indexOf(t)>=0; }).length - g.length;
        html += '<div class="grouphead'+(key!=='other'?' g-'+key:'')+'"><h2>'+svg(key)+t+'</h2>'
              + '<span class="gn">'+g.length+' 篇'
              + (related>0 ? ' · 另有 '+related+' 篇跨学科命中' : '')+'</span><div class="bar"></div></div>'
              + '<div class="wall">'+g.map(cardHTML).join('')+'</div>';
      });
      var rest = list.filter(function(a){ return TOPICS.indexOf(a.topic)<0; });
      if(rest.length){
        html += '<div class="grouphead"><h2>'+svg('other')+'其他</h2>'
              + '<span class="gn">'+rest.length+' 篇</span><div class="bar"></div></div>'
              + '<div class="wall">'+rest.map(cardHTML).join('')+'</div>';
      }
    } else {
      html = '<div class="wall">'+list.map(cardHTML).join('')+'</div>';
    }
    wrap.innerHTML = html;
  }

  var mask = document.getElementById('mask'), modal = document.getElementById('modal');
  function openModal(id){
    var a = A[id]; if(!a) return;
    var authors = a.authors.length ? a.authors.join('、') + (a.authorMore?' 等':'') : '未收录作者信息';
    modal.innerHTML =
      '<div class="mhead" style="background:linear-gradient(135deg,var(--'+a.tkey+'-a),var(--'+a.tkey+'-b))">'
      + '<button class="mclose" id="mclose" type="button">✕</button>'
      + '<div class="mj">'+esc(topicsOf(a).join(' / '))+' · '+esc(a.journal)+'</div>'
      + '<h3>'+esc(a.title)+'</h3>'
      + '<div class="mmeta">'
      +   '<span>'+esc(a.tierLabel)+'</span>'
      +   (a.score!=null?'<span>得分 '+a.score+'</span>':'')
      +   (a.pubdate?'<span>'+esc(a.pubdate)+'</span>':'')
      +   '<span>日报 '+esc(a.reportDate)+'</span>'
      + '</div></div>'
      + '<div class="mbody">'
      +   '<div class="sec-t">摘要</div>'
      +   (a.abstract
            ? '<p class="abs">'+esc(a.abstract)+'</p>'
            : '<p class="abs" style="color:#9d9da8">该条日报未收录摘要。</p>')
      +   '<div class="sec-t">作者</div><p class="authors">'+esc(authors)+'</p>'
      +   (a.doi ? '<div class="kv">DOI：<code>'+esc(a.doi)+'</code></div>' : '')
      +   (a.matchWhere ? '<div class="kv">关键词命中：'+esc(a.matchWhere)+'</div>' : '')
      +   '<div class="linkrow">'
      +     '<a class="btn pri" href="'+esc(a.url)+'" target="_blank" rel="noopener">打开原文 ↗</a>'
      +     (a.doi?'<a class="btn" href="https://doi.org/'+esc(a.doi)+'" target="_blank" rel="noopener">DOI 链接</a>':'')
      +     '<button class="btn" id="mcopy" type="button">复制 DOI</button>'
      +   '</div>'
      + '</div>';
    mask.classList.add('on');
    document.body.style.overflow = 'hidden';
    var cb = document.getElementById('mclose'); if(cb) cb.onclick = closeModal;
    var cp = document.getElementById('mcopy');
    if(cp) cp.onclick = function(){
      var txt = a.doi || a.url;
      var done = function(){ cp.textContent='已复制 ✓'; setTimeout(function(){ cp.textContent='复制 DOI'; },1400); };
      if(navigator.clipboard && navigator.clipboard.writeText){
        navigator.clipboard.writeText(txt).then(done, function(){ cp.textContent = txt; });
      } else { cp.textContent = txt; }
    };
  }
  function closeModal(){ mask.classList.remove('on'); document.body.style.overflow=''; }
  mask.onclick = closeModal;
  document.addEventListener('keydown', function(e){ if(e.key==='Escape') closeModal(); });

  wrap.addEventListener('click', function(e){
    var c = e.target.closest('.card'); if(c) openModal(+c.dataset.id);
  });
  wrap.addEventListener('keydown', function(e){
    if(e.key==='Enter'){ var c = e.target.closest('.card'); if(c) openModal(+c.dataset.id); }
  });

  render();
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
