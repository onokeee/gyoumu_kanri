"""アプリケーションファクトリ。

create_app() でFlaskアプリを生成・設定する。
新しい機能は、対応するBlueprintを作って
ここで register_blueprint するだけで追加できる。

設定の読み込み順:
  1. app/config.py の Config(固定設定と、環境ごとの設定の既定値)
  2. instance/config.py(環境ごとの実際の値。無ければ初回に自動作成)
instance/config.py は、マネージャーが画面(システム設定の「基本設定」タブ)からも変更できる
(app/system/。再起動が不要な項目は保存と同時に app.config にも反映される)。
"""
import os
import secrets

from flask import Flask

from app.config import Config
from app.extensions import db, login_manager
from app.instance_config import CONFIG_FILENAME, ensure_instance_config


def _ensure_secret_key(app):
    """SECRET_KEY が空なら、このプロセス限りのランダムな鍵を使う。

    鍵は起動のたびに変わるため、再起動するとログイン状態が切れる。
    instance/config.py に SECRET_KEY を記入すれば固定される
    (システム設定の「基本設定」タブの「新しいキーを生成」でも記入できる)。
    一時的な鍵を使っていることは app.extensions["secret_key_temporary"] に控える
    (システム設定の画面で、ファイルの値と実行中の値の違いを正しく判定するため)。
    """
    if app.config.get("SECRET_KEY"):
        return
    app.config["SECRET_KEY"] = secrets.token_hex(32)
    app.extensions["secret_key_temporary"] = True
    app.logger.warning(
        "SECRET_KEY が未設定のため、一時的な鍵で起動します（再起動でログアウトされます）。"
        "instance/%s に SECRET_KEY を設定してください。", CONFIG_FILENAME
    )


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)
    # 既定値の控え(システム設定の画面で、instance/config.py に無い項目の値として使う)
    app.extensions["config_defaults"] = {
        name: getattr(config_class, name) for name in dir(config_class) if name.isupper()
    }

    # instance フォルダ(SQLiteのDBファイル・環境ごとの設定ファイル置き場)を用意
    os.makedirs(app.instance_path, exist_ok=True)

    # 環境ごとの設定(instance/config.py)を読み込む。無ければ初回のみ自動作成する
    ensure_instance_config(app.instance_path)
    app.config.from_pyfile(CONFIG_FILENAME, silent=True)
    _ensure_secret_key(app)

    db_path = os.path.join(app.instance_path, "app.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"

    # 拡張の初期化
    db.init_app(app)
    login_manager.init_app(app)

    # モデルを読み込む(create_all でテーブルを認識させるため)
    from app import models  # noqa: F401

    # Blueprint 登録
    from app.auth.routes import auth_bp
    from app.main.routes import main_bp
    from app.tasks.routes import tasks_bp
    from app.routine.routes import routine_bp
    from app.leaves.routes import leaves_bp
    from app.skills.routes import skills_bp
    from app.manager.routes import manager_bp
    from app.departments.routes import departments_bp
    from app.export.routes import export_bp
    from app.weekly.routes import weekly_bp
    from app.overdue.routes import overdue_bp
    from app.skilltest.routes import skilltest_bp
    from app.system.routes import system_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(tasks_bp)
    app.register_blueprint(routine_bp)
    app.register_blueprint(leaves_bp)
    app.register_blueprint(skills_bp)
    # スキルテスト(メンバーが受験し到達度を自動登録。管理画面はマネージャーのみ)
    app.register_blueprint(skilltest_bp)
    app.register_blueprint(manager_bp)
    app.register_blueprint(departments_bp)
    app.register_blueprint(export_bp)
    # 定期メール(週報・期限超過通知)は画面だけを登録する。
    # 自動送信のスケジューラ(app/scheduler.py)はここでは起動しない(serve.py だけが起動)
    app.register_blueprint(weekly_bp)
    app.register_blueprint(overdue_bp)
    # システム設定(マネージャーのみ。基本設定・週報・期限超過通知・スキルテストの設定を1画面で変更)
    app.register_blueprint(system_bp)

    # テンプレートで使う共通変数
    @app.context_processor
    def inject_globals():
        return {"app_name": app.config.get("APP_NAME", "業務管理")}

    # 初回起動時にテーブルが無ければ作成
    with app.app_context():
        db.create_all()

    return app
