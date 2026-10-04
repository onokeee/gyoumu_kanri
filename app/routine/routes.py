"""定型・定期業務のルーティング。

マネージャー・メンバーの全員が登録・編集・削除できる(権限による制限なし)。
"""
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
from app.models.user import User
from app.models.routine import (
    RoutineWork,
    FREQ_UNIT_CHOICES,
    FREQ_MONTH,
    MANUAL_CHOICES,
    MANUAL_DONE,
    MANUAL_UNDONE,
)

routine_bp = Blueprint("routine", __name__, url_prefix="/routine")


def _active_users():
    return User.query.filter_by(is_active=True).order_by(User.display_name).all()


def _person_summary():
    """ヒト別の集計(全データ対象): 総件数・総合計時間(月,分)・手順書 完/未完 件数。

    返り値 (rows, totals)。rows は担当者名順。担当者が無効化されていても計上する。
    """
    summary = {}
    for rw in RoutineWork.query.all():
        s = summary.get(rw.assignee_id)
        if s is None:
            s = summary[rw.assignee_id] = {
                "assignee": rw.assignee, "count": 0, "minutes": 0, "done": 0, "undone": 0,
            }
        s["count"] += 1
        s["minutes"] += rw.monthly_minutes or 0
        if rw.manual_status == MANUAL_DONE:
            s["done"] += 1
        else:
            s["undone"] += 1
    rows = sorted(
        summary.values(),
        key=lambda x: x["assignee"].display_name if x["assignee"] else "",
    )
    totals = {"count": 0, "minutes": 0, "done": 0, "undone": 0}
    for s in rows:
        for k in totals:
            totals[k] += s[k]
    return rows, totals


def _to_int(value):
    value = (value or "").strip()
    return int(value) if value.isdigit() else None


def _get_or_404(routine_id):
    r = db.session.get(RoutineWork, routine_id)
    if r is None:
        abort(404)
    return r


def _can_edit_routine(rw):
    """編集できるか:マネージャー、または自分が担当のもの(メンバーは自分の分のみ)。"""
    return current_user.is_manager or rw.assignee_id == current_user.id


def _assignee_users():
    """担当者の選択肢。メンバーは自分のみ、マネージャーは全員。"""
    return _active_users() if current_user.is_manager else [current_user]


def _forced_assignee_id():
    """メンバーは担当者を自分に固定する(マネージャーはNone=フォームの選択に従う)。"""
    return None if current_user.is_manager else current_user.id


def _fill_from_form(rw, form, forced_assignee_id=None):
    """フォーム値を rw に反映。エラーメッセージのリストを返す。

    forced_assignee_id を渡すと担当者はそれに固定(メンバーの自分固定に使う)。
    """
    errors = []
    name = form.get("name", "").strip()
    if not name:
        errors.append("業務名は必須です。")

    if forced_assignee_id is not None:
        assignee_id = str(forced_assignee_id)
    else:
        assignee_id = form.get("assignee_id", "")
        if not assignee_id.isdigit():
            errors.append("担当者を選択してください。")

    if errors:
        return errors

    unit = form.get("frequency_unit") or FREQ_MONTH
    if unit not in FREQ_UNIT_CHOICES:
        unit = FREQ_MONTH
    manual = form.get("manual_status") or MANUAL_UNDONE
    if manual not in MANUAL_CHOICES:
        manual = MANUAL_UNDONE

    rw.name = name
    rw.assignee_id = int(assignee_id)
    rw.purpose = form.get("purpose", "").strip()
    rw.frequency_count = _to_int(form.get("frequency_count"))
    rw.frequency_unit = unit
    rw.minutes_per = _to_int(form.get("minutes_per"))
    rw.content = form.get("content", "").strip()
    rw.manual_status = manual
    return []


# --------------------------------------------------------------------------- #
# 一覧
# --------------------------------------------------------------------------- #
@routine_bp.route("/")
@login_required
def list_routines():
    assignee_id = request.args.get("assignee", "")
    manual = request.args.get("manual", "")
    scope = request.args.get("scope", "")
    keyword = request.args.get("q", "").strip()

    query = RoutineWork.query
    if assignee_id.isdigit():
        query = query.filter(RoutineWork.assignee_id == int(assignee_id))
    if scope == "mine":
        query = query.filter(RoutineWork.assignee_id == current_user.id)
    if manual in MANUAL_CHOICES:
        query = query.filter(RoutineWork.manual_status == manual)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            db.or_(RoutineWork.name.ilike(like), RoutineWork.content.ilike(like))
        )

    routines = query.order_by(RoutineWork.assignee_id, RoutineWork.id.desc()).all()

    summary_rows, summary_totals = _person_summary()

    return render_template(
        "routine/list.html",
        routines=routines,
        users=_active_users(),
        manual_choices=MANUAL_CHOICES,
        summary_rows=summary_rows,
        summary_totals=summary_totals,
        filters={"assignee": assignee_id, "manual": manual, "scope": scope, "q": keyword},
    )


# --------------------------------------------------------------------------- #
# 新規登録
# --------------------------------------------------------------------------- #
@routine_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_routine():
    users = _assignee_users()  # メンバーは自分のみ選択可
    if request.method == "POST":
        rw = RoutineWork(creator_id=current_user.id)
        errors = _fill_from_form(rw, request.form, forced_assignee_id=_forced_assignee_id())
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template(
                "routine/form.html", routine=None, users=users,
                freq_choices=FREQ_UNIT_CHOICES, manual_choices=MANUAL_CHOICES,
                form=request.form,
            )
        db.session.add(rw)
        db.session.commit()
        flash("定型・定期業務を登録しました。", "success")
        return redirect(url_for("routine.detail", routine_id=rw.id))

    return render_template(
        "routine/form.html", routine=None, users=users,
        freq_choices=FREQ_UNIT_CHOICES, manual_choices=MANUAL_CHOICES, form=None,
    )


# --------------------------------------------------------------------------- #
# 詳細
# --------------------------------------------------------------------------- #
@routine_bp.route("/<int:routine_id>")
@login_required
def detail(routine_id):
    rw = _get_or_404(routine_id)
    return render_template("routine/detail.html", routine=rw, can_edit=_can_edit_routine(rw))


# --------------------------------------------------------------------------- #
# 編集(マネージャー、または自分が担当のもの。メンバーは自分の分のみ)
# --------------------------------------------------------------------------- #
@routine_bp.route("/<int:routine_id>/edit", methods=["GET", "POST"])
@login_required
def edit_routine(routine_id):
    rw = _get_or_404(routine_id)
    if not _can_edit_routine(rw):
        flash("この定型・定期業務を編集できるのは担当者・マネージャーのみです。", "danger")
        return redirect(url_for("routine.detail", routine_id=rw.id))
    users = _assignee_users()
    if request.method == "POST":
        errors = _fill_from_form(rw, request.form, forced_assignee_id=_forced_assignee_id())
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template(
                "routine/form.html", routine=rw, users=users,
                freq_choices=FREQ_UNIT_CHOICES, manual_choices=MANUAL_CHOICES,
                form=request.form,
            )
        db.session.commit()
        flash("定型・定期業務を更新しました。", "success")
        return redirect(url_for("routine.detail", routine_id=rw.id))

    return render_template(
        "routine/form.html", routine=rw, users=users,
        freq_choices=FREQ_UNIT_CHOICES, manual_choices=MANUAL_CHOICES, form=None,
    )


# --------------------------------------------------------------------------- #
# 削除(マネージャーのみ。登録・編集は全員可)
# --------------------------------------------------------------------------- #
@routine_bp.route("/<int:routine_id>/delete", methods=["POST"])
@login_required
def delete_routine(routine_id):
    rw = _get_or_404(routine_id)
    if not current_user.is_manager:
        flash("定型・定期業務を削除できるのはマネージャーのみです。", "danger")
        return redirect(url_for("routine.detail", routine_id=rw.id))
    db.session.delete(rw)
    db.session.commit()
    flash("定型・定期業務を削除しました。", "info")
    return redirect(url_for("routine.list_routines"))
