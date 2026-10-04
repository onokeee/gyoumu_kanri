"""チーム(Department)モデル。

年休の見える化で使う組織区分。マネージャーが名称・メンバーの紐づけを管理する。
1人が複数のチームを兼務できるよう、User と多対多(user_departments)で持つ。
"""
from datetime import datetime

from app.extensions import db

# User ↔ Department の多対多(兼務対応)
user_departments = db.Table(
    "user_departments",
    db.Column("user_id", db.Integer, db.ForeignKey("users.id"), primary_key=True),
    db.Column("department_id", db.Integer, db.ForeignKey("departments.id"), primary_key=True),
)


class Department(db.Model):
    __tablename__ = "departments"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), nullable=False, unique=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    users = db.relationship(
        "User",
        secondary=user_departments,
        back_populates="departments",
        order_by="User.display_name",
    )

    def __repr__(self):
        return f"<Department {self.id} {self.name}>"
