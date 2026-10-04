"""週報の「期間・次回実行日時・ファイル名/件名」のルール(純粋関数のみ)。

DBにもFlaskにも依存しないため、画面・スケジューラ・作成処理のどこからでも使える。

期間のルール(画面で選択):
  prev7 : 送信日の前日までの7日間(既定)。例: 送信日が月曜 → 前週の月曜〜日曜
  incl7 : 送信日を含む7日間。          例: 送信日が金曜 → 前週の土曜〜当日の金曜
          ※自動送信では、送信日の送信時刻より後に記録した内容は、どの週報にも載らない
           (次回の期間は送信日の翌日から始まるため)。漏れなく載せたい場合は prev7 を使う

ファイル名・件名・メール本文で使える差し込み記号:
  {開始日} {終了日} {送信日} : yyyymmdd
  {年} {月}                  : 期間の終了日の西暦年(4桁)・月(2桁)
  {週}                       : 期間の終了日のISO週番号(2桁)
  {週の年}                   : {週} の属する年(ISO週の年。年末年始は {年} と異なることがある)
  {期間}                     : yyyy/mm/dd〜yyyy/mm/dd(ファイル名では / を - に置き換える)
"""
import re
from datetime import datetime, time, timedelta

from app.utils import parse_hhmm

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
_LINE_BREAKS = re.compile(r"[\r\n\t\x0b\x0c]+")
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


def next_run(settings, now):
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


def build_filename(pattern, start, end, send_date):
    """ファイル名のパターンから、実際のファイル名を作る。"""
    return safe_filename(render_pattern(pattern, start, end, send_date, for_filename=True))


def build_subject(pattern, start, end, send_date):
    """件名のパターンから、実際の件名を作る(改行・タブは空白にする)。"""
    text = render_pattern(pattern, start, end, send_date)
    return _LINE_BREAKS.sub(" ", text).strip() or "週報"
