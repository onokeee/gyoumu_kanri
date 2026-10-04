"""週報の材料(タスク情報)の収集と、チーム全体の集計。

材料にするのはタスク情報だけ:
  タスク(担当者・状態・優先度・開始日/期限・規模)、進捗記載(task_comments)、
  ステータス変更履歴(task_status_changes)、成果(実績)、負荷(月間負荷h・余力h)。
定型業務の内容・年休・スキルは週報に載せない(負荷の数値だけ _build_workload を使う)。

- 期間 [start, end] は日付で、両端を含む
- 進捗記載は「記載者」ではなく「タスクの担当者」の枠に入れる(ダッシュボードの活動状況と同じ)
- ステータス(進行中・保留・未完了など)は作成時点の値を使う
- 数値の集計はすべてここ(コード)で行う。AIには計算させない
- チーム全体の件数・成果は、複数担当のタスクも1件として数える(重複なし)
"""
from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import selectinload

from app.manager.routes import _OUTCOME_HOUR, _OUTCOME_MONEY, _annualize, _build_workload
from app.models.task import Task, STATUS_DOING, STATUS_DONE, STATUS_HOLD, STATUS_TODO
from app.models.user import User

# 「期限が近い」とみなす日数(期間の終了日の翌日から数える)
DUE_SOON_DAYS = 7
# 進捗記載1件を材料に載せる最大文字数(長文でAIへの送信量が膨らまないように)
COMMENT_MAX = 400


def _one_line(text, limit=None):
    """複数行のテキストを「 / 」区切りの1行にまとめる(長すぎる場合は切り詰める)。"""
    text = " / ".join(line.strip() for line in (text or "").splitlines() if line.strip())
    if limit and len(text) > limit:
        text = text[:limit] + "…"
    return text


def _sort_key(fact):
    """期限の近い順(期限なしは最後)→タイトル順。"""
    return (fact["due_date"] or date.max, fact["title"] or "")


def _completed_on(task):
    """完了日(最後に「完了」へ変更した日)。未完了なら None。

    変更履歴の無い完了タスク(古いデータなど)は更新日で代用する。
    """
    if task.status != STATUS_DONE:
        return None
    for change in reversed(task.status_changes):
        if change.status == STATUS_DONE and change.changed_at:
            return change.changed_at.date()
    return task.updated_at.date() if task.updated_at else None


def _task_facts(task, start, end):
    """1件のタスクについて、期間に関係する事実をまとめる(表示用の素の値だけ)。"""
    start_dt = datetime.combine(start, time.min)
    end_dt = datetime.combine(end, time.max)

    def in_period(dt):
        return dt is not None and start_dt <= dt <= end_dt

    comments = [
        {
            "at": c.created_at,
            "author": c.user.display_name if c.user else "",
            "text": _one_line(c.body, COMMENT_MAX),
        }
        for c in task.comments if in_period(c.created_at)
    ]
    # 最初の履歴は登録時の状態なので「変更」には含めない
    changes = [
        {"at": c.changed_at, "status": c.status}
        for c in task.status_changes[1:] if in_period(c.changed_at)
    ]
    completed_on = _completed_on(task)
    is_open = task.status != STATUS_DONE
    due = task.due_date
    return {
        "id": task.id,
        "title": task.title,
        "status": task.status,
        "priority": task.priority,
        "start_date": task.start_date,
        "due_date": due,
        "scale_label": task.scale_label or "",
        "assignees": task.assignee_names,
        "assignee_ids": {u.id for u in task.assignees},
        "comments": comments,
        "changes": changes,
        "initial_status": task.status_changes[0].status if task.status_changes else task.status,
        "created_in": in_period(task.created_at),
        # 着手 = 期間内に「進行中」になった(登録時から進行中の場合も含む)
        "started_in": any(
            c.status == STATUS_DOING and in_period(c.changed_at) for c in task.status_changes
        ),
        "completed_on": completed_on,
        "completed_in": completed_on is not None and start <= completed_on <= end,
        "is_open": is_open,
        "overdue": is_open and due is not None and due <= end,
        "due_soon": (is_open and due is not None
                     and end < due <= end + timedelta(days=DUE_SOON_DAYS)),
        "outcome_quant": task.outcome_quant_actual_label or "",
        "outcome_qual": _one_line(task.outcome_qual_actual),
        "outcome_value": task.outcome_quant_actual,
        "outcome_unit": task.outcome_quant_actual_unit,
    }


def _is_relevant(fact):
    """週報に関係するタスクか(未完了、または期間内に動きがあった)。"""
    return bool(
        fact["is_open"] or fact["comments"] or fact["changes"]
        or fact["completed_in"] or fact["created_in"]
    )


def _person_material(user, facts, workload_row):
    """1人分の材料。facts は対象者全員の関係タスク(重複なし)。"""
    mine = sorted((f for f in facts if user.id in f["assignee_ids"]), key=_sort_key)

    comments = sorted(
        (dict(c, task=f["title"]) for f in mine for c in f["comments"]),
        key=lambda c: c["at"],
    )
    changes = sorted(
        (dict(c, task=f["title"]) for f in mine for c in f["changes"]),
        key=lambda c: c["at"],
    )
    open_tasks = [f for f in mine if f["is_open"]]
    completed = [f for f in mine if f["completed_in"]]
    created = [f for f in mine if f["created_in"]]

    return {
        "user_id": user.id,
        "name": user.display_name,
        "open_tasks": open_tasks,
        "comments": comments,
        "changes": changes,
        "completed": completed,
        "created": created,
        "silent": [f for f in open_tasks if not f["comments"]],
        "overdue": [f for f in open_tasks if f["overdue"]],
        "due_soon": [f for f in open_tasks if f["due_soon"]],
        "doing_count": sum(1 for f in open_tasks if f["status"] == STATUS_DOING),
        "total_h": workload_row["total_h"] if workload_row else 0.0,
        "spare": workload_row["spare"] if workload_row else 0.0,
        # 動きの有無(無ければ AI を使わず「今週の記載なし」にする)
        "has_activity": bool(comments or changes or completed or created),
    }


def _team_metrics(facts, persons):
    """チーム全体の集計(重複なし)とヒト別の行。"""
    completed = sorted((f for f in facts if f["completed_in"]), key=_sort_key)
    overdue = sorted((f for f in facts if f["overdue"]), key=_sort_key)

    money = hour = 0.0
    for f in completed:
        kind, value = _annualize(f["outcome_value"], f["outcome_unit"])
        if kind == _OUTCOME_MONEY:
            money += value
        elif kind == _OUTCOME_HOUR:
            hour += value

    rows = [
        {
            "name": p["name"],
            "completed": len(p["completed"]),
            "doing": p["doing_count"],
            "overdue": len(p["overdue"]),
            "comments": len(p["comments"]),
            "total_h": p["total_h"],
            "spare": p["spare"],
        }
        for p in persons
    ]
    return {
        "person_count": len(persons),
        "completed": len(completed),
        "started": sum(1 for f in facts if f["started_in"]),
        "created": sum(1 for f in facts if f["created_in"]),
        "doing": sum(1 for f in facts if f["is_open"] and f["status"] == STATUS_DOING),
        "hold": sum(1 for f in facts if f["is_open"] and f["status"] == STATUS_HOLD),
        "todo": sum(1 for f in facts if f["is_open"] and f["status"] == STATUS_TODO),
        "overdue": len(overdue),
        "comments": sum(len(f["comments"]) for f in facts),
        "money_act": round(money, 1),   # ￥/年
        "hour_act": round(hour, 1),     # ｈ/年
        "completed_tasks": completed,
        "overdue_tasks": overdue,
        "rows": rows,
    }


def collect(start, end, users, today=None):
    """対象者(users)の期間 [start, end] の材料を集める。

    戻り値: {"start", "end", "persons": [1人分の材料...], "team": チーム全体の集計}
    users の順(表示名順)で persons を並べる。DBは読み取りのみ。
    """
    today = today or date.today()
    user_ids = [u.id for u in users]
    end_dt = datetime.combine(end, time.max)

    tasks = []
    if user_ids:
        tasks = (
            Task.query.filter(Task.assignees.any(User.id.in_(user_ids)))
            .options(
                selectinload(Task.assignees),
                selectinload(Task.comments),
                selectinload(Task.status_changes),
            )
            .all()
        )

    facts = []
    for task in tasks:
        # 期間より後に登録されたタスクは対象外(過去の期間を作成する場合)
        if task.created_at is not None and task.created_at > end_dt:
            continue
        fact = _task_facts(task, start, end)
        if _is_relevant(fact):
            facts.append(fact)

    workload_rows, _totals = _build_workload(today, users)
    workload = {r["user"].id: r for r in workload_rows}

    persons = [_person_material(u, facts, workload.get(u.id)) for u in users]
    return {
        "start": start,
        "end": end,
        "persons": persons,
        "team": _team_metrics(facts, persons),
    }
