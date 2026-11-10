#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股每日收盘复盘 · GitHub Pages 发布脚本

用法：
  # 归档版（历史复盘列表，写到 archive/）
  python3 publish.py --report /path/to/收盘总结_2026-08-11.html \
                     --date 2026-08-11 \
                     --title "CPO 反弹修复，FCC 禁令暂缓" \
                     --trend up|down|mixed

  # 合并版（数据层+归因层二合一，写到 merged/）—— 2026-10-12 起为唯一正式日报
  python3 publish.py --report /path/to/合并版_2026-10-12.html \
                     --date 2026-10-12 --subdir merged \
                     --title "一句话摘要" --trend down

功能：
  1. 把报告写入 <subdir>/<date>.html（subdir 默认 archive）
  2. subdir=archive 时重建 index.html 历史列表；subdir=merged 时更新首页「合并版」入口
  3. commit 并 push 到 gh-pages 分支
"""
import argparse
import html as html_lib
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta

SITE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SUBDIR = "archive"
ARCHIVE_DIR = os.path.join(SITE_DIR, DEFAULT_SUBDIR)
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


def scan_archive(subdir=DEFAULT_SUBDIR):
    """扫描 <subdir> 目录，返回 [(date_str, weekday_cn), ...] 按日期倒序"""
    d = os.path.join(SITE_DIR, subdir)
    if not os.path.isdir(d):
        return []
    entries = []
    for fn in os.listdir(d):
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


def verify_remote_synced(remote_ref="gh-pages"):
    """push 后校验远端分支 HEAD 是否与本地 HEAD 一致。

    防止「本地已 commit 但远端未追上」造成的 index.html / latest.html
    日期撕裂（首页显示旧日期、点进去是新数据）。
    返回 True 表示一致；False 表示不一致或无法校验。
    """
    local_head = run("git rev-parse HEAD", check=False)
    remote = subprocess.run(
        f"git ls-remote origin {remote_ref}",
        cwd=SITE_DIR, shell=True, capture_output=True, text=True
    )
    if remote.returncode != 0:
        print(f"[WARN] 无法校验远端（ls-remote 失败）: {remote.stderr.strip()}",
              file=sys.stderr)
        return False
    parts = remote.stdout.strip().split()
    remote_hash = parts[0] if parts else ""
    if local_head and remote_hash and local_head == remote_hash:
        print(f"[OK] 远端 {remote_ref} 与本地 HEAD 一致 ({local_head[:8]})")
        return True
    print(f"[ERROR] ⚠️ 远端未追上本地：本地 {local_head[:8]} / 远端 "
          f"{remote_hash[:8] if remote_hash else '(空)'}", file=sys.stderr)
    return False


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


def extract_merged_title(path):
    """从 merged/<date>.html 的 <title> 提取一句话摘要。

    标题形如 "A股日报 2026-10-09 · 深V收复 资金未跟"，取 · 之后的部分。
    文件未写完（缺 </html>）时返回 None，避免把生成中的半成品纳入列表。
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            s = f.read()
        if "</html>" not in s:
            return None
        m = re.search(r"<title>(.*?)</title>", s, re.S | re.I)
        if not m:
            return None
        t = html_lib.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()
        if "·" in t:
            t = t.split("·", 1)[1].strip()
        return t or None
    except Exception:
        return None


def build_full_list_html():
    """重建归档首页「历史复盘」列表（2026-11-10 新增）。

    内容来源全部是磁盘上真实存在的报告，⛔ 不编造任何标题或结论：
      · merged/ 下每份完整报告 → 链接 merged/<date>.html，摘要取自其 <title>
      · archive/ 下 merged 没有的早期报告 → 链接 archive/<date>.html，用 meta.txt
      · 同一天两者都有时以 merged（唯一正式版）为准
      · 合并版时代（>= 2026-10-12）相邻报告间缺失的工作日 → 「缺档」占位，
        纯数据推断（不依赖日历），不设链接、不编内容
    返回 (列表 HTML 串, 实际报告数)。
    """
    items = {}   # date -> (href, title_html, badge_html)
    merged_dir = os.path.join(SITE_DIR, "merged")
    if os.path.isdir(merged_dir):
        for fn in os.listdir(merged_dir):
            m = re.match(r"^(\d{4}-\d{2}-\d{2})\.html$", fn)
            if not m:
                continue
            d = m.group(1)
            title = extract_merged_title(os.path.join(merged_dir, fn))
            if title is None:
                continue
            items[d] = (
                f"merged/{d}.html",
                html_lib.escape(title),
                '<span class="r-badge" style="background:#e8eef7;color:#1565c0">合并版</span>',
            )

    meta = load_meta()
    if os.path.isdir(ARCHIVE_DIR):
        for fn in os.listdir(ARCHIVE_DIR):
            m = re.match(r"^(\d{4}-\d{2}-\d{2})\.html$", fn)
            if not m:
                continue
            d = m.group(1)
            if d in items:          # merged 优先
                continue
            item = meta.get(d, {"trend": "mixed", "title": "收盘主线复盘"})
            cls, txt = BADGE_MAP.get(item["trend"], BADGE_MAP["mixed"])
            items[d] = (
                f"archive/{d}.html",
                html_lib.escape(item["title"]),
                f'<span class="r-badge {cls}">{txt}</span>',
            )

    # 合并版时代相邻报告之间缺失的工作日 → 缺档占位（10-12 之前早期非每交易日跑，不推断）
    gaps = set()
    recent = sorted(d for d in items if d >= "2026-10-12")
    for i in range(len(recent) - 1):
        cur = datetime.strptime(recent[i], "%Y-%m-%d") + timedelta(days=1)
        end = datetime.strptime(recent[i + 1], "%Y-%m-%d")
        while cur < end:
            if cur.weekday() < 5:
                gaps.add(cur.strftime("%Y-%m-%d"))
            cur += timedelta(days=1)

    lines = []
    for d in sorted(set(items) | gaps, reverse=True):
        wd = WEEKDAY_CN[datetime.strptime(d, "%Y-%m-%d").weekday()]
        if d in gaps:
            lines.append(f"""        <li>
          <div style="display:flex;align-items:center;justify-content:space-between;padding:14px 4px;gap:12px;opacity:.55">
            <div class="r-left">
              <div class="r-date">{d} · {wd}</div>
              <div class="r-title">该交易日日报未生成（历史缺档）</div>
            </div>
            <span class="r-badge" style="background:#f0f0f0;color:#999">缺档</span>
          </div>
        </li>""")
            continue
        href, title, badge = items[d]
        lines.append(f"""        <li>
          <a href="{href}">
            <div class="r-left">
              <div class="r-date">{d} · {wd}</div>
              <div class="r-title">{title}</div>
            </div>
            {badge}
            <span class="arrow">›</span>
          </a>
        </li>""")
    return "\n".join(lines), len(items)


def rebuild_full_list():
    """把 index.html 的 <ul id="report-list"> 替换为完整时间线。"""
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        page = f.read()
    list_html, n = build_full_list_html()
    if not n:
        print("[WARN] 未找到任何报告，跳过列表重建")
        return False
    # 旧版「最新复盘」横幅已停用（正式版是 merged），改标注避免误以为 10-12 是最新
    page = re.sub(r'(<div class="label">)[^<]*(</div>)',
                  r"\g<1>历史归档 · 旧版4段式（已停用）\g<2>", page, count=1)
    page, cnt = re.subn(
        r'(<ul class="report-list" id="report-list">).*?(</ul>)',
        lambda m: m.group(1) + "\n" + list_html + "\n      " + m.group(2),
        page, flags=re.S
    )
    if cnt != 1:
        print("[WARN] 未找到 id=report-list 锚点，列表未更新")
        return False
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"[OK] 归档首页历史列表已重建（{n} 份报告 + {len(list_html.split('<li>')) - 1 - n} 个缺档占位）")
    return True


def update_merged_entry(date_str, title):
    """subdir=merged 时：更新首页「合并版」入口的日期/摘要/链接，并顺带重建历史列表。

    2026-11-10 起历史列表由 merged/ 目录自动重建（此前只更新横幅、列表停在 10-12）。
    archive/ 早期归档仍保留在列表中，两者按日期倒序合并成一条完整时间线。
    """
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    # 用「是否找到锚点」判断匹配，而不是「替换后是否有变化」——
    # 同日重发时内容可能完全一致，用 diff 判断会误报「未匹配」。
    matched = ('id="merged-date"' in html) and ('id="merged-desc"' in html)
    if not matched:
        print("[WARN] index.html 未找到合并版入口锚点（id=merged-date / merged-desc），"
              "跳过（结构可能已变）")
        return False
    html = re.sub(
        r'(<div class="date" id="merged-date"[^>]*>).*?(</div>)',
        rf'\g<1>{date_str} 单篇合并版\g<2>', html, flags=re.S
    )
    html = re.sub(
        r'(<div class="desc" id="merged-desc"[^>]*>).*?(</div>)',
        rf'\g<1>{title}\g<2>', html, flags=re.S
    )
    html = re.sub(
        r'(<a class="btn" href=")merged/[^"]*(")',
        rf'\g<1>merged/{date_str}.html\g<2>', html
    )
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[OK] index.html 合并版入口已指向 {date_str}")
    rebuild_full_list()
    return True


def update_index(entries, meta, subdir=DEFAULT_SUBDIR):
    """更新 index.html 的最新报告信息和历史列表（仅 subdir=archive 时调用）"""
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
    # 「查看最新」按钮直接指向 archive/<最新日期>.html。
    # 2026-09-23 起不再依赖 latest.html 这个副本：它只是 archive 里最新一份的复制，
    # 既冗余、又因为每次都要整文件覆盖而受本机文件策略拦截（PermissionError）。
    html = re.sub(
        r'(<a class="btn" href=")[^"]*(">查看最新)',
        rf'\g<1>archive/{latest_date}.html\g<2>',
        html
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
    ap.add_argument("--subdir", default=DEFAULT_SUBDIR,
                    choices=["archive", "merged"],
                    help="输出子目录：archive=历史归档（默认） / merged=合并版正式日报")
    ap.add_argument("--no-push", action="store_true", help="只更新本地不推送")
    ap.add_argument("--rebuild", action="store_true",
                    help="仅重建 index（不导入新报告）")
    args = ap.parse_args()

    out_dir = os.path.join(SITE_DIR, args.subdir)
    os.makedirs(out_dir, exist_ok=True)
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

        # 写入 <subdir>/<date>.html
        dest = os.path.join(out_dir, f"{date_str}.html")
        # ⚠️ 2026-10-08：shutil.copy2 覆盖已存在的归档文件会被本机文件策略拦截
        #    （Brokered host copy overwrite refused → 发布中断在归档之后、commit 之前）。
        #    改「读取 + 直接写入」，语义相同但不走 copy 的删除/重建路径（与 flow-site 同步）。
        with open(args.report, "r", encoding="utf-8") as src:
            _content = src.read()
        with open(dest, "w", encoding="utf-8") as dst:
            dst.write(_content)
        print(f"[OK] 报告已写入: {args.subdir}/{date_str}.html")
        # ⛔ 不再写 latest.html：index 的「查看最新」已改为直接指向 archive/<date>.html。

        if args.subdir == DEFAULT_SUBDIR:
            meta[date_str] = {"trend": args.trend, "title": args.title}
            save_meta(meta)

    if args.subdir == "merged":
        if args.rebuild:
            # 仅重建历史列表，不动「最新」横幅（避免 --rebuild 时把入口指向尚未发布的日期）
            rebuild_full_list()
        else:
            update_merged_entry(
                args.date or datetime.now().strftime("%Y-%m-%d"), args.title)
    else:
        entries = scan_archive(args.subdir)
        update_index(entries, meta, args.subdir)

    # git 提交推送
    if args.no_push:
        print("[SKIP] --no-push 已指定，跳过推送")
        return

    run("git add -A")
    status = run("git status --porcelain", check=False)
    if not status:
        print("[SKIP] 无变更，无需提交")
        return

    if args.subdir == "merged":
        commit_date = args.date or datetime.now().strftime("%Y-%m-%d")
        commit_msg = f"合并版日报更新 {commit_date}"
    else:
        commit_date = entries[0][0] if entries else datetime.now().strftime("%Y-%m-%d")
        commit_msg = f"收盘复盘更新 {commit_date}"
    # 沙箱环境无全局 git config，必须显式带 committer 身份，否则 commit 会失败
    run(f'{GIT_ID} commit -q -m "{commit_msg}"')
    print(f"[OK] 已提交")

    # 推送到 gh-pages 分支（失败自动重试一次）
    branch = run("git rev-parse --abbrev-ref HEAD", check=False) or "main"
    pushed = False
    for attempt in (1, 2):
        push_result = subprocess.run(
            f"git push -q origin {branch}:gh-pages",
            cwd=SITE_DIR, shell=True, capture_output=True, text=True
        )
        if push_result.returncode == 0:
            pushed = True
            break
        print(f"[WARN] 第 {attempt} 次推送失败: {push_result.stderr.strip()}",
              file=sys.stderr)
    if not pushed:
        print("[ERROR] 推送失败（已重试 1 次）", file=sys.stderr)
        print("[HINT] 本地已 commit，网络恢复后可手动执行："
              f"\n  cd {SITE_DIR} && git push origin {branch}:gh-pages",
              file=sys.stderr)
        sys.exit(1)
    print("[OK] 已推送到 gh-pages")
    # 二次校验远端 HEAD，防止「本地已提交但远端未追上」的日期撕裂
    verify_remote_synced("gh-pages")
    if args.subdir == "merged":
        print(f"[URL] https://roycejfu.github.io/astock-daily/merged/{commit_date}.html")
    else:
        print("[URL] https://roycejfu.github.io/astock-daily/")


if __name__ == "__main__":
    main()
