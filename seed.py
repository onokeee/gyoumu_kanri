"""初期データ投入スクリプト。

実行: python seed.py

ダミーユーザーと、動作確認用のサンプルタスクを作成する。
※ ログイン認証自体は app/auth/ldap_client.py の DUMMY_USERS で行われる。
   このスクリプトは「画面表示・担当者割り当て」用にDBへユーザーを登録する。
"""
from datetime import date, datetime, time, timedelta

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.task import (
    Task, TaskComment, TaskStatusChange, STATUS_TODO, STATUS_DOING, STATUS_DONE,
)
from app.models.routine import (
    RoutineWork, FREQ_DAY, FREQ_WEEK, FREQ_MONTH, MANUAL_DONE, MANUAL_UNDONE,
)
from app.models.leave import LeaveRequest, LEAVE_FULL, LEAVE_AM
from app.models.department import Department
from app.models.operation import Operation
from app.models.skill import (
    Skill,
    SkillRating,
    SKILL_TECHNICAL,
    SKILL_CONCEPTUAL,
    SKILL_HUMAN,
)
from app.auth.ldap_client import _DUMMY_USERS, _LOCAL_ACCOUNTS

app = create_app()

with app.app_context():
    db.create_all()

    # --- ユーザー(固定ローカル管理者＋ダミーLDAPの顔ぶれ)をDBに登録 ---
    user_map = {}
    for username, info in {**_LOCAL_ACCOUNTS, **_DUMMY_USERS}.items():
        user = User.query.filter_by(username=username).first()
        if user is None:
            user = User(username=username)
            db.session.add(user)
        user.display_name = info["display_name"]
        user.role = info["role"]
        user.is_active = True
        user_map[username] = user
    db.session.commit()

    # --- サンプルタスク(まだ無ければ作成) ---
    if Task.query.count() == 0:
        admin = user_map["admin"]
        today = date.today()
        samples = [
            dict(title="業務チェックリストの更新",
                 description="チェック項目に確認手順を追加する。",
                 status=STATUS_DOING, priority="高", scale="3d",
                 assignees=["yamada", "tanaka"],
                 start_date=today - timedelta(days=1), due_date=today + timedelta(days=2)),
            dict(title="問い合わせ対応記録のフォーマット見直し",
                 description="現状Excel手書き。Web入力に置き換える検討。",
                 status=STATUS_TODO, priority="中", scale="2w",
                 assignees=["suzuki"],
                 start_date=today + timedelta(days=1), due_date=today + timedelta(days=7)),
            dict(title="共有フォルダの整理(命名ルール策定)",
                 description="不要ファイルを整理した後、フォルダの命名ルールを決める。",
                 status=STATUS_TODO, priority="低", scale="1w",
                 assignees=["tanaka", "suzuki"],
                 start_date=today - timedelta(days=5), due_date=today - timedelta(days=1)),
            dict(title="月次実績の集計",
                 description="先月分の実績をまとめて報告。",
                 status=STATUS_DONE, priority="中",
                 assignees=[],
                 start_date=today - timedelta(days=8), due_date=today - timedelta(days=5),
                 outcome_quant_estimate=20, outcome_quant_estimate_unit="ｈ/月",
                 outcome_quant_actual=18, outcome_quant_actual_unit="ｈ/月",
                 outcome_quant_note="集計作業をRPA化し所要時間を短縮。",
                 outcome_qual_estimate="集計の属人化を解消したい",
                 outcome_qual_actual="手順書を整備し、他メンバーでも集計可能にした"),
        ]
        first_task = None
        for s in samples:
            anames = s.pop("assignees")
            t = Task(creator_id=admin.id, **s)
            t.assignees = [user_map[a] for a in anames]
            # 初期ステータス履歴(開始日起点)。ガントの色分け・実行時作成タスクと整合させる。
            base_dt = datetime.combine(t.start_date or today, time.min)
            t.status_changes.append(TaskStatusChange(status=t.status, changed_at=base_dt))
            db.session.add(t)
            if first_task is None:
                first_task = t
        db.session.flush()
        # サンプルコメント(やり取り)
        db.session.add(TaskComment(
            task_id=first_task.id, user_id=user_map["yamada"].id,
            body="確認手順も追記しました。確認をお願いします。"))
        db.session.commit()
        print(f"サンプルタスクを {len(samples)} 件、コメント1件を作成しました。")

    # --- サンプル定型・定期業務(まだ無ければ作成) ---
    if RoutineWork.query.count() == 0:
        admin = user_map["admin"]
        routines = [
            dict(name="日次バックアップ確認", assignee="yamada", purpose="データ消失の防止",
                 frequency_count=1, frequency_unit=FREQ_DAY, minutes_per=15,
                 content="バックアップの取得状況・ディスク容量・エラー有無を確認し記録する。",
                 manual_status=MANUAL_DONE),
            dict(name="週次問い合わせ集計レポート作成", assignee="suzuki", purpose="問い合わせ傾向の把握",
                 frequency_count=1, frequency_unit=FREQ_WEEK, minutes_per=60,
                 content="問い合わせデータを集計し、傾向をまとめて共有する。",
                 manual_status=MANUAL_UNDONE),
            dict(name="月次備品棚卸し", assignee="tanaka", purpose="備品台帳の精度維持",
                 frequency_count=1, frequency_unit=FREQ_MONTH, minutes_per=120,
                 content="備品の実数を数え、管理台帳と照合する。",
                 manual_status=MANUAL_DONE),
            dict(name="共有フォルダの定期整理", assignee="yamada", purpose="ファイル管理ルールの維持",
                 frequency_count=2, frequency_unit=FREQ_WEEK, minutes_per=20,
                 content="共有フォルダの不要ファイル・命名ルール違反を確認し、整理する。",
                 manual_status=MANUAL_UNDONE),
        ]
        for r in routines:
            aname = r.pop("assignee")
            db.session.add(RoutineWork(
                creator_id=admin.id, assignee_id=user_map[aname].id, **r))
        db.session.commit()
        print(f"サンプル定型・定期業務を {len(routines)} 件作成しました。")

    # --- チーム(Department)＋メンバー紐づけ(まだ無ければ作成) ---
    if Department.query.count() == 0:
        team_a = Department(name="チームA", sort_order=1)
        team_b = Department(name="チームB", sort_order=2)
        db.session.add_all([team_a, team_b])
        db.session.flush()
        # 紐づけ(兼務あり)。tanaka は両チームを兼務。
        team_a.users = [user_map[u] for u in ("suzuki", "tanaka", "leader", "kacho", "admin")]
        team_b.users = [user_map[u] for u in ("yamada", "tanaka", "leader", "kacho", "admin")]
        db.session.commit()
        print("チームを 2 件作成し、メンバーを紐づけました(兼務: 田中)。")

    # --- サンプル年休(承認なし・単一取得日。まだ無ければ作成) ---
    if LeaveRequest.query.count() == 0:
        today = date.today()
        leaves = [
            # 同日にチームBが3名 → カレンダーで同日上限超の警告色を確認できる
            LeaveRequest(user_id=user_map["yamada"].id, leave_date=today + timedelta(days=2), leave_type=LEAVE_FULL),
            LeaveRequest(user_id=user_map["tanaka"].id, leave_date=today + timedelta(days=2), leave_type=LEAVE_FULL),
            LeaveRequest(user_id=user_map["leader"].id, leave_date=today + timedelta(days=2), leave_type=LEAVE_FULL),
            # 別日
            LeaveRequest(user_id=user_map["suzuki"].id, leave_date=today + timedelta(days=4), leave_type=LEAVE_FULL),
            LeaveRequest(user_id=user_map["tanaka"].id, leave_date=today + timedelta(days=6), leave_type=LEAVE_AM),
        ]
        for lv in leaves:
            db.session.add(lv)
        db.session.commit()
        print(f"サンプル年休を {len(leaves)} 件作成しました。")

    # --- サンプルスキル項目＋到達度(まだ無ければ作成) ---
    if Skill.query.count() == 0:
        leader = user_map["leader"]
        skills_data = [
            dict(name="Webアプリ開発", skill_type=SKILL_TECHNICAL, category="開発", sort_order=1),
            dict(name="システム設計", skill_type=SKILL_TECHNICAL, category="設計", sort_order=2),
            dict(name="Excelでのデータ集計", skill_type=SKILL_TECHNICAL, category="分析", sort_order=3),
            dict(name="サーバー・ネットワーク運用", skill_type=SKILL_TECHNICAL, category="運用", sort_order=4),
            dict(name="Pythonによる業務自動化", skill_type=SKILL_TECHNICAL, category="開発", sort_order=5),
            dict(name="SQL・データベース操作", skill_type=SKILL_TECHNICAL, category="データ", sort_order=6),
            dict(name="BIツールでのダッシュボード作成", skill_type=SKILL_TECHNICAL, category="分析", sort_order=7),
            dict(name="業務システムの操作・設定", skill_type=SKILL_TECHNICAL, category="運用", sort_order=8),
            dict(name="業務全体の課題抽出", skill_type=SKILL_CONCEPTUAL, sort_order=1),
            dict(name="施策テーマの立案", skill_type=SKILL_CONCEPTUAL, sort_order=2),
            dict(name="データに基づく現状分析", skill_type=SKILL_CONCEPTUAL, sort_order=3),
            dict(name="業務の標準化・仕組み化", skill_type=SKILL_CONCEPTUAL, sort_order=4),
            dict(name="施策効果の定量評価", skill_type=SKILL_CONCEPTUAL, sort_order=5),
            dict(name="優先順位付けと計画立案", skill_type=SKILL_CONCEPTUAL, sort_order=6),
            dict(name="メンバーへの業務指導", skill_type=SKILL_HUMAN, sort_order=1),
            dict(name="他チームとの調整", skill_type=SKILL_HUMAN, sort_order=2),
            dict(name="報告・連絡・相談(報連相)", skill_type=SKILL_HUMAN, sort_order=3),
            dict(name="会議のファシリテーション", skill_type=SKILL_HUMAN, sort_order=4),
            dict(name="新人・後輩の育成", skill_type=SKILL_HUMAN, sort_order=5),
            dict(name="関係者との合意形成", skill_type=SKILL_HUMAN, sort_order=6),
        ]
        skill_map = {}
        for d in skills_data:
            s = Skill(**d)
            db.session.add(s)
            skill_map[d["name"]] = s
        db.session.commit()

        # 到達度はスパースに(未習得=行を作らない)
        ratings = [
            ("Webアプリ開発", "yamada", 3), ("Webアプリ開発", "suzuki", 2),
            ("システム設計", "yamada", 1),
            ("Excelでのデータ集計", "suzuki", 5), ("Excelでのデータ集計", "tanaka", 2),
            ("サーバー・ネットワーク運用", "tanaka", 4),
            ("業務全体の課題抽出", "yamada", 2), ("施策テーマの立案", "suzuki", 3),
            ("メンバーへの業務指導", "yamada", 2), ("他チームとの調整", "suzuki", 1),
        ]
        for sname, uname, lv in ratings:
            db.session.add(SkillRating(
                skill_id=skill_map[sname].id, user_id=user_map[uname].id,
                level=lv, rated_by_id=leader.id))
        db.session.commit()
        print(f"サンプルスキルを {len(skills_data)} 件、到達度を {len(ratings)} 件作成しました。")

    # --- サンプル業務(Operation。横軸「業務」ビュー用。まだ無ければ作成) ---
    if Operation.query.count() == 0:
        op_names = ["勉強会", "アプリ開発", "要件定義", "要求定義",
                    "Excelマクロ開発", "業務効率化", "ドキュメント整備"]
        for i, name in enumerate(op_names, start=1):
            db.session.add(Operation(name=name, sort_order=i))
        db.session.commit()
        print(f"サンプル業務を {len(op_names)} 件作成しました。")

    print("初期データの投入が完了しました。")
    print("登録ユーザー:", ", ".join(user_map.keys()))
    print("固定ローカル管理者(admin)のパスワードは instance/config.py の "
          "ADMIN_PASSWORD を確認してください。")
