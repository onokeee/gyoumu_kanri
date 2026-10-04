"""タスク管理のルーティング(一覧・作成・詳細・編集・状態更新・削除・コメント)。

1つのタスクを複数のメンバーに割り当て可能。コメントでやり取りする。
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
from app.utils import parse_date as _parse_due_date
from app.models.user import User
from app.models.task import (
    Task,
    TaskComment,
    TaskStatusChange,
    STATUS_CHOICES,
    STATUS_DONE,
    STATUS_COLORS,
    PRIORITY_CHOICES,
    PRIORITY_MID,
    OUTCOME_UNITS,
    TASK_SCALES,
    TASK_SCALE_KEYS,
)

tasks_bp = Blueprint("tasks", __name__, url_prefix="/tasks")

# 完了にするには成果(実績)が必要、という案内文(各所で共用)
_COMPLETE_NEEDS_OUTCOME = "「完了」にするには、成果(実績)の定量または定性のいずれかを入力してください。"


def _read_outcomes():
    """フォームから成果(定量・定性)欄を読み取る。返り値 (data, error)。

    定量の値は数値(カンマ・￥は無視)。不正な数値のときは error にメッセージを入れて返す。
    """
    def _num(field):
        raw = (request.form.get(field, "") or "").strip().replace(",", "").replace("￥", "")
        if raw == "":
            return None, False
        try:
            return float(raw), False
        except ValueError:
            return None, True

    est, est_bad = _num("outcome_quant_estimate")
    act, act_bad = _num("outcome_quant_actual")
    if est_bad:
        return None, "成果(定量)の見込みは数値で入力してください。"
    if act_bad:
        return None, "成果(定量)の実績は数値で入力してください。"

    def _unit(field):
        u = request.form.get(field, "") or None
        return u if u in OUTCOME_UNITS else None

    data = {
        "outcome_quant_estimate": est,
        "outcome_quant_estimate_unit": _unit("outcome_quant_estimate_unit"),
        "outcome_quant_actual": act,
        "outcome_quant_actual_unit": _unit("outcome_quant_actual_unit"),
        "outcome_quant_note": (request.form.get("outcome_quant_note", "") or "").strip() or None,
        "outcome_qual_estimate": (request.form.get("outcome_qual_estimate", "") or "").strip() or None,
        "outcome_qual_actual": (request.form.get("outcome_qual_actual", "") or "").strip() or None,
    }
    return data, None


def _outcomes_have_actual(data):
    """成果(実績)が定量・定性いずれかで入力されているか(完了の可否判定に使用)。"""
    return data["outcome_quant_actual"] is not None or bool(data["outcome_qual_actual"])


def _apply_outcomes(task, data):
    for key, value in data.items():
        setattr(task, key, value)


def _render_task_form(task, users, form, selected):
    return render_template(
        "tasks/form.html", task=task, users=users,
        status_choices=STATUS_CHOICES, priority_choices=PRIORITY_CHOICES,
        outcome_units=OUTCOME_UNITS, task_scales=TASK_SCALES,
        form=form, selected_assignees=selected,
        can_plan=current_user.is_manager,  # 計画系項目(優先度/日付/規模/担当者)を編集できるか
    )


def _read_scale():
    """フォームの規模を検証して返す(不正・未設定は None)。"""
    scale = request.form.get("scale") or None
    return scale if scale in TASK_SCALE_KEYS else None


def _log_status(task, status):
    """ステータス変更履歴を記録する(直近の記録と同じ状態なら追加しない)。

    ガントの棒を『ステータスを切り替えた日付』で色分けするために使う。
    """
    last = task.status_changes[-1].status if task.status_changes else None
    if status and status != last:
        task.status_changes.append(TaskStatusChange(status=status))


def _can_edit(task):
    """編集・削除の権限:作成者・担当者(いずれか)・マネージャーのみ。"""
    return (
        current_user.is_leader
        or task.creator_id == current_user.id
        or task.is_assigned_to(current_user)
    )


def _active_users():
    return User.query.filter_by(is_active=True).order_by(User.display_name).all()


def _selected_assignees(users):
    """フォームの assignee_ids(複数)から担当ユーザーのリストを返す。"""
    ids = {int(x) for x in request.form.getlist("assignee_ids") if x.isdigit()}
    return [u for u in users if u.id in ids]


@tasks_bp.route("/")
@login_required
def list_tasks():
    # フィルタ条件を取得(ステータス・担当者はチェックボックスで複数選択可=OR条件)
    statuses = [s for s in request.args.getlist("status") if s in STATUS_CHOICES]
    assignee_ids = [
        int(a) for a in request.args.getlist("assignee") if a.isdigit()
    ]
    scope = request.args.get("scope", "")  # "mine" なら自分の担当のみ
    hide_done = request.args.get("hide_done") == "1"  # 「完了」を除く
    keyword = request.args.get("q", "").strip()

    query = Task.query

    if statuses:
        query = query.filter(Task.status.in_(statuses))
    if assignee_ids:
        query = query.filter(Task.assignees.any(User.id.in_(assignee_ids)))
    if scope == "mine":
        query = query.filter(Task.assignees.any(User.id == current_user.id))
    if hide_done:
        query = query.filter(Task.status != STATUS_DONE)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            db.or_(Task.title.ilike(like), Task.description.ilike(like))
        )

    # 未完了→期限が近い順、その後に完了タスク
    tasks = query.order_by(
        (Task.status == STATUS_DONE).asc(),
        Task.due_date.is_(None).asc(),
        Task.due_date.asc(),
        Task.id.desc(),
    ).all()

    return render_template(
        "tasks/list.html",
        tasks=tasks,
        users=_active_users(),
        status_choices=STATUS_CHOICES,
        task_colors=STATUS_COLORS,
        priority_choices=PRIORITY_CHOICES,
        filters={
            "statuses": statuses, "assignees": assignee_ids,
            "scope": scope, "hide_done": hide_done, "q": keyword,
        },
    )


@tasks_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_task():
    # タスクの登録はマネージャーのみ(メンバーは不可)
    if not current_user.is_manager:
        flash("タスクを登録できるのはマネージャーのみです。", "danger")
        return redirect(url_for("tasks.list_tasks"))

    users = _active_users()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        sel = [u.id for u in _selected_assignees(users)]
        if not title:
            flash("タイトルは必須です。", "danger")
            return _render_task_form(None, users, request.form, sel)

        data, err = _read_outcomes()
        if err:
            flash(err, "danger")
            return _render_task_form(None, users, request.form, sel)

        status = request.form.get("status") or STATUS_CHOICES[0]
        if status == STATUS_DONE and not _outcomes_have_actual(data):
            flash(_COMPLETE_NEEDS_OUTCOME, "danger")
            return _render_task_form(None, users, request.form, sel)

        task = Task(
            title=title,
            description=request.form.get("description", "").strip(),
            status=status,
            priority=request.form.get("priority") or PRIORITY_MID,
            start_date=_parse_due_date(request.form.get("start_date")),
            due_date=_parse_due_date(request.form.get("due_date")),
            scale=_read_scale(),
            creator_id=current_user.id,
        )
        _apply_outcomes(task, data)
        task.assignees = _selected_assignees(users)
        db.session.add(task)
        _log_status(task, task.status)  # 初期ステータスを履歴に記録
        db.session.commit()
        flash("タスクを登録しました。", "success")
        return redirect(url_for("tasks.detail", task_id=task.id))

    return _render_task_form(None, users, None, [])


@tasks_bp.route("/<int:task_id>")
@login_required
def detail(task_id):
    task = db.session.get(Task, task_id)
    if task is None:
        abort(404)
    return render_template("tasks/detail.html", task=task, can_edit=_can_edit(task))


@tasks_bp.route("/<int:task_id>/edit", methods=["GET", "POST"])
@login_required
def edit_task(task_id):
    task = db.session.get(Task, task_id)
    if task is None:
        abort(404)
    if not _can_edit(task):
        flash("このタスクを編集する権限がありません。", "danger")
        return redirect(url_for("tasks.detail", task_id=task.id))

    users = _active_users()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        sel = [u.id for u in _selected_assignees(users)]
        if not title:
            flash("タイトルは必須です。", "danger")
            return _render_task_form(task, users, request.form, sel)

        data, err = _read_outcomes()
        if err:
            flash(err, "danger")
            return _render_task_form(task, users, request.form, sel)

        status = request.form.get("status") or task.status
        # 「完了」への変更時のみ実績を必須に(既に完了のタスクの編集は妨げない)
        if status == STATUS_DONE and task.status != STATUS_DONE and not _outcomes_have_actual(data):
            flash(_COMPLETE_NEEDS_OUTCOME, "danger")
            return _render_task_form(task, users, request.form, sel)

        task.title = title
        task.description = request.form.get("description", "").strip()
        task.status = status
        _log_status(task, task.status)  # 変更されていれば履歴に記録
        # 計画系の項目(優先度/開始日/期限/規模/担当者)はマネージャーのみ変更可。
        # メンバーは担当タスクの状況・内容・成果のみ更新でき、既存値を保持する。
        if current_user.is_manager:
            task.priority = request.form.get("priority") or task.priority
            task.start_date = _parse_due_date(request.form.get("start_date"))
            task.due_date = _parse_due_date(request.form.get("due_date"))
            task.scale = _read_scale()
            task.assignees = _selected_assignees(users)
        _apply_outcomes(task, data)
        db.session.commit()
        flash("タスクを更新しました。", "success")
        return redirect(url_for("tasks.detail", task_id=task.id))

    return _render_task_form(task, users, None, [u.id for u in task.assignees])


@tasks_bp.route("/<int:task_id>/status", methods=["POST"])
@login_required
def update_status(task_id):
    """一覧/詳細からワンクリックでステータスを変更する。"""
    task = db.session.get(Task, task_id)
    if task is None:
        abort(404)
    if not _can_edit(task):
        flash("このタスクを更新する権限がありません。", "danger")
        return redirect(request.referrer or url_for("tasks.list_tasks"))

    new_status = request.form.get("status")
    if new_status in STATUS_CHOICES:
        if new_status == STATUS_DONE and task.status != STATUS_DONE and not task.has_outcome_actual:
            flash(_COMPLETE_NEEDS_OUTCOME + "(タスクの編集画面から入力できます)", "warning")
        else:
            task.status = new_status
            _log_status(task, new_status)  # 変更日を履歴に記録(ガントの色分けに使用)
            db.session.commit()
            flash(f"ステータスを「{new_status}」に変更しました。", "success")
    return redirect(request.referrer or url_for("tasks.list_tasks"))


@tasks_bp.route("/<int:task_id>/comment", methods=["POST"])
@login_required
def add_comment(task_id):
    """進捗状況の記載。担当者・作成者・マネージャーのみ(担当外のメンバーは不可)。"""
    task = db.session.get(Task, task_id)
    if task is None:
        abort(404)
    if not _can_edit(task):
        flash("進捗状況を記載できるのは担当者・マネージャーのみです。", "danger")
        return redirect(url_for("tasks.detail", task_id=task.id))
    body = request.form.get("body", "").strip()
    if body:
        db.session.add(
            TaskComment(task_id=task.id, user_id=current_user.id, body=body)
        )
        db.session.commit()
    return redirect(url_for("tasks.detail", task_id=task.id))


def _can_edit_comment(comment):
    """進捗状況の記載内容を変更できるか:記載者本人・マネージャーのみ。

    進捗状況は「誰が何をしたか」の記録なので、他人の記載は書き換えさせない。
    """
    return current_user.is_manager or comment.user_id == current_user.id


@tasks_bp.route("/<int:task_id>/comment/<int:comment_id>/edit", methods=["POST"])
@login_required
def edit_comment(task_id, comment_id):
    """進捗状況の記載内容を変更する。記載者本人・マネージャーのみ。"""
    task = db.session.get(Task, task_id)
    if task is None:
        abort(404)
    comment = db.session.get(TaskComment, comment_id)
    if comment is None or comment.task_id != task.id:
        abort(404)
    if not _can_edit_comment(comment):
        flash("進捗状況を変更できるのは記載者本人・マネージャーのみです。", "danger")
        return redirect(url_for("tasks.detail", task_id=task.id))

    body = request.form.get("body", "").strip()
    if not body:
        flash("進捗状況の内容を入力してください。", "danger")
    else:
        comment.body = body
        db.session.commit()
        flash("進捗状況を更新しました。", "success")
    return redirect(url_for("tasks.detail", task_id=task.id))


@tasks_bp.route("/<int:task_id>/delete", methods=["POST"])
@login_required
def delete_task(task_id):
    task = db.session.get(Task, task_id)
    if task is None:
        abort(404)
    # 削除はマネージャーのみ(担当メンバーは編集・状態変更は可、削除は不可)
    if not current_user.is_manager:
        flash("タスクを削除できるのはマネージャーのみです。", "danger")
        return redirect(url_for("tasks.detail", task_id=task.id))

    db.session.delete(task)
    db.session.commit()
    flash("タスクを削除しました。", "info")
    return redirect(url_for("tasks.list_tasks"))
