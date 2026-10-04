"""週報(自動作成・メール送信)パッケージ。マネージャーのみ。

タスク情報(タスク・進捗記載・ステータス変更・成果・負荷)から、
チーム全体＋1人1ページの週報をWordで作り、メールで送る。DBには何も保存しない。

  routes.py         週報の画面と「今すぐ作成」(Blueprint: weekly_bp, /weekly)
  settings_form.py  設定フォームの入力チェック(システム設定の「週報」タブで使う)
  settings_store.py 画面で編集する設定(instance/weekly_settings.json)
  rules.py          期間・次回実行日時・ファイル名/件名の差し込み(純粋関数)
  collector.py      材料の収集とチーム全体の集計(数値はすべてコードで計算)
  writer.py         文章づくり(AI整形。使えない部分はルールベース)
  docx_builder.py   Word(.docx)の作成
  service.py        作成〜送信のとりまとめ(run_weekly)

アプリ共通の部品を使う:
  app/ai_client.py  ChatGPT(OpenAI互換)API の接続(差し替えポイント)
  app/mailer.py     メール送信(SMTP)
  app/scheduler.py  自動送信のスケジューラ(週報・期限超過通知。serve.py からだけ起動)

接続設定(メール・AI)はすべて instance/config.py から読み込む(システム設定の「基本設定」タブで変更)。
"""
