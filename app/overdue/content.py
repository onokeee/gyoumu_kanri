"""期限超過タスクの収集と、メール(件名・テキスト版・HTML版)の作成。

期限超過 = 期限(due_date)が今日より前で、完了していないタスク。
  ■未着手／進行中　期限超過一覧 : 状態が「未着手」「進行中」
  ■保留　期限超過一覧           : 状態が「保留」
各区分の中は担当者ごとにまとめる。複数担当のタスクは各担当者の下に載せる。
無効化されたユーザーが担当のタスクもその人の下に載せ、名前に「［無効］」を付ける
(担当の付け替えが必要なことが分かるように)。担当者がいないタスクは「担当者なし」にまとめる。
担当者は件数の多い順(同数なら表示名順。「担当者なし」は同数の中で最後)、
タスクは期限の古い順(超過の長い順)に並べる。

各タスクには直近の進捗記載(コメント)を comment_count 件まで、古い順に載せる
(タスク名の次の行から1件ずつ。記載が無ければ「コメントなし」)。
経過日数は営業日で数え「M日前（土日祝除く）」と書く(今日のものは「本日」)。
本文は1行にまとめ(改行は空白に)、長いものは COMMENT_TEXT_MAX 文字で切る。

リンクは APP_BASE_URL(instance/config.py。システム設定の「基本設定」タブで変更)＋タスク詳細画面のパス。
APP_BASE_URL が空・不正ならリンクは付けない(タスク名だけ)。
テキスト版は「タスク名（URL）」、HTML版はタスク名をリンクにする。HTML版は
テンプレート(templates/overdue/mail.html)で作り、すべての値をエスケープする。

DBは読み取りのみ。app_context の中で呼ぶ(リクエストは不要)。
"""
import re
from datetime import datetime
from urllib.parse import urlsplit

from flask import current_app, render_template
from sqlalchemy.orm import selectinload

from app.holidays import business_days_ago
from app.models.task import STATUS_DOING, STATUS_HOLD, STATUS_TODO, Task, TaskComment

# 区分: (キー, 見出し, 対象の状態, タスクの状態を表示するか)
SECTION_DEFS = (
    ("active", "未着手／進行中", (STATUS_TODO, STATUS_DOING), True),
    ("hold", "保留", (STATUS_HOLD,), False),
)
UNASSIGNED_LABEL = "担当者なし"
INACTIVE_MARK = "［無効］"
NO_COMMENT = "コメントなし"
NONE_TEXT = "該当なし"
COMMENT_TEXT_MAX = 200

_LINE_BREAKS = re.compile(r"[\r\n\t\v\f]+")
_SPACES = re.compile(r" {2,}")


# --------------------------------------------------------------------------- #
# リンク(APP_BASE_URL)
# --------------------------------------------------------------------------- #
def link_base():
    """リンクの基準URL (URL, 問題の説明)。使えなければ ("", 説明)。

    APP_BASE_URL は http:// または https:// で始まるURL(末尾の / は不要)。
    """
    raw = str(current_app.config.get("APP_BASE_URL") or "").strip()
    if not raw:
        return "", ("APP_BASE_URL が未設定のため、メールのタスク名にリンクを付けられません"
                    "（タスク名だけを載せます）。システム設定の「基本設定」タブで設定してください。")
    try:
        parts = urlsplit(raw)
        valid = (parts.scheme.lower() in ("http", "https") and bool(parts.hostname)
                 and not parts.query and not parts.fragment
                 and not any(ch.isspace() or ord(ch) < 0x20 for ch in raw))
    except ValueError:
        valid = False
    if not valid:
        return "", ("APP_BASE_URL の形式が正しくないため、メールのタスク名にリンクを付けられません"
                    "（システム設定の「基本設定」タブで、http:// または https:// で始まるURLを設定してください）。")
    return raw.rstrip("/"), None


def task_path(task_id):
    """タスク詳細画面のパス(例: /tasks/12)。リクエストの外でも作れるよう URL マップから作る。"""
    adapter = current_app.url_map.bind("localhost")
    return adapter.build("tasks.detail", {"task_id": task_id})


# --------------------------------------------------------------------------- #
# 表記の小道具
# --------------------------------------------------------------------------- #
def _date_label(d, today):
    """日付の短い表記(今年は mm/dd、それ以外は yyyy/mm/dd)。"""
    if d.year == today.year:
        return d.strftime("%m/%d")
    return d.strftime("%Y/%m/%d")


def _age_label(d, today):
    """コメントの経過日数(営業日)。今日(以降)なら「本日」。"""
    if d >= today:
        return "本日"
    return "{}日前（土日祝除く）".format(business_days_ago(d, today))


def one_line(text, limit=COMMENT_TEXT_MAX):
    """改行を空白にして1行にし、長ければ limit 文字で切る(末尾に「…」)。"""
    text = _SPACES.sub(" ", _LINE_BREAKS.sub(" ", text or "")).strip()
    if len(text) > limit:
        text = text[:limit - 1].rstrip() + "…"
    return text


# --------------------------------------------------------------------------- #
# 収集
# --------------------------------------------------------------------------- #
def _comment_items(task, today, comment_count):
    """直近 comment_count 件のコメント(古い順)。"""
    comments = sorted(task.comments, key=lambda c: (c.created_at or datetime.min, c.id))
    items = []
    for c in comments[-comment_count:]:
        written = (c.created_at or datetime.now()).date()
        author = c.user.display_name if c.user is not None else "（不明）"
        items.append({
            "head": "【{} {} {}】".format(_age_label(written, today),
                                        _date_label(written, today), author),
            "text": one_line(c.body),
        })
    return items


def _task_item(task, today, comment_count, base, show_status):
    """タスク1件分の表示用の値。"""
    due = "期限 {}".format(_date_label(task.due_date, today))
    return {
        "id": task.id,
        "title": one_line(task.title, limit=200),
        "due_date": task.due_date,
        "meta": "［{}・{}］".format(task.status, due) if show_status else "［{}］".format(due),
        "url": base + task_path(task.id) if base else "",
        "comments": _comment_items(task, today, comment_count),
        # 担当者(無効化されたユーザーも含む)。(ユーザーID, 表示名, 有効か)
        "owners": [(u.id, u.display_name, bool(u.is_active)) for u in task.assignees],
    }


def _group(items):
    """担当者ごとにまとめる(件数の多い順 → 表示名順。「担当者なし」は同数の中で最後)。"""
    buckets = {}
    for item in items:
        for owner_id, name, active in item["owners"] or [(None, UNASSIGNED_LABEL, True)]:
            bucket = buckets.setdefault(
                owner_id, {"name": name, "unassigned": owner_id is None, "active": active,
                           "tasks": []})
            bucket["tasks"].append(item)
    groups = []
    for bucket in buckets.values():
        bucket["tasks"].sort(key=lambda i: (i["due_date"], i["id"]))
        bucket["count"] = len(bucket["tasks"])
        bucket["label"] = "{}{}{}（{}件）".format(
            bucket["name"], "" if bucket["unassigned"] else "さん",
            "" if bucket["active"] else INACTIVE_MARK, bucket["count"])
        groups.append(bucket)
    groups.sort(key=lambda g: (-g["count"], g["unassigned"], g["name"]))
    return groups


def collect(today, comment_count):
    """期限超過タスクを集めて、区分・担当者ごとにまとめる。

    戻り値: {"today", "sections": [{"key", "title", "count", "groups"}...],
             "counts": {区分のキー: 件数(重複なし)}, "total", "link_problem"}
    """
    statuses = [s for _key, _title, group, _show in SECTION_DEFS for s in group]
    tasks = (
        Task.query.filter(
            Task.due_date.isnot(None),
            Task.due_date < today,
            Task.status.in_(statuses),
        )
        .options(
            selectinload(Task.assignees),
            selectinload(Task.comments).selectinload(TaskComment.user),
        )
        .all()
    )
    base, link_problem = link_base()

    sections = []
    for key, title, section_statuses, show_status in SECTION_DEFS:
        items = [
            _task_item(t, today, comment_count, base, show_status)
            for t in tasks if t.status in section_statuses
        ]
        sections.append({"key": key, "title": title, "count": len(items),
                         "groups": _group(items)})
    return {
        "today": today,
        "sections": sections,
        "counts": {s["key"]: s["count"] for s in sections},
        "total": sum(s["count"] for s in sections),
        "link_problem": link_problem,
    }


# --------------------------------------------------------------------------- #
# メール(件名・テキスト版・HTML版)
# --------------------------------------------------------------------------- #
def build_subject(data):
    """件名(例: 【期限超過】2026/10/05 未着手・進行中 3件／保留 1件)。"""
    return "【期限超過】{} 未着手・進行中 {}件／保留 {}件".format(
        data["today"].strftime("%Y/%m/%d"), data["counts"]["active"], data["counts"]["hold"])


def _intro(data):
    if data["total"] == 0:
        return "{} 時点で、期限を過ぎた未完了のタスクはありません。".format(
            data["today"].strftime("%Y/%m/%d"))
    return "{} 時点で期限を過ぎている未完了のタスクの一覧です（未着手・進行中 {}件／保留 {}件）。".format(
        data["today"].strftime("%Y/%m/%d"), data["counts"]["active"], data["counts"]["hold"])


def _footer():
    return "※このメールは{}から送信しています。".format(
        current_app.config.get("APP_NAME") or "業務管理システム")


def section_heading(section):
    return "■{}　期限超過一覧".format(section["title"])


def build_text(data):
    """テキスト版の本文(タスク名の後ろに括弧でURL)。"""
    lines = [_intro(data), ""]
    for section in data["sections"]:
        lines.append(section_heading(section))
        if not section["groups"]:
            lines.append(NONE_TEXT)
        for group in section["groups"]:
            lines.append(group["label"])
            for task in group["tasks"]:
                name = task["title"]
                if task["url"]:
                    name += "（{}）".format(task["url"])
                comments = ["{}{}".format(c["head"], c["text"]) for c in task["comments"]]
                # 見やすさのため、コメントはタスク名の次の行から1件ずつ書く
                lines.append("　{}{}".format(name, task["meta"]))
                lines.extend("　　" + c for c in (comments or [NO_COMMENT]))
        lines.append("")
    lines.append(_footer())
    return "\n".join(lines)


def build_html(data, subject):
    """HTML版の本文(タスク名をリンクにする。値はテンプレートですべてエスケープする)。"""
    return render_template(
        "overdue/mail.html",
        data=data,
        subject=subject,
        intro=_intro(data),
        footer=_footer(),
        heading=section_heading,
        none_text=NONE_TEXT,
        no_comment=NO_COMMENT,
    )


def build(today, comment_count):
    """メールの内容を作る。

    戻り値: {"subject", "text", "html", "counts", "total", "link_problem", "data"}
    """
    data = collect(today, comment_count)
    subject = build_subject(data)
    return {
        "subject": subject,
        "text": build_text(data),
        "html": build_html(data, subject),
        "counts": data["counts"],
        "total": data["total"],
        "link_problem": data["link_problem"],
        "data": data,
    }
