"""チーム(Department)の管理ルーティング。マネージャーのみ。

チームの追加・名称変更・有効/無効、および 人とチームの紐づけ(兼務対応)を管理する。
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
from app.models.user import User, ROLE_MANAGER, ROLE_MEMBER, ROLE_LABELS
from app.models.department import Department
from app.models.task import TaskComment
from app.models.routine import RoutineWork
from app.models.skill import SkillRating
from app.models.skilltest import SkillTestAttempt

departments_bp = Blueprint("departments", __name__, url_prefix="/departments")


def _require_admin():
    if not current_user.is_admin:
        abort(403)


def _member_has_history(user):
    """メンバーが業務データ(タスク/進捗/年休/スキル/スキルテスト/定型業務)を持つか。

    履歴があるユーザーは物理削除するとタスク等の参照が壊れるため、無効化に切り替える。
    """
    if user.created_tasks or user.assigned_tasks or user.leave_requests or user.skill_ratings:
        return True
    if TaskComment.query.filter_by(user_id=user.id).first():
        return True
    if SkillRating.query.filter_by(rated_by_id=user.id).first():
        return True
    if SkillTestAttempt.query.filter_by(user_id=user.id).first():
        return True
    if RoutineWork.query.filter(
        (RoutineWork.assignee_id == user.id) | (RoutineWork.creator_id == user.id)
    ).first():
        return True
    return False


@departments_bp.route("/")
@login_required
def manage():
    _require_admin()
    departments = Department.query.order_by(Department.sort_order, Department.name).all()
    users = User.query.filter_by(is_active=True).order_by(User.display_name).all()
    inactive_members = (
        User.query.filter_by(is_active=False).order_by(User.display_name).all()
    )
    # 紐づけ判定用: {dept_id: set(user_id)}
    membership = {d.id: {u.id for u in d.users} for d in departments}
    return render_template(
        "departments/manage.html",
        departments=departments,
        users=users,
        inactive_members=inactive_members,
        membership=membership,
        role_manager=ROLE_MANAGER,
        role_member=ROLE_MEMBER,
        role_labels=ROLE_LABELS,
    )


@departments_bp.route("/members/new", methods=["POST"])
@login_required
def new_member():
    """メンバー(ユーザー)を追加する。マネージャーのみ。"""
    _require_admin()
    username = request.form.get("username", "").strip()
    display_name = request.form.get("display_name", "").strip()
    role = request.form.get("role", ROLE_MEMBER)
    if role not in (ROLE_MANAGER, ROLE_MEMBER):
        role = ROLE_MEMBER

    if not username or not display_name:
        flash("ログインIDと氏名は必須です。", "danger")
    elif User.query.filter_by(username=username).first():
        flash(f"ログインID「{username}」は既に使われています。", "warning")
    else:
        db.session.add(User(
            username=username,
            display_name=display_name,
            role=role,
            is_active=True,
        ))
        db.session.commit()
        flash(f"メンバー「{display_name}」を追加しました。", "success")
    return redirect(url_for("departments.manage"))


@departments_bp.route("/members/<int:user_id>/delete", methods=["POST"])
@login_required
def delete_member(user_id):
    """メンバーを削除する。マネージャーのみ。

    業務データ(タスク・進捗・年休・スキル・定型業務)がある場合は、参照を壊さない
    よう物理削除せず「無効化」する(一覧・割り当てから外れる)。データが無ければ物理削除。
    """
    _require_admin()
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)
    if user.id == current_user.id:
        flash("自分自身は削除できません。", "warning")
        return redirect(url_for("departments.manage"))

    name = user.display_name
    if _member_has_history(user):
        # チームの紐づけを外し、無効化(履歴は保持)
        user.departments = []
        user.is_active = False
        db.session.commit()
        flash(
            f"「{name}」は業務データがあるため無効化しました(一覧・割り当てから外れます)。",
            "info",
        )
    else:
        user.departments = []
        db.session.delete(user)
        db.session.commit()
        flash(f"メンバー「{name}」を削除しました。", "success")
    return redirect(url_for("departments.manage"))


@departments_bp.route("/members/<int:user_id>/reactivate", methods=["POST"])
@login_required
def reactivate_member(user_id):
    """無効化したメンバーを復帰させる。マネージャーのみ。"""
    _require_admin()
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)
    user.is_active = True
    db.session.commit()
    flash(f"メンバー「{user.display_name}」を復帰しました。", "success")
    return redirect(url_for("departments.manage"))


@departments_bp.route("/new", methods=["POST"])
@login_required
def new_department():
    _require_admin()
    name = request.form.get("name", "").strip()
    if not name:
        flash("チームの名称を入力してください。", "danger")
    elif Department.query.filter_by(name=name).first():
        flash("同じ名称のチームが既にあります。", "warning")
    else:
        order_raw = request.form.get("sort_order", "0")
        db.session.add(Department(
            name=name,
            sort_order=int(order_raw) if order_raw.lstrip("-").isdigit() else 0,
        ))
        db.session.commit()
        flash(f"チーム「{name}」を追加しました。", "success")
    return redirect(url_for("departments.manage"))


@departments_bp.route("/<int:dept_id>/rename", methods=["POST"])
@login_required
def rename_department(dept_id):
    _require_admin()
    dept = db.session.get(Department, dept_id)
    if dept is None:
        abort(404)
    name = request.form.get("name", "").strip()
    if not name:
        flash("チームの名称を入力してください。", "danger")
    else:
        other = Department.query.filter_by(name=name).first()
        if other and other.id != dept.id:
            flash("同じ名称のチームが既にあります。", "warning")
        else:
            dept.name = name
            order_raw = request.form.get("sort_order", str(dept.sort_order))
            dept.sort_order = int(order_raw) if order_raw.lstrip("-").isdigit() else dept.sort_order
            db.session.commit()
            flash("チームを更新しました。", "success")
    return redirect(url_for("departments.manage"))


@departments_bp.route("/<int:dept_id>/toggle", methods=["POST"])
@login_required
def toggle_department(dept_id):
    _require_admin()
    dept = db.session.get(Department, dept_id)
    if dept is None:
        abort(404)
    dept.is_active = not dept.is_active
    db.session.commit()
    flash(
        f"チーム「{dept.name}」を{'有効' if dept.is_active else '無効'}にしました。", "info"
    )
    return redirect(url_for("departments.manage"))


@departments_bp.route("/memberships", methods=["POST"])
@login_required
def save_memberships():
    """人とチームの紐づけ(兼務対応)を一括保存する。"""
    _require_admin()
    users = User.query.filter_by(is_active=True).all()
    user_by_id = {u.id: u for u in users}
    for dept in Department.query.all():
        checked = request.form.getlist(f"dept_{dept.id}")
        checked_ids = {int(x) for x in checked if x.isdigit()}
        dept.users = [user_by_id[uid] for uid in checked_ids if uid in user_by_id]
    db.session.commit()
    flash("チームの紐づけを保存しました。", "success")
    return redirect(url_for("departments.manage"))
