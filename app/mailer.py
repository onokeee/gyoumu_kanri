"""メール送信(SMTP)の共通部品。週報・期限超過通知など、どの機能からも使う。

送信サーバー・差出人・宛先・認証情報はすべて instance/config.py に記入する
(MAIL_SMTP_SERVER / MAIL_SMTP_PORT / MAIL_USE_TLS / MAIL_USERNAME / MAIL_PASSWORD /
 MAIL_FROM / MAIL_TO / MAIL_CC / MAIL_TEST_TO)。画面からは変更できない。

send(subject, text, html=None, attachments=(), to=None, cc=None, test=False):
  text        : 本文(text/plain・UTF-8)
  html        : HTML版の本文。指定すると multipart/alternative(テキスト版＋HTML版)で送る
                (HTMLを表示できないメールソフトではテキスト版が表示される)
  attachments : 添付ファイル [(ファイル名, データ(bytes), maintype, subtype), ...]。
                指定すると multipart/mixed にして本文の後ろに添付する。
                日本語のファイル名は RFC 2231 の形式(filename*=utf-8''...)で付ける
  to / cc     : 本番の宛先の一覧。None なら MAIL_TO / MAIL_CC
  test        : True ならテスト送信。MAIL_TEST_TO(空なら差出人 MAIL_FROM)だけに送り、
                to / cc は使わない(Cc なし)
  戻り値      : (成功したか, メッセージ)

送信方法は一般的な smtplib の手順どおり:
  Date・Message-ID を付け、SMTP(必要なら STARTTLS・認証)で To＋Cc に送る。
  STARTTLS ではサーバー証明書とホスト名を検証する(検証できなければ送信しない)。
パスワードは画面・ログ・メッセージのどこにも表示しない。
"""
import smtplib
import socket
import ssl
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid, parseaddr

from flask import current_app

SMTP_TIMEOUT = 20


def addresses(value):
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


def settings():
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
        "to": addresses(config.get("MAIL_TO")),
        "cc": addresses(config.get("MAIL_CC")),
        "test_to": addresses(config.get("MAIL_TEST_TO")),
    }


def recipients(test=False, to=None, cc=None):
    """宛先 (To, Cc)。

    テスト送信は MAIL_TEST_TO(空なら差出人)宛てで Cc なし(to / cc は使わない)。
    本番送信は to / cc(None なら MAIL_TO / MAIL_CC)。
    """
    values = settings()
    if test:
        test_to = values["test_to"] or ([values["mail_from"]] if values["mail_from"] else [])
        return test_to, []
    to = values["to"] if to is None else addresses(to)
    cc = values["cc"] if cc is None else addresses(cc)
    return to, cc


def check(test=False, to=None, to_label="宛先（MAIL_TO）"):
    """送信に必要な設定が揃っているか。問題があればその説明、無ければ None。

    to       : 本番送信の宛先(None なら MAIL_TO)。テスト送信では使わない
    to_label : 本番の宛先が空のときに示す設定項目の名前
    """
    values = settings()
    actual_to, _cc = recipients(test, to=to)
    missing = []
    if not values["server"]:
        missing.append("送信サーバー（MAIL_SMTP_SERVER）")
    if not values["mail_from"]:
        missing.append("差出人（MAIL_FROM）")
    if not actual_to:
        missing.append("テスト送信の宛先（MAIL_TEST_TO または MAIL_FROM）" if test else to_label)
    if missing:
        return "メールの設定が不足しています: {}。instance/config.py に記入してサーバーを再起動してください。".format(
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


def send(subject, text, html=None, attachments=(), to=None, cc=None, test=False):
    """メールを送る。

    戻り値: (成功したか, メッセージ)
    一部の宛先だけ拒否された場合は失敗扱いにし、メッセージで拒否された宛先を示す。
    """
    problem = check(test, to=to)
    if problem:
        return False, problem

    values = settings()
    password = str(current_app.config.get("MAIL_PASSWORD") or "")
    mail_from = values["mail_from"]
    to, cc = recipients(test, to=to, cc=cc)

    msg = _build_message(subject, text, html, attachments)
    msg["From"] = mail_from
    msg["To"] = ",".join(to)
    if cc:
        msg["Cc"] = ",".join(cc)
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
