/* ManaDwar v9 - resident portal additions: Home (+ SOS), Notices, My Flat, Account,
   regular visitors, delivery rules. */
(function () {
  "use strict";
  var MD = window.MD;
  var $ = MD.$, esc = MD.esc, t = MD.t;
  var DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

  // One tab handler for every resident tab (the original one only knew the first three).
  function showTab(btnId) {
    var card = $("resident-view");
    card.querySelectorAll(".tabs > .tab-btn").forEach(function (b) { b.classList.toggle("active", b.id === btnId); });
    var target = $(btnId).getAttribute("data-rpanel");
    card.querySelectorAll(".card > .panel").forEach(function (p) { p.classList.toggle("active", p.id === target); });
  }

  // ------------------------------------------------------------------ Home
  var homeTimer = null;
  async function loadHome() {
    var root = $("rpanel-home");
    var r = await MD.getJSON("/me/home");
    if (!r.ok) { root.innerHTML = '<p class="note-text">' + esc(r.error) + "</p>"; return; }
    var h = r.data, c = h.counts, u = MD.user();
    var tiles = [
      ["visitors_live", "Visitors now"], ["visitors_scheduled", "Scheduled"], ["deliveries_expected", "Deliveries expected"],
      ["complaints_open", "Open complaints"], ["notices_unread", "New notices"],
    ].map(function (x) { return '<div class="tile ' + (x[0] === "notices_unread" && c[x[0]] ? "warn" : "") + '"><b>' + Number(c[x[0]]) + "</b><span>" + x[1] + "</span></div>"; }).join("");

    var sos = h.sos_active
      ? '<div class="callout" style="border-color:var(--denied);background:var(--denied-dim);"><h3>SOS ' + esc(h.sos_active.kind) + " — " + esc(h.sos_active.status === "ACKNOWLEDGED" ? "the gate has seen it" : "sent, waiting for the gate") + '</h3><p class="note-text" style="margin:0;">Sent ' + esc(MD.relTime(h.sos_active.created_at)) + ". Stay where you are if it is safe; help is being arranged.</p></div>"
      : '<div class="card" style="margin-bottom:14px;"><div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;"><div style="flex:1;min-width:200px;"><strong>' + esc(t("sosHelp")) + '</strong><div class="note-text" style="margin:2px 0 0;">Security and the admin get an alarm with your flat number.</div></div>' +
        '<select id="sos-kind" style="width:auto;"><option value="MEDICAL">Medical</option><option value="FIRE">Fire</option><option value="INTRUDER">Intruder</option><option value="OTHER">Other</option></select>' +
        '<button class="sos-btn" id="btn-sos">' + esc(t("sendSos")) + "</button></div></div>";

    var approvals = h.awaiting_approval.length
      ? '<div class="callout"><h3 class="section-title" style="margin:0 0 4px;">Needs your answer</h3>' + h.awaiting_approval.map(function (d) {
          return '<div class="approval-item"><div><strong>' + esc(d.platform || d.courier_name || "Courier") + '</strong> is at the gate<div class="note-text" style="margin:2px 0 0;">' + esc(MD.relTime(d.requested_at)) + '</div></div><div class="row-actions"><button class="approve" data-yes="' + Number(d.id) + '">Approve</button><button class="deny" data-no="' + Number(d.id) + '">Deny</button></div></div>';
        }).join("") + "</div>" : "";

    var vehicles = h.vehicles.length ? h.vehicles.map(function (v) {
      return "<div>" + esc(v.vehicle_number) + ' <span class="muted">(' + esc(v.vehicle_type) + ")</span> " + v.credentials.map(function (k) { return MD.badge(k.status) + ' <span class="muted">' + esc(k.type) + "</span>"; }).join(" ") + "</div>";
    }).join("") : '<p class="note-text">No vehicles registered. Ask the admin to add yours.</p>';

    var staff = h.staff.length ? h.staff.map(function (s) {
      var state = !s.present_today ? '<span class="muted">not in today</span>' : (s.inside ? '<span style="color:var(--granted)">inside since ' + esc(s.first_in) + "</span>" : "left at " + esc(s.last_out || "—"));
      return "<div>" + esc(s.name) + ' <span class="muted">(' + esc(s.role) + ")</span> — " + state + "</div>";
    }).join("") : '<p class="note-text">No house staff registered for your flat.</p>';

    var act = h.recent_activity.length ? '<div class="table-wrap"><table><thead><tr><th>When</th><th>What</th><th>Result</th></tr></thead><tbody>' + h.recent_activity.map(function (a) {
      return "<tr><td>" + esc(MD.fmtTime(a.timestamp)) + "</td><td>" + esc(a.subject || a.method) + " <span class=\"muted\">" + esc(a.direction) + "</span></td><td>" + MD.badge(a.access) + "</td></tr>";
    }).join("") + "</tbody></table></div>" : '<p class="note-text">Nothing at the gate for your flat yet.</p>';

    root.innerHTML = sos + approvals + '<div class="tiles">' + tiles + "</div>" +
      '<div class="two-col"><div><h3 class="section-title" style="font-size:0.95rem;">My vehicles</h3>' + vehicles + '</div><div><h3 class="section-title" style="font-size:0.95rem;">My house staff today</h3>' + staff + "</div></div>" +
      '<h3 class="section-title" style="margin-top:20px;font-size:0.95rem;">Recent activity at the gate</h3>' + act;

    var sosBtn = $("btn-sos");
    if (sosBtn) sosBtn.addEventListener("click", async function () {
      if (!window.confirm("Send an SOS to security and the admin now?")) return;
      var res = await MD.postJSON("/sos", { kind: $("sos-kind").value });
      if (!res.ok) { alert(res.error); return; }
      loadHome();
    });
    root.querySelectorAll("button[data-yes]").forEach(function (b) { b.addEventListener("click", async function () { await MD.postJSON("/deliveries/" + b.getAttribute("data-yes") + "/decision", { approve: true }); loadHome(); }); });
    root.querySelectorAll("button[data-no]").forEach(function (b) { b.addEventListener("click", async function () { await MD.postJSON("/deliveries/" + b.getAttribute("data-no") + "/decision", { approve: false }); loadHome(); }); });
    var dot = $("notice-dot");
    dot.textContent = c.notices_unread; dot.classList.toggle("hidden", !c.notices_unread);
  }

  // ------------------------------------------------------------------ Notices
  async function loadNotices() {
    var root = $("rpanel-notices");
    var r = await MD.getJSON("/notices");
    if (!r.ok) { root.innerHTML = '<p class="note-text">' + esc(r.error) + "</p>"; return; }
    if (!r.data.length) { root.innerHTML = '<p class="note-text">No notices right now.</p>'; return; }
    root.innerHTML = r.data.map(function (n) {
      return '<div class="card" style="margin-bottom:12px;' + (n.read ? "" : "border-color:var(--info);") + '"><div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;"><strong>' + (n.pinned ? "📌 " : "") + esc(n.title) + '</strong><span class="muted">' + esc(MD.fmtDay(n.created_at)) + (n.created_by ? " · " + esc(n.created_by) : "") + '</span></div><p style="white-space:pre-wrap;margin:8px 0;">' + esc(n.body) + "</p>" +
        (n.read ? '<span class="muted">✓ Read</span>' : '<button class="action secondary" style="margin:0;" data-read="' + Number(n.id) + '">Mark as read</button>') + "</div>";
    }).join("");
    root.querySelectorAll("button[data-read]").forEach(function (b) {
      b.addEventListener("click", async function () { await MD.postJSON("/notices/" + b.getAttribute("data-read") + "/read"); loadNotices(); loadHome(); });
    });
  }

  // ------------------------------------------------------------------ My Flat
  var flatMonth = null;
  async function loadFlat() {
    var root = $("rpanel-flat");
    if (!flatMonth) { var d = new Date(); flatMonth = d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0"); }
    var res = await Promise.all([MD.getJSON("/me/home"), MD.getJSON("/attendance/my-staff?month=" + flatMonth), MD.getJSON("/recurring-visitors")]);
    var home = res[0], att = res[1];
    var html = '<h3 class="section-title">Vehicles and gate tags</h3>';
    if (home.ok && home.data.vehicles.length) {
      html += '<div class="table-wrap"><table><thead><tr><th>Vehicle</th><th>Tag</th><th>Type</th><th>Status</th><th>Expires</th></tr></thead><tbody>';
      home.data.vehicles.forEach(function (v) {
        if (!v.credentials.length) html += "<tr><td>" + esc(v.vehicle_number) + '</td><td colspan="4" class="muted">No tag issued yet</td></tr>';
        v.credentials.forEach(function (k) { html += "<tr><td>" + esc(v.vehicle_number) + '</td><td class="mono">' + esc(k.value) + "</td><td>" + esc(k.type) + "</td><td>" + MD.badge(k.status) + "</td><td>" + (k.expires_at ? esc(MD.fmtTime(k.expires_at)) : "—") + "</td></tr>"; });
      });
      html += "</tbody></table></div>";
    } else html += '<p class="note-text">No vehicles registered. Ask the admin to add yours.</p>';

    html += '<h3 class="section-title" style="margin-top:24px;">House staff attendance</h3><div style="max-width:220px;"><input type="month" id="flat-month" value="' + esc(flatMonth) + '" /></div>';
    if (att.ok && att.data.staff.length) {
      att.data.staff.forEach(function (s) {
        html += '<div class="card" style="margin:12px 0 0;"><strong>' + esc(s.name) + '</strong> <span class="muted">(' + esc(s.role) + ") — " + Number(s.present_days) + " day(s) present</span>" +
          (s.days.length ? '<div class="table-wrap"><table><thead><tr><th>Date</th><th>First in</th><th>Last out</th><th>Hours</th></tr></thead><tbody>' + s.days.map(function (d) { return "<tr><td>" + esc(d.date) + "</td><td>" + esc(d.first_in || "—") + "</td><td>" + esc(d.last_out || "—") + "</td><td>" + (d.hours != null ? esc(d.hours) : "—") + "</td></tr>"; }).join("") + "</tbody></table></div>" : '<p class="note-text">No visits this month.</p>') + "</div>";
      });
    } else html += '<p class="note-text">' + (att.ok ? "No house staff registered for your flat." : esc(att.error)) + "</p>";
    root.innerHTML = html;
    $("flat-month").addEventListener("change", function () { if (this.value) { flatMonth = this.value; loadFlat(); } });
  }

  // ------------------------------------------------------------------ Regular visitors
  function recurringForm() {
    return '<h3 class="section-title" style="margin-top:28px;">Regular visitors</h3>' +
      '<p class="note-text">Maid, tutor, milkman, driver... People who come on the same days every week. Give them one code that works only on their days and hours.</p>' +
      '<div class="field-grid"><div><label for="rg-name">Name</label><input id="rg-name" maxlength="80" /></div><div><label for="rg-phone">Phone</label><input id="rg-phone" placeholder="10-digit number" /></div></div>' +
      '<div class="field-grid"><div><label for="rg-purpose">What for (optional)</label><input id="rg-purpose" maxlength="200" placeholder="e.g. Tuition" /></div><div></div></div>' +
      '<label>Days</label><div class="days">' + DAYS.map(function (d, i) { return '<label><input type="checkbox" class="rg-day" value="' + i + '" ' + (i < 5 ? "checked" : "") + " /> " + d + "</label>"; }).join("") + "</div>" +
      '<div class="field-grid"><div><label for="rg-from">From (time)</label><input type="time" id="rg-from" value="06:00" /></div><div><label for="rg-to">Until (time)</label><input type="time" id="rg-to" value="20:00" /></div></div>' +
      '<button class="action" id="rg-save">Add regular visitor</button><div class="inline-result hidden" id="rg-result"></div>' +
      '<div class="table-wrap"><table><thead><tr><th>Name</th><th>Days / hours</th><th>Code</th><th>Last entry</th><th></th></tr></thead><tbody id="rg-body"><tr class="empty-row"><td colspan="5">Loading...</td></tr></tbody></table></div>';
  }
  async function loadRecurring() {
    var body = $("rg-body"); if (!body) return;
    var r = await MD.getJSON("/recurring-visitors");
    if (!r.ok) { body.innerHTML = MD.emptyRow(5, r.error); return; }
    if (!r.data.length) { body.innerHTML = MD.emptyRow(5, "No regular visitors yet."); return; }
    body.innerHTML = r.data.map(function (x) {
      return "<tr><td>" + esc(x.name) + (x.purpose ? '<div class="note-text" style="margin:2px 0 0;">' + esc(x.purpose) + "</div>" : "") + "</td><td>" + esc(x.days.map(function (d) { return DAYS[d]; }).join(", ")) + "<br/>" + esc(x.start_time) + "–" + esc(x.end_time) + '</td><td class="mono">' + esc(x.otp_code) + "</td><td>" + (x.last_entry_at ? esc(MD.fmtTime(x.last_entry_at)) : "—") + "</td>" +
        '<td class="row-actions">' + MD.badge(x.is_active ? "ACTIVE" : "PAUSED") + ' <button data-rg="' + Number(x.id) + '" data-on="' + (x.is_active ? "0" : "1") + '">' + (x.is_active ? "Pause" : "Resume") + "</button></td></tr>";
    }).join("");
    body.querySelectorAll("button[data-rg]").forEach(function (b) {
      b.addEventListener("click", async function () {
        var res = await MD.postJSON("/recurring-visitors/" + b.getAttribute("data-rg") + "/active", { is_active: b.getAttribute("data-on") === "1" });
        if (!res.ok) alert(res.error); loadRecurring();
      });
    });
  }
  function wireRecurring() {
    $("rg-save").addEventListener("click", async function () {
      var box = $("rg-result"); box.classList.remove("hidden");
      var days = Array.prototype.slice.call(document.querySelectorAll(".rg-day:checked")).map(function (c) { return Number(c.value); });
      if (!$("rg-name").value.trim() || !$("rg-phone").value.trim()) { box.textContent = "Please enter the name and phone."; return; }
      if (!days.length) { box.textContent = "Choose at least one day."; return; }
      var r = await MD.postJSON("/recurring-visitors", { name: $("rg-name").value.trim(), phone: $("rg-phone").value.trim(), purpose: $("rg-purpose").value.trim() || null, days: days, start_time: $("rg-from").value, end_time: $("rg-to").value });
      if (!r.ok) { box.textContent = "Could not add: " + r.error; return; }
      box.innerHTML = "Added <strong>" + esc(r.data.name) + "</strong>. Their gate code:<br/><span class=\"otp-code\">" + esc(r.data.otp_code) + "</span>";
      $("rg-name").value = ""; $("rg-phone").value = ""; $("rg-purpose").value = "";
      loadRecurring();
    });
  }

  // ------------------------------------------------------------------ Delivery rules
  function rulesForm() {
    return '<h3 class="section-title" style="margin-top:28px;">My delivery rules</h3>' +
      '<p class="note-text">Decide once, per company. When a courier from that company turns up unannounced, security follows your rule without calling you.</p>' +
      '<div class="field-grid"><div><label for="dr-platform">Company</label><input id="dr-platform" list="rp-d-platforms" placeholder="e.g. Swiggy" maxlength="60" autocomplete="off" /></div>' +
      '<div><label for="dr-action">Rule</label><select id="dr-action"><option value="ALLOW">Always let in</option><option value="LEAVE_AT_GATE">Leave at the gate</option><option value="DENY">Never let in</option></select></div></div>' +
      '<button class="action" id="dr-save">Save rule</button><div class="error-text" id="dr-err"></div>' +
      '<div class="table-wrap"><table><thead><tr><th>Company</th><th>Rule</th><th></th></tr></thead><tbody id="dr-body"><tr class="empty-row"><td colspan="3">Loading...</td></tr></tbody></table></div>';
  }
  var RULE_TEXT = { ALLOW: "Always let in", LEAVE_AT_GATE: "Leave at the gate", DENY: "Never let in" };
  async function loadRules() {
    var body = $("dr-body"); if (!body) return;
    var r = await MD.getJSON("/delivery-rules");
    if (!r.ok) { body.innerHTML = MD.emptyRow(3, r.error); return; }
    if (!r.data.length) { body.innerHTML = MD.emptyRow(3, "No rules yet."); return; }
    body.innerHTML = r.data.map(function (x) {
      return "<tr><td>" + esc(x.platform) + "</td><td>" + esc(RULE_TEXT[x.action] || x.action) + '</td><td class="row-actions"><button class="deny" data-rule="' + Number(x.id) + '">Remove</button></td></tr>';
    }).join("");
    body.querySelectorAll("button[data-rule]").forEach(function (b) {
      b.addEventListener("click", async function () { await MD.request("DELETE", "/delivery-rules/" + b.getAttribute("data-rule")); loadRules(); });
    });
  }
  function wireRules() {
    $("dr-save").addEventListener("click", async function () {
      $("dr-err").textContent = "";
      if (!$("dr-platform").value.trim()) { $("dr-err").textContent = "Enter a company name."; return; }
      var r = await MD.postJSON("/delivery-rules", { platform: $("dr-platform").value.trim(), action: $("dr-action").value });
      if (!r.ok) { $("dr-err").textContent = r.error; return; }
      $("dr-platform").value = ""; loadRules();
    });
  }

  // ------------------------------------------------------------------ start
  document.addEventListener("md:ready", function () {
    var u = MD.user();
    if (u.role !== "RESIDENT") return;
    $("rp-regular-root").innerHTML = recurringForm(); wireRecurring();
    $("rp-rules-root").innerHTML = rulesForm(); wireRules();
    MD.renderAccount($("rpanel-account"));

    $("resident-view").querySelectorAll(".tabs > .tab-btn").forEach(function (b) { b.addEventListener("click", function () { showTab(b.id); }); });
    $("rtab-home").addEventListener("click", loadHome);
    $("rtab-notices").addEventListener("click", loadNotices);
    $("rtab-flat").addEventListener("click", loadFlat);
    $("rtab-visitors").addEventListener("click", loadRecurring);
    $("rtab-deliveries").addEventListener("click", loadRules);
    document.addEventListener("md:goto-account", function () { $("rtab-account").click(); });
    document.addEventListener("md:lang", loadHome);
    document.addEventListener("md:notify-new", function () { if ($("rpanel-home").classList.contains("active")) loadHome(); });

    showTab("rtab-home");
    loadHome(); loadRecurring(); loadRules();
    if (homeTimer) clearInterval(homeTimer);
    homeTimer = setInterval(function () { if (!document.hidden && $("rpanel-home").classList.contains("active")) loadHome(); }, 30000);
  });
})();
