/* ManaDwar v9 - shared front-end pieces: language, notifications bell, sound/speech at the gate,
   silent session refresh, invite sign-up, account page, complaint thread dialog.
   Loaded after app.js, which exposes window.MD. */
(function () {
  "use strict";
  var MD = window.MD;
  var $ = MD.$, esc = MD.esc;

  // ------------------------------------------------------------------ language
  // Core screens only. Hindi/Telugu text is a first draft: have a native speaker review it.
  var I18N = {
    en: { home: "Home", visitors: "Visitors", deliveries: "Deliveries", complaints: "Complaints", notices: "Notices", myFlat: "My Flat", account: "Account",
      gate: "Gate", today: "Today", sos: "SOS", staff: "Staff", people: "People", logs: "Logs", dashboard: "Dashboard", attendance: "Attendance",
      signOut: "Sign out", haveInvite: "Have an invite code? Create your account", signIn: "Sign in", notifications: "Notifications",
      markAllRead: "Mark all read", noNotifications: "Nothing new.", language: "Language", sound: "Sound", changePassword: "Change password",
      sosHelp: "Emergency? Tell the gate now.", sendSos: "Send SOS", welcome: "Welcome" },
    hi: { home: "होम", visitors: "आगंतुक", deliveries: "डिलीवरी", complaints: "शिकायतें", notices: "सूचनाएँ", myFlat: "मेरा फ़्लैट", account: "खाता",
      gate: "गेट", today: "आज", sos: "आपात", staff: "स्टाफ़", people: "लोग", logs: "लॉग", dashboard: "डैशबोर्ड", attendance: "उपस्थिति",
      signOut: "साइन आउट", haveInvite: "इन्वाइट कोड है? अपना खाता बनाएँ", signIn: "साइन इन", notifications: "सूचनाएँ",
      markAllRead: "सभी पढ़ा हुआ करें", noNotifications: "कुछ नया नहीं।", language: "भाषा", sound: "आवाज़", changePassword: "पासवर्ड बदलें",
      sosHelp: "आपातकाल? अभी गेट को बताएँ।", sendSos: "SOS भेजें", welcome: "स्वागत है" },
    te: { home: "హోమ్", visitors: "సందర్శకులు", deliveries: "డెలివరీలు", complaints: "ఫిర్యాదులు", notices: "నోటీసులు", myFlat: "నా ఫ్లాట్", account: "ఖాతా",
      gate: "గేట్", today: "ఈరోజు", sos: "అత్యవసరం", staff: "సిబ్బంది", people: "వ్యక్తులు", logs: "లాగ్‌లు", dashboard: "డాష్‌బోర్డ్", attendance: "హాజరు",
      signOut: "సైన్ అవుట్", haveInvite: "ఆహ్వాన కోడ్ ఉందా? మీ ఖాతాను సృష్టించండి", signIn: "సైన్ ఇన్", notifications: "నోటిఫికేషన్లు",
      markAllRead: "అన్నీ చదివినట్లు గుర్తించండి", noNotifications: "కొత్తది ఏమీ లేదు.", language: "భాష", sound: "ధ్వని", changePassword: "పాస్‌వర్డ్ మార్చండి",
      sosHelp: "అత్యవసరమా? ఇప్పుడే గేట్‌కు చెప్పండి.", sendSos: "SOS పంపండి", welcome: "స్వాగతం" },
  };
  var LANG_KEY = "manadwar_lang";
  var lang = MD.storeGet(LANG_KEY) || "en";
  if (!I18N[lang]) lang = "en";
  function t(key) { return (I18N[lang] && I18N[lang][key]) || I18N.en[key] || key; }
  MD.t = t;
  MD.lang = function () { return lang; };
  function applyLang() {
    document.documentElement.lang = lang;
    document.querySelectorAll("[data-i18n]").forEach(function (el) { el.textContent = t(el.getAttribute("data-i18n")); });
    var out = $("btn-logout"); if (out) out.textContent = t("signOut");
    var map = { "rtab-home": "home", "rtab-visitors": "visitors", "rtab-deliveries": "deliveries", "rtab-complaints": "complaints", "rtab-flat": "myFlat", "rtab-account": "account" };
    Object.keys(map).forEach(function (id) { var el = $(id); if (el) el.firstChild.textContent = t(map[id]) + (id === "rtab-notices" ? " " : ""); });
    var n = $("rtab-notices"); if (n && n.firstChild) n.firstChild.textContent = t("notices") + " ";
    document.dispatchEvent(new CustomEvent("md:lang"));
  }
  MD.setLang = function (l) { if (!I18N[l]) return; lang = l; MD.storeSet(LANG_KEY, l); applyLang(); };

  // ------------------------------------------------------------------ small helpers
  MD.fmtDay = function (ts) { var d = MD.parseUTC(ts); return d ? d.toLocaleDateString() : "—"; };
  MD.relTime = function (ts) {
    var d = MD.parseUTC(ts); if (!d) return "";
    var s = Math.round((Date.now() - d.getTime()) / 1000);
    if (s < 45) return "just now"; if (s < 3600) return Math.round(s / 60) + " min ago";
    if (s < 86400) return Math.round(s / 3600) + " h ago"; return d.toLocaleDateString();
  };
  MD.modal = function (html, onClose) {
    var wrap = document.createElement("div");
    wrap.className = "modal";
    wrap.innerHTML = '<div class="modal-card">' + html + "</div>";
    function close() { wrap.remove(); if (onClose) onClose(); }
    wrap.addEventListener("click", function (ev) { if (ev.target === wrap) close(); });
    document.body.appendChild(wrap);
    wrap.close = close;
    return wrap;
  };
  MD.downloadAuthed = async function (url, filename) {
    try {
      var res = await fetch(url, { headers: { "Authorization": "Bearer " + MD.getToken() } });
      if (!res.ok) { alert("Could not download the file."); return; }
      var blob = await res.blob();
      var a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = filename;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(function () { URL.revokeObjectURL(a.href); }, 2000);
    } catch (e) { alert("Could not download the file."); }
  };
  MD.pickPhoto = function (onFile, capture) {
    var input = document.createElement("input");
    input.type = "file"; input.accept = "image/jpeg,image/png,image/webp";
    if (capture) input.setAttribute("capture", capture);
    input.addEventListener("change", function () { if (input.files && input.files[0]) onFile(input.files[0]); });
    input.click();
  };
  MD.uploadPhoto = async function (url, file) {
    if (file.size > 5 * 1024 * 1024) { alert("That photo is over 5 MB. Please use a smaller one."); return null; }
    var fd = new FormData(); fd.append("file", file);
    var r = await MD.postForm(url, fd);
    if (!r.ok) { alert("Could not upload the photo: " + r.error); return null; }
    return r.data;
  };

  // ------------------------------------------------------------------ gate sound, speech, vibration
  var SOUND_KEY = "manadwar_sound";
  var audioCtx = null;
  function soundOn() { return MD.storeGet(SOUND_KEY) !== "off"; }
  function beep(freq, ms, when, type, gain) {
    try {
      audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
      var o = audioCtx.createOscillator(), g = audioCtx.createGain();
      o.type = type || "sine"; o.frequency.value = freq;
      g.gain.value = gain || 0.18;
      o.connect(g); g.connect(audioCtx.destination);
      var t0 = audioCtx.currentTime + (when || 0);
      o.start(t0); o.stop(t0 + ms / 1000);
    } catch (e) { /* audio blocked: silent */ }
  }
  MD.sounds = {
    granted: function () { beep(880, 120, 0); beep(1320, 180, 0.14); },
    denied: function () { beep(220, 260, 0, "square", 0.2); beep(180, 320, 0.3, "square", 0.2); },
    alarm: function () { for (var i = 0; i < 4; i++) { beep(980, 180, i * 0.4, "square", 0.25); beep(660, 180, i * 0.4 + 0.2, "square", 0.25); } },
  };
  function speak(text) {
    try {
      if (!window.speechSynthesis) return;
      window.speechSynthesis.cancel();
      var u = new SpeechSynthesisUtterance(text);
      u.lang = lang === "hi" ? "hi-IN" : lang === "te" ? "te-IN" : "en-IN";
      u.rate = 1;
      window.speechSynthesis.speak(u);
    } catch (e) { /* ignore */ }
  }
  MD.speak = speak;
  MD.onStatus = function (state, message, detail) {
    var u = MD.user();
    if (!u || (u.role !== "GUARD" && u.role !== "ADMIN") || !soundOn()) return;
    if (state === "granted") {
      MD.sounds.granted();
      if (navigator.vibrate) try { navigator.vibrate(120); } catch (e) { /* ignore */ }
      speak("Access granted. " + (detail || "").split(" — ")[0]);
    } else if (state === "denied") {
      MD.sounds.denied();
      if (navigator.vibrate) try { navigator.vibrate([250, 100, 250]); } catch (e) { /* ignore */ }
      speak("Access denied.");
    }
  };

  // ------------------------------------------------------------------ header tools: language, sound, bell
  var bellTimer = null, panel = null, lastUnread = null;
  function buildHeaderTools() {
    var tools = $("header-tools");
    var u = MD.user();
    var langSel = '<select id="lang-select" aria-label="Language"><option value="en">English</option><option value="hi">हिन्दी</option><option value="te">తెలుగు</option></select>';
    var sound = (u.role === "GUARD" || u.role === "ADMIN") ? '<button class="icon-btn" id="btn-sound" title="Gate sound and voice" aria-label="Gate sound and voice"></button>' : "";
    tools.innerHTML = langSel + sound + '<button class="icon-btn" id="btn-bell" aria-label="Notifications" title="Notifications">🔔<span class="dot hidden" id="bell-dot"></span></button>';
    $("lang-select").value = lang;
    $("lang-select").addEventListener("change", function () { MD.setLang(this.value); });
    if ($("btn-sound")) {
      var paint = function () { $("btn-sound").textContent = soundOn() ? "🔊" : "🔇"; };
      paint();
      $("btn-sound").addEventListener("click", function () {
        MD.storeSet(SOUND_KEY, soundOn() ? "off" : "on"); paint();
        if (soundOn()) MD.sounds.granted();   // a tap also unlocks audio on phones
      });
    }
    $("btn-bell").addEventListener("click", toggleBell);
  }

  function setUnread(n) {
    var dot = $("bell-dot"); if (!dot) return;
    dot.textContent = n > 99 ? "99+" : String(n);
    dot.classList.toggle("hidden", !n);
    document.title = (n ? "(" + n + ") " : "") + "ManaDwar — Gate Access Terminal";
    lastUnread = n;
  }
  async function pollUnread() {
    var r = await MD.getJSON("/notifications/unread-count");
    if (r.ok) {
      if (lastUnread !== null && r.data.unread > lastUnread) document.dispatchEvent(new CustomEvent("md:notify-new", { detail: r.data.unread - lastUnread }));
      setUnread(r.data.unread);
    }
  }
  async function toggleBell() {
    if (panel) { panel.remove(); panel = null; return; }
    panel = document.createElement("div");
    panel.className = "notif-panel";
    panel.innerHTML = '<div style="display:flex;justify-content:space-between;align-items:center;gap:8px;"><strong>' + esc(t("notifications")) +
      '</strong><button class="link-btn" id="btn-read-all">' + esc(t("markAllRead")) + '</button></div><div id="notif-list" class="muted" style="margin-top:8px;">…</div>';
    document.body.appendChild(panel);
    $("btn-read-all").addEventListener("click", async function () { await MD.postJSON("/notifications/read-all"); await loadNotifs(); pollUnread(); });
    await loadNotifs();
  }
  async function loadNotifs() {
    var box = $("notif-list"); if (!box) return;
    var r = await MD.getJSON("/notifications?limit=30");
    if (!r.ok) { box.textContent = r.error; return; }
    if (!r.data.length) { box.textContent = t("noNotifications"); return; }
    box.innerHTML = r.data.map(function (n) {
      return '<div class="notif-item ' + (n.read_at ? "" : "unread") + '" data-id="' + Number(n.id) + '"><strong>' + esc(n.title) + "</strong>" +
        (n.body ? "<div>" + esc(n.body) + "</div>" : "") + "<small>" + esc(MD.relTime(n.created_at)) + "</small></div>";
    }).join("");
    box.querySelectorAll(".notif-item.unread").forEach(function (el) {
      el.addEventListener("click", async function () { await MD.postJSON("/notifications/" + el.getAttribute("data-id") + "/read"); el.classList.remove("unread"); pollUnread(); });
    });
  }
  document.addEventListener("click", function (ev) {
    if (panel && !panel.contains(ev.target) && !ev.target.closest("#btn-bell")) { panel.remove(); panel = null; }
  });

  // ------------------------------------------------------------------ silent session refresh
  async function refreshToken() {
    if (!MD.getToken()) return;
    var r = await MD.postJSON("/auth/refresh");
    if (r.ok && r.data && r.data.access_token) MD.setToken(r.data.access_token);
  }

  // ------------------------------------------------------------------ account page (all roles)
  MD.renderAccount = function (root) {
    var u = MD.user();
    root.innerHTML =
      '<h3 class="section-title">' + esc(u.name) + ' <span class="role-pill">' + esc(u.role) + "</span></h3>" +
      '<p class="note-text">' + esc(u.email) + (u.apartment_no ? " · Apartment " + esc(u.apartment_no) : "") +
        (u.last_login_at ? " · Last sign-in " + esc(MD.fmtTime(u.last_login_at)) : "") + "</p>" +
      '<h3 class="section-title" style="margin-top:20px;">' + esc(t("changePassword")) + "</h3>" +
      '<div style="max-width:420px;"><label for="acc-cur">Current password</label><input type="password" id="acc-cur" autocomplete="current-password" />' +
      '<label for="acc-new">New password (8+ characters, a letter and a number)</label><input type="password" id="acc-new" autocomplete="new-password" />' +
      '<label for="acc-new2">Repeat new password</label><input type="password" id="acc-new2" autocomplete="new-password" />' +
      '<button class="action" id="acc-save">' + esc(t("changePassword")) + '</button><div class="error-text" id="acc-msg"></div></div>' +
      '<p class="note-text" style="margin-top:18px;">Other devices where you are signed in will be asked to sign in again after you change your password.</p>';
    $("acc-save").addEventListener("click", async function () {
      var msg = $("acc-msg"); msg.style.color = ""; msg.textContent = "";
      if ($("acc-new").value !== $("acc-new2").value) { msg.textContent = "The new passwords do not match."; return; }
      var r = await MD.postJSON("/auth/change-password", { current_password: $("acc-cur").value, new_password: $("acc-new").value });
      if (!r.ok) { msg.textContent = r.error; return; }
      MD.setToken(r.data.access_token);
      u.must_change_password = false; var b = $("pw-banner"); if (b) b.remove();
      $("acc-cur").value = $("acc-new").value = $("acc-new2").value = "";
      msg.style.color = "var(--granted)"; msg.textContent = "Password changed.";
    });
  };

  // ------------------------------------------------------------------ complaint conversation dialog
  MD.openThread = async function (id, isAdmin, onChange) {
    var m = MD.modal('<div id="th-body">Loading…</div>', onChange);
    async function render() {
      var res = await Promise.all([MD.getJSON("/complaints/" + id + "/comments"), MD.getJSON("/complaints")]);
      var comments = res[0], all = res[1];
      var c = all.ok ? all.data.find(function (x) { return x.id === id; }) : null;
      var body = m.querySelector("#th-body");
      if (!comments.ok || !c) { body.textContent = comments.error || "Could not load."; return; }
      body.innerHTML = '<h3 class="section-title">Complaint #' + id + " " + MD.badge(c.status) + "</h3>" +
        '<p style="margin:0 0 6px;">' + esc(c.description) + "</p>" +
        (c.assigned_to ? '<p class="note-text">Assigned to ' + esc(c.assigned_to) + "</p>" : "") +
        '<div class="thread">' + (comments.data.length ? comments.data.map(function (x) {
          return '<div class="msg ' + (x.author_role === "ADMIN" ? "admin" : "") + '"><small>' + esc(x.author_name) + " · " + esc(x.author_role) + " · " + esc(MD.relTime(x.created_at)) + "</small>" + esc(x.body) + "</div>";
        }).join("") : '<p class="note-text">No messages yet.</p>') + "</div>" +
        '<textarea id="th-text" rows="2" maxlength="1000" placeholder="Write a message"></textarea>' +
        '<div class="row-actions" style="margin-top:8px;"><button class="approve" id="th-send">Send</button><button id="th-close">Close</button></div>' +
        (isAdmin && c.status !== "RESOLVED" ? '<h3 class="section-title" style="margin-top:16px;font-size:0.95rem;">Assign</h3><div class="row-actions"><input id="th-assign" placeholder="Name, e.g. Ramesh (plumber)" maxlength="80" /><button id="th-assign-btn">Assign</button></div>' : "") +
        '<div class="error-text" id="th-err"></div>';
      body.querySelector("#th-close").addEventListener("click", function () { m.close(); });
      body.querySelector("#th-send").addEventListener("click", async function () {
        var text = body.querySelector("#th-text").value.trim(); if (!text) return;
        var r = await MD.postJSON("/complaints/" + id + "/comments", { body: text });
        if (!r.ok) { body.querySelector("#th-err").textContent = r.error; return; }
        render();
      });
      var ab = body.querySelector("#th-assign-btn");
      if (ab) ab.addEventListener("click", async function () {
        var who = body.querySelector("#th-assign").value.trim(); if (!who) return;
        var r = await MD.postJSON("/complaints/" + id + "/assign", { assigned_to: who });
        if (!r.ok) { body.querySelector("#th-err").textContent = r.error; return; }
        render();
      });
    }
    render();
  };

  // ------------------------------------------------------------------ login screen: invite sign-up
  $("link-register").addEventListener("click", function () { document.querySelector("#login-view .login-card").classList.add("hidden"); $("register-card").classList.remove("hidden"); });
  $("link-login").addEventListener("click", function () { $("register-card").classList.add("hidden"); document.querySelector("#login-view .login-card").classList.remove("hidden"); });
  $("register-form").addEventListener("submit", async function (ev) {
    ev.preventDefault();
    var err = $("register-error"); err.textContent = "";
    var email = $("reg-email").value.trim(), pass = $("reg-pass").value;
    var r = await MD.postJSON("/auth/register", { invite_code: $("reg-code").value.trim(), name: $("reg-fullname").value.trim(), email: email, password: pass });
    if (!r.ok) { err.textContent = r.error; return; }
    // account made: sign straight in
    var form = new URLSearchParams(); form.set("username", email); form.set("password", pass);
    var res = await fetch("/auth/login", { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: form.toString() });
    if (res.ok) { var d = await res.json(); MD.setToken(d.access_token); window.location.reload(); }
    else { $("register-card").classList.add("hidden"); document.querySelector("#login-view .login-card").classList.remove("hidden"); $("login-error").textContent = "Account created. Please sign in."; }
  });

  // ------------------------------------------------------------------ on sign-in
  document.addEventListener("md:ready", function () {
    var u = MD.user();
    buildHeaderTools();
    applyLang();
    pollUnread();
    if (bellTimer) clearInterval(bellTimer);
    bellTimer = setInterval(function () { if (!document.hidden) pollUnread(); }, 20000);
    setInterval(refreshToken, 10 * 60 * 1000);
    document.addEventListener("visibilitychange", function () { if (!document.hidden) { pollUnread(); refreshToken(); } });
    if (u.must_change_password) {
      var b = document.createElement("div");
      b.className = "banner"; b.id = "pw-banner";
      b.innerHTML = "You are using a temporary password. <button class=\"link-btn\" id=\"pw-banner-go\">Choose your own password now</button>";
      $("ext-banners").appendChild(b);
      $("pw-banner-go").addEventListener("click", function () { document.dispatchEvent(new CustomEvent("md:goto-account")); });
    }
  });
  applyLang();
})();
