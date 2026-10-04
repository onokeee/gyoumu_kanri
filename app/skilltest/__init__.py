"""スキルテスト(AIが作る4択問題でテクニカルスキルの到達度を確認し、自動で登録する)パッケージ。

メンバーが受験し、結果のレベルが今の到達度より高ければ skill_ratings に自動で登録する。
マネージャーは受験履歴(全問の内容・回答・所要時間・離脱回数)・問題プール・設定を管理する
(マネージャーはスキル管理の対象外のため受験しない)。

  routes.py         画面(Blueprint: skilltest_bp, /skilltest)。メンバー用と管理用(/skilltest/admin)
  service.py        受験の流れ(開始・出題・回答・離脱の記録・自動終了・採点・到達度の自動登録)
  generator.py      AIによる問題の作成と検証(app/ai_client.py の chat() を使用)
  pool.py           問題プールの集計と補充(バックグラウンド)
  settings_store.py 画面で編集する設定(instance/skilltest_settings.json)

DBには新しいテーブル(skill_test_questions / skill_test_attempts / skill_test_answers。
app/models/skilltest.py)だけを使い、既存のテーブルは変更しない
(到達度の自動登録で skill_ratings に行を追加・更新するだけ)。
"""
