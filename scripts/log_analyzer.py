#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
log_analyzer.py —— 测试环境日志分析工具

用途：
    从大量日志中快速统计错误分布、提取异常堆栈上下文、按时间聚合，
    用于测试执行后的问题定界（先定位时段与级别，再去翻具体内容）。

用法示例：
    python log_analyzer.py app.log --stats
    python log_analyzer.py app.log --level ERROR --context 5
    python log_analyzer.py app.log --hourly
    python log_analyzer.py app.log --grep "timeout" --context 2

兼容两种常见日志格式：
    1) 2026-11-18 10:23:45,123 ERROR [main] c.x.UserService - 用户登录失败
    2) 2026-11-18 10:23:45 ERROR ...
    3) 纯 ISO 风格 2026-11-18T10:23:45.123+0800 ERROR ...
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

# 日志级别，按严重程度排序
LEVELS = ("DEBUG", "INFO", "WARNING", "WARN", "ERROR", "CRITICAL", "FATAL")
LEVEL_SET = set(LEVELS)

# 匹配行首时间戳与级别。支持：
#   2026-11-18 10:23:45,123 ERROR ...
#   2026-11-18T10:23:45.123+0800 ERROR ...
#   2026-11-18 10:23:45 ERROR ...
FULL_PATTERN = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})[T\s]"
    r"(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})"
    r"(?:[.,](?P<ms>\d+))?"
    r"(?:[+\-Z][\d:]*)?"
    r"\s*(?P<level>DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL|FATAL)?",
    re.IGNORECASE,
)


@dataclass
class LogLine:
    """解析后的单行日志。解析失败时 date/hour/level 为 None，原文仍保留。"""

    lineno: int
    raw: str
    date: str | None = None
    hour: str | None = None
    level: str | None = None
    parsed: bool = False


def normalize_level(level: str | None) -> str:
    """统一级别命名：WARN -> WARNING，其余转大写。无法识别返回 UNKNOWN。"""
    if not level:
        return "UNKNOWN"
    upper = level.upper()
    if upper == "WARN":
        return "WARNING"
    return upper if upper in LEVEL_SET else "UNKNOWN"


def parse_line(lineno: int, raw: str) -> LogLine:
    """解析一行日志。容错设计：格式不匹配时不抛异常，标记为未解析。"""
    stripped = raw.rstrip("\n").rstrip("\r")
    match = FULL_PATTERN.match(stripped)
    if not match:
        return LogLine(lineno=lineno, raw=stripped)

    return LogLine(
        lineno=lineno,
        raw=stripped,
        date=match.group("date"),
        hour=match.group("hour"),
        level=normalize_level(match.group("level")),
        parsed=True,
    )


def iter_lines(path: Path, encoding: str) -> Iterator[LogLine]:
    """逐行读取并解析。用生成器避免大日志一次性载入内存。

    encoding 传 utf-8 时自动升级为 utf-8-sig，以便剥离 Windows 工具
    写日志时常见的 BOM——否则首行会因 \ufeff 前缀而解析失败。
    """
    effective = "utf-8-sig" if encoding.lower().replace("-", "") in (
        "utf8", "utf8sig"
    ) else encoding
    with path.open("r", encoding=effective, errors="replace") as fh:
        for lineno, raw in enumerate(fh, start=1):
            yield parse_line(lineno, raw)


def collect(path: Path, encoding: str) -> list[LogLine]:
    """需要多次遍历或输出上下文时，先收集成列表。"""
    return list(iter_lines(path, encoding))


def report_stats(lines: list[LogLine]) -> str:
    """日志级别分布统计。"""
    counter = Counter(line.level or "UNPARSED" for line in lines)
    total = len(lines)
    out = [f"总行数：{total}", "", "级别分布："]

    order = list(LEVELS) + ["UNKNOWN", "UNPARSED"]
    for level in order:
        count = counter.get(level)
        if not count:
            continue
        pct = count / total * 100 if total else 0
        bar = "█" * int(pct / 2)
        out.append(f"  {level:<10} {count:>8}  {pct:>6.2f}%  {bar}")

    parsed = sum(1 for line in lines if line.parsed)
    out.append("")
    out.append(f"可解析行：{parsed} / {total}"
               f"（{(parsed / total * 100) if total else 0:.1f}%）")
    return "\n".join(out)


def report_hourly(lines: list[LogLine], level: str | None) -> str:
    """按日期+小时聚合，定位问题集中时段。"""
    buckets: dict[str, Counter] = defaultdict(Counter)
    target = normalize_level(level) if level else None
    for line in lines:
        if not line.parsed or not line.date or not line.hour:
            continue
        if target and normalize_level(line.level) != target:
            continue
        buckets[line.date][line.hour] += 1

    if not buckets:
        return "未找到带时间戳的日志行，无法按小时聚合。"

    label = target or "全部级别"
    out = [f"按小时聚合（{label}）：", ""]
    for date in sorted(buckets):
        out.append(f"  {date}")
        hours = buckets[date]
        peak = max(hours.values())
        for hour in sorted(hours):
            count = hours[hour]
            bar = "█" * max(1, int(count / peak * 40)) if peak else ""
            out.append(f"    {hour}:00  {count:>6}  {bar}")
        out.append("")
    return "\n".join(out)


def report_matches(
    lines: list[LogLine],
    level: str | None,
    keyword: str | None,
    context: int,
    ignore_case: bool,
    limit: int,
) -> str:
    """按级别/关键字检索，并附带后续 context 行堆栈上下文。"""
    flags = re.IGNORECASE if ignore_case else 0
    pattern = re.compile(re.escape(keyword), flags) if keyword else None
    target_level = normalize_level(level) if level else None

    hits: list[int] = []
    for idx, line in enumerate(lines):
        if target_level and normalize_level(line.level) != target_level:
            continue
        if pattern and not pattern.search(line.raw):
            continue
        hits.append(idx)
        if len(hits) >= limit:
            break

    if not hits:
        cond = []
        if target_level:
            cond.append(f"级别={target_level}")
        if keyword:
            cond.append(f"关键字={keyword!r}")
        return f"未匹配到日志（条件：{'，'.join(cond) or '无'}）。"

    out = [f"命中 {len(hits)} 条"
           f"{'（已达 --limit 上限）' if len(hits) >= limit else ''}：", ""]
    for idx in hits:
        start = idx
        end = min(idx + context + 1, len(lines))
        for pos in range(start, end):
            prefix = ">>" if pos == start else "  "
            out.append(f"{prefix} L{lines[pos].lineno:<6} {lines[pos].raw}")
        if context:
            out.append("  " + "-" * 60)
        out.append("")
    return "\n".join(out)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="log_analyzer.py",
        description="测试环境日志分析工具：级别统计 / 堆栈上下文提取 / 时间聚合",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python log_analyzer.py app.log --stats\n"
            "  python log_analyzer.py app.log --level ERROR --context 5\n"
            "  python log_analyzer.py app.log --hourly\n"
            "  python log_analyzer.py app.log --grep timeout --context 2\n"
        ),
    )
    parser.add_argument("logfile", help="日志文件路径")
    parser.add_argument("--stats", action="store_true", help="输出日志级别分布统计")
    parser.add_argument("--hourly", action="store_true", help="按日期+小时聚合数量")
    parser.add_argument("--level", choices=[lv for lv in LEVELS],
                        help="只看指定级别（WARN 等价于 WARNING）")
    parser.add_argument("--grep", dest="keyword", help="关键字检索（正则元字符按字面处理）")
    parser.add_argument("--context", type=int, default=0, metavar="N",
                        help="输出命中行之后 N 行，用于查看堆栈")
    parser.add_argument("-i", "--ignore-case", action="store_true", help="关键字检索忽略大小写")
    parser.add_argument("--limit", type=int, default=50, metavar="N",
                        help="最多输出 N 条命中（默认 50）")
    parser.add_argument("--encoding", default="utf-8", help="日志编码（默认 utf-8）")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    path = Path(args.logfile)
    if not path.exists():
        print(f"[错误] 文件不存在：{path}", file=sys.stderr)
        return 2
    if not path.is_file():
        print(f"[错误] 不是文件：{path}", file=sys.stderr)
        return 2

    if args.context < 0:
        print("[错误] --context 不能为负数", file=sys.stderr)
        return 2

    lines = collect(path, args.encoding)
    if not lines:
        print(f"[提示] 文件为空：{path}")
        return 0

    # 未指定任何输出模式时，默认给出统计
    if not (args.stats or args.hourly or args.level or args.keyword):
        args.stats = True

    blocks = []
    if args.stats:
        blocks.append(report_stats(lines))
    if args.hourly:
        blocks.append(report_hourly(lines, args.level))
    if args.level or args.keyword:
        blocks.append(report_matches(
            lines=lines,
            level=args.level,
            keyword=args.keyword,
            context=args.context,
            ignore_case=args.ignore_case,
            limit=args.limit,
        ))

    print("\n".join(blocks))
    return 0


if __name__ == "__main__":
    sys.exit(main())
