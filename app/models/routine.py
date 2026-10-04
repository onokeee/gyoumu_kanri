"""定型・定期業務モデル。

各メンバーが担当している繰り返し業務(定型業務・定期業務)を管理する。
タスク(単発の作業)とは別物で、頻度・所要時間・手順書の作成状況などを持つ。
マネージャー・メンバーの全員が登録・編集できる。
"""
from datetime import datetime

from app.extensions import db

# 頻度の単位
FREQ_DAY = "日"
FREQ_WEEK = "週"
FREQ_MONTH = "月"
FREQ_UNIT_CHOICES = [FREQ_DAY, FREQ_WEEK, FREQ_MONTH]

# 手順書作成状況
MANUAL_UNDONE = "未完"
MANUAL_DONE = "完"
MANUAL_CHOICES = [MANUAL_UNDONE, MANUAL_DONE]
MANUAL_COLORS = {MANUAL_DONE: "success", MANUAL_UNDONE: "secondary"}


class RoutineWork(db.Model):
    __tablename__ = "routine_works"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)  # 業務名
    assignee_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)  # 担当者
    purpose = db.Column(db.String(300))               # 目的
    frequency_count = db.Column(db.Integer)           # 回数
    frequency_unit = db.Column(db.String(4), nullable=False, default=FREQ_MONTH)  # 頻度単位
    minutes_per = db.Column(db.Integer)               # 1回あたりの所要時間(分)
    content = db.Column(db.Text)                       # 業務内容(自由記載)
    manual_status = db.Column(
        db.String(8), nullable=False, default=MANUAL_UNDONE
    )  # 手順書作成状況(完/未完)

    creator_id = db.Column(db.Integer, db.ForeignKey("users.id"))  # 登録者
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    assignee = db.relationship("User", foreign_keys=[assignee_id])
    creator = db.relationship("User", foreign_keys=[creator_id])

    @property
    def manual_color(self):
        return MANUAL_COLORS.get(self.manual_status, "secondary")

    @property
    def is_manual_done(self):
        return self.manual_status == MANUAL_DONE

    @property
    def frequency_label(self):
        """例: 「3回/週」。回数未設定なら単位のみ。"""
        if self.frequency_count:
            return f"{self.frequency_count}回/{self.frequency_unit}"
        return f"―/{self.frequency_unit}"

    @property
    def minutes_label(self):
        return f"{self.minutes_per}分" if self.minutes_per else "―"

    # 月換算の係数(4週/月・30日/月)
    MONTH_FACTORS = {FREQ_DAY: 30, FREQ_WEEK: 4, FREQ_MONTH: 1}

    @property
    def monthly_minutes(self):
        """月あたりの所要時間(分)= 回数 × 1回所要 × 月換算係数(日30/週4/月1)。"""
        factor = self.MONTH_FACTORS.get(self.frequency_unit)
        if self.frequency_count and self.minutes_per and factor:
            return self.frequency_count * self.minutes_per * factor
        return None

    @property
    def monthly_minutes_label(self):
        m = self.monthly_minutes
        return f"{m}分" if m is not None else "―"

    def __repr__(self):
        return f"<RoutineWork {self.id}: {self.name}>"
