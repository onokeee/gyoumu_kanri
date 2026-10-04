"""ユーザーモデル。

認証はLDAP-APIで行う想定のため、パスワードはこのテーブルには保存しない。
LDAPで認証成功したユーザーの情報(表示名・役割)をミラーリングして保持する。
組織のグルーピングは「チーム」(Department モデル＋user_departments 多対多)のみで管理する。
"""
from datetime import datetime

from flask_login import UserMixin

from app.extensions import db, login_manager

# 役割(ロール)は マネージャー / メンバー の2種類。マネージャーが全機能を利用できる。
ROLE_MANAGER = "manager"  # マネージャー:全機能(スキル/各ダッシュボード/チーム管理など)
ROLE_MEMBER = "member"    # メンバー:一般利用

ROLE_LABELS = {
    ROLE_MANAGER: "manager",
    ROLE_MEMBER: "member",
}


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    # LDAPのログインID(ユーザーIDやアカウント名)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(16), nullable=False, default=ROLE_MEMBER)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

    # リレーション(タスク)
    created_tasks = db.relationship(
        "Task", foreign_keys="Task.creator_id", back_populates="creator"
    )
    # 担当タスク(複数割り当て対応の多対多)
    assigned_tasks = db.relationship(
        "Task", secondary="task_assignees", back_populates="assignees"
    )

    # リレーション(年休)。本人として申請したもの(承認者としての分は含まない)
    leave_requests = db.relationship(
        "LeaveRequest",
        foreign_keys="LeaveRequest.user_id",
        back_populates="user",
    )

    # 所属するチーム(兼務対応の多対多)。年休の見える化・チームマスタ管理で使う
    departments = db.relationship(
        "Department",
        secondary="user_departments",
        back_populates="users",
    )

    # リレーション(スキル到達度。評価対象としての自分)
    skill_ratings = db.relationship(
        "SkillRating",
        foreign_keys="SkillRating.user_id",
        back_populates="user",
    )

    @property
    def role_label(self):
        return ROLE_LABELS.get(self.role, self.role)

    # ロールはマネージャー/メンバーの2種類。マネージャー=全権限。
    # 既存コードの呼び出し互換のため3つのヘルパを残すが、いずれも「マネージャーかどうか」を返す。
    @property
    def is_admin(self):
        return self.role == ROLE_MANAGER

    @property
    def is_manager(self):
        return self.role == ROLE_MANAGER

    @property
    def is_leader(self):
        return self.role == ROLE_MANAGER

    @property
    def department_names(self):
        """所属するチームの名称(兼務は「、」区切り)。"""
        return "、".join(d.name for d in self.departments)

    def __repr__(self):
        return f"<User {self.username} ({self.display_name})>"


@login_manager.user_loader
def load_user(user_id):
    """Flask-Login がセッションからユーザーを復元するためのコールバック。"""
    return db.session.get(User, int(user_id))
