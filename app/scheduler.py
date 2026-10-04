"""定期メールの自動送信スケジューラ(バックグラウンドのスレッド1本で、2つの仕事を確認する)。

約30秒ごとに、次の仕事(ジョブ)ごとに設定(instance/ のJSON)を読み、実行時刻なら1回だけ実行する。
  weekly  : 週報。自動送信が有効で、今の曜日・時刻(HH:MM)が設定と一致したとき
  overdue : 期限超過通知。自動送信が有効で、今日が営業日(土日・祝日以外)で、
            今の時刻(HH:MM)が設定と一致したとき

- 起動するのは serve.py だけ(create_app・run.py・seed.py・migrate.py からは起動しない)
- ジョブごとに、同じ (日付, 時刻) ではこのプロセスの中で1回しか実行しない(メモリ上の記録)
- サーバーが止まっていて実行時刻を過ぎた分は、後から実行しない(取りこぼしの再実行なし)
- 実行履歴はDBに残さない(結果は各機能の「前回の結果」に上書き)
- 実行はジョブごとに別のスレッドで行う(時間のかかる週報の作成中も、もう一方の
  ジョブの時刻の確認が止まらないようにするため)
- 例外はジョブごとに捕まえてそのジョブの「前回の結果」に書き、他のジョブ・スレッドは止めない
"""
import threading
from collections import namedtuple
from datetime import datetime

from app.overdue import rules as overdue_rules
from app.overdue import service as overdue_service
from app.overdue import settings_store as overdue_settings
from app.weekly import service as weekly_service
from app.weekly import settings_store as weekly_settings
from app.weekly.rules import period_for

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
    result = weekly_service.run_weekly(
        app, start, end, weekly_settings.TRIGGER_AUTO, weekly_service.DELIVER_SEND,
        send_date=now.date(),
    )
    return result["ok"]


def _weekly_failure(message):
    weekly_settings.set_last_result(weekly_settings.TRIGGER_AUTO, False, message)


# --------------------------------------------------------------------------- #
# 期限超過通知
# --------------------------------------------------------------------------- #
def _overdue_run(app, settings, now):
    result = overdue_service.run_overdue(
        app, overdue_settings.TRIGGER_AUTO, test=False, today=now.date())
    return result["ok"]


def _overdue_failure(message):
    overdue_settings.set_last_result(overdue_settings.TRIGGER_AUTO, False, message)


JOBS = (
    Job("weekly", "週報", weekly_settings.load, _weekly_due_key, _weekly_run, _weekly_failure),
    Job("overdue", "期限超過通知", overdue_settings.load, overdue_rules.due_key,
        _overdue_run, _overdue_failure),
)

_start_lock = threading.Lock()
_thread = None


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
    global _thread
    with _start_lock:
        if _thread is not None and _thread.is_alive():
            return _thread
        _thread = threading.Thread(
            target=_loop, args=(app, interval), name="mail-scheduler", daemon=True
        )
        _thread.start()
    app.logger.info("定期メール（週報・期限超過通知）の自動送信スケジューラを起動しました（%s秒ごとに確認）",
                    interval)
    return _thread
