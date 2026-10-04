"""マネージャー(manager)向けダッシュボードのルーティング。

マネージャーのみアクセス可。チーム全体を俯瞰する読み取り専用の集計ビュー。年休は事由を出さない。
"""
from datetime import date, datetime, time, timedelta

from flask import Blueprint, render_template, request, abort
from flask_login import login_required, current_user

from app.utils import get_active_users, parse_date
from app.models.user import User, ROLE_MEMBER
from app.models.task import (
    Task, TaskComment, STATUS_CHOICES, STATUS_TODO, STATUS_DOING, STATUS_HOLD,
    STATUS_DONE, STATUS_COLORS,
)
from app.models.routine import RoutineWork
from app.models.leave import LeaveRequest
from app.models.skill import (
    Skill, SkillRating, SKILL_TECHNICAL, SKILL_PROFICIENT_LEVEL,
)

manager_bp = Blueprint("manager", __name__, url_prefix="/manager")

# ヒト別 月間負荷(目安工数h)の水準。フルタイム≒160h/月 を基準に色分け。
_LOAD_FULL = 160


def _load_level(total_h):
    if total_h >= _LOAD_FULL:
        return {"label": "高", "color": "danger", "pct": min(100, round(total_h / _LOAD_FULL * 100))}
    if total_h >= _LOAD_FULL / 2:
        return {"label": "中", "color": "warning", "pct": round(total_h / _LOAD_FULL * 100)}
    return {"label": "低", "color": "success", "pct": round(total_h / _LOAD_FULL * 100)}


def _build_workload(today, users):
    """ヒト別の負荷(月間目安工数h)と案件状況を集計する。

    タスク: 規模を実働工数に換算→期間で月あたりに配分(複数担当は均等割り)。未完了のみ。
    定型・定期業務: 月間工数(monthly_minutes)。両者を合算して月間負荷(h)を出す。
    """
    load = {
        u.id: {
            "user": u, "doing": 0, "todo": 0, "hold": 0, "overdue": 0,
            "task_h": 0.0, "routine_cnt": 0, "routine_min": 0,
        }
        for u in users
    }

    for t in Task.query.filter(Task.status != STATUS_DONE).all():
        assignees = [u for u in t.assignees if u.id in load]
        n = len(assignees)
        if n == 0:
            continue
        share = t.scale_monthly_hours / n  # 複数担当は均等割り
        overdue = bool(t.due_date and t.due_date < today)
        for u in assignees:
            d = load[u.id]
            if t.status == STATUS_DOING:
                d["doing"] += 1
            elif t.status == STATUS_TODO:
                d["todo"] += 1
            elif t.status == STATUS_HOLD:
                d["hold"] += 1
            if overdue:
                d["overdue"] += 1
            d["task_h"] += share

    for rw in RoutineWork.query.all():
        d = load.get(rw.assignee_id)
        if d is None:
            continue
        d["routine_cnt"] += 1
        d["routine_min"] += rw.monthly_minutes or 0

    rows = []
    for u in users:
        d = load[u.id]
        task_h = round(d["task_h"], 1)
        routine_h = round(d["routine_min"] / 60.0, 1)
        total_h = round(task_h + routine_h, 1)
        rows.append({
            "user": u, "doing": d["doing"], "todo": d["todo"], "hold": d["hold"],
            "overdue": d["overdue"], "task_open": d["doing"] + d["todo"] + d["hold"],
            "task_h": task_h, "routine_cnt": d["routine_cnt"],
            "routine_h": routine_h, "total_h": total_h,
            "spare": round(_LOAD_FULL - total_h, 1),  # 余力(フルタイム160h/月に対する残り。負=超過)
            "level": _load_level(total_h),
        })
    rows.sort(key=lambda r: r["total_h"], reverse=True)

    totals = {
        "task_open": sum(r["task_open"] for r in rows),
        "overdue": sum(r["overdue"] for r in rows),
        "task_h": round(sum(r["task_h"] for r in rows), 1),
        "routine_cnt": sum(r["routine_cnt"] for r in rows),
        "routine_h": round(sum(r["routine_h"] for r in rows), 1),
        "total_h": round(sum(r["total_h"] for r in rows), 1),
        "spare": round(sum(r["spare"] for r in rows), 1),
    }
    return rows, totals


# 成果(定量)の単位を「年あたり」に換算する係数。
# 1年=12ヶ月=360日(定型・定期業務の 30日/月 換算に合わせる)。
_OUTCOME_YEAR_FACTOR = {"年": 1, "月": 12, "日": 360}
_OUTCOME_MONEY = "￥"
_OUTCOME_HOUR = "ｈ"


def _annualize(value, unit):
    """成果(値＋単位)を (種別, 年換算値) にする。判定できないものは (None, 0)。"""
    if value is None or not unit:
        return None, 0.0
    kind, _sep, period = unit.partition("/")
    factor = _OUTCOME_YEAR_FACTOR.get(period)
    if factor is None or kind not in (_OUTCOME_MONEY, _OUTCOME_HOUR):
        return None, 0.0
    return kind, float(value) * factor


def _build_activity(today, users, include_unassigned=True):
    """活動状況(進捗記載)を「タスクの担当者」別 → タスク別 → 時系列にまとめる。

    記載者ではなく担当者の枠に出す(複数担当なら各担当の枠に重複表示)。
    期間は afrom/ato(既定=直近7日)。個人ダッシュボードでは users に本人だけを渡す。
    """
    act_from = parse_date(request.args.get("afrom")) or (today - timedelta(days=6))
    act_to = parse_date(request.args.get("ato")) or today
    if act_to < act_from:
        act_from, act_to = act_to, act_from

    act_comments = (
        TaskComment.query.filter(
            TaskComment.created_at >= datetime.combine(act_from, time.min),
            TaskComment.created_at <= datetime.combine(act_to, time.max),
        )
        .order_by(TaskComment.created_at.asc())  # タスク内は時系列(古い→新しい)
        .all()
    )

    def group_by_task(comments):
        task_map = {}  # task_id -> {"task":.., "comments":[...]}
        for c in comments:
            grp = task_map.get(c.task_id)
            if grp is None:
                grp = {"task": c.task, "comments": []}
                task_map[c.task_id] = grp
            grp["comments"].append(c)
        return sorted(
            task_map.values(),
            key=lambda g: g["comments"][-1].created_at, reverse=True,
        )

    rows = []
    for u in users:
        mine = [
            c for c in act_comments
            if c.task is not None and c.task.is_assigned_to(u)
        ]
        rows.append({"user": u, "label": u.display_name, "tasks": group_by_task(mine)})

    # 担当者未割当のタスクへの記載はどの枠にも出ないため、別枠でまとめる
    if include_unassigned:
        unassigned = [
            c for c in act_comments
            if c.task is not None and not c.task.assignees
        ]
        if unassigned:
            rows.append({
                "user": None, "label": "担当者未割当のタスク",
                "tasks": group_by_task(unassigned),
            })

    return {"activity_rows": rows, "act_from": act_from, "act_to": act_to}


def _build_outcomes(today, users, only_user_id=None):
    """成果(見込み・実績)をヒト別・全体で集計する。

    only_user_id を渡すと、その人が担当のタスクだけを集計する(個人ダッシュボード用)。
    按分はマネージャー画面と揃えるため、担当者数で割った値をそのまま使う。

    - 金額(￥)と時間(ｈ)は足せないので分けて集計し、いずれも年換算で揃える
    - 期間は「期限日(未設定なら開始日)」を基準に絞り込む(既定=今年)
    - 複数担当のタスクは負荷集計と同じく担当者で均等割り
    """
    ofrom = parse_date(request.args.get("ofrom")) or date(today.year, 1, 1)
    oto = parse_date(request.args.get("oto")) or date(today.year, 12, 31)
    if oto < ofrom:
        ofrom, oto = oto, ofrom

    def blank(user, label):
        return {
            "user": user, "label": label, "money_est": 0.0, "money_act": 0.0,
            "hour_est": 0.0, "hour_act": 0.0, "tasks": 0,
        }

    acc = {u.id: blank(u, u.display_name) for u in users}
    unassigned = blank(None, "未割当")
    qual_rows = []   # 定性成果(記載のあるタスク)
    undated = 0      # 期限・開始日が無く集計対象外になったタスク
    no_unit = 0      # 数値はあるが単位未選択で金額/時間に振り分けられないタスク
    counted = set()  # 合計の件数用(複数担当でも1件と数える)

    for t in Task.query.all():
        # 個人ダッシュボードでは自分が担当のタスクだけを対象にする
        if only_user_id is not None and not any(u.id == only_user_id for u in t.assignees):
            continue

        basis = t.due_date or t.start_date
        if basis is None:
            if (t.outcome_quant_estimate is not None
                    or t.outcome_quant_actual is not None
                    or t.outcome_qual_estimate or t.outcome_qual_actual):
                undated += 1
            continue
        if not (ofrom <= basis <= oto):
            continue

        e_kind, e_val = _annualize(t.outcome_quant_estimate, t.outcome_quant_estimate_unit)
        a_kind, a_val = _annualize(t.outcome_quant_actual, t.outcome_quant_actual_unit)
        has_qual = bool(t.outcome_qual_estimate or t.outcome_qual_actual)
        # 数値はあるのに単位が未選択だと金額/時間に振り分けられない(集計外)
        if ((t.outcome_quant_estimate is not None and e_kind is None)
                or (t.outcome_quant_actual is not None and a_kind is None)):
            no_unit += 1
        if e_kind is None and a_kind is None and not has_qual:
            continue  # 成果の記載が無いタスクは対象外

        assigned = [acc[u.id] for u in t.assignees if u.id in acc]
        if only_user_id is not None:
            # 按分の分母は全担当者数のまま(マネージャー画面と同じ値)、計上先は本人のみ
            targets = [acc[only_user_id]] if only_user_id in acc else []
            n = len(assigned) or 1
        else:
            targets = assigned or [unassigned]
            n = len(targets)
        if not targets:
            continue

        counted.add(t.id)
        for d in targets:
            d["tasks"] += 1
            if e_kind == _OUTCOME_MONEY:
                d["money_est"] += e_val / n
            elif e_kind == _OUTCOME_HOUR:
                d["hour_est"] += e_val / n
            if a_kind == _OUTCOME_MONEY:
                d["money_act"] += a_val / n
            elif a_kind == _OUTCOME_HOUR:
                d["hour_act"] += a_val / n

        if has_qual:
            qual_rows.append({
                "task": t,
                "estimate": t.outcome_qual_estimate,
                "actual": t.outcome_qual_actual,
            })

    rows = [d for d in acc.values() if d["tasks"]]
    if unassigned["tasks"]:
        rows.append(unassigned)

    def rate(act, est):
        return round(act / est * 100) if est else None

    for d in rows:
        d["money_diff"] = round(d["money_act"] - d["money_est"], 1)
        d["hour_diff"] = round(d["hour_act"] - d["hour_est"], 1)
        d["money_rate"] = rate(d["money_act"], d["money_est"])
        d["hour_rate"] = rate(d["hour_act"], d["hour_est"])
    rows.sort(key=lambda d: (d["money_act"], d["hour_act"]), reverse=True)

    totals = {
        "tasks": len(counted),  # 複数担当でも1件(ヒト別の件数は各担当に計上)
        "money_est": sum(d["money_est"] for d in rows),
        "money_act": sum(d["money_act"] for d in rows),
        "hour_est": sum(d["hour_est"] for d in rows),
        "hour_act": sum(d["hour_act"] for d in rows),
    }
    totals["money_diff"] = round(totals["money_act"] - totals["money_est"], 1)
    totals["hour_diff"] = round(totals["hour_act"] - totals["hour_est"], 1)
    totals["money_rate"] = rate(totals["money_act"], totals["money_est"])
    totals["hour_rate"] = rate(totals["hour_act"], totals["hour_est"])

    # グラフの横幅を揃えるための最大値
    money_max = max([max(d["money_est"], d["money_act"]) for d in rows] or [0])
    hour_max = max([max(d["hour_est"], d["hour_act"]) for d in rows] or [0])

    qual_rows.sort(key=lambda q: (q["task"].due_date or q["task"].start_date), reverse=True)

    return {
        "o_rows": rows, "o_totals": totals,
        "o_money_max": money_max, "o_hour_max": hour_max,
        "o_from": ofrom, "o_to": oto,
        "o_qual": qual_rows, "o_undated": undated, "o_no_unit": no_unit,
    }


def _build_gantt(today, only_user_id=None):
    """全タスクのガントチャート用データを組み立てる(ダッシュボード内蔵・全画面で共用)。

    only_user_id を渡すと、その人が担当のタスクだけに絞る(個人ダッシュボード用)。

    - 棒はステータス変更履歴に沿って日付ごとに色分け(segments)
    - 完了以外で期限超過は overdue(カミナリ線)
    - 進捗記載(コメント)日には marks(印＋ツールチップ)
    - 期間(gfrom/gto)・担当者(gassignee)・完了非表示(ghide)・ソート(gsort/gdir)に対応
    """
    gfrom = parse_date(request.args.get("gfrom")) or (today - timedelta(days=7))
    gto = parse_date(request.args.get("gto")) or (today + timedelta(days=28))
    if gto < gfrom:
        gfrom, gto = gto, gfrom
    gsort = request.args.get("gsort", "task")
    if gsort not in ("task", "assignee"):
        gsort = "task"
    gdir = request.args.get("gdir", "asc")
    if gdir not in ("asc", "desc"):
        gdir = "asc"
    ghide = request.args.get("ghide") == "1"
    # 個人ダッシュボードは本人固定(担当者フィルタは出さない)
    gassignee = "" if only_user_id is not None else request.args.get("gassignee", "")

    gtotal_days = (gto - gfrom).days + 1

    def left_of(d):
        return round((d - gfrom).days / gtotal_days * 100, 3)

    def width_of(days):
        return round(days / gtotal_days * 100, 3)

    gquery = Task.query
    if ghide:
        gquery = gquery.filter(Task.status != STATUS_DONE)
    if only_user_id is not None:
        gquery = gquery.filter(Task.assignees.any(User.id == only_user_id))
    elif gassignee.isdigit():
        gquery = gquery.filter(Task.assignees.any(User.id == int(gassignee)))

    gantt = []
    for t in gquery.all():
        s = t.start_date or t.due_date
        e = t.due_date or t.start_date
        segments = []
        marks = []
        if s and e:
            a, b = (s, e) if s <= e else (e, s)
            vs = max(a, gfrom)
            ve = min(b, gto)
            if vs <= ve:
                changes = list(t.status_changes)  # changed_at 昇順

                def status_at(d, _changes=changes, _task=t):
                    st = None
                    for c in _changes:
                        if c.changed_at.date() <= d:
                            st = c.status
                        else:
                            break
                    if st is None:
                        st = _changes[0].status if _changes else _task.status
                    return st

                cuts = sorted({
                    c.changed_at.date() for c in changes
                    if vs < c.changed_at.date() <= ve
                })
                bounds = [vs] + cuts + [ve + timedelta(days=1)]
                for i in range(len(bounds) - 1):
                    seg_s, seg_e = bounds[i], bounds[i + 1]
                    days = (seg_e - seg_s).days
                    if days <= 0:
                        continue
                    st = status_at(seg_s)
                    if segments and segments[-1]["status"] == st:
                        segments[-1]["width"] = round(segments[-1]["width"] + width_of(days), 3)
                    else:
                        segments.append({"left": left_of(seg_s), "width": width_of(days), "status": st})

                # 進捗記載(コメント)の印は、棒が可視のときのみ棒の上に打つ
                for c in t.comments:
                    cd = c.created_at.date()
                    if gfrom <= cd <= gto:
                        marks.append({
                            "left": left_of(cd),
                            "tip": "{} {}：{}".format(
                                c.created_at.strftime("%m/%d %H:%M"), c.user.display_name, c.body
                            ),
                        })

        overdue = bool(t.due_date and t.status != STATUS_DONE and t.due_date < today)
        overdue_left = left_of(t.due_date) if (overdue and gfrom <= t.due_date <= gto) else None

        gantt.append({
            "task": t, "segments": segments,
            "overdue": overdue, "overdue_left": overdue_left, "marks": marks,
        })

    def _gkey(g):
        t = g["task"]
        if gsort == "assignee":
            return (t.assignee_names or "￿").lower()
        return (t.title or "").lower()
    gantt.sort(key=_gkey, reverse=(gdir == "desc"))

    gticks = []
    d = gfrom
    while d <= gto:
        gticks.append({"date": d, "left": left_of(d)})
        d += timedelta(days=7)
    gtoday_left = left_of(today) if gfrom <= today <= gto else None

    return {
        "gantt": gantt,
        "gfrom": gfrom, "gto": gto,
        "gsort": gsort, "gdir": gdir, "ghide": ghide, "gassignee": gassignee,
        "gticks": gticks, "gtoday_left": gtoday_left,
        "status_colors": STATUS_COLORS,
        "gusers": [] if only_user_id is not None else get_active_users(),
        "gpersonal": only_user_id is not None,
    }


@manager_bp.route("/")
@login_required
def dashboard():
    if not current_user.is_manager:
        abort(403)

    today = date.today()
    users = get_active_users()
    members = [u for u in users if u.role == ROLE_MEMBER]
    member_ids = {u.id for u in members}
    # 「メンバー」集計の母数は ROLE_MEMBER のみ(マネージャーは除く)
    member_count = len(members)

    # ---- タスク進捗 ----
    task_counts = {s: Task.query.filter_by(status=s).count() for s in STATUS_CHOICES}
    task_open = Task.query.filter(Task.status != STATUS_DONE).count()
    task_overdue = Task.query.filter(
        Task.status != STATUS_DONE,
        Task.due_date.isnot(None),
        Task.due_date < today,
    ).count()
    task_overdue_rate = round(task_overdue / task_open * 100) if task_open else 0

    # ---- 年休: 直近1か月(今日〜30日先)の休暇予定 ----
    upcoming_leaves = (
        LeaveRequest.query.filter(
            LeaveRequest.leave_date >= today,
            LeaveRequest.leave_date <= today + timedelta(days=30),
        )
        .order_by(LeaveRequest.leave_date)
        .all()
    )

    # ---- スキル保有状況(テクニカル) ----
    tech_skills = (
        Skill.query.filter_by(skill_type=SKILL_TECHNICAL, is_active=True)
        .order_by(Skill.sort_order, Skill.name)
        .all()
    )
    weak_threshold = max(1, (member_count + 2) // 3)  # 対象の約1/3未満を手薄とみなす
    skill_rows = []
    for s in tech_skills:
        # 保有人数もメンバーに限定して数える(分母と母集団を揃える)
        holders = sum(
            1 for r in s.ratings
            if r.level >= SKILL_PROFICIENT_LEVEL and r.user_id in member_ids
        )
        skill_rows.append(
            {"skill": s, "holders": holders, "total": member_count,
             "weak": holders < weak_threshold}
        )

    # メンバー別 平均到達度(全テクニカル項目に対して。未評価=0)
    tech_ids = [s.id for s in tech_skills]
    by_user = {}
    if tech_ids:
        for r in SkillRating.query.filter(SkillRating.skill_id.in_(tech_ids)).all():
            by_user.setdefault(r.user_id, []).append(r.level)
    n_tech = len(tech_skills)
    member_avg = []
    for u in members:  # 「メンバー別」なのでメンバーのみを並べる
        levels = by_user.get(u.id, [])
        avg = round(sum(levels) / n_tech, 1) if n_tech else 0
        member_avg.append({"user": u, "avg": avg})

    # ---- メンバーの活動状況(進捗記載)。ヒト別 → タスク別 → 時系列 ----
    actx = _build_activity(today, users)
    activity_rows = actx["activity_rows"]
    act_from = actx["act_from"]
    act_to = actx["act_to"]

    # ---- ヒト別 負荷・案件状況(タスク＋定型業務を合算) ----
    workload_rows, workload_totals = _build_workload(today, users)

    # ---- 成果(見込み・実績)。ヒト別＋全体 ----
    octx = _build_outcomes(today, users)

    # ---- 全タスクのガントチャート ----
    gctx = _build_gantt(today)

    return render_template(
        "manager/dashboard.html",
        today=today,
        member_count=member_count,
        # ヒト別 負荷・案件状況
        workload_rows=workload_rows,
        workload_totals=workload_totals,
        load_full=_LOAD_FULL,
        # タスク
        task_counts=task_counts,
        task_colors=STATUS_COLORS,
        task_overdue=task_overdue,
        task_overdue_rate=task_overdue_rate,
        # 年休(直近1か月の休暇予定)
        upcoming_leaves=upcoming_leaves,
        # スキル
        skill_rows=skill_rows,
        member_avg=member_avg,
        proficient=SKILL_PROFICIENT_LEVEL,
        # メンバーの活動状況
        activity_rows=activity_rows,
        act_from=act_from,
        act_to=act_to,
        # ガントチャート(ダッシュボード内蔵。リンクは他セクションの期間も保持)
        gantt_endpoint="manager.dashboard",
        gantt_extra={
            "afrom": act_from.strftime("%Y-%m-%d"),
            "ato": act_to.strftime("%Y-%m-%d"),
            "ofrom": octx["o_from"].strftime("%Y-%m-%d"),
            "oto": octx["o_to"].strftime("%Y-%m-%d"),
        },
        **octx,
        **gctx,
    )


@manager_bp.route("/gantt")
@login_required
def gantt_full():
    """全タスクのガントチャートを全画面で表示する専用ページ。"""
    if not current_user.is_manager:
        abort(403)
    gctx = _build_gantt(date.today())
    return render_template(
        "manager/gantt_full.html",
        gantt_endpoint="manager.gantt_full",
        gantt_extra={},
        **gctx,
    )
