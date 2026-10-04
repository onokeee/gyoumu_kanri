"""アプリケーション設定(既定値)。

このファイルには、アプリ固有の固定設定と、環境ごとに変わる設定の
「既定値(空・中立の値)」だけを置く。ここに実際のパスワードやキーは書かない。

実際の値(秘密鍵・管理者パスワード・LDAP/AI/メールの接続先など)は
instance/config.py に記入する。instance/config.py はDB(instance/app.db)と
同じフォルダにあり、Git管理外。無ければ初回起動時にリポジトリ直下の
config.example.py をもとに自動作成される(app/instance_config.py)。

create_app() はこのクラスの値を読み込んだあと、instance/config.py の値で上書きする。
instance/config.py に書かれていない項目は、ここの既定値が使われる。
環境ごとの設定の項目は、システム設定の画面の項目の定義(app/system/config_fields.py)にも
追加すること(定義の無い項目は画面の「その他」に読み取り専用で表示される)。
"""


class Config:
    # ------------------------------------------------------------------ #
    # アプリ固有の固定設定(環境によらず共通)
    # ------------------------------------------------------------------ #
    # SQLAlchemy 設定(DBのパスは app/__init__.py で instance フォルダ基準に設定)
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # アプリのタイトル(画面表示用)
    APP_NAME = "業務管理システム"

    # セッションCookieを他のサイトからのPOST(フォーム送信・fetch など)に付けない。
    # 他サイトのページから勝手に送信・設定変更などをさせないため。
    # (メールのリンクなど、他から通常のリンクで開く場合は今まで通りログインしたまま開ける)
    SESSION_COOKIE_SAMESITE = "Lax"

    # ------------------------------------------------------------------ #
    # 環境ごとの設定(既定値)。実際の値は instance/config.py で上書きする
    # ------------------------------------------------------------------ #
    # セッション暗号化に使う秘密鍵。
    # 空のままなら起動のたびにランダムな鍵を生成する(再起動するとログアウトされる)。
    SECRET_KEY = ""

    # 固定ローカル管理者(admin)のパスワード。空なら admin でのログインは無効。
    ADMIN_PASSWORD = ""

    # LDAP-API のエンドポイント(本番のLDAP認証APIに差し替える際に使用)。
    LDAP_API_URL = ""

    # ChatGPT(OpenAI互換)API(週報の文章整形・スキルテストの問題作成)。
    # URLとキーがどちらも空ならAIは使わない。
    AI_API_URL = ""            # 空なら OpenAI公式のエンドポイントを使う
    AI_API_KEY = ""            # APIキー(キー不要の独自APIなら空のまま)
    AI_MODEL = "gpt-4o-mini"   # 使用するモデル名
    AI_TIMEOUT = 60            # タイムアウト(秒)

    # メール送信(SMTP)。送信サーバーが空ならメール送信は行えない。
    MAIL_SMTP_SERVER = ""      # 送信サーバー(ホスト名またはIPアドレス)
    MAIL_SMTP_PORT = 25        # ポート番号
    MAIL_USE_TLS = False       # True なら STARTTLS で暗号化する
    MAIL_USERNAME = ""         # 認証ユーザー名(空なら認証しない)
    MAIL_PASSWORD = ""         # 認証パスワード
    MAIL_FROM = ""             # 差出人アドレス
    MAIL_TO = []               # 宛先(To)のアドレス一覧
    MAIL_CC = []               # 宛先(Cc)のアドレス一覧
    MAIL_TEST_TO = []          # テスト送信の宛先一覧(空なら差出人 MAIL_FROM 宛て)

    # 期限超過通知(毎朝のメール)の宛先。OVERDUE_MAIL_TO が空なら MAIL_TO / MAIL_CC を使う。
    OVERDUE_MAIL_TO = []       # 宛先(To)のアドレス一覧
    OVERDUE_MAIL_CC = []       # 宛先(Cc)のアドレス一覧(OVERDUE_MAIL_TO が空のときは使わない)

    # メールに載せるリンクの基準URL(他のPCからこのアプリを開くときのURL。末尾の / は不要)。
    # 空ならメールにリンクを付けない(タスク名だけ)。
    APP_BASE_URL = ""

    # サーバー(serve.py)の待ち受けアドレス・ポート(開発用の run.py はポートのみ使用)
    SERVER_HOST = "0.0.0.0"
    SERVER_PORT = 8050
