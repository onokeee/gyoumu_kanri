"""基本設定(instance/config.py)の項目の定義。項目の定義はこのファイルの1か所だけに置く。

各項目: キー・グループ・表示名・説明・種類・再起動が必要か・秘密の値か(＋種類ごとの条件)。
新しい環境ごとの設定を app/config.py / config.example.py に追加したら、ここにも定義を追加する
(定義の無いキーは、画面の「その他」に読み取り専用で表示される)。

種類:
  text       1行の文字列(改行・制御文字は不可。pattern があればその形式だけ)
  url        http:// または https:// で始まるURL(空も可)
  int        整数(min〜max)
  bool       オン/オフ(チェックボックス)
  address    メールアドレス1件(空も可)
  addresses  メールアドレスの一覧(1行に1件。「,」「;」区切りも可)
  secret     パスワード・キー。値は画面に出さない(設定あり/未設定だけ)。
             空欄のまま保存すると変更しない。「空にする」で空にする。
             bound_to の接続先を変えるときは、入力し直すか「空にする」が必要
  secret_key セッションの秘密鍵。自由入力はなく、「新しいキーを生成」だけ
"""
import ast
import os
from dataclasses import dataclass
from typing import Optional

TYPE_TEXT = "text"
TYPE_URL = "url"
TYPE_INT = "int"
TYPE_BOOL = "bool"
TYPE_ADDRESS = "address"
TYPE_ADDRESSES = "addresses"
TYPE_SECRET = "secret"
TYPE_SECRET_KEY = "secret_key"

# グループ(画面の表示順)
GROUP_LOGIN = "login"
GROUP_LDAP = "ldap"
GROUP_AI = "ai"
GROUP_MAIL = "mail"
GROUP_RECIPIENTS = "recipients"
GROUP_OVERDUE = "overdue"
GROUP_SERVER = "server"
GROUP_OTHER = "other"

GROUPS = (
    (GROUP_LOGIN, "ログイン・セキュリティ"),
    (GROUP_LDAP, "LDAP"),
    (GROUP_AI, "AI"),
    (GROUP_MAIL, "メール送信"),
    (GROUP_RECIPIENTS, "宛先"),
    (GROUP_OVERDUE, "期限超過通知の宛先"),
    (GROUP_SERVER, "リンク・サーバー"),
)
OTHER_LABEL = "その他"

# ホスト名・IPアドレスに使える文字
_HOST_PATTERN = r"[A-Za-z0-9._:\-\[\]]+"
_HOST_HELP = "ホスト名またはIPアドレスを入力してください（空白・記号の一部は使えません）。"


@dataclass(frozen=True)
class Field:
    key: str
    group: str
    label: str
    help: str
    type: str = TYPE_TEXT
    restart_required: bool = False     # True ならファイルにだけ保存し、再起動後に反映
    secret: bool = False               # True なら値を画面・ログ・メッセージに出さない
    min: Optional[int] = None          # int の下限
    max: Optional[int] = None          # int の上限
    pattern: Optional[str] = None      # text の形式(正規表現。空欄は可)
    pattern_help: str = ""             # pattern に合わないときのメッセージ
    no_query: bool = False             # url: ?〜 や #〜 を付けられない
    confirm: bool = False              # secret: 確認のためもう一度入力する
    min_length: int = 0                # secret: 最小の文字数
    clear_warning: str = ""            # secret: 空にするときの注意
    # secret: この値を送る接続先の項目。これらを変えるときは、保存済みの値を新しい接続先へ
    # 送らないよう、値を入力し直すか「空にする」を指定してもらう
    bound_to: tuple = ()


FIELDS = (
    # ---- ログイン・セキュリティ ----
    Field(
        "SECRET_KEY", GROUP_LOGIN, "セッションの秘密鍵",
        "ログイン状態（セッション）の暗号化に使う鍵です。値は表示しません。"
        "自由には入力できず、「新しいキーを生成」で作り直します。"
        "未設定の場合は起動のたびに一時的な鍵を使います（再起動でログアウト）。",
        type=TYPE_SECRET_KEY, restart_required=True, secret=True,
    ),
    Field(
        "ADMIN_PASSWORD", GROUP_LOGIN, "固定ローカル管理者（admin）のパスワード",
        "ID「admin」でログインするときのパスワードです。値は表示しません。"
        "変更する場合だけ、新しいパスワードを2回入力してください（8文字以上）。保存するとすぐに有効になります。",
        type=TYPE_SECRET, secret=True, confirm=True, min_length=8,
        clear_warning="空にすると、admin のログイン可否は app/auth/ldap_client.py の判定に任されます"
                      "（ldap_client.py に admin 用の固定パスワードがある場合は、それでログインできるようになります）。",
    ),
    # ---- LDAP ----
    Field(
        "LDAP_API_URL", GROUP_LDAP, "LDAP認証APIのURL",
        "本番でLDAP認証APIに接続する場合のエンドポイントです（例: https://auth.example.com/ldap/auth）。"
        "この値の使い方は app/auth/ldap_client.py の実装によります"
        "（起動時に読み込む実装の場合は、変更後にサーバーの再起動が必要です）。",
        type=TYPE_URL,
    ),
    # ---- AI ----
    Field(
        "AI_API_URL", GROUP_AI, "AI APIのエンドポイント",
        "空なら OpenAI 公式のエンドポイントを使います。OpenAI互換の独自APIを使う場合に記入します"
        "（例: https://api.example.com/v1/chat/completions）。"
        "エンドポイントとAPIキーがどちらも空なら、AIは使いません（週報はルールベースで作成、"
        "スキルテストは問題プールにある問題だけで出題）。",
        type=TYPE_URL,
    ),
    Field(
        "AI_API_KEY", GROUP_AI, "APIキー",
        "OpenAI 公式を使う場合に必要です。キーが不要な独自APIなら空のままでかまいません。値は表示しません。"
        "エンドポイントの接続先（ホスト・ポート・http/https）を変えるときは、キーを入力し直すか「空にする」を指定してください。",
        type=TYPE_SECRET, secret=True, bound_to=("AI_API_URL",),
    ),
    Field(
        "AI_MODEL", GROUP_AI, "モデル名",
        "使用するモデル名です（空なら gpt-4o-mini）。独自APIの場合は利用できるモデル名にします。",
    ),
    Field(
        "AI_TIMEOUT", GROUP_AI, "タイムアウト（秒）",
        "AIの応答を待つ最大の秒数です。",
        type=TYPE_INT, min=5, max=600,
    ),
    # ---- メール送信 ----
    Field(
        "MAIL_SMTP_SERVER", GROUP_MAIL, "送信サーバー",
        "ホスト名またはIPアドレスです（例: smtp.example.com）。空ならメールは送信できません。",
        pattern=_HOST_PATTERN, pattern_help=_HOST_HELP,
    ),
    Field(
        "MAIL_SMTP_PORT", GROUP_MAIL, "ポート番号",
        "一般的には 25 / 587 などです。送信サーバーの指定に合わせます。",
        type=TYPE_INT, min=1, max=65535,
    ),
    Field(
        "MAIL_USE_TLS", GROUP_MAIL, "STARTTLS で暗号化する",
        "オンにすると STARTTLS で暗号化して送信します（サーバー証明書とホスト名を検証します。"
        "送信サーバーは証明書のホスト名と合わせてください）。",
        type=TYPE_BOOL,
    ),
    Field(
        "MAIL_USERNAME", GROUP_MAIL, "認証ユーザー名",
        "送信サーバーの認証ユーザー名です。認証が不要なら空のままにします。",
    ),
    Field(
        "MAIL_PASSWORD", GROUP_MAIL, "認証パスワード",
        "送信サーバーの認証パスワードです。値は表示しません。"
        "送信サーバー・ポート番号・認証ユーザー名を変えるときは、パスワードを入力し直すか「空にする」を指定してください。",
        type=TYPE_SECRET, secret=True,
        bound_to=("MAIL_SMTP_SERVER", "MAIL_SMTP_PORT", "MAIL_USERNAME"),
    ),
    Field(
        "MAIL_FROM", GROUP_MAIL, "差出人アドレス",
        "例: noreply@example.com",
        type=TYPE_ADDRESS,
    ),
    # ---- 宛先 ----
    Field(
        "MAIL_TO", GROUP_RECIPIENTS, "宛先（To）",
        "週報の宛先です（期限超過通知の宛先が空のときは期限超過通知にも使います）。",
        type=TYPE_ADDRESSES,
    ),
    Field(
        "MAIL_CC", GROUP_RECIPIENTS, "同報（Cc）",
        "週報の同報（Cc）です。",
        type=TYPE_ADDRESSES,
    ),
    Field(
        "MAIL_TEST_TO", GROUP_RECIPIENTS, "テスト送信の宛先",
        "テスト送信・メール接続テストの宛先です。空なら差出人アドレス宛てに送ります。",
        type=TYPE_ADDRESSES,
    ),
    # ---- 期限超過通知の宛先 ----
    Field(
        "OVERDUE_MAIL_TO", GROUP_OVERDUE, "宛先（To）",
        "期限超過通知の宛先です。空なら週報と同じ宛先（MAIL_TO / MAIL_CC）に送ります。",
        type=TYPE_ADDRESSES,
    ),
    Field(
        "OVERDUE_MAIL_CC", GROUP_OVERDUE, "同報（Cc）",
        "期限超過通知の同報（Cc）です。OVERDUE_MAIL_TO が空のときは使いません。",
        type=TYPE_ADDRESSES,
    ),
    # ---- リンク・サーバー ----
    Field(
        "APP_BASE_URL", GROUP_SERVER, "リンクの基準URL",
        "メールに載せるタスクへのリンクの基準URLです（メンバーのPCからこのアプリを開くときのURL。"
        "末尾の / は不要。例: http://192.0.2.10:8050）。空ならリンクを付けません（タスク名だけ）。",
        type=TYPE_URL, no_query=True,
    ),
    Field(
        "SERVER_HOST", GROUP_SERVER, "待ち受けアドレス",
        "python serve.py で起動したときの待ち受けアドレスです。0.0.0.0 なら同じネットワーク内の"
        "他のPCからも接続できます（空なら 0.0.0.0）。",
        restart_required=True, pattern=_HOST_PATTERN, pattern_help=_HOST_HELP,
    ),
    Field(
        "SERVER_PORT", GROUP_SERVER, "待ち受けポート",
        "python serve.py / python run.py で起動したときの待ち受けポートです。",
        type=TYPE_INT, min=1, max=65535, restart_required=True,
    ),
)

FIELD_MAP = {field.key: field for field in FIELDS}
SECRET_KEYS = tuple(field.key for field in FIELDS if field.secret)

# app/config.py の Config クラスの中で「環境ごとの設定」が始まる目印(この行より後が対象)
ENV_SECTION_MARKER = "環境ごとの設定"

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXAMPLE_PATH = os.path.join(_ROOT, "config.example.py")
APP_CONFIG_PATH = os.path.join(_ROOT, "app", "config.py")


def _parse_file(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            source = f.read()
        return source, ast.parse(source)
    except (OSError, SyntaxError, ValueError):
        return "", None


def _assigned_names(statements):
    """文の並びの中で代入している大文字の名前(出てきた順)。"""
    names = []
    for stmt in statements:
        targets = []
        if isinstance(stmt, ast.Assign):
            targets = stmt.targets
        elif isinstance(stmt, ast.AnnAssign):
            targets = [stmt.target]
        for target in targets:
            for node in ast.walk(target):
                if isinstance(node, ast.Name) and node.id.isupper():
                    names.append((node.id, stmt.lineno))
    return names


def documented_keys():
    """config.example.py と app/config.py(環境ごとの設定の部分)に出てくるキー。

    戻り値: (環境ごとの設定のキー(出てきた順), app/config.py の固定設定のキーの集合)
    """
    keys = []
    _source, tree = _parse_file(EXAMPLE_PATH)
    if tree is not None:
        keys.extend(name for name, _line in _assigned_names(tree.body))

    fixed = set()
    source, tree = _parse_file(APP_CONFIG_PATH)
    if tree is not None:
        marker = None
        for number, line in enumerate(source.splitlines(), start=1):
            if ENV_SECTION_MARKER in line and line.lstrip().startswith("#"):
                marker = number
                break
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "Config":
                for name, line in _assigned_names(node.body):
                    if marker is not None and line < marker:
                        fixed.add(name)
                    else:
                        keys.append(name)
    return list(dict.fromkeys(keys)), fixed
