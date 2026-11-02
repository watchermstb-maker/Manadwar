/* ManaDwar v9 - guard and admin console additions: navigation, SOS alarm, today's expected list,
   visitor/parcel photos, admin dashboard, people (residents, vehicles, tags, users, invites),
   gate log + audit trail, notices, staff attendance, account. */
(function () {
  "use strict";
  var MD = window.MD;
  var $ = MD.$, esc = MD.esc, t = MD.t;
  var DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  var isAdmin = false, current = null, pageTimer = null;

  function el(html) { var d = document.createElement("div"); d.innerHTML = html.trim(); return d.firstChild; }
  function tableWrap(head, bodyId, cols, empty) {
    return '<div class="table-wrap"><table><thead><tr>' + head.map(function (h) { return "<th>" + h + "</th>"; }).join("") + '</tr></thead><tbody id="' + bodyId + '">' + MD.emptyRow(cols, empty || "Loading...") + "</tbody></table></div>";
  }
  function subtabs(root, names, onPick) {
    var bar = root.querySelector(".subtabs");
    bar.innerHTML = names.map(function (n, i) { return '<button data-sub="' + n[0] + '" class="' + (i === 0 ? "active" : "") + '">' + esc(n[1]) + "</button>"; }).join("");
    bar.querySelectorAll("button").forEach(function (b) {
      b.addEventListener("click", function () {
        bar.querySelectorAll("button").forEach(function (x) { x.classList.toggle("active", x === b); });
        root.querySelectorAll(".sub").forEach(function (s) { s.classList.toggle("hidden", s.getAttribute("data-sub") !== b.getAttribute("data-sub")); });
        onPick(b.getAttribute("data-sub"));
      });
    });
  }
  function resSelect(id, withNone) {
    return '<select id="' + id + '">' + (withNone ? '<option value="">— choose —</option>' : "") + MD.residents().map(function (r) { return '<option value="' + Number(r.id) + '">' + esc(r.name) + " (" + esc(r.apartment_no) + ")</option>"; }).join("") + "</select>";
  }

  // ================================================================== navigation
  function buildNav(items) {
    var nav = $("main-nav");
    nav.innerHTML = items.map(function (i) { return '<button data-page="' + i[0] + '" id="nav-' + i[0] + '">' + esc(t(i[1])) + (i[0] === "sos" ? ' <span class="dot hidden" id="nav-sos-dot"></span>' : "") + "</button>"; }).join("");
    nav.classList.remove("hidden");
    nav.querySelectorAll("button").forEach(function (b) { b.addEventListener("click", function () { showPage(b.getAttribute("data-page")); }); });
  }
  var LOADERS = {};
  function showPage(name) {
    current = name;
    $("main-nav").querySelectorAll("button").forEach(function (b) { b.classList.toggle("active", b.getAttribute("data-page") === name); });
    $("staff-view").querySelectorAll(".page").forEach(function (p) { p.classList.toggle("active", p.getAttribute("data-page") === name); });
    if (pageTimer) { clearInterval(pageTimer); pageTimer = null; }
    if (LOADERS[name]) LOADERS[name]();
  }
  function makePage(name, html) {
    var p = el('<div class="card page" data-page="' + name + '">' + html + "</div>");
    $("ext-pages").appendChild(p);
    return p;
  }

  // ================================================================== SOS banner
  var seenSos = {};
  var sosFirstLoad = true;
  async function pollSos() {
    var r = await MD.getJSON("/sos?active_only=true");
    var host = $("ext-banners");
    var old = $("sos-banner-wrap"); if (old) old.remove();
    if (!r.ok) return;
    var alerts = r.data;
    var dot = $("nav-sos-dot"); if (dot) { dot.textContent = alerts.length; dot.classList.toggle("hidden", !alerts.length); }
    if (!alerts.length) return;
    var fresh = alerts.some(function (a) { return !seenSos[a.id]; });
    alerts.forEach(function (a) { seenSos[a.id] = true; });
    if (fresh && MD.storeGet("manadwar_sound") !== "off") {
      MD.sounds.alarm();
      if (navigator.vibrate) try { navigator.vibrate([400, 150, 400, 150, 400]); } catch (e) { /* ignore */ }
      var a0 = alerts.find(function (a) { return a.status === "ACTIVE"; });
      if (a0) MD.speak("S O S. " + a0.kind + ". Flat " + a0.apartment_no);
    }
    var wrap = el('<div id="sos-banner-wrap"></div>');
    wrap.innerHTML = alerts.map(function (a) {
      return '<div class="sos-banner"><h3>🚨 SOS ' + esc(a.kind) + " — Flat " + esc(a.apartment_no) + '</h3><div><strong>' + esc(a.resident_name) + "</strong>" +
        (a.phone ? ' · <a href="tel:' + esc(a.phone) + '" style="color:var(--text);">' + esc(a.phone) + "</a>" : "") + (a.message ? " — " + esc(a.message) : "") + '</div><div class="note-text" style="margin:4px 0 8px;">' + esc(MD.relTime(a.created_at)) +
        (a.status === "ACKNOWLEDGED" ? " · seen by " + esc(a.acknowledged_by || "gate") : "") + '</div><div class="row-actions">' +
        (a.status === "ACTIVE" ? '<button class="approve" data-ack="' + Number(a.id) + '">I am on it</button>' : "") + '<button data-resolve="' + Number(a.id) + '">Resolve</button></div></div>';
    }).join("");
    host.appendChild(wrap);
    wrap.querySelectorAll("button[data-ack]").forEach(function (b) { b.addEventListener("click", async function () { var x = await MD.postJSON("/sos/" + b.getAttribute("data-ack") + "/ack"); if (!x.ok) alert(x.error); pollSos(); }); });
    wrap.querySelectorAll("button[data-resolve]").forEach(function (b) {
      b.addEventListener("click", async function () {
        var note = window.prompt("Note (optional):", ""); if (note === null) return;
        var x = await MD.postJSON("/sos/" + b.getAttribute("data-resolve") + "/resolve", { note: note || null }); if (!x.ok) alert(x.error); pollSos();
      });
    });
  }

  // ================================================================== gate: photos after a successful check
  function photoPrompt(html, onClick) {
    var old = $("photo-prompt"); if (old) old.remove();
    var box = el('<div class="inline-result" id="photo-prompt">' + html + "</div>");
    $("status-screen").insertAdjacentElement("afterend", box);
    box.querySelector("button").addEventListener("click", function () { onClick(box); });
  }
  MD.onVerified = function (kind, data) {
    if (!data.visitor_id) { var old = $("photo-prompt"); if (old) old.remove(); return; }
    photoPrompt('Visitor entered. <button class="action secondary" style="margin:0 0 0 8px;">📷 Take visitor photo</button>', function (box) {
      MD.pickPhoto(async function (file) {
        var r = await MD.uploadPhoto("/visitors/" + data.visitor_id + "/photo", file);
        if (r) box.textContent = "Photo saved for " + (data.visitor_name || "visitor") + ".";
      }, "user");
    });
  };
  MD.onAdmitted = function (d) {
    if (!d || !d.id) return;
    photoPrompt('Delivery let in. <button class="action secondary" style="margin:0 0 0 8px;">📷 Photo of parcel</button>', function (box) {
      MD.pickPhoto(async function (file) {
        var r = await MD.uploadPhoto("/deliveries/" + d.id + "/parcel-photo", file);
        if (r) box.textContent = "Parcel photo saved.";
      }, "environment");
    });
  };

  // ================================================================== Today (expected at the gate)
  function loadToday() {
    var p = $("page-today");
    async function go() {
      var r = await MD.getJSON("/gate/expected");
      if (!r.ok) { p.querySelector(".body").textContent = r.error; return; }
      var d = r.data;
      function host(x) { return esc(x.host_name || "") + " <span class=\"muted\">" + esc(x.host_apartment || "") + "</span>"; }
      p.querySelector(".body").innerHTML =
        '<h3 class="section-title">Visitors with a pass</h3>' + (d.visitors.length ? '<div class="table-wrap"><table><thead><tr><th>Name</th><th>Visiting</th><th>Window</th><th>Vehicle</th><th>Status</th></tr></thead><tbody>' + d.visitors.map(function (v) {
          return "<tr><td>" + esc(v.name) + (v.purpose ? '<div class="note-text" style="margin:2px 0 0;">' + esc(v.purpose) + "</div>" : "") + "</td><td>" + host(v) + "</td><td>" + esc(MD.fmtTime(v.valid_from)) + " → " + esc(MD.fmtTime(v.valid_until)) + "</td><td>" + esc(v.vehicle_number || "—") + "</td><td>" + MD.badge(v.entered_today ? "ENTERED" : v.status) + "</td></tr>";
        }).join("") + "</tbody></table></div>" : '<p class="note-text">No passes for the rest of today.</p>') +
        '<h3 class="section-title" style="margin-top:22px;">Regular visitors today</h3>' + (d.regular_visitors.length ? '<div class="table-wrap"><table><thead><tr><th>Name</th><th>Visiting</th><th>Usual hours</th><th></th></tr></thead><tbody>' + d.regular_visitors.map(function (v) {
          return "<tr><td>" + esc(v.name) + (v.purpose ? '<div class="note-text" style="margin:2px 0 0;">' + esc(v.purpose) + "</div>" : "") + "</td><td>" + host(v) + "</td><td>" + esc(v.start_time) + "–" + esc(v.end_time) + "</td><td>" + (v.entered_today ? MD.badge("ENTERED") : "—") + "</td></tr>";
        }).join("") + "</tbody></table></div>" : '<p class="note-text">None expected for the rest of today.</p>') +
        '<h3 class="section-title" style="margin-top:22px;">Deliveries</h3>' + (d.deliveries.length ? '<div class="table-wrap"><table><thead><tr><th>Company</th><th>For</th><th>Window</th><th>Note</th></tr></thead><tbody>' + d.deliveries.map(function (x) {
          return "<tr><td>" + esc(x.platform || "—") + "</td><td>" + host(x) + "</td><td>" + esc(MD.fmtTime(x.expected_from)) + " → " + esc(MD.fmtTime(x.expected_until)) + "</td><td>" + (x.leave_at_gate ? MD.badge("LEAVE AT GATE") : "") + "</td></tr>";
        }).join("") + "</tbody></table></div>" : '<p class="note-text">No deliveries expected.</p>');
    }
    go();
    pageTimer = setInterval(function () { if (!document.hidden) go(); }, 30000);
  }

  // ================================================================== Dashboard
  async function loadDashboard() {
    var body = $("page-dashboard").querySelector(".body");
    var r = await MD.getJSON("/admin/dashboard");
    if (!r.ok) { body.textContent = r.error; return; }
    var d = r.data, max = Math.max.apply(null, d.hourly_granted.concat([1]));
    function tile(n, label, warn) { return '<div class="tile ' + (warn && n ? "warn" : "") + '"><b>' + Number(n) + "</b><span>" + esc(label) + "</span></div>"; }
    body.innerHTML = (d.sos_active ? '<div class="banner" style="border-color:var(--denied);background:var(--denied-dim);">🚨 ' + Number(d.sos_active) + " active SOS alert(s) — see the SOS banner above.</div>" : "") +
      '<div class="tiles">' + tile(d.today.granted, "Entries today") + tile(d.today.denied, "Denied today", true) + tile(d.visitor_passes.live, "Live passes") + tile(d.visitor_passes.scheduled, "Scheduled passes") +
      tile(d.deliveries.EXPECTED || 0, "Deliveries expected") + tile(d.deliveries.AWAITING_APPROVAL || 0, "Awaiting resident", true) + tile(d.complaints.open, "Open complaints", true) + tile(d.complaints.in_progress, "In progress") +
      tile(d.staff_present_today, "House staff in today") + tile(d.denied_24h, "Denied (24 h)", true) + "</div>" +
      '<h3 class="section-title" style="font-size:0.95rem;">Entries by hour today</h3><div class="bars">' + d.hourly_granted.map(function (n, h) { return '<div title="' + h + ':00 — ' + n + '" style="height:' + Math.max(2, Math.round(n / max * 100)) + '%"></div>'; }).join("") + '</div><div class="bars-x"><span>0h</span><span>6h</span><span>12h</span><span>18h</span><span>23h</span></div>' +
      (d.complaints.oldest_open_days ? '<p class="note-text">Oldest unresolved complaint: ' + Number(d.complaints.oldest_open_days) + " day(s).</p>" : "") +
      '<h3 class="section-title" style="margin-top:18px;font-size:0.95rem;">Society</h3><div class="tiles">' + tile(d.totals.residents, "Flats/residents") + tile(d.totals.resident_logins, "Resident logins") + tile(d.totals.guards, "Guards") + tile(d.totals.vehicles, "Vehicles") + tile(d.totals.credentials_active, "Active tags") + tile(d.totals.staff, "House staff") + "</div>" +
      '<h3 class="section-title" style="margin-top:18px;font-size:0.95rem;">Latest at the gate</h3>' + logTable(d.recent_activity);
    pageTimer = setInterval(function () { if (!document.hidden && current === "dashboard") loadDashboard(); }, 30000);
  }
  function logTable(rows) {
    if (!rows.length) return '<p class="note-text">Nothing logged yet.</p>';
    return '<div class="table-wrap"><table><thead><tr><th>Time</th><th>Who / what</th><th>For</th><th>Method</th><th>Dir</th><th>Result</th><th>By</th></tr></thead><tbody>' + rows.map(function (l) {
      return "<tr><td>" + esc(MD.fmtTime(l.timestamp)) + "</td><td>" + esc(l.subject || l.credential_value) + "</td><td>" + esc(l.resident_label || "—") + "</td><td>" + esc(l.entry_method) + "</td><td>" + esc(l.direction) + "</td><td>" + MD.badge(l.access) + "</td><td>" + esc(l.actor_name || "—") + "</td></tr>";
    }).join("") + "</tbody></table></div>";
  }

  // ================================================================== People
  function peoplePage() {
    var p = makePage("people", '<h2 class="section-title">People and tags</h2><div class="subtabs"></div>' +
      '<div class="sub" data-sub="residents"><div class="field-grid"><div><label for="pr-name">Name</label><input id="pr-name" maxlength="80" /></div><div><label for="pr-flat">Flat / apartment</label><input id="pr-flat" maxlength="20" /></div></div>' +
      '<div class="field-grid"><div><label for="pr-phone">Phone (optional)</label><input id="pr-phone" /></div><div></div></div><button class="action" id="pr-add">Add resident</button><div class="error-text" id="pr-err"></div>' +
      tableWrap(["#", "Name", "Flat", "Phone", ""], "pr-body", 5) + "</div>" +
      '<div class="sub hidden" data-sub="vehicles"><div class="field-grid"><div><label for="pv-res">Owner</label><span id="pv-res-slot"></span></div><div><label for="pv-num">Vehicle number</label><input id="pv-num" placeholder="e.g. KA-01-AB-1234" maxlength="20" /></div></div>' +
      '<div class="field-grid"><div><label for="pv-type">Type</label><select id="pv-type"><option value="CAR">Car</option><option value="BIKE">Bike</option></select></div><div></div></div><button class="action" id="pv-add">Add vehicle</button><div class="error-text" id="pv-err"></div>' +
      tableWrap(["Vehicle", "Owner", "Tags", ""], "pv-body", 4) + "</div>" +
      '<div class="sub hidden" data-sub="users"><div class="field-grid"><div><label for="pu-name">Name</label><input id="pu-name" maxlength="80" /></div><div><label for="pu-email">Email</label><input id="pu-email" type="email" /></div></div>' +
      '<div class="field-grid"><div><label for="pu-role">Role</label><select id="pu-role"><option value="GUARD">Guard</option><option value="ADMIN">Admin</option></select></div><div><label for="pu-pass">Password (leave empty to generate)</label><input id="pu-pass" type="text" autocomplete="off" /></div></div>' +
      '<button class="action" id="pu-add">Create login</button><div class="inline-result hidden" id="pu-result"></div><p class="note-text" style="margin-top:12px;">Residents create their own login with an invite code (Invites tab).</p>' +
      tableWrap(["Name", "Email", "Role", "Flat", "Last sign-in", "Status", ""], "pu-body", 7) + "</div>" +
      '<div class="sub hidden" data-sub="invites"><p class="note-text">An invite code lets one family member create a login linked to a flat. Codes work once and expire after 7 days. A flat can have up to 5 logins.</p><label for="pi-res">Flat</label><span id="pi-res-slot"></span>' +
      '<button class="action" id="pi-add">Create invite code</button><div class="inline-result hidden" id="pi-result"></div>' + tableWrap(["Code", "Flat", "Created", "Expires", "Status"], "pi-body", 5) + "</div>");
    subtabs(p, [["residents", "Residents"], ["vehicles", "Vehicles & tags"], ["users", "Logins"], ["invites", "Invites"]], function (s) { ({ residents: loadResidentsTable, vehicles: loadVehicles, users: loadUsers, invites: loadInvites })[s](); });
    return p;
  }
  function refreshResSelects() { $("pv-res-slot").innerHTML = resSelect("pv-res", true); $("pi-res-slot").innerHTML = resSelect("pi-res", true); }

  async function loadResidentsTable() {
    await MD.loadResidents(); refreshResSelects();
    var body = $("pr-body"), list = MD.residents();
    body.innerHTML = list.length ? list.map(function (r) {
      return "<tr><td>" + Number(r.id) + "</td><td>" + esc(r.name) + "</td><td>" + esc(r.apartment_no) + "</td><td>" + esc(r.phone || "—") + '</td><td class="row-actions"><button data-edit="' + Number(r.id) + '">Edit</button></td></tr>';
    }).join("") : MD.emptyRow(5, "No residents yet.");
    body.querySelectorAll("button[data-edit]").forEach(function (b) {
      b.addEventListener("click", function () {
        var r = MD.residents().find(function (x) { return String(x.id) === b.getAttribute("data-edit"); });
        var m = MD.modal('<h3 class="section-title">Edit resident</h3><label>Name</label><input id="er-name" maxlength="80" value="' + esc(r.name) + '" /><label>Flat</label><input id="er-flat" maxlength="20" value="' + esc(r.apartment_no) + '" /><label>Phone</label><input id="er-phone" value="' + esc(r.phone || "") + '" /><div class="row-actions" style="margin-top:14px;"><button class="approve" id="er-save">Save</button><button id="er-cancel">Cancel</button></div><div class="error-text" id="er-err"></div>');
        m.querySelector("#er-cancel").addEventListener("click", m.close);
        m.querySelector("#er-save").addEventListener("click", async function () {
          var res = await MD.request("PATCH", "/residents/" + r.id, { name: m.querySelector("#er-name").value, apartment_no: m.querySelector("#er-flat").value, phone: m.querySelector("#er-phone").value || null });
          if (!res.ok) { m.querySelector("#er-err").textContent = res.error; return; }
          m.close(); loadResidentsTable();
        });
      });
    });
  }
  function wireResidents() {
    $("pr-add").addEventListener("click", async function () {
      $("pr-err").textContent = "";
      var r = await MD.postJSON("/residents", { name: $("pr-name").value, apartment_no: $("pr-flat").value, phone: $("pr-phone").value || null });
      if (!r.ok) { $("pr-err").textContent = r.error; return; }
      $("pr-name").value = $("pr-flat").value = $("pr-phone").value = ""; loadResidentsTable();
    });
  }

  async function loadVehicles() {
    refreshResSelects();
    var res = await Promise.all([MD.getJSON("/vehicles"), MD.getJSON("/credentials")]);
    var body = $("pv-body");
    if (!res[0].ok) { body.innerHTML = MD.emptyRow(4, res[0].error); return; }
    var creds = res[1].ok ? res[1].data : [];
    var byVehicle = {}; creds.forEach(function (c) { (byVehicle[c.vehicle_id] = byVehicle[c.vehicle_id] || []).push(c); });
    body.innerHTML = res[0].data.length ? res[0].data.map(function (v) {
      var mine = (byVehicle[v.id] || []).map(function (c) {
        return '<div><span class="mono">' + esc(c.credential_value) + "</span> " + MD.badge(c.status) + (c.credential_scope === "VISITOR" ? ' <span class="muted">visitor</span>' : "") + (c.expires_at ? ' <span class="muted">until ' + esc(MD.fmtDay(c.expires_at)) + "</span>" : "") +
          ' <span class="row-actions" style="display:inline-flex;">' + (c.status === "ACTIVE" ? '<button class="deny" data-cred="' + Number(c.id) + '" data-st="BLOCKED">Block</button>' : '<button class="approve" data-cred="' + Number(c.id) + '" data-st="ACTIVE">Activate</button>') + '<button data-exp="' + Number(c.id) + '">Expiry</button></span></div>';
      }).join("");
      return "<tr><td>" + esc(v.vehicle_number) + ' <span class="muted">' + esc(v.vehicle_type) + "</span></td><td>" + esc(v.resident_id ? MD.residentLabel(v.resident_id) : "Visitor") + "</td><td>" + (mine || '<span class="muted">no tag</span>') + '</td><td class="row-actions"><button data-issue="' + Number(v.id) + '">Issue tag</button></td></tr>';
    }).join("") : MD.emptyRow(4, "No vehicles yet.");
    body.querySelectorAll("button[data-cred]").forEach(function (b) { b.addEventListener("click", async function () { var r = await MD.request("PATCH", "/credentials/" + b.getAttribute("data-cred"), { status: b.getAttribute("data-st") }); if (!r.ok) alert(r.error); loadVehicles(); }); });
    body.querySelectorAll("button[data-exp]").forEach(function (b) {
      b.addEventListener("click", function () {
        var m = MD.modal('<h3 class="section-title">Tag expiry</h3><label>Expires on (empty = never)</label><input type="date" id="ex-date" /><div class="row-actions" style="margin-top:14px;"><button class="approve" id="ex-save">Save</button><button id="ex-cancel">Cancel</button></div><div class="error-text" id="ex-err"></div>');
        m.querySelector("#ex-cancel").addEventListener("click", m.close);
        m.querySelector("#ex-save").addEventListener("click", async function () {
          var v = m.querySelector("#ex-date").value;
          var payload = v ? { expires_at: new Date(v + "T23:59:00").toISOString() } : { clear_expiry: true };
          var r = await MD.request("PATCH", "/credentials/" + b.getAttribute("data-exp"), payload);
          if (!r.ok) { m.querySelector("#ex-err").textContent = r.error; return; }
          m.close(); loadVehicles();
        });
      });
    });
    body.querySelectorAll("button[data-issue]").forEach(function (b) {
      b.addEventListener("click", function () {
        var m = MD.modal('<h3 class="section-title">Issue a gate tag</h3><label>Kind</label><select id="is-kind"><option value="RFID">RFID sticker/card</option><option value="FASTAG">FASTag</option></select><label>Tag code (empty = generate one)</label><input id="is-code" maxlength="64" placeholder="Scan or type the printed code" /><div class="row-actions" style="margin-top:14px;"><button class="approve" id="is-save">Issue</button><button id="is-cancel">Cancel</button></div><div class="error-text" id="is-err"></div>');
        m.querySelector("#is-cancel").addEventListener("click", m.close);
        m.querySelector("#is-save").addEventListener("click", async function () {
          var code = m.querySelector("#is-code").value.trim();
          var r = await MD.postJSON("/credentials", { vehicle_id: Number(b.getAttribute("data-issue")), credential_type: m.querySelector("#is-kind").value, credential_value: code || null });
          if (!r.ok) { m.querySelector("#is-err").textContent = r.error; return; }
          m.close(); loadVehicles();
        });
      });
    });
  }
  function wireVehicles() {
    $("pv-add").addEventListener("click", async function () {
      $("pv-err").textContent = "";
      if (!$("pv-res").value) { $("pv-err").textContent = "Choose the owner."; return; }
      var r = await MD.postJSON("/vehicles", { resident_id: Number($("pv-res").value), vehicle_number: $("pv-num").value, vehicle_type: $("pv-type").value });
      if (!r.ok) { $("pv-err").textContent = r.error; return; }
      $("pv-num").value = ""; loadVehicles();
    });
  }

  async function loadUsers() {
    var r = await MD.getJSON("/admin/users"), body = $("pu-body");
    if (!r.ok) { body.innerHTML = MD.emptyRow(7, r.error); return; }
    var me = MD.user();
    body.innerHTML = r.data.map(function (u) {
      return "<tr><td>" + esc(u.name) + "</td><td>" + esc(u.email) + "</td><td>" + esc(u.role) + "</td><td>" + esc(u.apartment_no || "—") + "</td><td>" + (u.last_login_at ? esc(MD.fmtTime(u.last_login_at)) : "never") + "</td><td>" + MD.badge(u.is_active ? "ACTIVE" : "BLOCKED") + (u.must_change_password ? ' <span class="muted">temp password</span>' : "") + '</td><td class="row-actions"><button data-reset="' + Number(u.id) + '">Reset password</button>' +
        (u.id === me.id ? "" : (u.is_active ? '<button class="deny" data-off="' + Number(u.id) + '">Deactivate</button>' : '<button class="approve" data-on="' + Number(u.id) + '">Activate</button>')) + "</td></tr>";
    }).join("");
    body.querySelectorAll("button[data-reset]").forEach(function (b) {
      b.addEventListener("click", async function () {
        if (!window.confirm("Reset this person's password? They will be signed out everywhere.")) return;
        var x = await MD.postJSON("/admin/users/" + b.getAttribute("data-reset") + "/reset-password", {});
        if (!x.ok) { alert(x.error); return; }
        var m = MD.modal('<h3 class="section-title">Temporary password</h3><p class="note-text">Give this to ' + esc(x.data.name) + ' now. It is shown only once and they must change it when they sign in.</p><div class="mono-box">' + esc(x.data.temporary_password) + '</div><div class="row-actions" style="margin-top:14px;"><button id="tp-close">Done</button></div>', loadUsers);
        m.querySelector("#tp-close").addEventListener("click", m.close);
      });
    });
    function toggle(attr, on) { body.querySelectorAll("button[" + attr + "]").forEach(function (b) { b.addEventListener("click", async function () { var x = await MD.postJSON("/admin/users/" + b.getAttribute(attr) + "/active", { is_active: on }); if (!x.ok) alert(x.error); loadUsers(); }); }); }
    toggle("data-off", false); toggle("data-on", true);
  }
  function wireUsers() {
    $("pu-add").addEventListener("click", async function () {
      var box = $("pu-result"); box.classList.remove("hidden");
      var r = await MD.postJSON("/admin/users", { name: $("pu-name").value, email: $("pu-email").value, role: $("pu-role").value, password: $("pu-pass").value || null });
      if (!r.ok) { box.textContent = "Could not create: " + r.error; return; }
      box.innerHTML = "Login created for <strong>" + esc(r.data.name) + "</strong>." + (r.data.temporary_password ? '<br/>Temporary password (shown once):<br/><span class="otp-code">' + esc(r.data.temporary_password) + "</span>" : "");
      $("pu-name").value = $("pu-email").value = $("pu-pass").value = ""; loadUsers();
    });
  }

  async function loadInvites() {
    refreshResSelects();
    var r = await MD.getJSON("/admin/invites"), body = $("pi-body");
    if (!r.ok) { body.innerHTML = MD.emptyRow(5, r.error); return; }
    body.innerHTML = r.data.length ? r.data.map(function (i) {
      return '<tr><td class="mono">' + (i.status === "ACTIVE" ? esc(i.code) : "••••••••") + "</td><td>" + esc(i.resident_label || "—") + "</td><td>" + esc(MD.fmtTime(i.created_at)) + "</td><td>" + esc(MD.fmtTime(i.expires_at)) + "</td><td>" + MD.badge(i.status) + "</td></tr>";
    }).join("") : MD.emptyRow(5, "No invites yet.");
  }
  function wireInvites() {
    $("pi-add").addEventListener("click", async function () {
      var box = $("pi-result"); box.classList.remove("hidden");
      if (!$("pi-res").value) { box.textContent = "Choose the flat first."; return; }
      var r = await MD.postJSON("/admin/invites", { resident_id: Number($("pi-res").value) });
      if (!r.ok) { box.textContent = "Could not create: " + r.error; return; }
      var msg = "Your ManaDwar invite code is " + r.data.code + ". Open the ManaDwar page, choose 'Have an invite code?' and use it within 7 days.";
      box.innerHTML = "Invite for <strong>" + esc(r.data.resident_label) + '</strong>:<br/><span class="otp-code">' + esc(r.data.code) + '</span><br/><a class="wa-btn" target="_blank" rel="noopener" href="https://wa.me/?text=' + encodeURIComponent(msg) + '">Share on WhatsApp</a>';
      loadInvites();
    });
  }

  // ================================================================== Logs (gate log + audit trail)
  var LOG_PAGE = 50, logOffset = 0, logTotal = 0;
  function logsPage() {
    var p = makePage("logs", '<h2 class="section-title">Logs</h2><div class="subtabs"></div>' +
      '<div class="sub" data-sub="gate"><div class="filter-row" style="grid-template-columns:2fr 1fr 1fr;"><input id="lg-q" placeholder="Search vehicle, tag, visitor, flat..." maxlength="80" /><select id="lg-method"><option value="">All methods</option><option>RFID</option><option>OTP</option><option>STAFF</option><option>DELIVERY</option></select><select id="lg-access"><option value="">All results</option><option>GRANTED</option><option>DENIED</option></select></div>' +
      '<div class="filter-row" style="grid-template-columns:1fr 1fr 1fr 1fr;"><select id="lg-dir"><option value="">In and out</option><option>IN</option><option>OUT</option></select><input type="date" id="lg-from" /><input type="date" id="lg-to" /><button class="action secondary" id="lg-csv" style="margin:0;">Download CSV</button></div>' +
      '<div id="lg-table"></div><div class="pager"><button class="action secondary" id="lg-prev">← Newer</button><span id="lg-info"></span><button class="action secondary" id="lg-next">Older →</button></div></div>' +
      '<div class="sub hidden" data-sub="audit"><input id="au-q" placeholder="Search action, person, detail..." maxlength="80" /><div id="au-table"></div></div>');
    subtabs(p, [["gate", "Gate log"], ["audit", "Admin audit trail"]], function (s) { if (s === "gate") loadLogs(); else loadAudit(); });
    return p;
  }
  function logQuery() {
    var q = new URLSearchParams();
    [["q", "lg-q"], ["method", "lg-method"], ["access", "lg-access"], ["direction", "lg-dir"], ["date_from", "lg-from"], ["date_to", "lg-to"]].forEach(function (x) { var v = $(x[1]).value.trim(); if (v) q.set(x[0], v); });
    return q;
  }
  async function loadLogs() {
    var q = logQuery(); q.set("limit", LOG_PAGE); q.set("offset", logOffset);
    var r = await MD.getJSON("/entry-logs?" + q.toString());
    if (!r.ok) { $("lg-table").textContent = r.error; return; }
    logTotal = Number(r.headers.get("X-Total-Count") || r.data.length);
    $("lg-table").innerHTML = logTable(r.data);
    $("lg-info").textContent = logTotal ? (logOffset + 1) + "–" + Math.min(logOffset + LOG_PAGE, logTotal) + " of " + logTotal : "No matching entries";
    $("lg-prev").disabled = logOffset === 0; $("lg-next").disabled = logOffset + LOG_PAGE >= logTotal;
  }
  async function loadAudit() {
    var r = await MD.getJSON("/audit-logs?limit=200&q=" + encodeURIComponent($("au-q").value.trim()));
    if (!r.ok) { $("au-table").textContent = r.error; return; }
    $("au-table").innerHTML = r.data.length ? '<div class="table-wrap"><table><thead><tr><th>When</th><th>Who</th><th>Action</th><th>Detail</th></tr></thead><tbody>' + r.data.map(function (a) {
      return "<tr><td>" + esc(MD.fmtTime(a.created_at)) + "</td><td>" + esc(a.user_name || "—") + '</td><td class="mono">' + esc(a.action) + "</td><td>" + esc(a.detail || "") + "</td></tr>";
    }).join("") + "</tbody></table></div>" : '<p class="note-text">Nothing recorded yet.</p>';
  }
  function wireLogs() {
    var reload = function () { logOffset = 0; loadLogs(); };
    ["lg-method", "lg-access", "lg-dir", "lg-from", "lg-to"].forEach(function (id) { $(id).addEventListener("change", reload); });
    var timer; $("lg-q").addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(reload, 300); });
    $("lg-prev").addEventListener("click", function () { logOffset = Math.max(0, logOffset - LOG_PAGE); loadLogs(); });
    $("lg-next").addEventListener("click", function () { logOffset += LOG_PAGE; loadLogs(); });
    $("lg-csv").addEventListener("click", function () { MD.downloadAuthed("/entry-logs/export.csv?" + logQuery().toString(), "manadwar-gate-log.csv"); });
    var t2; $("au-q").addEventListener("input", function () { clearTimeout(t2); t2 = setTimeout(loadAudit, 300); });
  }

  // ================================================================== Notices (admin)
  function noticesPage() {
    return makePage("notices", '<h2 class="section-title">Notice board</h2><div class="field-grid"><div><label for="nt-title">Title</label><input id="nt-title" maxlength="120" /></div><div><label for="nt-exp">Hide after (optional)</label><input type="datetime-local" id="nt-exp" /></div></div>' +
      '<label for="nt-body">Message</label><textarea id="nt-body" rows="4" maxlength="2000"></textarea><label class="check"><input type="checkbox" id="nt-pin" /> Pin to the top</label><button class="action" id="nt-post">Post notice</button><div class="error-text" id="nt-err"></div><div id="nt-list"></div>');
  }
  async function loadNotices() {
    var r = await MD.getJSON("/notices?include_expired=true"), box = $("nt-list");
    if (!r.ok) { box.textContent = r.error; return; }
    box.innerHTML = r.data.length ? r.data.map(function (n) {
      return '<div class="card" style="margin:14px 0 0;"><div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;"><strong>' + (n.pinned ? "📌 " : "") + esc(n.title) + '</strong><span class="muted">' + esc(MD.fmtDay(n.created_at)) + '</span></div><p style="white-space:pre-wrap;margin:8px 0;">' + esc(n.body) + '</p><div class="row-actions"><button data-readers="' + Number(n.id) + '">Read by ' + Number(n.read_count || 0) + " of " + Number(n.reader_total || 0) + '</button><button data-pin="' + Number(n.id) + '" data-to="' + (n.pinned ? "0" : "1") + '">' + (n.pinned ? "Unpin" : "Pin") + '</button><button class="deny" data-del="' + Number(n.id) + '">Delete</button></div></div>';
    }).join("") : '<p class="note-text">No notices yet.</p>';
    box.querySelectorAll("button[data-pin]").forEach(function (b) { b.addEventListener("click", async function () { await MD.postJSON("/notices/" + b.getAttribute("data-pin") + "/pin", { pinned: b.getAttribute("data-to") === "1" }); loadNotices(); }); });
    box.querySelectorAll("button[data-del]").forEach(function (b) { b.addEventListener("click", async function () { if (!window.confirm("Delete this notice for everyone?")) return; await MD.request("DELETE", "/notices/" + b.getAttribute("data-del")); loadNotices(); }); });
    box.querySelectorAll("button[data-readers]").forEach(function (b) {
      b.addEventListener("click", async function () {
        var x = await MD.getJSON("/notices/" + b.getAttribute("data-readers") + "/readers");
        if (!x.ok) { alert(x.error); return; }
        function names(list) { return list.length ? list.map(function (u) { return esc(u.name) + " (" + esc(u.apartment_no || "—") + ")"; }).join(", ") : "—"; }
        var m = MD.modal('<h3 class="section-title">Who has read it</h3><p><strong>Read (' + x.data.read.length + "):</strong> " + names(x.data.read) + "</p><p><strong>Not yet (" + x.data.unread.length + "):</strong> " + names(x.data.unread) + '</p><div class="row-actions"><button id="rd-close">Close</button></div>');
        m.querySelector("#rd-close").addEventListener("click", m.close);
      });
    });
  }
  function wireNotices() {
    $("nt-post").addEventListener("click", async function () {
      $("nt-err").textContent = "";
      var payload = { title: $("nt-title").value, body: $("nt-body").value, pinned: $("nt-pin").checked };
      if ($("nt-exp").value) payload.expires_at = new Date($("nt-exp").value).toISOString();
      var r = await MD.postJSON("/notices", payload);
      if (!r.ok) { $("nt-err").textContent = r.error; return; }
      $("nt-title").value = $("nt-body").value = $("nt-exp").value = ""; $("nt-pin").checked = false; loadNotices();
    });
  }

  // ================================================================== Attendance (admin)
  var attMonth = null;
  function attendancePage() {
    return makePage("attendance", '<h2 class="section-title">House staff attendance</h2><p class="note-text">Worked out from gate scans: first IN and last OUT each day.</p><div id="at-today"></div>' +
      '<h3 class="section-title" style="margin-top:22px;font-size:0.95rem;">Monthly report</h3><div class="filter-row" style="grid-template-columns:1fr 2fr auto;"><input type="month" id="at-month" /><span id="at-emp-slot"></span><button class="action secondary" id="at-csv" style="margin:0;">Download CSV</button></div><div id="at-report"></div>');
  }
  async function loadAttendance() {
    if (!attMonth) { var d = new Date(); attMonth = d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0"); }
    $("at-month").value = attMonth;
    $("at-emp-slot").innerHTML = '<select id="at-emp"><option value="">All employers</option>' + MD.residents().map(function (r) { return '<option value="' + Number(r.id) + '">' + esc(r.name) + " (" + esc(r.apartment_no) + ")</option>"; }).join("") + "</select>";
    $("at-emp").addEventListener("change", loadReport);
    var r = await MD.getJSON("/attendance/today");
    $("at-today").innerHTML = r.ok ? '<div class="tiles"><div class="tile"><b>' + r.data.present.length + '</b><span>In today</span></div><div class="tile"><b>' + r.data.inside_now + '</b><span>Inside now</span></div><div class="tile"><b>' + r.data.active_staff + "</b><span>Active staff</span></div></div>" +
      (r.data.present.length ? '<div class="table-wrap"><table><thead><tr><th>Name</th><th>Role</th><th>Employer</th><th>First in</th><th>Last out</th><th></th></tr></thead><tbody>' + r.data.present.map(function (s) { return "<tr><td>" + esc(s.name) + "</td><td>" + esc(s.role) + "</td><td>" + esc(s.employer) + "</td><td>" + esc(s.first_in) + "</td><td>" + esc(s.last_out || "—") + "</td><td>" + (s.inside ? MD.badge("INSIDE") : "") + "</td></tr>"; }).join("") + "</tbody></table></div>" : '<p class="note-text">Nobody has come in yet today.</p>') : esc(r.error);
    loadReport();
  }
  async function loadReport() {
    attMonth = $("at-month").value || attMonth;
    var emp = $("at-emp") ? $("at-emp").value : "";
    var r = await MD.getJSON("/attendance/report?month=" + attMonth + (emp ? "&employer_id=" + emp : ""));
    if (!r.ok) { $("at-report").textContent = r.error; return; }
    $("at-report").innerHTML = r.data.staff.length ? '<div class="table-wrap"><table><thead><tr><th>Name</th><th>Role</th><th>Employer</th><th>Days present</th></tr></thead><tbody>' + r.data.staff.map(function (s) { return "<tr><td>" + esc(s.name) + "</td><td>" + esc(s.role) + "</td><td>" + esc(s.employer) + "</td><td>" + Number(s.present_days) + "</td></tr>"; }).join("") + "</tbody></table></div>" : '<p class="note-text">No staff registered.</p>';
  }
  function wireAttendance() {
    $("at-month").addEventListener("change", loadReport);
    $("at-csv").addEventListener("click", function () { var emp = $("at-emp").value; MD.downloadAuthed("/attendance/export.csv?month=" + ($("at-month").value || attMonth) + (emp ? "&employer_id=" + emp : ""), "manadwar-attendance-" + ($("at-month").value || attMonth) + ".csv"); });
  }

  // ================================================================== start
  document.addEventListener("md:ready", async function () {
    var u = MD.user();
    if (u.role !== "GUARD" && u.role !== "ADMIN") return;
    isAdmin = u.role === "ADMIN";

    makePage("today", '<h2 class="section-title">Expected at the gate today</h2><div class="body">Loading…</div>').id = "page-today";
    var acct = makePage("account", '<div class="body"></div>');
    LOADERS.today = loadToday;
    LOADERS.account = function () { MD.renderAccount(acct.querySelector(".body")); };
    LOADERS.gate = function () {};
    LOADERS.staff = function () { MD.loadStaffDirectory(); };
    LOADERS.deliveries = function () { MD.refreshDeliveries(); };
    LOADERS.complaints = function () { MD.loadComplaints(); };

    if (isAdmin) {
      var dash = makePage("dashboard", '<h2 class="section-title">Dashboard</h2><div class="body">Loading…</div>'); dash.id = "page-dashboard";
      var pp = peoplePage(); wireResidents(); wireVehicles(); wireUsers(); wireInvites();
      var lp = logsPage(); wireLogs();
      noticesPage(); wireNotices();
      attendancePage(); wireAttendance();
      LOADERS.dashboard = loadDashboard;
      LOADERS.people = function () { loadResidentsTable(); };
      LOADERS.logs = function () { logOffset = 0; loadLogs(); };
      LOADERS.notices = loadNotices;
      LOADERS.attendance = loadAttendance;
      buildNav([["dashboard", "dashboard"], ["gate", "gate"], ["today", "today"], ["deliveries", "deliveries"], ["complaints", "complaints"], ["staff", "staff"], ["people", "people"], ["logs", "logs"], ["notices", "notices"], ["attendance", "attendance"], ["account", "account"]]);
    } else {
      buildNav([["gate", "gate"], ["today", "today"], ["staff", "staff"], ["account", "account"]]);
    }
    document.addEventListener("md:goto-account", function () { showPage("account"); });
    document.addEventListener("md:lang", function () {
      var items = isAdmin ? [["dashboard", "dashboard"], ["gate", "gate"], ["today", "today"], ["deliveries", "deliveries"], ["complaints", "complaints"], ["staff", "staff"], ["people", "people"], ["logs", "logs"], ["notices", "notices"], ["attendance", "attendance"], ["account", "account"]] : [["gate", "gate"], ["today", "today"], ["staff", "staff"], ["account", "account"]];
      buildNav(items); showPage(current);
    });

    // SOS: poll fast, and straight away when a new notification arrives
    pollSos();
    setInterval(function () { if (!document.hidden) pollSos(); }, 8000);
    document.addEventListener("md:notify-new", pollSos);

    await MD.loadResidents();
    refreshResSelectsSafe();
    showPage(isAdmin ? "dashboard" : "gate");
  });
  function refreshResSelectsSafe() { if ($("pv-res-slot")) refreshResSelects(); }
})();
