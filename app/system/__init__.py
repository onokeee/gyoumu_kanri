"""システム設定(マネージャーのみ)。アプリのすべての設定を1つの画面(タブ)で変更する。

  routes.py         画面(Blueprint: system_bp, /system/settings)。タブ:
                      基本設定（config） : instance/config.py の環境ごとの設定
                      週報               : instance/weekly_settings.json
                      期限超過通知       : instance/overdue_settings.json
                      スキルテスト       : instance/skilltest_settings.json
  config_fields.py  基本設定の項目の定義(キー・グループ・表示名・説明・種類・再起動の要否・秘密か)。
                    項目の定義はこのファイルの1か所だけにある
  config_form.py    基本設定の入力チェック・保存(instance/config.py の書き換え)・画面表示用の値

週報・期限超過通知・スキルテストの入力チェックと表示用の値は、各機能の
settings_form.py にあり(保存先も各機能の settings_store.py のまま)、この画面から使う。
各機能の画面には、実行・状況の表示だけが残る(設定はこの画面へのリンク)。
"""
