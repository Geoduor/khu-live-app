(function () {
  var APP_URL = "https://khu-live-app.vercel.app";
  var PAGE_URL = APP_URL + "/install.html";
  var ua = navigator.userAgent || "";
  var $ = function (id) { return document.getElementById(id); };

  var isIOS = /iPad|iPhone|iPod/.test(ua) || (ua.indexOf("Mac") > -1 && "ontouchend" in document);
  var isAndroid = /Android/i.test(ua);
  var inApp = /FBAN|FBAV|FB_IAB|Instagram|WhatsApp|musical_ly|TikTok|Line\/|Telegram|Twitter|; wv\)/i.test(ua);
  var standalone = (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) || window.navigator.standalone === true;

  // Show the card for THIS device first and highlight it.
  var current = isIOS ? "iosCard" : isAndroid ? "androidCard" : "desktopCard";
  var main = document.querySelector("main");
  main.style.display = "flex";
  main.style.flexDirection = "column";
  var order = { hero: 0, inapp: 1, installed: 1, apkCard: 4 };
  document.querySelector(".hero").style.order = order.hero;
  $("inapp").style.order = order.inapp;
  $("installed").style.order = order.installed;
  ["androidCard", "iosCard", "desktopCard"].forEach(function (id) {
    $(id).style.order = id === current ? "2" : "3";
  });
  $("apkCard").style.order = "4";
  document.querySelector(".share").style.order = "5";
  document.querySelector(".foot").style.order = "6";
  $(current).classList.add("current");

  if (standalone) $("installed").hidden = false;
  if (inApp) {
    $("inapp").hidden = false;
    $("inappBrowser").textContent = isIOS ? "Safari" : "Chrome";
  }

  // One-tap install on Android / desktop Chrome & Edge.
  var deferred = null;
  window.addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault();
    deferred = e;
    $("installBtn").hidden = false;
    $("installBtn").textContent = "📲 Install KHU Live";
  });
  $("installBtn").addEventListener("click", function () {
    if (!deferred) return;
    deferred.prompt();
    deferred.userChoice.then(function () { deferred = null; $("installBtn").hidden = true; });
  });

  // Share helpers
  var text = "Follow Kenya hockey live — scores, fixtures & tables. Install free: " + PAGE_URL;
  $("waBtn").href = "https://wa.me/?text=" + encodeURIComponent(text);
  function copy(btn) {
    var done = function () { var t = btn.textContent; btn.textContent = "Copied ✓"; setTimeout(function () { btn.textContent = t; }, 2200); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(PAGE_URL).then(done, function () { window.prompt("Copy this link:", PAGE_URL); });
    } else { window.prompt("Copy this link:", PAGE_URL); }
  }
  $("copyBtn").addEventListener("click", function () { copy($("copyBtn")); });
  $("copyBtnTop").addEventListener("click", function () { copy($("copyBtnTop")); });

  // Show the Android file section only once the .apk is actually uploaded.
  if (isAndroid || !isIOS) {
    fetch("/khu-live.apk", { method: "HEAD" }).then(function (r) {
      var type = r.headers.get("content-type") || "";
      if (r.ok && type.indexOf("text/html") === -1) $("apkCard").hidden = false;
    }).catch(function () {});
  }
})();
