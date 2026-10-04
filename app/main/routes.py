"""トップページ(ダッシュボード)のルーティング。

活動状況・ガントチャート・成果は、マネージャーダッシュボードと同じ集計処理を
「自分の担当分だけ」に絞って再利用している(app/manager/routes.py の _build_*)。
"""
from datetime import date

from flask import Blueprint, render_template
from flask_login import login_required, current_user

from app.utils import get_active_users
from app.models.user import User
from app.models.task import (
    Task,
    STATUS_TODO,
    STATUS_DOING,
    STATUS_HOLD,
    STATUS_DONE,
    STATUS_CHOICES,
    PRIORITY_CHOICES,
)
from app.manager.routes import _build_activity, _build_gantt, _build_outcomes

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
@login_required
def dashboard():
    # ---- タスク ----
    # 自分が担当(複数割り当ての1人)で未完了のタスク
    my_tasks = (
        Task.query.filter(
            Task.assignees.any(User.id == current_user.id),
            Task.status != STATUS_DONE,
        )
        .order_by(Task.due_date.is_(None), Task.due_date.asc())
        .all()
    )
    my_overdue = [t for t in my_tasks if t.is_overdue]

    # ステータス別の件数: 全体数 と 自分の担当数(例 4(1))
    statuses = [STATUS_TODO, STATUS_DOING, STATUS_HOLD, STATUS_DONE]
    status_counts = {s: Task.query.filter_by(status=s).count() for s in statuses}
    my_status_counts = {
        s: Task.query.filter(
            Task.assignees.any(User.id == current_user.id), Task.status == s
        ).count()
        for s in statuses
    }

    # ---- 自分の分だけの 活動状況 / 成果 / ガントチャート ----
    today = date.today()
    me = current_user._get_current_object()
    actx = _build_activity(today, [me], include_unassigned=False)
    # 成果の按分(担当者数で割る)を全体と揃えるため、母集団は有効ユーザー全員を渡す
    octx = _build_outcomes(today, get_active_users(), only_user_id=me.id)
    gctx = _build_gantt(today, only_user_id=me.id)

    return render_template(
        "main/dashboard.html",
        my_tasks=my_tasks,
        my_overdue=my_overdue,
        status_counts=status_counts,
        my_status_counts=my_status_counts,
        status_choices=STATUS_CHOICES,
        priority_choices=PRIORITY_CHOICES,
        # ガント(自分の担当のみ)。リンク・フォームは他セクションの期間も保持する
        gantt_endpoint="main.dashboard",
        gantt_extra={
            "afrom": actx["act_from"].strftime("%Y-%m-%d"),
            "ato": actx["act_to"].strftime("%Y-%m-%d"),
            "ofrom": octx["o_from"].strftime("%Y-%m-%d"),
            "oto": octx["o_to"].strftime("%Y-%m-%d"),
        },
        **actx,
        **octx,
        **gctx,
    )
