"""業務管理システム(チームのタスク・定型業務・スキル・年休などを一元管理する Flask アプリ)。

Python のコードはすべてこの app.py にまとめている。ほかのファイル:
  templates.html   画面テンプレート(Jinja2)・CSS・JavaScript(セクションごとに区切って1ファイル)
  ldap_client.py   LDAP認証(本番環境ごとに差し替えるファイル)
  instance/        DB(app.db)・環境ごとの設定(config.py)・画面で編集する設定(*.json)。Git管理外。
                   config.py が無ければ初回の起動時に自動作成する

起動(サーバー。定期メール〔週報・期限超過通知〕の自動送信もこのときだけ行う):
  flask --app app run --port 8050                  このPCだけで使う
  flask --app app run --host 0.0.0.0 --port 8050   同じネットワーク(LAN)の他のPCからも使う
開発・動作確認(自分のPCだけ。.py を変更すると自動で再起動する。自動送信は1つのプロセスだけが行う):
  flask --app app run --port 8050 --debug --exclude-patterns "*/instance/*"
  (--exclude-patterns を付けないと、システム設定の画面で instance/config.py を保存するたびに再起動する)
コマンド:
  flask --app app seed                             初期データ(ダミーユーザー・サンプル)の投入
  flask --app app migrate [--check] [--db パス]     既存DBを最新のモデル定義に合わせる

動作確認で差し替える関数(呼び出すたびにこのモジュールから探すので、app._now = ... で差し替えられる):
  _now()            スキルテストの時刻(3-8)
  _call_chat_api()  AI(ChatGPT互換API)の呼び出し(4-1。独自APIへの移行もここだけを書き換える)

目次(章は「# ####」、節は「# ====」の見出しで始まる):
  1. 設定(既定値・instance/config.py)
      1-1. 設定の既定値(Config)
      1-2. instance/config.py の見本(自動作成に使う)
      1-3. instance/config.py の自動作成・読み込み・画面からの更新
  2. 共通の部品
      2-1. Flask 拡張(DB・ログイン管理)
      2-2. 小さなヘルパー関数
      2-3. 画面で編集する設定(JSONファイル)の読み書き
      2-4. 営業日カレンダー(土日・祝日)
  3. モデル(DBのテーブル)
      3-1. ユーザー
      3-2. タスク
      3-3. 年休
      3-4. 定型・定期業務
      3-5. スキル
      3-6. 業務(Operation)と必要スキル
      3-7. チーム(Department)
      3-8. スキルテスト
  4. 外部との接続(AI・メール)
      4-1. ChatGPT(OpenAI互換)API クライアント
      4-2. メール送信(SMTP)
  5. 画面(Blueprint)
      5-1. 認証(ログイン/ログアウト)
      5-2. トップページ(ダッシュボード)
      5-3. タスク
      5-4. 定型・定期業務
      5-5. 年休
      5-6. スキル管理
      5-7. マネージャーダッシュボード
      5-8. チーム管理
      5-9. Excel データ出力
  6. 週報(自動作成・メール送信)
      6-1. 週報: 期間・次回実行日時・ファイル名/件名のルール
      6-2. 週報: 設定の保存・読み込み
      6-3. 週報: 設定フォーム
      6-4. 週報: 材料の収集と集計
      6-5. 週報: 文章づくり(AI整形とルールベース)
      6-6. 週報: Word(.docx)の作成
      6-7. 週報: 作成・送信のとりまとめ
      6-8. 週報: 画面
  7. 期限超過通知(毎朝のメール)
      7-1. 期限超過通知: 実行時刻の判定・次回の送信日時
      7-2. 期限超過通知: 設定の保存・読み込み
      7-3. 期限超過通知: 設定フォーム
      7-4. 期限超過通知: タスクの収集とメールの作成
      7-5. 期限超過通知: 作成・送信のとりまとめ
      7-6. 期限超過通知: 画面
  8. スキルテスト
      8-1. スキルテスト: 設定の保存・読み込み
      8-2. スキルテスト: AIによる問題の作成
      8-3. スキルテスト: 受験の流れ
      8-4. スキルテスト: 問題プールの集計と補充
      8-5. スキルテスト: 設定フォーム
      8-6. スキルテスト: 画面
  9. システム設定
      9-1. システム設定: 基本設定の項目の定義
      9-2. システム設定: 基本設定の入力チェック・保存
      9-3. システム設定: 画面
  10. 定期メールの自動送信スケジューラ
      10-1. スケジューラ(週報・期限超過通知)
      10-2. サーバーとして起動したときの開始(プロセス間で1つだけ)
  11. アプリの組み立て
      11-1. 画面テンプレート・静的ファイル(templates.html)
      11-2. create_app(アプリの作成)
  12. flask コマンド(seed / migrate)
      12-1. seed: 初期データの投入
      12-2. migrate: 既存DBを最新のモデル定義に合わせる
"""
import ast
import calendar
import codecs
import copy
import hashlib
import hmac
import json
import math
import os
import pathlib
import posixpath
import random
import re
import secrets
import shutil
import smtplib
import socket
import sqlite3
import ssl
import sys
import tempfile
import threading
import types
import unicodedata
import urllib.error
import urllib.request
from collections import namedtuple
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid, parseaddr
from functools import lru_cache
from io import BytesIO
from time import monotonic
from typing import Optional
from urllib.parse import quote, urlsplit

import click
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor
from flask import (
    Blueprint,
    Flask,
    Response,
    abort,
    current_app,
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask.cli import with_appcontext
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_sqlalchemy import SQLAlchemy
from jinja2 import BaseLoader, TemplateNotFound
from openpyxl import Workbook
from openpyxl.styles import Font
from sqlalchemy import case, func, inspect, text
from sqlalchemy.orm import selectinload


# #############################################################################
# 1. 設定(既定値・instance/config.py)
# #############################################################################


# =============================================================================
# 1-1. 設定の既定値(Config)
# =============================================================================
# このクラスには、アプリ固有の固定設定と、環境ごとに変わる設定の「既定値(空・中立の値)」だけを
# 置く。ここに実際のパスワードやキーは書かない。
#
# 実際の値(秘密鍵・管理者パスワード・LDAP/AI/メールの接続先など)は instance/config.py に記入する。
# instance/config.py はDB(instance/app.db)と同じフォルダにあり、Git管理外。無ければ初回起動時に
# 下の見本(CONFIG_TEMPLATE)をもとに自動作成される(ensure_instance_config)。
#
# create_app() はこのクラスの値を読み込んだあと、instance/config.py の値で上書きする。
# instance/config.py に書かれていない項目は、ここの既定値が使われる。
# 環境ごとの設定の項目を追加したら、見本(CONFIG_TEMPLATE)と、システム設定の画面の項目の定義
# (FIELDS)にも追加すること(定義の無い項目は画面の「その他」に読み取り専用で表示される)。
class FixedConfig:
    """アプリ固有の固定設定(環境によらず共通)。"""

    # SQLAlchemy 設定(DBのパスは prepare_instance() で instance フォルダ基準に設定)
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # アプリのタイトル(画面表示用)
    APP_NAME = "業務管理システム"

    # セッションCookieを他のサイトからのPOST(フォーム送信・fetch など)に付けない。
    # 他サイトのページから勝手に送信・設定変更などをさせないため。
    # (メールのリンクなど、他から通常のリンクで開く場合は今まで通りログインしたまま開ける)
    SESSION_COOKIE_SAMESITE = "Lax"


class Config(FixedConfig):
    """環境ごとの設定(既定値)。実際の値は instance/config.py で上書きする。"""

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


# =============================================================================
# 1-2. instance/config.py の見本(自動作成に使う)
# =============================================================================
# instance/config.py が無い状態で起動すると、この内容で作成する(ensure_instance_config)。
# そのとき SECRET_KEY と ADMIN_PASSWORD にはランダムな値を入れる。
# ここ(Git管理下)には実際のパスワード・キー・アドレスを書かないこと。
CONFIG_TEMPLATE = '''\
# =============================================================================
# 業務管理システム 環境ごとの設定ファイル
#
# ・実際に使われるのは instance/config.py (DBと同じフォルダ。Git管理外)です。
# ・instance/config.py が無い状態で起動すると、app.py の見本(CONFIG_TEMPLATE)をもとに
#   自動作成されます。そのとき SECRET_KEY と ADMIN_PASSWORD にはランダムな値が自動で入ります。
#   (既にある instance/config.py が上書きされることはありません)
# ・値を変更したら、サーバーを再起動すると反映されます。
# ・マネージャーは画面（システム設定の「基本設定」タブ）からも変更できます。
#   画面で保存すると、変更した項目の行だけが書き換わり、変更前の内容は config.py.bak に残ります
#   （SECRET_KEY 以外は、保存するとすぐに反映されます）。
# ・ここに書かれていない項目は app.py の既定値(Config)が使われます。
# ・書式は Python です。文字列は "..." で囲み、アドレスの一覧は [...] で書きます。
# =============================================================================

# -----------------------------------------------------------------------------
# セキュリティ
# -----------------------------------------------------------------------------
# セッション暗号化に使う秘密鍵(長いランダムな文字列)。
# 自動作成時にランダムな値が入ります。変更すると全員がログアウトされます。
# 空のままだと起動のたびに一時的な鍵が使われます(再起動でログアウト)。
SECRET_KEY = ""

# 固定ローカル管理者(ID: admin)のパスワード。
# 自動作成時にランダムな値が入ります。必要に応じて変更してください。
# 空にすると admin でのログインは無効になります。
ADMIN_PASSWORD = ""

# -----------------------------------------------------------------------------
# LDAP認証
# -----------------------------------------------------------------------------
# LDAP認証APIのエンドポイント(本番でLDAPに接続する場合に記入)。
# 例: "https://auth.example.com/ldap/auth"
LDAP_API_URL = ""

# -----------------------------------------------------------------------------
# ChatGPT(OpenAI互換)API  ※週報の文章整形・スキルテストの問題作成に使用
# -----------------------------------------------------------------------------
# AI_API_URL と AI_API_KEY がどちらも空なら、AIは使いません(週報はルールベースで作成、
# スキルテストは問題プールにある問題だけで出題)。
# ・OpenAI公式を使う場合      : AI_API_KEY にAPIキーを記入(AI_API_URL は空でよい)
# ・OpenAI互換の独自APIの場合 : AI_API_URL にエンドポイントを記入
#                               (キーが不要なら AI_API_KEY は空のままでよい)
# 例: AI_API_URL = "https://api.example.com/v1/chat/completions"
AI_API_URL = ""
AI_API_KEY = ""
# 使用するモデル名(独自APIの場合は利用可能なモデル名に変更)
AI_MODEL = "gpt-4o-mini"
# 応答待ちのタイムアウト(秒)
AI_TIMEOUT = 60

# -----------------------------------------------------------------------------
# メール送信(SMTP)  ※週報・期限超過通知の送信に使用
# -----------------------------------------------------------------------------
# 送信サーバー(ホスト名またはIPアドレス)。空ならメール送信は行えません。
# 例: MAIL_SMTP_SERVER = "smtp.example.com"
MAIL_SMTP_SERVER = ""
# ポート番号(一般的には 25 / 587 など。送信サーバーの指定に合わせる)
MAIL_SMTP_PORT = 25
# True にすると STARTTLS で暗号化して送信します
# (サーバー証明書とホスト名を検証します。MAIL_SMTP_SERVER は証明書のホスト名と合わせてください)
MAIL_USE_TLS = False
# 送信サーバーの認証ユーザー名とパスワード(認証不要なら空のまま)
MAIL_USERNAME = ""
MAIL_PASSWORD = ""
# 差出人アドレス
# 例: MAIL_FROM = "noreply@example.com"
MAIL_FROM = ""
# 宛先(To)・同報(Cc)のアドレス一覧
# 例: MAIL_TO = ["manager@example.com", "team@example.com"]
MAIL_TO = []
MAIL_CC = []
# テスト送信の宛先一覧(空なら差出人 MAIL_FROM 宛てに送ります)
# 例: MAIL_TEST_TO = ["you@example.com"]
MAIL_TEST_TO = []

# -----------------------------------------------------------------------------
# 期限超過通知(毎朝のメール)
# -----------------------------------------------------------------------------
# 期限超過通知の宛先(To)・同報(Cc)のアドレス一覧。
# OVERDUE_MAIL_TO が空なら、週報と同じ MAIL_TO / MAIL_CC に送ります
# (そのとき OVERDUE_MAIL_CC は使いません)。テスト送信は MAIL_TEST_TO 宛てです。
# 例: OVERDUE_MAIL_TO = ["team@example.com"]
OVERDUE_MAIL_TO = []
OVERDUE_MAIL_CC = []

# メールに載せるタスクへのリンクの基準URL
# (メンバーのPCからこのアプリを開くときのURL。末尾の / は不要)。
# 空ならメールにはリンクを付けず、タスク名だけを載せます。
# 例: APP_BASE_URL = "http://192.0.2.10:8050"
APP_BASE_URL = ""
'''


# =============================================================================
# 1-3. instance/config.py の自動作成・読み込み・画面からの更新
# =============================================================================
# 環境ごとの設定ファイル(instance/config.py)の自動作成・読み込み・画面からの更新。
#
# 環境によって変わる値(秘密鍵・管理者パスワード・LDAP/AI/メールの接続先など)は、
# すべて instance/config.py の1か所にまとめる。instance/ はDB(app.db)と同じ
# フォルダで Git管理外のため、パスワードやキーがリポジトリに入ることはない。
#
# ■ 自動作成(ensure_instance_config)
# prepare_instance()(アプリの起動時・seed / migrate コマンド)は ensure_instance_config() を呼ぶ。
#   - instance/config.py が既にあれば何もしない(決して上書きしない)
#   - 無ければ、見本(CONFIG_TEMPLATE)をもとに作成する
#       ・SECRET_KEY     : ランダムな値(secrets.token_hex(32))
#       ・ADMIN_PASSWORD : ランダムな値(secrets.token_urlsafe(12))。導入先ごとに異なる
#       ・AI_API_URL / AI_API_KEY / AI_MODEL :
#           旧「AI接続設定」画面で保存した値がDBに残っていれば、1回だけ引き継ぐ
#           (DBは読み取り専用で開き、一切書き込まない。失敗したら引き継がない)
# 作成時はファイルの場所だけを1行表示する(パスワードやキーの値は表示しない)。
#
# ■ 読み込み(read_config)
# ファイルを Flask の from_pyfile と同じ方法で評価し、大文字の名前の値を返す。
#
# ■ 画面からの更新(update_config。システム設定の「基本設定」タブで使う)
#   1. 変更する項目の `KEY = ...` の値の部分だけを置き換える(無い項目は末尾に追記)。
#      コメント・知らない項目・書式(改行コードを含む)はそのまま残す
#   2. 先頭付近の「# 最終更新: ...」の行を1行だけ更新する(無ければ追加)
#   3. 新しい内容が Python として正しく、期待どおりの値になることを確かめる
#      (変更しない項目の値が変わっていないことも確かめる)
#   4. 元のファイルを instance/config.py.bak にコピーしてから、
#      一時ファイルに書いて置き換える(os.replace。書き込み途中で壊れたファイルを残さない)
#   同時に保存されても壊れないよう、共通のロック(config_file_lock)で直列化する。
#   エラーメッセージには設定値(パスワード・キーなど)を含めない。

CONFIG_FILENAME = "config.py"
BACKUP_SUFFIX = ".bak"

# 画面から更新したときに書く見出しコメント(1行だけ。毎回置き換える)
HEADER_PREFIX = "# 最終更新:"

# 読み込み・更新を直列化するロック(画面からの保存が同時に行われても壊れないように)
config_file_lock = threading.RLock()

_UTF8_BOM = "﻿"
# Python の構文で行の区切りになる改行(\r\n / \r / \n)。ast の行番号と同じ数え方で分ける
_LINE_RE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+$")
_CODING_RE = re.compile(r"^[ \t\f]*#.*?coding[:=]")
# 文字コードの指定(PEP 263。1〜2行目のコメント)
_CODING_DECL_RE = re.compile(r"^[ \t\f]*#.*?coding[:=][ \t]*([-\w.]+)")


class ConfigFileError(Exception):
    """instance/config.py を読み込めない・安全に更新できない(メッセージに設定値は含めない)。"""


class ConfigConflictError(ConfigFileError):
    """画面を開いた後に、ほかの保存や直接の編集で instance/config.py が変わっていた。"""


# --------------------------------------------------------------------------- #
# 値の書き方と、`KEY = ...` の置き換え
# --------------------------------------------------------------------------- #
def format_value(value):
    """設定ファイルに書く値の表記(文字列は repr()、一覧はリスト表記)。

    文字列は repr() で書き出すので、引用符や改行などを含んでも安全に記述できる。
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(format_value(item) for item in value) + "]"
    raise TypeError("設定ファイルに書けない種類の値です: {}".format(type(value).__name__))


def _split_lines(text):
    """行に分ける(行末の改行を含む)。ast の行番号と同じ区切り方。"""
    return _LINE_RE.findall(text)


def _binds(node, key):
    """文 node の中で key に代入しているか(入れ子の文も含む)。"""
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id == key and isinstance(child.ctx, ast.Store):
            return True
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                and child.name == key:
            return True
        if isinstance(child, (ast.Import, ast.ImportFrom)):
            for alias in child.names:
                if (alias.asname or alias.name.split(".")[0]) == key:
                    return True
    return False


def _value_node(tree, key):
    """最後に key を決めているトップレベルの文が単純な `KEY = 値` なら、その値の式を返す。

    `KEY = 値`(注釈付きを含む)以外の形(条件付き・複数代入・+= など)で最後に決まる場合や、
    どこでも代入していない場合は None(呼び出し側は末尾に追記する)。
    """
    found = None
    for stmt in tree.body:
        if not _binds(stmt, key):
            continue
        found = None
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 \
                and isinstance(stmt.targets[0], ast.Name) and stmt.targets[0].id == key:
            found = stmt.value
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) \
                and stmt.target.id == key and stmt.value is not None:
            found = stmt.value
    return found


def _char_index(lines, starts, lineno, col_offset):
    """ast の (行番号, UTF-8 のバイト位置) を、本文の文字位置に変換する。"""
    line = lines[lineno - 1]
    prefix = line.encode("utf-8")[:col_offset].decode("utf-8", "ignore")
    return starts[lineno - 1] + len(prefix)


def _newline_of(text):
    """ファイルで使われている改行コード(既定は \\n)。"""
    match = re.search(r"\r\n|\r|\n", text)
    return match.group(0) if match else "\n"


def _set_value(text, key, value, newline=None):
    """設定ファイルの本文で `KEY = ...` の値の部分を置き換える(無ければ末尾に追記)。

    値は format_value() で書き出す(文字列は repr()、一覧はリスト表記)。
    行末のコメントや前後の行、ほかの項目はそのまま残す。
    本文が Python として解釈できない場合や、単純な `KEY = 値` で決まっていない場合は
    末尾に `KEY = 値` を追記する(後の代入が優先されるため)。
    """
    newline = newline or _newline_of(text)
    literal = format_value(value)
    try:
        node = _value_node(ast.parse(text), key)
    except SyntaxError:
        node = None
    if node is not None:
        lines = _split_lines(text)
        starts, position = [], 0
        for line in lines:
            starts.append(position)
            position += len(line)
        begin = _char_index(lines, starts, node.lineno, node.col_offset)
        end = _char_index(lines, starts, node.end_lineno, node.end_col_offset)
        return text[:begin] + literal + text[end:]

    if text and not text.endswith(("\n", "\r")):
        text += newline
    return text + "{} = {}{}".format(key, literal, newline)


def _refresh_header(text, line, newline):
    """「# 最終更新: ...」の行を置き換える(無ければ先頭に追加。文字コード指定の行の後ろ)。"""
    lines = _split_lines(text)
    for index, current in enumerate(lines):
        if current.startswith(HEADER_PREFIX):
            ending = current[len(current.rstrip("\r\n")):] or newline
            lines[index] = line + ending
            return "".join(lines)
    insert_at = 0
    while insert_at < min(2, len(lines)) and (
            lines[insert_at].startswith("#!") or _CODING_RE.match(lines[insert_at])):
        insert_at += 1
    lines.insert(insert_at, line + newline)
    return "".join(lines)


def _clean_label(text):
    """見出しコメントに入れる文字列(文字・数字と . _ @ - だけ。ほかは _ にする)。

    「:」「=」を残さないので、コメントが文字コードの指定(# coding: ...)と解釈されることはない。
    """
    text = re.sub(r"[\x00-\x1f\x7f]", "", str(text or "")).strip()
    return re.sub(r"[^\w.@\-]", "_", text)[:64] or "不明"


def _declared_encoding(text):
    """1〜2行目の文字コードの指定(# coding: ...)。無ければ None。"""
    for line in _split_lines(text)[:2]:
        match = _CODING_DECL_RE.match(line)
        if match:
            return match.group(1)
    return None


# --------------------------------------------------------------------------- #
# 読み込み
# --------------------------------------------------------------------------- #
def config_path(instance_path):
    return os.path.join(instance_path, CONFIG_FILENAME)


def file_version(path):
    """ファイルの版(更新日時とサイズ)。内容から作らないので、設定値の推測には使えない。"""
    try:
        stat = os.stat(path)
    except OSError:
        return "none"
    return "{}-{}".format(stat.st_mtime_ns, stat.st_size)


def evaluate(text, filename):
    """設定ファイルを Flask の from_pyfile と同じ方法で評価し、大文字の名前の値を返す。

    text はファイルの内容(bytes。from_pyfile と同じく文字コードの指定に従って読む)または本文(str)。
    """
    module = types.ModuleType("config")
    module.__file__ = filename
    exec(compile(text, filename, "exec"), module.__dict__)  # noqa: S102 (設定ファイル自体の評価)
    return {name: value for name, value in vars(module).items() if name.isupper()}


def read_config(instance_path):
    """instance/config.py を読み込む。

    戻り値: {"path", "exists", "text", "values", "version", "bom"}
    ファイルが無ければ exists=False・values={}。読めない・評価できない場合は ConfigFileError。
    """
    path = config_path(instance_path)
    version = file_version(path)
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except FileNotFoundError:
        return {"path": path, "exists": False, "text": "", "values": {},
                "version": version, "bom": False}
    except OSError as exc:
        raise ConfigFileError("instance/{} を開けません（{}）。".format(
            CONFIG_FILENAME, exc.__class__.__name__)) from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigFileError("instance/{} を UTF-8 として読み込めません。".format(
            CONFIG_FILENAME)) from exc
    bom = text.startswith(_UTF8_BOM)
    if bom:
        text = text[len(_UTF8_BOM):]
    try:
        values = evaluate(raw, path)  # 起動時(from_pyfile)と同じく、ファイルの内容(bytes)を評価する
    except SyntaxError as exc:
        raise ConfigFileError("instance/{} の {} 行目に書式の誤りがあります。".format(
            CONFIG_FILENAME, exc.lineno)) from exc
    except Exception as exc:
        raise ConfigFileError("instance/{} を評価できません（{}）。".format(
            CONFIG_FILENAME, exc.__class__.__name__)) from exc
    return {"path": path, "exists": True, "text": text, "values": values,
            "version": version, "bom": bom}


def _is_utf8(name):
    try:
        return codecs.lookup(name).name == "utf-8"
    except LookupError:
        return False


def same_value(a, b):
    """設定値が同じか(True と 1 のように型が違うものは別扱い。一覧は要素ごとに比べる)。"""
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(same_value(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


_PLAIN_TYPES = (type(None), bool, int, float, str, list, tuple, dict)


# --------------------------------------------------------------------------- #
# 画面からの更新
# --------------------------------------------------------------------------- #
def _write_atomic(path, data):
    """一時ファイルに書いてから置き換える(書き込み途中で壊れたファイルを残さない)。"""
    folder = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(prefix=".config_", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def update_config(instance_path, changes, username, expected_version=None, now=None):
    """instance/config.py の項目を書き換える(changes = {KEY: 新しい値})。

    expected_version を渡すと、ファイルの版がそれと違う場合は ConfigConflictError
    (画面を開いた後に別の保存・直接の編集があった)。
    戻り値: 書き換え後のファイルの値(大文字の名前の辞書)。
    失敗した場合は ConfigFileError(ファイルは変更しない)。
    """
    with config_file_lock:
        current = read_config(instance_path)
        path = current["path"]
        if expected_version is not None and current["version"] != expected_version:
            raise ConfigConflictError(
                "画面を開いた後に instance/{} が更新されています。".format(CONFIG_FILENAME))

        text = current["text"]
        declared = _declared_encoding(text)
        if declared is not None and not _is_utf8(declared):
            raise ConfigFileError(
                "instance/{} の文字コードの指定（coding）が UTF-8 ではないため、画面から更新できません。"
                "ファイルは変更していません。ファイルを直接編集してください。".format(CONFIG_FILENAME))
        newline = _newline_of(text)
        for key, value in changes.items():
            text = _set_value(text, key, value, newline)
        stamp = (now or datetime.now()).strftime("%Y-%m-%d %H:%M")
        text = _refresh_header(
            text, "{} {}（画面から変更: {}）".format(HEADER_PREFIX, stamp, _clean_label(username)),
            newline)

        data = text.encode("utf-8")
        if current["bom"]:
            data = _UTF8_BOM.encode("utf-8") + data

        # 新しい内容が正しく、期待どおりの値になることを確かめてから置き換える
        # (書き込むバイト列そのものを、起動時の from_pyfile と同じ方法で評価する)
        try:
            ast.parse(data)
            values = evaluate(data, path)
        except Exception as exc:
            raise ConfigFileError("更新後の instance/{} を確認できませんでした（{}）。"
                                  "ファイルは変更していません。".format(
                                      CONFIG_FILENAME, exc.__class__.__name__)) from exc
        wrong = [key for key, value in changes.items()
                 if key not in values or not same_value(values[key], value)]
        for key, old in current["values"].items():
            if key in changes or not isinstance(old, _PLAIN_TYPES):
                continue
            if key not in values or not same_value(values[key], old):
                wrong.append(key)
        if wrong:
            raise ConfigFileError(
                "instance/{} の書き方のため、画面から安全に更新できませんでした（{}）。"
                "ファイルは変更していません。ファイルを直接編集してください。".format(
                    CONFIG_FILENAME, "、".join(sorted(set(wrong)))))

        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if current["exists"]:
                shutil.copy2(path, path + BACKUP_SUFFIX)
            _write_atomic(path, data)
        except OSError as exc:
            raise ConfigFileError("instance/{} を保存できませんでした（{}）。".format(
                CONFIG_FILENAME, exc.__class__.__name__)) from exc
        return values


# --------------------------------------------------------------------------- #
# 自動作成
# --------------------------------------------------------------------------- #
def _read_old_ai_settings(db_path):
    """旧「AI接続設定」画面の値(ai_settings テーブル)を読み取り専用で取得する。

    DB・テーブル・行が無い場合や、読み取りに失敗した場合は空の辞書を返す。
    """
    if not os.path.isfile(db_path):
        return {}
    try:
        uri = pathlib.Path(db_path).resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        try:
            found = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ai_settings'"
            ).fetchone()
            if found is None:
                return {}
            row = conn.execute(
                "SELECT api_url, api_key, model FROM ai_settings ORDER BY id LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
    except Exception:
        return {}
    if row is None:
        return {}

    values = {}
    for key, value in zip(("AI_API_URL", "AI_API_KEY", "AI_MODEL"), row):
        value = (value or "").strip() if isinstance(value, str) else ""
        if value:
            values[key] = value
    return values


def _build_content(db_path):
    """新しく作る instance/config.py の内容を組み立てる。"""
    text = CONFIG_TEMPLATE
    values = {
        "SECRET_KEY": secrets.token_hex(32),
        "ADMIN_PASSWORD": secrets.token_urlsafe(12),
    }
    # 旧画面のAI接続設定を1回だけ引き継ぐ(空の項目は見本の値のまま)
    values.update(_read_old_ai_settings(db_path))

    for key, value in values.items():
        text = _set_value(text, key, value)

    header = "# 自動作成: {}(app.py の見本 CONFIG_TEMPLATE をもとに作成)\n".format(
        datetime.now().strftime("%Y/%m/%d %H:%M")
    )
    return header + text


def _notice(message):
    """起動時のお知らせを1行表示する(表示できない環境でも起動は止めない)。"""
    try:
        print(message, flush=True)
    except Exception:
        pass


def ensure_instance_config(instance_path):
    """instance/config.py が無ければ作成する。作成した場合は True を返す。

    既にある場合は何もしない(内容の確認・上書きもしない)。
    作成に失敗した場合は1行表示して False を返す(Config の既定値で起動を続ける)。
    """
    path = config_path(instance_path)
    if os.path.exists(path):
        return False

    content = _build_content(os.path.join(instance_path, "app.db"))
    try:
        # "x" = 新規作成専用。同時に別プロセスが作成していても上書きしない
        with open(path, "x", encoding="utf-8", newline="\n") as f:
            f.write(content)
    except FileExistsError:
        return False
    except OSError as exc:
        _notice("設定ファイルを作成できませんでした: {} ({})".format(path, exc))
        return False

    _notice("設定ファイルを作成しました（管理者パスワード等はこのファイルで確認・変更）: {}"
            .format(path))
    return True


# #############################################################################
# 2. 共通の部品
# #############################################################################


# =============================================================================
# 2-1. Flask 拡張(DB・ログイン管理)
# =============================================================================
# Flask拡張のインスタンス。
#
# アプリ本体への紐付け(init_app)は create_app()・prepare_instance() で行う。

db = SQLAlchemy()
login_manager = LoginManager()

# 未ログイン時に飛ばすログイン画面のエンドポイント
login_manager.login_view = "auth.login"
login_manager.login_message = "ログインしてください。"
login_manager.login_message_category = "warning"


# =============================================================================
# 2-2. 小さなヘルパー関数
# =============================================================================
# アプリ共通の小さなヘルパー関数。
#
# 複数のBlueprintから再利用する純粋関数を置く。


def parse_date(value):
    """フォームの日付文字列(YYYY-MM-DD)をdateに変換する。空・不正ならNone。

    tasks / leaves で共通利用する。
    """
    value = (value or "").strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_hhmm(value):
    """"HH:MM"(または "H:MM")を datetime.time に変換する。不正なら None。

    週報・期限超過通知の送信時刻で共通利用する。
    """
    try:
        return datetime.strptime((value or "").strip(), "%H:%M").time()
    except (TypeError, ValueError):
        return None


def get_active_users():
    """有効なユーザーを表示名順で取得する(担当者・受信者の選択肢用)。"""
    return User.query.filter_by(is_active=True).order_by(User.display_name).all()


# =============================================================================
# 2-3. 画面で編集する設定(JSONファイル)の読み書き
# =============================================================================
# 画面で編集する設定(JSONファイル)の読み書きの共通部品。
#
# 週報(instance/weekly_settings.json)・期限超過通知(instance/overdue_settings.json)など、
# DBを使わずに instance/ のJSONファイルへ設定と「前回の結果」を保存する機能で使う。
#
#   read_json(path, label)      : 読む。無ければ None、あるのに読めなければ SettingsFileError
#   write_json(path, data)      : 一時ファイルに書いてから置き換える(書き込み途中で壊れない)
#   normalize_last_result(v)    : 読み込んだ「前回の結果」を検証する(不正なら None)
#   new_last_result(...)        : 新しい「前回の結果」(日時・きっかけ・成否・メッセージ)
#
# 画面の保存とバックグラウンドの送信が同時に書き込んでも壊れないよう、呼び出し側は
# 機能ごとのロックで「読む→書く」を直列化する。
# ファイルがあるのに読み込めない(壊れている・開けない)ときは、保存済みの設定を
# 消さないよう上書きしない(SettingsFileError を送出する)。

# 実行のきっかけ(前回の結果の表示用)
TRIGGER_AUTO = "自動"
TRIGGER_MANUAL = "手動"
TRIGGER_TEST = "テスト"

# 前回の結果のメッセージの最大文字数
MESSAGE_MAX = 500


class SettingsFileError(OSError):
    """設定ファイルはあるが読み込めない(壊れている・開けない)。上書きを防ぐために使う。"""


def read_json(path, label):
    """設定ファイルを読む。無ければ None、あるのに読めなければ SettingsFileError。

    label はエラーメッセージに使う設定の名前(例: 「週報の設定ファイル」)。
    エディタで保存したときに付く BOM は無視する。
    """
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise SettingsFileError(
            "{}（instance/{}）を読み込めません。"
            "ファイルを修正するか削除してください: {}".format(
                label, os.path.basename(path), exc)
        ) from exc


def write_json(path, data):
    """一時ファイルに書いてから置き換える(書き込み途中で壊れたファイルを残さない)。"""
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    stem = os.path.splitext(os.path.basename(path))[0]
    fd, tmp_path = tempfile.mkstemp(prefix=".{}_".format(stem), suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def normalize_last_result(value):
    """読み込んだ「前回の結果」を検証して整える(辞書でなければ None)。"""
    if not isinstance(value, dict):
        return None
    return {
        "at": str(value.get("at") or ""),
        "trigger": str(value.get("trigger") or ""),
        "ok": bool(value.get("ok")),
        "message": str(value.get("message") or "")[:MESSAGE_MAX],
    }


def new_last_result(trigger, ok, message):
    """今の日時で「前回の結果」を作る。"""
    return {
        "at": datetime.now().strftime("%Y/%m/%d %H:%M"),
        "trigger": trigger,
        "ok": bool(ok),
        "message": str(message or "")[:MESSAGE_MAX],
    }


# =============================================================================
# 2-4. 営業日カレンダー(土日・祝日)
# =============================================================================
# 営業日カレンダー(土日と日本の祝日・休日。純粋な Python だけで計算する)。
#
# 外部のライブラリや祝日データのファイルは使わず、「国民の祝日に関する法律」の
# ルールから計算する。DBにもFlaskにも依存しないため、どこからでも使える。
#
#   is_holiday(d)                    : 祝日・休日(振替休日・国民の休日を含む)か
#   holiday_name(d)                  : 祝日・休日の名前(該当しなければ None)
#   is_business_day(d)               : 営業日(月〜金で、祝日・休日でない日)か
#   business_days_ago(past, today)   : past より後〜today まで(両端のうち today を含む)の
#                                      営業日の日数。同じ日なら 0
#
# 計算するもの:
#   - 日付が決まっている祝日(元日・建国記念の日・天皇誕生日・昭和の日・憲法記念日・
#     みどりの日・こどもの日・山の日・文化の日・勤労感謝の日)
#   - ハッピーマンデー(成人の日・海の日・敬老の日・スポーツの日〔体育の日〕)
#   - 春分の日・秋分の日(1980〜2099年の標準的な計算式。範囲外の年も同じ式で近似する)
#   - 振替休日(祝日が日曜日のとき、その後の最も近い祝日でない日。2006年までは翌月曜日)
#   - 国民の休日(前日と翌日が祝日である、祝日でない日。日曜日を除く)
#   - 一度きりの祝日・休日(2019年の天皇の即位の日・即位礼正殿の儀の行われる日、
#     2020・2021年の海の日・スポーツの日・山の日の移動など)
# 法律の改正の年(成人の日のハッピーマンデー化・天皇誕生日の日付など)も反映する。
# 祝日法の施行(1948年7月20日)より前の日付は、祝日なしとして扱う。

_ONE_DAY = timedelta(days=1)

# 祝日法の施行日・振替休日の導入日・国民の休日の導入日・振替休日の改正日
_LAW_START = date(1948, 7, 20)
_SUBSTITUTE_START = date(1973, 4, 12)
_BRIDGE_START = date(1985, 12, 27)
_SUBSTITUTE_2007 = date(2007, 1, 1)

# 一度きりの祝日・休日(特別法による)
_SPECIAL_DAYS = {
    date(1959, 4, 10): "皇太子明仁親王の結婚の儀",
    date(1989, 2, 24): "昭和天皇の大喪の礼",
    date(1990, 11, 12): "即位礼正殿の儀",
    date(1993, 6, 9): "皇太子徳仁親王の結婚の儀",
    date(2019, 5, 1): "天皇の即位の日",
    date(2019, 10, 22): "即位礼正殿の儀の行われる日",
}

# 2020・2021年は海の日・スポーツの日・山の日が特別法で移動した
_MOVED_DAYS = {
    2020: {"海の日": (7, 23), "スポーツの日": (7, 24), "山の日": (8, 10)},
    2021: {"海の日": (7, 22), "スポーツの日": (7, 23), "山の日": (8, 8)},
}


def _to_date(value):
    """datetime は日付部分だけにする(date はそのまま)。"""
    if isinstance(value, datetime):
        return value.date()
    return value


def _nth_monday(year, month, nth):
    """その月の第 nth 月曜日。"""
    first = date(year, month, 1)
    offset = (0 - first.weekday()) % 7  # 0 = 月曜日
    return first + timedelta(days=offset + 7 * (nth - 1))


def vernal_equinox_day(year):
    """春分の日の日付(3月の日)。1980〜2099年の標準的な計算式。"""
    n = year - 1980
    return int(20.8431 + 0.242194 * n) - n // 4


def autumnal_equinox_day(year):
    """秋分の日の日付(9月の日)。1980〜2099年の標準的な計算式。"""
    n = year - 1980
    return int(23.2488 + 0.242194 * n) - n // 4


def _national_holidays(year):
    """その年の「国民の祝日」(振替休日・国民の休日を除く) {date: 名前}。"""
    days = {}

    def add(month, day, name):
        d = date(year, month, day)
        if d >= _LAW_START:
            days[d] = name

    moved = _MOVED_DAYS.get(year, {})

    add(1, 1, "元日")
    if year >= 2000:
        d = _nth_monday(year, 1, 2)
        add(d.month, d.day, "成人の日")
    elif year >= 1949:
        add(1, 15, "成人の日")
    if year >= 1967:
        add(2, 11, "建国記念の日")
    if year >= 2020:
        add(2, 23, "天皇誕生日")
    if year >= 1949:
        add(3, vernal_equinox_day(year), "春分の日")
    if year >= 2007:
        add(4, 29, "昭和の日")
    elif year >= 1989:
        add(4, 29, "みどりの日")
    else:
        add(4, 29, "天皇誕生日")
    add(5, 3, "憲法記念日")
    if year >= 2007:
        add(5, 4, "みどりの日")
    add(5, 5, "こどもの日")
    if "海の日" in moved:
        add(*moved["海の日"], "海の日")
    elif year >= 2003:
        d = _nth_monday(year, 7, 3)
        add(d.month, d.day, "海の日")
    elif year >= 1996:
        add(7, 20, "海の日")
    if "山の日" in moved:
        add(*moved["山の日"], "山の日")
    elif year >= 2016:
        add(8, 11, "山の日")
    if year >= 2003:
        d = _nth_monday(year, 9, 3)
        add(d.month, d.day, "敬老の日")
    elif year >= 1966:
        add(9, 15, "敬老の日")
    add(9, autumnal_equinox_day(year), "秋分の日")
    if "スポーツの日" in moved:
        add(*moved["スポーツの日"], "スポーツの日")
    elif year >= 2000:
        d = _nth_monday(year, 10, 2)
        add(d.month, d.day, "スポーツの日" if year >= 2020 else "体育の日")
    elif year >= 1966:
        add(10, 10, "体育の日")
    add(11, 3, "文化の日")
    add(11, 23, "勤労感謝の日")
    if 1989 <= year <= 2018:
        add(12, 23, "天皇誕生日")

    for d, name in _SPECIAL_DAYS.items():
        if d.year == year:
            days[d] = name
    return days


@lru_cache(maxsize=256)
def _holidays_of_year(year):
    """その年の祝日・休日(振替休日・国民の休日を含む) {date: 名前}。"""
    national = _national_holidays(year)
    result = dict(national)

    # 振替休日: 祝日が日曜日のとき
    #   2007年から: その後の最も近い「祝日でない日」
    #   2006年まで: 翌日(月曜日)が祝日でなければ、その翌日
    for d in sorted(national):
        if d.weekday() != 6 or d < _SUBSTITUTE_START:
            continue
        substitute = d + _ONE_DAY
        if d >= _SUBSTITUTE_2007:
            while substitute in national:
                substitute += _ONE_DAY
        elif substitute in national:
            continue
        if substitute.year == year:
            result.setdefault(substitute, "振替休日")

    # 国民の休日: 前日と翌日が祝日で、その日自体は祝日でない日(日曜日・振替休日を除く)
    for d in sorted(national):
        between = d + _ONE_DAY
        if (between >= _BRIDGE_START and between.year == year
                and between not in result and between.weekday() != 6
                and (between + _ONE_DAY) in national):
            result[between] = "国民の休日"
    return result


def holiday_name(d):
    """祝日・休日の名前(振替休日・国民の休日を含む)。該当しなければ None。"""
    d = _to_date(d)
    return _holidays_of_year(d.year).get(d)


def is_holiday(d):
    """祝日・休日(振替休日・国民の休日を含む)か。土日であることは問わない。"""
    return holiday_name(d) is not None


def is_business_day(d):
    """営業日(月〜金で、祝日・休日でない日)か。"""
    d = _to_date(d)
    return d.weekday() < 5 and not is_holiday(d)


def business_days_ago(past_date, today):
    """past_date より後〜today までの営業日の日数(past_date < d <= today)。

    同じ日(または past_date が today より後)なら 0。
    例: 金曜日 → 次の月曜日(祝日でない)は 1。
    """
    past_date, today = _to_date(past_date), _to_date(today)
    if past_date >= today:
        return 0
    count = 0
    d = past_date + _ONE_DAY
    while d <= today:
        if is_business_day(d):
            count += 1
        d += _ONE_DAY
    return count


# #############################################################################
# 3. モデル(DBのテーブル)
# #############################################################################
# DBのテーブルは、ここで定義したクラスから作る(足りないテーブルは起動時に create_all で作成。
# 既存のテーブルへの列の追加は flask --app app migrate)。


# =============================================================================
# 3-1. ユーザー
# =============================================================================
# ユーザーモデル。
#
# 認証はLDAP-APIで行う想定のため、パスワードはこのテーブルには保存しない。
# LDAPで認証成功したユーザーの情報(表示名・役割)をミラーリングして保持する。
# 組織のグルーピングは「チーム」(Department モデル＋user_departments 多対多)のみで管理する。

# 役割(ロール)は マネージャー / メンバー の2種類。マネージャーが全機能を利用できる。
ROLE_MANAGER = "manager"  # マネージャー:全機能(スキル/各ダッシュボード/チーム管理など)
ROLE_MEMBER = "member"    # メンバー:一般利用

# ldap_client.py(本番環境ごとに差し替えるファイル。内容は変えない)は
# 「from app.models.user import ROLE_MANAGER, ROLE_MEMBER」で役割の定数を読む。
# このモジュール(app.py)をその名前でも読めるようにしておく。
sys.modules.setdefault("app.models", sys.modules[__name__])
sys.modules.setdefault("app.models.user", sys.modules[__name__])

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


# =============================================================================
# 3-2. タスク
# =============================================================================
# タスクモデル。
#
# 誰が・何を・いつまでに・どこまで進んでいるか を管理する。
# 1つのタスクを複数のメンバーに割り当てられる(担当者は多対多)。
# やり取りはコメント(TaskComment)で行う。

# ステータスの定義(順序は画面の並び順にも使う)
STATUS_TODO = "未着手"
STATUS_DOING = "進行中"
STATUS_HOLD = "保留"
STATUS_DONE = "完了"
STATUS_CHOICES = [STATUS_TODO, STATUS_DOING, STATUS_HOLD, STATUS_DONE]

# ステータスごとのBootstrapバッジ色(画面表示用)
STATUS_COLORS = {
    STATUS_TODO: "secondary",
    STATUS_DOING: "primary",
    STATUS_HOLD: "warning",
    STATUS_DONE: "success",
}

# 優先度の定義
PRIORITY_LOW = "低"
PRIORITY_MID = "中"
PRIORITY_HIGH = "高"
PRIORITY_CHOICES = [PRIORITY_HIGH, PRIORITY_MID, PRIORITY_LOW]

PRIORITY_COLORS = {
    PRIORITY_HIGH: "danger",
    PRIORITY_MID: "info",
    PRIORITY_LOW: "light",
}

# 成果(定量)の単位(見込み・実績で選択)。￥=金額 / ｈ=時間、年・月・日あたり。
OUTCOME_UNITS = ["￥/年", "￥/月", "￥/日", "ｈ/年", "ｈ/月", "ｈ/日"]


def _fmt_num(v):
    """float を入力/表示用の文字列に(整数は小数点なし・末尾ゼロ除去)。"""
    if v is None:
        return ""
    s = ("%.4f" % float(v)).rstrip("0").rstrip(".")
    return s or "0"


def _fmt_amount(v):
    """桁区切り付きの表示用文字列。"""
    if v is None:
        return ""
    s = _fmt_num(abs(v))
    ip, _dot, fp = s.partition(".")
    ip = "{:,}".format(int(ip)) if ip else "0"
    out = ip + ("." + fp if fp else "")
    return ("-" + out) if float(v) < 0 else out


# タスクの規模(=担当者が完了までに要する実働工数の目安。マネージャがスキル/キャパを
# 考慮して選ぶため、能力差は規模選択の時点で反映される)。負荷合算のため実働時間(h)に
# 対応づける(8h/日・40h/週・160h/月換算)。各要素 = (キー, 表示名, 工数h, 目安日数)。
TASK_SCALES = [
    ("1h",     "1時間", 1,    1),
    ("half_d", "半日",  4,    1),
    ("1d",     "1日",   8,    1),
    ("3d",     "3日",   24,   3),
    ("1w",     "1週",   40,   7),
    ("2w",     "2週",   80,   14),
    ("1m",     "1か月", 160,  30),
    ("3m",     "3か月", 480,  91),
    ("half_y", "半期",  960,  182),
    ("1y",     "1年",   1920, 365),
]
TASK_SCALE_KEYS = [s[0] for s in TASK_SCALES]
TASK_SCALE_LABELS = {s[0]: s[1] for s in TASK_SCALES}
TASK_SCALE_HOURS = {s[0]: s[2] for s in TASK_SCALES}
TASK_SCALE_DAYS = {s[0]: s[3] for s in TASK_SCALES}


# タスク ↔ 担当者(複数割り当て)の多対多
task_assignees = db.Table(
    "task_assignees",
    db.Column("task_id", db.Integer, db.ForeignKey("tasks.id"), primary_key=True),
    db.Column("user_id", db.Integer, db.ForeignKey("users.id"), primary_key=True),
)


class Task(db.Model):
    __tablename__ = "tasks"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(16), nullable=False, default=STATUS_TODO, index=True)
    priority = db.Column(db.String(8), nullable=False, default=PRIORITY_MID)
    start_date = db.Column(db.Date)      # 開始日(ガントチャートの開始)
    due_date = db.Column(db.Date)        # 期限(ガントチャートの終了)
    scale = db.Column(db.String(16))     # 規模(TASK_SCALE_KEYS)。実働工数の目安=負荷

    # 成果(定量): 見込み・実績(値＋単位)＋補足
    outcome_quant_estimate = db.Column(db.Float)          # 見込み(値)
    outcome_quant_estimate_unit = db.Column(db.String(8))  # 見込み(単位)
    outcome_quant_actual = db.Column(db.Float)            # 実績(値)
    outcome_quant_actual_unit = db.Column(db.String(8))   # 実績(単位)
    outcome_quant_note = db.Column(db.Text)                # 補足
    # 成果(定性): 見込み・実績
    outcome_qual_estimate = db.Column(db.Text)            # 見込み
    outcome_qual_actual = db.Column(db.Text)              # 実績

    creator_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    creator = db.relationship(
        "User", foreign_keys=[creator_id], back_populates="created_tasks"
    )
    # 担当者(複数)。User.assigned_tasks と多対多で対応
    assignees = db.relationship(
        "User",
        secondary=task_assignees,
        back_populates="assigned_tasks",
        order_by="User.display_name",
    )
    comments = db.relationship(
        "TaskComment",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskComment.created_at",
    )
    status_changes = db.relationship(
        "TaskStatusChange",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskStatusChange.changed_at",
    )

    @property
    def status_color(self):
        return STATUS_COLORS.get(self.status, "secondary")

    @property
    def priority_color(self):
        return PRIORITY_COLORS.get(self.priority, "secondary")

    @property
    def is_done(self):
        return self.status == STATUS_DONE

    @property
    def is_overdue(self):
        """期限切れ(未完了かつ期限が過去)かどうか。"""
        if self.due_date and not self.is_done:
            return self.due_date < date.today()
        return False

    @property
    def assignee_names(self):
        """担当者名(複数は「、」区切り)。未割当は空文字。"""
        return "、".join(u.display_name for u in self.assignees)

    def is_assigned_to(self, user):
        return user is not None and any(u.id == user.id for u in self.assignees)

    # --- 規模(負荷)関連 ---
    @property
    def scale_label(self):
        return TASK_SCALE_LABELS.get(self.scale)

    @property
    def scale_hours(self):
        """規模に対応する実働工数(h)。未設定は0。"""
        return TASK_SCALE_HOURS.get(self.scale, 0)

    @property
    def scale_monthly_hours(self):
        """規模(実働工数)を期間で月換算した、月あたりの目安工数(h)。

        タスクは一過性のため、開始〜期限の期間で月あたりに配分する。
        1か月未満の期間は当月に全量計上(effort / max(月数, 1))。
        期間が未設定なら規模の目安日数で代用する。
        """
        h = self.scale_hours
        if not h:
            return 0.0
        if self.start_date and self.due_date and self.due_date >= self.start_date:
            days = (self.due_date - self.start_date).days + 1
        else:
            days = TASK_SCALE_DAYS.get(self.scale, 30)
        months = max(days / 30.0, 1.0)
        return h / months

    # --- 成果(定量)の表示・入力用ヘルパ ---
    @property
    def outcome_quant_estimate_input(self):
        return _fmt_num(self.outcome_quant_estimate)

    @property
    def outcome_quant_actual_input(self):
        return _fmt_num(self.outcome_quant_actual)

    @property
    def outcome_quant_estimate_label(self):
        if self.outcome_quant_estimate is None:
            return None
        return "{} {}".format(
            _fmt_amount(self.outcome_quant_estimate),
            self.outcome_quant_estimate_unit or "",
        ).strip()

    @property
    def outcome_quant_actual_label(self):
        if self.outcome_quant_actual is None:
            return None
        return "{} {}".format(
            _fmt_amount(self.outcome_quant_actual),
            self.outcome_quant_actual_unit or "",
        ).strip()

    @property
    def has_outcome_actual(self):
        """完了に必要な『成果(実績)』が定量・定性いずれかで入力済みか。"""
        return (
            self.outcome_quant_actual is not None
            or bool((self.outcome_qual_actual or "").strip())
        )

    def __repr__(self):
        return f"<Task {self.id}: {self.title}>"


class TaskStatusChange(db.Model):
    """タスクのステータス変更履歴。ガントの棒を日付で色分けするために使う。"""

    __tablename__ = "task_status_changes"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("tasks.id"), nullable=False, index=True)
    status = db.Column(db.String(16), nullable=False)
    changed_at = db.Column(db.DateTime, default=datetime.now)

    task = db.relationship("Task", back_populates="status_changes")

    def __repr__(self):
        return f"<TaskStatusChange task={self.task_id} {self.status} @{self.changed_at}>"


class TaskComment(db.Model):
    """タスクへのコメント(やり取り)。ログインユーザーは誰でも投稿できる。"""

    __tablename__ = "task_comments"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("tasks.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)

    task = db.relationship("Task", back_populates="comments")
    user = db.relationship("User")

    def __repr__(self):
        return f"<TaskComment {self.id} task={self.task_id}>"


# =============================================================================
# 3-3. 年休
# =============================================================================
# 年休(有給休暇)の予定モデル。
#
# チーム内での情報共有・見える化が目的。承認フローは持たない(登録=即共有)。
# 1レコード=1取得日。種別は 全休 / 午前半休 / 午後半休。

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


# =============================================================================
# 3-4. 定型・定期業務
# =============================================================================
# 定型・定期業務モデル。
#
# 各メンバーが担当している繰り返し業務(定型業務・定期業務)を管理する。
# タスク(単発の作業)とは別物で、頻度・所要時間・手順書の作成状況などを持つ。
# マネージャー・メンバーの全員が登録・編集できる。

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


# =============================================================================
# 3-5. スキル
# =============================================================================
# スキル管理(スキルマップ)モデル。
#
# Katzの3区分(テクニカル/コンセプチュアル/ヒューマン)でメンバーの到達度を管理する。
# 到達度はマネージャーが設定・更新する(本人の自己評価は持たない)。
# 未評価(スパース)は SkillRating レコード未作成 = レベル0(未習得)として扱う。

# --- スキル区分(Katzの3スキル) ---
SKILL_TECHNICAL = "テクニカル"
SKILL_CONCEPTUAL = "コンセプチュアル"
SKILL_HUMAN = "ヒューマン"
SKILL_TYPE_CHOICES = [SKILL_TECHNICAL, SKILL_CONCEPTUAL, SKILL_HUMAN]
SKILL_TYPE_LABELS = {
    SKILL_TECHNICAL: "テクニカルスキル",
    SKILL_CONCEPTUAL: "コンセプチュアルスキル",
    SKILL_HUMAN: "ヒューマンスキル",
}
SKILL_TYPE_COLORS = {
    SKILL_TECHNICAL: "primary",
    SKILL_CONCEPTUAL: "success",
    SKILL_HUMAN: "info",
}

# --- 到達尺度(区分ごと。リストの index = レベル値) ---
# テクニカルは6段階＋未習得(0〜6)。
# コンセプチュアル/ヒューマンは未習得＋5段階(0〜5)。
SKILL_SCALES = {
    SKILL_TECHNICAL: [
        "未習得",
        "簡単なものが作れる",
        "少し難しいものも作れる",
        "難しいものもつくれる",
        "大体何でも作れる",
        "指導できる",
        "勉強会を開催できる",
    ],
    SKILL_CONCEPTUAL: [
        "未習得",
        "指示があれば対応できる",
        "自分の担当範囲を把握して動ける",
        "業務全体を俯瞰し問題点を指摘できる",
        "課題を構造化し解決策を立案できる",
        "全体最適の視点で方針を示し牽引できる",
    ],
    SKILL_HUMAN: [
        "未習得",
        "挨拶・報連相が確実にできる",
        "周囲と協調して作業を進められる",
        "後輩の相談に乗り指導できる",
        "チームの合意形成や調整ができる",
        "他チーム・関係者を巻き込み人を動かせる",
    ],
}

# レベル別のバッジ色(0=未習得は淡色、上位ほど濃く)
SKILL_LEVEL_COLORS = {
    0: "light",
    1: "secondary",
    2: "info",
    3: "primary",
    4: "primary",
    5: "success",
    6: "success",
}

# 「単独で実務可能」とみなす到達度の下限(スキル保有状況の指標で使用)
SKILL_PROFICIENT_LEVEL = 2


def scale_for(skill_type):
    return SKILL_SCALES.get(skill_type, SKILL_SCALES[SKILL_TECHNICAL])


def level_label(skill_type, level):
    scale = scale_for(skill_type)
    return scale[level] if 0 <= level < len(scale) else str(level)


class Skill(db.Model):
    __tablename__ = "skills"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    skill_type = db.Column(
        db.String(16), nullable=False, default=SKILL_TECHNICAL, index=True
    )
    category = db.Column(db.String(64))  # テクニカル項目のグルーピング(任意)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    ratings = db.relationship(
        "SkillRating",
        back_populates="skill",
        cascade="all, delete-orphan",
        order_by="SkillRating.id",
    )
    # このスキルを必要とする業務の要件(必要レベル付き)。横軸「業務」ビューで使う
    operation_reqs = db.relationship(
        "OperationSkill",
        back_populates="skill",
        cascade="all, delete-orphan",
    )

    @property
    def type_label(self):
        return SKILL_TYPE_LABELS.get(self.skill_type, self.skill_type)

    @property
    def type_color(self):
        return SKILL_TYPE_COLORS.get(self.skill_type, "secondary")

    @property
    def max_level(self):
        return len(scale_for(self.skill_type)) - 1

    @property
    def level_labels(self):
        return scale_for(self.skill_type)

    def rating_for(self, user):
        """指定ユーザーの到達度レコードを返す(未評価ならNone)。"""
        if user is None:
            return None
        return next((r for r in self.ratings if r.user_id == user.id), None)

    def level_of(self, user):
        """指定ユーザーの到達度(未評価は0)。"""
        r = self.rating_for(user)
        return r.level if r else 0

    def holder_count(self, min_level=SKILL_PROFICIENT_LEVEL):
        """一定レベル以上を保有するメンバー数(スキル保有状況の指標)。"""
        return sum(1 for r in self.ratings if r.level >= min_level)

    def __repr__(self):
        return f"<Skill {self.id} {self.skill_type}:{self.name}>"


class SkillRating(db.Model):
    __tablename__ = "skill_ratings"
    __table_args__ = (
        db.UniqueConstraint("skill_id", "user_id", name="uq_skill_user"),
    )

    id = db.Column(db.Integer, primary_key=True)
    skill_id = db.Column(db.Integer, db.ForeignKey("skills.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    level = db.Column(db.Integer, nullable=False, default=0)
    note = db.Column(db.String(200))
    rated_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    rated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    created_at = db.Column(db.DateTime, default=datetime.now)

    skill = db.relationship("Skill", back_populates="ratings")
    user = db.relationship(
        "User", foreign_keys=[user_id], back_populates="skill_ratings"
    )
    rater = db.relationship("User", foreign_keys=[rated_by_id])

    @property
    def level_label(self):
        return level_label(self.skill.skill_type, self.level)

    @property
    def level_color(self):
        return SKILL_LEVEL_COLORS.get(self.level, "secondary")

    @property
    def is_unrated(self):
        return self.level == 0

    def __repr__(self):
        return f"<SkillRating skill={self.skill_id} user={self.user_id} lv={self.level}>"


# =============================================================================
# 3-6. 業務(Operation)と必要スキル
# =============================================================================
# 業務(Operation)モデルと、業務ごとの必要スキル(OperationSkill)。
#
# スキルマップの縦軸=スキル項目に対し、横軸を『ヒト』だけでなく『業務』でも見られる。
# 業務に必要なスキルは OperationSkill で持ち、必要到達レベルは
# ヒトのスキル到達度(SkillRating)と同じ到達尺度(scale_for)を使う。


class OperationSkill(db.Model):
    """業務に必要なスキルと、その必要到達レベル。

    レベルはスキル区分ごとの到達尺度(ヒトのスキル管理と同じ)。
    レベル0(不要)はレコードを作らない(スパース)。
    """
    __tablename__ = "operation_skills"

    operation_id = db.Column(
        db.Integer, db.ForeignKey("operations.id"), primary_key=True
    )
    skill_id = db.Column(
        db.Integer, db.ForeignKey("skills.id"), primary_key=True
    )
    level = db.Column(db.Integer, nullable=False, default=0)

    operation = db.relationship("Operation", back_populates="skill_reqs")
    skill = db.relationship("Skill", back_populates="operation_reqs")

    def __repr__(self):
        return f"<OperationSkill op={self.operation_id} skill={self.skill_id} lv={self.level}>"


class Operation(db.Model):
    __tablename__ = "operations"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.Text)  # 業務内容の詳細(スキルマップのマウスオーバー表示)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

    # この業務に必要なスキル(必要レベル付き)。level>=1 のみ保持(スパース)。
    skill_reqs = db.relationship(
        "OperationSkill",
        back_populates="operation",
        cascade="all, delete-orphan",
    )

    def req_for(self, skill):
        """指定スキルの必要レベル・レコードを返す(未設定ならNone)。"""
        sid = skill.id if hasattr(skill, "id") else skill
        return next((r for r in self.skill_reqs if r.skill_id == sid), None)

    def required_level(self, skill):
        r = self.req_for(skill)
        return r.level if r else 0

    def __repr__(self):
        return f"<Operation {self.id}: {self.name}>"


# =============================================================================
# 3-7. チーム(Department)
# =============================================================================
# チーム(Department)モデル。
#
# 年休の見える化で使う組織区分。マネージャーが名称・メンバーの紐づけを管理する。
# 1人が複数のチームを兼務できるよう、User と多対多(user_departments)で持つ。

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


# =============================================================================
# 3-8. スキルテスト
# =============================================================================
# スキルテスト(AIが作る4択問題で、メンバーのテクニカルスキルの到達度を確認する)のモデル。
#
# すべて新しいテーブル(既存のテーブルは変更しない)。履歴は削除せずに残す。
#
#   SkillTestQuestion : 問題プール(スキル・レベルごとの4択問題。AIが作成し、マネージャーが有効/無効を切り替える)
#   SkillTestAttempt  : 受験1回分(状態・期限・採点結果・到達度の自動登録の結果・離脱回数・設定の控え)
#   SkillTestAnswer   : 受験の1問分(出題した問題・選択肢の並びの控え・回答・所要時間・時間切れ・離脱回数)
#
# 回答には出題時点の問題文・選択肢(並べ替えた順)・正解の位置を控えとして保存する。
# 後から問題を無効にしたり内容が変わったりしても、受験履歴はそのまま読める。
#
# 日時はすべて _now() から取る(受験の流れ(8-3)も _now() を使う)。
# 動作確認では app._now を差し替えると、制限時間・期限・再受験の間隔などを時刻を固定して確かめられる。

# --- 受験の状態 ---
ATTEMPT_IN_PROGRESS = "in_progress"  # 受験中
ATTEMPT_FINISHED = "finished"        # 全問に回答して終了
ATTEMPT_EXPIRED = "expired"          # 制限時間(全体)を過ぎて自動で終了(未回答は時間切れ)

ATTEMPT_STATUS_LABELS = {
    ATTEMPT_IN_PROGRESS: "受験中",
    ATTEMPT_FINISHED: "終了",
    ATTEMPT_EXPIRED: "時間切れで終了",
}
ATTEMPT_STATUS_COLORS = {
    ATTEMPT_IN_PROGRESS: "primary",
    ATTEMPT_FINISHED: "success",
    ATTEMPT_EXPIRED: "warning",
}

# --- 問題の作成元 ---
SOURCE_AI = "ai"
SOURCE_LABELS = {SOURCE_AI: "AI"}

# 選択肢の表示記号(index 0〜3)
CHOICE_LETTERS = ["A", "B", "C", "D"]


def _now():
    """現在の日時。スキルテストの時刻はすべてここから取る(動作確認ではこの関数を差し替える)。"""
    return datetime.now()


def choice_letter(index):
    """選択肢の位置(0〜3)を表示用の記号(A〜D)にする。範囲外・None は空文字。"""
    if isinstance(index, int) and 0 <= index < len(CHOICE_LETTERS):
        return CHOICE_LETTERS[index]
    return ""


def _json_list(text):
    """JSON文字列(リスト)を読む。壊れていれば空のリスト。"""
    try:
        value = json.loads(text or "[]")
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def _json_dict(text):
    """JSON文字列(辞書)を読む。壊れていれば空の辞書。"""
    try:
        value = json.loads(text or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


class SkillTestQuestion(db.Model):
    """問題プールの4択問題(スキル・レベルごと)。"""
    __tablename__ = "skill_test_questions"
    __table_args__ = (
        db.Index("ix_skill_test_questions_skill_level", "skill_id", "level"),
    )

    id = db.Column(db.Integer, primary_key=True)
    skill_id = db.Column(db.Integer, db.ForeignKey("skills.id"), nullable=False, index=True)
    level = db.Column(db.Integer, nullable=False)          # 想定する到達レベル(1〜4)
    question = db.Column(db.Text, nullable=False)          # 問題文
    choices = db.Column(db.Text, nullable=False)           # 選択肢4つ(JSONの配列。作成時の順)
    answer_index = db.Column(db.Integer, nullable=False)   # 正解の位置(choices の 0〜3)
    explanation = db.Column(db.Text)                       # 解説(マネージャーだけが見る)
    source = db.Column(db.String(16), nullable=False, default=SOURCE_AI)
    model = db.Column(db.String(64))                       # 作成したAIのモデル名
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=lambda: _now())

    skill = db.relationship("Skill")

    @property
    def choice_list(self):
        return _json_list(self.choices)

    @property
    def answer_letter(self):
        return choice_letter(self.answer_index)

    @property
    def source_label(self):
        return SOURCE_LABELS.get(self.source, self.source or "")

    def __repr__(self):
        return f"<SkillTestQuestion {self.id} skill={self.skill_id} lv={self.level}>"


class SkillTestAttempt(db.Model):
    """スキルテストの受験1回分。"""
    __tablename__ = "skill_test_attempts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    skill_id = db.Column(db.Integer, db.ForeignKey("skills.id"), nullable=False, index=True)
    status = db.Column(db.String(16), nullable=False, default=ATTEMPT_IN_PROGRESS, index=True)
    started_at = db.Column(db.DateTime, nullable=False, default=lambda: _now())
    finished_at = db.Column(db.DateTime)
    deadline_at = db.Column(db.DateTime, nullable=False)   # 全体の期限(各問の制限時間の合計＋余裕)
    total = db.Column(db.Integer, nullable=False, default=0)    # 問題数
    correct = db.Column(db.Integer, nullable=False, default=0)  # 正解数(終了時に確定)
    # レベルごとの結果(JSONの配列: level / total / correct / rate / rate_ok / passed)
    level_results = db.Column(db.Text)
    result_level = db.Column(db.Integer)                   # テストで認定したレベル(0〜)
    prev_level = db.Column(db.Integer)                     # 終了時点の到達度(登録前)
    new_level = db.Column(db.Integer)                      # 終了後の到達度(登録しなければ prev と同じ)
    applied = db.Column(db.Boolean, nullable=False, default=False)  # 到達度を自動登録したか
    blur_count = db.Column(db.Integer, nullable=False, default=0)   # 画面から離れた回数(タブ切替など)
    reused_count = db.Column(db.Integer, nullable=False, default=0)  # 受験済みの問題を再出題した数
    settings_snapshot = db.Column(db.Text)                 # 受験開始時の設定の控え(JSON)

    user = db.relationship("User")
    skill = db.relationship("Skill")
    answers = db.relationship(
        "SkillTestAnswer",
        back_populates="attempt",
        cascade="all, delete-orphan",
        order_by="SkillTestAnswer.seq",
    )

    @property
    def is_in_progress(self):
        return self.status == ATTEMPT_IN_PROGRESS

    @property
    def status_label(self):
        return ATTEMPT_STATUS_LABELS.get(self.status, self.status)

    @property
    def status_color(self):
        return ATTEMPT_STATUS_COLORS.get(self.status, "secondary")

    @property
    def level_result_list(self):
        return [r for r in _json_list(self.level_results) if isinstance(r, dict)]

    @property
    def settings_dict(self):
        return _json_dict(self.settings_snapshot)

    @property
    def rate(self):
        """正答率(%。小数1桁)。問題数0なら None。"""
        if not self.total:
            return None
        return round(self.correct * 100.0 / self.total, 1)

    @property
    def answered_count(self):
        return sum(1 for a in self.answers if a.answered_at is not None)

    def __repr__(self):
        return f"<SkillTestAttempt {self.id} user={self.user_id} skill={self.skill_id} {self.status}>"


class SkillTestAnswer(db.Model):
    """受験の1問分(出題時点の控えと回答)。"""
    __tablename__ = "skill_test_answers"
    __table_args__ = (
        db.UniqueConstraint("attempt_id", "seq", name="uq_skill_test_answer_seq"),
    )

    id = db.Column(db.Integer, primary_key=True)
    attempt_id = db.Column(
        db.Integer, db.ForeignKey("skill_test_attempts.id"), nullable=False, index=True
    )
    seq = db.Column(db.Integer, nullable=False)            # 出題順(1〜)
    level = db.Column(db.Integer, nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey("skill_test_questions.id"), index=True)
    question = db.Column(db.Text, nullable=False)          # 問題文の控え
    choices = db.Column(db.Text, nullable=False)           # 選択肢の控え(JSON。画面に出した順)
    correct_index = db.Column(db.Integer, nullable=False)  # 正解の位置の控え(画面に出した順)
    selected_index = db.Column(db.Integer)                 # 選んだ位置(未回答は None)
    is_correct = db.Column(db.Boolean, nullable=False, default=False)
    timed_out = db.Column(db.Boolean, nullable=False, default=False)
    time_limit_sec = db.Column(db.Integer, nullable=False)
    served_at = db.Column(db.DateTime)                     # 初めて画面に出した日時(未表示は None)
    answered_at = db.Column(db.DateTime)                   # 回答(または時間切れ)を確定した日時
    elapsed_sec = db.Column(db.Float)                      # 表示から回答までの秒数
    blur_count = db.Column(db.Integer, nullable=False, default=0)  # この問題の表示中に画面から離れた回数

    attempt = db.relationship("SkillTestAttempt", back_populates="answers")
    source_question = db.relationship("SkillTestQuestion")

    @property
    def choice_list(self):
        return _json_list(self.choices)

    @property
    def is_done(self):
        return self.answered_at is not None

    @property
    def correct_letter(self):
        return choice_letter(self.correct_index)

    @property
    def selected_letter(self):
        return choice_letter(self.selected_index)

    @property
    def result_label(self):
        """マネージャー向けの結果表示。"""
        if self.answered_at is None:
            return "未回答"
        if self.timed_out:
            return "時間切れ"
        return "正解" if self.is_correct else "不正解"

    def __repr__(self):
        return f"<SkillTestAnswer attempt={self.attempt_id} seq={self.seq}>"


# #############################################################################
# 4. 外部との接続(AI・メール)
# #############################################################################


# =============================================================================
# 4-1. ChatGPT(OpenAI互換)API クライアント
# =============================================================================
# ChatGPT(OpenAI互換)API クライアント(アプリ共通。週報の文章整形・スキルテストの問題作成で使用)。
#
# どの機能からも ai_chat() で使う(機能ごとに接続部分を持たない)。
#
# ★将来の差し替えポイント★
# 独自のOpenAI互換APIに移行する場合は、`_call_chat_api()` の中身
# だけを書き換える。呼び出し側は `ai_chat()` の戻り値の形 (text, error) にしか
# 依存していないので、他のコードは変更不要。
#
# 接続設定は instance/config.py に記入する(コードには書かない。
# システム設定の「基本設定」タブからも変更でき、保存するとすぐに反映される):
#   AI_API_URL  : エンドポイント(空なら OpenAI公式 AI_DEFAULT_API_URL)
#   AI_API_KEY  : APIキー(キー不要の独自APIなら空でよい)
#   AI_MODEL    : モデル名
#   AI_TIMEOUT  : タイムアウト(秒)
# AI_API_KEY と AI_API_URL がどちらも空なら機能は自動的に無効(ai_is_configured() が False)
# になり、呼び出し側はAIを使わない動きになる(週報はルールベースの文章、
# スキルテストは問題プールにある問題だけで出題)。
# APIキーは画面・ログ・エラーメッセージのどこにも表示しない。

AI_DEFAULT_API_URL = "https://api.openai.com/v1/chat/completions"
AI_DEFAULT_MODEL = "gpt-4o-mini"
AI_DEFAULT_TIMEOUT = 60


def _ai_settings():
    """現在の接続設定(instance/config.py の値。未記入の項目は Config の既定値)。"""
    config = current_app.config
    try:
        timeout = int(config.get("AI_TIMEOUT") or AI_DEFAULT_TIMEOUT)
    except (TypeError, ValueError):
        timeout = AI_DEFAULT_TIMEOUT
    return {
        "api_url": str(config.get("AI_API_URL") or "").strip(),
        "api_key": str(config.get("AI_API_KEY") or "").strip(),
        "model": str(config.get("AI_MODEL") or "").strip() or AI_DEFAULT_MODEL,
        "timeout": timeout if timeout > 0 else AI_DEFAULT_TIMEOUT,
    }


def ai_is_configured():
    """ChatGPT-APIが使える設定になっているか(キーまたはURLが記入済み)。"""
    values = _ai_settings()
    return bool(values["api_key"] or values["api_url"])


def _endpoint_label(url):
    """接続先の表示用(スキームとホスト名だけ。URL内の認証情報・パス・クエリは表示しない)。"""
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        host = None
    if not host:
        return "（URLを解釈できません）"
    return "{}://{}".format(parts.scheme or "http", host)


def ai_status_label():
    """画面表示用の状態文言(APIキーや接続先URLの詳細は表示しない)。"""
    if not ai_is_configured():
        return ("未設定（システム設定の「基本設定」タブで AI_API_KEY "
                "または AI_API_URL を設定すると使えます）")
    values = _ai_settings()
    return "接続先: {} ／ モデル: {}".format(
        _endpoint_label(values["api_url"] or AI_DEFAULT_API_URL), values["model"]
    )


def _mask_api_key(text, api_key):
    """エラーメッセージにAPIキーが含まれていた場合に伏せ字にする。"""
    text = str(text or "")
    if api_key and api_key in text:
        text = text.replace(api_key, "***")
    return text


# --------------------------------------------------------------------------- #
# ここから下が差し替え対象(HTTP通信部分)
# --------------------------------------------------------------------------- #
def _call_chat_api(messages):
    """チャット補完APIを呼び出して本文テキストを返す。

    独自APIに差し替える場合は、この関数だけをそのAPIの仕様に合わせて書き換える。
    (認証ヘッダ・リクエスト形式・レスポンスの取り出し方など)
    例外はそのまま送出し、呼び出し元の chat() で文言に変換する。
    """
    values = _ai_settings()
    url = values["api_url"] or AI_DEFAULT_API_URL

    payload = {
        "model": values["model"],
        "messages": messages,
        "temperature": 0.3,
    }
    request_obj = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
    )
    request_obj.add_header("Content-Type", "application/json; charset=utf-8")
    if values["api_key"]:
        request_obj.add_header("Authorization", "Bearer {}".format(values["api_key"]))

    with urllib.request.urlopen(request_obj, timeout=values["timeout"]) as response:
        data = json.loads(response.read().decode("utf-8"))

    # OpenAI互換のレスポンス形式から本文を取り出す
    return data["choices"][0]["message"]["content"]


# --------------------------------------------------------------------------- #
# 呼び出し側が使うのはこの関数だけ
# --------------------------------------------------------------------------- #
def ai_chat(messages):
    """メッセージ列(OpenAI形式の role/content の辞書のリスト)をAIに送る。

    戻り値: (応答の本文, None) / 失敗時は (None, エラーメッセージ)
    """
    if not ai_is_configured():
        return None, ("ChatGPT-APIが未設定です。システム設定の「基本設定」タブで AI_API_KEY"
                      "（独自APIの場合は AI_API_URL）を設定してください。")

    values = _ai_settings()
    api_key = values["api_key"]
    try:
        text = _call_chat_api(messages)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            # 先にキーを伏せ字にしてから切り詰める(切り詰めでキーの一部だけが残らないように)
            detail = _mask_api_key(exc.read().decode("utf-8", "ignore"), api_key)[:200]
        except Exception:
            pass
        return None, _mask_api_key("APIエラー({}): {}".format(exc.code, detail or exc.reason),
                                   api_key)
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (socket.timeout, TimeoutError)):
            return None, "APIの応答がタイムアウトしました（{}秒）。".format(values["timeout"])
        return None, _mask_api_key("APIに接続できませんでした: {}".format(exc.reason), api_key)
    except (socket.timeout, TimeoutError):
        return None, "APIの応答がタイムアウトしました（{}秒）。".format(values["timeout"])
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        return None, _mask_api_key("APIの応答を解釈できませんでした: {}".format(exc), api_key)
    except Exception as exc:  # 想定外
        return None, _mask_api_key("AI処理に失敗しました: {}".format(exc), api_key)

    text = (text or "").strip() if isinstance(text, str) else ""
    if not text:
        return None, "AIの応答が空でした。"
    return text, None


# =============================================================================
# 4-2. メール送信(SMTP)
# =============================================================================
# メール送信(SMTP)の共通部品。週報・期限超過通知など、どの機能からも使う。
#
# 送信サーバー・差出人・宛先・認証情報はすべて instance/config.py に記入する
# (MAIL_SMTP_SERVER / MAIL_SMTP_PORT / MAIL_USE_TLS / MAIL_USERNAME / MAIL_PASSWORD /
#  MAIL_FROM / MAIL_TO / MAIL_CC / MAIL_TEST_TO)。システム設定の「基本設定」タブからも変更でき、
# 保存するとすぐに反映される(値は送信のたびに current_app.config から読む)。
#
# send_mail(subject, text, html=None, attachments=(), to=None, cc=None, test=False):
#   text        : 本文(text/plain・UTF-8)
#   html        : HTML版の本文。指定すると multipart/alternative(テキスト版＋HTML版)で送る
#                 (HTMLを表示できないメールソフトではテキスト版が表示される)
#   attachments : 添付ファイル [(ファイル名, データ(bytes), maintype, subtype), ...]。
#                 指定すると multipart/mixed にして本文の後ろに添付する。
#                 日本語のファイル名は RFC 2231 の形式(filename*=utf-8''...)で付ける
#   to / cc     : 本番の宛先の一覧。None なら MAIL_TO / MAIL_CC
#   test        : True ならテスト送信。MAIL_TEST_TO(空なら差出人 MAIL_FROM)だけに送り、
#                 to / cc は使わない(Cc なし)
#   戻り値      : (成功したか, メッセージ)
#
# 送信方法は一般的な smtplib の手順どおり:
#   Date・Message-ID を付け、SMTP(必要なら STARTTLS・認証)で To＋Cc に送る。
#   STARTTLS ではサーバー証明書とホスト名を検証する(検証できなければ送信しない)。
# パスワードは画面・ログ・メッセージのどこにも表示しない。

SMTP_TIMEOUT = 20


def mail_addresses(value):
    """設定値をアドレスの一覧に整える(文字列で書かれていても「,」「;」区切りとして扱う)。"""
    if isinstance(value, str):
        value = value.replace(";", ",").split(",")
    if not isinstance(value, (list, tuple)):
        return []
    result = []
    for item in value:
        item = str(item or "").strip()
        # 改行などヘッダを壊す文字を含むものは使わない
        if item and not any(ch in item for ch in "\r\n\t"):
            result.append(item)
    return result


def _header_address(item):
    """ヘッダ(From/To/Cc)に書くアドレス。「表示名 <アドレス>」の表示名だけを符号化する
    (日本語の表示名でもアドレスの部分が読める形になる)。"""
    name, addr = parseaddr(item)
    if not addr:
        return item
    try:
        return formataddr((name, addr), charset="utf-8")
    except UnicodeError:  # アドレスの部分が半角でない(そのまま渡す)
        return item


def mail_settings():
    """現在のメール設定(画面の読み取り専用表示にも使う。パスワードは含めない)。"""
    config = current_app.config
    try:
        port = int(config.get("MAIL_SMTP_PORT") or 25)
    except (TypeError, ValueError):
        port = 25
    return {
        "server": str(config.get("MAIL_SMTP_SERVER") or "").strip(),
        "port": port,
        "use_tls": bool(config.get("MAIL_USE_TLS")),
        "username": str(config.get("MAIL_USERNAME") or "").strip(),
        "mail_from": str(config.get("MAIL_FROM") or "").strip(),
        "to": mail_addresses(config.get("MAIL_TO")),
        "cc": mail_addresses(config.get("MAIL_CC")),
        "test_to": mail_addresses(config.get("MAIL_TEST_TO")),
    }


def mail_recipients(test=False, to=None, cc=None):
    """宛先 (To, Cc)。

    テスト送信は MAIL_TEST_TO(空なら差出人)宛てで Cc なし(to / cc は使わない)。
    本番送信は to / cc(None なら MAIL_TO / MAIL_CC)。
    """
    values = mail_settings()
    if test:
        test_to = values["test_to"] or ([values["mail_from"]] if values["mail_from"] else [])
        return test_to, []
    to = values["to"] if to is None else mail_addresses(to)
    cc = values["cc"] if cc is None else mail_addresses(cc)
    return to, cc


def check_mail_settings(test=False, to=None, to_label="宛先（MAIL_TO）"):
    """送信に必要な設定が揃っているか。問題があればその説明、無ければ None。

    to       : 本番送信の宛先(None なら MAIL_TO)。テスト送信では使わない
    to_label : 本番の宛先が空のときに示す設定項目の名前
    """
    values = mail_settings()
    actual_to, _cc = mail_recipients(test, to=to)
    missing = []
    if not values["server"]:
        missing.append("送信サーバー（MAIL_SMTP_SERVER）")
    if not values["mail_from"]:
        missing.append("差出人（MAIL_FROM）")
    if not actual_to:
        missing.append("テスト送信の宛先（MAIL_TEST_TO または MAIL_FROM）" if test else to_label)
    if missing:
        return "メールの設定が不足しています: {}。システム設定の「基本設定」タブで設定してください。".format(
            "、".join(missing))
    return None


def _build_message(subject, text, html, attachments):
    """送信するメッセージを組み立てる(ヘッダは呼び出し元で付ける)。"""
    body = MIMEText(text or "", "plain", "utf-8")
    if html is not None:
        # テキスト版を先、HTML版を後に置く(メールソフトは後ろの表示できる形式を使う)
        alternative = MIMEMultipart("alternative")
        alternative.attach(body)
        alternative.attach(MIMEText(html, "html", "utf-8"))
        body = alternative
    if not attachments:
        return body

    msg = MIMEMultipart()
    msg.attach(body)
    for filename, data, maintype, subtype in attachments:
        part = MIMEBase(maintype, subtype)
        part.set_payload(data)
        encoders.encode_base64(part)
        # 日本語のファイル名は RFC 2231 の形式で付ける
        part.add_header("Content-Disposition", "attachment", filename=("utf-8", "", filename))
        msg.attach(part)
    return msg


def send_mail(subject, text, html=None, attachments=(), to=None, cc=None, test=False):
    """メールを送る。

    戻り値: (成功したか, メッセージ)
    一部の宛先だけ拒否された場合は失敗扱いにし、メッセージで拒否された宛先を示す。
    """
    problem = check_mail_settings(test, to=to)
    if problem:
        return False, problem

    values = mail_settings()
    password = str(current_app.config.get("MAIL_PASSWORD") or "")
    mail_from = values["mail_from"]
    to, cc = mail_recipients(test, to=to, cc=cc)

    msg = _build_message(subject, text, html, attachments)
    msg["From"] = _header_address(mail_from)
    msg["To"] = ", ".join(_header_address(item) for item in to)
    if cc:
        msg["Cc"] = ", ".join(_header_address(item) for item in cc)
    msg["Subject"] = subject
    # Date・Message-ID が無いと受信側で拒否・迷惑メール扱いされることがある
    msg["Date"] = formatdate(localtime=True)
    domain = parseaddr(mail_from)[1].rpartition("@")[2]
    msg["Message-ID"] = make_msgid(domain=domain or None)

    # To と Cc に同じアドレスがあっても1通だけ届ける
    envelope = list(dict.fromkeys(to + cc))

    try:
        with smtplib.SMTP(values["server"], values["port"], timeout=SMTP_TIMEOUT) as smtp:
            if values["use_tls"]:
                smtp.starttls(context=ssl.create_default_context())
            if values["username"]:
                smtp.login(values["username"], password)
            refused = smtp.sendmail(mail_from, envelope, msg.as_string())
    except smtplib.SMTPAuthenticationError:
        return False, "送信サーバーの認証に失敗しました（MAIL_USERNAME / MAIL_PASSWORD を確認してください）。"
    except smtplib.SMTPRecipientsRefused as exc:
        return False, "すべての宛先が拒否されました: {}".format("、".join(exc.recipients))
    except smtplib.SMTPSenderRefused:
        return False, "差出人（{}）が送信サーバーに拒否されました。".format(mail_from)
    except smtplib.SMTPNotSupportedError:
        return False, "送信サーバーが STARTTLS または認証に対応していません（MAIL_USE_TLS / MAIL_USERNAME を確認してください）。"
    except smtplib.SMTPException as exc:
        return False, "メール送信に失敗しました: {}".format(exc)
    except (socket.timeout, TimeoutError):
        return False, "送信サーバーの応答がタイムアウトしました（{}秒）。".format(SMTP_TIMEOUT)
    except ssl.SSLCertVerificationError as exc:
        return False, "送信サーバーの証明書を検証できませんでした（MAIL_SMTP_SERVER のホスト名と証明書を確認してください）: {}".format(
            exc.verify_message or exc)
    except OSError as exc:
        return False, "送信サーバー（{}:{}）に接続できませんでした: {}".format(
            values["server"], values["port"], exc)

    if refused:
        return False, "一部の宛先に送信できませんでした（拒否: {}）。他の {} 件には送信済みです。".format(
            "、".join(refused), len(envelope) - len(refused))
    return True, "送信しました（To {}件・Cc {}件）。".format(len(to), len(cc))


# #############################################################################
# 5. 画面(Blueprint)
# #############################################################################


# =============================================================================
# 5-1. 認証(ログイン/ログアウト)
# =============================================================================
# 認証(ログイン/ログアウト)のルーティング。
#
# ldap_client.py(プロジェクト直下)は本番環境ごとに差し替えるファイルなので、ここからは
# authenticate() と _LOCAL_ACCOUNTS(表示名・役割)しか使わない(中身には依存しない)。
# 固定ローカル管理者(admin)のパスワードは、instance/config.py の ADMIN_PASSWORD で
# 先に確認する(設定が空のときだけ ldap_client.py の判定に任せる)。
# ADMIN_PASSWORD はシステム設定の「基本設定」タブからも変更でき、保存するとすぐに有効になる
# (ログインのたびに current_app.config から読む)。

auth_bp = Blueprint("auth", __name__)

ADMIN_USERNAME = "admin"


def _check_config_admin(username, password):
    """instance/config.py の ADMIN_PASSWORD で固定ローカル管理者を確認する。

    戻り値: (確認したか, 認証結果)
      - ADMIN_PASSWORD が空、または admin 以外のID → (False, None) = ldap_client.py に任せる
      - admin で一致 → (True, 認証結果の dict)
      - admin で不一致 → (True, None) = ログイン不可(ldap_client.py 側の既定パスワードは使わせない)
    """
    expected = str(current_app.config.get("ADMIN_PASSWORD") or "")
    if not expected or username != ADMIN_USERNAME:
        return False, None
    # 比較時間から内容を推測されないよう hmac.compare_digest を使う
    if not hmac.compare_digest(str(password or "").encode("utf-8"), expected.encode("utf-8")):
        return True, None
    import ldap_client  # 本番環境ごとに差し替えるファイル(使うときに読み込む)

    local = getattr(ldap_client, "_LOCAL_ACCOUNTS", {}).get(ADMIN_USERNAME, {})
    return True, {
        "username": ADMIN_USERNAME,
        "display_name": local.get("display_name") or "管理者",
        "role": local.get("role") or ROLE_MANAGER,
        "source": "local",
    }


def _ensure_local_user(info):
    """固定ローカルアカウント(admin 等)は、アプリ未登録でも用意する(初期・緊急用)。"""
    user = User.query.filter_by(username=info["username"]).first()
    if user is None:
        user = User(username=info["username"])
        db.session.add(user)
    user.display_name = info["display_name"]
    user.role = info["role"]
    user.is_active = True
    db.session.commit()
    return user


def _match_registered_user(info):
    """LDAP認証済みのIDを『アプリに登録済み・有効』と突き合わせる。

    アプリ未登録 or 無効化 なら None(=ログイン不可)。
    登録済みなら氏名(display_name)は LDAP を正として同期し、
    役割(role)はアプリの登録(マネージャーがメンバー管理で設定)を正として維持する。
    """
    user = User.query.filter_by(username=info["username"]).first()
    if user is None or not user.is_active:
        return None
    user.display_name = info["display_name"]
    db.session.commit()
    return user


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    # すでにログイン済みならトップへ
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        # ① 本人確認: 固定ローカル管理者は instance/config.py で、
        #    それ以外は ldap_client.py の authenticate()(LDAP＋固定ローカル)で確認する
        checked, info = _check_config_admin(username, password)
        if not checked:
            import ldap_client  # 本番環境ごとに差し替えるファイル(使うときに読み込む)

            info = ldap_client.authenticate(username, password)
        if info is None:
            flash("IDまたはパスワードが正しくありません。", "danger")
            return render_template("auth/login.html", username=username)

        if info.get("source") == "local":
            # 固定ローカル管理者は常に許可(アプリ登録チェック免除)
            user = _ensure_local_user(info)
        else:
            # ② LDAPで実在確認できても、アプリ未登録/無効のIDはログインさせない
            user = _match_registered_user(info)
            if user is None:
                flash(
                    "このIDはアプリに登録されていません(または無効化されています)。"
                    "マネージャーにアカウント登録を依頼してください。", "danger"
                )
                return render_template("auth/login.html", username=username)

        login_user(user)
        flash(f"ようこそ、{user.display_name} さん。", "success")

        # ログイン前にアクセスしようとしていたページがあればそこへ戻す
        next_page = request.args.get("next")
        if next_page and next_page.startswith("/"):
            return redirect(next_page)
        return redirect(url_for("main.dashboard"))

    return render_template("auth/login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("ログアウトしました。", "info")
    return redirect(url_for("auth.login"))


# =============================================================================
# 5-2. トップページ(ダッシュボード)
# =============================================================================
# トップページ(ダッシュボード)のルーティング。
#
# 活動状況・ガントチャート・成果は、マネージャーダッシュボードと同じ集計処理を
# 「自分の担当分だけ」に絞って再利用している(マネージャーダッシュボード(5-7)の _build_*)。

main_bp = Blueprint("main", __name__)


@main_bp.route("/", endpoint="dashboard")
@login_required
def main_dashboard():
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


# =============================================================================
# 5-3. タスク
# =============================================================================
# タスク管理のルーティング(一覧・作成・詳細・編集・状態更新・削除・コメント)。
#
# 1つのタスクを複数のメンバーに割り当て可能。コメントでやり取りする。

tasks_bp = Blueprint("tasks", __name__, url_prefix="/tasks")

# 完了にするには成果(実績)が必要、という案内文(各所で共用)
_COMPLETE_NEEDS_OUTCOME = "「完了」にするには、成果(実績)の定量または定性のいずれかを入力してください。"


def _read_outcomes():
    """フォームから成果(定量・定性)欄を読み取る。返り値 (data, error)。

    定量の値は数値(カンマ・￥は無視)。不正な数値のときは error にメッセージを入れて返す。
    """
    def _num(field):
        raw = (request.form.get(field, "") or "").strip().replace(",", "").replace("￥", "")
        if raw == "":
            return None, False
        try:
            return float(raw), False
        except ValueError:
            return None, True

    est, est_bad = _num("outcome_quant_estimate")
    act, act_bad = _num("outcome_quant_actual")
    if est_bad:
        return None, "成果(定量)の見込みは数値で入力してください。"
    if act_bad:
        return None, "成果(定量)の実績は数値で入力してください。"

    def _unit(field):
        u = request.form.get(field, "") or None
        return u if u in OUTCOME_UNITS else None

    data = {
        "outcome_quant_estimate": est,
        "outcome_quant_estimate_unit": _unit("outcome_quant_estimate_unit"),
        "outcome_quant_actual": act,
        "outcome_quant_actual_unit": _unit("outcome_quant_actual_unit"),
        "outcome_quant_note": (request.form.get("outcome_quant_note", "") or "").strip() or None,
        "outcome_qual_estimate": (request.form.get("outcome_qual_estimate", "") or "").strip() or None,
        "outcome_qual_actual": (request.form.get("outcome_qual_actual", "") or "").strip() or None,
    }
    return data, None


def _outcomes_have_actual(data):
    """成果(実績)が定量・定性いずれかで入力されているか(完了の可否判定に使用)。"""
    return data["outcome_quant_actual"] is not None or bool(data["outcome_qual_actual"])


def _apply_outcomes(task, data):
    for key, value in data.items():
        setattr(task, key, value)


def _render_task_form(task, users, form, selected):
    return render_template(
        "tasks/form.html", task=task, users=users,
        status_choices=STATUS_CHOICES, priority_choices=PRIORITY_CHOICES,
        outcome_units=OUTCOME_UNITS, task_scales=TASK_SCALES,
        form=form, selected_assignees=selected,
        can_plan=current_user.is_manager,  # 計画系項目(優先度/日付/規模/担当者)を編集できるか
    )


def _read_scale():
    """フォームの規模を検証して返す(不正・未設定は None)。"""
    scale = request.form.get("scale") or None
    return scale if scale in TASK_SCALE_KEYS else None


def _log_status(task, status):
    """ステータス変更履歴を記録する(直近の記録と同じ状態なら追加しない)。

    ガントの棒を『ステータスを切り替えた日付』で色分けするために使う。
    """
    last = task.status_changes[-1].status if task.status_changes else None
    if status and status != last:
        task.status_changes.append(TaskStatusChange(status=status))


def _can_edit(task):
    """編集・削除の権限:作成者・担当者(いずれか)・マネージャーのみ。"""
    return (
        current_user.is_leader
        or task.creator_id == current_user.id
        or task.is_assigned_to(current_user)
    )


def _selected_assignees(users):
    """フォームの assignee_ids(複数)から担当ユーザーのリストを返す。"""
    ids = {int(x) for x in request.form.getlist("assignee_ids") if x.isdigit()}
    return [u for u in users if u.id in ids]


@tasks_bp.route("/")
@login_required
def list_tasks():
    # フィルタ条件を取得(ステータス・担当者はチェックボックスで複数選択可=OR条件)
    statuses = [s for s in request.args.getlist("status") if s in STATUS_CHOICES]
    assignee_ids = [
        int(a) for a in request.args.getlist("assignee") if a.isdigit()
    ]
    scope = request.args.get("scope", "")  # "mine" なら自分の担当のみ
    hide_done = request.args.get("hide_done") == "1"  # 「完了」を除く
    keyword = request.args.get("q", "").strip()

    query = Task.query

    if statuses:
        query = query.filter(Task.status.in_(statuses))
    if assignee_ids:
        query = query.filter(Task.assignees.any(User.id.in_(assignee_ids)))
    if scope == "mine":
        query = query.filter(Task.assignees.any(User.id == current_user.id))
    if hide_done:
        query = query.filter(Task.status != STATUS_DONE)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            db.or_(Task.title.ilike(like), Task.description.ilike(like))
        )

    # 未完了→期限が近い順、その後に完了タスク
    tasks = query.order_by(
        (Task.status == STATUS_DONE).asc(),
        Task.due_date.is_(None).asc(),
        Task.due_date.asc(),
        Task.id.desc(),
    ).all()

    return render_template(
        "tasks/list.html",
        tasks=tasks,
        users=get_active_users(),
        status_choices=STATUS_CHOICES,
        task_colors=STATUS_COLORS,
        priority_choices=PRIORITY_CHOICES,
        filters={
            "statuses": statuses, "assignees": assignee_ids,
            "scope": scope, "hide_done": hide_done, "q": keyword,
        },
    )


@tasks_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_task():
    # タスクの登録はマネージャーのみ(メンバーは不可)
    if not current_user.is_manager:
        flash("タスクを登録できるのはマネージャーのみです。", "danger")
        return redirect(url_for("tasks.list_tasks"))

    users = get_active_users()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        sel = [u.id for u in _selected_assignees(users)]
        if not title:
            flash("タイトルは必須です。", "danger")
            return _render_task_form(None, users, request.form, sel)

        data, err = _read_outcomes()
        if err:
            flash(err, "danger")
            return _render_task_form(None, users, request.form, sel)

        status = request.form.get("status") or STATUS_CHOICES[0]
        if status == STATUS_DONE and not _outcomes_have_actual(data):
            flash(_COMPLETE_NEEDS_OUTCOME, "danger")
            return _render_task_form(None, users, request.form, sel)

        task = Task(
            title=title,
            description=request.form.get("description", "").strip(),
            status=status,
            priority=request.form.get("priority") or PRIORITY_MID,
            start_date=parse_date(request.form.get("start_date")),
            due_date=parse_date(request.form.get("due_date")),
            scale=_read_scale(),
            creator_id=current_user.id,
        )
        _apply_outcomes(task, data)
        task.assignees = _selected_assignees(users)
        db.session.add(task)
        _log_status(task, task.status)  # 初期ステータスを履歴に記録
        db.session.commit()
        flash("タスクを登録しました。", "success")
        return redirect(url_for("tasks.detail", task_id=task.id))

    return _render_task_form(None, users, None, [])


@tasks_bp.route("/<int:task_id>", endpoint="detail")
@login_required
def task_detail(task_id):
    task = db.session.get(Task, task_id)
    if task is None:
        abort(404)
    return render_template("tasks/detail.html", task=task, can_edit=_can_edit(task))


@tasks_bp.route("/<int:task_id>/edit", methods=["GET", "POST"])
@login_required
def edit_task(task_id):
    task = db.session.get(Task, task_id)
    if task is None:
        abort(404)
    if not _can_edit(task):
        flash("このタスクを編集する権限がありません。", "danger")
        return redirect(url_for("tasks.detail", task_id=task.id))

    users = get_active_users()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        sel = [u.id for u in _selected_assignees(users)]
        if not title:
            flash("タイトルは必須です。", "danger")
            return _render_task_form(task, users, request.form, sel)

        data, err = _read_outcomes()
        if err:
            flash(err, "danger")
            return _render_task_form(task, users, request.form, sel)

        status = request.form.get("status") or task.status
        # 「完了」への変更時のみ実績を必須に(既に完了のタスクの編集は妨げない)
        if status == STATUS_DONE and task.status != STATUS_DONE and not _outcomes_have_actual(data):
            flash(_COMPLETE_NEEDS_OUTCOME, "danger")
            return _render_task_form(task, users, request.form, sel)

        task.title = title
        task.description = request.form.get("description", "").strip()
        task.status = status
        _log_status(task, task.status)  # 変更されていれば履歴に記録
        # 計画系の項目(優先度/開始日/期限/規模/担当者)はマネージャーのみ変更可。
        # メンバーは担当タスクの状況・内容・成果のみ更新でき、既存値を保持する。
        if current_user.is_manager:
            task.priority = request.form.get("priority") or task.priority
            task.start_date = parse_date(request.form.get("start_date"))
            task.due_date = parse_date(request.form.get("due_date"))
            task.scale = _read_scale()
            task.assignees = _selected_assignees(users)
        _apply_outcomes(task, data)
        db.session.commit()
        flash("タスクを更新しました。", "success")
        return redirect(url_for("tasks.detail", task_id=task.id))

    return _render_task_form(task, users, None, [u.id for u in task.assignees])


@tasks_bp.route("/<int:task_id>/status", methods=["POST"])
@login_required
def update_status(task_id):
    """一覧/詳細からワンクリックでステータスを変更する。"""
    task = db.session.get(Task, task_id)
    if task is None:
        abort(404)
    if not _can_edit(task):
        flash("このタスクを更新する権限がありません。", "danger")
        return redirect(request.referrer or url_for("tasks.list_tasks"))

    new_status = request.form.get("status")
    if new_status in STATUS_CHOICES:
        if new_status == STATUS_DONE and task.status != STATUS_DONE and not task.has_outcome_actual:
            flash(_COMPLETE_NEEDS_OUTCOME + "(タスクの編集画面から入力できます)", "warning")
        else:
            task.status = new_status
            _log_status(task, new_status)  # 変更日を履歴に記録(ガントの色分けに使用)
            db.session.commit()
            flash(f"ステータスを「{new_status}」に変更しました。", "success")
    return redirect(request.referrer or url_for("tasks.list_tasks"))


@tasks_bp.route("/<int:task_id>/comment", methods=["POST"])
@login_required
def add_comment(task_id):
    """進捗状況の記載。担当者・作成者・マネージャーのみ(担当外のメンバーは不可)。"""
    task = db.session.get(Task, task_id)
    if task is None:
        abort(404)
    if not _can_edit(task):
        flash("進捗状況を記載できるのは担当者・マネージャーのみです。", "danger")
        return redirect(url_for("tasks.detail", task_id=task.id))
    body = request.form.get("body", "").strip()
    if body:
        db.session.add(
            TaskComment(task_id=task.id, user_id=current_user.id, body=body)
        )
        db.session.commit()
    return redirect(url_for("tasks.detail", task_id=task.id))


def _can_edit_comment(comment):
    """進捗状況の記載内容を変更できるか:記載者本人・マネージャーのみ。

    進捗状況は「誰が何をしたか」の記録なので、他人の記載は書き換えさせない。
    """
    return current_user.is_manager or comment.user_id == current_user.id


@tasks_bp.route("/<int:task_id>/comment/<int:comment_id>/edit", methods=["POST"])
@login_required
def edit_comment(task_id, comment_id):
    """進捗状況の記載内容を変更する。記載者本人・マネージャーのみ。"""
    task = db.session.get(Task, task_id)
    if task is None:
        abort(404)
    comment = db.session.get(TaskComment, comment_id)
    if comment is None or comment.task_id != task.id:
        abort(404)
    if not _can_edit_comment(comment):
        flash("進捗状況を変更できるのは記載者本人・マネージャーのみです。", "danger")
        return redirect(url_for("tasks.detail", task_id=task.id))

    body = request.form.get("body", "").strip()
    if not body:
        flash("進捗状況の内容を入力してください。", "danger")
    else:
        comment.body = body
        db.session.commit()
        flash("進捗状況を更新しました。", "success")
    return redirect(url_for("tasks.detail", task_id=task.id))


@tasks_bp.route("/<int:task_id>/delete", methods=["POST"])
@login_required
def delete_task(task_id):
    task = db.session.get(Task, task_id)
    if task is None:
        abort(404)
    # 削除はマネージャーのみ(担当メンバーは編集・状態変更は可、削除は不可)
    if not current_user.is_manager:
        flash("タスクを削除できるのはマネージャーのみです。", "danger")
        return redirect(url_for("tasks.detail", task_id=task.id))

    db.session.delete(task)
    db.session.commit()
    flash("タスクを削除しました。", "info")
    return redirect(url_for("tasks.list_tasks"))


# =============================================================================
# 5-4. 定型・定期業務
# =============================================================================
# 定型・定期業務のルーティング。
#
# マネージャー・メンバーの全員が登録・編集・削除できる(権限による制限なし)。

routine_bp = Blueprint("routine", __name__, url_prefix="/routine")


def _person_summary():
    """ヒト別の集計(全データ対象): 総件数・総合計時間(月,分)・手順書 完/未完 件数。

    返り値 (rows, totals)。rows は担当者名順。担当者が無効化されていても計上する。
    """
    summary = {}
    for rw in RoutineWork.query.all():
        s = summary.get(rw.assignee_id)
        if s is None:
            s = summary[rw.assignee_id] = {
                "assignee": rw.assignee, "count": 0, "minutes": 0, "done": 0, "undone": 0,
            }
        s["count"] += 1
        s["minutes"] += rw.monthly_minutes or 0
        if rw.manual_status == MANUAL_DONE:
            s["done"] += 1
        else:
            s["undone"] += 1
    rows = sorted(
        summary.values(),
        key=lambda x: x["assignee"].display_name if x["assignee"] else "",
    )
    totals = {"count": 0, "minutes": 0, "done": 0, "undone": 0}
    for s in rows:
        for k in totals:
            totals[k] += s[k]
    return rows, totals


def _to_int(value):
    value = (value or "").strip()
    return int(value) if value.isdigit() else None


def _get_routine_or_404(routine_id):
    r = db.session.get(RoutineWork, routine_id)
    if r is None:
        abort(404)
    return r


def _can_edit_routine(rw):
    """編集できるか:マネージャー、または自分が担当のもの(メンバーは自分の分のみ)。"""
    return current_user.is_manager or rw.assignee_id == current_user.id


def _assignee_users():
    """担当者の選択肢。メンバーは自分のみ、マネージャーは全員。"""
    return get_active_users() if current_user.is_manager else [current_user]


def _forced_assignee_id():
    """メンバーは担当者を自分に固定する(マネージャーはNone=フォームの選択に従う)。"""
    return None if current_user.is_manager else current_user.id


def _fill_from_form(rw, form, forced_assignee_id=None):
    """フォーム値を rw に反映。エラーメッセージのリストを返す。

    forced_assignee_id を渡すと担当者はそれに固定(メンバーの自分固定に使う)。
    """
    errors = []
    name = form.get("name", "").strip()
    if not name:
        errors.append("業務名は必須です。")

    if forced_assignee_id is not None:
        assignee_id = str(forced_assignee_id)
    else:
        assignee_id = form.get("assignee_id", "")
        if not assignee_id.isdigit():
            errors.append("担当者を選択してください。")

    if errors:
        return errors

    unit = form.get("frequency_unit") or FREQ_MONTH
    if unit not in FREQ_UNIT_CHOICES:
        unit = FREQ_MONTH
    manual = form.get("manual_status") or MANUAL_UNDONE
    if manual not in MANUAL_CHOICES:
        manual = MANUAL_UNDONE

    rw.name = name
    rw.assignee_id = int(assignee_id)
    rw.purpose = form.get("purpose", "").strip()
    rw.frequency_count = _to_int(form.get("frequency_count"))
    rw.frequency_unit = unit
    rw.minutes_per = _to_int(form.get("minutes_per"))
    rw.content = form.get("content", "").strip()
    rw.manual_status = manual
    return []


# --------------------------------------------------------------------------- #
# 一覧
# --------------------------------------------------------------------------- #
@routine_bp.route("/")
@login_required
def list_routines():
    assignee_id = request.args.get("assignee", "")
    manual = request.args.get("manual", "")
    scope = request.args.get("scope", "")
    keyword = request.args.get("q", "").strip()

    query = RoutineWork.query
    if assignee_id.isdigit():
        query = query.filter(RoutineWork.assignee_id == int(assignee_id))
    if scope == "mine":
        query = query.filter(RoutineWork.assignee_id == current_user.id)
    if manual in MANUAL_CHOICES:
        query = query.filter(RoutineWork.manual_status == manual)
    if keyword:
        like = f"%{keyword}%"
        query = query.filter(
            db.or_(RoutineWork.name.ilike(like), RoutineWork.content.ilike(like))
        )

    routines = query.order_by(RoutineWork.assignee_id, RoutineWork.id.desc()).all()

    summary_rows, summary_totals = _person_summary()

    return render_template(
        "routine/list.html",
        routines=routines,
        users=get_active_users(),
        manual_choices=MANUAL_CHOICES,
        summary_rows=summary_rows,
        summary_totals=summary_totals,
        filters={"assignee": assignee_id, "manual": manual, "scope": scope, "q": keyword},
    )


# --------------------------------------------------------------------------- #
# 新規登録
# --------------------------------------------------------------------------- #
@routine_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_routine():
    users = _assignee_users()  # メンバーは自分のみ選択可
    if request.method == "POST":
        rw = RoutineWork(creator_id=current_user.id)
        errors = _fill_from_form(rw, request.form, forced_assignee_id=_forced_assignee_id())
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template(
                "routine/form.html", routine=None, users=users,
                freq_choices=FREQ_UNIT_CHOICES, manual_choices=MANUAL_CHOICES,
                form=request.form,
            )
        db.session.add(rw)
        db.session.commit()
        flash("定型・定期業務を登録しました。", "success")
        return redirect(url_for("routine.detail", routine_id=rw.id))

    return render_template(
        "routine/form.html", routine=None, users=users,
        freq_choices=FREQ_UNIT_CHOICES, manual_choices=MANUAL_CHOICES, form=None,
    )


# --------------------------------------------------------------------------- #
# 詳細
# --------------------------------------------------------------------------- #
@routine_bp.route("/<int:routine_id>", endpoint="detail")
@login_required
def routine_detail(routine_id):
    rw = _get_routine_or_404(routine_id)
    return render_template("routine/detail.html", routine=rw, can_edit=_can_edit_routine(rw))


# --------------------------------------------------------------------------- #
# 編集(マネージャー、または自分が担当のもの。メンバーは自分の分のみ)
# --------------------------------------------------------------------------- #
@routine_bp.route("/<int:routine_id>/edit", methods=["GET", "POST"])
@login_required
def edit_routine(routine_id):
    rw = _get_routine_or_404(routine_id)
    if not _can_edit_routine(rw):
        flash("この定型・定期業務を編集できるのは担当者・マネージャーのみです。", "danger")
        return redirect(url_for("routine.detail", routine_id=rw.id))
    users = _assignee_users()
    if request.method == "POST":
        errors = _fill_from_form(rw, request.form, forced_assignee_id=_forced_assignee_id())
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template(
                "routine/form.html", routine=rw, users=users,
                freq_choices=FREQ_UNIT_CHOICES, manual_choices=MANUAL_CHOICES,
                form=request.form,
            )
        db.session.commit()
        flash("定型・定期業務を更新しました。", "success")
        return redirect(url_for("routine.detail", routine_id=rw.id))

    return render_template(
        "routine/form.html", routine=rw, users=users,
        freq_choices=FREQ_UNIT_CHOICES, manual_choices=MANUAL_CHOICES, form=None,
    )


# --------------------------------------------------------------------------- #
# 削除(マネージャーのみ。登録・編集は全員可)
# --------------------------------------------------------------------------- #
@routine_bp.route("/<int:routine_id>/delete", methods=["POST"])
@login_required
def delete_routine(routine_id):
    rw = _get_routine_or_404(routine_id)
    if not current_user.is_manager:
        flash("定型・定期業務を削除できるのはマネージャーのみです。", "danger")
        return redirect(url_for("routine.detail", routine_id=rw.id))
    db.session.delete(rw)
    db.session.commit()
    flash("定型・定期業務を削除しました。", "info")
    return redirect(url_for("routine.list_routines"))


# =============================================================================
# 5-5. 年休
# =============================================================================
# 年休(有給休暇)の予定のルーティング。
#
# チーム内の情報共有・見える化が目的。承認フローは無し(登録=即共有)。
# 1レコード=1取得日。種別は 全休/午前半休/午後半休。
# チーム(Department)は兼務対応の多対多。同日に同じチームで休む人数が多いと調整を促す。
# 取消は本人のみ。

leaves_bp = Blueprint("leaves", __name__, url_prefix="/leaves")

CALENDAR_WEEKDAY_LABELS = ["日", "月", "火", "水", "木", "金", "土"]


# --------------------------------------------------------------------------- #
# 権限ヘルパー(取消・編集は本人のみ)
# --------------------------------------------------------------------------- #
def _can_modify_leave(leave):
    return leave.user_id == current_user.id


def _get_leave_or_404(leave_id):
    leave = db.session.get(LeaveRequest, leave_id)
    if leave is None:
        abort(404)
    return leave


def _duplicate_on(user_id, leave_date, exclude_id=None):
    """同一ユーザー・同一取得日の既存レコードを返す(無ければNone)。

    1日に複数登録すると換算日数が二重計上されるため、登録/更新時に弾く。
    """
    q = LeaveRequest.query.filter_by(user_id=user_id, leave_date=leave_date)
    if exclude_id:
        q = q.filter(LeaveRequest.id != exclude_id)
    return q.first()


def _active_departments():
    return Department.query.filter_by(is_active=True).order_by(Department.sort_order, Department.name).all()


# --------------------------------------------------------------------------- #
# 同日上限の超過判定・登録時メッセージ
# --------------------------------------------------------------------------- #
def _is_overbooked(user, leave_date, exclude_id=None):
    """本人の所属チーム(有効なもの)のいずれかで、同日に休む人数が上限を超えるか。"""
    # 無効化されたチームは判定対象外(カレンダーの警告と基準を揃える)
    depts = [d for d in user.departments if d.is_active]
    if not depts:
        return False
    q = LeaveRequest.query.filter(LeaveRequest.leave_date == leave_date)
    if exclude_id:
        q = q.filter(LeaveRequest.id != exclude_id)
    others = q.all()
    for dept in depts:
        member_ids = {u.id for u in dept.users}
        off_ids = {lv.user_id for lv in others if lv.user_id in member_ids}
        off_ids.add(user.id)  # 本人ぶん
        if len(off_ids) > LEAVE_DAILY_LIMIT:
            return True
    return False


def _registration_messages(user, leave_date, exclude_id=None):
    """登録/更新後に出すメッセージ(同日上限・今週連絡)をflashする。"""
    if _is_overbooked(user, leave_date, exclude_id=exclude_id):
        flash(
            "チーム内（マネージャー・メンバー）で業務影響ないよう事前にすり合わせて登録するようお願いします。",
            "warning",
        )
    # 今週(月〜日)の取得なら、チャット/メール/口頭での連絡を促す
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    if monday <= leave_date <= sunday:
        flash(
            "今週の取得です。チャット・メール・口頭のいずれかで関係者へ連絡をお願いします。",
            "info",
        )


# --------------------------------------------------------------------------- #
# カレンダー(既定ビュー)
# --------------------------------------------------------------------------- #
def _build_weeks(year, month, dept_id=None):
    cal = calendar.Calendar(firstweekday=6)  # 日曜始まり
    weeks_dates = cal.monthdatescalendar(year, month)
    first, last = weeks_dates[0][0], weeks_dates[-1][-1]

    leaves = LeaveRequest.query.filter(
        LeaveRequest.leave_date >= first, LeaveRequest.leave_date <= last
    ).all()

    # チームフィルタ
    if dept_id:
        dept = db.session.get(Department, dept_id)
        member_ids = {u.id for u in dept.users} if dept else set()
        leaves = [lv for lv in leaves if lv.user_id in member_ids]

    # チームごとのメンバー(同日上限の判定用)
    dept_member_ids = {d.id: {u.id for u in d.users} for d in _active_departments()}

    by_date = {}
    for lv in leaves:
        by_date.setdefault(lv.leave_date, []).append(lv)

    today = date.today()
    weeks = []
    for wk in weeks_dates:
        row = []
        for d in wk:
            day_leaves = by_date.get(d, [])
            off_ids = {lv.user_id for lv in day_leaves}
            if dept_id:
                warn = len(off_ids) > LEAVE_DAILY_LIMIT
            else:
                warn = any(
                    len(off_ids & mids) > LEAVE_DAILY_LIMIT
                    for mids in dept_member_ids.values()
                )
            row.append(
                {
                    "date": d,
                    "in_month": d.month == month,
                    "is_today": d == today,
                    "weekday": d.weekday(),
                    "is_weekend": d.weekday() >= 5,
                    "leaves": day_leaves,
                    "warn": warn,
                }
            )
        weeks.append(row)
    return weeks


@leaves_bp.route("/")
@login_required
def calendar_view():
    today = date.today()
    try:
        year = int(request.args.get("year", today.year))
        month = int(request.args.get("month", today.month))
        if not (1 <= month <= 12):
            raise ValueError
    except (TypeError, ValueError):
        year, month = today.year, today.month

    dept_raw = request.args.get("dept", "")
    dept_id = int(dept_raw) if dept_raw.isdigit() else None
    weeks = _build_weeks(year, month, dept_id)

    prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)

    return render_template(
        "leaves/calendar.html",
        weeks=weeks,
        year=year,
        month=month,
        weekday_labels=CALENDAR_WEEKDAY_LABELS,
        departments=_active_departments(),
        dept_id=dept_id,
        prev=(prev_year, prev_month),
        next=(next_year, next_month),
        today=today,
        daily_limit=LEAVE_DAILY_LIMIT,
    )


# --------------------------------------------------------------------------- #
# 一覧
# --------------------------------------------------------------------------- #
@leaves_bp.route("/list")
@login_required
def list_leaves():
    user_id = request.args.get("user", "")
    scope = request.args.get("scope", "")
    date_from = parse_date(request.args.get("from"))
    date_to = parse_date(request.args.get("to"))

    query = LeaveRequest.query
    if user_id.isdigit():
        query = query.filter(LeaveRequest.user_id == int(user_id))
    if scope == "mine":
        query = query.filter(LeaveRequest.user_id == current_user.id)
    if date_from:
        query = query.filter(LeaveRequest.leave_date >= date_from)
    if date_to:
        query = query.filter(LeaveRequest.leave_date <= date_to)

    leaves = query.order_by(LeaveRequest.leave_date.desc(), LeaveRequest.id.desc()).all()
    total_days = round(sum(lv.day_count for lv in leaves), 2)

    users = User.query.filter_by(is_active=True).order_by(User.display_name).all()

    return render_template(
        "leaves/list.html",
        leaves=leaves,
        users=users,
        filters={
            "user": user_id,
            "scope": scope,
            "from": request.args.get("from", ""),
            "to": request.args.get("to", ""),
        },
        total_days=total_days,
    )


# --------------------------------------------------------------------------- #
# 新規登録
# --------------------------------------------------------------------------- #
@leaves_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_leave():
    if request.method == "POST":
        leave_date = parse_date(request.form.get("leave_date"))
        leave_type = request.form.get("leave_type") or LEAVE_FULL
        if leave_type not in LEAVE_TYPE_CHOICES:
            leave_type = LEAVE_FULL

        if leave_date is None:
            flash("取得日を入力してください。", "danger")
            return render_template(
                "leaves/form.html", leave=None,
                type_choices=LEAVE_TYPE_CHOICES, daily_limit=LEAVE_DAILY_LIMIT,
                form=request.form,
            )

        dup = _duplicate_on(current_user.id, leave_date)
        if dup:
            flash("その取得日の年休は既に登録されています。", "warning")
            return redirect(url_for("leaves.detail", leave_id=dup.id))

        leave = LeaveRequest(
            user_id=current_user.id, leave_date=leave_date, leave_type=leave_type
        )
        db.session.add(leave)
        db.session.commit()
        flash("年休を登録しました。", "success")
        _registration_messages(current_user, leave_date, exclude_id=leave.id)
        return redirect(url_for("leaves.calendar_view", year=leave_date.year, month=leave_date.month))

    return render_template(
        "leaves/form.html", leave=None,
        type_choices=LEAVE_TYPE_CHOICES, daily_limit=LEAVE_DAILY_LIMIT, form=None,
    )


# --------------------------------------------------------------------------- #
# 詳細
# --------------------------------------------------------------------------- #
@leaves_bp.route("/<int:leave_id>", endpoint="detail")
@login_required
def leave_detail(leave_id):
    leave = _get_leave_or_404(leave_id)
    return render_template(
        "leaves/detail.html", leave=leave, can_modify=_can_modify_leave(leave)
    )


# --------------------------------------------------------------------------- #
# 編集(本人のみ)
# --------------------------------------------------------------------------- #
@leaves_bp.route("/<int:leave_id>/edit", methods=["GET", "POST"])
@login_required
def edit_leave(leave_id):
    leave = _get_leave_or_404(leave_id)
    if not _can_modify_leave(leave):
        flash("年休を編集できるのは本人のみです。", "danger")
        return redirect(url_for("leaves.detail", leave_id=leave.id))

    if request.method == "POST":
        leave_date = parse_date(request.form.get("leave_date"))
        leave_type = request.form.get("leave_type") or LEAVE_FULL
        if leave_type not in LEAVE_TYPE_CHOICES:
            leave_type = LEAVE_FULL
        if leave_date is None:
            flash("取得日を入力してください。", "danger")
            return render_template(
                "leaves/form.html", leave=leave,
                type_choices=LEAVE_TYPE_CHOICES, daily_limit=LEAVE_DAILY_LIMIT,
                form=request.form,
            )
        dup = _duplicate_on(current_user.id, leave_date, exclude_id=leave.id)
        if dup:
            flash("その取得日の年休は既に登録されています。", "warning")
            return redirect(url_for("leaves.detail", leave_id=dup.id))
        leave.leave_date = leave_date
        leave.leave_type = leave_type
        db.session.commit()
        flash("年休を更新しました。", "success")
        _registration_messages(current_user, leave_date, exclude_id=leave.id)
        return redirect(url_for("leaves.detail", leave_id=leave.id))

    return render_template(
        "leaves/form.html", leave=leave,
        type_choices=LEAVE_TYPE_CHOICES, daily_limit=LEAVE_DAILY_LIMIT, form=None,
    )


# --------------------------------------------------------------------------- #
# 取消(本人のみ)
# --------------------------------------------------------------------------- #
@leaves_bp.route("/<int:leave_id>/cancel", methods=["POST"])
@login_required
def cancel_leave(leave_id):
    leave = _get_leave_or_404(leave_id)
    if not _can_modify_leave(leave):
        flash("年休を取消できるのは本人のみです。", "danger")
        return redirect(url_for("leaves.detail", leave_id=leave.id))
    db.session.delete(leave)
    db.session.commit()
    flash("年休を取消しました。", "info")
    return redirect(url_for("leaves.calendar_view"))


# =============================================================================
# 5-6. スキル管理
# =============================================================================
# スキル管理のルーティング。
#
# スキルの閲覧・編集はいずれもマネージャーのみ(メンバーは before_request で403)。
# スキルマップ(マトリクス)、個人スキル、項目定義、到達度の設定を扱う。

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


# =============================================================================
# 5-7. マネージャーダッシュボード
# =============================================================================
# マネージャー(manager)向けダッシュボードのルーティング。
#
# マネージャーのみアクセス可。チーム全体を俯瞰する読み取り専用の集計ビュー。年休は事由を出さない。

manager_bp = Blueprint("manager", __name__, url_prefix="/manager")

# ヒト別 月間負荷(目安工数h)の水準。フルタイム≒160h/月 を基準に色分け。
_LOAD_FULL = 160


def _load_level(total_h):
    if total_h >= _LOAD_FULL:
        return {"label": "高", "color": "danger", "pct": min(100, round(total_h / _LOAD_FULL * 100))}
    if total_h >= _LOAD_FULL / 2:
        return {"label": "中", "color": "warning", "pct": round(total_h / _LOAD_FULL * 100)}
    return {"label": "低", "color": "success", "pct": round(total_h / _LOAD_FULL * 100)}


def _build_workload(today, users):
    """ヒト別の負荷(月間目安工数h)と案件状況を集計する。

    タスク: 規模を実働工数に換算→期間で月あたりに配分(複数担当は均等割り)。未完了のみ。
    定型・定期業務: 月間工数(monthly_minutes)。両者を合算して月間負荷(h)を出す。
    """
    load = {
        u.id: {
            "user": u, "doing": 0, "todo": 0, "hold": 0, "overdue": 0,
            "task_h": 0.0, "routine_cnt": 0, "routine_min": 0,
        }
        for u in users
    }

    for t in Task.query.filter(Task.status != STATUS_DONE).all():
        assignees = [u for u in t.assignees if u.id in load]
        n = len(assignees)
        if n == 0:
            continue
        share = t.scale_monthly_hours / n  # 複数担当は均等割り
        overdue = bool(t.due_date and t.due_date < today)
        for u in assignees:
            d = load[u.id]
            if t.status == STATUS_DOING:
                d["doing"] += 1
            elif t.status == STATUS_TODO:
                d["todo"] += 1
            elif t.status == STATUS_HOLD:
                d["hold"] += 1
            if overdue:
                d["overdue"] += 1
            d["task_h"] += share

    for rw in RoutineWork.query.all():
        d = load.get(rw.assignee_id)
        if d is None:
            continue
        d["routine_cnt"] += 1
        d["routine_min"] += rw.monthly_minutes or 0

    rows = []
    for u in users:
        d = load[u.id]
        task_h = round(d["task_h"], 1)
        routine_h = round(d["routine_min"] / 60.0, 1)
        total_h = round(task_h + routine_h, 1)
        rows.append({
            "user": u, "doing": d["doing"], "todo": d["todo"], "hold": d["hold"],
            "overdue": d["overdue"], "task_open": d["doing"] + d["todo"] + d["hold"],
            "task_h": task_h, "routine_cnt": d["routine_cnt"],
            "routine_h": routine_h, "total_h": total_h,
            "spare": round(_LOAD_FULL - total_h, 1),  # 余力(フルタイム160h/月に対する残り。負=超過)
            "level": _load_level(total_h),
        })
    rows.sort(key=lambda r: r["total_h"], reverse=True)

    totals = {
        "task_open": sum(r["task_open"] for r in rows),
        "overdue": sum(r["overdue"] for r in rows),
        "task_h": round(sum(r["task_h"] for r in rows), 1),
        "routine_cnt": sum(r["routine_cnt"] for r in rows),
        "routine_h": round(sum(r["routine_h"] for r in rows), 1),
        "total_h": round(sum(r["total_h"] for r in rows), 1),
        "spare": round(sum(r["spare"] for r in rows), 1),
    }
    return rows, totals


# 成果(定量)の単位を「年あたり」に換算する係数。
# 1年=12ヶ月=360日(定型・定期業務の 30日/月 換算に合わせる)。
_OUTCOME_YEAR_FACTOR = {"年": 1, "月": 12, "日": 360}
_OUTCOME_MONEY = "￥"
_OUTCOME_HOUR = "ｈ"


def _annualize(value, unit):
    """成果(値＋単位)を (種別, 年換算値) にする。判定できないものは (None, 0)。"""
    if value is None or not unit:
        return None, 0.0
    kind, _sep, period = unit.partition("/")
    factor = _OUTCOME_YEAR_FACTOR.get(period)
    if factor is None or kind not in (_OUTCOME_MONEY, _OUTCOME_HOUR):
        return None, 0.0
    return kind, float(value) * factor


def _build_activity(today, users, include_unassigned=True):
    """活動状況(進捗記載)を「タスクの担当者」別 → タスク別 → 時系列にまとめる。

    記載者ではなく担当者の枠に出す(複数担当なら各担当の枠に重複表示)。
    期間は afrom/ato(既定=直近7日)。個人ダッシュボードでは users に本人だけを渡す。
    """
    act_from = parse_date(request.args.get("afrom")) or (today - timedelta(days=6))
    act_to = parse_date(request.args.get("ato")) or today
    if act_to < act_from:
        act_from, act_to = act_to, act_from

    act_comments = (
        TaskComment.query.filter(
            TaskComment.created_at >= datetime.combine(act_from, time.min),
            TaskComment.created_at <= datetime.combine(act_to, time.max),
        )
        .order_by(TaskComment.created_at.asc())  # タスク内は時系列(古い→新しい)
        .all()
    )

    def group_by_task(comments):
        task_map = {}  # task_id -> {"task":.., "comments":[...]}
        for c in comments:
            grp = task_map.get(c.task_id)
            if grp is None:
                grp = {"task": c.task, "comments": []}
                task_map[c.task_id] = grp
            grp["comments"].append(c)
        return sorted(
            task_map.values(),
            key=lambda g: g["comments"][-1].created_at, reverse=True,
        )

    rows = []
    for u in users:
        mine = [
            c for c in act_comments
            if c.task is not None and c.task.is_assigned_to(u)
        ]
        rows.append({"user": u, "label": u.display_name, "tasks": group_by_task(mine)})

    # 担当者未割当のタスクへの記載はどの枠にも出ないため、別枠でまとめる
    if include_unassigned:
        unassigned = [
            c for c in act_comments
            if c.task is not None and not c.task.assignees
        ]
        if unassigned:
            rows.append({
                "user": None, "label": "担当者未割当のタスク",
                "tasks": group_by_task(unassigned),
            })

    return {"activity_rows": rows, "act_from": act_from, "act_to": act_to}


def _build_outcomes(today, users, only_user_id=None):
    """成果(見込み・実績)をヒト別・全体で集計する。

    only_user_id を渡すと、その人が担当のタスクだけを集計する(個人ダッシュボード用)。
    按分はマネージャー画面と揃えるため、担当者数で割った値をそのまま使う。

    - 金額(￥)と時間(ｈ)は足せないので分けて集計し、いずれも年換算で揃える
    - 期間は「期限日(未設定なら開始日)」を基準に絞り込む(既定=今年)
    - 複数担当のタスクは負荷集計と同じく担当者で均等割り
    """
    ofrom = parse_date(request.args.get("ofrom")) or date(today.year, 1, 1)
    oto = parse_date(request.args.get("oto")) or date(today.year, 12, 31)
    if oto < ofrom:
        ofrom, oto = oto, ofrom

    def blank(user, label):
        return {
            "user": user, "label": label, "money_est": 0.0, "money_act": 0.0,
            "hour_est": 0.0, "hour_act": 0.0, "tasks": 0,
        }

    acc = {u.id: blank(u, u.display_name) for u in users}
    unassigned = blank(None, "未割当")
    qual_rows = []   # 定性成果(記載のあるタスク)
    undated = 0      # 期限・開始日が無く集計対象外になったタスク
    no_unit = 0      # 数値はあるが単位未選択で金額/時間に振り分けられないタスク
    counted = set()  # 合計の件数用(複数担当でも1件と数える)

    for t in Task.query.all():
        # 個人ダッシュボードでは自分が担当のタスクだけを対象にする
        if only_user_id is not None and not any(u.id == only_user_id for u in t.assignees):
            continue

        basis = t.due_date or t.start_date
        if basis is None:
            if (t.outcome_quant_estimate is not None
                    or t.outcome_quant_actual is not None
                    or t.outcome_qual_estimate or t.outcome_qual_actual):
                undated += 1
            continue
        if not (ofrom <= basis <= oto):
            continue

        e_kind, e_val = _annualize(t.outcome_quant_estimate, t.outcome_quant_estimate_unit)
        a_kind, a_val = _annualize(t.outcome_quant_actual, t.outcome_quant_actual_unit)
        has_qual = bool(t.outcome_qual_estimate or t.outcome_qual_actual)
        # 数値はあるのに単位が未選択だと金額/時間に振り分けられない(集計外)
        if ((t.outcome_quant_estimate is not None and e_kind is None)
                or (t.outcome_quant_actual is not None and a_kind is None)):
            no_unit += 1
        if e_kind is None and a_kind is None and not has_qual:
            continue  # 成果の記載が無いタスクは対象外

        assigned = [acc[u.id] for u in t.assignees if u.id in acc]
        if only_user_id is not None:
            # 按分の分母は全担当者数のまま(マネージャー画面と同じ値)、計上先は本人のみ
            targets = [acc[only_user_id]] if only_user_id in acc else []
            n = len(assigned) or 1
        else:
            targets = assigned or [unassigned]
            n = len(targets)
        if not targets:
            continue

        counted.add(t.id)
        for d in targets:
            d["tasks"] += 1
            if e_kind == _OUTCOME_MONEY:
                d["money_est"] += e_val / n
            elif e_kind == _OUTCOME_HOUR:
                d["hour_est"] += e_val / n
            if a_kind == _OUTCOME_MONEY:
                d["money_act"] += a_val / n
            elif a_kind == _OUTCOME_HOUR:
                d["hour_act"] += a_val / n

        if has_qual:
            qual_rows.append({
                "task": t,
                "estimate": t.outcome_qual_estimate,
                "actual": t.outcome_qual_actual,
            })

    rows = [d for d in acc.values() if d["tasks"]]
    if unassigned["tasks"]:
        rows.append(unassigned)

    def rate(act, est):
        return round(act / est * 100) if est else None

    for d in rows:
        d["money_diff"] = round(d["money_act"] - d["money_est"], 1)
        d["hour_diff"] = round(d["hour_act"] - d["hour_est"], 1)
        d["money_rate"] = rate(d["money_act"], d["money_est"])
        d["hour_rate"] = rate(d["hour_act"], d["hour_est"])
    rows.sort(key=lambda d: (d["money_act"], d["hour_act"]), reverse=True)

    totals = {
        "tasks": len(counted),  # 複数担当でも1件(ヒト別の件数は各担当に計上)
        "money_est": sum(d["money_est"] for d in rows),
        "money_act": sum(d["money_act"] for d in rows),
        "hour_est": sum(d["hour_est"] for d in rows),
        "hour_act": sum(d["hour_act"] for d in rows),
    }
    totals["money_diff"] = round(totals["money_act"] - totals["money_est"], 1)
    totals["hour_diff"] = round(totals["hour_act"] - totals["hour_est"], 1)
    totals["money_rate"] = rate(totals["money_act"], totals["money_est"])
    totals["hour_rate"] = rate(totals["hour_act"], totals["hour_est"])

    # グラフの横幅を揃えるための最大値
    money_max = max([max(d["money_est"], d["money_act"]) for d in rows] or [0])
    hour_max = max([max(d["hour_est"], d["hour_act"]) for d in rows] or [0])

    qual_rows.sort(key=lambda q: (q["task"].due_date or q["task"].start_date), reverse=True)

    return {
        "o_rows": rows, "o_totals": totals,
        "o_money_max": money_max, "o_hour_max": hour_max,
        "o_from": ofrom, "o_to": oto,
        "o_qual": qual_rows, "o_undated": undated, "o_no_unit": no_unit,
    }


def _build_gantt(today, only_user_id=None):
    """全タスクのガントチャート用データを組み立てる(ダッシュボード内蔵・全画面で共用)。

    only_user_id を渡すと、その人が担当のタスクだけに絞る(個人ダッシュボード用)。

    - 棒はステータス変更履歴に沿って日付ごとに色分け(segments)
    - 完了以外で期限超過は overdue(カミナリ線)
    - 進捗記載(コメント)日には marks(印＋ツールチップ)
    - 期間(gfrom/gto)・担当者(gassignee)・完了非表示(ghide)・ソート(gsort/gdir)に対応
    """
    gfrom = parse_date(request.args.get("gfrom")) or (today - timedelta(days=7))
    gto = parse_date(request.args.get("gto")) or (today + timedelta(days=28))
    if gto < gfrom:
        gfrom, gto = gto, gfrom
    gsort = request.args.get("gsort", "task")
    if gsort not in ("task", "assignee"):
        gsort = "task"
    gdir = request.args.get("gdir", "asc")
    if gdir not in ("asc", "desc"):
        gdir = "asc"
    ghide = request.args.get("ghide") == "1"
    # 個人ダッシュボードは本人固定(担当者フィルタは出さない)
    gassignee = "" if only_user_id is not None else request.args.get("gassignee", "")

    gtotal_days = (gto - gfrom).days + 1

    def left_of(d):
        return round((d - gfrom).days / gtotal_days * 100, 3)

    def width_of(days):
        return round(days / gtotal_days * 100, 3)

    gquery = Task.query
    if ghide:
        gquery = gquery.filter(Task.status != STATUS_DONE)
    if only_user_id is not None:
        gquery = gquery.filter(Task.assignees.any(User.id == only_user_id))
    elif gassignee.isdigit():
        gquery = gquery.filter(Task.assignees.any(User.id == int(gassignee)))

    gantt = []
    for t in gquery.all():
        s = t.start_date or t.due_date
        e = t.due_date or t.start_date
        segments = []
        marks = []
        if s and e:
            a, b = (s, e) if s <= e else (e, s)
            vs = max(a, gfrom)
            ve = min(b, gto)
            if vs <= ve:
                changes = list(t.status_changes)  # changed_at 昇順

                def status_at(d, _changes=changes, _task=t):
                    st = None
                    for c in _changes:
                        if c.changed_at.date() <= d:
                            st = c.status
                        else:
                            break
                    if st is None:
                        st = _changes[0].status if _changes else _task.status
                    return st

                cuts = sorted({
                    c.changed_at.date() for c in changes
                    if vs < c.changed_at.date() <= ve
                })
                bounds = [vs] + cuts + [ve + timedelta(days=1)]
                for i in range(len(bounds) - 1):
                    seg_s, seg_e = bounds[i], bounds[i + 1]
                    days = (seg_e - seg_s).days
                    if days <= 0:
                        continue
                    st = status_at(seg_s)
                    if segments and segments[-1]["status"] == st:
                        segments[-1]["width"] = round(segments[-1]["width"] + width_of(days), 3)
                    else:
                        segments.append({"left": left_of(seg_s), "width": width_of(days), "status": st})

                # 進捗記載(コメント)の印は、棒が可視のときのみ棒の上に打つ
                for c in t.comments:
                    cd = c.created_at.date()
                    if gfrom <= cd <= gto:
                        marks.append({
                            "left": left_of(cd),
                            "tip": "{} {}：{}".format(
                                c.created_at.strftime("%m/%d %H:%M"), c.user.display_name, c.body
                            ),
                        })

        overdue = bool(t.due_date and t.status != STATUS_DONE and t.due_date < today)
        overdue_left = left_of(t.due_date) if (overdue and gfrom <= t.due_date <= gto) else None

        gantt.append({
            "task": t, "segments": segments,
            "overdue": overdue, "overdue_left": overdue_left, "marks": marks,
        })

    def _gkey(g):
        t = g["task"]
        if gsort == "assignee":
            return (t.assignee_names or "￿").lower()
        return (t.title or "").lower()
    gantt.sort(key=_gkey, reverse=(gdir == "desc"))

    gticks = []
    d = gfrom
    while d <= gto:
        gticks.append({"date": d, "left": left_of(d)})
        d += timedelta(days=7)
    gtoday_left = left_of(today) if gfrom <= today <= gto else None

    return {
        "gantt": gantt,
        "gfrom": gfrom, "gto": gto,
        "gsort": gsort, "gdir": gdir, "ghide": ghide, "gassignee": gassignee,
        "gticks": gticks, "gtoday_left": gtoday_left,
        "status_colors": STATUS_COLORS,
        "gusers": [] if only_user_id is not None else get_active_users(),
        "gpersonal": only_user_id is not None,
    }


@manager_bp.route("/", endpoint="dashboard")
@login_required
def manager_dashboard():
    if not current_user.is_manager:
        abort(403)

    today = date.today()
    users = get_active_users()
    members = [u for u in users if u.role == ROLE_MEMBER]
    member_ids = {u.id for u in members}
    # 「メンバー」集計の母数は ROLE_MEMBER のみ(マネージャーは除く)
    member_count = len(members)

    # ---- タスク進捗 ----
    task_counts = {s: Task.query.filter_by(status=s).count() for s in STATUS_CHOICES}
    task_open = Task.query.filter(Task.status != STATUS_DONE).count()
    task_overdue = Task.query.filter(
        Task.status != STATUS_DONE,
        Task.due_date.isnot(None),
        Task.due_date < today,
    ).count()
    task_overdue_rate = round(task_overdue / task_open * 100) if task_open else 0

    # ---- 年休: 直近1か月(今日〜30日先)の休暇予定 ----
    upcoming_leaves = (
        LeaveRequest.query.filter(
            LeaveRequest.leave_date >= today,
            LeaveRequest.leave_date <= today + timedelta(days=30),
        )
        .order_by(LeaveRequest.leave_date)
        .all()
    )

    # ---- スキル保有状況(テクニカル) ----
    tech_skills = (
        Skill.query.filter_by(skill_type=SKILL_TECHNICAL, is_active=True)
        .order_by(Skill.sort_order, Skill.name)
        .all()
    )
    weak_threshold = max(1, (member_count + 2) // 3)  # 対象の約1/3未満を手薄とみなす
    skill_rows = []
    for s in tech_skills:
        # 保有人数もメンバーに限定して数える(分母と母集団を揃える)
        holders = sum(
            1 for r in s.ratings
            if r.level >= SKILL_PROFICIENT_LEVEL and r.user_id in member_ids
        )
        skill_rows.append(
            {"skill": s, "holders": holders, "total": member_count,
             "weak": holders < weak_threshold}
        )

    # メンバー別 平均到達度(全テクニカル項目に対して。未評価=0)
    tech_ids = [s.id for s in tech_skills]
    by_user = {}
    if tech_ids:
        for r in SkillRating.query.filter(SkillRating.skill_id.in_(tech_ids)).all():
            by_user.setdefault(r.user_id, []).append(r.level)
    n_tech = len(tech_skills)
    member_avg = []
    for u in members:  # 「メンバー別」なのでメンバーのみを並べる
        levels = by_user.get(u.id, [])
        avg = round(sum(levels) / n_tech, 1) if n_tech else 0
        member_avg.append({"user": u, "avg": avg})

    # ---- メンバーの活動状況(進捗記載)。ヒト別 → タスク別 → 時系列 ----
    actx = _build_activity(today, users)
    activity_rows = actx["activity_rows"]
    act_from = actx["act_from"]
    act_to = actx["act_to"]

    # ---- ヒト別 負荷・案件状況(タスク＋定型業務を合算) ----
    workload_rows, workload_totals = _build_workload(today, users)

    # ---- 成果(見込み・実績)。ヒト別＋全体 ----
    octx = _build_outcomes(today, users)

    # ---- 全タスクのガントチャート ----
    gctx = _build_gantt(today)

    return render_template(
        "manager/dashboard.html",
        today=today,
        member_count=member_count,
        # ヒト別 負荷・案件状況
        workload_rows=workload_rows,
        workload_totals=workload_totals,
        load_full=_LOAD_FULL,
        # タスク
        task_counts=task_counts,
        task_colors=STATUS_COLORS,
        task_overdue=task_overdue,
        task_overdue_rate=task_overdue_rate,
        # 年休(直近1か月の休暇予定)
        upcoming_leaves=upcoming_leaves,
        # スキル
        skill_rows=skill_rows,
        member_avg=member_avg,
        proficient=SKILL_PROFICIENT_LEVEL,
        # メンバーの活動状況
        activity_rows=activity_rows,
        act_from=act_from,
        act_to=act_to,
        # ガントチャート(ダッシュボード内蔵。リンクは他セクションの期間も保持)
        gantt_endpoint="manager.dashboard",
        gantt_extra={
            "afrom": act_from.strftime("%Y-%m-%d"),
            "ato": act_to.strftime("%Y-%m-%d"),
            "ofrom": octx["o_from"].strftime("%Y-%m-%d"),
            "oto": octx["o_to"].strftime("%Y-%m-%d"),
        },
        **octx,
        **gctx,
    )


@manager_bp.route("/gantt")
@login_required
def gantt_full():
    """全タスクのガントチャートを全画面で表示する専用ページ。"""
    if not current_user.is_manager:
        abort(403)
    gctx = _build_gantt(date.today())
    return render_template(
        "manager/gantt_full.html",
        gantt_endpoint="manager.gantt_full",
        gantt_extra={},
        **gctx,
    )


# =============================================================================
# 5-8. チーム管理
# =============================================================================
# チーム(Department)の管理ルーティング。マネージャーのみ。
#
# チームの追加・名称変更・有効/無効、および 人とチームの紐づけ(兼務対応)を管理する。

departments_bp = Blueprint("departments", __name__, url_prefix="/departments")


def _require_admin():
    if not current_user.is_admin:
        abort(403)


def _member_has_history(user):
    """メンバーが業務データ(タスク/進捗/年休/スキル/スキルテスト/定型業務)を持つか。

    履歴があるユーザーは物理削除するとタスク等の参照が壊れるため、無効化に切り替える。
    """
    if user.created_tasks or user.assigned_tasks or user.leave_requests or user.skill_ratings:
        return True
    if TaskComment.query.filter_by(user_id=user.id).first():
        return True
    if SkillRating.query.filter_by(rated_by_id=user.id).first():
        return True
    if SkillTestAttempt.query.filter_by(user_id=user.id).first():
        return True
    if RoutineWork.query.filter(
        (RoutineWork.assignee_id == user.id) | (RoutineWork.creator_id == user.id)
    ).first():
        return True
    return False


@departments_bp.route("/")
@login_required
def manage():
    _require_admin()
    departments = Department.query.order_by(Department.sort_order, Department.name).all()
    users = User.query.filter_by(is_active=True).order_by(User.display_name).all()
    inactive_members = (
        User.query.filter_by(is_active=False).order_by(User.display_name).all()
    )
    # 紐づけ判定用: {dept_id: set(user_id)}
    membership = {d.id: {u.id for u in d.users} for d in departments}
    return render_template(
        "departments/manage.html",
        departments=departments,
        users=users,
        inactive_members=inactive_members,
        membership=membership,
        role_manager=ROLE_MANAGER,
        role_member=ROLE_MEMBER,
        role_labels=ROLE_LABELS,
    )


@departments_bp.route("/members/new", methods=["POST"])
@login_required
def new_member():
    """メンバー(ユーザー)を追加する。マネージャーのみ。"""
    _require_admin()
    username = request.form.get("username", "").strip()
    display_name = request.form.get("display_name", "").strip()
    role = request.form.get("role", ROLE_MEMBER)
    if role not in (ROLE_MANAGER, ROLE_MEMBER):
        role = ROLE_MEMBER

    if not username or not display_name:
        flash("ログインIDと氏名は必須です。", "danger")
    elif User.query.filter_by(username=username).first():
        flash(f"ログインID「{username}」は既に使われています。", "warning")
    else:
        db.session.add(User(
            username=username,
            display_name=display_name,
            role=role,
            is_active=True,
        ))
        db.session.commit()
        flash(f"メンバー「{display_name}」を追加しました。", "success")
    return redirect(url_for("departments.manage"))


@departments_bp.route("/members/<int:user_id>/delete", methods=["POST"])
@login_required
def delete_member(user_id):
    """メンバーを削除する。マネージャーのみ。

    業務データ(タスク・進捗・年休・スキル・定型業務)がある場合は、参照を壊さない
    よう物理削除せず「無効化」する(一覧・割り当てから外れる)。データが無ければ物理削除。
    """
    _require_admin()
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)
    if user.id == current_user.id:
        flash("自分自身は削除できません。", "warning")
        return redirect(url_for("departments.manage"))

    name = user.display_name
    if _member_has_history(user):
        # チームの紐づけを外し、無効化(履歴は保持)
        user.departments = []
        user.is_active = False
        db.session.commit()
        flash(
            f"「{name}」は業務データがあるため無効化しました(一覧・割り当てから外れます)。",
            "info",
        )
    else:
        user.departments = []
        db.session.delete(user)
        db.session.commit()
        flash(f"メンバー「{name}」を削除しました。", "success")
    return redirect(url_for("departments.manage"))


@departments_bp.route("/members/<int:user_id>/reactivate", methods=["POST"])
@login_required
def reactivate_member(user_id):
    """無効化したメンバーを復帰させる。マネージャーのみ。"""
    _require_admin()
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)
    user.is_active = True
    db.session.commit()
    flash(f"メンバー「{user.display_name}」を復帰しました。", "success")
    return redirect(url_for("departments.manage"))


@departments_bp.route("/new", methods=["POST"])
@login_required
def new_department():
    _require_admin()
    name = request.form.get("name", "").strip()
    if not name:
        flash("チームの名称を入力してください。", "danger")
    elif Department.query.filter_by(name=name).first():
        flash("同じ名称のチームが既にあります。", "warning")
    else:
        order_raw = request.form.get("sort_order", "0")
        db.session.add(Department(
            name=name,
            sort_order=int(order_raw) if order_raw.lstrip("-").isdigit() else 0,
        ))
        db.session.commit()
        flash(f"チーム「{name}」を追加しました。", "success")
    return redirect(url_for("departments.manage"))


@departments_bp.route("/<int:dept_id>/rename", methods=["POST"])
@login_required
def rename_department(dept_id):
    _require_admin()
    dept = db.session.get(Department, dept_id)
    if dept is None:
        abort(404)
    name = request.form.get("name", "").strip()
    if not name:
        flash("チームの名称を入力してください。", "danger")
    else:
        other = Department.query.filter_by(name=name).first()
        if other and other.id != dept.id:
            flash("同じ名称のチームが既にあります。", "warning")
        else:
            dept.name = name
            order_raw = request.form.get("sort_order", str(dept.sort_order))
            dept.sort_order = int(order_raw) if order_raw.lstrip("-").isdigit() else dept.sort_order
            db.session.commit()
            flash("チームを更新しました。", "success")
    return redirect(url_for("departments.manage"))


@departments_bp.route("/<int:dept_id>/toggle", methods=["POST"])
@login_required
def toggle_department(dept_id):
    _require_admin()
    dept = db.session.get(Department, dept_id)
    if dept is None:
        abort(404)
    dept.is_active = not dept.is_active
    db.session.commit()
    flash(
        f"チーム「{dept.name}」を{'有効' if dept.is_active else '無効'}にしました。", "info"
    )
    return redirect(url_for("departments.manage"))


@departments_bp.route("/memberships", methods=["POST"])
@login_required
def save_memberships():
    """人とチームの紐づけ(兼務対応)を一括保存する。"""
    _require_admin()
    users = User.query.filter_by(is_active=True).all()
    user_by_id = {u.id: u for u in users}
    for dept in Department.query.all():
        checked = request.form.getlist(f"dept_{dept.id}")
        checked_ids = {int(x) for x in checked if x.isdigit()}
        dept.users = [user_by_id[uid] for uid in checked_ids if uid in user_by_id]
    db.session.commit()
    flash("チームの紐づけを保存しました。", "success")
    return redirect(url_for("departments.manage"))


# =============================================================================
# 5-9. Excel データ出力
# =============================================================================
# 全データの Excel(.xlsx) 出力。マネージャーのみ。
#
# 各メニューのデータ(現在データ＋履歴データ)を openpyxl で xlsx 化し、
# 添付ファイルとしてダウンロードさせる。読み取り専用(DBは変更しない)。

export_bp = Blueprint("export", __name__, url_prefix="/export")


@export_bp.before_request
@login_required
def _export_managers_only():
    """データ出力はマネージャーのみ。"""
    if not current_user.is_manager:
        abort(403)


def _fmt(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "はい" if v else "いいえ"
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, date):
        return v.strftime("%Y-%m-%d")
    return v


def _xlsx_response(sheets, filename):
    """sheets = [(シート名, ヘッダ list, 行 list of list)] を1つの xlsx にして返す。"""
    wb = Workbook()
    wb.remove(wb.active)
    for name, headers, rows in sheets:
        ws = wb.create_sheet(title=name[:31])
        ws.append(list(headers))
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for row in rows:
            ws.append([_fmt(c) for c in row])
            # openpyxl は「=」で始まる文字列を数式として保存するため、文字列として書き出す
            # (タスク名・コメント・AIが作った問題文や選択肢などが数式として計算されないように)
            for cell in ws[ws.max_row]:
                if cell.data_type == "f" and isinstance(cell.value, str):
                    cell.data_type = "s"
        ws.freeze_panes = "A2"
        for i, h in enumerate(headers, start=1):
            ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = \
                max(10, min(45, len(str(h)) * 2 + 6))
    if not wb.sheetnames:
        wb.create_sheet(title="data")
    bio = BytesIO()
    wb.save(bio)
    return Response(
        bio.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --------------------------------------------------------------------------- #
# 各メニューのシート定義(現在データ＋履歴データ)
# --------------------------------------------------------------------------- #
def _tasks_sheets():
    tasks = Task.query.order_by(Task.id).all()
    t_headers = [
        "ID", "タイトル", "ステータス", "優先度", "開始日", "期限", "規模",
        "担当者", "登録者", "成果定量-見込み", "単位", "成果定量-実績", "単位",
        "成果-補足", "成果定性-見込み", "成果定性-実績", "内容・詳細",
        "登録日時", "更新日時",
    ]
    t_rows = [[
        t.id, t.title, t.status, t.priority, t.start_date, t.due_date,
        t.scale_label or "", t.assignee_names,
        t.creator.display_name if t.creator else "",
        t.outcome_quant_estimate, t.outcome_quant_estimate_unit,
        t.outcome_quant_actual, t.outcome_quant_actual_unit,
        t.outcome_quant_note, t.outcome_qual_estimate, t.outcome_qual_actual,
        t.description, t.created_at, t.updated_at,
    ] for t in tasks]

    changes = TaskStatusChange.query.order_by(
        TaskStatusChange.task_id, TaskStatusChange.changed_at
    ).all()
    c_rows = [[
        ch.task_id, ch.task.title if ch.task else "", ch.status, ch.changed_at,
    ] for ch in changes]

    comments = TaskComment.query.order_by(
        TaskComment.task_id, TaskComment.created_at
    ).all()
    cm_rows = [[
        cm.task_id, cm.task.title if cm.task else "",
        cm.user.display_name if cm.user else "", cm.body, cm.created_at,
    ] for cm in comments]

    return [
        ("タスク(現在)", t_headers, t_rows),
        ("ステータス履歴", ["タスクID", "タスク", "ステータス", "変更日時"], c_rows),
        ("進捗状況(履歴)", ["タスクID", "タスク", "記載者", "進捗内容", "記載日時"], cm_rows),
    ]


def _routine_sheets():
    rows = [[
        r.id, r.name, r.assignee.display_name if r.assignee else "",
        r.purpose, r.frequency_count, r.frequency_unit, r.minutes_per,
        r.monthly_minutes, r.content, r.manual_status,
        r.creator.display_name if r.creator else "", r.created_at, r.updated_at,
    ] for r in RoutineWork.query.order_by(RoutineWork.assignee_id, RoutineWork.id).all()]
    headers = [
        "ID", "業務名", "担当者", "目的", "回数", "頻度単位", "1回所要(分)",
        "月間所要(分)", "業務内容", "手順書", "登録者", "登録日時", "更新日時",
    ]
    return [("定型・定期業務", headers, rows)]


def _skills_sheets():
    skills = Skill.query.order_by(Skill.skill_type, Skill.sort_order, Skill.name).all()
    s_rows = [[
        s.id, s.name, s.type_label, s.category, s.description, s.is_active, s.sort_order,
    ] for s in skills]

    ratings = SkillRating.query.order_by(SkillRating.user_id, SkillRating.skill_id).all()
    r_rows = [[
        r.user.display_name if r.user else "", r.skill.name if r.skill else "",
        r.level, r.note, r.rater.display_name if r.rater else "", r.rated_at,
    ] for r in ratings]

    ops = Operation.query.order_by(Operation.sort_order, Operation.name).all()
    o_rows = [[o.id, o.name, o.description, o.is_active, o.sort_order] for o in ops]

    reqs = OperationSkill.query.all()
    req_rows = [[
        r.operation.name if r.operation else "",
        r.skill.name if r.skill else "", r.level,
    ] for r in reqs]

    return [
        ("スキル項目", ["ID", "スキル名", "区分", "カテゴリ", "説明", "有効", "並び順"], s_rows),
        ("到達度", ["メンバー", "スキル", "到達度", "メモ", "評価者", "評価日時"], r_rows),
        ("業務", ["ID", "業務名", "説明", "有効", "並び順"], o_rows),
        ("業務別-必要スキル", ["業務", "必要スキル", "必要レベル"], req_rows),
    ]


def _leaves_sheets():
    rows = [[
        lv.id, lv.user.display_name if lv.user else "",
        lv.leave_date, lv.leave_type, lv.day_count, lv.created_at,
    ] for lv in LeaveRequest.query.order_by(LeaveRequest.leave_date).all()]
    headers = ["ID", "メンバー", "取得日", "種別", "換算日数", "登録日時"]
    return [("年休", headers, rows)]


def _skilltest_sheets():
    """スキルテストの受験履歴・回答(全問)・問題プール。"""
    attempts = SkillTestAttempt.query.order_by(SkillTestAttempt.started_at, SkillTestAttempt.id).all()
    a_headers = [
        "受験ID", "メンバー", "スキル", "状態", "開始日時", "終了日時", "全体の期限",
        "問題数", "正解数", "正答率(%)", "レベル別(正解/問題・判定)", "結果レベル",
        "受験前の到達度", "受験後の到達度", "自動登録", "離脱回数", "再出題数", "受験時の設定",
    ]
    a_rows = []
    for a in attempts:
        per_level = "、".join(
            "Lv{} {}/{}{}".format(
                r.get("level"), r.get("correct"), r.get("total"), "合格" if r.get("passed") else "")
            for r in a.level_result_list
        )
        a_rows.append([
            a.id, a.user.display_name if a.user else "", a.skill.name if a.skill else "",
            a.status_label, a.started_at, a.finished_at, a.deadline_at,
            a.total, None if a.is_in_progress else a.correct,
            None if a.is_in_progress else a.rate, per_level, a.result_level,
            a.prev_level, a.new_level, None if a.is_in_progress else a.applied,
            a.blur_count, a.reused_count, a.settings_snapshot or "",
        ])

    answers = (
        SkillTestAnswer.query.join(SkillTestAttempt)
        .order_by(SkillTestAttempt.started_at, SkillTestAnswer.attempt_id, SkillTestAnswer.seq)
        .all()
    )
    w_headers = [
        "受験ID", "メンバー", "スキル", "出題順", "レベル", "問題ID", "問題文",
        "選択肢A", "選択肢B", "選択肢C", "選択肢D", "正解", "回答", "結果",
        "制限時間(秒)", "表示日時", "確定日時", "所要(秒)", "離脱回数",
    ]
    w_rows = []
    for w in answers:
        choices = (w.choice_list + ["", "", "", ""])[:4]
        attempt = w.attempt
        w_rows.append([
            w.attempt_id,
            attempt.user.display_name if attempt and attempt.user else "",
            attempt.skill.name if attempt and attempt.skill else "",
            w.seq, w.level, w.question_id, w.question,
            choices[0], choices[1], choices[2], choices[3],
            choice_letter(w.correct_index), choice_letter(w.selected_index), w.result_label,
            w.time_limit_sec, w.served_at, w.answered_at, w.elapsed_sec, w.blur_count,
        ])

    questions = SkillTestQuestion.query.order_by(
        SkillTestQuestion.skill_id, SkillTestQuestion.level, SkillTestQuestion.id).all()
    q_headers = [
        "問題ID", "スキル", "レベル", "問題文", "選択肢A", "選択肢B", "選択肢C", "選択肢D",
        "正解", "解説", "作成元", "モデル", "有効", "作成日時",
    ]
    q_rows = []
    for q in questions:
        choices = (q.choice_list + ["", "", "", ""])[:4]
        q_rows.append([
            q.id, q.skill.name if q.skill else "", q.level, q.question,
            choices[0], choices[1], choices[2], choices[3],
            q.answer_letter, q.explanation, q.source_label, q.model, q.is_active, q.created_at,
        ])

    return [
        ("スキルテスト受験履歴", a_headers, a_rows),
        ("スキルテスト回答", w_headers, w_rows),
        ("スキルテスト問題", q_headers, q_rows),
    ]


def _teams_sheets():
    depts = Department.query.order_by(Department.sort_order, Department.name).all()
    d_rows = [[
        d.id, d.name, d.is_active, d.sort_order,
        "、".join(u.display_name for u in d.users),
    ] for d in depts]

    users = User.query.order_by(User.display_name).all()
    u_rows = [[
        u.username, u.display_name, u.role_label, u.is_active, u.department_names,
    ] for u in users]

    return [
        ("チーム", ["ID", "チーム名", "有効", "並び順", "所属メンバー"], d_rows),
        ("メンバー", ["ログインID", "氏名", "役割", "有効", "所属チーム"], u_rows),
    ]


# --------------------------------------------------------------------------- #
# ダウンロード用ルート
# --------------------------------------------------------------------------- #
@export_bp.route("/tasks.xlsx")
def tasks_xlsx():
    return _xlsx_response(_tasks_sheets(), "tasks.xlsx")


@export_bp.route("/routine.xlsx")
def routine_xlsx():
    return _xlsx_response(_routine_sheets(), "routine.xlsx")


@export_bp.route("/skills.xlsx")
def skills_xlsx():
    return _xlsx_response(_skills_sheets(), "skills.xlsx")


@export_bp.route("/leaves.xlsx")
def leaves_xlsx():
    return _xlsx_response(_leaves_sheets(), "leaves.xlsx")


@export_bp.route("/skilltest.xlsx")
def skilltest_xlsx():
    return _xlsx_response(_skilltest_sheets(), "skilltest.xlsx")


@export_bp.route("/teams.xlsx")
def teams_xlsx():
    return _xlsx_response(_teams_sheets(), "teams.xlsx")


@export_bp.route("/all.xlsx")
def all_xlsx():
    sheets = (
        _tasks_sheets() + _routine_sheets() + _skills_sheets()
        + _skilltest_sheets() + _leaves_sheets() + _teams_sheets()
    )
    return _xlsx_response(sheets, "all_data.xlsx")


# #############################################################################
# 6. 週報(自動作成・メール送信)
# #############################################################################
# マネージャーのみ。タスク情報(タスク・進捗記載・ステータス変更・成果・負荷)から、
# チーム全体＋1人1ページの週報をWordで作り、メールで送る。DBには何も保存しない。
#
#   6-1 ルール         期間・次回実行日時・ファイル名/件名の差し込み(純粋関数)
#   6-2 設定の保存     画面で編集する設定(instance/weekly_settings.json)
#   6-3 設定フォーム   設定フォームの入力チェック(システム設定の「週報」タブで使う)
#   6-4 材料の収集     材料の収集とチーム全体の集計(数値はすべてコードで計算)
#   6-5 文章づくり     AI整形。使えない部分はルールベース
#   6-6 Word の作成    Word(.docx)の作成
#   6-7 とりまとめ     作成〜送信のとりまとめ(run_weekly)
#   6-8 画面           週報の画面と「今すぐ作成」(Blueprint: weekly_bp, /weekly)
#
# アプリ共通の部品を使う: AI(4-1 ai_chat)・メール送信(4-2 send_mail)・
# 自動送信のスケジューラ(10。「flask --app app run」で起動したときだけ動く)。
# 接続設定(メール・AI)はすべて instance/config.py から読み込む(システム設定の「基本設定」タブで変更)。


# =============================================================================
# 6-1. 週報: 期間・次回実行日時・ファイル名/件名のルール
# =============================================================================
# 週報の「期間・次回実行日時・ファイル名/件名」のルール(純粋関数のみ)。
#
# DBにもFlaskにも依存しないため、画面・スケジューラ・作成処理のどこからでも使える。
#
# 期間のルール(画面で選択):
#   prev7 : 送信日の前日までの7日間(既定)。例: 送信日が月曜 → 前週の月曜〜日曜
#   incl7 : 送信日を含む7日間。          例: 送信日が金曜 → 前週の土曜〜当日の金曜
#           ※自動送信では、送信日の送信時刻より後に記録した内容は、どの週報にも載らない
#            (次回の期間は送信日の翌日から始まるため)。漏れなく載せたい場合は prev7 を使う
#
# ファイル名・件名・メール本文で使える差し込み記号:
#   {開始日} {終了日} {送信日} : yyyymmdd
#   {年} {月}                  : 期間の終了日の西暦年(4桁)・月(2桁)
#   {週}                       : 期間の終了日のISO週番号(2桁)
#   {週の年}                   : {週} の属する年(ISO週の年。年末年始は {年} と異なることがある)
#   {期間}                     : yyyy/mm/dd〜yyyy/mm/dd(ファイル名では / を - に置き換える)

WEEKDAY_LABELS = ["月", "火", "水", "木", "金", "土", "日"]

PERIOD_PREV7 = "prev7"
PERIOD_INCL7 = "incl7"
PERIOD_RULES = {
    PERIOD_PREV7: "送信日の前日までの7日間",
    PERIOD_INCL7: "送信日を含む7日間",
}

# 差し込み記号の説明(画面のヘルプ表示用)
PLACEHOLDER_HELP = [
    ("{開始日}", "対象期間の開始日（例: 20260921）"),
    ("{終了日}", "対象期間の終了日（例: 20260927）"),
    ("{送信日}", "作成・送信した日（例: 20260928）"),
    ("{年}", "終了日の西暦年（例: 2026）。{月} と組み合わせて使います"),
    ("{月}", "終了日の月・2桁（例: 09）"),
    ("{週}", "終了日のISO週番号・2桁（例: 39）。年と組み合わせる場合は {週の年} を使います"),
    ("{週の年}", "{週} の属する年（ISO週の年。例: 2026。年末年始は {年} と異なることがあります）"),
    ("{期間}", "対象期間（例: 2026/09/21〜2026/09/27。ファイル名では / が - になります）"),
]

# 見本(チーム全体・個人・注意点)で使える差し込み記号
SAMPLE_PLACEHOLDER_HELP = [
    ("{期間}", "対象期間（例: 2026/09/21〜2026/09/27）"),
    ("{氏名}", "個人の見本では本人の氏名、チーム全体の見本では「チーム全体」"),
    ("{作成日}", "作成した日（例: 2026/09/28）"),
]

# ファイル名の長さの上限(拡張子を含む)
FILENAME_MAX = 120
DOCX_EXT = ".docx"

# Windowsのファイル名に使えない文字と制御文字
_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')
# 件名に入れられない改行・タブ
_SUBJECT_LINE_BREAKS = re.compile(r"[\r\n\t\x0b\x0c]+")
# Windowsの予約名(拡張子を除いた名前がこれだと保存できない)
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"} | {
    "{}{}".format(p, i) for p in ("COM", "LPT") for i in range(1, 10)
}


def period_for(send_date, rule):
    """送信日と期間のルールから、対象期間 (開始日, 終了日) を返す(両端を含む7日間)。"""
    if rule == PERIOD_INCL7:
        end = send_date
    else:
        end = send_date - timedelta(days=1)
    return end - timedelta(days=6), end


def period_label(start, end):
    """画面・文書用の期間表記(yyyy/mm/dd〜yyyy/mm/dd)。"""
    return "{}〜{}".format(start.strftime("%Y/%m/%d"), end.strftime("%Y/%m/%d"))


def next_weekly_run(settings, now):
    """設定から次回の自動実行日時を求める。自動送信が無効・時刻不正なら None。

    当日の実行時刻の「分」の間はまだ実行中とみなし、当日の日時を返す。
    """
    if not settings.get("enabled"):
        return None
    at = parse_hhmm(settings.get("time"))
    if at is None:
        return None
    weekday = settings.get("weekday", 0)
    days_ahead = (weekday - now.weekday()) % 7
    candidate = datetime.combine(now.date() + timedelta(days=days_ahead), time(at.hour, at.minute))
    if candidate < now.replace(second=0, microsecond=0):
        candidate += timedelta(days=7)
    return candidate


def render_pattern(pattern, start, end, send_date, for_filename=False):
    """パターン中の差し込み記号を値に置き換える(知らない記号はそのまま残す)。"""
    period = period_label(start, end)
    if for_filename:
        period = period.replace("/", "-")
    iso_year, iso_week, _weekday = end.isocalendar()
    values = {
        "{開始日}": start.strftime("%Y%m%d"),
        "{終了日}": end.strftime("%Y%m%d"),
        "{送信日}": send_date.strftime("%Y%m%d"),
        "{年}": "{:04d}".format(end.year),
        "{月}": "{:02d}".format(end.month),
        "{週}": "{:02d}".format(iso_week),
        "{週の年}": "{:04d}".format(iso_year),
        "{期間}": period,
    }
    text = pattern or ""
    for key, value in values.items():
        text = text.replace(key, value)
    return text


def safe_filename(name, default_stem="週報"):
    """Windowsで保存できるファイル名(.docx)に整える。

    - 使えない文字(\\ / : * ? " < > |)と制御文字は「_」に置き換える
    - 前後の空白(と末尾のピリオド)を除く
    - 拡張子 .docx を付ける(既に付いていればそのまま)
    - 拡張子を含めて FILENAME_MAX 文字以内に切り詰める
    """
    name = _INVALID_FILENAME_CHARS.sub("_", name or "").strip()
    stem = name[:-len(DOCX_EXT)] if name.lower().endswith(DOCX_EXT) else name
    stem = stem.strip().rstrip(". ")
    stem = stem[:FILENAME_MAX - len(DOCX_EXT)].rstrip(". ")
    if not stem:
        stem = default_stem
    if stem.split(".")[0].upper() in _RESERVED_NAMES:
        stem = "_" + stem
    return stem + DOCX_EXT


def preview_names(settings, today):
    """今日作成した場合の対象期間・ファイル名・件名(画面のプレビュー用)。"""
    start, end = period_for(today, settings["period_rule"])
    return {
        "period": period_label(start, end),
        "filename": build_weekly_filename(settings["filename_pattern"], start, end, today),
        "subject": build_weekly_subject(settings["subject_pattern"], start, end, today),
    }


def build_weekly_filename(pattern, start, end, send_date):
    """ファイル名のパターンから、実際のファイル名を作る。"""
    return safe_filename(render_pattern(pattern, start, end, send_date, for_filename=True))


def build_weekly_subject(pattern, start, end, send_date):
    """件名のパターンから、実際の件名を作る(改行・タブは空白にする)。"""
    text = render_pattern(pattern, start, end, send_date)
    return _SUBJECT_LINE_BREAKS.sub(" ", text).strip() or "週報"


# =============================================================================
# 6-2. 週報: 設定の保存・読み込み
# =============================================================================
# 週報の設定(画面で編集する値)の保存・読み込み。
#
# DBは使わず、instance/weekly_settings.json(Git管理外)に保存する。
# ファイルが無ければ既定値を使い、画面で保存したとき(または送信して前回の結果を
# 記録したとき)に作成される。
#
# ここに保存するのは「いつ・誰を・どう書くか」だけ。メールの送信サーバー・宛先や
# AIのキーは保存しない(instance/config.py。システム設定の「基本設定」タブで変更する)。
# 画面の入力チェックは設定フォーム(6-3。システム設定の「週報」タブで使う)。
#
# 保存項目:
#   enabled          : 自動送信する/しない
#   weekday / time   : 自動送信の曜日(0=月〜6=日)・時刻("HH:MM")
#   period_rule      : 期間のルール(PERIOD_RULES)
#   target_user_ids  : 週報に載せる対象者(ユーザーID)。新規ユーザーは自動では入らない
#   target_usernames : 対象者のIDごとのログインID({"ID": "ログインID"})。
#                      削除されたユーザーのIDが新しいユーザーに再利用されても、
#                      IDとログインIDの両方が一致する人だけを対象者とする(取り違え防止)
#   team_sample / person_sample / guidelines : 文章の見本と書く際の注意点
#   filename_pattern / subject_pattern / mail_body : ファイル名・件名・メール本文
#   last_result      : 前回の結果(日時・きっかけ・成否・メッセージ)。毎回上書き
#
# 画面の保存とバックグラウンドの送信が同時に書き込んでも壊れないよう、
# ロックで直列化し、一時ファイルに書いてから置き換える(os.replace)。
# ファイルがあるのに読み込めない(壊れている・開けない)ときは、表示や自動送信の判定には
# 既定値を使うが、保存済みの設定を消さないよう上書きはしない(SettingsFileError)。
# ファイルの読み書きは期限超過通知と共通の部品(2-3)を使う。

WEEKLY_SETTINGS_FILENAME = "weekly_settings.json"
WEEKLY_SETTINGS_LABEL = "週報の設定ファイル"

# 文章の見本などの最大文字数(設定ファイルの肥大化を防ぐ)
WEEKLY_TEXT_MAX = 20000

DEFAULT_TEAM_SAMPLE = """■全体の状況（{期間}）
・完了3件、新規着手2件。全体としておおむね計画どおりに進んでいる。
・期限超過は1件（〇〇の確認待ち。来週前半に完了見込み）。
■主な成果
・〇〇の手順を見直し、作業時間を削減（120 ｈ/年）。
■課題・リスク
・△△は関係者の日程調整中のため保留。来週に再開予定。
■来週の予定
・□□の試行を開始する。"""

DEFAULT_PERSON_SAMPLE = """■今週の実績
・〇〇の資料作成を完了（成果: 作業時間 5 ｈ/月 の削減）。
・△△の検討を進め、方針案を作成した。
■課題・相談事項
・□□は確認待ちのため、期限を1週間延長したい。
■来週の予定
・△△の方針案を共有し、意見を集める。"""

DEFAULT_GUIDELINES = """・事実を簡潔に書く（1項目1〜2行程度）。
・完了したものは、成果（数値・効果）を添える。
・遅れや課題がある場合は、理由と今後の対応を書く。
・敬称は付けない。
・材料に無いことは書かず、該当が無い項目は「特になし」と書く。"""

DEFAULT_FILENAME_PATTERN = "週報_{開始日}-{終了日}.docx"
DEFAULT_SUBJECT_PATTERN = "【週報】{期間}"
DEFAULT_MAIL_BODY = """各位

{期間} の週報を送付します。
添付のWordファイルをご確認ください。

※このメールは業務管理システムから送信しています。"""

WEEKLY_DEFAULTS = {
    "enabled": False,
    "weekday": 0,
    "time": "08:00",
    "period_rule": PERIOD_PREV7,
    "target_user_ids": [],
    "target_usernames": {},
    "team_sample": DEFAULT_TEAM_SAMPLE,
    "person_sample": DEFAULT_PERSON_SAMPLE,
    "guidelines": DEFAULT_GUIDELINES,
    "filename_pattern": DEFAULT_FILENAME_PATTERN,
    "subject_pattern": DEFAULT_SUBJECT_PATTERN,
    "mail_body": DEFAULT_MAIL_BODY,
    "last_result": None,
}

# 画面から保存できる項目(last_result は送信処理だけが書き込む)
WEEKLY_EDITABLE_KEYS = [k for k in WEEKLY_DEFAULTS if k != "last_result"]

_TEXT_KEYS = (
    "team_sample", "person_sample", "guidelines",
    "filename_pattern", "subject_pattern", "mail_body",
)

_weekly_settings_lock = threading.RLock()


def _weekly_settings_path():
    return os.path.join(current_app.instance_path, WEEKLY_SETTINGS_FILENAME)


def _normalize_weekly_settings(data):
    """読み込んだ値を検証し、不正・欠落した項目は既定値で補う。"""
    result = copy.deepcopy(WEEKLY_DEFAULTS)
    if not isinstance(data, dict):
        return result

    if isinstance(data.get("enabled"), bool):
        result["enabled"] = data["enabled"]
    weekday = data.get("weekday")
    if isinstance(weekday, int) and not isinstance(weekday, bool) and 0 <= weekday <= 6:
        result["weekday"] = weekday
    at = parse_hhmm(data.get("time")) if isinstance(data.get("time"), str) else None
    if at is not None:
        result["time"] = at.strftime("%H:%M")
    if data.get("period_rule") in PERIOD_RULES:
        result["period_rule"] = data["period_rule"]
    ids = data.get("target_user_ids")
    names = data.get("target_usernames")
    if isinstance(ids, list) and isinstance(names, dict):
        # ログインIDの記録が無いIDは本人か確認できないため、対象者に含めない
        result["target_user_ids"] = sorted({
            i for i in ids
            if isinstance(i, int) and not isinstance(i, bool)
            and isinstance(names.get(str(i)), str) and names.get(str(i))
        })
        result["target_usernames"] = {
            str(i): names[str(i)] for i in result["target_user_ids"]
        }
    for key in _TEXT_KEYS:
        if isinstance(data.get(key), str):
            result[key] = data[key][:WEEKLY_TEXT_MAX]
    result["last_result"] = normalize_last_result(data.get("last_result"))
    return result


def load_weekly_settings():
    """現在の設定を返す(ファイルが無い・読み込めない場合は既定値)。"""
    with _weekly_settings_lock:
        try:
            data = read_json(_weekly_settings_path(), WEEKLY_SETTINGS_LABEL)
        except SettingsFileError as exc:
            current_app.logger.warning("%s（既定値を使用）", exc)
            data = None
        return _normalize_weekly_settings(data)


def _load_weekly_settings_for_update():
    """書き込む前に現在の設定を読む。

    ファイルがあるのに読み込めない場合は SettingsFileError を送出する
    (既定値で上書きして、保存済みの対象者・見本などを消さないため)。
    """
    return _normalize_weekly_settings(read_json(_weekly_settings_path(), WEEKLY_SETTINGS_LABEL))


def is_weekly_target(settings, user):
    """user が対象者として選ばれているか(ユーザーIDとログインIDの両方が一致する場合だけ)。"""
    names = settings.get("target_usernames") or {}
    return bool(user.username) and names.get(str(user.id)) == user.username


def save_weekly_settings(values):
    """画面で編集した項目を保存する(last_result は変更しない)。"""
    with _weekly_settings_lock:
        current = _load_weekly_settings_for_update()
        for key in WEEKLY_EDITABLE_KEYS:
            if key in values:
                current[key] = values[key]
        data = _normalize_weekly_settings(current)
        write_json(_weekly_settings_path(), data)
        return data


def set_weekly_last_result(trigger, ok, message):
    """前回の結果を上書きする(他の設定項目は変更しない)。

    設定ファイルが読み込めない場合は書き込まずに SettingsFileError を送出する。
    """
    with _weekly_settings_lock:
        current = _load_weekly_settings_for_update()
        current["last_result"] = new_last_result(trigger, ok, message)
        write_json(_weekly_settings_path(), current)
        return current["last_result"]


# =============================================================================
# 6-3. 週報: 設定フォーム
# =============================================================================
# 週報の設定フォームの入力チェックと表示用の値(システム設定の「週報」タブで使う)。
#
# 設定の画面はシステム設定(/system/settings?tab=weekly)にまとめてあり、
# 週報の画面(/weekly/)には実行と状況の表示だけが残る。保存先は設定の保存(6-2)のまま
# (instance/weekly_settings.json)。
#
#   parse_weekly_form(form)       フォームの入力を検証する → (保存する値, エラーメッセージの一覧)
#   settings_with_input(cur, v)   入力エラーで再表示するとき、保存済みの設定に入力中の値を重ねる
#                                 (期限超過通知の設定フォームでも使う)
#   weekly_form_context(settings) フォームの表示に使う値

WEEKLY_LABEL = "週報"
WEEKLY_SAVED_MESSAGE = "週報の設定を保存しました。"


def _text(form, name, single_line=False):
    """フォームのテキスト(改行を統一。1行項目は改行を除く)。"""
    value = (form.get(name) or "").replace("\r\n", "\n").replace("\r", "\n")
    if single_line:
        value = " ".join(value.split("\n")).strip()
    return value


def parse_weekly_form(form):
    """フォームの入力を検証する。戻り値: (values, errors)。errors が空なら保存してよい。"""
    errors = []
    values = {"enabled": form.get("enabled") == "1"}

    weekday = form.get("weekday", "")
    if weekday.isdecimal() and 0 <= int(weekday) <= 6:
        values["weekday"] = int(weekday)
    else:
        errors.append("送信する曜日を選択してください。")

    at = parse_hhmm(form.get("time"))
    if at is not None:
        values["time"] = at.strftime("%H:%M")
    else:
        errors.append("送信する時刻を「時:分」（例: 08:00）で入力してください。")

    rule = form.get("period_rule", "")
    if rule in PERIOD_RULES:
        values["period_rule"] = rule
    else:
        errors.append("対象期間のルールを選択してください。")

    # 対象者のチェックボックスの値は「ユーザーID:ログインID」(画面表示後のID再利用による取り違え防止)
    active = {u.id: u for u in get_active_users()}
    chosen = {}
    invalid = False
    for raw in form.getlist("target_user_ids"):
        user_id, _sep, username = raw.partition(":")
        user = active.get(int(user_id)) if user_id.isdecimal() else None
        if user is None or user.username != username:
            invalid = True
            continue
        chosen[user.id] = user.username
    if invalid:
        errors.append("対象者に有効でないユーザーが含まれています。画面を開き直して選び直してください。")
    values["target_user_ids"] = sorted(chosen)
    values["target_usernames"] = {str(i): name for i, name in chosen.items()}

    for key in ("team_sample", "person_sample", "guidelines", "mail_body"):
        values[key] = _text(form, key).strip("\n")
    values["filename_pattern"] = _text(form, "filename_pattern", single_line=True)
    values["subject_pattern"] = _text(form, "subject_pattern", single_line=True)
    if not values["filename_pattern"]:
        errors.append("ファイル名のパターンを入力してください。")
    if not values["subject_pattern"]:
        errors.append("メール件名のパターンを入力してください。")
    for key, label in (("team_sample", "チーム全体の見本"), ("person_sample", "個人の見本"),
                       ("guidelines", "書く際の注意点"), ("mail_body", "メール本文")):
        if len(values[key]) > WEEKLY_TEXT_MAX:
            errors.append("{}は{}文字以内にしてください。".format(label, WEEKLY_TEXT_MAX))
    return values, errors


def settings_with_input(current, values):
    """保存済みの設定に入力中の値を重ねる(入力エラー時の再表示用。保存はしない)。"""
    current.update(values)
    return current


def weekly_form_context(settings):
    """週報の設定フォームの表示に使う値。"""
    users = get_active_users()
    # IDとログインIDの両方が一致する人だけを選択済みにする(IDが再利用された別人は選ばない)
    selected_ids = {u.id for u in users if is_weekly_target(settings, u)}
    return {
        "settings": settings,
        "users": users,
        "selected_ids": selected_ids,
        "selected_count": sum(1 for u in users if u.id in selected_ids),
        "weekday_labels": WEEKDAY_LABELS,
        "period_rules": PERIOD_RULES,
        "placeholders": PLACEHOLDER_HELP,
        "sample_placeholders": SAMPLE_PLACEHOLDER_HELP,
        "preview": preview_names(settings, date.today()),
    }


# =============================================================================
# 6-4. 週報: 材料の収集と集計
# =============================================================================
# 週報の材料(タスク情報)の収集と、チーム全体の集計。
#
# 材料にするのはタスク情報だけ:
#   タスク(担当者・状態・優先度・開始日/期限・規模)、進捗記載(task_comments)、
#   ステータス変更履歴(task_status_changes)、成果(実績)、負荷(月間負荷h・余力h)。
# 定型業務の内容・年休・スキルは週報に載せない(負荷の数値だけ _build_workload を使う)。
#
# - 期間 [start, end] は日付で、両端を含む
# - 進捗記載は「記載者」ではなく「タスクの担当者」の枠に入れる(ダッシュボードの活動状況と同じ)
# - ステータス(進行中・保留・未完了など)は作成時点の値を使う
# - 数値の集計はすべてここ(コード)で行う。AIには計算させない
# - チーム全体の件数・成果は、複数担当のタスクも1件として数える(重複なし)

# 「期限が近い」とみなす日数(期間の終了日の翌日から数える)
DUE_SOON_DAYS = 7
# 進捗記載1件を材料に載せる最大文字数(長文でAIへの送信量が膨らまないように)
COMMENT_MAX = 400


def _one_line(text, limit=None):
    """複数行のテキストを「 / 」区切りの1行にまとめる(長すぎる場合は切り詰める)。"""
    text = " / ".join(line.strip() for line in (text or "").splitlines() if line.strip())
    if limit and len(text) > limit:
        text = text[:limit] + "…"
    return text


def _sort_key(fact):
    """期限の近い順(期限なしは最後)→タイトル順。"""
    return (fact["due_date"] or date.max, fact["title"] or "")


def _completed_on(task):
    """完了日(最後に「完了」へ変更した日)。未完了なら None。

    変更履歴の無い完了タスク(古いデータなど)は更新日で代用する。
    """
    if task.status != STATUS_DONE:
        return None
    for change in reversed(task.status_changes):
        if change.status == STATUS_DONE and change.changed_at:
            return change.changed_at.date()
    return task.updated_at.date() if task.updated_at else None


def _task_facts(task, start, end):
    """1件のタスクについて、期間に関係する事実をまとめる(表示用の素の値だけ)。"""
    start_dt = datetime.combine(start, time.min)
    end_dt = datetime.combine(end, time.max)

    def in_period(dt):
        return dt is not None and start_dt <= dt <= end_dt

    comments = [
        {
            "at": c.created_at,
            "author": c.user.display_name if c.user else "",
            "text": _one_line(c.body, COMMENT_MAX),
        }
        for c in task.comments if in_period(c.created_at)
    ]
    # 最初の履歴は登録時の状態なので「変更」には含めない
    changes = [
        {"at": c.changed_at, "status": c.status}
        for c in task.status_changes[1:] if in_period(c.changed_at)
    ]
    completed_on = _completed_on(task)
    is_open = task.status != STATUS_DONE
    due = task.due_date
    return {
        "id": task.id,
        "title": task.title,
        "status": task.status,
        "priority": task.priority,
        "start_date": task.start_date,
        "due_date": due,
        "scale_label": task.scale_label or "",
        "assignees": task.assignee_names,
        "assignee_ids": {u.id for u in task.assignees},
        "comments": comments,
        "changes": changes,
        "initial_status": task.status_changes[0].status if task.status_changes else task.status,
        "created_in": in_period(task.created_at),
        # 着手 = 期間内に「進行中」になった(登録時から進行中の場合も含む)
        "started_in": any(
            c.status == STATUS_DOING and in_period(c.changed_at) for c in task.status_changes
        ),
        "completed_on": completed_on,
        "completed_in": completed_on is not None and start <= completed_on <= end,
        "is_open": is_open,
        "overdue": is_open and due is not None and due <= end,
        "due_soon": (is_open and due is not None
                     and end < due <= end + timedelta(days=DUE_SOON_DAYS)),
        "outcome_quant": task.outcome_quant_actual_label or "",
        "outcome_qual": _one_line(task.outcome_qual_actual),
        "outcome_value": task.outcome_quant_actual,
        "outcome_unit": task.outcome_quant_actual_unit,
    }


def _is_relevant(fact):
    """週報に関係するタスクか(未完了、または期間内に動きがあった)。"""
    return bool(
        fact["is_open"] or fact["comments"] or fact["changes"]
        or fact["completed_in"] or fact["created_in"]
    )


def _person_material(user, facts, workload_row):
    """1人分の材料。facts は対象者全員の関係タスク(重複なし)。"""
    mine = sorted((f for f in facts if user.id in f["assignee_ids"]), key=_sort_key)

    comments = sorted(
        (dict(c, task=f["title"]) for f in mine for c in f["comments"]),
        key=lambda c: c["at"],
    )
    changes = sorted(
        (dict(c, task=f["title"]) for f in mine for c in f["changes"]),
        key=lambda c: c["at"],
    )
    open_tasks = [f for f in mine if f["is_open"]]
    completed = [f for f in mine if f["completed_in"]]
    created = [f for f in mine if f["created_in"]]

    return {
        "user_id": user.id,
        "name": user.display_name,
        "open_tasks": open_tasks,
        "comments": comments,
        "changes": changes,
        "completed": completed,
        "created": created,
        "silent": [f for f in open_tasks if not f["comments"]],
        "overdue": [f for f in open_tasks if f["overdue"]],
        "due_soon": [f for f in open_tasks if f["due_soon"]],
        "doing_count": sum(1 for f in open_tasks if f["status"] == STATUS_DOING),
        "total_h": workload_row["total_h"] if workload_row else 0.0,
        "spare": workload_row["spare"] if workload_row else 0.0,
        # 動きの有無(無ければ AI を使わず「今週の記載なし」にする)
        "has_activity": bool(comments or changes or completed or created),
    }


def _team_metrics(facts, persons):
    """チーム全体の集計(重複なし)とヒト別の行。"""
    completed = sorted((f for f in facts if f["completed_in"]), key=_sort_key)
    overdue = sorted((f for f in facts if f["overdue"]), key=_sort_key)

    money = hour = 0.0
    for f in completed:
        kind, value = _annualize(f["outcome_value"], f["outcome_unit"])
        if kind == _OUTCOME_MONEY:
            money += value
        elif kind == _OUTCOME_HOUR:
            hour += value

    rows = [
        {
            "name": p["name"],
            "completed": len(p["completed"]),
            "doing": p["doing_count"],
            "overdue": len(p["overdue"]),
            "comments": len(p["comments"]),
            "total_h": p["total_h"],
            "spare": p["spare"],
        }
        for p in persons
    ]
    return {
        "person_count": len(persons),
        "completed": len(completed),
        "started": sum(1 for f in facts if f["started_in"]),
        "created": sum(1 for f in facts if f["created_in"]),
        "doing": sum(1 for f in facts if f["is_open"] and f["status"] == STATUS_DOING),
        "hold": sum(1 for f in facts if f["is_open"] and f["status"] == STATUS_HOLD),
        "todo": sum(1 for f in facts if f["is_open"] and f["status"] == STATUS_TODO),
        "overdue": len(overdue),
        "comments": sum(len(f["comments"]) for f in facts),
        "money_act": round(money, 1),   # ￥/年
        "hour_act": round(hour, 1),     # ｈ/年
        "completed_tasks": completed,
        "overdue_tasks": overdue,
        "rows": rows,
    }


def collect_weekly_material(start, end, users, today=None):
    """対象者(users)の期間 [start, end] の材料を集める。

    戻り値: {"start", "end", "persons": [1人分の材料...], "team": チーム全体の集計}
    users の順(表示名順)で persons を並べる。DBは読み取りのみ。
    """
    today = today or date.today()
    user_ids = [u.id for u in users]
    end_dt = datetime.combine(end, time.max)

    tasks = []
    if user_ids:
        tasks = (
            Task.query.filter(Task.assignees.any(User.id.in_(user_ids)))
            .options(
                selectinload(Task.assignees),
                selectinload(Task.comments),
                selectinload(Task.status_changes),
            )
            .all()
        )

    facts = []
    for task in tasks:
        # 期間より後に登録されたタスクは対象外(過去の期間を作成する場合)
        if task.created_at is not None and task.created_at > end_dt:
            continue
        fact = _task_facts(task, start, end)
        if _is_relevant(fact):
            facts.append(fact)

    workload_rows, _totals = _build_workload(today, users)
    workload = {r["user"].id: r for r in workload_rows}

    persons = [_person_material(u, facts, workload.get(u.id)) for u in users]
    return {
        "start": start,
        "end": end,
        "persons": persons,
        "team": _team_metrics(facts, persons),
    }


# =============================================================================
# 6-5. 週報: 文章づくり(AI整形とルールベース)
# =============================================================================
# 週報の文章づくり(AI整形とルールベースの代替文)。
#
# 流れ:
#   1. 動きのあった対象者ごとに AI を1回呼ぶ(個人の見本＋注意点＋その人の材料)
#      動きの無い対象者は AI を使わず「今週の記載なし」と未完了の担当タスクを載せる
#   2. チーム全体で AI を1回呼ぶ(チーム全体の見本＋注意点＋コードで集計した数値＋各人の文章)
#
# AI が未設定、または呼び出しに失敗した部分は、同じ「■見出し／・箇条書き」の形で
# ルールベースの文章を作り、文書側で「AI未整形」と注記する。
# AI は部分ごと(各人・チーム全体)に毎回呼び出し、失敗した部分だけを代替の文章にする
# (一時的なエラーで、残りの部分まで AI未整形 にならないようにするため)。
#
# 見本・注意点の差し込み記号 {期間} {氏名} {作成日} は、AIに送る前に置き換える。

SYSTEM_PROMPT = """あなたはチームの週報を作成する担当者です。次のルールを必ず守ってください。
・【材料】に書かれた事実だけを使う。材料に無いことは書かない・推測しない。
・数値は材料に書かれたとおりに使う。新しい数値を計算・集計しない（合計・平均・割合なども出さない）。
・【見本】の見出し・順序・口調・分量に合わせる。
・【見本】に書かれた事実（案件名・数値・人名・出来事など）は決して使わない。見本は書き方の参考にだけ使う。
・見出しの行は「■」で始め、箇条書きの行は「・」で始める。
・プレーンテキストで書く。Markdown（#、**、-、表など）は使わない。
・書くべき事実が材料に無い項目は、作らずに「特になし」と書く。"""

NOTE_AI_OFF = "AI未整形（AIが未設定のため、集計内容をそのまま記載しています）"
NOTE_AI_FAILED = "AI未整形（AIの呼び出しに失敗したため、集計内容をそのまま記載しています）"
NO_ACTIVITY = "今週の記載なし"
WEEKLY_NONE_TEXT = "特になし"


# --------------------------------------------------------------------------- #
# 表記の小道具
# --------------------------------------------------------------------------- #
def _mmdd(d):
    """日付(または日時)を mm/dd に。None は ―。"""
    return d.strftime("%m/%d") if d else "―"


def _money(value):
    return "{:,.0f} ￥/年".format(value)


def _hour(value):
    return "{:,.1f} ｈ/年".format(value)


def _outcome(f):
    """完了タスクの成果(実績)の表記。無ければ空文字。"""
    parts = [p for p in (f["outcome_quant"], f["outcome_qual"]) if p]
    return " ／ ".join(parts)


def _task_line(f):
    """タスク1件の1行表記(タイトル【状態】(優先度・開始・期限・規模))。"""
    info = ["優先度 {}".format(f["priority"] or "―"),
            "開始 {}".format(_mmdd(f["start_date"])),
            "期限 {}".format(_mmdd(f["due_date"]))]
    if f["scale_label"]:
        info.append("規模 {}".format(f["scale_label"]))
    return "{}【{}】（{}）".format(f["title"], f["status"], "・".join(info))


def _section(lines, title, items):
    """材料の1区分を追加する(項目が無ければ「なし」)。"""
    lines.append("[{}]".format(title))
    if items:
        lines.extend("・" + item for item in items)
    else:
        lines.append("・なし")
    lines.append("")


def _fill(text, period, name, created_on):
    """見本・注意点の差し込み記号を置き換える。"""
    return (text or "").replace("{期間}", period).replace("{氏名}", name).replace(
        "{作成日}", created_on.strftime("%Y/%m/%d"))


# --------------------------------------------------------------------------- #
# AIに渡す材料(テキスト)
# --------------------------------------------------------------------------- #
def person_material_text(p, period):
    """1人分の材料をテキストにする。"""
    lines = [
        "氏名: {}".format(p["name"]),
        "期間: {}".format(period),
        "月間負荷: {:.1f}h ／ 余力: {:.1f}h".format(p["total_h"], p["spare"]),
        "",
    ]
    _section(lines, "期間内に完了したタスク（成果は実績）", [
        "{}（完了日 {}）{}".format(
            f["title"], _mmdd(f["completed_on"]),
            " 成果: " + _outcome(f) if _outcome(f) else "")
        for f in p["completed"]
    ])
    _section(lines, "期間内の進捗記載（日付・タスク・記載者・内容）", [
        "{} {}（記載: {}）: {}".format(_mmdd(c["at"]), c["task"], c["author"], c["text"])
        for c in p["comments"]
    ])
    _section(lines, "期間内のステータス変更", [
        "{} {} → {}".format(_mmdd(c["at"]), c["task"], c["status"]) for c in p["changes"]
    ])
    _section(lines, "期間内に新しく登録されたタスク", [
        "{}（登録時の状態: {}）".format(f["title"], f["initial_status"]) for f in p["created"]
    ])
    _section(lines, "担当している未完了のタスク", [_task_line(f) for f in p["open_tasks"]])
    _section(lines, "期限超過の未完了タスク", [
        "{}（期限 {}・{}）".format(f["title"], _mmdd(f["due_date"]), f["status"])
        for f in p["overdue"]
    ])
    _section(lines, "今後7日以内に期限を迎えるタスク", [
        "{}（期限 {}・{}）".format(f["title"], _mmdd(f["due_date"]), f["status"])
        for f in p["due_soon"]
    ])
    _section(lines, "期間内に進捗記載の無い未完了タスク", [f["title"] for f in p["silent"]])
    return "\n".join(lines).strip()


def team_material_text(material, person_texts, period):
    """チーム全体の材料(コードで集計した数値＋各人の文章)をテキストにする。"""
    team = material["team"]
    names = "、".join(p["name"] for p in material["persons"])
    lines = [
        "期間: {}".format(period),
        "対象者: {}名（{}）".format(team["person_count"], names),
        "",
    ]
    _section(lines, "チーム全体の集計（システムで集計済み。複数担当のタスクは1件として数える）", [
        "期間内に完了: {}件".format(team["completed"]),
        "期間内に着手（進行中になった）: {}件".format(team["started"]),
        "期間内に新規登録: {}件".format(team["created"]),
        "現在 進行中: {}件".format(team["doing"]),
        "現在 保留: {}件".format(team["hold"]),
        "現在 未着手: {}件".format(team["todo"]),
        "期限超過（未完了）: {}件".format(team["overdue"]),
        "期間内の進捗記載: {}件".format(team["comments"]),
        "期間内に完了したタスクの成果（実績・年換算の合計）: 金額 {} ／ 時間 {}".format(
            _money(team["money_act"]), _hour(team["hour_act"])),
    ])
    _section(lines, "ヒト別の集計", [
        "{}: 完了 {}件 ／ 進行中 {}件 ／ 期限超過 {}件 ／ 進捗記載 {}件 ／ 月間負荷 {:.1f}h ／ 余力 {:.1f}h"
        .format(r["name"], r["completed"], r["doing"], r["overdue"], r["comments"],
                r["total_h"], r["spare"])
        for r in team["rows"]
    ])
    _section(lines, "期間内に完了したタスク", [
        "{}（担当 {}）{}".format(
            f["title"], f["assignees"] or "未割当",
            " 成果: " + _outcome(f) if _outcome(f) else "")
        for f in team["completed_tasks"]
    ])
    _section(lines, "期限超過の未完了タスク", [
        "{}（担当 {}・期限 {}・{}）".format(
            f["title"], f["assignees"] or "未割当", _mmdd(f["due_date"]), f["status"])
        for f in team["overdue_tasks"]
    ])
    lines.append("[各メンバーの週報（個人分）]")
    for name, text in person_texts:
        lines.append("【{}】".format(name))
        lines.append(text.strip())
        lines.append("")
    return "\n".join(lines).strip()


# --------------------------------------------------------------------------- #
# ルールベースの文章(AIが使えないときの代替)
# --------------------------------------------------------------------------- #
def _block(lines, heading, items):
    lines.append("■" + heading)
    if items:
        lines.extend("・" + item for item in items)
    else:
        lines.append("・" + WEEKLY_NONE_TEXT)


def person_rule_text(p):
    """1人分の文章(ルールベース)。"""
    results = []
    for f in p["completed"]:
        outcome = _outcome(f)
        results.append("完了: {}（{}）".format(
            f["title"], "成果: " + outcome if outcome else "完了日 " + _mmdd(f["completed_on"])))
    # 進捗記載はタスクごとにまとめる(登場順)
    by_task = {}
    for c in p["comments"]:
        by_task.setdefault(c["task"], []).append(
            "{} {}（{}）".format(_mmdd(c["at"]), c["text"], c["author"]))
    results.extend("{}: {}".format(title, " ／ ".join(items)) for title, items in by_task.items())

    changes = ["{} {} → {}".format(_mmdd(c["at"]), c["task"], c["status"]) for c in p["changes"]]
    changes.extend("新規登録: {}（{}）".format(f["title"], f["initial_status"]) for f in p["created"])

    issues = ["期限超過: {}（期限 {}・{}）".format(f["title"], _mmdd(f["due_date"]), f["status"])
              for f in p["overdue"]]
    if p["silent"]:
        issues.append("今週の進捗記載なし: {}".format("、".join(f["title"] for f in p["silent"])))

    plans = ["期限が近い: {}（期限 {}）".format(f["title"], _mmdd(f["due_date"])) for f in p["due_soon"]]

    lines = []
    _block(lines, "今週の実績", results)
    _block(lines, "状況の変化", changes)
    _block(lines, "課題・遅れ", issues)
    _block(lines, "来週の予定", plans)
    _block(lines, "負荷", ["月間負荷 {:.1f}h ／ 余力 {:.1f}h".format(p["total_h"], p["spare"])])
    return "\n".join(lines)


def no_activity_text(p):
    """動きの無かった対象者の文章(「今週の記載なし」＋未完了の担当タスク)。"""
    lines = [NO_ACTIVITY]
    _block(lines, "未完了の担当タスク", [
        "{}【{}】（期限 {}）".format(f["title"], f["status"], _mmdd(f["due_date"]))
        for f in p["open_tasks"]
    ])
    return "\n".join(lines)


def team_rule_text(material, period):
    """チーム全体の文章(ルールベース)。"""
    team = material["team"]
    lines = []
    _block(lines, "全体の状況（{}・対象 {}名）".format(period, team["person_count"]), [
        "完了 {}件 ／ 着手 {}件 ／ 新規 {}件 ／ 進行中 {}件 ／ 保留 {}件 ／ 期限超過 {}件".format(
            team["completed"], team["started"], team["created"],
            team["doing"], team["hold"], team["overdue"]),
        "進捗記載 {}件".format(team["comments"]),
    ])
    results = ["成果の合計（年換算）: 金額 {} ／ 時間 {}".format(
        _money(team["money_act"]), _hour(team["hour_act"]))] if team["completed"] else []
    results.extend(
        "{}（担当 {}）{}".format(
            f["title"], f["assignees"] or "未割当",
            ": " + _outcome(f) if _outcome(f) else "")
        for f in team["completed_tasks"]
    )
    _block(lines, "今週完了したタスクと成果", results)
    _block(lines, "課題・遅れ", [
        "期限超過: {}（担当 {}・期限 {}）".format(
            f["title"], f["assignees"] or "未割当", _mmdd(f["due_date"]))
        for f in team["overdue_tasks"]
    ])
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# AI 呼び出し
# --------------------------------------------------------------------------- #
def _messages(sample, guidelines, material_text, instruction):
    content = "\n".join([
        "【見本】（書き方の参考。ここに書かれた事実は使わないこと）",
        sample.strip() or "（見本なし）",
        "",
        "【書く際の注意点】",
        guidelines.strip() or WEEKLY_NONE_TEXT,
        "",
        "【材料】（ここに書かれた事実だけを使うこと）",
        material_text,
        "",
        instruction,
    ])
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


def _clean_ai_reply(text):
    """AIの応答を整える(改行の統一・コードブロック記号の除去・前後の空白除去)。"""
    lines = []
    for line in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.strip().startswith("```"):
            continue
        lines.append(line.rstrip())
    return "\n".join(lines).strip()


class _AiSession:
    """1回の週報作成の間の AI 呼び出し状況(部分ごとに呼び、失敗した部分だけ代替文にする)。"""

    def __init__(self):
        self.configured = ai_is_configured()
        self.error = None  # 最初に失敗したときのエラー(前回の結果の表示用)
        self.used = 0
        self.fallback = 0

    def write(self, messages, rule_text):
        """AIで書く。使えなければ rule_text を使う。戻り値: (本文, AIを使ったか, 注記)"""
        if not self.configured:
            self.fallback += 1
            return rule_text, False, NOTE_AI_OFF
        text, error = ai_chat(messages)
        text = _clean_ai_reply(text) if error is None else ""
        if text:
            self.used += 1
            return text, True, None
        if self.error is None:
            self.error = error or "AIの応答が空でした。"
        self.fallback += 1
        return rule_text, False, NOTE_AI_FAILED


def write_report(material, settings, created_on):
    """材料から、チーム全体と各人の文章を作る。

    戻り値:
      {"team": {"text", "ai", "note"},
       "persons": [{"name", "text", "ai", "note", "no_activity"}],
       "ai_configured", "ai_error", "ai_used", "ai_fallback"}
    """
    period = period_label(material["start"], material["end"])
    ai = _AiSession()

    persons = []
    for p in material["persons"]:
        if not p["has_activity"]:
            persons.append({"name": p["name"], "text": no_activity_text(p),
                            "ai": False, "note": None, "no_activity": True})
            continue
        messages = _messages(
            _fill(settings["person_sample"], period, p["name"], created_on),
            _fill(settings["guidelines"], period, p["name"], created_on),
            person_material_text(p, period),
            "上の材料だけを使って、{}の週報（個人分）を【見本】の見出し・順序・口調・分量に"
            "合わせて作成してください。氏名の見出しは不要です。".format(p["name"]),
        )
        text, used_ai, note = ai.write(messages, person_rule_text(p))
        persons.append({"name": p["name"], "text": text, "ai": used_ai,
                        "note": note, "no_activity": False})

    team_name = "チーム全体"
    messages = _messages(
        _fill(settings["team_sample"], period, team_name, created_on),
        _fill(settings["guidelines"], period, team_name, created_on),
        team_material_text(material, [(p["name"], p["text"]) for p in persons], period),
        "上の材料だけを使って、チーム全体の週報を【見本】の見出し・順序・口調・分量に"
        "合わせて作成してください。メンバー別の集計表はシステムが別に付けるため、表は作らないでください。",
    )
    text, used_ai, note = ai.write(messages, team_rule_text(material, period))

    return {
        "team": {"text": text, "ai": used_ai, "note": note},
        "persons": persons,
        "ai_configured": ai.configured,
        "ai_error": ai.error,
        "ai_used": ai.used,
        "ai_fallback": ai.fallback,
    }


# =============================================================================
# 6-6. 週報: Word(.docx)の作成
# =============================================================================
# 週報のWord(.docx)ファイルを作る(python-docx)。
#
# 文書の構成(1回の作成で1ファイル):
#   タイトル「週報」／対象期間／「(アプリ名)が自動作成（作成日時）」
#   チーム全体 : 見出し＋文章＋メンバー別の集計表(コードで作成)＋チーム合計の1行
#   個人       : 改ページして1人1ページ(氏名の見出し＋文章)
#
# 文章(AI または ルールベース)は1行ずつ次のように変換する:
#   ■ または 【 で始まる行 → 見出し2
#   ・ - * で始まる行      → 箇条書き(List Bullet)
#   空行                   → 飛ばす
#   Markdown の記号(行頭の #・**)は取り除く
# Word(XML)に入れられない制御文字(貼り付けた端末出力の ESC など)は、すべての文字列から取り除く
# (1文字でも残っていると文書全体が作成できないため)。

FONT_NAME = "Yu Gothic"
FONT_SIZE = Pt(10.5)

TABLE_HEADERS = ["氏名", "完了", "進行中", "期限超過", "進捗記載数", "月間負荷h", "余力h"]

_MD_HEADING = re.compile(r"^#{1,6}\s*")
_MD_RULE = re.compile(r"^[-=_*]{3,}$")
_BULLET_MARKS = ("・", "-", "*", "•")
_HEADING_MARKS = ("■", "【")
# XML 1.0 で使えない文字(タブ・改行以外の制御文字、サロゲート、U+FFFE/U+FFFF)
_XML_INVALID = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


def _xml_text(value):
    """Word に入れられない制御文字などを取り除いた文字列にする。"""
    return _XML_INVALID.sub("", str(value or ""))


def _set_style_font(style, size=None):
    """スタイルのフォントを游ゴシックにする(日本語用の東アジアフォントも指定)。"""
    style.font.name = FONT_NAME
    if size is not None:
        style.font.size = size
    rfonts = style.element.get_or_add_rPr().get_or_add_rFonts()
    rfonts.set(qn("w:eastAsia"), FONT_NAME)
    # テーマのフォント指定が残っていると明示したフォントより優先されるため外す
    for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
        rfonts.attrib.pop(qn(attr), None)


def _new_document(title):
    doc = Document()
    _set_style_font(doc.styles["Normal"], FONT_SIZE)
    for name in ("Title", "Heading 1", "Heading 2", "List Bullet"):
        try:
            _set_style_font(doc.styles[name])
        except KeyError:
            pass

    # A4・余白20mm
    section = doc.sections[0]
    section.page_width, section.page_height = Mm(210), Mm(297)
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(section, side, Mm(20))

    doc.core_properties.title = title
    return doc


def _add_note(doc, text):
    """小さめの灰色の注記(「AI未整形」など)。"""
    run = doc.add_paragraph().add_run("※" + _xml_text(text))
    run.italic = True
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(0x6C, 0x75, 0x7D)


def add_text(doc, text):
    """文章を1行ずつ見出し・箇条書き・本文に変換して追加する。"""
    for raw in (text or "").splitlines():
        line = _xml_text(raw).strip().replace("**", "")
        is_md_heading = bool(_MD_HEADING.match(line))
        line = _MD_HEADING.sub("", line).strip()
        if not line or _MD_RULE.match(line):
            continue
        if is_md_heading or line.startswith(_HEADING_MARKS):
            doc.add_paragraph(line, style="Heading 2")
        elif line.startswith(_BULLET_MARKS):
            body = line[1:].strip()
            if body:
                doc.add_paragraph(body, style="List Bullet")
        else:
            doc.add_paragraph(line)


def _add_member_table(doc, rows):
    """メンバー別の集計表(コードで集計した値をそのまま載せる)。"""
    table = doc.add_table(rows=1, cols=len(TABLE_HEADERS))
    table.style = "Table Grid"
    for cell, header in zip(table.rows[0].cells, TABLE_HEADERS):
        cell.text = ""
        run = cell.paragraphs[0].add_run(header)
        run.bold = True
        cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
    for r in rows:
        values = [
            r["name"], str(r["completed"]), str(r["doing"]), str(r["overdue"]),
            str(r["comments"]), "{:.1f}".format(r["total_h"]), "{:.1f}".format(r["spare"]),
        ]
        for i, (cell, value) in enumerate(zip(table.add_row().cells, values)):
            cell.text = _xml_text(value)
            if i > 0:
                cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
    return table


def _team_total_line(team):
    return (
        "チーム合計（複数担当のタスクは1件）: 完了 {}件・着手 {}件・新規 {}件・"
        "進行中 {}件・保留 {}件・期限超過 {}件 ／ 成果（期間内に完了・年換算）: "
        "金額 {:,.0f} ￥/年・時間 {:,.1f} ｈ/年"
    ).format(
        team["completed"], team["started"], team["created"], team["doing"],
        team["hold"], team["overdue"], team["money_act"], team["hour_act"],
    )


def build_docx(material, written, created_at, app_name):
    """週報の .docx を作ってバイト列で返す。

    material : collect_weekly_material() の戻り値(期間・チーム集計)
    written  : write_report() の戻り値(チーム全体・各人の文章)
    """
    period = period_label(material["start"], material["end"])
    doc = _new_document("週報 {}".format(period))

    doc.add_heading("週報", level=0)
    doc.add_paragraph("対象期間: {}（対象 {}名）".format(period, len(written["persons"])))
    info = doc.add_paragraph().add_run(
        "{}が自動作成（{}）".format(_xml_text(app_name), created_at.strftime("%Y/%m/%d %H:%M")))
    info.font.size = Pt(9)
    info.font.color.rgb = RGBColor(0x6C, 0x75, 0x7D)

    # ---- チーム全体 ----
    doc.add_heading("チーム全体", level=1)
    team_text = written["team"]
    if team_text["note"]:
        _add_note(doc, team_text["note"])
    add_text(doc, team_text["text"])

    doc.add_paragraph("■メンバー別の集計（システム集計）", style="Heading 2")
    _add_member_table(doc, material["team"]["rows"])
    total = doc.add_paragraph().add_run(_team_total_line(material["team"]))
    total.font.size = Pt(9)

    # ---- 個人(1人1ページ) ----
    for person in written["persons"]:
        doc.add_page_break()
        doc.add_heading(_xml_text(person["name"]), level=1)
        if person["note"]:
            _add_note(doc, person["note"])
        add_text(doc, person["text"])

    bio = BytesIO()
    doc.save(bio)
    return bio.getvalue()


# =============================================================================
# 6-7. 週報: 作成・送信のとりまとめ
# =============================================================================
# 週報の作成・送信のとりまとめ(画面の「今すぐ作成」と自動送信の両方から使う)。
#
# run_weekly(app, start, end, trigger, deliver):
#   1. 設定(instance/weekly_settings.json)と対象者を読み込む
#   2. 材料を集める(collect_weekly_material) → 文章を作る(write_report) → Wordにする(build_docx)
#   3. deliver に応じて:
#        "download" : ファイルを返すだけ(送信しない・前回の結果も変えない)
#        "test"     : テスト宛先(MAIL_TEST_TO、空なら差出人)に送る。Cc なし
#        "send"     : 本番の宛先(MAIL_TO・MAIL_CC)に送る
#      test / send は成否にかかわらず「前回の結果」を上書きする。
#
# start_weekly_background(...) は test / send を別スレッドで実行する(画面からの送信用。
# 画面はすぐに戻り、結果は「前回の結果」に表示される)。
# テスト送信・本番送信は同時に1つだけ実行する(二重送信の防止)。
#
# DBは読み取りのみ(書き込みは一切しない)。必ず app.app_context() の中で動く。

DELIVER_DOWNLOAD = "download"
DELIVER_TEST = "test"
DELIVER_SEND = "send"
DELIVER_CHOICES = (DELIVER_DOWNLOAD, DELIVER_TEST, DELIVER_SEND)

# 添付する Word ファイルの MIME タイプ
DOCX_MAINTYPE = "application"
DOCX_SUBTYPE = "vnd.openxmlformats-officedocument.wordprocessingml.document"

# メール送信(テスト・本番)は同時に1つだけ(二重送信を防ぐ)
_weekly_send_lock = threading.Lock()


class WeeklyError(Exception):
    """利用者に伝える想定内のエラー(対象者が未選択など)。ログにトレースは残さない。"""


def weekly_is_sending():
    """メール送信(テスト・本番)の処理中か。"""
    return _weekly_send_lock.locked()


def target_users(settings):
    """週報に載せる対象者(画面で選んだ人のうち、有効なユーザーだけ。表示名順)。

    削除されたユーザーのIDが新しく登録したユーザーに再利用されても含めないよう、
    ユーザーIDに加えてログインIDも一致する人だけを対象にする。
    """
    ids = settings.get("target_user_ids") or []
    if not ids:
        return []
    users = (
        User.query.filter(User.id.in_(ids), User.is_active.is_(True))
        .order_by(User.display_name)
        .all()
    )
    return [u for u in users if is_weekly_target(settings, u)]


def _weekly_summary(written, users, send_message=None):
    """前回の結果に残す短いメッセージ。"""
    parts = []
    if send_message:
        parts.append(send_message.rstrip("。"))
    parts.append("対象 {}名".format(len(users)))
    if not written["ai_configured"]:
        parts.append("AI未設定のためルールベースで作成")
    elif written["ai_fallback"]:
        parts.append("AI未整形 {}件（{}）".format(
            written["ai_fallback"], written["ai_error"] or "AIの呼び出しに失敗"))
    else:
        parts.append("AI整形 {}件".format(written["ai_used"]))
    return " ／ ".join(parts)


def _build_weekly(app, start, end, send_date):
    """週報を作成する。戻り値: (結果の辞書, 対象者, 文章)"""
    settings = load_weekly_settings()
    users = target_users(settings)
    if not users:
        raise WeeklyError("週報の対象者が選択されていません。設定画面で対象者を選んで保存してください。")

    material = collect_weekly_material(start, end, users)
    written = write_report(material, settings, send_date)
    data = build_docx(
        material, written, datetime.now(), app.config.get("APP_NAME") or "業務管理システム")
    return {
        "data": data,
        "filename": build_weekly_filename(settings["filename_pattern"], start, end, send_date),
        "subject": build_weekly_subject(settings["subject_pattern"], start, end, send_date),
        "body": render_pattern(settings["mail_body"], start, end, send_date),
    }, users, written


def _deliver_weekly(app, start, end, trigger, deliver, send_date):
    """テスト送信・本番送信の本体(_send_lock を持った状態で呼ぶ)。

    成否にかかわらず「前回の結果」を上書きする。
    """
    test = deliver == DELIVER_TEST
    with app.app_context():
        result = {"filename": None, "data": None}
        try:
            # 送信できない設定なら、時間のかかる作成(AI呼び出し)の前に止める
            problem = check_mail_settings(test=test)
            if problem:
                ok, message = False, problem
            else:
                result, users, written = _build_weekly(app, start, end, send_date)
                ok, send_message = send_mail(
                    result["subject"], result["body"],
                    attachments=[(result["filename"], result["data"],
                                  DOCX_MAINTYPE, DOCX_SUBTYPE)],
                    test=test,
                )
                message = _weekly_summary(written, users, send_message)
        except Exception as exc:
            ok, message = False, _weekly_error_message(app, exc)

        prefix = "期間 {}〜{}: ".format(start.strftime("%m/%d"), end.strftime("%m/%d"))
        try:
            set_weekly_last_result(trigger, ok, prefix + message)
        except Exception:
            app.logger.exception("週報の前回の結果を保存できませんでした")
        return dict(result, ok=ok, message=message)


def run_weekly(app, start, end, trigger, deliver, send_date=None):
    """週報を作成し、deliver に応じて送信する(呼び出したスレッドで最後まで実行)。

    trigger   : 前回の結果に残すきっかけ(自動 / 手動 / テスト)
    send_date : 差し込み記号 {送信日}・{作成日} の日付(省略時は今日)
    戻り値: {"ok", "message", "filename", "data"}
    例外は外に出さず、失敗は ok=False とメッセージで返す。
    テスト送信・本番送信は同時に1つだけ(処理中なら終わるまで待つ)。
    """
    if deliver not in DELIVER_CHOICES:
        raise ValueError("deliver が不正です: {}".format(deliver))
    send_date = send_date or date.today()

    if deliver == DELIVER_DOWNLOAD:
        with app.app_context():
            try:
                result, users, written = _build_weekly(app, start, end, send_date)
            except Exception as exc:
                return {"ok": False, "message": _weekly_error_message(app, exc),
                        "filename": None, "data": None}
            return dict(result, ok=True, message=_weekly_summary(written, users))

    with _weekly_send_lock:
        return _deliver_weekly(app, start, end, trigger, deliver, send_date)


def start_weekly_background(app, start, end, trigger, deliver, send_date=None):
    """テスト送信・本番送信を別スレッドで始める(画面の「今すぐ作成」用)。

    既に送信処理中なら何もせず False を返す(二重送信の防止)。
    結果は「前回の結果」に記録される。
    """
    if deliver not in (DELIVER_TEST, DELIVER_SEND):
        raise ValueError("deliver が不正です: {}".format(deliver))
    if not _weekly_send_lock.acquire(blocking=False):
        return False
    send_date = send_date or date.today()

    def worker():
        try:
            _deliver_weekly(app, start, end, trigger, deliver, send_date)
        except Exception:
            app.logger.exception("週報の送信処理でエラーが発生しました")
        finally:
            _weekly_send_lock.release()

    try:
        threading.Thread(target=worker, name="weekly-send", daemon=True).start()
    except Exception:
        _weekly_send_lock.release()
        raise
    return True


def _weekly_error_message(app, exc):
    """例外を画面・前回の結果用の短い文言にする(想定外のものはログにトレースを残す)。"""
    if isinstance(exc, WeeklyError):
        app.logger.warning("週報: %s", exc)
        return str(exc)
    app.logger.exception("週報の作成・送信に失敗しました")
    return "週報の作成中にエラーが発生しました: {}".format(exc)


# =============================================================================
# 6-8. 週報: 画面
# =============================================================================
# 週報(自動作成・メール送信)の画面と手動実行。マネージャーのみ。
#
# GET  /weekly/          週報の画面(次回の自動送信・前回の結果・メール/AIの設定状況・
#                        今すぐ作成・現在の設定の概要とファイル名/件名のプレビュー)
# POST /weekly/run       今すぐ作成: download=Wordをダウンロード / test=テスト送信 / send=本番送信
# GET  /weekly/preview   入力中のファイル名・件名のプレビュー(JSON。システム設定の「週報」タブで使う)
# POST /weekly/settings  旧URL。システム設定の保存(POST /system/settings/weekly)へ転送する
#
# 週報の設定(曜日・時刻・対象者・見本など)は、システム設定の「週報」タブで変更する
# (入力チェックは parse_weekly_form()、保存先は instance/weekly_settings.json)。
# メールの送信サーバー・宛先、AIの接続先・キーはシステム設定の「基本設定」タブ
# (instance/config.py)で変更する(この画面では状況だけを表示する)。

weekly_bp = Blueprint("weekly", __name__, url_prefix="/weekly")

DOCX_MIMETYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
# 「今すぐ作成」で指定できる期間の上限(日数)
RUN_MAX_DAYS = 366


@weekly_bp.before_request
def _weekly_managers_only():
    """週報の画面・作成はマネージャーのみ(未ログインはログイン画面へ)。

    login_required は OPTIONS を素通しするため使わず、ここで直接確認する。
    """
    if not current_user.is_authenticated:
        return current_app.login_manager.unauthorized()
    if not getattr(current_user, "is_manager", False):
        abort(403)


def _render_weekly(settings):
    """週報の画面を表示する(実行と状況だけ。設定はシステム設定の「週報」タブ)。"""
    today = date.today()
    users = get_active_users()
    selected = [u for u in users if is_weekly_target(settings, u)]
    run_from, run_to = period_for(today, settings["period_rule"])

    upcoming = next_weekly_run(settings, datetime.now())
    upcoming_period = None
    if upcoming is not None:
        upcoming_period = period_label(*period_for(upcoming.date(), settings["period_rule"]))

    mail = mail_settings()
    test_to, _cc = mail_recipients(test=True)
    return render_template(
        "weekly/index.html",
        settings=settings,
        selected_users=selected,
        selected_count=len(selected),
        weekday_labels=WEEKDAY_LABELS,
        period_rules=PERIOD_RULES,
        preview=preview_names(settings, today),
        upcoming=upcoming,
        upcoming_period=upcoming_period,
        last=settings["last_result"],
        run_from=run_from,
        run_to=run_to,
        mail=mail,
        mail_problem=check_mail_settings(test=False),
        test_problem=check_mail_settings(test=True),
        test_to_count=len(test_to),
        test_to_is_from=not mail["test_to"],
        ai_enabled=ai_is_configured(),
        ai_status=ai_status_label(),
        sending=weekly_is_sending(),
    )


@weekly_bp.route("/", endpoint="index")
def weekly_index():
    return _render_weekly(load_weekly_settings())


@weekly_bp.route("/settings", methods=["POST"], endpoint="save_settings")
def weekly_save_settings():
    """旧URL(設定の保存)。設定はシステム設定に移したため、そちらの保存へ転送する。

    307 で転送するのでフォームの内容はそのまま届き、保存後はシステム設定の「週報」タブに戻る。
    """
    return redirect(url_for("system.save_weekly"), code=307)


@weekly_bp.route("/preview")
def preview():
    """入力中のパターンで、今日作成した場合のファイル名・件名を返す。"""
    settings = load_weekly_settings()
    for key in ("filename_pattern", "subject_pattern"):
        if key in request.args:
            settings[key] = request.args.get(key, "")
    if request.args.get("period_rule") in PERIOD_RULES:
        settings["period_rule"] = request.args["period_rule"]
    return jsonify(preview_names(settings, date.today()))


def _docx_response(data, filename, start, end):
    """Wordファイルを添付として返す(日本語のファイル名は RFC 5987 の filename* で渡す)。"""
    fallback = "weekly_report_{}-{}.docx".format(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
    if re.fullmatch(r"[A-Za-z0-9._ ()\-]+", filename):
        fallback = filename
    disposition = "attachment; filename=\"{}\"; filename*=UTF-8''{}".format(
        fallback, quote(filename, safe=""))
    return Response(data, mimetype=DOCX_MIMETYPE,
                    headers={"Content-Disposition": disposition})


@weekly_bp.route("/run", methods=["POST"], endpoint="run_now")
def weekly_run_now():
    action = request.form.get("action", "")
    if action not in DELIVER_CHOICES:
        abort(400)

    settings = load_weekly_settings()
    default_from, default_to = period_for(date.today(), settings["period_rule"])
    start = parse_date(request.form.get("start")) or default_from
    end = parse_date(request.form.get("end")) or default_to
    if end < start:
        start, end = end, start
    if (end - start).days + 1 > RUN_MAX_DAYS:
        flash("期間は{}日以内で指定してください。".format(RUN_MAX_DAYS), "danger")
        return redirect(url_for("weekly.index"))

    app = current_app._get_current_object()

    if action == DELIVER_DOWNLOAD:
        result = run_weekly(
            app, start, end, TRIGGER_MANUAL, DELIVER_DOWNLOAD)
        if not result["ok"]:
            flash(result["message"], "danger")
            return redirect(url_for("weekly.index"))
        return _docx_response(result["data"], result["filename"], start, end)

    if action == DELIVER_TEST:
        trigger, label = TRIGGER_TEST, "テスト送信"
    else:
        trigger, label = TRIGGER_MANUAL, "本番の宛先への送信"

    if not start_weekly_background(app, start, end, trigger, action):
        flash("別の送信を処理中です。完了してから、もう一度実行してください。", "warning")
        return redirect(url_for("weekly.index"))

    flash("{}を開始しました（期間 {}）。結果は「前回の結果」に表示されます"
          "（作成に数十秒〜数分かかる場合があります。画面を再読み込みして確認してください）。"
          .format(label, period_label(start, end)), "info")
    return redirect(url_for("weekly.index"))


# #############################################################################
# 7. 期限超過通知(毎朝のメール)
# #############################################################################
# マネージャーのみ。営業日(土日・祝日以外)の毎朝、指定の時刻に「期限を過ぎた未完了タスク」の一覧を
# 1通のメールで送る。一覧は状態(未着手／進行中・保留)ごと、担当者ごとにまとめ、
# 各タスクには直近の進捗記載(コメント)とタスク詳細画面へのリンクを付ける。
# DBは読み取りのみ(何も保存しない)。
#
#   7-1 ルール         自動送信の実行時刻の判定・次回の送信日時(純粋関数)
#   7-2 設定の保存     画面で編集する設定と前回の結果(instance/overdue_settings.json)
#   7-3 設定フォーム   設定フォームの入力チェック(システム設定の「期限超過通知」タブで使う)
#   7-4 メールの作成   期限超過タスクの収集とメール本文(テキスト版・HTML版)・件名の作成
#   7-5 とりまとめ     作成〜送信のとりまとめ(run_overdue・start_overdue_background)
#   7-6 画面           画面・プレビュー・今すぐ送信(Blueprint: overdue_bp, /overdue)
#
# アプリ共通の部品を使う: メール送信(4-2 send_mail)・営業日カレンダー(2-4)・
# 自動送信のスケジューラ(10。「flask --app app run」で起動したときだけ動く)。
# メールの送信サーバー・宛先・リンクの基準URL(APP_BASE_URL)は instance/config.py から読み込む
# (システム設定の「基本設定」タブで変更)。


# =============================================================================
# 7-1. 期限超過通知: 実行時刻の判定・次回の送信日時
# =============================================================================
# 期限超過通知の「実行時刻の判定・次回の送信日時」(純粋関数のみ)。
#
# DBにもFlaskにも依存しないため、画面・スケジューラのどこからでも使える。
# 自動送信は営業日(月〜金で、日本の祝日・休日でない日。2-4 の営業日カレンダー)だけ行う。

# 次の営業日を探す上限(日数)。連休が続いてもこれより長くはならない
_SEARCH_DAYS = 31


def overdue_due_key(settings, now):
    """今が自動送信の実行時刻なら (日付, "HH:MM") を返す。そうでなければ None。

    自動送信が有効で、今日が営業日で、今の時刻(HH:MM)が設定と一致するとき。
    """
    if not settings.get("enabled"):
        return None
    at = parse_hhmm(settings.get("time"))
    if at is None or now.strftime("%H:%M") != at.strftime("%H:%M"):
        return None
    if not is_business_day(now.date()):
        return None
    return (now.date(), at.strftime("%H:%M"))


def next_overdue_run(settings, now):
    """次回の自動送信日時(次の営業日の設定時刻)。自動送信が無効・時刻不正なら None。

    今日が営業日で、まだ設定時刻を過ぎていなければ今日。
    当日の実行時刻の「分」の間はまだ実行中とみなし、当日の日時を返す。
    """
    if not settings.get("enabled"):
        return None
    at = parse_hhmm(settings.get("time"))
    if at is None:
        return None
    candidate = datetime.combine(now.date(), time(at.hour, at.minute))
    if candidate < now.replace(second=0, microsecond=0):
        candidate += timedelta(days=1)
    for _ in range(_SEARCH_DAYS):
        if is_business_day(candidate.date()):
            return candidate
        candidate += timedelta(days=1)
    return None


# =============================================================================
# 7-2. 期限超過通知: 設定の保存・読み込み
# =============================================================================
# 期限超過通知の設定(画面で編集する値)の保存・読み込み。
#
# DBは使わず、instance/overdue_settings.json(Git管理外)に保存する。
# ファイルが無ければ既定値を使い、画面で保存したとき(または送信して前回の結果を
# 記録したとき)に作成される。
#
# ここに保存するのは「いつ・何件のコメントを載せるか」だけ。メールの送信サーバー・宛先や
# リンクの基準URLは保存しない(instance/config.py。システム設定の「基本設定」タブで変更する)。
# 画面の入力チェックは設定フォーム(7-3。システム設定の「期限超過通知」タブで使う)。
#
# 保存項目:
#   enabled       : 自動送信する/しない(既定はしない)
#   time          : 自動送信の時刻("HH:MM"。既定 "05:00")。営業日(土日・祝日以外)だけ送る
#   comment_count : 各タスクに載せる進捗記載(コメント)の件数(直近から。1〜10、既定 1)
#   last_result   : 前回の結果(日時・きっかけ・成否・メッセージ)。毎回上書き
#
# 画面の保存とバックグラウンドの送信が同時に書き込んでも壊れないよう、ロックで直列化し、
# 一時ファイルに書いてから置き換える(週報と共通の部品。2-3)。
# ファイルがあるのに読み込めない(壊れている・開けない)ときは、表示や自動送信の判定には
# 既定値を使うが、保存済みの設定を消さないよう上書きはしない(SettingsFileError)。

OVERDUE_SETTINGS_FILENAME = "overdue_settings.json"
OVERDUE_SETTINGS_LABEL = "期限超過通知の設定ファイル"

# 各タスクに載せるコメント件数の範囲
COMMENT_COUNT_MIN = 1
COMMENT_COUNT_MAX = 10

OVERDUE_DEFAULTS = {
    "enabled": False,
    "time": "05:00",
    "comment_count": 1,
    "last_result": None,
}

# 画面から保存できる項目(last_result は送信処理だけが書き込む)
OVERDUE_EDITABLE_KEYS = [k for k in OVERDUE_DEFAULTS if k != "last_result"]

_overdue_settings_lock = threading.RLock()


def _overdue_settings_path():
    return os.path.join(current_app.instance_path, OVERDUE_SETTINGS_FILENAME)


def valid_comment_count(value):
    """コメント件数として使える整数か(bool は除く)。"""
    return (isinstance(value, int) and not isinstance(value, bool)
            and COMMENT_COUNT_MIN <= value <= COMMENT_COUNT_MAX)


def _normalize_overdue_settings(data):
    """読み込んだ値を検証し、不正・欠落した項目は既定値で補う。"""
    result = copy.deepcopy(OVERDUE_DEFAULTS)
    if not isinstance(data, dict):
        return result

    if isinstance(data.get("enabled"), bool):
        result["enabled"] = data["enabled"]
    at = parse_hhmm(data.get("time")) if isinstance(data.get("time"), str) else None
    if at is not None:
        result["time"] = at.strftime("%H:%M")
    if valid_comment_count(data.get("comment_count")):
        result["comment_count"] = data["comment_count"]
    result["last_result"] = normalize_last_result(data.get("last_result"))
    return result


def load_overdue_settings():
    """現在の設定を返す(ファイルが無い・読み込めない場合は既定値)。"""
    with _overdue_settings_lock:
        try:
            data = read_json(_overdue_settings_path(), OVERDUE_SETTINGS_LABEL)
        except SettingsFileError as exc:
            current_app.logger.warning("%s（既定値を使用）", exc)
            data = None
        return _normalize_overdue_settings(data)


def _load_overdue_settings_for_update():
    """書き込む前に現在の設定を読む。

    ファイルがあるのに読み込めない場合は SettingsFileError を送出する
    (既定値で上書きして、保存済みの設定を消さないため)。
    """
    return _normalize_overdue_settings(read_json(_overdue_settings_path(), OVERDUE_SETTINGS_LABEL))


def save_overdue_settings(values):
    """画面で編集した項目を保存する(last_result は変更しない)。"""
    with _overdue_settings_lock:
        current = _load_overdue_settings_for_update()
        for key in OVERDUE_EDITABLE_KEYS:
            if key in values:
                current[key] = values[key]
        data = _normalize_overdue_settings(current)
        write_json(_overdue_settings_path(), data)
        return data


def set_overdue_last_result(trigger, ok, message):
    """前回の結果を上書きする(他の設定項目は変更しない)。

    設定ファイルが読み込めない場合は書き込まずに SettingsFileError を送出する。
    """
    with _overdue_settings_lock:
        current = _load_overdue_settings_for_update()
        current["last_result"] = new_last_result(trigger, ok, message)
        write_json(_overdue_settings_path(), current)
        return current["last_result"]


# =============================================================================
# 7-3. 期限超過通知: 設定フォーム
# =============================================================================
# 期限超過通知の設定フォームの入力チェックと表示用の値(システム設定の「期限超過通知」タブで使う)。
#
# 設定の画面はシステム設定(/system/settings?tab=overdue)にまとめてあり、
# 期限超過通知の画面(/overdue/)には実行・プレビューと状況の表示だけが残る。
# 保存先は設定の保存(7-2)のまま(instance/overdue_settings.json)。
#
#   parse_overdue_form(form)       フォームの入力を検証する → (保存する値, エラーメッセージの一覧)
#   settings_with_input(cur, v)    入力エラーで再表示するとき、保存済みの設定に入力中の値を重ねる
#                                  (週報の設定フォーム(6-3)と共通)
#   overdue_form_context(settings) フォームの表示に使う値

OVERDUE_LABEL = "期限超過通知"
OVERDUE_SAVED_MESSAGE = "期限超過通知の設定を保存しました。"


def parse_overdue_form(form):
    """フォームの入力を検証する。戻り値: (values, errors)。errors が空なら保存してよい。"""
    errors = []
    values = {"enabled": form.get("enabled") == "1"}

    at = parse_hhmm(form.get("time"))
    if at is not None:
        values["time"] = at.strftime("%H:%M")
    else:
        errors.append("送信する時刻を「時:分」（例: 05:00）で入力してください。")

    raw_count = (form.get("comment_count") or "").strip()
    count = int(raw_count) if raw_count.isdecimal() else None
    if valid_comment_count(count):
        values["comment_count"] = count
    else:
        errors.append("表示するコメント件数は{}〜{}の数字で入力してください。".format(
            COMMENT_COUNT_MIN, COMMENT_COUNT_MAX))
    return values, errors


def overdue_form_context(settings):
    """期限超過通知の設定フォームの表示に使う値。"""
    return {
        "settings": settings,
        "comment_min": COMMENT_COUNT_MIN,
        "comment_max": COMMENT_COUNT_MAX,
    }


# =============================================================================
# 7-4. 期限超過通知: タスクの収集とメールの作成
# =============================================================================
# 期限超過タスクの収集と、メール(件名・テキスト版・HTML版)の作成。
#
# 期限超過 = 期限(due_date)が今日より前で、完了していないタスク。
#   ■未着手／進行中　期限超過一覧 : 状態が「未着手」「進行中」
#   ■保留　期限超過一覧           : 状態が「保留」
# 各区分の中は担当者ごとにまとめる。複数担当のタスクは各担当者の下に載せる。
# 無効化されたユーザーが担当のタスクもその人の下に載せ、名前に「［無効］」を付ける
# (担当の付け替えが必要なことが分かるように)。担当者がいないタスクは「担当者なし」にまとめる。
# 担当者は件数の多い順(同数なら表示名順。「担当者なし」は同数の中で最後)、
# タスクは期限の古い順(超過の長い順)に並べる。
#
# 各タスクには直近の進捗記載(コメント)を comment_count 件まで、古い順に載せる
# (タスク名の次の行から1件ずつ。記載が無ければ「コメントなし」)。
# 経過日数は営業日で数え「M日前（土日祝除く）」と書く(今日のものは「本日」)。
# 本文は1行にまとめ(改行は空白に)、長いものは COMMENT_TEXT_MAX 文字で切る。
#
# リンクは APP_BASE_URL(instance/config.py。システム設定の「基本設定」タブで変更)＋タスク詳細画面のパス。
# APP_BASE_URL が空・不正ならリンクは付けない(タスク名だけ)。
# テキスト版は「タスク名（URL）」、HTML版はタスク名をリンクにする。HTML版は
# テンプレート(templates.html の overdue/mail.html)で作り、すべての値をエスケープする。
#
# DBは読み取りのみ。app_context の中で呼ぶ(リクエストは不要)。

# 区分: (キー, 見出し, 対象の状態, タスクの状態を表示するか)
SECTION_DEFS = (
    ("active", "未着手／進行中", (STATUS_TODO, STATUS_DOING), True),
    ("hold", "保留", (STATUS_HOLD,), False),
)
UNASSIGNED_LABEL = "担当者なし"
INACTIVE_MARK = "［無効］"
NO_COMMENT = "コメントなし"
OVERDUE_NONE_TEXT = "該当なし"
COMMENT_TEXT_MAX = 200

_COMMENT_LINE_BREAKS = re.compile(r"[\r\n\t\v\f]+")
_SPACES = re.compile(r" {2,}")


# --------------------------------------------------------------------------- #
# リンク(APP_BASE_URL)
# --------------------------------------------------------------------------- #
def link_base():
    """リンクの基準URL (URL, 問題の説明)。使えなければ ("", 説明)。

    APP_BASE_URL は http:// または https:// で始まるURL(末尾の / は不要)。
    """
    raw = str(current_app.config.get("APP_BASE_URL") or "").strip()
    if not raw:
        return "", ("APP_BASE_URL が未設定のため、メールのタスク名にリンクを付けられません"
                    "（タスク名だけを載せます）。システム設定の「基本設定」タブで設定してください。")
    try:
        parts = urlsplit(raw)
        valid = (parts.scheme.lower() in ("http", "https") and bool(parts.hostname)
                 and not parts.query and not parts.fragment
                 and not any(ch.isspace() or ord(ch) < 0x20 for ch in raw))
    except ValueError:
        valid = False
    if not valid:
        return "", ("APP_BASE_URL の形式が正しくないため、メールのタスク名にリンクを付けられません"
                    "（システム設定の「基本設定」タブで、http:// または https:// で始まるURLを設定してください）。")
    return raw.rstrip("/"), None


def task_path(task_id):
    """タスク詳細画面のパス(例: /tasks/12)。リクエストの外でも作れるよう URL マップから作る。"""
    adapter = current_app.url_map.bind("localhost")
    return adapter.build("tasks.detail", {"task_id": task_id})


# --------------------------------------------------------------------------- #
# 表記の小道具
# --------------------------------------------------------------------------- #
def _date_label(d, today):
    """日付の短い表記(今年は mm/dd、それ以外は yyyy/mm/dd)。"""
    if d.year == today.year:
        return d.strftime("%m/%d")
    return d.strftime("%Y/%m/%d")


def _age_label(d, today):
    """コメントの経過日数(営業日)。今日(以降)なら「本日」。"""
    if d >= today:
        return "本日"
    return "{}日前（土日祝除く）".format(business_days_ago(d, today))


def one_line(text, limit=COMMENT_TEXT_MAX):
    """改行を空白にして1行にし、長ければ limit 文字で切る(末尾に「…」)。"""
    text = _SPACES.sub(" ", _COMMENT_LINE_BREAKS.sub(" ", text or "")).strip()
    if len(text) > limit:
        text = text[:limit - 1].rstrip() + "…"
    return text


# --------------------------------------------------------------------------- #
# 収集
# --------------------------------------------------------------------------- #
def _comment_items(task, today, comment_count):
    """直近 comment_count 件のコメント(古い順)。"""
    comments = sorted(task.comments, key=lambda c: (c.created_at or datetime.min, c.id))
    items = []
    for c in comments[-comment_count:]:
        written = (c.created_at or datetime.now()).date()
        author = c.user.display_name if c.user is not None else "（不明）"
        items.append({
            "head": "【{} {} {}】".format(_age_label(written, today),
                                        _date_label(written, today), author),
            "text": one_line(c.body),
        })
    return items


def _task_item(task, today, comment_count, base, show_status):
    """タスク1件分の表示用の値。"""
    due = "期限 {}".format(_date_label(task.due_date, today))
    return {
        "id": task.id,
        "title": one_line(task.title, limit=200),
        "due_date": task.due_date,
        "meta": "［{}・{}］".format(task.status, due) if show_status else "［{}］".format(due),
        "url": base + task_path(task.id) if base else "",
        "comments": _comment_items(task, today, comment_count),
        # 担当者(無効化されたユーザーも含む)。(ユーザーID, 表示名, 有効か)
        "owners": [(u.id, u.display_name, bool(u.is_active)) for u in task.assignees],
    }


def _group(items):
    """担当者ごとにまとめる(件数の多い順 → 表示名順。「担当者なし」は同数の中で最後)。"""
    buckets = {}
    for item in items:
        for owner_id, name, active in item["owners"] or [(None, UNASSIGNED_LABEL, True)]:
            bucket = buckets.setdefault(
                owner_id, {"name": name, "unassigned": owner_id is None, "active": active,
                           "tasks": []})
            bucket["tasks"].append(item)
    groups = []
    for bucket in buckets.values():
        bucket["tasks"].sort(key=lambda i: (i["due_date"], i["id"]))
        bucket["count"] = len(bucket["tasks"])
        bucket["label"] = "{}{}{}（{}件）".format(
            bucket["name"], "" if bucket["unassigned"] else "さん",
            "" if bucket["active"] else INACTIVE_MARK, bucket["count"])
        groups.append(bucket)
    groups.sort(key=lambda g: (-g["count"], g["unassigned"], g["name"]))
    return groups


def collect_overdue_tasks(today, comment_count):
    """期限超過タスクを集めて、区分・担当者ごとにまとめる。

    戻り値: {"today", "sections": [{"key", "title", "count", "groups"}...],
             "counts": {区分のキー: 件数(重複なし)}, "total", "link_problem"}
    """
    statuses = [s for _key, _title, group, _show in SECTION_DEFS for s in group]
    tasks = (
        Task.query.filter(
            Task.due_date.isnot(None),
            Task.due_date < today,
            Task.status.in_(statuses),
        )
        .options(
            selectinload(Task.assignees),
            selectinload(Task.comments).selectinload(TaskComment.user),
        )
        .all()
    )
    base, link_problem = link_base()

    sections = []
    for key, title, section_statuses, show_status in SECTION_DEFS:
        items = [
            _task_item(t, today, comment_count, base, show_status)
            for t in tasks if t.status in section_statuses
        ]
        sections.append({"key": key, "title": title, "count": len(items),
                         "groups": _group(items)})
    return {
        "today": today,
        "sections": sections,
        "counts": {s["key"]: s["count"] for s in sections},
        "total": sum(s["count"] for s in sections),
        "link_problem": link_problem,
    }


# --------------------------------------------------------------------------- #
# メール(件名・テキスト版・HTML版)
# --------------------------------------------------------------------------- #
def build_overdue_subject(data):
    """件名(例: 【期限超過】2026/10/05 未着手・進行中 3件／保留 1件)。"""
    return "【期限超過】{} 未着手・進行中 {}件／保留 {}件".format(
        data["today"].strftime("%Y/%m/%d"), data["counts"]["active"], data["counts"]["hold"])


def _intro(data):
    if data["total"] == 0:
        return "{} 時点で、期限を過ぎた未完了のタスクはありません。".format(
            data["today"].strftime("%Y/%m/%d"))
    return "{} 時点で期限を過ぎている未完了のタスクの一覧です（未着手・進行中 {}件／保留 {}件）。".format(
        data["today"].strftime("%Y/%m/%d"), data["counts"]["active"], data["counts"]["hold"])


def _footer():
    return "※このメールは{}から送信しています。".format(
        current_app.config.get("APP_NAME") or "業務管理システム")


def section_heading(section):
    return "■{}　期限超過一覧".format(section["title"])


def build_overdue_text(data):
    """テキスト版の本文(タスク名の後ろに括弧でURL)。"""
    lines = [_intro(data), ""]
    for section in data["sections"]:
        lines.append(section_heading(section))
        if not section["groups"]:
            lines.append(OVERDUE_NONE_TEXT)
        for group in section["groups"]:
            lines.append(group["label"])
            for task in group["tasks"]:
                name = task["title"]
                if task["url"]:
                    name += "（{}）".format(task["url"])
                comments = ["{}{}".format(c["head"], c["text"]) for c in task["comments"]]
                # 見やすさのため、コメントはタスク名の次の行から1件ずつ書く
                lines.append("　{}{}".format(name, task["meta"]))
                lines.extend("　　" + c for c in (comments or [NO_COMMENT]))
        lines.append("")
    lines.append(_footer())
    return "\n".join(lines)


def build_overdue_html(data, subject):
    """HTML版の本文(タスク名をリンクにする。値はテンプレートですべてエスケープする)。"""
    return render_template(
        "overdue/mail.html",
        data=data,
        subject=subject,
        intro=_intro(data),
        footer=_footer(),
        heading=section_heading,
        none_text=OVERDUE_NONE_TEXT,
        no_comment=NO_COMMENT,
    )


def build_overdue_content(today, comment_count):
    """メールの内容を作る。

    戻り値: {"subject", "text", "html", "counts", "total", "link_problem", "data"}
    """
    data = collect_overdue_tasks(today, comment_count)
    subject = build_overdue_subject(data)
    return {
        "subject": subject,
        "text": build_overdue_text(data),
        "html": build_overdue_html(data, subject),
        "counts": data["counts"],
        "total": data["total"],
        "link_problem": data["link_problem"],
        "data": data,
    }


# =============================================================================
# 7-5. 期限超過通知: 作成・送信のとりまとめ
# =============================================================================
# 期限超過通知の作成・送信のとりまとめ(画面の「今すぐ送信」と自動送信の両方から使う)。
#
# run_overdue(app, trigger, test):
#   1. 設定(instance/overdue_settings.json)を読み込む
#   2. 期限超過タスクを集めてメール(件名・テキスト版・HTML版)を作る(build_overdue_content)
#   3. test=True  : テスト宛先(MAIL_TEST_TO、空なら差出人)に送る。Cc なし
#      test=False : 本番の宛先に送る。OVERDUE_MAIL_TO が記入されていれば
#                   OVERDUE_MAIL_TO・OVERDUE_MAIL_CC、空なら MAIL_TO・MAIL_CC
#   成否にかかわらず「前回の結果」を上書きする。期限超過が0件でも送る(「該当なし」)。
#
# start_overdue_background(...) は送信を別スレッドで実行する(画面からの送信用。
# 画面はすぐに戻り、結果は「前回の結果」に表示される)。
# 送信は同時に1つだけ実行する(二重送信の防止)。
#
# DBは読み取りのみ(書き込みは一切しない)。必ず app.app_context() の中で動く。

# 本番の宛先が空のときに示す設定項目の名前
OVERDUE_TO_LABEL = "宛先（OVERDUE_MAIL_TO または MAIL_TO）"

# メール送信(テスト・本番)は同時に1つだけ(二重送信を防ぐ)
_overdue_send_lock = threading.Lock()


def overdue_is_sending():
    """メール送信(テスト・本番)の処理中か。"""
    return _overdue_send_lock.locked()


def overdue_recipients():
    """本番の宛先 (To, Cc, 使う設定の名前)。

    OVERDUE_MAIL_TO が記入されていれば OVERDUE_MAIL_TO・OVERDUE_MAIL_CC を、
    空なら週報と同じ MAIL_TO・MAIL_CC を使う。
    """
    config = current_app.config
    to = mail_addresses(config.get("OVERDUE_MAIL_TO"))
    if to:
        return to, mail_addresses(config.get("OVERDUE_MAIL_CC")), "OVERDUE_MAIL_TO / OVERDUE_MAIL_CC"
    values = mail_settings()
    return values["to"], values["cc"], "MAIL_TO / MAIL_CC"


def check_overdue_mail_settings(test=False):
    """送信に必要な設定が揃っているか。問題があればその説明、無ければ None。"""
    to, _cc, _source = overdue_recipients()
    return check_mail_settings(test, to=to, to_label=OVERDUE_TO_LABEL)


def build_overdue_mail(today=None):
    """保存済みの設定(表示するコメント件数)で、今日の時点のメールの内容を作る。"""
    settings = load_overdue_settings()
    return build_overdue_content(today or date.today(), settings["comment_count"])


def _overdue_summary(mail, send_message):
    """前回の結果に残す短いメッセージ。"""
    parts = [send_message.rstrip("。"),
             "未着手・進行中 {}件／保留 {}件".format(mail["counts"]["active"], mail["counts"]["hold"])]
    if mail["link_problem"]:
        parts.append("リンクなし（APP_BASE_URL 未設定・不正）")
    return " ／ ".join(parts)


def _deliver_overdue(app, trigger, test, today):
    """送信の本体(_send_lock を持った状態で呼ぶ)。成否にかかわらず「前回の結果」を上書きする。"""
    with app.app_context():
        try:
            problem = check_overdue_mail_settings(test)
            if problem:
                ok, message = False, problem
            else:
                mail = build_overdue_mail(today)
                to, cc, _source = overdue_recipients()
                ok, send_message = send_mail(
                    mail["subject"], mail["text"], html=mail["html"], to=to, cc=cc, test=test)
                message = _overdue_summary(mail, send_message)
        except Exception as exc:
            app.logger.exception("期限超過通知の作成・送信に失敗しました")
            ok, message = False, "期限超過通知の作成中にエラーが発生しました: {}".format(exc)

        try:
            set_overdue_last_result(trigger, ok, message)
        except Exception:
            app.logger.exception("期限超過通知の前回の結果を保存できませんでした")
        return {"ok": ok, "message": message}


def run_overdue(app, trigger, test=False, today=None):
    """期限超過通知を作成して送信する(呼び出したスレッドで最後まで実行)。

    trigger : 前回の結果に残すきっかけ(自動 / 手動 / テスト)
    today   : 期限超過の基準日(省略時は今日)
    戻り値: {"ok", "message"}。例外は外に出さず、失敗は ok=False とメッセージで返す。
    送信は同時に1つだけ(処理中なら終わるまで待つ)。
    """
    with _overdue_send_lock:
        return _deliver_overdue(app, trigger, test, today)


def start_overdue_background(app, trigger, test=False):
    """送信を別スレッドで始める(画面の「今すぐ送信」用)。

    既に送信処理中なら何もせず False を返す(二重送信の防止)。
    結果は「前回の結果」に記録される。
    """
    if not _overdue_send_lock.acquire(blocking=False):
        return False
    today = date.today()

    def worker():
        try:
            _deliver_overdue(app, trigger, test, today)
        except Exception:
            app.logger.exception("期限超過通知の送信処理でエラーが発生しました")
        finally:
            _overdue_send_lock.release()

    try:
        threading.Thread(target=worker, name="overdue-send", daemon=True).start()
    except Exception:
        _overdue_send_lock.release()
        raise
    return True


# =============================================================================
# 7-6. 期限超過通知: 画面
# =============================================================================
# 期限超過通知(毎朝のメール)の画面と手動送信。マネージャーのみ。
#
# GET  /overdue/          期限超過通知の画面(次回の自動送信・前回の結果・メール/リンクの設定状況・
#                         現在の設定の概要・今この時点のメールのプレビュー)
# POST /overdue/run       今すぐ送信: test=テスト送信 / send=本番の宛先に送信(バックグラウンド)
# POST /overdue/settings  旧URL。システム設定の保存(POST /system/settings/overdue)へ転送する
#
# 期限超過通知の設定(自動送信・時刻・コメント件数)は、システム設定の「期限超過通知」タブで変更する
# (入力チェックは parse_overdue_form()、保存先は instance/overdue_settings.json)。
# メールの送信サーバー・宛先・リンクの基準URL(APP_BASE_URL)はシステム設定の「基本設定」タブ
# (instance/config.py)で変更する(この画面では状況だけを表示する)。

overdue_bp = Blueprint("overdue", __name__, url_prefix="/overdue")

ACTION_TEST = "test"
ACTION_SEND = "send"


@overdue_bp.before_request
def _overdue_managers_only():
    """期限超過通知の画面・送信はマネージャーのみ(未ログインはログイン画面へ)。

    login_required は OPTIONS を素通しするため使わず、ここで直接確認する。
    """
    if not current_user.is_authenticated:
        return current_app.login_manager.unauthorized()
    if not getattr(current_user, "is_manager", False):
        abort(403)


def _preview_document(html):
    """プレビュー用のHTML(リンクは別タブで開く)。iframe の srcdoc に入れて表示する。"""
    return html.replace("<head>", '<head>\n<base target="_blank">', 1)


def _render_overdue(settings):
    """期限超過通知の画面を表示する(実行と状況だけ。設定はシステム設定の「期限超過通知」タブ)。"""
    mail = mail_settings()
    to, cc, source = overdue_recipients()
    test_to, _cc = mail_recipients(test=True)
    base_url, link_problem = link_base()
    # 今この時点のメールの内容。「今すぐ送信」と同じく保存済みの設定で作る
    preview = build_overdue_content(date.today(), settings["comment_count"])
    return render_template(
        "overdue/index.html",
        settings=settings,
        upcoming=next_overdue_run(settings, datetime.now()),
        weekday_labels=WEEKDAY_LABELS,
        last=settings["last_result"],
        mail=mail,
        to_count=len(to),
        cc_count=len(cc),
        recipient_source=source,
        mail_problem=check_overdue_mail_settings(test=False),
        test_problem=check_overdue_mail_settings(test=True),
        test_to_count=len(test_to),
        test_to_is_from=not mail["test_to"],
        base_url=base_url,
        link_configured=bool(str(current_app.config.get("APP_BASE_URL") or "").strip()),
        link_problem=link_problem,
        preview=preview,
        preview_document=_preview_document(preview["html"]),
        sending=overdue_is_sending(),
    )


@overdue_bp.route("/", endpoint="index")
def overdue_index():
    return _render_overdue(load_overdue_settings())


@overdue_bp.route("/settings", methods=["POST"], endpoint="save_settings")
def overdue_save_settings():
    """旧URL(設定の保存)。設定はシステム設定に移したため、そちらの保存へ転送する。

    307 で転送するのでフォームの内容はそのまま届き、保存後はシステム設定の「期限超過通知」タブに戻る。
    """
    return redirect(url_for("system.save_overdue"), code=307)


@overdue_bp.route("/run", methods=["POST"], endpoint="run_now")
def overdue_run_now():
    action = request.form.get("action", "")
    if action == ACTION_TEST:
        trigger, label, test = TRIGGER_TEST, "テスト送信", True
    elif action == ACTION_SEND:
        trigger, label, test = TRIGGER_MANUAL, "本番の宛先への送信", False
    else:
        abort(400)

    app = current_app._get_current_object()
    if not start_overdue_background(app, trigger, test=test):
        flash("別の送信を処理中です。完了してから、もう一度実行してください。", "warning")
        return redirect(url_for("overdue.index"))

    flash("{}を開始しました。結果は「前回の結果」に表示されます"
          "（画面を再読み込みして確認してください）。".format(label), "info")
    return redirect(url_for("overdue.index"))


# #############################################################################
# 8. スキルテスト
# #############################################################################
# AIが作る4択問題でテクニカルスキルの到達度を確認し、自動で登録する。
# メンバーが受験し、結果のレベルが今の到達度より高ければ skill_ratings に自動で登録する。
# マネージャーは受験履歴(全問の内容・回答・所要時間・離脱回数)・問題プールを管理し、
# 設定はシステム設定の「スキルテスト」タブで変更する
# (マネージャーはスキル管理の対象外のため受験しない)。
#
#   8-1 設定の保存     画面で編集する設定(instance/skilltest_settings.json)
#   8-2 問題の作成     AIによる問題の作成と検証(4-1 の ai_chat() を使用)
#   8-3 受験の流れ     開始・出題・回答・離脱の記録・自動終了・採点・到達度の自動登録
#   8-4 問題プール     問題プールの集計と補充(バックグラウンド)
#   8-5 設定フォーム   設定フォームの入力チェック(システム設定の「スキルテスト」タブで使う)
#   8-6 画面           Blueprint: skilltest_bp, /skilltest。メンバー用と管理用(/skilltest/admin)
#
# DBにはスキルテスト用のテーブル(skill_test_questions / skill_test_attempts / skill_test_answers。
# 3-8)だけを使い、ほかのテーブルは変更しない(到達度の自動登録で skill_ratings に行を追加・更新するだけ)。


# =============================================================================
# 8-1. スキルテスト: 設定の保存・読み込み
# =============================================================================
# スキルテストの設定(画面で編集する値)の保存・読み込み。マネージャーが編集する。
#
# DBは使わず、instance/skilltest_settings.json(Git管理外)に保存する。
# ファイルが無ければ既定値を使い、画面で保存したとき(または問題の補充の結果を
# 記録したとき)に作成される。
#
# 保存項目:
#   questions_per_level   : レベルごとの問題数({"1": 8, "2": 8, "3": 7, "4": 7})
#   time_limits           : レベルごとの1問の制限時間(秒。{"1": 60, "2": 90, "3": 150, "4": 180})
#   pass_rate             : 合格ライン(正答率 %。既定 70)
#   retake_days           : 同じスキルを再受験できるまでの日数(前回の受験開始から。0 なら制限なし)
#   max_auto_level        : テストで判定・自動登録するレベルの上限(1〜4。既定 4)
#   pool_target_per_level : 問題プールの補充で目標にする、レベルごとの有効な問題数(既定 20)
#   last_result           : 前回の問題の補充の結果(日時・きっかけ・成否・メッセージ)。毎回上書き
#
# 受験中のテストは開始時点の設定の控え(SkillTestAttempt.settings_snapshot)で採点するため、
# 設定を変えても受験中・受験済みのテストには影響しない。
#
# 画面の保存とバックグラウンドの補充が同時に書き込んでも壊れないよう、ロックで直列化し、
# 一時ファイルに書いてから置き換える(週報・期限超過通知と共通の部品。2-3)。
# ファイルがあるのに読み込めない(壊れている・開けない)ときは既定値で動き、
# 保存済みの設定を消さないよう上書きはしない(SettingsFileError)。

SKILLTEST_SETTINGS_FILENAME = "skilltest_settings.json"
SKILLTEST_SETTINGS_LABEL = "スキルテストの設定ファイル"

# テストで判定できるレベル(1〜4)。5・6 と コンセプチュアル/ヒューマンはマネージャーが評価する
SKILLTEST_LEVELS = [1, 2, 3, 4]

# 各項目の範囲(画面の入力チェックと読み込み時の検証に使う)
QUESTIONS_MIN, QUESTIONS_MAX = 1, 30         # レベルごとの問題数
TIME_LIMIT_MIN, TIME_LIMIT_MAX = 10, 900     # 1問の制限時間(秒)
PASS_RATE_MIN, PASS_RATE_MAX = 1, 100        # 合格ライン(%)
RETAKE_DAYS_MIN, RETAKE_DAYS_MAX = 0, 365    # 再受験までの日数
AUTO_LEVEL_MIN, AUTO_LEVEL_MAX = 1, 4        # 自動登録するレベルの上限
POOL_TARGET_MIN, POOL_TARGET_MAX = 1, 200    # 問題プールの目標数(レベルごと)

# 画面(システム設定の「スキルテスト」タブ)に出す各項目の範囲(st.limits.QUESTIONS_MIN などで参照)
SKILLTEST_LIMITS = {
    "QUESTIONS_MIN": QUESTIONS_MIN, "QUESTIONS_MAX": QUESTIONS_MAX,
    "TIME_LIMIT_MIN": TIME_LIMIT_MIN, "TIME_LIMIT_MAX": TIME_LIMIT_MAX,
    "PASS_RATE_MIN": PASS_RATE_MIN, "PASS_RATE_MAX": PASS_RATE_MAX,
    "RETAKE_DAYS_MIN": RETAKE_DAYS_MIN, "RETAKE_DAYS_MAX": RETAKE_DAYS_MAX,
    "AUTO_LEVEL_MIN": AUTO_LEVEL_MIN, "AUTO_LEVEL_MAX": AUTO_LEVEL_MAX,
    "POOL_TARGET_MIN": POOL_TARGET_MIN, "POOL_TARGET_MAX": POOL_TARGET_MAX,
}

SKILLTEST_DEFAULTS = {
    "questions_per_level": {"1": 8, "2": 8, "3": 7, "4": 7},
    "time_limits": {"1": 60, "2": 90, "3": 150, "4": 180},
    "pass_rate": 70,
    "retake_days": 7,
    "max_auto_level": 4,
    "pool_target_per_level": 20,
    "last_result": None,
}

# 画面から保存できる項目(last_result は問題の補充だけが書き込む)
SKILLTEST_EDITABLE_KEYS = [k for k in SKILLTEST_DEFAULTS if k != "last_result"]

_skilltest_settings_lock = threading.RLock()


def _skilltest_settings_path():
    return os.path.join(current_app.instance_path, SKILLTEST_SETTINGS_FILENAME)


def valid_int(value, low, high):
    """範囲内の整数か(bool は除く)。"""
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _per_level(data, default, low, high):
    """レベルごとの値({"1": n, ...})を検証し、不正・欠落したレベルは既定値で補う。"""
    result = dict(default)
    if isinstance(data, dict):
        for level in SKILLTEST_LEVELS:
            value = data.get(str(level))
            if valid_int(value, low, high):
                result[str(level)] = value
    return result


def _normalize_skilltest_settings(data):
    """読み込んだ値を検証し、不正・欠落した項目は既定値で補う。"""
    result = copy.deepcopy(SKILLTEST_DEFAULTS)
    if not isinstance(data, dict):
        return result
    result["questions_per_level"] = _per_level(
        data.get("questions_per_level"), SKILLTEST_DEFAULTS["questions_per_level"],
        QUESTIONS_MIN, QUESTIONS_MAX)
    result["time_limits"] = _per_level(
        data.get("time_limits"), SKILLTEST_DEFAULTS["time_limits"], TIME_LIMIT_MIN, TIME_LIMIT_MAX)
    for key, low, high in (
        ("pass_rate", PASS_RATE_MIN, PASS_RATE_MAX),
        ("retake_days", RETAKE_DAYS_MIN, RETAKE_DAYS_MAX),
        ("max_auto_level", AUTO_LEVEL_MIN, AUTO_LEVEL_MAX),
        ("pool_target_per_level", POOL_TARGET_MIN, POOL_TARGET_MAX),
    ):
        if valid_int(data.get(key), low, high):
            result[key] = data[key]
    result["last_result"] = normalize_last_result(data.get("last_result"))
    return result


def load_skilltest_settings():
    """現在の設定を返す(ファイルが無い・読み込めない場合は既定値)。"""
    with _skilltest_settings_lock:
        try:
            data = read_json(_skilltest_settings_path(), SKILLTEST_SETTINGS_LABEL)
        except SettingsFileError as exc:
            current_app.logger.warning("%s（既定値を使用）", exc)
            data = None
        return _normalize_skilltest_settings(data)


def _load_skilltest_settings_for_update():
    """書き込む前に現在の設定を読む(読み込めなければ SettingsFileError。上書きしない)。"""
    return _normalize_skilltest_settings(
        read_json(_skilltest_settings_path(), SKILLTEST_SETTINGS_LABEL))


def save_skilltest_settings(values):
    """画面で編集した項目を保存する(last_result は変更しない)。"""
    with _skilltest_settings_lock:
        current = _load_skilltest_settings_for_update()
        for key in SKILLTEST_EDITABLE_KEYS:
            if key in values:
                current[key] = values[key]
        data = _normalize_skilltest_settings(current)
        write_json(_skilltest_settings_path(), data)
        return data


def set_skilltest_last_result(trigger, ok, message):
    """前回の問題の補充の結果を上書きする(他の設定項目は変更しない)。"""
    with _skilltest_settings_lock:
        current = _load_skilltest_settings_for_update()
        current["last_result"] = new_last_result(trigger, ok, message)
        write_json(_skilltest_settings_path(), current)
        return current["last_result"]


# --------------------------------------------------------------------------- #
# 設定値の取り出し(受験開始時の控え settings_snapshot にも同じ形で使える)
# --------------------------------------------------------------------------- #
def tested_levels(settings, skill_max_level):
    """テストで判定するレベル(1〜min(上限, スキルの最大レベル))。"""
    top = min(int(settings.get("max_auto_level") or AUTO_LEVEL_MAX), AUTO_LEVEL_MAX,
              int(skill_max_level or 0))
    return list(range(1, max(top, 0) + 1))


def questions_for(settings, level):
    """そのレベルの問題数。"""
    return int(settings["questions_per_level"].get(str(level),
                                                   SKILLTEST_DEFAULTS["questions_per_level"]["1"]))


def time_limit_for(settings, level):
    """そのレベルの1問の制限時間(秒)。"""
    return int(settings["time_limits"].get(str(level), SKILLTEST_DEFAULTS["time_limits"]["1"]))


def skilltest_plan(settings, levels):
    """出題の計画: [{level, count, limit}] と 合計の問題数・制限時間(秒)。"""
    rows = [{"level": lv, "count": questions_for(settings, lv),
             "limit": time_limit_for(settings, lv)} for lv in levels]
    total = sum(r["count"] for r in rows)
    seconds = sum(r["count"] * r["limit"] for r in rows)
    return rows, total, seconds


# =============================================================================
# 8-2. スキルテスト: AIによる問題の作成
# =============================================================================
# スキルテストの問題(4択)をAIで作成し、検証して問題プールに保存する。
#
# AIの接続はアプリ共通の ai_chat()(4-1)を使う(接続先・キーは instance/config.py)。
# 1回の呼び出しで作る問題は最大 CHUNK_SIZE 問。足りなければ数回に分けて呼び出す。
#
# AIの応答は信用せず、次をすべて満たす問題だけを保存する:
#   ・問題文が空でなく、長すぎない
#   ・選択肢がちょうど4つで、どれも空でなく、長すぎず、互いに異なる
#   ・正解の位置(answer_index)が 0〜3 の整数
#   ・「すべて正しい」「どれでもない」などの選択肢を含まない
#   ・同じスキルの既存の問題(有効・無効とも)や、同じ応答の中の問題と内容が重複しない
#     (全角/半角・大文字/小文字・空白・句読点の違いは同じとみなす)
# 応答の前後にコードブロック(```json … ```)や説明文が付いていても、JSONの配列を取り出して読む。

# 1回のAI呼び出しで作る問題数の上限
CHUNK_SIZE = 10

# 1問あたりの長さの上限(文字数)
QUESTION_MAX = 500
CHOICE_MAX = 200
EXPLANATION_MAX = 1000

# 重複を避けるためにAIへ伝える既存の問題の数と、1問あたりの文字数
AVOID_SAMPLES = 30
AVOID_SAMPLE_CHARS = 60

# レベル(1〜4)ごとの難易度の目安(到達尺度の文言とあわせてAIに伝える)
DIFFICULTY = {
    1: "入門レベル。基本的な用語・概念・操作を正しく理解しているかを問う。",
    2: "初級レベル。基本を組み合わせた簡単な応用や、よくある場面での正しいやり方を問う。",
    3: "中級レベル。設計上の選択、問題の原因の切り分け、注意点など、実践での判断を問う。",
    4: "上級レベル。複数の要素にまたがる深い理解と、状況に応じた最適な判断を問う。",
}

# 使わせない選択肢(「すべて正しい」「どれでもない」の類)
_FORBIDDEN_CHOICE = re.compile(
    r"(すべて|全て|全部|いずれも|どれも)(が)?(正しい|誤り|誤っている|正解|当てはまる|該当する|該当しない)"
    r"|どれでもない|いずれでもない|どれも当てはまらない|上記(の)?(すべて|全て|いずれ|どれ)"
    r"|all of the above|none of the above",
    re.IGNORECASE,
)

# 重複判定で無視する文字(空白・句読点・括弧・引用符など)
_IGNORABLE = re.compile(r"[\s、。，．,.!！?？・:：;；「」『』（）()\[\]【】{}<>＜＞\"'`“”‘’]+")


def normalize_text(text):
    """重複判定用に文章を正規化する(NFKC・小文字化・空白と句読点の除去)。"""
    value = unicodedata.normalize("NFKC", str(text or "")).lower()
    return _IGNORABLE.sub("", value)


def model_label():
    """問題に記録するAIのモデル名(instance/config.py の AI_MODEL。空なら既定のモデル名)。"""
    name = str(current_app.config.get("AI_MODEL") or "").strip() or AI_DEFAULT_MODEL
    return name[:64]


def build_messages(skill, level, count, avoid=()):
    """AIに送るメッセージ(OpenAI形式)を作る。"""
    label = level_label(skill.skill_type or SKILL_TECHNICAL, level)
    lines = [
        "次の条件で、4択の問題を{}問作成してください。".format(count),
        "",
        "■スキル",
        "名称: {}".format(skill.name),
        "カテゴリ: {}".format(skill.category or "（なし）"),
        "説明: {}".format((skill.description or "（なし）").strip()),
        "",
        "■難易度: レベル{}（1〜4の4段階）".format(level),
        "このレベルの目安: 「{}」人なら正解できる水準".format(label),
        "出題の方針: {}".format(DIFFICULTY.get(level, DIFFICULTY[4])),
        "",
        "■守ること",
        "・特定の組織の事情に依存しない、一般に通用する知識・技能を問う",
        "・正解はちょうど1つ。ほかの3つは、もっともらしいが明確に誤りの選択肢にする",
        "・「すべて正しい」「どれでもない」のような選択肢は使わない",
        "・4つの選択肢はすべて異なる内容にする",
        "・問題文は200文字程度まで、選択肢は60文字程度までに簡潔にまとめる",
        "・正解の位置（answer_index）が特定の位置に偏らないようにする",
        "・explanation には、正解の理由を簡潔に書く",
    ]
    samples = [s for s in avoid if s][:AVOID_SAMPLES]
    if samples:
        lines.append("・次の既存の問題と同じ内容の問題は作らない:")
        for text in samples:
            one_line = " ".join(str(text).split())
            lines.append("  - {}".format(one_line[:AVOID_SAMPLE_CHARS]))
    lines += [
        "",
        "■出力形式",
        "JSONの配列だけを出力する（前後に説明文を付けない）。各要素の形は次のとおり。",
        '[{"question": "問題文", "choices": ["選択肢1", "選択肢2", "選択肢3", "選択肢4"], '
        '"answer_index": 0, "explanation": "解説"}]',
        "answer_index は正解の選択肢の位置（0〜3の整数）。",
    ]
    return [
        {"role": "system",
         "content": ("あなたは、技術スキルの理解度を確認するための4択問題を作る出題者です。"
                     "指示された条件を守り、JSONの配列だけを出力してください。")},
        {"role": "user", "content": "\n".join(lines)},
    ]


def _extract_json_array(text):
    """AIの応答からJSONの配列を取り出す(コードブロックや前後の文章があっても読む)。"""
    body = str(text or "").strip()
    fence = re.match(r"^```[A-Za-z0-9_-]*\s*\n?(.*?)\n?```\s*$", body, re.DOTALL)
    if fence:
        body = fence.group(1).strip()
    try:
        data = json.loads(body)
    except ValueError:
        start, end = body.find("["), body.rfind("]")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(body[start:end + 1])
        except ValueError:
            return None
    if isinstance(data, dict):
        # {"questions": [...]} の形で返ってきた場合も受け付ける
        for value in data.values():
            if isinstance(value, list):
                return value
        return None
    return data if isinstance(data, list) else None


# 保存しない制御文字(改行・タブ以外。Excel出力や画面表示で問題になるため除く)
_QUESTION_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean_question_text(value):
    """制御文字と前後の空白を除いた文字列(文字列でなければ None)。"""
    if not isinstance(value, str):
        return None
    return _QUESTION_CONTROL.sub("", value.replace("\r\n", "\n").replace("\r", "\n")).strip()


def validate_item(item):
    """AIが作った1問を検証する。正しければ整えた辞書、不正なら None。"""
    if not isinstance(item, dict):
        return None
    question = _clean_question_text(item.get("question"))
    if not question or len(question) > QUESTION_MAX:
        return None
    choices = item.get("choices")
    if not isinstance(choices, list) or len(choices) != 4:
        return None
    cleaned = []
    for choice in choices:
        text = _clean_question_text(choice)
        if not text or len(text) > CHOICE_MAX or _FORBIDDEN_CHOICE.search(text):
            return None
        cleaned.append(text)
    if len({normalize_text(c) for c in cleaned}) != 4 or any(not normalize_text(c) for c in cleaned):
        return None
    index = item.get("answer_index")
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index <= 3:
        return None
    explanation = item.get("explanation", "")
    if explanation is None:
        explanation = ""
    explanation = _clean_question_text(explanation)
    if explanation is None:
        return None
    if len(explanation) > EXPLANATION_MAX:
        explanation = explanation[:EXPLANATION_MAX]
    return {"question": question, "choices": cleaned, "answer_index": index,
            "explanation": explanation}


def parse_response(text):
    """AIの応答を読み、検証を通った問題の一覧を返す: (問題のリスト, エラー)。"""
    items = _extract_json_array(text)
    if items is None:
        return [], "AIの応答をJSONの配列として読み取れませんでした。"
    valid = [v for v in (validate_item(item) for item in items) if v is not None]
    return valid, None


def existing_keys(skill_id):
    """そのスキルの既存の問題(有効・無効とも)の正規化した問題文の集合。"""
    rows = db.session.query(SkillTestQuestion.question).filter_by(skill_id=skill_id).all()
    return {normalize_text(r[0]) for r in rows}


def _avoid_samples(skill_id, level):
    """重複を避けるためにAIへ伝える既存の問題文(新しい順)。"""
    rows = (
        db.session.query(SkillTestQuestion.question)
        .filter_by(skill_id=skill_id, level=level)
        .order_by(SkillTestQuestion.id.desc())
        .limit(AVOID_SAMPLES)
        .all()
    )
    return [r[0] for r in rows]


def generate_questions(skill, level, count, max_calls=None, stop_at=None):
    """AIで問題を作り、検証を通ったものを問題プールに保存する(呼び出したスレッドで実行)。

    count     : 作りたい問題数(足りなければ CHUNK_SIZE 問ずつ数回に分けて呼び出す)
    max_calls : AIを呼び出す回数の上限(省略時は 必要回数＋1。重複・不正で減った分の補い)
    stop_at   : この時刻(time.monotonic())を過ぎたら次の呼び出しをしない(受験者を待たせすぎない)
    戻り値: (保存した SkillTestQuestion のリスト, エラーメッセージ または None)
    AIに接続できない・応答が無いなどのエラーが起きたら、その時点で止める
    (それまでに保存した問題は残る)。応答の形式が不正なだけなら、回数の上限まで続ける。
    """
    created = []
    if count <= 0:
        return created, None
    if max_calls is None:
        max_calls = int(math.ceil(count / float(CHUNK_SIZE))) + 1
    keys = existing_keys(skill.id)
    model = model_label()
    last_error = None
    calls = 0
    while len(created) < count and calls < max_calls:
        if stop_at is not None and monotonic() >= stop_at:
            return created, "時間内に必要な数の問題を作成できませんでした。"
        calls += 1
        want = min(CHUNK_SIZE, count - len(created))
        text, error = ai_chat(build_messages(skill, level, want, _avoid_samples(skill.id, level)))
        if error:
            return created, error
        items, parse_error = parse_response(text)
        if parse_error:
            last_error = parse_error
            continue
        added = 0
        for item in items:
            if len(created) >= count:
                break
            key = normalize_text(item["question"])
            if not key or key in keys:
                continue
            keys.add(key)
            question = SkillTestQuestion(
                skill_id=skill.id,
                level=level,
                question=item["question"],
                choices=json.dumps(item["choices"], ensure_ascii=False),
                answer_index=item["answer_index"],
                explanation=item["explanation"],
                source=SOURCE_AI,
                model=model,
                is_active=True,
                created_at=_now(),
            )
            db.session.add(question)
            created.append(question)
            added += 1
        # 呼び出しごとに保存する(後で失敗しても、ここまでの問題は残す)
        db.session.commit()
        if added == 0:
            last_error = "AIの応答に使える問題がありませんでした（形式の不備・重複）。"
    if len(created) < count:
        return created, last_error or "必要な数の問題を作成できませんでした。"
    return created, None


# =============================================================================
# 8-3. スキルテスト: 受験の流れ
# =============================================================================
# スキルテストの受験の流れ(開始・出題・回答・離脱の記録・採点・到達度の自動登録)。
#
# ルール(画面・README にも同じことを書いている):
#   ・対象は「有効なテクニカルスキル」だけ。判定するレベルは 1〜min(上限 4, スキルの最大レベル)
#   ・問題はやさしい順(レベル1→上限)に1問ずつ出す(同じレベルの中はランダム)。戻れない
#   ・各問の制限時間はサーバー側で計る(初めて表示した日時 served_at を保存。再読み込みしても
#     残り時間は戻らない)。制限時間＋GRACE_SEC 秒を過ぎた回答は時間切れ(不正解)
#   ・全体の期限(各問の制限時間の合計＋DEADLINE_MARGIN_MIN 分)を過ぎた受験は、次に触れたとき
#     (一覧・出題・回答・管理画面の表示)に自動で終了し、未回答は時間切れとして同じように採点する
#   ・採点: レベルLは「Lの正答率が合格ライン以上」かつ「L未満のレベルがすべて合格」のとき合格。
#     結果のレベル = 合格した最も高いレベル(レベル1が不合格なら0)
#   ・到達度の自動登録: 結果のレベルが現在の到達度より高いときだけ skill_ratings に登録する
#     (マネージャーが付けた到達度を下げることはない)。評価者は本人、メモは
#     「スキルテストで自動登録（YYYY/MM/DD・正答率NN%）」
#   ・受験できるのは有効なメンバー(role=member)だけ。受験中のテストは1人1つ(開くと再開)
#   ・同じスキルの再受験は、前回の受験開始から retake_days 日後から
#
# 時刻はすべてモデルの _now()(3-8)から取る(動作確認で app._now を差し替えられるように)。
# 同じ人の操作(開始・出題・回答・離脱の記録・自動終了)はプロセス内のロックで直列化する。

# 制限時間を過ぎてから回答を受け付ける猶予(秒。通信の遅れの分)
GRACE_SEC = 5
# 全体の期限 = 各問の制限時間の合計 ＋ この分数
DEADLINE_MARGIN_MIN = 10
# 選択せずに送られた回答(時間切れの自動送信)を「時間切れ」とみなす、制限時間の手前の秒数
AUTO_SUBMIT_TOLERANCE_SEC = 3
# 離脱回数の上限(異常な送信で数が膨らみすぎないように)
BLUR_MAX = 9999
# 受験開始時に不足分をAIで作るのに使う時間の上限(秒)。過ぎたら新しい呼び出しはせず再出題に回す
START_AI_BUDGET_SEC = 150

# 受験開始の失敗時のメッセージ
MSG_NOT_READY = "問題が準備できません。マネージャーに連絡してください。"

_rng = random.SystemRandom()

# 同じ人の操作を直列化するロック(開始の準備は時間がかかるので別のロック)
_locks_guard = threading.Lock()
_user_locks = {}
_start_locks = {}


def _lock_for(table, user_id, factory):
    with _locks_guard:
        lock = table.get(user_id)
        if lock is None:
            lock = table[user_id] = factory()
        return lock


def user_lock(user_id):
    """その人の受験の操作(出題・回答・離脱の記録・自動終了)を直列化するロック。"""
    return _lock_for(_user_locks, user_id, threading.RLock)


def _start_lock(user_id):
    return _lock_for(_start_locks, user_id, threading.Lock)


# --------------------------------------------------------------------------- #
# 対象者・対象スキル
# --------------------------------------------------------------------------- #
def is_test_taker(user):
    """スキルテストを受験できる人か(有効なメンバー。マネージャーはスキル管理の対象外)。"""
    return (user is not None and getattr(user, "is_authenticated", True)
            and bool(getattr(user, "is_active", False))
            and getattr(user, "role", None) == ROLE_MEMBER)


def is_testable(skill):
    """テストの対象スキルか(有効なテクニカルスキル)。"""
    return skill is not None and skill.is_active and skill.skill_type == SKILL_TECHNICAL


def testable_skills():
    """テストの対象スキル(有効なテクニカルスキル。スキルマップと同じ並び)。"""
    return (
        Skill.query.filter_by(skill_type=SKILL_TECHNICAL, is_active=True)
        .order_by(Skill.sort_order, Skill.name)
        .all()
    )


def in_progress_attempt(user_id):
    """受験中のテスト(1人1つ。無ければ None)。"""
    return (
        SkillTestAttempt.query.filter_by(user_id=user_id, status=ATTEMPT_IN_PROGRESS)
        .order_by(SkillTestAttempt.started_at.desc(), SkillTestAttempt.id.desc())
        .first()
    )


def last_attempt(user_id, skill_id):
    """そのスキルの直近の受験(無ければ None)。"""
    return (
        SkillTestAttempt.query.filter_by(user_id=user_id, skill_id=skill_id)
        .order_by(SkillTestAttempt.started_at.desc(), SkillTestAttempt.id.desc())
        .first()
    )


def next_available(attempt, settings):
    """次に受験できる日時(前回の受験開始＋再受験までの日数)。制限が無ければ None。"""
    days = int(settings.get("retake_days") or 0)
    if attempt is None or days <= 0:
        return None
    return attempt.started_at + timedelta(days=days)


# --------------------------------------------------------------------------- #
# 採点と到達度の自動登録
# --------------------------------------------------------------------------- #
def _rate_percent(correct, total):
    return round(correct * 100.0 / total, 1) if total else 0.0


def grade_levels(answers, pass_rate):
    """レベルごとの結果と、結果のレベルを返す: (結果のリスト, 結果のレベル)。

    レベルLの合格 = Lの正答率が合格ライン以上 かつ L未満のレベルがすべて合格。
    """
    results = []
    result_level = 0
    lower_passed = True
    for level in sorted({a.level for a in answers}):
        rows = [a for a in answers if a.level == level]
        total = len(rows)
        correct = sum(1 for a in rows if a.is_correct)
        # 浮動小数の誤差を避けるため整数で比べる(correct/total >= pass_rate/100)
        rate_ok = total > 0 and correct * 100 >= pass_rate * total
        passed = lower_passed and rate_ok
        if passed:
            result_level = level
        lower_passed = passed
        results.append({
            "level": level,
            "total": total,
            "correct": correct,
            "rate": _rate_percent(correct, total),
            "rate_ok": rate_ok,
            "passed": passed,
        })
    return results, result_level


def rating_note(finished_at, correct, total):
    """自動登録した到達度のメモ(200文字以内)。"""
    rate = int(round(correct * 100.0 / total)) if total else 0
    return "スキルテストで自動登録（{}・正答率{}%）".format(
        finished_at.strftime("%Y/%m/%d"), rate)[:200]


def _finish(attempt, now, status):
    """受験を終了し、採点して、必要なら到達度を自動登録する(commit は呼び出し側)。"""
    snapshot = attempt.settings_dict
    pass_rate = int(snapshot.get("pass_rate") or SKILLTEST_DEFAULTS["pass_rate"])
    answers = list(attempt.answers)
    results, result_level = grade_levels(answers, pass_rate)

    attempt.status = status
    attempt.finished_at = now
    attempt.total = len(answers)
    attempt.correct = sum(1 for a in answers if a.is_correct)
    attempt.level_results = json.dumps(results, ensure_ascii=False)
    attempt.result_level = result_level

    rating = SkillRating.query.filter_by(
        skill_id=attempt.skill_id, user_id=attempt.user_id).first()
    prev = rating.level if rating else 0
    attempt.prev_level = prev
    # 受験後にマネージャーになった・無効化された人は登録しない(スキル管理の対象外)
    eligible = is_test_taker(attempt.user)
    if eligible and result_level > prev:
        if rating is None:
            rating = SkillRating(skill_id=attempt.skill_id, user_id=attempt.user_id)
            db.session.add(rating)
        rating.level = result_level
        rating.note = rating_note(now, attempt.correct, attempt.total)
        rating.rated_by_id = attempt.user_id
        rating.rated_at = now
        attempt.applied = True
        attempt.new_level = result_level
    else:
        attempt.applied = False
        attempt.new_level = prev


def _expire(attempt, now):
    """全体の期限を過ぎた受験を終了する。未回答はすべて時間切れ(不正解)として採点する。

    終了日時は「全体の期限」とする(最後の回答がそれより後なら、その回答の日時)。
    放置された受験が後日(一覧・管理画面を開いたときなど)に終了しても、終了日時・
    到達度の登録日時・メモの日付が後日にならないようにする。
    表示したまま未回答の問題の所要秒数は「制限時間＋猶予」までとする。
    """
    end = min(now, attempt.deadline_at)
    answered = [a.answered_at for a in attempt.answers if a.answered_at is not None]
    if answered:
        end = max(end, max(answered))
    for answer in attempt.answers:
        if answer.answered_at is None:
            answer.timed_out = True
            answer.is_correct = False
            if answer.served_at is not None:
                elapsed = max(0.0, (end - answer.served_at).total_seconds())
                answer.elapsed_sec = round(min(elapsed, answer.time_limit_sec + GRACE_SEC), 1)
    _finish(attempt, end, ATTEMPT_EXPIRED)


def _is_past_deadline(attempt, now, grace=0):
    return now > attempt.deadline_at + timedelta(seconds=grace)


def expire_due(user_id=None):
    """全体の期限を過ぎた受験中のテストを終了する(user_id を指定するとその人の分だけ)。

    一覧・出題・管理画面などを開いたときに呼ぶ(終了した件数を返す)。
    """
    now = _now()
    query = SkillTestAttempt.query.filter(
        SkillTestAttempt.status == ATTEMPT_IN_PROGRESS,
        SkillTestAttempt.deadline_at < now,
    )
    if user_id is not None:
        query = query.filter(SkillTestAttempt.user_id == user_id)
    targets = [(a.id, a.user_id) for a in query.all()]
    closed = 0
    for attempt_id, owner_id in targets:
        with user_lock(owner_id):
            db.session.expire_all()
            attempt = db.session.get(SkillTestAttempt, attempt_id)
            if attempt is None or attempt.status != ATTEMPT_IN_PROGRESS:
                continue
            now = _now()
            if not _is_past_deadline(attempt, now):
                continue
            _expire(attempt, now)
            db.session.commit()
            closed += 1
    return closed


# --------------------------------------------------------------------------- #
# 受験の開始(問題の選択・不足分のAI作成・受験済みの問題の再出題)
# --------------------------------------------------------------------------- #
StartOutcome = namedtuple("StartOutcome", "attempt resumed error")


def _served_history(user_id, skill_id):
    """その人がそのスキルで表示された問題: {question_id: 最後に表示した日時}。"""
    rows = (
        db.session.query(SkillTestAnswer.question_id, func.max(SkillTestAnswer.served_at))
        .join(SkillTestAttempt, SkillTestAnswer.attempt_id == SkillTestAttempt.id)
        .filter(
            SkillTestAttempt.user_id == user_id,
            SkillTestAttempt.skill_id == skill_id,
            SkillTestAnswer.served_at.isnot(None),
            SkillTestAnswer.question_id.isnot(None),
        )
        .group_by(SkillTestAnswer.question_id)
        .all()
    )
    return {qid: served for qid, served in rows}


def _usable(question):
    """出題に使える問題か(選択肢が4つ・正解の位置が正しい)。"""
    index = question.answer_index
    return (len(question.choice_list) == 4 and isinstance(index, int)
            and not isinstance(index, bool) and 0 <= index <= 3)


def _active_questions(skill_id, level):
    return [
        q for q in SkillTestQuestion.query.filter_by(
            skill_id=skill_id, level=level, is_active=True).all()
        if _usable(q)
    ]


def _pick_for_level(skill, level, count, served, state):
    """1つのレベルの問題を選ぶ: (問題のリスト, 再出題した数)。

    1. その人に表示したことのない有効な問題(ランダム)
    2. 足りなければ不足分をAIで作る(同期。1回で最大10問ずつ)
    3. まだ足りなければ、その人に表示したのが最も古い問題から再出題する
    """
    active = _active_questions(skill.id, level)
    unseen = [q for q in active if q.id not in served]
    _rng.shuffle(unseen)
    picked = unseen[:count]

    if len(picked) < count and state["ai"]:
        created, error = generate_questions(
            skill, level, count - len(picked), stop_at=state["stop_at"])
        picked += created[:count - len(picked)]
        state["generated"] += len(created)
        if error:
            state["errors"].append("Lv{}: {}".format(level, error))
            if not created:
                # 1問も作れなかった(AIに接続できない等)。残りのレベルでは待たずに諦める
                state["ai"] = False

    reused = 0
    if len(picked) < count:
        picked_ids = {q.id for q in picked}
        seen = sorted(
            (q for q in active if q.id in served and q.id not in picked_ids),
            key=lambda q: (served[q.id], q.id),
        )
        extra = seen[:count - len(picked)]
        reused = len(extra)
        picked += extra
    return picked, reused


def _shuffled_choices(question):
    """選択肢を並べ替える: (並べ替えた選択肢, 並べ替えた後の正解の位置)。"""
    choices = question.choice_list
    order = list(range(len(choices)))
    _rng.shuffle(order)
    return [choices[i] for i in order], order.index(question.answer_index)


def start_attempt(user, skill):
    """受験を始める(受験中のテストがあればそれを返す)。戻り値は StartOutcome。

    attempt : 始めた(または再開する)受験。始められなければ None
    resumed : 受験中のテストを再開する場合 True
    error   : 始められない理由(画面に表示する文言)
    """
    if not is_test_taker(user):
        return StartOutcome(None, False, "スキルテストを受験できるのは、有効なメンバーだけです。")
    if not is_testable(skill):
        return StartOutcome(None, False, "このスキルはスキルテストの対象外です（有効なテクニカルスキルだけが対象）。")

    start_lock = _start_lock(user.id)
    if not start_lock.acquire(blocking=False):
        return StartOutcome(None, False, "問題を準備中です。しばらく待ってから、もう一度開いてください。")
    try:
        expire_due(user.id)
        existing = in_progress_attempt(user.id)
        if existing is not None:
            return StartOutcome(existing, True, None)

        settings = load_skilltest_settings()
        now = _now()
        available = next_available(last_attempt(user.id, skill.id), settings)
        if available is not None and now < available:
            return StartOutcome(None, False, "このスキルは {} から再受験できます。".format(
                available.strftime("%Y/%m/%d %H:%M")))

        levels = tested_levels(settings, skill.max_level)
        if not levels:
            return StartOutcome(None, False, "このスキルはテストで判定できるレベルがありません。")
        rows, _total, seconds = skilltest_plan(settings, levels)

        served = _served_history(user.id, skill.id)
        state = {"ai": ai_is_configured(), "generated": 0, "errors": [],
                 "stop_at": monotonic() + START_AI_BUDGET_SEC}
        picked_by_level = []
        reused_total = 0
        short = []
        for row in rows:
            picked, reused = _pick_for_level(skill, row["level"], row["count"], served, state)
            reused_total += reused
            if len(picked) < row["count"]:
                short.append("Lv{} {}/{}問".format(row["level"], len(picked), row["count"]))
            picked_by_level.append((row, picked))
        if short:
            current_app.logger.warning(
                "スキルテストの問題が不足しています（スキルID %s: %s）%s", skill.id,
                "、".join(short), " ／ ".join(state["errors"]))
            return StartOutcome(None, False, MSG_NOT_READY)

        with user_lock(user.id):
            db.session.expire_all()
            existing = in_progress_attempt(user.id)
            if existing is not None:
                return StartOutcome(existing, True, None)
            now = _now()
            snapshot = {
                "levels": levels,
                "questions_per_level": {str(r["level"]): r["count"] for r in rows},
                "time_limits": {str(r["level"]): r["limit"] for r in rows},
                "pass_rate": settings["pass_rate"],
                "retake_days": settings["retake_days"],
                "max_auto_level": settings["max_auto_level"],
                "grace_sec": GRACE_SEC,
                "deadline_margin_min": DEADLINE_MARGIN_MIN,
            }
            attempt = SkillTestAttempt(
                user_id=user.id,
                skill_id=skill.id,
                status=ATTEMPT_IN_PROGRESS,
                started_at=now,
                deadline_at=now + timedelta(seconds=seconds, minutes=DEADLINE_MARGIN_MIN),
                total=sum(r["count"] for r in rows),
                correct=0,
                applied=False,
                blur_count=0,
                reused_count=reused_total,
                settings_snapshot=json.dumps(snapshot, ensure_ascii=False),
            )
            db.session.add(attempt)
            seq = 0
            for row, picked in picked_by_level:
                _rng.shuffle(picked)  # 同じレベルの中はランダムな順
                for question in picked:
                    seq += 1
                    choices, correct_index = _shuffled_choices(question)
                    attempt.answers.append(SkillTestAnswer(
                        seq=seq,
                        level=row["level"],
                        question_id=question.id,
                        question=question.question,
                        choices=json.dumps(choices, ensure_ascii=False),
                        correct_index=correct_index,
                        is_correct=False,
                        timed_out=False,
                        time_limit_sec=row["limit"],
                        blur_count=0,
                    ))
            db.session.commit()
            return StartOutcome(attempt, False, None)
    finally:
        start_lock.release()


# --------------------------------------------------------------------------- #
# 出題・回答・離脱の記録
# --------------------------------------------------------------------------- #
def _current(attempt):
    """次に答える問題(未確定のうち最初のもの)。全問確定済みなら None。"""
    return next((a for a in attempt.answers if a.answered_at is None), None)


def _elapsed(answer, now):
    return (now - answer.served_at).total_seconds() if answer.served_at else 0.0


def _close_timeout(answer, now, selected=None):
    """時間切れとして確定する(不正解)。"""
    answer.timed_out = True
    answer.is_correct = False
    answer.selected_index = selected
    answer.answered_at = now
    answer.elapsed_sec = round(_elapsed(answer, now), 1)


def _finish_if_done(attempt, now):
    if _current(attempt) is None and attempt.status == ATTEMPT_IN_PROGRESS:
        _finish(attempt, now, ATTEMPT_FINISHED)


def prepare_question(attempt_id, user_id):
    """今の問題を表示できる状態にして返す(初めて表示する問題は served_at を記録する)。

    制限時間＋猶予を過ぎた問題は時間切れとして次へ進む。全体の期限を過ぎていれば終了する。
    戻り値: (受験, 表示する問題 または None〔終了済み〕)
    """
    with user_lock(user_id):
        db.session.expire_all()
        attempt = db.session.get(SkillTestAttempt, attempt_id)
        if attempt is None or attempt.user_id != user_id:
            return None, None
        if attempt.status != ATTEMPT_IN_PROGRESS:
            return attempt, None
        now = _now()
        if _is_past_deadline(attempt, now):
            _expire(attempt, now)
            db.session.commit()
            return attempt, None
        changed = False
        while True:
            answer = _current(attempt)
            if answer is None:
                _finish(attempt, now, ATTEMPT_FINISHED)
                changed = True
                break
            if answer.served_at is None:
                answer.served_at = now
                changed = True
                break
            if _elapsed(answer, now) > answer.time_limit_sec + GRACE_SEC:
                _close_timeout(answer, now)
                changed = True
                continue
            break
        if changed:
            db.session.commit()
        return attempt, answer


def remaining_seconds(attempt, answer, now=None):
    """その問題の残り時間(秒。全体の期限も考慮。0未満は0)。

    秒未満は切り上げる(画面の自動送信が制限時間より早くならないように。遅れた分は猶予の範囲)。
    """
    now = now or _now()
    left = answer.time_limit_sec - _elapsed(answer, now)
    left = min(left, (attempt.deadline_at - now).total_seconds())
    return max(0, int(math.ceil(left)))


# submit_answer の結果
ANSWER_RECORDED = "recorded"    # 回答を記録した
ANSWER_TIMEOUT = "timeout"      # 時間切れとして記録した
ANSWER_NO_CHOICE = "no_choice"  # 選択肢が選ばれていない(時間内。記録しない)
ANSWER_STALE = "stale"          # 今の問題ではない(二重送信・戻るボタンなど。無視)
ANSWER_CLOSED = "closed"        # 受験は終了している(期限切れで今終了した場合も含む)


def submit_answer(attempt_id, user_id, seq, choice):
    """回答を記録する。戻り値: (受験, 結果 ANSWER_〜)。

    seq    : 回答した問題の出題順(画面に出した今の問題と一致しなければ無視)
    choice : 選んだ選択肢の位置(画面に出した順の 0〜3)。未選択は None
    """
    with user_lock(user_id):
        db.session.expire_all()
        attempt = db.session.get(SkillTestAttempt, attempt_id)
        if attempt is None or attempt.user_id != user_id:
            return None, ANSWER_STALE
        if attempt.status != ATTEMPT_IN_PROGRESS:
            return attempt, ANSWER_CLOSED
        now = _now()
        if _is_past_deadline(attempt, now, grace=GRACE_SEC):
            _expire(attempt, now)
            db.session.commit()
            return attempt, ANSWER_CLOSED

        answer = _current(attempt)
        if answer is None:
            _finish(attempt, now, ATTEMPT_FINISHED)
            db.session.commit()
            return attempt, ANSWER_CLOSED
        if answer.seq != seq or answer.served_at is None:
            return attempt, ANSWER_STALE
        if choice is not None and not 0 <= choice < len(answer.choice_list):
            choice = None

        elapsed = _elapsed(answer, now)
        if elapsed > answer.time_limit_sec + GRACE_SEC:
            _close_timeout(answer, now, selected=choice)
            outcome = ANSWER_TIMEOUT
        elif choice is None:
            # 画面の残り時間は「問題の制限時間」と「全体の期限」の短い方。全体の期限で0になった
            # 自動送信なら、受験を終了する(未回答は時間切れ)
            if (attempt.deadline_at - now).total_seconds() <= AUTO_SUBMIT_TOLERANCE_SEC:
                _expire(attempt, now)
                db.session.commit()
                return attempt, ANSWER_CLOSED
            if elapsed < answer.time_limit_sec - AUTO_SUBMIT_TOLERANCE_SEC:
                return attempt, ANSWER_NO_CHOICE
            _close_timeout(answer, now)
            outcome = ANSWER_TIMEOUT
        else:
            answer.selected_index = choice
            answer.is_correct = choice == answer.correct_index
            answer.timed_out = False
            answer.answered_at = now
            answer.elapsed_sec = round(elapsed, 1)
            outcome = ANSWER_RECORDED

        if _current(attempt) is not None and _is_past_deadline(attempt, now):
            # 全体の期限を過ぎてから(猶予の間に)回答した。残りは時間切れとして終了する
            _expire(attempt, now)
        else:
            _finish_if_done(attempt, now)
        db.session.commit()
        return attempt, outcome


def record_blur(attempt_id, user_id, seq):
    """画面から離れた(タブの切り替え・ウィンドウの切り替えなど)ことを記録する。

    受験中だけ数える。表示済みの問題の出題順 seq が送られれば、その問題の回数にも数える。
    """
    with user_lock(user_id):
        db.session.expire_all()
        attempt = db.session.get(SkillTestAttempt, attempt_id)
        if attempt is None or attempt.user_id != user_id:
            return False
        if attempt.status != ATTEMPT_IN_PROGRESS:
            return False
        attempt.blur_count = min((attempt.blur_count or 0) + 1, BLUR_MAX)
        answer = next((a for a in attempt.answers if a.seq == seq), None)
        if answer is not None and answer.served_at is not None:
            answer.blur_count = min((answer.blur_count or 0) + 1, BLUR_MAX)
        db.session.commit()
        return True


# --------------------------------------------------------------------------- #
# 画面用のまとめ
# --------------------------------------------------------------------------- #
def member_overview(user):
    """メンバーのテスト一覧の行(スキルごとの現在の到達度・前回の受験・次に受験できる日時)。"""
    settings = load_skilltest_settings()
    now = _now()
    running = in_progress_attempt(user.id)
    ratings = {r.skill_id: r for r in SkillRating.query.filter_by(user_id=user.id).all()}
    rows = []
    for skill in testable_skills():
        last = last_attempt(user.id, skill.id)
        available = next_available(last, settings)
        levels = tested_levels(settings, skill.max_level)
        rating = ratings.get(skill.id)
        level = rating.level if rating else 0
        if running is not None and running.skill_id == skill.id:
            state = "resume"
        elif running is not None:
            state = "busy"          # 別のスキルを受験中
        elif available is not None and now < available:
            state = "wait"          # 再受験の間隔をあけている
        else:
            state = "ready"
        rows.append({
            "skill": skill,
            "level": level,
            "rating": rating,
            "last": last,
            "available": available,
            "state": state,
            "top_level": levels[-1] if levels else 0,
            "capped": bool(levels) and level >= levels[-1],
        })
    return rows, running


# =============================================================================
# 8-4. スキルテスト: 問題プールの集計と補充
# =============================================================================
# スキルテストの問題プールの集計と補充(マネージャー向け)。
#
# 補充(start_topup)は、指定したスキルの各レベルの「有効な問題」が目標数
# (設定 pool_target_per_level)に届くまで、AIで問題を作ってプールに保存する。
# AIの呼び出しには時間がかかるため、別スレッドで実行する(画面はすぐに戻る)。
# 補充は同時に1つだけ。結果は「前回の補充の結果」(instance/skilltest_settings.json)に残す。

# 補充は同時に1つだけ(AIの呼び出しが重ならないように)
_topup_lock = threading.Lock()
_running = {"skill_name": ""}


def is_topup_running():
    """問題の補充を実行中か。"""
    return _topup_lock.locked()


def running_skill_name():
    """補充を実行中のスキル名(実行中でなければ空)。"""
    return _running["skill_name"] if is_topup_running() else ""


def counts_by_skill():
    """スキル・レベルごとの問題数: {skill_id: {level: {"active": n, "inactive": m}}}。"""
    rows = (
        db.session.query(
            SkillTestQuestion.skill_id, SkillTestQuestion.level,
            SkillTestQuestion.is_active, func.count(SkillTestQuestion.id))
        .group_by(SkillTestQuestion.skill_id, SkillTestQuestion.level,
                  SkillTestQuestion.is_active)
        .all()
    )
    result = {}
    for skill_id, level, active, count in rows:
        per_level = result.setdefault(skill_id, {})
        cell = per_level.setdefault(level, {"active": 0, "inactive": 0})
        cell["active" if active else "inactive"] += count
    return result


def usage_by_question(skill_id):
    """問題ごとの出題数と正解数: {question_id: {"served": n, "correct": m}}。"""
    rows = (
        db.session.query(
            SkillTestAnswer.question_id,
            func.count(SkillTestAnswer.id),
            func.sum(case((SkillTestAnswer.is_correct.is_(True), 1), else_=0)))
        .join(SkillTestQuestion, SkillTestAnswer.question_id == SkillTestQuestion.id)
        .filter(SkillTestQuestion.skill_id == skill_id,
                SkillTestAnswer.served_at.isnot(None))
        .group_by(SkillTestAnswer.question_id)
        .all()
    )
    return {qid: {"served": served or 0, "correct": int(correct or 0)}
            for qid, served, correct in rows}


def _topup(app, skill_id):
    """補充の本体(_topup_lock を持った状態で呼ぶ)。結果を「前回の補充の結果」に残す。"""
    with app.app_context():
        name = "ID {}".format(skill_id)
        try:
            skill = db.session.get(Skill, skill_id)
            if skill is None or not is_testable(skill):
                ok, message = False, "対象外のスキルです（有効なテクニカルスキルだけ補充できます）。"
            elif not ai_is_configured():
                name = skill.name
                ok, message = False, ("AI（ChatGPT互換API）が未設定のため問題を作成できません。"
                                      "システム設定の「基本設定」タブで AI_API_KEY または AI_API_URL を設定してください。")
            else:
                name = skill.name
                settings = load_skilltest_settings()
                target = settings["pool_target_per_level"]
                parts, added_total, error = [], 0, None
                for level in tested_levels(settings, skill.max_level):
                    active = SkillTestQuestion.query.filter_by(
                        skill_id=skill.id, level=level, is_active=True).count()
                    need = target - active
                    if need <= 0:
                        parts.append("Lv{} 追加なし（{}問）".format(level, active))
                        continue
                    created, error = generate_questions(
                        skill, level, need,
                        max_calls=int(math.ceil(need / float(CHUNK_SIZE))) + 2)
                    added_total += len(created)
                    parts.append("Lv{} +{}（{}問）".format(level, len(created), active + len(created)))
                    if error:
                        break
                summary = "「{}」: {} ／ 計{}問を追加".format(name, "、".join(parts), added_total)
                if error:
                    ok, message = False, "{} ／ 途中で止まりました: {}".format(summary, error)
                else:
                    ok, message = True, summary
        except Exception as exc:
            app.logger.exception("スキルテストの問題の補充に失敗しました")
            db.session.rollback()
            ok, message = False, "「{}」の問題の補充中にエラーが発生しました: {}".format(name, exc)

        try:
            set_skilltest_last_result(TRIGGER_MANUAL, ok, message)
        except Exception:
            app.logger.exception("スキルテストの補充の結果を保存できませんでした")
        return {"ok": ok, "message": message}


def start_topup(app, skill):
    """補充を別スレッドで始める。既に補充中なら何もせず False を返す。"""
    if not _topup_lock.acquire(blocking=False):
        return False
    _running["skill_name"] = skill.name
    skill_id = skill.id

    def worker():
        try:
            _topup(app, skill_id)
        except Exception:
            app.logger.exception("スキルテストの問題の補充でエラーが発生しました")
        finally:
            _running["skill_name"] = ""
            _topup_lock.release()

    try:
        threading.Thread(target=worker, name="skilltest-topup", daemon=True).start()
    except Exception:
        _running["skill_name"] = ""
        _topup_lock.release()
        raise
    return True


def run_topup(app, skill_id):
    """補充を呼び出したスレッドで最後まで実行する(動作確認用。補充中なら終わるまで待つ)。"""
    with _topup_lock:
        return _topup(app, skill_id)


# =============================================================================
# 8-5. スキルテスト: 設定フォーム
# =============================================================================
# スキルテストの設定フォームの入力チェックと表示用の値(システム設定の「スキルテスト」タブで使う)。
#
# 設定の画面はシステム設定(/system/settings?tab=skilltest)にまとめてあり、
# スキルテスト管理(/skilltest/admin)には受験履歴と問題プールだけが残る。
# 保存先は設定の保存(8-1)のまま(instance/skilltest_settings.json)。
#
#   parse_skilltest_form(form)       フォームの入力を検証する → (保存する値, エラーメッセージの一覧)
#   skilltest_with_input(cur, v)     入力エラーで再表示するとき、保存済みの設定に入力中の値を重ねる
#   skilltest_form_context(settings) フォームの表示に使う値

SKILLTEST_LABEL = "スキルテスト"
SKILLTEST_SAVED_MESSAGE = "スキルテストの設定を保存しました（受験中・受験済みのテストには影響しません）。"

# レベルごと以外の数値の項目: (キー, 表示名, 下限, 上限, 単位)
_SCALAR_FIELDS = (
    ("pass_rate", "合格ライン", PASS_RATE_MIN, PASS_RATE_MAX, "%"),
    ("retake_days", "再受験までの日数", RETAKE_DAYS_MIN, RETAKE_DAYS_MAX, "日"),
    ("max_auto_level", "判定・自動登録するレベルの上限", AUTO_LEVEL_MIN, AUTO_LEVEL_MAX, ""),
    ("pool_target_per_level", "問題プールの目標数", POOL_TARGET_MIN, POOL_TARGET_MAX, "問"),
)


def _number(form, name):
    raw = (form.get(name) or "").strip()
    return int(raw) if raw.isdecimal() else None


def parse_skilltest_form(form):
    """フォームの入力を検証する。戻り値: (values, errors)。errors が空なら保存してよい。"""
    errors = []
    values = {"questions_per_level": {}, "time_limits": {}}

    for level in SKILLTEST_LEVELS:
        count = _number(form, "questions_{}".format(level))
        if valid_int(count, QUESTIONS_MIN, QUESTIONS_MAX):
            values["questions_per_level"][str(level)] = count
        else:
            errors.append("Lv{}の問題数は{}〜{}の数字で入力してください。".format(
                level, QUESTIONS_MIN, QUESTIONS_MAX))
        limit = _number(form, "limit_{}".format(level))
        if valid_int(limit, TIME_LIMIT_MIN, TIME_LIMIT_MAX):
            values["time_limits"][str(level)] = limit
        else:
            errors.append("Lv{}の制限時間は{}〜{}秒の数字で入力してください。".format(
                level, TIME_LIMIT_MIN, TIME_LIMIT_MAX))

    for key, label, low, high, unit in _SCALAR_FIELDS:
        value = _number(form, key)
        if valid_int(value, low, high):
            values[key] = value
        else:
            errors.append("{}は{}〜{}{}の数字で入力してください。".format(label, low, high, unit))
    return values, errors


def skilltest_with_input(current, values):
    """保存済みの設定に入力中の値を重ねる(入力エラー時の再表示用。保存はしない)。

    レベルごとの値は、正しく入力されたレベルだけを重ねる。
    """
    current["questions_per_level"].update(values.get("questions_per_level", {}))
    current["time_limits"].update(values.get("time_limits", {}))
    for key, _label, _low, _high, _unit in _SCALAR_FIELDS:
        if key in values:
            current[key] = values[key]
    return current


def skilltest_form_context(settings):
    """スキルテストの設定フォームの表示に使う値。"""
    scale = scale_for(SKILL_TECHNICAL)
    _rows, total, seconds = skilltest_plan(
        settings, tested_levels(settings, len(scale) - 1))
    return {
        "settings": settings,
        "levels": SKILLTEST_LEVELS,
        "plan_total": total,
        "plan_minutes": int(round(seconds / 60.0)),
        "scale": scale,
        "limits": SKILLTEST_LIMITS,
        "grace_sec": GRACE_SEC,
        "margin_min": DEADLINE_MARGIN_MIN,
    }


# =============================================================================
# 8-6. スキルテスト: 画面
# =============================================================================
# スキルテストの画面。
#
# メンバー(有効な role=member のみ。マネージャーは受験できない):
#   GET  /skilltest/                         テストの一覧(現在の到達度・前回の受験・次に受験できる日時・ルール)
#   POST /skilltest/start/<skill_id>         受験を始める(受験中のテストがあれば再開)
#   GET  /skilltest/attempt/<id>             出題(1問ずつ。戻れない)
#   POST /skilltest/attempt/<id>/answer      回答
#   POST /skilltest/attempt/<id>/blur        画面から離れたことの記録(JavaScript から送る)
#   GET  /skilltest/attempt/<id>/result      結果(レベルごとの正解数と結果のレベルだけ。正解は見せない)
#
# マネージャーのみ(メンバーは403):
#   GET  /skilltest/admin                    受験履歴(全員。メンバー・スキル・状態で絞り込み)
#   GET  /skilltest/admin/attempt/<id>       受験の詳細(全問の問題・選択肢・正解・回答・所要時間・離脱回数)
#   GET  /skilltest/admin/pool               問題プール(スキル・レベルごとの問題数、補充)
#   GET  /skilltest/admin/pool/<skill_id>    スキルごとの問題の一覧(有効/無効の切り替え)
#   POST /skilltest/admin/pool/<skill_id>/topup        問題の補充(バックグラウンド)
#   POST /skilltest/admin/questions/<id>/toggle        問題の有効/無効の切り替え
#   GET  /skilltest/admin/settings, POST 同じURL       旧URL。設定はシステム設定の「スキルテスト」タブへ移した
#                                                      (GET はそのタブへ、POST はその保存へ転送する)
#
# 受験の操作はすべて本人の受験だけが対象(他人の受験は404)。

skilltest_bp = Blueprint("skilltest", __name__, url_prefix="/skilltest")

# 問題一覧の絞り込み(有効/無効)
STATE_ACTIVE = "active"
STATE_INACTIVE = "inactive"


@skilltest_bp.before_request
def _guard():
    """ログイン必須。管理画面(admin_〜)はマネージャー、それ以外は受験できるメンバーだけ。

    login_required は OPTIONS を素通しするため使わず、ここで直接確認する。
    """
    if not current_user.is_authenticated:
        return current_app.login_manager.unauthorized()
    endpoint = request.endpoint or ""
    if not endpoint:
        return None  # 存在しないURL(404)
    if endpoint.startswith("skilltest.admin"):
        if not getattr(current_user, "is_manager", False):
            abort(403)
        return None
    if is_test_taker(current_user):
        return None
    if getattr(current_user, "is_manager", False) and endpoint == "skilltest.index" \
            and request.method == "GET":
        flash("マネージャーはスキル管理の対象外のため、スキルテストは受験できません。"
              "スキルテスト管理を表示します。", "info")
        return redirect(url_for("skilltest.admin_attempts"))
    abort(403)


def _tech_scale():
    return scale_for(SKILL_TECHNICAL)


def _rules(settings):
    """ルール説明用の値(テクニカルスキルの判定レベル・問題数・制限時間・期限)。"""
    levels = tested_levels(settings, len(_tech_scale()) - 1)
    rows, total, seconds = skilltest_plan(settings, levels)
    return {
        "levels": levels,
        "rows": rows,
        "total": total,
        "minutes": int(round(seconds / 60.0)),
        "deadline_minutes": int(round(seconds / 60.0)) + DEADLINE_MARGIN_MIN,
        "pass_rate": settings["pass_rate"],
        "retake_days": settings["retake_days"],
        "top_level": levels[-1] if levels else 0,
        "grace_sec": GRACE_SEC,
    }


def _no_store(response):
    """出題画面などをブラウザにキャッシュさせない(戻るボタンで前の問題を出さない)。"""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


# --------------------------------------------------------------------------- #
# メンバー
# --------------------------------------------------------------------------- #
@skilltest_bp.route("/", endpoint="index")
def skilltest_index():
    me = current_user._get_current_object()
    expire_due(me.id)
    rows, running = member_overview(me)
    settings = load_skilltest_settings()
    history = (
        SkillTestAttempt.query.filter_by(user_id=me.id)
        .order_by(SkillTestAttempt.started_at.desc(), SkillTestAttempt.id.desc())
        .limit(100)
        .all()
    )
    return render_template(
        "skilltest/index.html",
        rows=rows,
        running=running,
        history=history,
        rules=_rules(settings),
        scale=_tech_scale(),
        level_colors=SKILL_LEVEL_COLORS,
    )


@skilltest_bp.route("/start/<int:skill_id>", methods=["POST"])
def start(skill_id):
    skill = db.session.get(Skill, skill_id)
    if skill is None:
        abort(404)
    outcome = start_attempt(current_user._get_current_object(), skill)
    if outcome.error:
        flash(outcome.error, "danger" if outcome.error == MSG_NOT_READY else "warning")
        return redirect(url_for("skilltest.index"))
    if outcome.resumed:
        flash("受験中のテスト（{}）を再開します。".format(outcome.attempt.skill.name), "info")
    return redirect(url_for("skilltest.question", attempt_id=outcome.attempt.id))


@skilltest_bp.route("/attempt/<int:attempt_id>")
def question(attempt_id):
    attempt, item = prepare_question(attempt_id, current_user.id)
    if attempt is None:
        abort(404)
    if item is None:
        return redirect(url_for("skilltest.result", attempt_id=attempt.id))
    remaining = remaining_seconds(attempt, item)
    response = make_response(render_template(
        "skilltest/question.html",
        attempt=attempt,
        item=item,
        choices=item.choice_list,
        letters=CHOICE_LETTERS,
        remaining=remaining,
        answered=sum(1 for a in attempt.answers if a.answered_at is not None),
        scale=_tech_scale(),
    ))
    return _no_store(response)


@skilltest_bp.route("/attempt/<int:attempt_id>/answer", methods=["POST"])
def answer(attempt_id):
    seq = request.form.get("seq", type=int)
    raw = (request.form.get("choice") or "").strip()
    choice = int(raw) if raw.isdecimal() else None
    attempt, outcome = submit_answer(attempt_id, current_user.id, seq, choice)
    if attempt is None:
        abort(404)
    if outcome == ANSWER_NO_CHOICE:
        flash("選択肢を選んでから「回答する」を押してください（残り時間は進んでいます）。", "warning")
    elif outcome == ANSWER_TIMEOUT:
        flash("制限時間を過ぎたため、時間切れとして記録しました。", "warning")
    elif outcome == ANSWER_STALE:
        flash("この問題には回答済みです（前の問題には戻れません）。今の問題を表示します。", "info")
    if attempt.status != ATTEMPT_IN_PROGRESS:
        if attempt.status == ATTEMPT_EXPIRED:
            flash("全体の制限時間を過ぎたため、テストを終了しました（未回答は時間切れ）。", "warning")
        return redirect(url_for("skilltest.result", attempt_id=attempt.id))
    return redirect(url_for("skilltest.question", attempt_id=attempt.id))


@skilltest_bp.route("/attempt/<int:attempt_id>/blur", methods=["POST"])
def blur(attempt_id):
    attempt = db.session.get(SkillTestAttempt, attempt_id)
    if attempt is None or attempt.user_id != current_user.id:
        abort(404)
    record_blur(attempt_id, current_user.id, request.form.get("seq", type=int))
    return ("", 204)


@skilltest_bp.route("/attempt/<int:attempt_id>/result")
def result(attempt_id):
    me = current_user._get_current_object()
    attempt = db.session.get(SkillTestAttempt, attempt_id)
    if attempt is None or attempt.user_id != me.id:
        abort(404)
    if attempt.status == ATTEMPT_IN_PROGRESS:
        expire_due(me.id)
        db.session.expire_all()
        attempt = db.session.get(SkillTestAttempt, attempt_id)
        if attempt.status == ATTEMPT_IN_PROGRESS:
            return redirect(url_for("skilltest.question", attempt_id=attempt.id))
    settings = load_skilltest_settings()
    available = None
    latest = last_attempt(me.id, attempt.skill_id)
    if latest is not None and latest.id == attempt.id:
        available = next_available(attempt, settings)
    return _no_store(make_response(render_template(
        "skilltest/result.html",
        attempt=attempt,
        level_results=attempt.level_result_list,
        scale=_tech_scale(),
        level_colors=SKILL_LEVEL_COLORS,
        available=available,
        now=_now(),
    )))


# --------------------------------------------------------------------------- #
# マネージャー: 受験履歴
# --------------------------------------------------------------------------- #
def _int_arg(name):
    value = request.args.get(name, "").strip()
    return int(value) if value.isdecimal() else None


@skilltest_bp.route("/admin")
def admin_attempts():
    expire_due()
    filters = {
        "user_id": _int_arg("user_id"),
        "skill_id": _int_arg("skill_id"),
        "status": request.args.get("status", ""),
    }
    if filters["status"] not in ATTEMPT_STATUS_LABELS:
        filters["status"] = ""

    query = SkillTestAttempt.query
    if filters["user_id"]:
        query = query.filter(SkillTestAttempt.user_id == filters["user_id"])
    if filters["skill_id"]:
        query = query.filter(SkillTestAttempt.skill_id == filters["skill_id"])
    if filters["status"]:
        query = query.filter(SkillTestAttempt.status == filters["status"])
    attempts = query.order_by(
        SkillTestAttempt.started_at.desc(), SkillTestAttempt.id.desc()).all()

    # 絞り込みの選択肢: 受験したことのある人＋今のメンバー / テクニカルスキル
    taker_ids = {row[0] for row in db.session.query(SkillTestAttempt.user_id).distinct()}
    users = [
        u for u in User.query.order_by(User.display_name).all()
        if u.id in taker_ids or (u.is_active and u.role == ROLE_MEMBER)
    ]
    skills = (
        Skill.query.filter_by(skill_type=SKILL_TECHNICAL)
        .order_by(Skill.is_active.desc(), Skill.sort_order, Skill.name)
        .all()
    )
    return render_template(
        "skilltest/admin_attempts.html",
        attempts=attempts,
        filters=filters,
        users=users,
        skills=skills,
        status_labels=ATTEMPT_STATUS_LABELS,
        scale=_tech_scale(),
        level_colors=SKILL_LEVEL_COLORS,
    )


@skilltest_bp.route("/admin/attempt/<int:attempt_id>")
def admin_attempt(attempt_id):
    attempt = db.session.get(SkillTestAttempt, attempt_id)
    if attempt is None:
        abort(404)
    if attempt.status == ATTEMPT_IN_PROGRESS:
        expire_due(attempt.user_id)
        db.session.expire_all()
        attempt = db.session.get(SkillTestAttempt, attempt_id)
    return render_template(
        "skilltest/admin_attempt.html",
        attempt=attempt,
        level_results=attempt.level_result_list,
        snapshot=attempt.settings_dict,
        letters=CHOICE_LETTERS,
        scale=_tech_scale(),
        level_colors=SKILL_LEVEL_COLORS,
        status_finished=ATTEMPT_FINISHED,
    )


# --------------------------------------------------------------------------- #
# マネージャー: 問題プール
# --------------------------------------------------------------------------- #
@skilltest_bp.route("/admin/pool")
def admin_pool():
    settings = load_skilltest_settings()
    counts = counts_by_skill()
    skills = (
        Skill.query.filter_by(skill_type=SKILL_TECHNICAL)
        .order_by(Skill.is_active.desc(), Skill.sort_order, Skill.name)
        .all()
    )
    levels = tested_levels(settings, len(_tech_scale()) - 1)
    rows = []
    for skill in skills:
        per_level = counts.get(skill.id, {})
        rows.append({
            "skill": skill,
            "testable": is_testable(skill),
            "cells": [
                {
                    "level": lv,
                    "active": per_level.get(lv, {}).get("active", 0),
                    "inactive": per_level.get(lv, {}).get("inactive", 0),
                    "need": questions_for(settings, lv),
                }
                for lv in levels
            ],
            "total": sum(c["active"] + c["inactive"] for c in per_level.values()),
        })
    return render_template(
        "skilltest/admin_pool.html",
        rows=rows,
        levels=levels,
        settings=settings,
        target=settings["pool_target_per_level"],
        last=settings["last_result"],
        running=is_topup_running(),
        running_name=running_skill_name(),
        ai_enabled=ai_is_configured(),
        ai_status=ai_status_label(),
        scale=_tech_scale(),
    )


@skilltest_bp.route("/admin/pool/<int:skill_id>")
def admin_pool_skill(skill_id):
    skill = db.session.get(Skill, skill_id)
    if skill is None:
        abort(404)
    level = _int_arg("level")
    state = request.args.get("state", "")
    if state not in (STATE_ACTIVE, STATE_INACTIVE):
        state = ""
    query = SkillTestQuestion.query.filter_by(skill_id=skill.id)
    if level:
        query = query.filter(SkillTestQuestion.level == level)
    if state:
        query = query.filter(SkillTestQuestion.is_active.is_(state == STATE_ACTIVE))
    questions = query.order_by(SkillTestQuestion.level, SkillTestQuestion.id).all()
    settings = load_skilltest_settings()
    return render_template(
        "skilltest/admin_pool_skill.html",
        skill=skill,
        questions=questions,
        usage=usage_by_question(skill.id),
        counts=counts_by_skill().get(skill.id, {}),
        levels=tested_levels(settings, skill.max_level) or [1, 2, 3, 4],
        filters={"level": level, "state": state},
        testable=is_testable(skill),
        letters=CHOICE_LETTERS,
        scale=scale_for(skill.skill_type),
        running=is_topup_running(),
        ai_enabled=ai_is_configured(),
        target=settings["pool_target_per_level"],
    )


@skilltest_bp.route("/admin/pool/<int:skill_id>/topup", methods=["POST"])
def admin_topup(skill_id):
    skill = db.session.get(Skill, skill_id)
    if skill is None:
        abort(404)
    back = url_for("skilltest.admin_pool_skill", skill_id=skill.id) \
        if request.form.get("back") == "skill" else url_for("skilltest.admin_pool")
    if not is_testable(skill):
        flash("有効なテクニカルスキルだけ補充できます。", "warning")
        return redirect(back)
    if not ai_is_configured():
        flash("AI（ChatGPT互換API）が未設定のため、問題を作成できません。", "danger")
        return redirect(back)
    app = current_app._get_current_object()
    if not start_topup(app, skill):
        flash("別の補充を処理中です。完了してから、もう一度実行してください。", "warning")
        return redirect(back)
    flash("「{}」の問題の補充を開始しました。数分かかることがあります。結果は問題プールの"
          "「前回の補充の結果」に表示されます（画面を再読み込みして確認してください）。".format(skill.name),
          "info")
    return redirect(back)


@skilltest_bp.route("/admin/questions/<int:question_id>/toggle", methods=["POST"])
def admin_toggle_question(question_id):
    question = db.session.get(SkillTestQuestion, question_id)
    if question is None:
        abort(404)
    question.is_active = not question.is_active
    db.session.commit()
    flash("問題 #{} を{}にしました。".format(
        question.id, "有効" if question.is_active else "無効（今後は出題しない）"), "info")
    params = {"skill_id": question.skill_id}
    level = request.form.get("level", "")
    state = request.form.get("state", "")
    if level.isdecimal():
        params["level"] = int(level)
    if state in (STATE_ACTIVE, STATE_INACTIVE):
        params["state"] = state
    return redirect(url_for("skilltest.admin_pool_skill", **params)
                    + "#q{}".format(question.id))


# --------------------------------------------------------------------------- #
# マネージャー: 設定(旧URL)
# --------------------------------------------------------------------------- #
@skilltest_bp.route("/admin/settings", methods=["GET", "POST"])
def admin_settings():
    """旧URL。設定はシステム設定の「スキルテスト」タブに移した。

    GET はそのタブへ移動し、POST は 307 でそのタブの保存へ転送する(フォームの内容はそのまま届く)。
    入力チェックは parse_skilltest_form()、保存先は instance/skilltest_settings.json のまま。
    """
    if request.method == "POST":
        return redirect(url_for("system.save_skilltest"), code=307)
    return redirect(url_for("system.settings", tab="skilltest"))


# #############################################################################
# 9. システム設定
# #############################################################################
# マネージャーのみ。アプリのすべての設定を1つの画面(タブ)で変更する。
#
#   9-1 項目の定義     基本設定の項目の定義(キー・グループ・表示名・説明・種類・再起動の要否・秘密か)。
#                      項目の定義はここの1か所だけにある
#   9-2 入力チェック   基本設定の入力チェック・保存(instance/config.py の書き換え)・画面表示用の値
#   9-3 画面           Blueprint: system_bp, /system/settings。タブ:
#                        基本設定（config） : instance/config.py の環境ごとの設定
#                        週報               : instance/weekly_settings.json
#                        期限超過通知       : instance/overdue_settings.json
#                        スキルテスト       : instance/skilltest_settings.json
#
# 週報・期限超過通知・スキルテストの入力チェックと表示用の値は、各機能の設定フォーム
# (6-3・7-3・8-5)にあり(保存先も各機能の設定の保存のまま)、この画面から使う。
# 各機能の画面には、実行・状況の表示だけが残る(設定はこの画面へのリンク)。


# =============================================================================
# 9-1. システム設定: 基本設定の項目の定義
# =============================================================================
# 基本設定(instance/config.py)の項目の定義。項目の定義はここ(FIELDS)の1か所だけに置く。
#
# 各項目: キー・グループ・表示名・説明・種類・再起動が必要か・秘密の値か(＋種類ごとの条件)。
# 新しい環境ごとの設定を Config と見本(CONFIG_TEMPLATE)に追加したら、ここにも定義を追加する
# (定義の無いキーは、画面の「その他」に読み取り専用で表示される)。
#
# 種類:
#   text       1行の文字列(改行・制御文字は不可。pattern があればその形式だけ)
#   url        http:// または https:// で始まるURL(空も可)
#   int        整数(min〜max)
#   bool       オン/オフ(チェックボックス)
#   address    メールアドレス1件(空も可)
#   addresses  メールアドレスの一覧(1行に1件。「,」「;」区切りも可)
#   secret     パスワード・キー。値は画面に出さない(設定あり/未設定だけ)。
#              空欄のまま保存すると変更しない。「空にする」で空にする。
#              bound_to の接続先を変えるときは、入力し直すか「空にする」が必要
#   secret_key セッションの秘密鍵。自由入力はなく、「新しいキーを生成」だけ

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

GROUPS = (
    (GROUP_LOGIN, "ログイン・セキュリティ"),
    (GROUP_LDAP, "LDAP"),
    (GROUP_AI, "AI"),
    (GROUP_MAIL, "メール送信"),
    (GROUP_RECIPIENTS, "宛先"),
    (GROUP_OVERDUE, "期限超過通知の宛先"),
    (GROUP_SERVER, "リンク・サーバー"),
)
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
        clear_warning="空にすると、admin のログイン可否は ldap_client.py の判定に任されます"
                      "（ldap_client.py に admin 用の固定パスワードがある場合は、それでログインできるようになります）。",
    ),
    # ---- LDAP ----
    Field(
        "LDAP_API_URL", GROUP_LDAP, "LDAP認証APIのURL",
        "本番でLDAP認証APIに接続する場合のエンドポイントです（例: https://auth.example.com/ldap/auth）。"
        "この値の使い方は ldap_client.py の実装によります"
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
)

FIELD_MAP = {field.key: field for field in FIELDS}
SECRET_KEYS = tuple(field.key for field in FIELDS if field.secret)

# 以前の版で使っていて、今は使わない項目。instance/config.py に残っていれば、画面の「その他」に
# この説明を付けて表示する(ファイルからは消さない)
RETIRED_KEYS = {
    "SERVER_HOST": "instance/config.py だけに記載（使われていません。待ち受けのアドレスは起動のコマンド"
                   "「flask --app app run」の --host で指定します）",
    "SERVER_PORT": "instance/config.py だけに記載（使われていません。待ち受けのポートは起動のコマンド"
                   "「flask --app app run」の --port で指定します）",
}


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
    """見本(CONFIG_TEMPLATE)と Config(環境ごとの設定の既定値)に出てくるキー。

    戻り値: (環境ごとの設定のキー(出てきた順), 固定設定(FixedConfig)のキーの集合)
    """
    keys = [name for name, _line in _assigned_names(ast.parse(CONFIG_TEMPLATE).body)]
    keys += [name for name in vars(Config) if name.isupper()]
    fixed = {name for name in vars(FixedConfig) if name.isupper()}
    return list(dict.fromkeys(keys)), fixed


# =============================================================================
# 9-2. システム設定: 基本設定の入力チェック・保存
# =============================================================================
# 基本設定(instance/config.py)の入力チェック・保存・画面表示用の値。
#
# 項目の定義は FIELDS(9-1。1か所)にあり、ここではそれに従って処理する。
#
# 保存の流れ(save_config_form):
#   1. instance/config.py を読み、画面を開いたときから変わっていないか確かめる(版の比較)
#   2. すべての項目を検証する。誤りが1つでもあれば何も書かない(入力は画面に残す。秘密の値は除く)
#   3. 値が変わった項目だけを instance/config.py に書く(1-3 の update_config。
#      元のファイルは instance/config.py.bak に残す)
#   4. 再起動が不要な項目は、実行中のアプリの設定(current_app.config)にもすぐ反映する。
#      SECRET_KEY はファイルにだけ書き、再起動後に反映される
#
# 秘密の値(SECRET_KEY / ADMIN_PASSWORD / AI_API_KEY / MAIL_PASSWORD)は、画面・ログ・
# メッセージのどこにも出さない(画面には「設定あり／未設定」だけを表示する)。

CONFIG_TEXT_MAX = 500           # 1行の文字列・URLの最大文字数
SECRET_MAX = 500         # パスワード・キーの最大文字数
ADDRESS_MAX_COUNT = 100  # アドレスの一覧の最大件数

_CONFIG_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_ADDR = r"[^\s@<>()\[\],;:\"\\]+@[^\s@<>()\[\],;:\"\\.][^\s@<>()\[\],;:\"\\]*"
# 「name@example.com」または「表示名 <name@example.com>」(表示名に , ; " < > は使えない。
# アドレスの部分は半角英数字・記号だけ。表示名は送信時に send_mail() が符号化する)
_ADDRESS_RE = re.compile(r"[^<>,;\"\x00-\x1f\x7f]*<{0}>|{0}".format(_ADDR))
_ADDRESS_SPLIT = re.compile(r"[\r\n,;]+")
# 「その他」の項目で値を表示しない(秘密の値の可能性がある)キー
_SECRET_LIKE = re.compile(r"KEY|PASS|SECRET|TOKEN|CREDENTIAL", re.IGNORECASE)

# 保存の結果
CONFIG_SAVE_OK = "ok"
CONFIG_SAVE_UNCHANGED = "unchanged"
CONFIG_SAVE_INVALID = "invalid"
CONFIG_SAVE_CONFLICT = "conflict"
CONFIG_SAVE_ERROR = "error"

# changed         : ファイルで値を変えた項目
# restart_changed : そのうち再起動後に反映される項目
# applied         : 実行中のアプリに反映した(値が変わった)項目
SaveResult = namedtuple("SaveResult", "status errors state changed restart_changed applied message")

MSG_CONFLICT = ("画面を開いた後に、設定ファイル（instance/config.py）が更新されています"
                "（ほかの人の保存・直接の編集）。最新の内容を表示しましたので、もう一度変更してください。")


# --------------------------------------------------------------------------- #
# 既定値・現在の値
# --------------------------------------------------------------------------- #
def defaults(app):
    """Config の既定値(create_app で控えたもの。無ければ Config クラス)。"""
    stored = app.extensions.get("config_defaults")
    if stored is not None:
        return stored
    return {name: getattr(Config, name) for name in dir(Config) if name.isupper()}


def effective(app, file_values):
    """各項目の値(ファイルに書かれていればその値、無ければ既定値)。"""
    base = defaults(app)
    return {f.key: file_values[f.key] if f.key in file_values else base.get(f.key)
            for f in FIELDS}


def running_value(app, key):
    """実行中のアプリの値。SECRET_KEY が起動時の一時的な鍵なら空として扱う。"""
    if key == "SECRET_KEY" and app.extensions.get("secret_key_temporary"):
        return ""
    return app.config.get(key)


def _differs(field, file_value, run_value):
    if field.type in (TYPE_SECRET, TYPE_SECRET_KEY):
        return str(file_value or "") != str(run_value or "")
    return not same_value(file_value, run_value)


def pending_fields(app, file_values):
    """ファイルの値と実行中の値が違う項目(再起動すると反映される)。"""
    values = effective(app, file_values)
    return [f for f in FIELDS if _differs(f, values[f.key], running_value(app, f.key))]


def mask_secrets(app, text):
    """メッセージに秘密の値(パスワード・キー)が含まれていたら伏せ字にする。"""
    text = str(text or "")
    for key in SECRET_KEYS:
        value = app.config.get(key)
        if isinstance(value, str) and len(value) >= 4 and value in text:
            text = text.replace(value, "***")
    return text


# --------------------------------------------------------------------------- #
# 入力チェック
# --------------------------------------------------------------------------- #
def _valid_address(text):
    """メールアドレス1件の簡単な形式チェック(local@domain、または 表示名 <local@domain>)。"""
    if not text or len(text) > 254 or _CONFIG_CONTROL.search(text):
        return False
    if not _ADDRESS_RE.fullmatch(text):
        return False
    addr = text[text.rfind("<") + 1:-1] if text.endswith(">") else text
    if not addr.isascii():
        return False
    # 送信時(send_mail()・smtplib)の解釈と同じアドレスになること(表示名の書き方によっては別の
    # アドレスと解釈されるため)
    if parseaddr(text)[1] != addr:
        return False
    domain = addr.rpartition("@")[2]
    return ".." not in domain and not domain.endswith(".")


def _parse_text(field, raw):
    value = raw.strip()
    if _CONFIG_CONTROL.search(value):
        return None, "改行・制御文字は使えません。"
    if len(value) > CONFIG_TEXT_MAX:
        return None, "{}文字以内で入力してください。".format(CONFIG_TEXT_MAX)
    if field.pattern and value and not re.fullmatch(field.pattern, value):
        return None, field.pattern_help or "形式が正しくありません。"
    return value, None


def _parse_url(field, raw):
    value = raw.strip()
    if not value:
        return "", None
    if _CONFIG_CONTROL.search(value) or any(ch.isspace() for ch in value):
        return None, "空白・改行を含まないURLを入力してください。"
    if len(value) > CONFIG_TEXT_MAX:
        return None, "{}文字以内で入力してください。".format(CONFIG_TEXT_MAX)
    try:
        parts = urlsplit(value)
        valid = parts.scheme.lower() in ("http", "https") and bool(parts.hostname)
        parts.port  # ポート番号が不正なら ValueError
    except ValueError:
        valid = False
    if not valid:
        return None, "http:// または https:// で始まるURLを入力してください。"
    if field.no_query and (parts.query or parts.fragment):
        return None, "「?」「#」以降を付けずに入力してください。"
    return value, None


def _parse_int(field, raw):
    value = raw.strip()
    message = "{}〜{}の整数で入力してください。".format(field.min, field.max)
    if not (value.isascii() and value.isdigit()) or len(value) > 9:
        return None, message
    number = int(value)
    if not field.min <= number <= field.max:
        return None, message
    return number, None


def _parse_address(field, raw):
    value = raw.strip()
    if not value:
        return "", None
    if not _valid_address(value):
        return None, "メールアドレスの形式が正しくありません（例: name@example.com）。"
    return value, None


def _parse_addresses(field, raw):
    items = [item.strip() for item in _ADDRESS_SPLIT.split(raw or "")]
    items = [item for item in items if item]
    bad = [item for item in items if not _valid_address(item)]
    if bad:
        return None, "メールアドレスの形式が正しくありません: {}".format(
            "、".join(item[:80] for item in bad[:3]))
    if len(items) > ADDRESS_MAX_COUNT:
        return None, "アドレスは{}件までにしてください。".format(ADDRESS_MAX_COUNT)
    return list(dict.fromkeys(items)), None


_PARSERS = {
    TYPE_TEXT: _parse_text,
    TYPE_URL: _parse_url,
    TYPE_INT: _parse_int,
    TYPE_ADDRESS: _parse_address,
    TYPE_ADDRESSES: _parse_addresses,
}


def _parse_secret(field, form, current_value):
    """秘密の値。空欄なら変更しない、「空にする」なら空、入力があればその値。"""
    raw = form.get(field.key, "")
    confirm = form.get(field.key + "_confirm", "") if field.confirm else ""
    clear = form.get("clear_" + field.key) == "1"
    if clear:
        if raw or confirm:
            return None, "新しい値の入力と「空にする」は同時に指定できません。", clear
        return "", None, clear
    if not raw:
        if confirm:
            return None, "新しいパスワードを両方の欄に入力してください。", clear
        return current_value, None, clear  # 変更しない
    if _CONFIG_CONTROL.search(raw):
        return None, "改行・制御文字は使えません。", clear
    if len(raw) > SECRET_MAX:
        return None, "{}文字以内で入力してください。".format(SECRET_MAX), clear
    if field.min_length and len(raw) < field.min_length:
        return None, "{}文字以上で入力してください。".format(field.min_length), clear
    if field.confirm and raw != confirm:
        return None, "確認のための入力が一致しません。", clear
    return raw, None, clear


def _destination(key, value):
    """秘密の値を送る接続先としての値(同じ接続先なら同じ値。AI_API_URL はスキーム・ホスト・ポート)。"""
    if key == "AI_API_URL":
        url = str(value or "").strip() or AI_DEFAULT_API_URL
        try:
            parts = urlsplit(url)
            port = parts.port or {"http": 80, "https": 443}.get(parts.scheme.lower())
            return parts.scheme.lower(), (parts.hostname or "").lower(), port
        except ValueError:
            return url
    if key == "MAIL_SMTP_PORT":
        try:
            return int(value or 25)
        except (TypeError, ValueError):
            return value
    if key == "MAIL_SMTP_SERVER":
        return str(value or "").strip().lower()
    return str(value or "").strip()


def _check_secret_destinations(form, current, values, errors):
    """接続先を変えるのに、保存済みの秘密の値をそのまま使おうとしていないか。

    画面に表示しない値(APIキー・パスワード)が、新しい接続先へ送られないようにする。
    """
    for field in FIELDS:
        if not field.bound_to or field.key in errors:
            continue
        kept = not form.get(field.key, "") and form.get("clear_" + field.key) != "1"
        if not kept or not _is_set(current.get(field.key)):
            continue
        moved = [FIELD_MAP[key] for key in field.bound_to
                 if key in values and _destination(key, values[key]) != _destination(key, current.get(key))]
        if moved:
            errors[field.key] = (
                "{}を変更するときは、{}を入力し直すか「空にする」を指定してください"
                "（保存済みの値は新しい接続先には使いません）。".format(
                    "・".join(f.label for f in moved), field.label))
            values.pop(field.key, None)


def parse_config_form(form, current):
    """フォームの入力を検証する。

    current : 今の値(ファイルの値。無ければ既定値)。秘密の値を変更しないときや、
              フォームに項目が無いときに使う
    戻り値: (values, errors, state)
      values : 全項目の保存後の値 {KEY: 値}
      errors : 誤りのある項目 {KEY: メッセージ}
      state  : 再表示用の入力(秘密の値は含めない)
    """
    values, errors, state = {}, {}, {}
    for field in FIELDS:
        key = field.key
        if field.type == TYPE_SECRET_KEY:
            generate = form.get("generate_" + key) == "1"
            state["generate_" + key] = generate
            values[key] = secrets.token_hex(32) if generate else current.get(key)
            continue
        if field.type == TYPE_SECRET:
            value, error, clear = _parse_secret(field, form, current.get(key))
            state["clear_" + key] = clear
        elif field.type == TYPE_BOOL:
            # チェックボックスの前に hidden の "0" を置いている(項目が無い = 変更しない)
            posted = form.getlist(key)
            value, error = ("1" in posted) if posted else current.get(key), None
            state[key] = bool(value)
        elif key not in form:
            value, error = current.get(key), None
            state[key] = _display(field, value)
        else:
            raw = form.get(key, "")
            state[key] = raw
            value, error = _PARSERS[field.type](field, raw)
        if error:
            errors[key] = error
        else:
            values[key] = value
    _check_secret_destinations(form, current, values, errors)
    return values, errors, state


# --------------------------------------------------------------------------- #
# 保存
# --------------------------------------------------------------------------- #
def _apply_live(app, file_values):
    """再起動が不要な項目に、ファイルの値を実行中のアプリの設定へ反映する。値が変わった項目を返す。"""
    final = effective(app, file_values)
    applied = []
    for field in FIELDS:
        if field.restart_required:
            continue
        if not same_value(app.config.get(field.key), final[field.key]):
            applied.append(field.key)
        app.config[field.key] = final[field.key]
    return applied


def save_config_form(app, form, username):
    """基本設定を保存する。戻り値: SaveResult(メッセージに秘密の値は含めない)。

    保存後(変更が無かった場合も)、再起動が不要な項目はファイルの値を実行中のアプリに反映する
    (ファイルを直接編集した値も、ここで保存すると反映される)。
    """
    def result(status, errors=None, state=None, changed=(), restart_changed=(), applied=(),
               message=""):
        return SaveResult(status, errors or {}, state, list(changed), list(restart_changed),
                          list(applied), message)

    with config_file_lock:
        try:
            info = read_config(app.instance_path)
        except ConfigFileError as exc:
            return result(CONFIG_SAVE_ERROR, message=str(exc))
        if form.get("version", "") != info["version"]:
            return result(CONFIG_SAVE_CONFLICT, message=MSG_CONFLICT)

        current = effective(app, info["values"])
        values, errors, state = parse_config_form(form, current)
        if errors:
            return result(CONFIG_SAVE_INVALID, errors=errors, state=state)

        changes = {f.key: values[f.key] for f in FIELDS
                   if not same_value(values[f.key], current.get(f.key))}
        if not changes:
            applied = _apply_live(app, info["values"])
            if applied:
                app.logger.info("システム設定（基本設定）: ファイルの値を実行中の設定に反映しました: %s（%s）",
                                ", ".join(applied), username)
            return result(CONFIG_SAVE_UNCHANGED, applied=applied)

        try:
            new_values = update_config(
                app.instance_path, changes, username, expected_version=info["version"])
        except ConfigConflictError:
            return result(CONFIG_SAVE_CONFLICT, message=MSG_CONFLICT)
        except ConfigFileError as exc:
            app.logger.warning("システム設定（基本設定）を保存できませんでした: %s", exc)
            return result(CONFIG_SAVE_ERROR, state=state, message=str(exc))

        # 再起動が不要な項目は、実行中のアプリにもすぐ反映する
        applied = _apply_live(app, new_values)
        changed = [f.key for f in FIELDS if f.key in changes]
        restart_changed = [key for key in changed if FIELD_MAP[key].restart_required]
        app.logger.info("システム設定（基本設定）を変更しました: %s（%s）",
                        ", ".join(changed), username)
        return result(CONFIG_SAVE_OK, changed=changed, restart_changed=restart_changed,
                      applied=applied)


# --------------------------------------------------------------------------- #
# 画面表示用の値
# --------------------------------------------------------------------------- #
def _display(field, value):
    """入力欄に表示する値(秘密の値には使わない)。"""
    if field.type == TYPE_BOOL:
        return bool(value)
    if field.type == TYPE_ADDRESSES:
        if isinstance(value, str):
            items = re.split(r"[,;]", value)
        elif isinstance(value, (list, tuple)):
            items = [str(item) for item in value]
        else:
            items = []
        return "\n".join(item.strip() for item in items if item.strip())
    if value is None:
        return ""
    return str(value)


def _is_set(value):
    return value not in (None, "", [], ())


def _other_rows(app, file_values):
    """定義の無いキー(読み取り専用で「その他」に表示)。"""
    documented, fixed = documented_keys()
    base = defaults(app)
    keys = [(key, "app.py の見本・既定値") for key in documented if key not in FIELD_MAP]
    keys += [(key, RETIRED_KEYS.get(key, "instance/config.py だけに記載")) for key in file_values
             if key not in FIELD_MAP and key not in fixed and key not in documented]
    rows = []
    for key, source in keys:
        in_file = key in file_values
        value = file_values[key] if in_file else base.get(key)
        hidden = bool(_SECRET_LIKE.search(key))
        text = repr(value) if (in_file or key in base) else ""
        rows.append({
            "key": key,
            "source": source,
            "in_file": in_file,
            "is_set": _is_set(value),
            "hidden": hidden,
            "value": "" if hidden else (text if len(text) <= 120 else text[:117] + "..."),
        })
    return rows


def config_form_context(app, state=None, errors=None):
    """基本設定タブの表示用の値。state / errors は保存エラーで再表示するときの入力と誤り。"""
    errors = errors or {}
    try:
        info = read_config(app.instance_path)
        file_error = None
    except ConfigFileError as exc:
        info, file_error = None, str(exc)

    if info is not None:
        file_values = info["values"]
        current = effective(app, file_values)
        pending = pending_fields(app, file_values)
    else:
        file_values = {}
        current = {f.key: app.config.get(f.key) for f in FIELDS}
        pending = []
    pending_keys = {f.key for f in pending}

    groups = []
    for group_key, group_label in GROUPS:
        rows = []
        for field in (f for f in FIELDS if f.group == group_key):
            value = current.get(field.key)
            if field.type == TYPE_SECRET_KEY and info is None:
                value = running_value(app, field.key)
            row = {
                "field": field,
                "is_set": _is_set(value),
                "in_file": field.key in file_values,
                "pending": field.key in pending_keys,
                "error": errors.get(field.key),
                # キー名に clear などを使わない(Jinja の row.clear が dict.clear メソッドになるため)
                "clear_checked": bool(state and state.get("clear_" + field.key)),
                "generate_checked": bool(state and state.get("generate_" + field.key)),
                "value": "",
            }
            if not field.secret:
                if state is not None and field.key in state:
                    row["value"] = state[field.key]
                else:
                    row["value"] = _display(field, value)
            rows.append(row)
        groups.append({"key": group_key, "label": group_label, "rows": rows})

    test_to, _cc = mail_recipients(test=True)
    return {
        "file_error": file_error,
        "can_save": info is not None,
        "exists": bool(info and info["exists"]),
        "version": info["version"] if info else "",
        "groups": groups,
        "other": _other_rows(app, file_values),
        "pending": pending,
        "pending_secret_key": "SECRET_KEY" in pending_keys,
        "error_count": len(errors),
        "mail_test_problem": check_mail_settings(test=True),
        "mail_test_to_count": len(test_to),
        "mail_test_to_is_from": not mail_settings()["test_to"],
        "ai_enabled": ai_is_configured(),
        "ai_status": ai_status_label(),
    }


# =============================================================================
# 9-3. システム設定: 画面
# =============================================================================
# システム設定の画面。マネージャーのみ(未ログインはログイン画面へ、メンバーは403)。
#
# GET  /system/settings?tab=<タブ>     設定画面(タブ: config / weekly / overdue / skilltest)
# POST /system/settings/config         基本設定の保存(instance/config.py)
# POST /system/settings/weekly         週報の設定の保存(instance/weekly_settings.json)
# POST /system/settings/overdue        期限超過通知の設定の保存(instance/overdue_settings.json)
# POST /system/settings/skilltest      スキルテストの設定の保存(instance/skilltest_settings.json)
# POST /system/settings/test-mail      メール接続テスト(保存済みの設定で、テスト送信の宛先へ短いメール)
# POST /system/settings/test-ai        AI接続テスト(保存済みの設定で、短い問い合わせを1回)
#
# タブごとに別のフォーム・保存ボタンを持ち、保存後は同じタブに戻る(?tab= で開くタブを指定)。
# 入力に誤りがあれば何も保存せず、入力中の内容(秘密の値は除く)を残して同じタブを再表示する。

system_bp = Blueprint("system", __name__, url_prefix="/system")

TAB_CONFIG = "config"
TAB_WEEKLY = "weekly"
TAB_OVERDUE = "overdue"
TAB_SKILLTEST = "skilltest"

# (キー, 表示名, アイコン)
TABS = (
    (TAB_CONFIG, "基本設定（config）", "bi-sliders"),
    (TAB_WEEKLY, "週報", "bi-file-earmark-text"),
    (TAB_OVERDUE, "期限超過通知", "bi-alarm"),
    (TAB_SKILLTEST, "スキルテスト", "bi-patch-check"),
)
TAB_KEYS = tuple(key for key, _label, _icon in TABS)

# 機能ごとの設定(画面のJSONファイル)の扱い方
#   label         : ログに出す機能の名前
#   saved_message : 保存したときのメッセージ
#   load / save   : 設定の読み込み・保存
#   parse         : フォームの入力の検証 → (保存する値, エラーメッセージの一覧)
#   with_input    : 入力エラーで再表示するとき、保存済みの設定に入力中の値を重ねる
#   context       : フォームの表示に使う値
SettingsFeature = namedtuple(
    "SettingsFeature", "label saved_message load save parse with_input context")

# タブ → 機能ごとの設定
FEATURES = {
    TAB_WEEKLY: SettingsFeature(
        WEEKLY_LABEL, WEEKLY_SAVED_MESSAGE, load_weekly_settings, save_weekly_settings,
        parse_weekly_form, settings_with_input, weekly_form_context),
    TAB_OVERDUE: SettingsFeature(
        OVERDUE_LABEL, OVERDUE_SAVED_MESSAGE, load_overdue_settings, save_overdue_settings,
        parse_overdue_form, settings_with_input, overdue_form_context),
    TAB_SKILLTEST: SettingsFeature(
        SKILLTEST_LABEL, SKILLTEST_SAVED_MESSAGE, load_skilltest_settings,
        save_skilltest_settings, parse_skilltest_form, skilltest_with_input,
        skilltest_form_context),
}

# AI接続テストで送る問い合わせ(短く、応答も短くなるもの)
AI_TEST_MESSAGES = [
    {"role": "user", "content": "接続テストです。「OK」とだけ返してください。"},
]
AI_REPLY_MAX = 80


@system_bp.before_request
def _system_managers_only():
    """システム設定はマネージャーのみ(未ログインはログイン画面へ)。

    login_required は OPTIONS を素通しするため使わず、ここで直接確認する。
    """
    if not current_user.is_authenticated:
        return current_app.login_manager.unauthorized()
    if not getattr(current_user, "is_manager", False):
        abort(403)


def _tab_url(tab):
    return url_for("system.settings", tab=tab)


def _render_system_settings(tab, status=200, config_state=None, config_errors=None, inputs=None):
    """設定画面を表示する。

    config_state / config_errors : 基本設定の入力エラーで再表示するときの入力と誤り
    inputs                       : 機能の設定の入力エラーで再表示するときの {タブ: 設定}
    """
    app = current_app._get_current_object()
    inputs = inputs or {}
    contexts = {}
    for key, feature in FEATURES.items():
        settings = inputs[key] if key in inputs else feature.load()
        contexts[key] = feature.context(settings)
    return render_template(
        "system/settings.html",
        tab=tab,
        tabs=TABS,
        cfg=config_form_context(app, state=config_state, errors=config_errors),
        wk=contexts[TAB_WEEKLY],
        od=contexts[TAB_OVERDUE],
        st=contexts[TAB_SKILLTEST],
    ), status


@system_bp.route("/", endpoint="index")
def system_index():
    return redirect(_tab_url(TAB_CONFIG))


@system_bp.route("/settings", endpoint="settings")
def system_settings():
    tab = request.args.get("tab", "")
    if tab not in TAB_KEYS:
        tab = TAB_CONFIG
    return _render_system_settings(tab)


# --------------------------------------------------------------------------- #
# 基本設定(instance/config.py)
# --------------------------------------------------------------------------- #
@system_bp.route("/settings/config", methods=["POST"])
def save_config():
    app = current_app._get_current_object()
    result = save_config_form(app, request.form, current_user.username)

    if result.status == CONFIG_SAVE_INVALID:
        flash("入力内容に誤りがあります（{}件）。各項目のメッセージを確認してください。"
              "設定は保存していません。".format(len(result.errors)), "danger")
        return _render_system_settings(TAB_CONFIG, status=400,
                                       config_state=result.state, config_errors=result.errors)
    if result.status == CONFIG_SAVE_CONFLICT:
        flash(result.message, "warning")
        return redirect(_tab_url(TAB_CONFIG))
    if result.status == CONFIG_SAVE_ERROR:
        flash("基本設定を保存できませんでした: {}".format(result.message), "danger")
        return _render_system_settings(TAB_CONFIG, status=500, config_state=result.state)
    if result.status == CONFIG_SAVE_UNCHANGED:
        message = "変更された項目はありません（設定ファイルは更新していません）。"
        if result.applied:
            message += "設定ファイルの値を実行中の設定に反映しました: {}。".format("、".join(result.applied))
        flash(message, "info")
        return redirect(_tab_url(TAB_CONFIG))

    message = "基本設定を保存しました（変更: {}）。変更前の内容は instance/config.py.bak に残しています。".format(
        "、".join(result.changed))
    live = [key for key in result.changed if key not in result.restart_changed]
    if live:
        message += "{} はすぐに反映しました。".format("、".join(live))
    others = [key for key in result.applied if key not in result.changed]
    if others:
        message += "設定ファイルを直接編集した {} も実行中の設定に反映しました。".format("、".join(others))
    flash(message, "success")
    if result.restart_changed:
        notice = "{} はサーバーの再起動後に反映されます。".format("、".join(result.restart_changed))
        if "SECRET_KEY" in result.restart_changed:
            notice += "再起動すると全員がログアウトされます。"
        flash(notice, "warning")
    return redirect(_tab_url(TAB_CONFIG))


@system_bp.route("/settings/test-mail", methods=["POST"])
def test_mail():
    """保存済みの設定で、テスト送信の宛先(MAIL_TEST_TO。空なら差出人)へ短いメールを送る。"""
    app = current_app._get_current_object()
    subject = "【接続テスト】{}".format(app.config.get("APP_NAME") or "業務管理システム")
    text = (
        "このメールは、{} の「システム設定」のメール接続テストで送信しました。\n"
        "送信日時: {}\n"
        "実行した人: {}\n"
        "\n"
        "返信は不要です。\n"
    ).format(app.config.get("APP_NAME") or "業務管理システム",
             datetime.now().strftime("%Y/%m/%d %H:%M"), current_user.display_name)
    ok, message = send_mail(subject, text, test=True)
    message = mask_secrets(app, message)
    if ok:
        flash("メール接続テスト: OK（{}）".format(message), "success")
    else:
        flash("メール接続テスト: 失敗しました。{}".format(message), "danger")
    return redirect(_tab_url(TAB_CONFIG))


@system_bp.route("/settings/test-ai", methods=["POST"])
def test_ai():
    """保存済みの設定で、AIに短い問い合わせを1回送る。"""
    app = current_app._get_current_object()
    reply, error = ai_chat(AI_TEST_MESSAGES)
    if error:
        flash("AI接続テスト: 失敗しました。{}".format(mask_secrets(app, error)), "danger")
    else:
        reply = " ".join(str(reply).split())
        if len(reply) > AI_REPLY_MAX:
            reply = reply[:AI_REPLY_MAX] + "…"
        flash("AI接続テスト: OK（応答: {}）".format(mask_secrets(app, reply)), "success")
    return redirect(_tab_url(TAB_CONFIG))


# --------------------------------------------------------------------------- #
# 機能ごとの設定(週報・期限超過通知・スキルテスト)
# --------------------------------------------------------------------------- #
def _save_feature(tab):
    """機能の設定を保存する(入力チェックと保存先は FEATURES の各機能の関数)。"""
    feature = FEATURES[tab]
    values, errors = feature.parse(request.form)
    if errors:
        for message in errors:
            flash(message, "danger")
        # 入力中の内容を残したまま再表示する(保存はしない)
        return _render_system_settings(tab, status=400,
                                       inputs={tab: feature.with_input(feature.load(), values)})
    try:
        feature.save(values)
    except OSError as exc:
        current_app.logger.exception("%sの設定を保存できませんでした", feature.label)
        flash("設定を保存できませんでした: {}".format(exc), "danger")
        return _render_system_settings(tab, status=500,
                                       inputs={tab: feature.with_input(feature.load(), values)})
    flash(feature.saved_message, "success")
    return redirect(_tab_url(tab))


@system_bp.route("/settings/weekly", methods=["POST"])
def save_weekly():
    return _save_feature(TAB_WEEKLY)


@system_bp.route("/settings/overdue", methods=["POST"])
def save_overdue():
    return _save_feature(TAB_OVERDUE)


@system_bp.route("/settings/skilltest", methods=["POST"])
def save_skilltest():
    return _save_feature(TAB_SKILLTEST)


# #############################################################################
# 10. 定期メールの自動送信スケジューラ
# #############################################################################


# =============================================================================
# 10-1. スケジューラ(週報・期限超過通知)
# =============================================================================
# 定期メールの自動送信スケジューラ(バックグラウンドのスレッド1本で、2つの仕事を確認する)。
#
# 約30秒ごとに、次の仕事(ジョブ)ごとに設定(instance/ のJSON)を読み、実行時刻なら1回だけ実行する。
#   weekly  : 週報。自動送信が有効で、今の曜日・時刻(HH:MM)が設定と一致したとき
#   overdue : 期限超過通知。自動送信が有効で、今日が営業日(土日・祝日以外)で、
#             今の時刻(HH:MM)が設定と一致したとき
#
# - 起動するのは「flask --app app run」でサーバーとして動かしたときだけ(create_app() の最後で
#   start_scheduler_once() を呼ぶ。seed / migrate コマンド・テスト・import では起動しない)。
#   flask run --debug の自動再読み込みで2つのプロセスがアプリを作っても、instance/scheduler.lock の
#   ロックを取れた1つのプロセスだけが動かす(10-2)
# - ジョブごとに、同じ (日付, 時刻) ではこのプロセスの中で1回しか実行しない(メモリ上の記録)
# - サーバーが止まっていて実行時刻を過ぎた分は、後から実行しない(取りこぼしの再実行なし)
# - 実行履歴はDBに残さない(結果は各機能の「前回の結果」に上書き)
# - 実行はジョブごとに別のスレッドで行う(時間のかかる週報の作成中も、もう一方の
#   ジョブの時刻の確認が止まらないようにするため)
# - 例外はジョブごとに捕まえてそのジョブの「前回の結果」に書き、他のジョブ・スレッドは止めない

CHECK_INTERVAL = 30  # 秒

# name           : ジョブの名前(実行済みの記録のキー)
# label          : ログ・メッセージ用の名前
# load_settings  : 設定を読む(app_context の中で呼ぶ)
# due_key        : (設定, 今) → 実行時刻なら (日付, "HH:MM")、そうでなければ None
# run            : (app, 設定, 今) → 実行して成否を返す
# record_failure : (メッセージ) → 前回の結果に失敗を書く(app_context の中で呼ぶ)
Job = namedtuple("Job", "name label load_settings due_key run record_failure")


# --------------------------------------------------------------------------- #
# 週報
# --------------------------------------------------------------------------- #
def _weekly_due_key(settings, now):
    """今が週報の実行時刻なら (日付, "HH:MM") を返す。そうでなければ None。"""
    if not settings["enabled"]:
        return None
    if now.weekday() != settings["weekday"] or now.strftime("%H:%M") != settings["time"]:
        return None
    return (now.date(), settings["time"])


def _weekly_run(app, settings, now):
    start, end = period_for(now.date(), settings["period_rule"])
    result = run_weekly(
        app, start, end, TRIGGER_AUTO, DELIVER_SEND,
        send_date=now.date(),
    )
    return result["ok"]


def _weekly_failure(message):
    set_weekly_last_result(TRIGGER_AUTO, False, message)


# --------------------------------------------------------------------------- #
# 期限超過通知
# --------------------------------------------------------------------------- #
def _overdue_run(app, settings, now):
    result = run_overdue(
        app, TRIGGER_AUTO, test=False, today=now.date())
    return result["ok"]


def _overdue_failure(message):
    set_overdue_last_result(TRIGGER_AUTO, False, message)


JOBS = (
    Job("weekly", "週報", load_weekly_settings, _weekly_due_key, _weekly_run, _weekly_failure),
    Job("overdue", "期限超過通知", load_overdue_settings, overdue_due_key,
        _overdue_run, _overdue_failure),
)

_scheduler_start_lock = threading.Lock()
_scheduler_thread = None


def _execute(app, job, settings, now):
    """ジョブを実行する(例外はここで捕まえて、そのジョブの前回の結果に書く)。"""
    try:
        ok = job.run(app, settings, now)
        app.logger.info("%sの自動送信: %s", job.label, "成功" if ok else "失敗")
    except Exception as exc:  # 各 run は例外を出さない想定だが念のため
        app.logger.exception("%sの自動送信でエラーが発生しました", job.label)
        try:
            with app.app_context():
                job.record_failure("自動送信でエラーが発生しました: {}".format(exc))
        except Exception:
            app.logger.exception("%sの前回の結果を保存できませんでした", job.label)


def _check_job(app, job, fired, now, start_thread=True):
    """1つのジョブの確認。実行を始めた場合はそのスレッド(start_thread=False なら True)を返す。"""
    with app.app_context():
        settings = job.load_settings()
    key = job.due_key(settings, now)
    if key is None or key in fired:
        return None
    fired.add(key)
    # 古い記録は不要(同じ日付・時刻が再び来ることはない)
    for old in [k for k in fired if k[0] < now.date()]:
        fired.discard(old)

    if not start_thread:
        _execute(app, job, settings, now)
        return True
    thread = threading.Thread(
        target=_execute, args=(app, job, settings, now),
        name="scheduled-{}".format(job.name), daemon=True,
    )
    thread.start()
    return thread


def _tick(app, fired, now, start_thread=True):
    """1回分の確認。fired はジョブ名ごとの実行済みの記録 {name: set()}。

    実行を始めたジョブの {name: スレッド(start_thread=False なら True)} を返す。
    1つのジョブの確認で例外が起きても、他のジョブの確認は続ける。
    """
    started = {}
    for job in JOBS:
        try:
            result = _check_job(app, job, fired.setdefault(job.name, set()), now, start_thread)
        except Exception:
            app.logger.exception("%sの自動送信の確認でエラーが発生しました", job.label)
            continue
        if result is not None:
            started[job.name] = result
    return started


def _loop(app, interval):
    fired = {}
    wait = threading.Event()
    while True:
        try:
            _tick(app, fired, datetime.now())
        except Exception:
            app.logger.exception("定期メールのスケジューラでエラーが発生しました")
        wait.wait(interval)


def start_scheduler(app, interval=CHECK_INTERVAL):
    """スケジューラのスレッドを起動する(2回目以降の呼び出しは何もしない)。"""
    global _scheduler_thread
    with _scheduler_start_lock:
        if _scheduler_thread is not None and _scheduler_thread.is_alive():
            return _scheduler_thread
        _scheduler_thread = threading.Thread(
            target=_loop, args=(app, interval), name="mail-scheduler", daemon=True
        )
        _scheduler_thread.start()
    app.logger.info("定期メール（週報・期限超過通知）の自動送信スケジューラを起動しました（%s秒ごとに確認）",
                    interval)
    return _scheduler_thread


# =============================================================================
# 10-2. サーバーとして起動したときの開始(プロセス間で1つだけ)
# =============================================================================
SCHEDULER_LOCK_FILENAME = "scheduler.lock"

# ロックを取ったファイル(プロセスが終わるまで開いたままにする。閉じるとロックが外れる)
_scheduler_lock_file = None


def _acquire_scheduler_lock(instance_path):
    """instance/scheduler.lock のロックを取る(待たない)。取れた(既に持っている)なら True。

    flask run --debug では自動再読み込み(reloader)のために2つのプロセスがアプリを作るため、
    ロックを取れた1つのプロセスだけがスケジューラを動かす(同じ仕事を2回実行しないように)。
    ロックはプロセスが終わると OS が外す。
    """
    global _scheduler_lock_file
    if _scheduler_lock_file is not None:
        return True
    # ファイルを開けない(読み取り専用・権限が無いなど)ときの OSError は、
    # 呼び出し元の start_scheduler_once() が受け止める(自動送信だけを止める)
    lock_file = open(os.path.join(instance_path, SCHEDULER_LOCK_FILENAME), "a+b")
    try:
        if os.name == "nt":
            import msvcrt
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock_file.close()
        return False
    _scheduler_lock_file = lock_file
    return True


def start_scheduler_once(app):
    """スケジューラを起動する(ほかのプロセスが既に動かしていれば起動しない)。

    ロックのファイルを開けないときも起動しない(自動送信だけを止め、サーバーは起動する)。
    """
    try:
        acquired = _acquire_scheduler_lock(app.instance_path)
    except OSError:
        app.logger.warning("instance/%s を開けないため、定期メールの自動送信スケジューラは起動しません。",
                           SCHEDULER_LOCK_FILENAME, exc_info=True)
        return None
    if not acquired:
        app.logger.info("定期メールの自動送信スケジューラは別のプロセスで動いているため、"
                        "このプロセスでは起動しません。")
        return None
    thread = start_scheduler(app)
    _notice("定期メール（週報・期限超過通知）の自動送信スケジューラを起動しました。")
    return thread


# #############################################################################
# 11. アプリの組み立て
# #############################################################################


# =============================================================================
# 11-1. 画面テンプレート・静的ファイル(templates.html)
# =============================================================================
# 画面テンプレート(Jinja2)・CSS・JavaScript は、プロジェクト直下の templates.html に
# ファイルごとのセクションとしてまとめてある(TemplateSections で読む)。
# テンプレート名・静的ファイルの URL(/static/...)はフォルダに分けていたときと同じ。

# プロジェクト直下の templates.html(画面テンプレート・CSS・JavaScript をまとめたファイル)
TEMPLATES_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "templates.html"
)
# 区切りの行(「{#=== 名前 ===#}」だけの行)。次の区切りの行の前までが、その名前の中身
_SECTION_MARKER = re.compile(r"^\{#=== (\S+) ===#\}\r?(?:\n|\Z)", re.MULTILINE)
# 名前がこれで始まるセクションは静的ファイル(/static/<残りの名前> で配信する)
STATIC_SECTION_PREFIX = "static/"


def _parse_sections(text, path):
    """templates.html の中身を {セクション名: 中身} に分ける(path はエラーの表示用)。

    最初の区切りより前(ファイルの説明のコメント)は読まない。
    名前の重複・中身が空のセクションはエラー(起動時に気付けるように)。
    """
    markers = list(_SECTION_MARKER.finditer(text))
    if not markers:
        raise RuntimeError(f"{path} に区切りの行がありません。")
    sections = {}
    for marker, following in zip(markers, markers[1:] + [None]):
        name = marker.group(1)
        body = text[marker.end():following.start() if following else len(text)]
        if name in sections:
            raise RuntimeError(f"{path}: セクション「{name}」が重複しています。")
        if not body.strip():
            raise RuntimeError(f"{path}: セクション「{name}」の中身が空です。")
        sections[name] = body
    return sections


class TemplateSections:
    """templates.html をセクションごとに読む(テンプレート用のローダーと静的ファイルの配信で共用)。

    ファイルの更新日時が変わったときだけ読み直す。
    テンプレートを読み直すかどうかは、フォルダに分けていたときと同じく
    Flask の設定(デバッグモード・TEMPLATES_AUTO_RELOAD)に従う。
    """

    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self._mtime = None
        self._sections = {}

    def load(self):
        """({セクション名: 中身}, 読み込んだファイルの更新日時) を返す。"""
        mtime = os.path.getmtime(self.path)
        with self._lock:
            if mtime != self._mtime:
                # 改行コードはそのまま読む(静的ファイルを元のバイト列のまま返すため)。
                # utf-8-sig: メモ帳などで BOM 付きで保存されても読めるように
                with open(self.path, encoding="utf-8-sig", newline="") as f:
                    self._sections = _parse_sections(f.read(), self.path)
                self._mtime = mtime
            return self._sections, self._mtime

    def is_current(self, mtime):
        """更新日時 mtime で読み込んだ後、ファイルが変わっていないか。"""
        try:
            return os.path.getmtime(self.path) == mtime
        except OSError:
            return False


template_sections = TemplateSections(TEMPLATES_FILE)


class SectionTemplateLoader(BaseLoader):
    """Jinja のテンプレートを templates.html のセクションから読むローダー。

    テンプレート名はセクション名(例: "tasks/list.html")。static/ のセクションはテンプレートにしない。
    """

    def __init__(self, sections):
        self.sections = sections

    def get_source(self, environment, template):
        sections, mtime = self.sections.load()
        if template.startswith(STATIC_SECTION_PREFIX) or template not in sections:
            raise TemplateNotFound(template)
        # エラーの表示用。行番号はセクションの先頭(区切りの次の行)から数えたもの
        filename = f"{self.sections.path}#{template}"
        return sections[template], filename, lambda: self.sections.is_current(mtime)

    def list_templates(self):
        sections, _ = self.sections.load()
        return sorted(name for name in sections if not name.startswith(STATIC_SECTION_PREFIX))


def send_static_section(filename):
    """静的ファイル(templates.html の static/ のセクション)を返す。エンドポイント名は static。

    Flask の static フォルダから配信していたときと同じ応答にする:
    Content-Type はファイル名から判定し、Content-Disposition(inline)・Cache-Control(既定 no-cache)・
    ETag と Last-Modified による条件付きGET(304)に対応する。無い名前は 404。
    """
    sections, mtime = template_sections.load()
    body = sections.get(STATIC_SECTION_PREFIX + filename)
    if body is None:
        abort(404)
    data = body.encode("utf-8")
    return send_file(
        BytesIO(data),
        download_name=posixpath.basename(filename),
        etag=hashlib.sha1(data).hexdigest(),
        last_modified=mtime,
    )


# =============================================================================
# 11-2. create_app(アプリの作成)
# =============================================================================
# 設定の読み込み順:
#   1. Config(このファイルの固定設定と、環境ごとの設定の既定値)
#   2. instance/config.py(環境ごとの実際の値。無ければ初回に自動作成)
# instance/config.py は、マネージャーが画面(システム設定の「基本設定」タブ)からも変更できる
# (再起動が不要な項目は保存と同時に app.config にも反映される)。
#
# 新しい機能は、Blueprint を作って BLUEPRINTS に加えるだけで追加できる。
BLUEPRINTS = (
    auth_bp,
    main_bp,
    tasks_bp,
    routine_bp,
    leaves_bp,
    skills_bp,
    # スキルテスト(メンバーが受験し到達度を自動登録。管理画面はマネージャーのみ)
    skilltest_bp,
    manager_bp,
    departments_bp,
    export_bp,
    # 定期メール(週報・期限超過通知)の画面。自動送信のスケジューラは create_app() の最後で
    # 「flask run」のときだけ起動する
    weekly_bp,
    overdue_bp,
    # システム設定(マネージャーのみ。基本設定・週報・期限超過通知・スキルテストの設定を1画面で変更)
    system_bp,
)


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


def prepare_instance(app):
    """instance フォルダ(DBファイル・環境ごとの設定ファイル置き場)を用意して、設定とDBを読み込む。

    instance/config.py が無ければ初回のみ自動作成し、その値で既定値を上書きする。
    DB(instance/app.db)に足りないテーブルがあれば作成する。
    用意済みのアプリ(DBを紐付け済み)では何もしない。
    """
    if "sqlalchemy" in app.extensions:
        # create_app() で用意済みのアプリに seed / migrate を実行したときなど
        return
    os.makedirs(app.instance_path, exist_ok=True)
    ensure_instance_config(app.instance_path)
    app.config.from_pyfile(CONFIG_FILENAME, silent=True)
    _ensure_secret_key(app)

    db_path = os.path.join(app.instance_path, "app.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    db.init_app(app)
    with app.app_context():
        db.create_all()


def create_app():
    """アプリを作る。「flask --app app <コマンド>」はこの関数でアプリを作る。

    - flask run         : instance を用意し、定期メールの自動送信スケジューラも起動する
    - flask seed / migrate など、このアプリのコマンド:
                          コマンドを探すために読み込まれる段階では instance に触れない
                          (各コマンドが prepare_instance() を呼ぶ。migrate --db は既定のDBに触れない)
    - それ以外(テスト・flask routes など): instance を用意する(スケジューラは起動しない)
    """
    app = Flask(__name__, instance_relative_config=True, static_folder=None, template_folder=None)
    # 画面テンプレート・CSS・JavaScript は templates.html から読む(区切りの誤りは起動時にエラーにする)
    template_sections.load()
    app.jinja_loader = SectionTemplateLoader(template_sections)
    app.add_url_rule("/static/<path:filename>", endpoint="static", view_func=send_static_section)
    app.config.from_object(Config)
    # 既定値の控え(システム設定の画面で、instance/config.py に無い項目の値として使う)
    app.extensions["config_defaults"] = {
        name: getattr(Config, name) for name in dir(Config) if name.isupper()
    }

    login_manager.init_app(app)
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    # テンプレートで使う共通変数
    @app.context_processor
    def inject_globals():
        return {"app_name": app.config.get("APP_NAME", "業務管理")}

    app.cli.add_command(seed_command)
    app.cli.add_command(migrate_command)

    # flask コマンドから読み込まれているときの click の Context(それ以外は None)
    command = click.get_current_context(silent=True)
    if command is not None and isinstance(command.command, click.Group):
        # flask がこのアプリのコマンド(seed / migrate)を探すために読み込んでいる
        return app
    prepare_instance(app)
    if command is not None and command.command.name == "run":
        start_scheduler_once(app)
    return app


# #############################################################################
# 12. flask コマンド(seed / migrate)
# #############################################################################
# 「flask --app app <コマンド>」で使えるコマンド(create_app() で登録する)。
#   flask --app app seed                          初期データの投入
#   flask --app app migrate [--check] [--db パス]   既存DBを最新のモデル定義に合わせる
# どちらも定期メールの自動送信スケジューラは起動しない。


# =============================================================================
# 12-1. seed: 初期データの投入
# =============================================================================
@click.command("seed")
@with_appcontext
def seed_command():
    """初期データ(ダミーユーザー・動作確認用のサンプル)を投入する。

    ダミーユーザーと、動作確認用のサンプルタスクなどを作成する(既にあれば作らない)。
    ※ ログイン認証自体は ldap_client.py の _DUMMY_USERS で行われる。
       このコマンドは「画面表示・担当者割り当て」用にDBへユーザーを登録する。
    """
    import ldap_client  # 本番環境ごとに差し替えるファイル(使うときに読み込む)

    app = current_app._get_current_object()
    prepare_instance(app)

    with app.app_context():
        # --- ユーザー(固定ローカル管理者＋ダミーLDAPの顔ぶれ)をDBに登録 ---
        user_map = {}
        accounts = {**ldap_client._LOCAL_ACCOUNTS, **ldap_client._DUMMY_USERS}
        for username, info in accounts.items():
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


# =============================================================================
# 12-2. migrate: 既存DBを最新のモデル定義に合わせる
# =============================================================================
# コードを新しいものに差し替えたあと、**実運用中のDBを消さずに** flask --app app migrate を
# 1回実行すれば、不足しているテーブル・列が追加されて動くようになる。
#
# やること:
#   1. モデルにあってDBに無い「テーブル」を作成 (db.create_all)
#   2. モデルにあってDBに無い「列」を ALTER TABLE ADD COLUMN で追加
#      ※SQLiteでは列の削除・型変更ができないため、追加のみ行う
#   3. DBにだけ残っている未使用列は、そのまま放置(読み書きしないので無害)
#
# 既存データは一切削除・変更しない。何度実行しても安全(冪等)。
def collect_changes(insp):
    """不足しているテーブル・列を洗い出す。"""
    db_tables = set(insp.get_table_names())
    missing_tables = []
    missing_columns = []   # (table, column, ddl_type, nullable)

    for table in db.metadata.sorted_tables:
        if table.name not in db_tables:
            missing_tables.append(table.name)
            continue
        have = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in have:
                continue
            ddl_type = col.type.compile(db.engine.dialect)
            missing_columns.append((table.name, col.name, ddl_type, col.nullable))
    return missing_tables, missing_columns


def unused_columns(insp):
    """DBにだけ残っている列(無害だが参考表示)。"""
    result = []
    db_tables = set(insp.get_table_names())
    for table in db.metadata.sorted_tables:
        if table.name not in db_tables:
            continue
        have = {c["name"] for c in insp.get_columns(table.name)}
        want = {c.name for c in table.columns}
        for name in sorted(have - want):
            result.append((table.name, name))
    return result


def _migrate_target_app(path):
    """対象DB用のアプリを用意する。

    Flask-SQLAlchemy は init_app 時に接続先を確定するため、あとから
    SQLALCHEMY_DATABASE_URI を書き換えても効かない。--db 指定時は
    専用のアプリを組み立てて、既定のDB(instance/app.db)には一切触れない。
    """
    if not path:
        # 通常はアプリ本体(= instance/app.db)を対象にする
        app = current_app._get_current_object()
        prepare_instance(app)
        return app

    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///{}".format(
        os.path.abspath(path)
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    with app.app_context():
        db.create_all()  # 指定DBに対して不足テーブルを作成
    return app


@click.command("migrate")
@click.option("--check", "check_only", is_flag=True, help="確認のみ(DBを変更しない)。")
@click.option("--db", "db_path", metavar="PATH", help="instance/app.db 以外のDBを対象にする。")
@with_appcontext
def migrate_command(check_only, db_path):
    """既存DBを最新のモデル定義に合わせる(不足しているテーブル・列を追加する)。"""
    app = _migrate_target_app(db_path)

    with app.app_context():
        print("対象DB:", db.engine.url)  # 実際に接続しているDBを表示する
        insp = inspect(db.engine)
        missing_tables, missing_columns = collect_changes(insp)

        # create_all 済みなので、ここで残っている missing_tables は基本無いはず
        if missing_tables:
            print("作成されたテーブル:", ", ".join(missing_tables))

        if not missing_columns:
            print("不足している列はありません。DBは最新の状態です。")
        else:
            print("不足している列: {} 件".format(len(missing_columns)))
            for table, col, ddl_type, nullable in missing_columns:
                print("  - {}.{} ({})".format(table, col, ddl_type))

            if check_only:
                print("\n--check のため変更していません。"
                      "実行するには: flask --app app migrate")
                return

            added, skipped = 0, []
            for table, col, ddl_type, nullable in missing_columns:
                if not nullable:
                    # SQLiteは NOT NULL 列を後から追加できない(既定値が必要)
                    skipped.append("{}.{}".format(table, col))
                    continue
                with db.engine.begin() as conn:
                    conn.execute(text(
                        'ALTER TABLE "{}" ADD COLUMN "{}" {}'.format(table, col, ddl_type)
                    ))
                added += 1
                print("  追加: {}.{}".format(table, col))
            print("列を {} 件追加しました。".format(added))
            if skipped:
                print("★手動対応が必要(NOT NULL列のため自動追加不可):",
                      ", ".join(skipped))

        extras = unused_columns(insp)
        if extras:
            print("\n参考: DBにだけ残る未使用列(読み書きしないので無害)")
            for table, col in extras:
                print("  - {}.{}".format(table, col))

        # 最終確認
        insp2 = inspect(db.engine)
        _, still_missing = collect_changes(insp2)
        print("\n結果:", "OK（モデル定義と一致しました）" if not still_missing
              else "★まだ不足があります: {}".format(still_missing))
