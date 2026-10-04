"""期限超過通知(毎朝のメール)パッケージ。マネージャーのみ。

営業日(土日・祝日以外)の毎朝、指定の時刻に「期限を過ぎた未完了タスク」の一覧を
1通のメールで送る。一覧は状態(未着手／進行中・保留)ごと、担当者ごとにまとめ、
各タスクには直近の進捗記載(コメント)とタスク詳細画面へのリンクを付ける。
DBは読み取りのみ(何も保存しない)。

  routes.py         画面・プレビュー・今すぐ送信(Blueprint: overdue_bp, /overdue)
  settings_form.py  設定フォームの入力チェック(システム設定の「期限超過通知」タブで使う)
  settings_store.py 画面で編集する設定と前回の結果(instance/overdue_settings.json)
  rules.py          自動送信の実行時刻の判定・次回の送信日時(純粋関数)
  content.py        期限超過タスクの収集とメール本文(テキスト版・HTML版)・件名の作成
  service.py        作成〜送信のとりまとめ(run_overdue・start_background)

アプリ共通の部品を使う:
  app/mailer.py     メール送信(SMTP)
  app/holidays.py   営業日カレンダー(土日・日本の祝日)
  app/scheduler.py  自動送信のスケジューラ(週報・期限超過通知。serve.py からだけ起動)

メールの送信サーバー・宛先・リンクの基準URL(APP_BASE_URL)は instance/config.py から読み込む
(システム設定の「基本設定」タブで変更)。
"""
