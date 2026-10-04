"""年休(有給休暇)の予定のルーティング。

チーム内の情報共有・見える化が目的。承認フローは無し(登録=即共有)。
1レコード=1取得日。種別は 全休/午前半休/午後半休。
チーム(Department)は兼務対応の多対多。同日に同じチームで休む人数が多いと調整を促す。
取消は本人のみ。
"""
import calendar
from datetime import date, timedelta

from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    request,
    flash,
    abort,
)
from flask_login import login_required, current_user

from app.extensions import db
from app.utils import parse_date
from app.models.user import User
from app.models.department import Department
from app.models.leave import (
    LeaveRequest,
    LEAVE_TYPE_CHOICES,
    LEAVE_FULL,
    LEAVE_DAILY_LIMIT,
)

leaves_bp = Blueprint("leaves", __name__, url_prefix="/leaves")

WEEKDAY_LABELS = ["日", "月", "火", "水", "木", "金", "土"]


# --------------------------------------------------------------------------- #
# 権限ヘルパー(取消・編集は本人のみ)
# --------------------------------------------------------------------------- #
def _can_modify_leave(leave):
    return leave.user_id == current_user.id


def _get_or_404(leave_id):
    leave = db.session.get(LeaveRequest, leave_id)
    if leave is None:
        abort(404)
    return leave


def _duplicate_on(user_id, leave_date, exclude_id=None):
    """同一ユーザー・同一取得日の既存レコードを返す(無ければNone)。

    1日に複数登録すると換算日数が二重計上されるため、登録/更新時に弾く。
    """
    q = LeaveRequest.query.filter_by(user_id=user_id, leave_date=leave_date)
    if exclude_id:
        q = q.filter(LeaveRequest.id != exclude_id)
    return q.first()


def _active_departments():
    return Department.query.filter_by(is_active=True).order_by(Department.sort_order, Department.name).all()


# --------------------------------------------------------------------------- #
# 同日上限の超過判定・登録時メッセージ
# --------------------------------------------------------------------------- #
def _is_overbooked(user, leave_date, exclude_id=None):
    """本人の所属チーム(有効なもの)のいずれかで、同日に休む人数が上限を超えるか。"""
    # 無効化されたチームは判定対象外(カレンダーの警告と基準を揃える)
    depts = [d for d in user.departments if d.is_active]
    if not depts:
        return False
    q = LeaveRequest.query.filter(LeaveRequest.leave_date == leave_date)
    if exclude_id:
        q = q.filter(LeaveRequest.id != exclude_id)
    others = q.all()
    for dept in depts:
        member_ids = {u.id for u in dept.users}
        off_ids = {lv.user_id for lv in others if lv.user_id in member_ids}
        off_ids.add(user.id)  # 本人ぶん
        if len(off_ids) > LEAVE_DAILY_LIMIT:
            return True
    return False


def _registration_messages(user, leave_date, exclude_id=None):
    """登録/更新後に出すメッセージ(同日上限・今週連絡)をflashする。"""
    if _is_overbooked(user, leave_date, exclude_id=exclude_id):
        flash(
            "チーム内（マネージャー・メンバー）で業務影響ないよう事前にすり合わせて登録するようお願いします。",
            "warning",
        )
    # 今週(月〜日)の取得なら、チャット/メール/口頭での連絡を促す
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    if monday <= leave_date <= sunday:
        flash(
            "今週の取得です。チャット・メール・口頭のいずれかで関係者へ連絡をお願いします。",
            "info",
        )


# --------------------------------------------------------------------------- #
# カレンダー(既定ビュー)
# --------------------------------------------------------------------------- #
def _build_weeks(year, month, dept_id=None):
    cal = calendar.Calendar(firstweekday=6)  # 日曜始まり
    weeks_dates = cal.monthdatescalendar(year, month)
    first, last = weeks_dates[0][0], weeks_dates[-1][-1]

    leaves = LeaveRequest.query.filter(
        LeaveRequest.leave_date >= first, LeaveRequest.leave_date <= last
    ).all()

    # チームフィルタ
    if dept_id:
        dept = db.session.get(Department, dept_id)
        member_ids = {u.id for u in dept.users} if dept else set()
        leaves = [lv for lv in leaves if lv.user_id in member_ids]

    # チームごとのメンバー(同日上限の判定用)
    dept_member_ids = {d.id: {u.id for u in d.users} for d in _active_departments()}

    by_date = {}
    for lv in leaves:
        by_date.setdefault(lv.leave_date, []).append(lv)

    today = date.today()
    weeks = []
    for wk in weeks_dates:
        row = []
        for d in wk:
            day_leaves = by_date.get(d, [])
            off_ids = {lv.user_id for lv in day_leaves}
            if dept_id:
                warn = len(off_ids) > LEAVE_DAILY_LIMIT
            else:
                warn = any(
                    len(off_ids & mids) > LEAVE_DAILY_LIMIT
                    for mids in dept_member_ids.values()
                )
            row.append(
                {
                    "date": d,
                    "in_month": d.month == month,
                    "is_today": d == today,
                    "weekday": d.weekday(),
                    "is_weekend": d.weekday() >= 5,
                    "leaves": day_leaves,
                    "warn": warn,
                }
            )
        weeks.append(row)
    return weeks


@leaves_bp.route("/")
@login_required
def calendar_view():
    today = date.today()
    try:
        year = int(request.args.get("year", today.year))
        month = int(request.args.get("month", today.month))
        if not (1 <= month <= 12):
            raise ValueError
    except (TypeError, ValueError):
        year, month = today.year, today.month

    dept_raw = request.args.get("dept", "")
    dept_id = int(dept_raw) if dept_raw.isdigit() else None
    weeks = _build_weeks(year, month, dept_id)

    prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)

    return render_template(
        "leaves/calendar.html",
        weeks=weeks,
        year=year,
        month=month,
        weekday_labels=WEEKDAY_LABELS,
        departments=_active_departments(),
        dept_id=dept_id,
        prev=(prev_year, prev_month),
        next=(next_year, next_month),
        today=today,
        daily_limit=LEAVE_DAILY_LIMIT,
    )


# --------------------------------------------------------------------------- #
# 一覧
# --------------------------------------------------------------------------- #
@leaves_bp.route("/list")
@login_required
def list_leaves():
    user_id = request.args.get("user", "")
    scope = request.args.get("scope", "")
    date_from = parse_date(request.args.get("from"))
    date_to = parse_date(request.args.get("to"))

    query = LeaveRequest.query
    if user_id.isdigit():
        query = query.filter(LeaveRequest.user_id == int(user_id))
    if scope == "mine":
        query = query.filter(LeaveRequest.user_id == current_user.id)
    if date_from:
        query = query.filter(LeaveRequest.leave_date >= date_from)
    if date_to:
        query = query.filter(LeaveRequest.leave_date <= date_to)

    leaves = query.order_by(LeaveRequest.leave_date.desc(), LeaveRequest.id.desc()).all()
    total_days = round(sum(lv.day_count for lv in leaves), 2)

    users = User.query.filter_by(is_active=True).order_by(User.display_name).all()

    return render_template(
        "leaves/list.html",
        leaves=leaves,
        users=users,
        filters={
            "user": user_id,
            "scope": scope,
            "from": request.args.get("from", ""),
            "to": request.args.get("to", ""),
        },
        total_days=total_days,
    )


# --------------------------------------------------------------------------- #
# 新規登録
# --------------------------------------------------------------------------- #
@leaves_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_leave():
    if request.method == "POST":
        leave_date = parse_date(request.form.get("leave_date"))
        leave_type = request.form.get("leave_type") or LEAVE_FULL
        if leave_type not in LEAVE_TYPE_CHOICES:
            leave_type = LEAVE_FULL

        if leave_date is None:
            flash("取得日を入力してください。", "danger")
            return render_template(
                "leaves/form.html", leave=None,
                type_choices=LEAVE_TYPE_CHOICES, daily_limit=LEAVE_DAILY_LIMIT,
                form=request.form,
            )

        dup = _duplicate_on(current_user.id, leave_date)
        if dup:
            flash("その取得日の年休は既に登録されています。", "warning")
            return redirect(url_for("leaves.detail", leave_id=dup.id))

        leave = LeaveRequest(
            user_id=current_user.id, leave_date=leave_date, leave_type=leave_type
        )
        db.session.add(leave)
        db.session.commit()
        flash("年休を登録しました。", "success")
        _registration_messages(current_user, leave_date, exclude_id=leave.id)
        return redirect(url_for("leaves.calendar_view", year=leave_date.year, month=leave_date.month))

    return render_template(
        "leaves/form.html", leave=None,
        type_choices=LEAVE_TYPE_CHOICES, daily_limit=LEAVE_DAILY_LIMIT, form=None,
    )


# --------------------------------------------------------------------------- #
# 詳細
# --------------------------------------------------------------------------- #
@leaves_bp.route("/<int:leave_id>")
@login_required
def detail(leave_id):
    leave = _get_or_404(leave_id)
    return render_template(
        "leaves/detail.html", leave=leave, can_modify=_can_modify_leave(leave)
    )


# --------------------------------------------------------------------------- #
# 編集(本人のみ)
# --------------------------------------------------------------------------- #
@leaves_bp.route("/<int:leave_id>/edit", methods=["GET", "POST"])
@login_required
def edit_leave(leave_id):
    leave = _get_or_404(leave_id)
    if not _can_modify_leave(leave):
        flash("年休を編集できるのは本人のみです。", "danger")
        return redirect(url_for("leaves.detail", leave_id=leave.id))

    if request.method == "POST":
        leave_date = parse_date(request.form.get("leave_date"))
        leave_type = request.form.get("leave_type") or LEAVE_FULL
        if leave_type not in LEAVE_TYPE_CHOICES:
            leave_type = LEAVE_FULL
        if leave_date is None:
            flash("取得日を入力してください。", "danger")
            return render_template(
                "leaves/form.html", leave=leave,
                type_choices=LEAVE_TYPE_CHOICES, daily_limit=LEAVE_DAILY_LIMIT,
                form=request.form,
            )
        dup = _duplicate_on(current_user.id, leave_date, exclude_id=leave.id)
        if dup:
            flash("その取得日の年休は既に登録されています。", "warning")
            return redirect(url_for("leaves.detail", leave_id=dup.id))
        leave.leave_date = leave_date
        leave.leave_type = leave_type
        db.session.commit()
        flash("年休を更新しました。", "success")
        _registration_messages(current_user, leave_date, exclude_id=leave.id)
        return redirect(url_for("leaves.detail", leave_id=leave.id))

    return render_template(
        "leaves/form.html", leave=leave,
        type_choices=LEAVE_TYPE_CHOICES, daily_limit=LEAVE_DAILY_LIMIT, form=None,
    )


# --------------------------------------------------------------------------- #
# 取消(本人のみ)
# --------------------------------------------------------------------------- #
@leaves_bp.route("/<int:leave_id>/cancel", methods=["POST"])
@login_required
def cancel_leave(leave_id):
    leave = _get_or_404(leave_id)
    if not _can_modify_leave(leave):
        flash("年休を取消できるのは本人のみです。", "danger")
        return redirect(url_for("leaves.detail", leave_id=leave.id))
    db.session.delete(leave)
    db.session.commit()
    flash("年休を取消しました。", "info")
    return redirect(url_for("leaves.calendar_view"))
