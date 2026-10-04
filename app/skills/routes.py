"""スキル管理のルーティング。

スキルの閲覧・編集はいずれもマネージャーのみ(メンバーは before_request で403)。
スキルマップ(マトリクス)、個人スキル、項目定義、到達度の設定を扱う。
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
from app.models.user import User, ROLE_MEMBER
from app.models.skill import (
    Skill,
    SkillRating,
    SKILL_TYPE_CHOICES,
    SKILL_TYPE_LABELS,
    SKILL_TYPE_COLORS,
    SKILL_LEVEL_COLORS,
    SKILL_TECHNICAL,
    SKILL_PROFICIENT_LEVEL,
    scale_for,
)
from app.models.operation import Operation, OperationSkill

skills_bp = Blueprint("skills", __name__, url_prefix="/skills")

# スキルマップの「全スキル」タブ用の擬似区分値(全区分をまとめて表示)
SKILL_TYPE_ALL = "all"

# スキルマップの横軸に表示できる列(ヒト / 業務。両方同時表示も可)
AXIS_PERSON = "person"
AXIS_OPERATION = "operation"


@skills_bp.before_request
@login_required
def _restrict_to_managers():
    """スキル管理はマネージャーのみ。メンバーは一切アクセス不可(403)。"""
    if not current_user.is_manager:
        abort(403)


def _can_edit_skill():
    """スキル項目の定義・到達度の編集はマネージャー。"""
    return current_user.is_leader


def _skill_users():
    """スキル管理の対象者(メンバーのみ)。

    manager権限のユーザーは評価・育成の対象外なので、スキルマップの列や
    業務×ヒトの対応表には出さない。
    """
    return (
        User.query.filter_by(is_active=True, role=ROLE_MEMBER)
        .order_by(User.display_name)
        .all()
    )


def _is_skill_target(user):
    """その人がスキル管理の対象か(メンバーかつ有効)。"""
    return user is not None and user.is_active and user.role == ROLE_MEMBER


def _active_skills(skill_type):
    return (
        Skill.query.filter_by(skill_type=skill_type, is_active=True)
        .order_by(Skill.sort_order, Skill.name)
        .all()
    )


def _view_skills(skill_type):
    """表示対象の有効スキル(全スキル時は3区分すべて、それ以外は選択区分のみ)。"""
    types = SKILL_TYPE_CHOICES if skill_type == SKILL_TYPE_ALL else [skill_type]
    result = []
    for t in types:
        result.extend(_active_skills(t))
    return result


def _active_operations():
    return (
        Operation.query.filter_by(is_active=True)
        .order_by(Operation.sort_order, Operation.name)
        .all()
    )


# --------------------------------------------------------------------------- #
# スキルマップ(マトリクス)
# --------------------------------------------------------------------------- #
@skills_bp.route("/")
@login_required
def list_skills():
    # 既定は「全スキル」(一番左のタブ)。個別区分は ?type=<区分> で表示。
    skill_type = request.args.get("type", SKILL_TYPE_ALL)
    if skill_type != SKILL_TYPE_ALL and skill_type not in SKILL_TYPE_CHOICES:
        skill_type = SKILL_TYPE_ALL
    is_all = skill_type == SKILL_TYPE_ALL

    # 横軸に表示する列(ヒト・業務を任意に組み合わせ。既定はヒトのみ)
    show = [s for s in request.args.getlist("show") if s in (AXIS_PERSON, AXIS_OPERATION)]
    if not show:
        show = [AXIS_PERSON]
    show_person = AXIS_PERSON in show
    show_op = AXIS_OPERATION in show

    # 行=スキル項目。全スキル時は3区分すべてを順に、それ以外は選択区分のみ。
    view_types = SKILL_TYPE_CHOICES if is_all else [skill_type]
    groups = []
    all_skill_ids = []
    for t in view_types:
        sk = _active_skills(t)
        all_skill_ids.extend(s.id for s in sk)
        groups.append({
            "type": t,
            "label": SKILL_TYPE_LABELS[t],
            "color": SKILL_TYPE_COLORS.get(t, "secondary"),
            "scale": scale_for(t),
            "skills": sk,
        })

    # 業務列(横軸=業務): {skill_id: {op_id: 必要レベル}}
    operations = _active_operations() if show_op else []
    req_by_skill = {sid: {} for sid in all_skill_ids}
    if show_op and all_skill_ids:
        for r in OperationSkill.query.filter(
            OperationSkill.skill_id.in_(all_skill_ids)
        ).all():
            if r.skill_id in req_by_skill:
                req_by_skill[r.skill_id][r.operation_id] = r.level

    # ヒト列(横軸=ヒト): {skill_id: {user_id: SkillRating}}
    users = _skill_users() if show_person else []
    level_by_skill = {sid: {} for sid in all_skill_ids}
    if show_person and all_skill_ids:
        for r in SkillRating.query.filter(
            SkillRating.skill_id.in_(all_skill_ids)
        ).all():
            if r.skill_id in level_by_skill:
                level_by_skill[r.skill_id][r.user_id] = r

    # 「単独可」の人数もスキル管理の対象者(メンバー)だけで数える
    target_ids = {u.id for u in users}
    holder_counts = {
        sid: sum(
            1 for uid, r in per.items()
            if uid in target_ids and r.level >= SKILL_PROFICIENT_LEVEL
        )
        for sid, per in level_by_skill.items()
    }

    return render_template(
        "skills/map.html",
        skill_type=skill_type,
        is_all=is_all,
        all_type=SKILL_TYPE_ALL,
        type_choices=SKILL_TYPE_CHOICES,
        type_labels=SKILL_TYPE_LABELS,
        groups=groups,
        show=show,
        show_person=show_person,
        show_op=show_op,
        axis_person=AXIS_PERSON,
        axis_operation=AXIS_OPERATION,
        operations=operations,
        req_by_skill=req_by_skill,
        users=users,
        level_by_skill=level_by_skill,
        holder_counts=holder_counts,
        level_colors=SKILL_LEVEL_COLORS,
        proficient=SKILL_PROFICIENT_LEVEL,
        can_edit=_can_edit_skill(),
    )


@skills_bp.route("/operations/<int:op_id>/edit", methods=["GET", "POST"])
@login_required
def edit_operation(op_id):
    """業務ごとの必要スキル(ヒトと同じ到達尺度のレベル)を設定する(マネージャー)。"""
    op = db.session.get(Operation, op_id)
    if op is None:
        abort(404)
    if not _can_edit_skill():
        flash("業務の必要スキルを編集する権限がありません(マネージャー)。", "danger")
        return redirect(url_for("skills.list_skills", show=[AXIS_OPERATION]))

    all_skills = []
    for stype in SKILL_TYPE_CHOICES:
        all_skills.extend(_active_skills(stype))

    if request.method == "POST":
        for s in all_skills:
            raw = request.form.get(f"level_{s.id}", "")
            level = int(raw) if raw.isdigit() else 0
            level = max(0, min(level, s.max_level))
            req = op.req_for(s)
            if level == 0:
                # 不要(レベル0)は行を作らない(既存があれば削除=スパース維持)
                if req is not None:
                    db.session.delete(req)
                continue
            if req is None:
                req = OperationSkill(operation_id=op.id, skill_id=s.id)
                db.session.add(req)
            req.level = level
        db.session.commit()
        flash(f"業務「{op.name}」の必要スキルを更新しました。", "success")
        return redirect(url_for("skills.list_skills", show=[AXIS_OPERATION]))

    by_type = {}
    for stype in SKILL_TYPE_CHOICES:
        by_type[stype] = [(s, op.req_for(s)) for s in _active_skills(stype)]

    return render_template(
        "skills/operation_edit.html",
        operation=op,
        by_type=by_type,
        type_choices=SKILL_TYPE_CHOICES,
        type_labels=SKILL_TYPE_LABELS,
    )


@skills_bp.route("/coverage")
@login_required
def coverage():
    """別の見方: 縦=業務、横=ヒト。各ヒトがその業務に対応できるか(必要スキル充足)。"""
    operations = _active_operations()
    users = _skill_users()

    # 必要スキルの到達度を lookup 化: (user_id, skill_id) -> level
    req_skill_ids = {r.skill_id for op in operations for r in op.skill_reqs}
    level_lookup = {}
    if req_skill_ids:
        for sr in SkillRating.query.filter(
            SkillRating.skill_id.in_(req_skill_ids)
        ).all():
            level_lookup[(sr.user_id, sr.skill_id)] = sr.level

    rows = []
    for op in operations:
        reqs = op.skill_reqs  # level>=1 のみ
        cells = []
        doable = 0
        for u in users:
            if not reqs:
                cells.append({"state": "none"})
                continue
            met = sum(
                1 for r in reqs
                if level_lookup.get((u.id, r.skill_id), 0) >= r.level
            )
            full = met == len(reqs)
            if full:
                doable += 1
            cells.append({
                "state": "full" if full else "partial",
                "met": met, "total": len(reqs),
            })
        rows.append({"op": op, "req_count": len(reqs), "cells": cells, "doable": doable})

    # ヒト別 対応可能な業務数(フッター用)
    per_user_doable = [
        sum(1 for row in rows if row["cells"][i].get("state") == "full")
        for i in range(len(users))
    ]

    return render_template(
        "skills/coverage.html",
        operations=operations,
        users=users,
        rows=rows,
        per_user_doable=per_user_doable,
        can_edit=_can_edit_skill(),
    )


# --------------------------------------------------------------------------- #
# メンバー個人のスキル
# --------------------------------------------------------------------------- #
@skills_bp.route("/member/<int:user_id>")
@login_required
def member(user_id):
    member = db.session.get(User, user_id)
    if member is None:
        abort(404)
    if not _is_skill_target(member):
        # manager権限のユーザーはスキル管理の対象外
        flash("マネージャーはスキル管理の対象外です。", "info")
        return redirect(url_for("skills.list_skills"))

    # 区分ごとに (skill, rating) を整理
    by_type = {}
    for stype in SKILL_TYPE_CHOICES:
        rows = []
        for s in _active_skills(stype):
            rows.append((s, s.rating_for(member)))
        by_type[stype] = rows

    # --- 育成計画: 業務ごとの必要スキルに対する本人の過不足 ---
    current = {
        sr.skill_id: sr.level
        for sr in SkillRating.query.filter_by(user_id=member.id).all()
    }
    op_rows = []
    need = {}  # skill_id -> 育成が必要なスキルの集約
    for op in _active_operations():
        reqs = sorted(
            op.skill_reqs,
            key=lambda r: (r.skill.skill_type, r.skill.sort_order, r.skill.name),
        )
        if not reqs:
            continue  # 必要スキル未設定の業務は対象外
        lines = []
        unmet = 0
        for r in reqs:
            cur = current.get(r.skill_id, 0)
            gap = cur - r.level  # 負=不足
            met = gap >= 0
            if not met:
                unmet += 1
                e = need.get(r.skill_id)
                if e is None:
                    e = need[r.skill_id] = {
                        "skill": r.skill, "target": 0, "current": cur, "ops": [],
                    }
                e["target"] = max(e["target"], r.level)  # 複数業務なら最大の必要レベル
                e["ops"].append(op.name)
            lines.append({
                "skill": r.skill, "required": r.level,
                "current": cur, "gap": gap, "met": met,
            })
        op_rows.append({
            "op": op, "lines": lines, "unmet": unmet,
            "can_do": unmet == 0, "total": len(reqs),
        })

    for e in need.values():
        e["gap"] = e["current"] - e["target"]  # 負の不足量
    training = sorted(
        need.values(),
        key=lambda e: (e["gap"], e["skill"].skill_type, e["skill"].name),
    )
    doable = sum(1 for row in op_rows if row["can_do"])

    return render_template(
        "skills/member.html",
        member=member,
        by_type=by_type,
        type_choices=SKILL_TYPE_CHOICES,
        type_labels=SKILL_TYPE_LABELS,
        op_rows=op_rows,
        training=training,
        doable=doable,
        op_total=len(op_rows),
        can_edit=_can_edit_skill(),
    )


@skills_bp.route("/member/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
def edit_member(user_id):
    member = db.session.get(User, user_id)
    if member is None:
        abort(404)
    if not _is_skill_target(member):
        # manager権限のユーザーはスキル管理の対象外
        flash("マネージャーはスキル管理の対象外です。", "info")
        return redirect(url_for("skills.list_skills"))
    if not _can_edit_skill():
        flash("スキル到達度を編集する権限がありません(マネージャー)。", "danger")
        return redirect(url_for("skills.member", user_id=user_id))

    # 全区分の有効スキルをまとめて編集
    all_skills = []
    for stype in SKILL_TYPE_CHOICES:
        all_skills.extend(_active_skills(stype))

    if request.method == "POST":
        for s in all_skills:
            raw = request.form.get(f"level_{s.id}", "")
            note = (request.form.get(f"note_{s.id}", "") or "").strip()
            level = int(raw) if raw.isdigit() else 0
            level = max(0, min(level, s.max_level))

            rating = s.rating_for(member)
            if level == 0 and not note:
                # 未習得かつメモ無し → スパース維持(既存があれば削除)
                if rating is not None:
                    db.session.delete(rating)
                continue
            if rating is None:
                rating = SkillRating(skill_id=s.id, user_id=member.id)
                db.session.add(rating)
            rating.level = level
            rating.note = note
            rating.rated_by_id = current_user.id
        db.session.commit()
        flash(f"{member.display_name} さんのスキル到達度を更新しました。", "success")
        return redirect(url_for("skills.member", user_id=member.id))

    by_type = {}
    for stype in SKILL_TYPE_CHOICES:
        by_type[stype] = [(s, s.rating_for(member)) for s in _active_skills(stype)]

    return render_template(
        "skills/member_edit.html",
        member=member,
        by_type=by_type,
        type_choices=SKILL_TYPE_CHOICES,
        type_labels=SKILL_TYPE_LABELS,
    )


# --------------------------------------------------------------------------- #
# スキル項目の管理(マネージャー)
# --------------------------------------------------------------------------- #
@skills_bp.route("/items")
@login_required
def items():
    if not _can_edit_skill():
        flash("スキル項目を管理する権限がありません(マネージャー)。", "danger")
        return redirect(url_for("skills.list_skills"))
    skills = Skill.query.order_by(
        Skill.skill_type, Skill.sort_order, Skill.name
    ).all()
    return render_template(
        "skills/items.html",
        skills=skills,
        type_labels=SKILL_TYPE_LABELS,
        proficient=SKILL_PROFICIENT_LEVEL,
    )


@skills_bp.route("/items/new", methods=["GET", "POST"])
@login_required
def new_item():
    if not _can_edit_skill():
        flash("スキル項目を作成する権限がありません(マネージャー)。", "danger")
        return redirect(url_for("skills.list_skills"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("スキル名は必須です。", "danger")
            return render_template(
                "skills/item_form.html", skill=None,
                type_choices=SKILL_TYPE_CHOICES, type_labels=SKILL_TYPE_LABELS,
                form=request.form,
            )
        stype = request.form.get("skill_type")
        if stype not in SKILL_TYPE_CHOICES:
            stype = SKILL_TECHNICAL
        order_raw = request.form.get("sort_order", "0")
        skill = Skill(
            name=name,
            skill_type=stype,
            category=request.form.get("category", "").strip(),
            description=request.form.get("description", "").strip(),
            sort_order=int(order_raw) if order_raw.lstrip("-").isdigit() else 0,
        )
        db.session.add(skill)
        db.session.commit()
        flash("スキル項目を追加しました。", "success")
        return redirect(url_for("skills.items"))

    return render_template(
        "skills/item_form.html", skill=None,
        type_choices=SKILL_TYPE_CHOICES, type_labels=SKILL_TYPE_LABELS, form=None,
    )


@skills_bp.route("/items/<int:skill_id>/edit", methods=["GET", "POST"])
@login_required
def edit_item(skill_id):
    if not _can_edit_skill():
        flash("スキル項目を編集する権限がありません(マネージャー)。", "danger")
        return redirect(url_for("skills.list_skills"))
    skill = db.session.get(Skill, skill_id)
    if skill is None:
        abort(404)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("スキル名は必須です。", "danger")
            return render_template(
                "skills/item_form.html", skill=skill,
                type_choices=SKILL_TYPE_CHOICES, type_labels=SKILL_TYPE_LABELS,
                form=request.form,
            )
        # skill_type は到達度との整合のため変更不可(表示のみ)
        skill.name = name
        skill.category = request.form.get("category", "").strip()
        skill.description = request.form.get("description", "").strip()
        order_raw = request.form.get("sort_order", "0")
        skill.sort_order = int(order_raw) if order_raw.lstrip("-").isdigit() else 0
        db.session.commit()
        flash("スキル項目を更新しました。", "success")
        return redirect(url_for("skills.items"))

    return render_template(
        "skills/item_form.html", skill=skill,
        type_choices=SKILL_TYPE_CHOICES, type_labels=SKILL_TYPE_LABELS, form=None,
    )


@skills_bp.route("/items/<int:skill_id>/toggle", methods=["POST"])
@login_required
def toggle_item(skill_id):
    if not _can_edit_skill():
        flash("権限がありません(マネージャー)。", "danger")
        return redirect(url_for("skills.list_skills"))
    skill = db.session.get(Skill, skill_id)
    if skill is None:
        abort(404)
    skill.is_active = not skill.is_active
    db.session.commit()
    flash(
        f"「{skill.name}」を{'有効' if skill.is_active else '無効'}にしました。", "info"
    )
    return redirect(url_for("skills.items"))


# --------------------------------------------------------------------------- #
# 業務(Operation)項目の管理(マネージャー)。横軸「業務」ビューの列に使う。
# --------------------------------------------------------------------------- #
@skills_bp.route("/operations")
@login_required
def operations():
    if not _can_edit_skill():
        flash("業務項目を管理する権限がありません(マネージャー)。", "danger")
        return redirect(url_for("skills.list_skills"))
    ops = Operation.query.order_by(Operation.sort_order, Operation.name).all()
    return render_template("skills/operations.html", operations=ops)


@skills_bp.route("/operations/new", methods=["POST"])
@login_required
def new_operation():
    if not _can_edit_skill():
        flash("業務項目を作成する権限がありません(マネージャー)。", "danger")
        return redirect(url_for("skills.list_skills"))
    name = request.form.get("name", "").strip()
    if not name:
        flash("業務名を入力してください。", "danger")
    elif Operation.query.filter_by(name=name).first():
        flash("同じ名称の業務が既にあります。", "warning")
    else:
        order_raw = request.form.get("sort_order", "0")
        db.session.add(Operation(
            name=name,
            description=request.form.get("description", "").strip() or None,
            sort_order=int(order_raw) if order_raw.lstrip("-").isdigit() else 0,
        ))
        db.session.commit()
        flash(f"業務「{name}」を追加しました。", "success")
    return redirect(url_for("skills.operations"))


@skills_bp.route("/operations/<int:op_id>/rename", methods=["POST"])
@login_required
def rename_operation(op_id):
    if not _can_edit_skill():
        flash("業務項目を編集する権限がありません(マネージャー)。", "danger")
        return redirect(url_for("skills.list_skills"))
    op = db.session.get(Operation, op_id)
    if op is None:
        abort(404)
    name = request.form.get("name", "").strip()
    if not name:
        flash("業務名を入力してください。", "danger")
    else:
        other = Operation.query.filter_by(name=name).first()
        if other and other.id != op.id:
            flash("同じ名称の業務が既にあります。", "warning")
        else:
            op.name = name
            op.description = request.form.get("description", "").strip() or None
            order_raw = request.form.get("sort_order", str(op.sort_order))
            op.sort_order = int(order_raw) if order_raw.lstrip("-").isdigit() else op.sort_order
            db.session.commit()
            flash("業務を更新しました。", "success")
    return redirect(url_for("skills.operations"))


@skills_bp.route("/operations/<int:op_id>/toggle", methods=["POST"])
@login_required
def toggle_operation(op_id):
    if not _can_edit_skill():
        flash("権限がありません(マネージャー)。", "danger")
        return redirect(url_for("skills.list_skills"))
    op = db.session.get(Operation, op_id)
    if op is None:
        abort(404)
    op.is_active = not op.is_active
    db.session.commit()
    flash(f"業務「{op.name}」を{'有効' if op.is_active else '無効'}にしました。", "info")
    return redirect(url_for("skills.operations"))
