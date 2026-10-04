/* システム設定の画面(system/settings.html)用。
 *
 * ・開いているタブを URL(?tab=...)に残す(再読み込み・ブックマークでも同じタブを開く)。
 *   #weekly のような URL の末尾(フラグメント)でもタブを指定できる。
 * ・基本設定で admin のパスワードを空にする・新しい SECRET_KEY を生成するときは、保存前に確認する。
 *
 * JavaScript が無効でも、タブは ?tab= のリンクとして動き、保存もできる。
 */
(function () {
  "use strict";

  function setupTabs() {
    var links = document.querySelectorAll("#system-tabs [data-tab]");
    if (!links.length) return;

    links.forEach(function (link) {
      link.addEventListener("shown.bs.tab", function () {
        if (!window.history || !window.history.replaceState) return;
        // タブのリンク先(/system/settings?tab=...)にする。保存エラーの再表示は保存用の URL
        // (POST 専用)で表示されるため、今の URL のパスは使わない(再読み込みで 405 になる)
        window.history.replaceState(null, "", link.getAttribute("href"));
      });
    });

    // #weekly / #pane-weekly / #tab-weekly で開いた場合はそのタブを表示する
    var wanted = (window.location.hash || "").replace(/^#(pane-|tab-)?/, "");
    if (!wanted || !window.bootstrap) return;
    links.forEach(function (link) {
      if (link.getAttribute("data-tab") === wanted) {
        window.bootstrap.Tab.getOrCreateInstance(link).show();
      }
    });
  }

  function setupConfirm() {
    var form = document.getElementById("config-form");
    if (!form) return;
    form.addEventListener("submit", function (event) {
      var messages = [];
      var clearAdmin = form.elements["clear_ADMIN_PASSWORD"];
      var generateKey = form.elements["generate_SECRET_KEY"];
      if (clearAdmin && clearAdmin.checked) {
        messages.push("admin のパスワードを空にします（admin のログイン可否は app/auth/ldap_client.py の判定に任されます）。");
      }
      if (generateKey && generateKey.checked) {
        messages.push("新しい SECRET_KEY を生成します（サーバーの再起動後に有効になり、そのとき全員がログアウトされます）。");
      }
      if (messages.length && !window.confirm(messages.join("\n") + "\nよろしいですか？")) {
        event.preventDefault();
      }
    });
  }

  function init() {
    setupTabs();
    setupConfirm();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
