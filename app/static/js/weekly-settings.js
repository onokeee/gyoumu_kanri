/* 週報の設定画面(weekly/settings.html)用。
 *
 * ・対象者の「全員選択」「全解除」ボタンと、選択人数の表示
 * ・ファイル名・件名のプレビュー更新
 *   入力中のパターンをサーバー(/weekly/preview)に送り、今日作成した場合の
 *   ファイル名・件名を表示する(差し込み・ファイル名の整形はサーバー側と同じ処理)。
 *
 * JavaScript が無効でも設定の保存はでき、プレビューは保存後の画面に表示される。
 */
(function () {
  "use strict";

  function setupTargets() {
    var boxes = document.querySelectorAll("input[name='target_user_ids']");
    var counter = document.getElementById("target-count");

    function updateCount() {
      if (!counter) return;
      var n = 0;
      boxes.forEach(function (cb) { if (cb.checked) n += 1; });
      counter.textContent = n;
    }

    document.querySelectorAll("[data-check-all]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var checked = btn.getAttribute("data-check-all") === "1";
        boxes.forEach(function (cb) { cb.checked = checked; });
        updateCount();
      });
    });
    boxes.forEach(function (cb) { cb.addEventListener("change", updateCount); });
  }

  function setupPreview() {
    var form = document.getElementById("weekly-settings-form");
    if (!form || !window.fetch) return;
    var url = form.getAttribute("data-preview-url");
    var targets = {
      filename: document.getElementById("preview-filename"),
      subject: document.getElementById("preview-subject"),
      period: document.getElementById("preview-period")
    };
    var timer = null;

    function refresh() {
      var params = new URLSearchParams();
      params.set("filename_pattern", form.elements["filename_pattern"].value);
      params.set("subject_pattern", form.elements["subject_pattern"].value);
      var rule = form.querySelector("input[name='period_rule']:checked");
      if (rule) params.set("period_rule", rule.value);

      fetch(url + "?" + params.toString(), { credentials: "same-origin" })
        .then(function (res) { return res.ok ? res.json() : null; })
        .then(function (data) {
          if (!data) return;
          Object.keys(targets).forEach(function (key) {
            if (targets[key] && typeof data[key] === "string") {
              targets[key].textContent = data[key];
            }
          });
        })
        .catch(function () { /* プレビューが更新できなくても保存には影響しない */ });
    }

    function schedule() {
      clearTimeout(timer);
      timer = setTimeout(refresh, 300);
    }

    ["filename_pattern", "subject_pattern"].forEach(function (name) {
      form.elements[name].addEventListener("input", schedule);
    });
    form.querySelectorAll("input[name='period_rule']").forEach(function (el) {
      el.addEventListener("change", schedule);
    });
  }

  function init() {
    setupTargets();
    setupPreview();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
