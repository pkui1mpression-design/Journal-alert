#!/usr/bin/env python
"""journal-alert entry point.

Typical use::

    python run.py --once               # fetch, filter, write report, push
    python run.py --check              # only test every data source
    python run.py --dry-run --print    # no writes, print the report to stdout
    python run.py --rerender           # rebuild today's report from the snapshot
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jalert import push as push_module  # noqa: E402
from jalert.cards import write_cards  # noqa: E402
from jalert.config import describe_secret_sources, load_config  # noqa: E402
from jalert.fetch import collect_items, http_request  # noqa: E402
from jalert.report import build_digest, build_markdown  # noqa: E402
from jalert.score import Scorer, tier_of  # noqa: E402
from jalert.state import Store, last_run_started  # noqa: E402

TIER_RANK = {"must_read": 0, "worth_reading": 1, "other": 2}


def setup_logging(log_dir: str, level: str) -> logging.Logger:
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("jalert")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S"))
    logger.addHandler(stream)
    file_handler = logging.FileHandler(
        Path(log_dir) / f"jalert-{date.today():%Y-%m}.log", encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s"))
    logger.addHandler(file_handler)
    return logger


def entry_to_dict(entry: dict) -> dict:
    item = entry["item"]
    scored = entry["scored"]
    return {
        "item": item.as_dict(),
        "scored": {
            "score": scored.score,
            "labels": scored.labels,
            "matches": [
                {"label": m.label, "term": m.term, "field_name": m.field_name, "points": m.points}
                for m in scored.matches
            ],
        },
    }


def hydrate_entries(records: list[dict]) -> list[dict]:
    """Rebuild renderable entries from a JSON snapshot."""
    entries = []
    for record in records:
        item = SimpleNamespace(**record["item"])
        scored_data = record["scored"]
        scored = SimpleNamespace(
            score=scored_data["score"],
            labels=scored_data.get("labels", []),
            matches=[SimpleNamespace(**m) for m in scored_data.get("matches", [])],
            excluded=False,
        )
        entries.append({"item": item, "scored": scored})
    return entries


def sort_entries(entries: list[dict], tiers: dict, today: str = "") -> list[dict]:
    """Tier first, then score, then newest first. Future-dated issues are clamped."""
    reference = today or date.today().isoformat()

    def key(entry):
        item = entry["item"]
        stamp = item.date or ""
        if stamp > reference:  # Elsevier stamps ahead-of-print articles with a future issue date
            stamp = reference
        try:
            ordinal = -date.fromisoformat(stamp).toordinal()
        except ValueError:
            ordinal = 0
        return (
            TIER_RANK.get(tier_of(entry["scored"].score, tiers), 3),
            -entry["scored"].score,
            ordinal,
            item.journal,
        )

    return sorted(entries, key=key)


def load_snapshot(path: Path) -> dict:
    """Load a day snapshot, or an empty dict when absent or corrupt."""
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def prune_reports(reports_dir: Path, keep_days: int, log) -> None:
    if keep_days <= 0:
        return
    cutoff = date.today().toordinal() - keep_days
    removed = 0
    for pattern in ("*.md", "*.json"):
        for path in reports_dir.glob(pattern):
            try:
                stamp = date.fromisoformat(path.stem).toordinal()
            except ValueError:
                continue
            if stamp < cutoff:
                path.unlink(missing_ok=True)
                removed += 1
    if removed:
        log.info("pruned %d report(s)/snapshot(s) older than %d days", removed, keep_days)


def cards_output_path(cfg: dict) -> Path:
    """Where the card-wall page goes; relative paths resolve against the project root."""
    raw = str(cfg.get("output", {}).get("cards_html", "docs/index.html") or "docs/index.html")
    path = Path(raw)
    return path if path.is_absolute() else Path(cfg["_root"]) / path


def build_cards_page(cfg: dict, log) -> int:
    """Rebuild the static card-wall page from every report on disk.

    Kept separate from the fetch pipeline on purpose: it only reads ``reports/``,
    so it can be run on its own (``--cards``) to refresh the page without
    touching the network, the ledger or the push channels.
    """
    written = write_cards(
        Path(cfg["reports_dir"]),
        cards_output_path(cfg),
        project=cfg.get("project", {}).get("name", "文献日报"),
        log=log,
    )
    if written is None:
        log.warning("cards page not written: no reports found in %s", cfg["reports_dir"])
        return 1
    return 0


def cap_entries(entries: list[dict], cfg: dict, log) -> tuple[list[dict], int]:
    """Trim the rendered report to the top-N entries (``output.max_entries``).

    ``entries`` must already be sorted by ``sort_entries`` (tier, then score,
    then date), so slicing keeps the most important ones. The full set is still
    written to the SQLite ledger and the JSON snapshot, so raising the cap and
    running ``--rerender`` brings the rest back without re-fetching.
    A cap of ``0`` (the default) means "no limit".
    """
    cap = int(cfg.get("output", {}).get("max_entries", 0) or 0)
    total = len(entries)
    if cap > 0 and total > cap:
        log.info("report capped to top %d of %d entries (output.max_entries)", cap, total)
        return entries[:cap], total
    return entries, total


def rerender(args, cfg, log, day, tiers, day_snapshot, report_path) -> int:
    """Rebuild a report from the saved day snapshot without any network access."""
    snapshot = load_snapshot(day_snapshot)
    entries = snapshot.get("entries") or []
    if not entries:
        log.error("no snapshot for %s - run a normal pass first", day)
        return 1
    day_entries = sort_entries(hydrate_entries(entries), tiers, day)
    listed_entries, entries_total = cap_entries(day_entries, cfg, log)
    markdown = build_markdown(
        day=day,
        cfg=cfg,
        entries=listed_entries,
        statuses=snapshot.get("statuses", []),
        fetched_total=int(snapshot.get("fetched", 0)),
        matched_total=int(snapshot.get("matched", 0)),
        new_count=int(snapshot.get("new_total", len(day_entries))),
        seen_before=0,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        entries_total=entries_total,
        all_entries=day_entries,
    )
    report_path.write_text(markdown, encoding="utf-8", newline="\n")
    log.info("report re-rendered from snapshot: %s (%d entries)", report_path, len(day_entries))
    if args.print_report:
        print("\n" + markdown)
    return 0


def print_status_table(statuses: list[dict]) -> None:
    print(f"\n{'期刊':<44} {'源':<9} {'状态':<5} {'条数':>5}  说明")
    for status in statuses:
        print(
            f"{status['journal']:<44} {status['source']:<9} "
            f"{'OK' if status['ok'] else 'FAIL':<5} {status['items']:>5}  {status.get('note', '')}"
        )


def effective_window_days(cfg: dict, log, explicit: int | None = None) -> int:
    """Widen the lookback window to cover the gap since the last run.

    A laptop is not always on. With a fixed window, every day the machine stayed
    off would silently drop that day's papers. So the window becomes
    ``max(configured, days_since_last_run + 1)``, capped by ``max_catchup_days``.

    An explicit ``--days`` on the command line always wins and disables catch-up.
    """
    configured = int(cfg.get("window", {}).get("days", 3))
    if explicit:
        log.info("lookback window: %d day(s) (from --days, catch-up disabled)", explicit)
        return int(explicit)

    cap = int(cfg.get("window", {}).get("max_catchup_days", 30))
    last = last_run_started(cfg["state_db"])
    if not last:
        log.info("lookback window: %d day(s) (no previous run recorded)", configured)
        return configured
    try:
        gap = (datetime.now() - datetime.fromisoformat(last)).days
    except ValueError:
        log.warning("unreadable last-run timestamp %r; using configured window", last)
        return configured

    window = min(max(configured, gap + 1), cap)
    if window > configured:
        log.info(
            "lookback window widened to %d day(s): last run was %s (%d day(s) ago)%s",
            window, last, gap, "  [capped]" if gap + 1 > cap else "",
        )
    else:
        log.info("lookback window: %d day(s) (last run %s)", window, last)
    return window


def doctor(cfg: dict, log) -> int:
    """Verify that *this* machine can run the pipeline.

    Checks the interpreter, required standard-library modules, write access to
    the three data directories, config sanity and three quick network probes.
    Meant to be the first command you run after copying the project to a new PC.
    """
    import time

    problems: list[str] = []
    print("=" * 70)
    print("journal-alert 环境自检 (--doctor)")
    print("=" * 70)
    print(f"Python 解释器  : {sys.version.split()[0]}   {sys.executable}")
    if sys.version_info < (3, 10):
        problems.append(f"Python 版本过低（{sys.version.split()[0]}），需要 3.10 或更高")
    print(f"项目目录       : {cfg['_root']}")
    print(f"配置文件       : {cfg['_config_path']}")
    print(f"本机覆盖层     : {cfg.get('_local_overlay') or '（无，密钥需另填）'}")
    print("命令行         : " + " ".join(sys.argv[:3]) + " ...")

    missing = []
    for module in ("sqlite3", "urllib.request", "xml.etree.ElementTree", "gzip", "zlib", "json"):
        try:
            __import__(module)
        except ImportError:
            missing.append(module)
    print(f"标准库依赖     : {'全部可用' if not missing else '缺失 ' + ', '.join(missing)}")
    if missing:
        problems.append("缺少标准库模块: " + ", ".join(missing))

    for label, path in (
        ("报告目录", cfg["reports_dir"]),
        ("日志目录", cfg["log_dir"]),
        ("历史库目录", str(Path(cfg["state_db"]).parent)),
    ):
        target = Path(path)
        try:
            target.mkdir(parents=True, exist_ok=True)
            probe = target / ".write-test"
            probe.write_text("ok", encoding="utf-8", newline="\n")
            probe.unlink()
            print(f"写入权限       : {label} 可写  {target}")
        except OSError as exc:
            print(f"写入权限       : {label} 不可写  {target}  -> {exc}")
            problems.append(f"{label} 不可写: {target}")

    journals = [j for j in cfg.get("journals", []) if j.get("enabled", True)]
    keywords = cfg.get("keywords", [])
    print(f"期刊 / 关键词  : {len(journals)} 本启用 / {len(keywords)} 组关键词")
    if not journals:
        problems.append("config.json 里没有启用的期刊")
    if not keywords:
        problems.append("config.json 里没有关键词")
    tiers = cfg.get("tiers", {})
    print(
        f"分级阈值       : 必读 >= {tiers.get('must_read')} ｜ 值得一读 >= {tiers.get('worth_reading')} "
        f"｜ 最低收录 >= {tiers.get('min_score')}"
    )
    print(f"时间窗 / 并发  : 近 {cfg.get('window', {}).get('days')} 天 ｜ {cfg.get('window', {}).get('workers')} 路并发")

    channels = describe_secret_sources(cfg)
    print(f"推送渠道       : {'、'.join(channels) if channels else '未配置密钥（只写本地报告，属正常）'}")

    print("-" * 70)
    print("网络连通性（海外站点，超时 25 秒，允许 1 次重试）")
    probe_failures: list[str] = []
    for label, url in (
        ("期刊 RSS", "https://www.nature.com/nature.rss"),
        ("OpenAlex", "https://api.openalex.org/works?per-page=1"),
        ("Crossref", "https://api.crossref.org/journals/0028-0836/works?rows=1"),
    ):
        started = time.time()
        try:
            status, raw = http_request(url, timeout=25, retries=1)
            print(f"  {label:<9} OK    HTTP {status}  {len(raw):>8d} B  {time.time() - started:.1f}s")
        except Exception as exc:  # noqa: BLE001 - diagnostic, keep going
            print(f"  {label:<9} FAIL  {str(exc)[:80]}")
            probe_failures.append(label)

    if len(probe_failures) == 3:
        problems.append("三个海外站点全部不可达（Python 的联网被阻断了）")
    elif probe_failures:
        print()
        print(f"说明：{len(probe_failures)}/3 个站点本次超时（{'、'.join(probe_failures)}）。")
        print("      海外 API 偶发超时很常见（实测约 15% 的调用），不视为故障：")
        print("      抓取管线有重试，且每本刊都有 2–3 个独立数据源互为兜底，")
        print("      单站超时不会导致漏文献。重复运行 --doctor 通常会看到它恢复正常。")

    print("=" * 70)
    if problems:
        print("发现问题：")
        for item in problems:
            print("  ✗ " + item)
        print(
            "\n提示：浏览器能打开网页不代表 Python 能联网——代理、防火墙或安全软件\n"
            "      可能只放行部分程序。本项目所有网络访问都由 Python 完成。"
        )
        return 1
    print("一切正常，这台机器可以直接运行 journal-alert。")
    print("建议接着执行：run.py --check    （逐本刊验证全部数据源）")
    return 0


def run(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    if args.days:
        cfg["window"]["days"] = args.days
    if args.sources:
        chosen = {s.strip().lower() for s in args.sources.split(",") if s.strip()}
        cfg["window"]["sources"] = {name: name in chosen for name in ("rss", "openalex", "crossref")}

    log = setup_logging(cfg["log_dir"], cfg.get("log", {}).get("level", "INFO"))
    started = datetime.now().isoformat(timespec="seconds")
    day = args.date or date.today().isoformat()
    tiers = cfg.get("tiers", {})
    reports_dir = Path(cfg["reports_dir"])
    reports_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir = Path(cfg["_root"]) / "state" / "daily"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    day_snapshot = snapshot_dir / f"{day}.json"
    report_path = reports_dir / f"{day}.md"
    log.info("=== %s run for %s ===", cfg.get("project", {}).get("name", "journal-alert"), day)

    if args.test_push:
        project = cfg.get("project", {}).get("name", "文献日报")
        title = f"{project} · 推送通道自检"
        body = (
            "如果你在微信里看到这条消息，说明推送密钥配置成功。\n\n"
            "正式日报会在每个工作日 07:30 自动送达，内容是当天命中的文献摘要卡片。"
        )
        results = push_module.dispatch(cfg, title, body, log)
        if not results:
            print("\n没有任何「已启用且填了密钥」的渠道。请编辑 config.json：")
            print('  push.enabled = true，并在 channels 里填入 serverchan.sendkey / pushplus.token / bark.key')
            return 1
        for result in results:
            print(f"  {result['channel']:<12} {'成功' if result['ok'] else '失败'}  {result['detail']}")
        return 0 if any(r["ok"] for r in results) else 1

    if args.doctor:
        return doctor(cfg, log)

    if args.rerender:
        return rerender(args, cfg, log, day, tiers, day_snapshot, report_path)

    if args.cards:
        return build_cards_page(cfg, log)

    window_days = effective_window_days(cfg, log, explicit=args.days)
    cfg["window"]["days"] = window_days
    items, statuses = collect_items(cfg, log, since_days=window_days)
    failures = [s for s in statuses if not s["ok"]]
    log.info("fetched %d unique items (%d source calls failed)", len(items), len(failures))

    if args.check:
        print_status_table(statuses)
        return 0

    scorer = Scorer(
        cfg.get("keywords", []),
        cfg.get("exclude_terms", []),
        cfg.get("exclude_doi_prefixes", []),
    )
    min_score = int(tiers.get("min_score", 3))

    matched: list[dict] = []
    for item in items:
        scored = scorer.score(item)
        if scored.excluded or scored.score < min_score:
            continue
        matched.append({"item": item, "scored": scored})
    log.info("keyword matched %d/%d items (min_score=%d)", len(matched), len(items), min_score)

    with Store(cfg["state_db"]) as store:
        known = store.known_uids([entry["item"].uid for entry in matched])
        new_entries = [entry for entry in matched if entry["item"].uid not in known]
        for entry in new_entries:
            entry["scored"].tier = tier_of(entry["scored"].score, tiers)
        if not args.dry_run:
            store.save([(e["item"], e["scored"]) for e in new_entries])
        log.info("new items: %d (已存在 %d)", len(new_entries), len(matched) - len(new_entries))

        previous = {} if args.dry_run else load_snapshot(day_snapshot)
        merged_records = list(previous.get("entries", []))
        added_now = 0
        if args.dry_run:
            merged_records = [entry_to_dict(e) for e in new_entries]
        else:
            seen_uid = {r["item"]["uid"] for r in merged_records}
            for entry in new_entries:
                # ``entry["item"]`` is an Item object here, not the dict form kept
                # in the snapshot - so read the attribute, not a key.
                uid = entry["item"].uid
                if uid not in seen_uid:
                    merged_records.append(entry_to_dict(entry))
                    seen_uid.add(uid)
                    added_now += 1
            snapshot_payload = {
                "date": day,
                "updated": datetime.now().isoformat(timespec="seconds"),
                "fetched": len(items),
                "matched": len(matched),
                "new_total": int(previous.get("new_total", 0)) + added_now,
                "entries": merged_records,
                "statuses": statuses,
            }
            day_snapshot.write_text(
                json.dumps(snapshot_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
                newline="\n",
            )

        day_entries = sort_entries(hydrate_entries(merged_records), tiers, day)
        listed_entries, entries_total = cap_entries(day_entries, cfg, log)
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        markdown = build_markdown(
            day=day,
            cfg=cfg,
            entries=listed_entries,
            statuses=statuses,
            fetched_total=len(items),
            matched_total=len(matched),
            new_count=len(new_entries),
            seen_before=len(known),
            generated_at=generated_at,
            entries_total=entries_total,
            all_entries=day_entries,
        )

        if args.dry_run or args.print_report:
            print("\n" + markdown)
        if not args.dry_run:
            report_path.write_text(markdown, encoding="utf-8", newline="\n")
            log.info("report written: %s", report_path)
            if cfg.get("output", {}).get("write_json_snapshot", True):
                snapshot_payload["generated"] = generated_at
                (reports_dir / f"{day}.json").write_text(
                    json.dumps(snapshot_payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                    newline="\n",
                )

        pushed = 0
        if not args.dry_run and not args.no_push and cfg.get("push", {}).get("enabled", False):
            push_cfg = cfg["push"]
            if new_entries or not push_cfg.get("skip_when_empty", True):
                title, body = build_digest(
                    day=day,
                    cfg=cfg,
                    entries=sort_entries(new_entries, tiers, day),
                    fetched_total=len(items),
                    matched_total=len(matched),
                    max_items=int(push_cfg.get("max_items", 6)),
                    max_chars=int(push_cfg.get("max_chars", 1800)),
                )
                results = push_module.dispatch(cfg, title, body, log)
                pushed = sum(1 for r in results if r["ok"])
                log.info("push results: %s", json.dumps(results, ensure_ascii=False))
            else:
                log.info("no new items; push skipped (skip_when_empty=true)")

        if not args.dry_run:
            store.record_run(
                started=started,
                fetched=len(items),
                matched=len(matched),
                new_items=len(new_entries),
                pushed=pushed,
                report_path=str(report_path),
                note=f"{len(failures)} source failure(s)",
            )
            prune_reports(reports_dir, int(cfg.get("output", {}).get("keep_days", 365)), log)
            # Rebuilt after pruning so the page matches what the archive holds.
            # Wrapped because the report is the deliverable and the page is a
            # convenience: an HTML bug must never fail the daily run.
            if cfg.get("output", {}).get("cards", True):
                try:
                    build_cards_page(cfg, log)
                except Exception as exc:  # noqa: BLE001 - deliberately broad
                    log.warning("cards page build failed (report unaffected): %s", exc)

    if not args.dry_run and cfg.get("output", {}).get("open_after_run") and report_path.is_file():
        if hasattr(os, "startfile"):  # Windows only; a no-op on Linux/macOS/CI
            os.startfile(str(report_path))  # noqa: S606 - opt-in via config
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Journal RSS/API keyword alert and daily report")
    parser.add_argument("--config", help="path to config.json")
    parser.add_argument("--once", action="store_true", help="single run (default)")
    parser.add_argument("--check", action="store_true", help="only probe data sources, then exit")
    parser.add_argument(
        "--rerender",
        action="store_true",
        help="rebuild today's report from the saved snapshot without fetching",
    )
    parser.add_argument(
        "--cards",
        action="store_true",
        help="rebuild the static card-wall page from reports/ and exit",
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="check interpreter, permissions, config and network reachability, then exit",
    )
    parser.add_argument("--dry-run", action="store_true", help="do not write state, reports or push")
    parser.add_argument("--print", dest="print_report", action="store_true", help="print the report to stdout")
    parser.add_argument("--no-push", action="store_true", help="skip push notifications")
    parser.add_argument(
        "--test-push",
        action="store_true",
        help="send one test message through the configured channels, then exit",
    )
    parser.add_argument("--days", type=int, help="override the lookback window in days")
    parser.add_argument("--sources", help="comma list: rss,openalex,crossref")
    parser.add_argument("--date", help="report date label (YYYY-MM-DD), defaults to today")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
