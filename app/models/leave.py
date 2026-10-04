"""年休(有給休暇)の予定モデル。

チーム内での情報共有・見える化が目的。承認フローは持たない(登録=即共有)。
1レコード=1取得日。種別は 全休 / 午前半休 / 午後半休。
"""
from datetime import datetime

from app.extensions import db

# 同じチームで同日に休む人数がこれを超えると、登録時に調整を促すメッセージを表示
LEAVE_DAILY_LIMIT = 2

# --- 休暇種別 ---
LEAVE_FULL = "全休"
LEAVE_AM = "午前半休"
LEAVE_PM = "午後半休"
LEAVE_TYPE_CHOICES = [LEAVE_FULL, LEAVE_AM, LEAVE_PM]
LEAVE_TYPE_COLORS = {
    LEAVE_FULL: "primary",
    LEAVE_AM: "info",
    LEAVE_PM: "info",
}


class LeaveRequest(db.Model):
    __tablename__ = "leave_requests"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    leave_date = db.Column(db.Date, nullable=False, index=True)  # 取得日(単日)
    leave_type = db.Column(db.String(16), nullable=False, default=LEAVE_FULL)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    user = db.relationship(
        "User", foreign_keys=[user_id], back_populates="leave_requests"
    )

    @property
    def type_color(self):
        return LEAVE_TYPE_COLORS.get(self.leave_type, "secondary")

    @property
    def day_count(self):
        """換算取得日数。全休=1、半休=0.5。"""
        return 0.5 if self.leave_type in (LEAVE_AM, LEAVE_PM) else 1

    @property
    def date_label(self):
        return self.leave_date.strftime("%Y/%m/%d")

    def __repr__(self):
        return f"<LeaveRequest {self.id} user={self.user_id} {self.leave_date} {self.leave_type}>"
