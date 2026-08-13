#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股每日收盘复盘 · GitHub Pages 发布脚本

用法：
  python3 publish.py --report /path/to/收盘总结_2026-08-11.html \
                     --date 2026-08-11 \
                     --title "CPO 反弹修复，FCC 禁令暂缓" \
                     --trend up|down|mixed

功能：
  1. 把报告复制到 archive/<date>.html 并更新 latest.html
  2. 自动重建 index.html 里的历史列表（按日期倒序）
  3. commit 并 push 到 gh-pages 分支
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime

SITE_DIR = os.path.dirname(os.path.abspath(__file__))
ARCHIVE_DIR = os.path.join(SITE_DIR, "archive")
INDEX_PATH = os.path.join(SITE_DIR, "index.html")
LATEST_PATH = os.path.join(SITE_DIR, "latest.html")

# 沙箱/自动化环境通常没有全局 git config，提交时必须显式指定身份
GIT_USER_EMAIL = os.environ.get("GIT_AUTHOR_EMAIL", "roycefu@tencent.com")
GIT_USER_NAME = os.environ.get("GIT_AUTHOR_NAME", "roycejfu")
GIT_ID = f'git -c user.email="{GIT_USER_EMAIL}" -c user.name="{GIT_USER_NAME}"'

WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

BADGE_MAP = {
    "up":     ("badge-up",    "主线走强"),
    "down":   ("badge-down",  "主线杀跌"),
    "mixed":  ("badge-mixed", "分化震荡"),
}


def run(cmd, cwd=SITE_DIR, check=True):
    """执行 shell 命令并返回 stdout"""
    result = subprocess.run(
        cmd, cwd=cwd, shell=True,
        capture_output=True, text=True
    )
    if check and result.returncode != 0:
        print(f"[ERROR] 命令失败: {cmd}", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def scan_archive():
    """扫描 archive 目录，返回 [(date_str, weekday_cn), ...] 按日期倒序"""
    if not os.path.isdir(ARCHIVE_DIR):
        return []
    entries = []
    for fn in os.listdir(ARCHIVE_DIR):
        m = re.match(r"^(\d{4}-\d{2}-\d{2})\.html$", fn)
        if m:
            date_str = m.group(1)
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            entries.append((date_str, WEEKDAY_CN[dt.weekday()]))
    entries.sort(key=lambda x: x[0], reverse=True)
    return entries


def load_meta():
    """读取 meta.txt（记录每份报告的标题和趋势），返回 dict"""
    meta_path = os.path.join(SITE_DIR, "meta.txt")
    meta = {}
    if os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("|", 2)
                if len(parts) == 3:
                    meta[parts[0]] = {"trend": parts[1], "title": parts[2]}
    return meta


def save_meta(meta):
    """写回 meta.txt"""
    meta_path = os.path.join(SITE_DIR, "meta.txt")
    with open(meta_path, "w", encoding="utf-8") as f:
        f.write("# date|trend|title\n")
        for date_str in sorted(meta.keys(), reverse=True):
            item = meta[date_str]
            f.write(f"{date_str}|{item['trend']}|{item['title']}\n")


def build_list_html(entries, meta):
    """生成历史列表的 HTML"""
    lines = []
    for date_str, weekday in entries:
        item = meta.get(date_str, {"trend": "mixed", "title": "收盘主线复盘"})
        badge_cls, badge_text = BADGE_MAP.get(item["trend"], BADGE_MAP["mixed"])
        title = item["title"]
        lines.append(f"""        <li>
          <a href="archive/{date_str}.html">
            <div class="r-left">
              <div class="r-date">{date_str} · {weekday}</div>
              <div class="r-title">{title}</div>
            </div>
            <span class="r-badge {badge_cls}">{badge_text}</span>
            <span class="arrow">›</span>
          </a>
        </li>""")
    return "\n".join(lines)


def update_index(entries, meta):
    """更新 index.html 的最新报告信息和历史列表"""
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    if not entries:
        print("[WARN] archive 目录为空，跳过 index 更新")
        return

    # 更新最新报告信息
    latest_date, latest_weekday = entries[0]
    latest_meta = meta.get(latest_date, {"title": "收盘主线复盘"})
    html = re.sub(
        r'(<div class="date" id="latest-date">).*?(</div>)',
        rf'\g<1>{latest_date}（{latest_weekday}）\g<2>',
        html, flags=re.S
    )
    html = re.sub(
        r'(<div class="desc" id="latest-desc">).*?(</div>)',
        rf'\g<1>{latest_meta["title"]}\g<2>',
        html, flags=re.S
    )

    # 重建历史列表
    list_html = build_list_html(entries, meta)
    html = re.sub(
        r'(<ul class="report-list" id="report-list">).*?(</ul>)',
        lambda m: m.group(1) + "\n" + list_html + "\n      " + m.group(2),
        html, flags=re.S
    )

    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[OK] index.html 已更新（{len(entries)} 份报告）")


def main():
    ap = argparse.ArgumentParser(description="发布 A股收盘复盘到 GitHub Pages")
    ap.add_argument("--report", help="报告 HTML 文件路径")
    ap.add_argument("--date", help="报告日期 YYYY-MM-DD（默认今天）")
    ap.add_argument("--title", default="收盘主线复盘", help="一句话摘要")
    ap.add_argument("--trend", default="mixed",
                    choices=["up", "down", "mixed"], help="主线强弱")
    ap.add_argument("--no-push", action="store_true", help="只更新本地不推送")
    ap.add_argument("--rebuild", action="store_true",
                    help="仅重建 index（不导入新报告）")
    args = ap.parse_args()

    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    meta = load_meta()

    if not args.rebuild:
        if not args.report:
            print("[ERROR] 需要 --report 参数（或用 --rebuild 仅重建索引）",
                  file=sys.stderr)
            sys.exit(1)
        if not os.path.exists(args.report):
            print(f"[ERROR] 报告文件不存在: {args.report}", file=sys.stderr)
            sys.exit(1)

        date_str = args.date or datetime.now().strftime("%Y-%m-%d")
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            print(f"[ERROR] 日期格式错误: {date_str}，应为 YYYY-MM-DD",
                  file=sys.stderr)
            sys.exit(1)

        # 复制到 archive 和 latest
        dest = os.path.join(ARCHIVE_DIR, f"{date_str}.html")
        shutil.copy2(args.report, dest)
        shutil.copy2(args.report, LATEST_PATH)
        print(f"[OK] 报告已归档: archive/{date_str}.html")

        # 记录 meta
        meta[date_str] = {"trend": args.trend, "title": args.title}
        save_meta(meta)

    entries = scan_archive()
    update_index(entries, meta)

    # git 提交推送
    if args.no_push:
        print("[SKIP] --no-push 已指定，跳过推送")
        return

    run("git add -A")
    status = run("git status --porcelain", check=False)
    if not status:
        print("[SKIP] 无变更，无需提交")
        return

    commit_date = entries[0][0] if entries else datetime.now().strftime("%Y-%m-%d")
    # 沙箱环境无全局 git config，必须显式带 committer 身份，否则 commit 会失败
    run(f'{GIT_ID} commit -q -m "收盘复盘更新 {commit_date}"')
    print(f"[OK] 已提交")

    # 推送到 gh-pages 分支
    branch = run("git rev-parse --abbrev-ref HEAD", check=False) or "main"
    push_result = subprocess.run(
        f"git push -q origin {branch}:gh-pages",
        cwd=SITE_DIR, shell=True, capture_output=True, text=True
    )
    if push_result.returncode != 0:
        print(f"[ERROR] 推送失败:\n{push_result.stderr}", file=sys.stderr)
        print("[HINT] 本地已 commit，网络恢复后可手动执行："
              f"\n  cd {SITE_DIR} && git push origin {branch}:gh-pages",
              file=sys.stderr)
        sys.exit(1)
    print("[OK] 已推送到 gh-pages")
    print("[URL] https://roycejfu.github.io/astock-daily/")


if __name__ == "__main__":
    main()
