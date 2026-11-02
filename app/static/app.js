(function () {
  "use strict";

  const $ = function (id) { return document.getElementById(id); };

  // -------------------------------------------------------------
  // Session: JWT kept in localStorage (falls back to memory-only if the
  // browser blocks storage). Every API call sends it as a Bearer token.
  // -------------------------------------------------------------
  const TOKEN_KEY = "manadwar_token";
  const MSG_KEY = "manadwar_msg";

  function storeGet(key) { try { return window.localStorage.getItem(key); } catch (e) { return null; } }
  function storeSet(key, val) { try { window.localStorage.setItem(key, val); } catch (e) { /* memory-only */ } }
  function storeDel(key) { try { window.localStorage.removeItem(key); } catch (e) { /* ignore */ } }

  let token = storeGet(TOKEN_KEY);
  let currentUser = null;
  let isAdmin = false;

  function signOut(message) {
    storeDel(TOKEN_KEY);
    if (message) { try { window.sessionStorage.setItem(MSG_KEY, message); } catch (e) { /* ignore */ } }
    window.location.reload();
  }

  // -------------------------------------------------------------
  // Safety: residents type text that guards/admins later see rendered
  // in their own browsers, so everything interpolated into innerHTML
  // goes through esc().
  // -------------------------------------------------------------
  const ESC_MAP = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  function esc(value) {
    return String(value === null || value === undefined ? "" : value).replace(/[&<>"']/g, function (c) { return ESC_MAP[c]; });
  }

  function errorText(data, status) {
    const detail = data && data.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail.length) {
      return detail.map(function (d) { return d.msg || JSON.stringify(d); }).join("; ");
    }
    return "Request failed (" + status + ")";
  }

  // -------------------------------------------------------------
  // Fetch helpers
  // -------------------------------------------------------------
  async function request(method, url, body, isForm) {
    const headers = {};
    if (token) headers["Authorization"] = "Bearer " + token;
    const opts = { method: method, headers: headers };
    if (body !== undefined) {
      if (isForm) {
        opts.body = body; // FormData: the browser sets the multipart boundary itself
      } else {
        headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(body);
      }
    }
    const usedToken = token;
    try {
      const res = await fetch(url, opts);
      const data = await res.json().catch(function () { return {}; });
      // Only sign out if the rejected token is still the current one: after a password
      // change (or silent refresh) a slow in-flight request may carry the old token.
      if (res.status === 401 && token && token === usedToken) {
        signOut("Your session expired. Please sign in again.");
        return { ok: false, status: 401, data: data, error: "Session expired." };
      }
      if (!res.ok) {
        return { ok: false, status: res.status, data: data, error: errorText(data, res.status), headers: res.headers };
      }
      return { ok: true, status: res.status, data: data, headers: res.headers };
    } catch (err) {
      return { ok: false, status: 0, data: null, error: "Network error: could not reach the server." };
    }
  }

  function postJSON(url, body) { return request("POST", url, body); }
  function postForm(url, formData) { return request("POST", url, formData, true); }
  function getJSON(url) { return request("GET", url); }

  // /auth/login expects a form-encoded body (OAuth2 password flow), not JSON.
  async function loginRequest(email, password) {
    const form = new URLSearchParams();
    form.set("username", email);
    form.set("password", password);
    try {
      const res = await fetch("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: form.toString(),
      });
      const data = await res.json().catch(function () { return {}; });
      if (!res.ok) return { ok: false, error: errorText(data, res.status) };
      return { ok: true, token: data.access_token };
    } catch (err) {
      return { ok: false, error: "Network error: could not reach the server." };
    }
  }

  function parseUTC(ts) {
    if (!ts) return null;
    // Backend returns naive UTC timestamps with no "Z" suffix; append one
    // so the browser interprets them as UTC rather than local time.
    const iso = ts.endsWith("Z") ? ts : ts + "Z";
    return new Date(iso);
  }

  function fmtTime(ts) {
    const d = parseUTC(ts);
    return d ? d.toLocaleString() : "—";
  }

  function badge(text) {
    const cls = String(text).toLowerCase().replace(/[^a-z_]/g, "");
    return '<span class="badge ' + cls + '">' + esc(text) + "</span>";
  }

  function emptyRow(cols, text) {
    return '<tr class="empty-row"><td colspan="' + cols + '">' + esc(text) + "</td></tr>";
  }

  // -------------------------------------------------------------
  // Generic tab switcher
  // -------------------------------------------------------------
  function wireTabs(tabButtons, dataAttr, panelIds) {
    tabButtons.forEach(function (btn) {
      btn.addEventListener("click", function () {
        tabButtons.forEach(function (b) { b.classList.remove("active"); });
        btn.classList.add("active");
        const target = btn.getAttribute(dataAttr);
        panelIds.forEach(function (pid) {
          const el = $(pid);
          if (!el) return;
          el.classList.toggle("active", pid === target);
        });
      });
    });
  }

  wireTabs(
    [$("tab-vehicle"), $("tab-visitor"), $("tab-delivery"), $("tab-staff")],
    "data-panel",
    ["panel-vehicle", "panel-visitor", "panel-delivery", "panel-staff"]
  );
  wireTabs([$("vtab-verify"), $("vtab-register")], "data-vpanel", ["vpanel-verify", "vpanel-register"]);
  wireTabs(
    [$("rtab-visitors"), $("rtab-deliveries"), $("rtab-complaints")],
    "data-rpanel",
    ["rpanel-visitors", "rpanel-deliveries", "rpanel-complaints"]
  );

  // =============================================================
  // GUARD / ADMIN CONSOLE
  // =============================================================

  const statusScreen = $("status-screen");
  const statusMessage = $("status-message");
  const statusDetail = $("status-detail");

  function setStatus(state, message, detail) {
    statusScreen.classList.remove("state-idle", "state-granted", "state-denied");
    statusScreen.classList.add("state-" + state);
    statusMessage.textContent = message;
    statusDetail.textContent = detail || "";
    if (window.MD && typeof window.MD.onStatus === "function") window.MD.onStatus(state, message, detail || "");
  }

  // Residents: loaded once, used to populate every resident dropdown/picker.
  let residentsById = {};
  let allResidents = [];

  // Searchable resident picker: a text box that filters residents by name,
  // flat number or phone, and stores the chosen resident id in a hidden
  // input (same id the old <select> had, so callers just read .value).
  function makeResidentPicker(valueId) {
    const input = $(valueId + "-search");
    const hidden = $(valueId);
    const list = $(valueId + "-list");

    function render() {
      const q = input.value.trim().toLowerCase();
      const matches = allResidents.filter(function (r) {
        return !q || (r.name + " " + r.apartment_no + " " + (r.phone || "")).toLowerCase().indexOf(q) !== -1;
      }).slice(0, 8);
      list.innerHTML = matches.length
        ? matches.map(function (r) {
            return '<div class="picker-item" data-id="' + Number(r.id) + '"><strong>' + esc(r.name) + "</strong><span>" + esc(r.apartment_no) + "</span></div>";
          }).join("")
        : '<div class="picker-empty">No matching resident</div>';
      list.classList.remove("hidden");
    }

    function choose(id) {
      const r = residentsById[id];
      if (!r) return;
      hidden.value = String(r.id);
      input.value = r.name + " (" + r.apartment_no + ")";
      list.classList.add("hidden");
    }

    input.addEventListener("input", function () { hidden.value = ""; render(); });
    input.addEventListener("focus", render);
    input.addEventListener("blur", function () { list.classList.add("hidden"); });
    input.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter") {
        ev.preventDefault();
        const first = list.querySelector(".picker-item");
        if (first) choose(Number(first.getAttribute("data-id")));
      } else if (ev.key === "Escape") {
        list.classList.add("hidden");
      }
    });
    // mousedown (not click) so the input doesn't blur before we read the choice
    list.addEventListener("mousedown", function (ev) {
      const item = ev.target.closest(".picker-item");
      if (item) { ev.preventDefault(); choose(Number(item.getAttribute("data-id"))); }
    });

    return { reset: function () { input.value = ""; hidden.value = ""; } };
  }

  const hostPicker = makeResidentPicker("reg-host");
  const walkinPicker = makeResidentPicker("del-host");

  async function loadResidents() {
    const result = await getJSON("/residents");
    if (!result.ok) return;
    const residents = result.data;
    allResidents = residents;
    residentsById = {};
    residents.forEach(function (r) { residentsById[r.id] = r; });

    // Staff employer dropdown is optional (security guards are often
    // society-employed, not tied to one resident), so it gets a blank
    // "none" option the others don't.
    const employerSel = $("staffreg-employer");
    if (employerSel) {
      employerSel.innerHTML = "";
      const noneOpt = document.createElement("option");
      noneOpt.value = "";
      noneOpt.textContent = "— No specific resident (society-employed) —";
      employerSel.appendChild(noneOpt);
      residents.forEach(function (r) {
        const opt = document.createElement("option");
        opt.value = r.id;
        opt.textContent = r.name + " (" + r.apartment_no + ")";
        employerSel.appendChild(opt);
      });
    }
  }

  function residentLabel(id) {
    const r = residentsById[id];
    return r ? (r.name + " (" + r.apartment_no + ")") : ("#" + id);
  }

  // ---- Vehicle tab
  $("btn-verify-rfid").addEventListener("click", async function () {
    const value = $("rfid-input").value.trim();
    const direction = $("rfid-direction").value;
    if (!value) {
      setStatus("denied", "NO CREDENTIAL", "Enter an RFID/FASTag code first.");
      return;
    }
    setStatus("idle", "CHECKING...", "");
    const result = await postJSON("/verify-rfid", { credential_value: value, gate_name: "MAIN_GATE", direction: direction });
    if (!result.ok) {
      setStatus("denied", "ERROR", result.error);
      return;
    }
    const data = result.data;
    if (data.access === "GRANTED") {
      setStatus("granted", "ACCESS GRANTED", (data.vehicle_number || "") + (data.resident_name ? " — " + data.resident_name : ""));
    } else {
      setStatus("denied", "ACCESS DENIED", data.message || "");
    }
  });

  // ---- Staff tab: verify staff ID-card credential
  $("btn-verify-staff").addEventListener("click", async function () {
    const value = $("staff-credential-input").value.trim();
    const direction = $("staff-direction").value;
    if (!value) {
      setStatus("denied", "NO CREDENTIAL", "Enter a staff ID-card code first.");
      return;
    }
    setStatus("idle", "CHECKING...", "");
    const result = await postJSON("/verify-staff", { credential_value: value, gate_name: "MAIN_GATE", direction: direction });
    if (!result.ok) {
      setStatus("denied", "ERROR", result.error);
      return;
    }
    const data = result.data;
    if (data.access === "GRANTED") {
      setStatus("granted", "ACCESS GRANTED", (data.staff_name || "") + (data.role ? " — " + data.role : "") + (data.employer_name ? " (" + data.employer_name + ")" : ""));
    } else {
      setStatus("denied", "ACCESS DENIED", data.message || "");
    }
  });

  // ---- Visitor tab: verify OTP
  async function verifyOtpCode(code) {
    setStatus("idle", "CHECKING...", "");
    const result = await postJSON("/verify-otp", { otp_code: code, gate_name: "MAIN_GATE", direction: "IN" });
    if (!result.ok) {
      setStatus("denied", "ERROR", result.error);
      return;
    }
    const data = result.data;
    if (data.access === "GRANTED") {
      setStatus("granted", "ACCESS GRANTED", (data.visitor_name || "") + (data.recurring ? " (regular visitor)" : "") +
        (data.host_resident_name ? " visiting " + data.host_resident_name : "") + (data.host_apartment ? " (" + data.host_apartment + ")" : "") +
        (data.vehicle_number ? " — vehicle " + data.vehicle_number : ""));
      if (window.MD && typeof window.MD.onVerified === "function") window.MD.onVerified("otp", data);
    } else {
      setStatus("denied", "ACCESS DENIED", data.message || "");
    }
  }

  $("btn-verify-otp").addEventListener("click", async function () {
    const code = $("otp-input").value.trim();
    if (!code) {
      setStatus("denied", "NO OTP", "Enter the OTP code first.");
      return;
    }
    await verifyOtpCode(code);
  });

  // ---- QR scanning (v7.2): the visitor's QR carries the same OTP, so a scan
  // runs exactly the same check as typing it. Camera frames are decoded in
  // this browser and never uploaded.
  const SCAN_COOLDOWN_MS = 5000;   // the same pass held in front of the camera is counted once
  let scanStream = null, scanRunning = false, scanBusy = false;
  let lastScan = { text: "", at: 0 };
  const scanCanvas = document.createElement("canvas");
  const scanCtx = scanCanvas.getContext("2d", { willReadFrequently: true });

  // Our passes are "ManaDwar Visitor Pass ... OTP: 123456 ..."; a bare
  // 6-digit QR is accepted too. Anything else is not ours.
  function otpFromQr(text) {
    const t = String(text || "").trim();
    if (/^\d{6}$/.test(t)) return t;
    if (!/^ManaDwar Visitor Pass/i.test(t)) return null;
    const m = /(?:^|\n)\s*OTP:\s*(\d{6})\s*(?:\n|$)/i.exec(t);
    return m ? m[1] : null;
  }

  async function handleScanned(text, fromPhoto) {
    const now = Date.now();
    if (!fromPhoto && text === lastScan.text && now - lastScan.at < SCAN_COOLDOWN_MS) return;
    lastScan = { text: text, at: now };
    const otp = otpFromQr(text);
    if (!otp) {
      setStatus("denied", "ACCESS DENIED", "Not a ManaDwar visitor pass.");
      return;
    }
    scanBusy = true;
    try { await verifyOtpCode(otp); } finally { scanBusy = false; lastScan.at = Date.now(); }
  }

  function decodeFrom(source, sw, sh, maxWidth, both) {
    const w = Math.min(maxWidth, sw), h = Math.max(1, Math.round(sh * w / sw));
    scanCanvas.width = w; scanCanvas.height = h;
    scanCtx.drawImage(source, 0, 0, w, h);
    const img = scanCtx.getImageData(0, 0, w, h);
    const code = jsQR(img.data, w, h, { inversionAttempts: both ? "attemptBoth" : "dontInvert" });
    return code && code.data ? code.data : null;
  }

  function scanTick() {
    if (!scanRunning) return;
    const v = $("scan-video");
    if (v.readyState >= 2 && v.videoWidth && !scanBusy) {
      const text = decodeFrom(v, v.videoWidth, v.videoHeight, 640, false);
      if (text) handleScanned(text, false);
    }
    setTimeout(scanTick, 120);
  }

  function stopScan() {
    scanRunning = false;
    if (scanStream) { scanStream.getTracks().forEach(function (t) { t.stop(); }); scanStream = null; }
    $("scan-video").srcObject = null;
    $("scan-view").classList.add("hidden");
    $("btn-scan-stop").classList.add("hidden");
    $("btn-scan-start").classList.remove("hidden");
  }

  async function startScan() {
    const note = $("scan-note");
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.isSecureContext) {
      note.textContent = "Live camera isn't available on this connection (browsers only allow it on localhost or HTTPS). Use 'Take photo of QR' instead, or type the OTP.";
      return;
    }
    try {
      scanStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false });
    } catch (e) {
      note.textContent = (e && e.name === "NotAllowedError")
        ? "Camera permission is blocked. Allow it in the browser, or use 'Take photo of QR', or type the OTP."
        : "No camera could be started. Use 'Take photo of QR' instead, or type the OTP.";
      return;
    }
    const video = $("scan-video");
    video.srcObject = scanStream;
    try { await video.play(); } catch (e) { /* autoplay quirks: frames still arrive */ }
    $("scan-view").classList.remove("hidden");
    $("btn-scan-start").classList.add("hidden");
    $("btn-scan-stop").classList.remove("hidden");
    note.textContent = "Camera on. Hold the visitor's QR inside the frame; the result shows in the screen above.";
    lastScan = { text: "", at: 0 };
    scanRunning = true;
    scanTick();
  }

  function loadImageFile(file) {
    return new Promise(function (resolve, reject) {
      const url = URL.createObjectURL(file);
      const img = new Image();
      img.onload = function () { URL.revokeObjectURL(url); resolve(img); };
      img.onerror = function () { URL.revokeObjectURL(url); reject(new Error("bad image")); };
      img.src = url;
    });
  }

  $("btn-scan-start").addEventListener("click", startScan);
  $("btn-scan-stop").addEventListener("click", function () {
    stopScan();
    $("scan-note").textContent = "Camera off.";
  });

  $("qr-photo").addEventListener("change", async function () {
    const input = this;
    const file = input.files && input.files[0];
    if (!file) return;
    setStatus("idle", "READING PHOTO...", "");
    let text = null;
    try {
      const img = await loadImageFile(file);
      const sw = img.naturalWidth || img.width, sh = img.naturalHeight || img.height;
      const widths = [1280, 800, 480];
      for (let i = 0; i < widths.length && !text; i++) text = decodeFrom(img, sw, sh, widths[i], true);
    } catch (e) {
      setStatus("denied", "UNREADABLE PHOTO", "That file couldn't be opened as a picture. Try again, or type the OTP.");
      input.value = "";
      return;
    }
    input.value = "";   // so taking the same photo again still fires
    if (!text) {
      setStatus("denied", "NO QR FOUND", "Move closer so the QR fills the photo and try again, or type the OTP.");
      return;
    }
    await handleScanned(text, true);
  });

  // The camera only runs while the Verify OTP screen is in front.
  [$("vtab-register"), $("tab-vehicle"), $("tab-delivery"), $("tab-staff")].forEach(function (b) { b.addEventListener("click", stopScan); });
  document.addEventListener("visibilitychange", function () { if (document.hidden) stopScan(); });

  // ---- Visitor tab: register visitor (guard/admin, on behalf of any host)
  const visitTypeSelect = $("reg-visit-type");
  const longTermFields = $("reg-longterm-fields");

  function syncLongTermFields() {
    longTermFields.classList.toggle("hidden", visitTypeSelect.value !== "LONG_TERM");
    $("reg-short-wrap").classList.toggle("hidden", visitTypeSelect.value === "LONG_TERM");
  }
  visitTypeSelect.addEventListener("change", syncLongTermFields);
  syncLongTermFields();

  $("btn-register-visitor").addEventListener("click", async function () {
    const resultBox = $("reg-result");
    resultBox.classList.add("hidden");

    const name = $("reg-name").value.trim();
    const phone = $("reg-phone").value.trim();
    const hostSelect = $("reg-host");
    const hostId = hostSelect.value ? parseInt(hostSelect.value, 10) : null;
    const visitType = visitTypeSelect.value;
    const purpose = $("reg-purpose").value.trim();

    if (!name || !phone || !hostId) {
      resultBox.classList.remove("hidden");
      resultBox.textContent = "Please fill in visitor name, phone, and host resident.";
      return;
    }

    const payload = { name: name, phone: phone, host_resident_id: hostId, visit_type: visitType, purpose: purpose || null };
    if ($("reg-from").value) payload.valid_from = new Date($("reg-from").value).toISOString();
    if (visitType === "SHORT_TERM" && $("reg-short-vnum").value.trim()) payload.vehicle_number = $("reg-short-vnum").value.trim();

    if (visitType === "LONG_TERM") {
      const validUntilRaw = $("reg-valid-until").value;
      if (!validUntilRaw) {
        resultBox.classList.remove("hidden");
        resultBox.textContent = "Long-term visits require a 'valid until' date/time.";
        return;
      }
      payload.valid_until = new Date(validUntilRaw).toISOString();
      const vehicleNumber = $("reg-vehicle-number").value.trim();
      const vehicleType = $("reg-vehicle-type").value;
      if (vehicleNumber) {
        payload.vehicle_number = vehicleNumber;
        payload.vehicle_type = vehicleType || "CAR";
      }
    }

    const result = await postJSON("/visitors", payload);
    resultBox.classList.remove("hidden");
    if (!result.ok) {
      resultBox.innerHTML = "Registration failed: " + esc(result.error);
      return;
    }

    const visitor = result.data;
    resultBox.innerHTML =
      "Visitor <strong>" + esc(visitor.name) + "</strong> registered.<br/>" +
      "Share this OTP for gate entry. It works for every entry until " + esc(fmtTime(visitor.valid_until)) + ":<br/>" +
      '<span class="otp-code">' + esc(visitor.otp_code) + "</span>";

    setStatus("idle", "VISITOR REGISTERED", visitor.name + " — OTP issued" + (visitor.status === "SCHEDULED" ? " (starts " + fmtTime(visitor.valid_from) + ")" : "") + ".");
    hostPicker.reset();
  });

  // ---- Delivery tab (v7.0): residents announce, the guard matches arrivals
  function deliveryWhen(d) {
    if (d.source === "WALK_IN") return "Arrived " + fmtTime(d.requested_at);
    return fmtTime(d.expected_from) + " → " + fmtTime(d.expected_until);
  }

  function deliveryWho(d) {
    let extra = [];
    if (d.courier_name) extra.push(esc(d.courier_name));
    if (d.courier_phone) extra.push(esc(d.courier_phone));
    if (d.description) extra.push(esc(d.description));
    return "<strong>" + esc(d.platform || "—") + "</strong>" +
      (extra.length ? '<div class="note-text" style="margin:2px 0 0;">' + extra.join(" · ") + "</div>" : "");
  }

  const STATUS_LABEL = {
    EXPECTED: "Expected", AWAITING_APPROVAL: "Awaiting resident", APPROVED: "Approved",
    ADMITTED: "Let in", DENIED: "Denied", CANCELLED: "Cancelled", EXPIRED: "Expired",
  };
  function deliveryBadge(status) {
    return '<span class="badge ' + String(status).toLowerCase() + '">' + esc(STATUS_LABEL[status] || status) + "</span>";
  }

  let openDeliveries = [];

  function renderOpenDeliveries() {
    const body = $("del-open-body");
    const q = $("del-search").value.trim().toLowerCase();
    const rows = openDeliveries.filter(function (d) {
      if (!q) return true;
      return [d.platform || "", d.courier_name || "", d.description || "", residentLabel(d.host_resident_id)].join(" ").toLowerCase().indexOf(q) !== -1;
    });
    if (rows.length === 0) {
      body.innerHTML = emptyRow(5, openDeliveries.length ? "No waiting deliveries match your search." : "No deliveries waiting right now.");
      return;
    }
    body.innerHTML = rows.map(function (d) {
      const id = Number(d.id);
      let actions;
      if (d.status === "AWAITING_APPROVAL") {
        actions = '<span class="note-text" style="margin:0;align-self:center;">Waiting for resident</span><button class="deny" data-refuse-id="' + id + '">Refuse</button>';
      } else {
        actions = '<button class="approve" data-admit-id="' + id + '">Let in</button><button class="deny" data-refuse-id="' + id + '">Refuse</button>';
      }
      return "<tr>" +
        "<td>" + deliveryWho(d) + "</td>" +
        "<td>" + esc(residentLabel(d.host_resident_id)) + "</td>" +
        "<td>" + esc(deliveryWhen(d)) + "</td>" +
        "<td>" + deliveryBadge(d.status) + "</td>" +
        '<td class="row-actions">' + actions + "</td>" +
      "</tr>";
    }).join("");

    body.querySelectorAll("button[data-admit-id]").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        const d = openDeliveries.find(function (x) { return String(x.id) === btn.getAttribute("data-admit-id"); });
        const result = await postJSON("/deliveries/" + btn.getAttribute("data-admit-id") + "/admit", { gate_name: "MAIN_GATE" });
        if (!result.ok) { setStatus("denied", "CANNOT LET IN", result.error); await refreshDeliveries(); return; }
        setStatus("granted", "DELIVERY ADMITTED", (d && d.platform ? d.platform + " — " : "") + (d ? residentLabel(d.host_resident_id) : ""));
        if (window.MD && typeof window.MD.onAdmitted === "function") window.MD.onAdmitted(result.data);
        await refreshDeliveries();
      });
    });
    body.querySelectorAll("button[data-refuse-id]").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        const result = await postJSON("/deliveries/" + btn.getAttribute("data-refuse-id") + "/refuse", { gate_name: "MAIN_GATE" });
        if (!result.ok) { setStatus("denied", "ERROR", result.error); await refreshDeliveries(); return; }
        setStatus("denied", "DELIVERY REFUSED", result.data.platform || "Courier turned away.");
        await refreshDeliveries();
      });
    });
  }

  async function loadOpenDeliveries() {
    const result = await getJSON("/deliveries?needs_action=true");
    if (!result.ok) {
      $("del-open-body").innerHTML = emptyRow(5, "Could not load deliveries: " + result.error);
      return;
    }
    openDeliveries = result.data;
    renderOpenDeliveries();
  }

  $("del-search").addEventListener("input", renderOpenDeliveries);
  $("btn-refresh-deliveries").addEventListener("click", refreshDeliveries);

  $("btn-walkin-delivery").addEventListener("click", async function () {
    const box = $("del-result");
    box.classList.remove("hidden");
    const hostId = $("del-host").value ? parseInt($("del-host").value, 10) : null;
    const platform = $("del-platform").value.trim();
    const courier = $("del-courier-name").value.trim();
    if (!hostId) { box.textContent = "Please choose the resident (search by name or flat number)."; return; }
    if (!platform && !courier) { box.textContent = "Enter the platform or the courier's name."; return; }

    const result = await postJSON("/deliveries/walk-in", {
      host_resident_id: hostId,
      platform: platform || null,
      courier_name: courier || null,
      courier_phone: $("del-courier-phone").value.trim() || null,
      description: $("del-note").value.trim() || null,
    });
    if (!result.ok) { box.innerHTML = "Could not log it: " + esc(result.error); return; }
    const wd = result.data;
    if (wd.rule_applied) {
      const denied = wd.status === "DENIED";
      box.innerHTML = "<strong>" + esc(residentLabel(hostId)) + "</strong> has a standing rule for this company.<br/>" + esc(wd.rule_applied) + "." +
        (denied ? " Turn the courier away." : (wd.leave_at_gate ? " Take the parcel at the gate; the courier does not go up." : " You can let the courier in."));
      if (denied) setStatus("denied", "DELIVERY NOT ALLOWED", (platform || courier) + " — " + wd.rule_applied);
      else setStatus("granted", "RESIDENT PRE-APPROVED", (platform || courier) + " — " + (wd.leave_at_gate ? "leave at gate" : "let in"));
    } else {
      box.innerHTML = "Asked <strong>" + esc(residentLabel(hostId)) + "</strong> to approve. It will show above as <em>Awaiting resident</em>.";
      setStatus("idle", "WAITING FOR RESIDENT", (platform || courier) + " — " + residentLabel(hostId));
    }
    walkinPicker.reset();
    ["del-platform", "del-courier-name", "del-courier-phone", "del-note"].forEach(function (id) { $(id).value = ""; });
    await refreshDeliveries();
  });

  // ---- Admin overview: summary tiles + searchable history with overrides
  let deliveryHistory = [];

  async function loadDeliveryOverview() {
    const sum = await getJSON("/deliveries/summary");
    if (sum.ok) {
      const p = sum.data.pending_now || {}, l = sum.data.last_24h || {};
      const tiles = [
        ["Expected now", p.EXPECTED || 0], ["Awaiting resident", p.AWAITING_APPROVAL || 0],
        ["Let in (24h)", l.ADMITTED || 0], ["Refused (24h)", l.DENIED || 0], ["Total (24h)", l.TOTAL || 0],
      ];
      $("del-tiles").innerHTML = tiles.map(function (t) { return '<div class="tile"><b>' + Number(t[1]) + "</b><span>" + esc(t[0]) + "</span></div>"; }).join("");
      const tops = sum.data.top_platforms_24h || [];
      $("del-top-platforms").textContent = tops.length
        ? "Busiest platforms (24h): " + tops.map(function (t) { return t.platform + " (" + t.count + ")"; }).join(", ")
        : "No deliveries in the last 24 hours.";
    }
    const params = [];
    if ($("delh-status").value) params.push("status=" + encodeURIComponent($("delh-status").value));
    if ($("delh-days").value) params.push("days=" + encodeURIComponent($("delh-days").value));
    params.push("limit=500");
    const hist = await getJSON("/deliveries?" + params.join("&"));
    if (!hist.ok) { $("delh-body").innerHTML = emptyRow(7, "Could not load deliveries: " + hist.error); return; }
    deliveryHistory = hist.data;
    renderDeliveryHistory();
  }

  function renderDeliveryHistory() {
    const body = $("delh-body");
    const q = $("delh-search").value.trim().toLowerCase();
    const rows = deliveryHistory.filter(function (d) {
      if (!q) return true;
      return [d.platform || "", d.courier_name || "", d.description || "", residentLabel(d.host_resident_id)].join(" ").toLowerCase().indexOf(q) !== -1;
    });
    $("delh-count").textContent = "Showing " + rows.length + " of " + deliveryHistory.length;
    if (rows.length === 0) { body.innerHTML = emptyRow(7, deliveryHistory.length ? "No deliveries match your search." : "No deliveries in this period."); return; }
    body.innerHTML = rows.map(function (d) {
      const id = Number(d.id);
      let actions = "—";
      if (d.status === "AWAITING_APPROVAL") {
        actions = '<button class="approve" data-ov-approve="' + id + '">Approve</button><button class="deny" data-ov-deny="' + id + '">Deny</button>';
      } else if (d.status === "EXPECTED" || d.status === "APPROVED") {
        actions = '<button data-ov-cancel="' + id + '">Cancel</button>';
      }
      return "<tr>" +
        "<td>" + id + "</td>" +
        "<td>" + esc(residentLabel(d.host_resident_id)) + "</td>" +
        "<td>" + deliveryWho(d) + "</td>" +
        "<td>" + esc(d.source === "WALK_IN" ? "Unexpected" : "Announced") + "</td>" +
        "<td>" + esc(deliveryWhen(d)) + "</td>" +
        "<td>" + deliveryBadge(d.status) + "</td>" +
        '<td class="row-actions">' + actions + "</td>" +
      "</tr>";
    }).join("");

    async function act(path, payload) {
      const result = await postJSON(path, payload);
      if (!result.ok) alert("Could not update delivery: " + result.error);
      await refreshDeliveries();
    }
    body.querySelectorAll("button[data-ov-approve]").forEach(function (b) { b.addEventListener("click", function () { act("/deliveries/" + b.getAttribute("data-ov-approve") + "/decision", { approve: true }); }); });
    body.querySelectorAll("button[data-ov-deny]").forEach(function (b) { b.addEventListener("click", function () { act("/deliveries/" + b.getAttribute("data-ov-deny") + "/decision", { approve: false }); }); });
    body.querySelectorAll("button[data-ov-cancel]").forEach(function (b) { b.addEventListener("click", function () { act("/deliveries/" + b.getAttribute("data-ov-cancel") + "/cancel"); }); });
  }

  $("delh-search").addEventListener("input", renderDeliveryHistory);
  $("delh-status").addEventListener("change", loadDeliveryOverview);
  $("delh-days").addEventListener("change", loadDeliveryOverview);

  async function refreshDeliveries() {
    await loadOpenDeliveries();
    if (isAdmin) await loadDeliveryOverview();
  }

  // Keep the gate screen fresh without anyone pressing Refresh.
  setInterval(function () {
    if (document.hidden) return;
    if (!$("staff-view").classList.contains("hidden") && $("panel-delivery").classList.contains("active")) refreshDeliveries();
    if (!$("resident-view").classList.contains("hidden") && $("rpanel-deliveries").classList.contains("active")) loadMyDeliveries();
  }, 10000);

  // ---- Complaint photos need the auth header, so they are fetched with it
  // and shown from a temporary blob URL (a plain <img src> can't send it).
  async function openComplaintPhoto(complaintId) {
    try {
      const res = await fetch("/complaints/" + complaintId + "/image", { headers: { "Authorization": "Bearer " + token } });
      if (!res.ok) { alert("Could not load the photo."); return; }
      const blob = await res.blob();
      const img = $("img-modal-img");
      if (img.getAttribute("src")) URL.revokeObjectURL(img.getAttribute("src"));
      img.src = URL.createObjectURL(blob);
      $("img-modal").classList.remove("hidden");
    } catch (e) {
      alert("Could not load the photo.");
    }
  }

  function closePhotoModal() {
    const img = $("img-modal-img");
    if (img.getAttribute("src")) URL.revokeObjectURL(img.getAttribute("src"));
    img.removeAttribute("src");
    $("img-modal").classList.add("hidden");
  }
  $("img-modal-close").addEventListener("click", closePhotoModal);
  $("img-modal").addEventListener("click", function (ev) { if (ev.target === $("img-modal")) closePhotoModal(); });
  document.addEventListener("keydown", function (ev) { if (ev.key === "Escape") closePhotoModal(); });

  // ---- Complaint categories come from the server (single source of truth)
  let complaintCategories = [];

  async function loadComplaintCategories() {
    if (complaintCategories.length) return;
    const r = await getJSON("/complaints/categories");
    if (r.ok) complaintCategories = r.data;
  }

  function fillCategorySelect(selectId, firstLabel) {
    const sel = $(selectId);
    sel.innerHTML = "";
    const first = document.createElement("option");
    first.value = "";
    first.textContent = firstLabel;
    sel.appendChild(first);
    complaintCategories.forEach(function (c) {
      const opt = document.createElement("option");
      opt.value = c;
      opt.textContent = c;
      sel.appendChild(opt);
    });
  }

  // ---- Complaints (admin)
  const complaintResidentPicker = makeResidentPicker("comp-resident");
  let complaintsCache = [];

  $("btn-create-complaint").addEventListener("click", async function () {
    const residentId = $("comp-resident").value ? parseInt($("comp-resident").value, 10) : null;
    const category = $("comp-category").value;
    const description = $("comp-description").value.trim();

    if (!residentId || !category || !description) {
      alert("Please choose a resident, pick a category, and describe the complaint.");
      return;
    }

    const result = await postJSON("/complaints", { resident_id: residentId, category: category, description: description });
    if (!result.ok) {
      alert("Could not raise complaint: " + result.error);
      return;
    }
    $("comp-description").value = "";
    $("comp-category").value = "";
    complaintResidentPicker.reset();
    await loadComplaints();
  });

  function renderComplaints() {
    const body = $("complaints-body");
    const status = $("comp-filter-status").value;
    const category = $("comp-filter-category").value;
    const q = $("comp-search").value.trim().toLowerCase();

    const rows = complaintsCache.filter(function (c) {
      if (status && c.status !== status) return false;
      if (category && c.category !== category) return false;
      if (q) {
        const hay = [residentLabel(c.resident_id), c.category || "", c.description, c.resolution_notes || ""].join(" ").toLowerCase();
        if (hay.indexOf(q) === -1) return false;
      }
      return true;
    });

    $("comp-count").textContent = "Showing " + rows.length + " of " + complaintsCache.length;
    if (rows.length === 0) {
      body.innerHTML = emptyRow(8, complaintsCache.length ? "No complaints match these filters." : "No complaints yet.");
      return;
    }

    body.innerHTML = rows.map(function (c) {
      const id = Number(c.id);
      let actions = "—";
      if (c.status === "OPEN") {
        actions = '<button data-start-id="' + id + '">Start</button> <button data-resolve-id="' + id + '">Resolve</button>';
      } else if (c.status === "IN_PROGRESS") {
        actions = '<button data-resolve-id="' + id + '">Resolve</button>';
      }
      actions += ' <button data-thread-id="' + id + '">' + (actions === "—" ? "Open" : "Thread") + "</button>";
      if (actions.indexOf("—") === 0) actions = actions.replace("—", "");
      const photo = c.has_image ? '<button data-photo-id="' + id + '">View</button>' : "—";
      const notes = (c.resolution_notes
        ? '<div class="note-text" style="margin:4px 0 0;">Resolution: ' + esc(c.resolution_notes) + "</div>"
        : "") + (c.assigned_to ? '<div class="note-text" style="margin:4px 0 0;">Assigned to: ' + esc(c.assigned_to) + "</div>" : "");
      return "<tr>" +
        "<td>" + id + "</td>" +
        "<td>" + esc(residentLabel(c.resident_id)) + "</td>" +
        "<td>" + esc(c.category || "—") + "</td>" +
        "<td>" + esc(c.description) + notes + "</td>" +
        '<td class="row-actions">' + photo + "</td>" +
        "<td>" + badge(c.status) + "</td>" +
        "<td>" + esc(fmtTime(c.raised_at)) + "</td>" +
        '<td class="row-actions">' + actions + "</td>" +
      "</tr>";
    }).join("");

    body.querySelectorAll("button[data-photo-id]").forEach(function (btn) {
      btn.addEventListener("click", function () { openComplaintPhoto(btn.getAttribute("data-photo-id")); });
    });
    body.querySelectorAll("button[data-thread-id]").forEach(function (btn) {
      btn.addEventListener("click", function () { if (window.MD.openThread) window.MD.openThread(Number(btn.getAttribute("data-thread-id")), true, loadComplaints); });
    });
    body.querySelectorAll("button[data-start-id]").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        const result = await postJSON("/complaints/" + btn.getAttribute("data-start-id") + "/status", { status: "IN_PROGRESS", resolution_notes: null });
        if (!result.ok) { alert("Could not update complaint: " + result.error); return; }
        await loadComplaints();
      });
    });
    body.querySelectorAll("button[data-resolve-id]").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        const notes = window.prompt("Resolution notes (optional):", "");
        if (notes === null) return; // cancelled
        const result = await postJSON("/complaints/" + btn.getAttribute("data-resolve-id") + "/status", { status: "RESOLVED", resolution_notes: notes || null });
        if (!result.ok) { alert("Could not resolve complaint: " + result.error); return; }
        await loadComplaints();
      });
    });
  }

  async function loadComplaints() {
    const result = await getJSON("/complaints");
    if (!result.ok) {
      $("complaints-body").innerHTML = emptyRow(8, "Could not load complaints: " + result.error);
      return;
    }
    complaintsCache = result.data;
    renderComplaints();
  }

  $("comp-search").addEventListener("input", renderComplaints);
  $("comp-filter-status").addEventListener("change", renderComplaints);
  $("comp-filter-category").addEventListener("change", renderComplaints);

  // ---- General Staff directory (admin: full control; guard: read-only)
  $("btn-register-staff").addEventListener("click", async function () {
    const resultBox = $("staffreg-result");
    resultBox.classList.add("hidden");

    const name = $("staffreg-name").value.trim();
    const phone = $("staffreg-phone").value.trim();
    const role = $("staffreg-role").value;
    const employerSelect = $("staffreg-employer");
    const employerId = employerSelect.value ? parseInt(employerSelect.value, 10) : null;
    const aadhaarRaw = $("staffreg-aadhaar").value.trim();
    const expiresRaw = $("staffreg-expires").value;

    if (!name || !phone || !aadhaarRaw) {
      resultBox.classList.remove("hidden");
      resultBox.textContent = "Please fill in name, phone, and Aadhaar number.";
      return;
    }
    if (!$("staffreg-consent").checked) {
      resultBox.classList.remove("hidden");
      resultBox.textContent = "Please confirm the staff member has agreed to the Aadhaar use described above.";
      return;
    }

    const payload = {
      name: name,
      phone: phone,
      role: role,
      employed_by_resident_id: employerId,
      aadhaar_number: aadhaarRaw,
      consent_given: true,
    };
    if (expiresRaw) {
      payload.expires_at = new Date(expiresRaw).toISOString();
    }

    const result = await postJSON("/staff", payload);
    resultBox.classList.remove("hidden");
    if (!result.ok) {
      resultBox.innerHTML = "Registration failed: " + esc(result.error);
      return;
    }

    const member = result.data;
    resultBox.innerHTML =
      "Staff member <strong>" + esc(member.name) + "</strong> registered.<br/>" +
      "Their gate ID-card code (Aadhaar stored only as last 4 digits: " + esc(member.aadhaar_last4) + "):<br/>" +
      '<span class="otp-code">' + esc(member.credential_value) + "</span>";

    $("staffreg-name").value = "";
    $("staffreg-phone").value = "";
    $("staffreg-aadhaar").value = "";
    $("staffreg-expires").value = "";
    $("staffreg-consent").checked = false;

    await loadStaffDirectory();
  });

  let staffCache = [];

  function renderStaffDirectory() {
    const body = $("staff-body");
    const q = $("staff-search").value.trim().toLowerCase();
    const statusFilter = $("staff-filter-status").value;

    const rows = staffCache.filter(function (s) {
      if (statusFilter && s.status !== statusFilter) return false;
      if (!q) return true;
      const employer = s.employed_by_resident_id ? residentLabel(s.employed_by_resident_id) : "society";
      return [s.name, s.role, employer, s.credential_value, s.aadhaar_last4, s.phone].join(" ").toLowerCase().indexOf(q) !== -1;
    });

    $("staff-count").textContent = "Showing " + rows.length + " of " + staffCache.length;
    if (staffCache.length === 0) { body.innerHTML = emptyRow(8, "No staff registered yet."); return; }
    if (rows.length === 0) { body.innerHTML = emptyRow(8, "No staff match your search."); return; }

    body.innerHTML = rows.map(function (s) {
      const id = Number(s.id);
      const employer = s.employed_by_resident_id ? residentLabel(s.employed_by_resident_id) : "— Society —";
      let action = "—";
      if (isAdmin) {
        action = s.status === "BLOCKED"
          ? '<button class="approve" data-unblock-id="' + id + '">Unblock</button>'
          : '<button class="deny" data-block-id="' + id + '">Block</button>';
        if (s.aadhaar_last4 && s.aadhaar_last4 !== "XXXX") action += ' <button data-erase-id="' + id + '">Erase Aadhaar</button>';
      }
      return "<tr>" +
        "<td>" + id + "</td>" +
        "<td>" + esc(s.name) + "</td>" +
        "<td>" + esc(s.role) + "</td>" +
        "<td>" + esc(employer) + "</td>" +
        '<td class="mono">' + (s.aadhaar_last4 && s.aadhaar_last4 !== "XXXX" ? "XXXX-XXXX-" + esc(s.aadhaar_last4) : "erased") + "</td>" +
        '<td class="mono">' + esc(s.credential_value) + "</td>" +
        "<td>" + badge(s.status) + "</td>" +
        '<td class="row-actions">' + action + "</td>" +
      "</tr>";
    }).join("");

    body.querySelectorAll("button[data-block-id]").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        const result = await postJSON("/staff/" + btn.getAttribute("data-block-id") + "/status", { status: "BLOCKED" });
        if (!result.ok) { alert("Could not block staff member: " + result.error); return; }
        await loadStaffDirectory();
      });
    });
    body.querySelectorAll("button[data-erase-id]").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        if (!window.confirm("Erase the stored Aadhaar fingerprint and last 4 digits for this person? This cannot be undone.")) return;
        const result = await postJSON("/staff/" + btn.getAttribute("data-erase-id") + "/erase-aadhaar");
        if (!result.ok) { alert("Could not erase: " + result.error); return; }
        await loadStaffDirectory();
      });
    });
    body.querySelectorAll("button[data-unblock-id]").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        const result = await postJSON("/staff/" + btn.getAttribute("data-unblock-id") + "/status", { status: "ACTIVE" });
        if (!result.ok) { alert("Could not unblock staff member: " + result.error); return; }
        await loadStaffDirectory();
      });
    });
  }

  async function loadStaffDirectory() {
    const result = await getJSON("/staff");
    if (!result.ok) {
      $("staff-body").innerHTML = emptyRow(8, "Could not load staff: " + result.error);
      return;
    }
    staffCache = result.data;
    renderStaffDirectory(); // keeps whatever the search box / filter currently say
  }

  $("staff-search").addEventListener("input", renderStaffDirectory);
  $("staff-filter-status").addEventListener("change", renderStaffDirectory);

  async function startStaffConsole() {
    isAdmin = currentUser.role === "ADMIN";
    $("header-sub").textContent = isAdmin ? "Gate Access Terminal — admin console" : "Gate Access Terminal — guard console";
    // Guards run the gate only: no complaints management, and the staff
    // directory is read-only for them (no registration, no block/unblock).
    $("complaints-card").classList.toggle("hidden", !isAdmin);
    $("deliveries-card").classList.toggle("hidden", !isAdmin);
    $("staffreg-form").classList.toggle("hidden", !isAdmin);
    $("staff-view").classList.remove("hidden");

    await loadResidents();
    await loadOpenDeliveries();
    await loadStaffDirectory();
    if (isAdmin) {
      await loadDeliveryOverview();
      await loadComplaintCategories();
      fillCategorySelect("comp-category", "Select a category...");
      fillCategorySelect("comp-filter-category", "All categories");
      await loadComplaints();
    }
  }

  // =============================================================
  // RESIDENT PORTAL (everything is scoped to the logged-in resident)
  // =============================================================

  const rpLongTerm = $("rp-v-longterm");
  function syncRpLongTerm() {
    rpLongTerm.classList.toggle("hidden", $("rp-v-type").value !== "LONG_TERM");
    $("rp-v-short-wrap").classList.toggle("hidden", $("rp-v-type").value === "LONG_TERM");
  }
  $("rp-v-type").addEventListener("change", syncRpLongTerm);
  syncRpLongTerm();

  function visitorStatus(v) {
    if (v.status) return v.status;
    const end = parseUTC(v.valid_until);
    return end && end < new Date() ? "EXPIRED" : "ACTIVE";
  }

  async function loadMyVisitors() {
    const body = $("rp-v-body");
    const result = await getJSON("/visitors");
    if (!result.ok) { body.innerHTML = emptyRow(8, "Could not load visitors: " + result.error); return; }
    if (result.data.length === 0) { body.innerHTML = emptyRow(8, "No visitors registered yet."); return; }
    body.innerHTML = result.data.map(function (v) {
      const st = visitorStatus(v);
      const acts = (st === "ACTIVE" || st === "SCHEDULED" ? '<button class="deny" data-vcancel="' + Number(v.id) + '">Cancel</button>' : "") +
        (v.has_photo ? ' <button data-vphoto="' + Number(v.id) + '">Photo</button>' : "");
      return "<tr>" +
        "<td>" + Number(v.id) + "</td>" +
        "<td>" + esc(v.name) + "</td>" +
        "<td>" + esc(v.visit_type) + "</td>" +
        '<td class="mono">' + esc(v.otp_code) + "</td>" +
        "<td>" + esc(fmtTime(v.valid_until)) + "</td>" +
        "<td>" + esc(v.otp_verified_at ? fmtTime(v.otp_verified_at) : "—") + "</td>" +
        "<td>" + badge(st) + "</td>" +
        '<td class="row-actions">' + (acts || "—") + "</td>" +
      "</tr>";
    }).join("");
    body.querySelectorAll("button[data-vcancel]").forEach(function (b) {
      b.addEventListener("click", async function () {
        if (!window.confirm("Cancel this pass? The OTP stops working immediately.")) return;
        const r = await postJSON("/visitors/" + b.getAttribute("data-vcancel") + "/cancel");
        if (!r.ok) { alert("Could not cancel: " + r.error); return; }
        await loadMyVisitors();
      });
    });
    body.querySelectorAll("button[data-vphoto]").forEach(function (b) {
      b.addEventListener("click", function () { window.MD.showImage("/visitors/" + b.getAttribute("data-vphoto") + "/photo", "Visitor photo"); });
    });
  }

  // ---- Share a visitor's OTP (v7.1): WhatsApp message + QR visitor pass
  // Turn whatever the resident typed into the digits wa.me wants (country
  // code first, no "+"). Returns null when it can't be a usable number.
  function waNumber(raw) {
    const text = String(raw || "").trim();
    const intl = /^(\+|00)/.test(text);
    let d = text.replace(/\D/g, "");
    if (/^00/.test(text)) d = d.replace(/^00/, "");
    if (!intl && d.length === 10) return "91" + d;                       // 98765 43210
    if (!intl && d.length === 11 && d.charAt(0) === "0") return "91" + d.slice(1); // 098765 43210
    if (d.length === 12 && d.slice(0, 2) === "91") return d;            // +91 98765 43210
    if (intl && d.length >= 11 && d.length <= 15) return d;             // another country, typed with +
    return null;
  }

  function hostLine() {
    return currentUser.name + (currentUser.apartment_no ? " (Flat " + currentUser.apartment_no + ")" : "");
  }

  function inviteMessage(v) {
    return "Hello " + v.name + ",\n\n" +
      hostLine() + " is inviting you to visit.\n\n" +
      "This is your ManaDwar entry OTP: " + v.otp_code + "\n\n" +
      "Show it to the guard at the gate. It works for every entry until " + fmtTime(v.valid_until) + ".";
  }

  function passText(v) {
    return "ManaDwar Visitor Pass\n" +
      "Visitor: " + v.name + "\n" +
      "Host: " + hostLine() + "\n" +
      "OTP: " + v.otp_code + "\n" +
      "Valid until: " + fmtTime(v.valid_until);
  }

  function shareBlock(v) {
    const num = waNumber(v.phone);
    const wa = num
      ? '<a class="wa-btn" id="rp-v-wa" target="_blank" rel="noopener noreferrer" href="https://wa.me/' + num + "?text=" + encodeURIComponent(inviteMessage(v)) + '">Send on WhatsApp</a>' +
        '<div class="note-text" style="margin:6px 0 0;">Opens WhatsApp to ' + esc(v.phone) + " with the message ready. Check it, then press send.</div>"
      : '<div class="note-text" style="margin:0;">WhatsApp can\'t be opened because "' + esc(v.phone) + '" doesn\'t look like a full phone number. Share the OTP another way.</div>';
    return '<div class="share-box">' + wa +
      '<div class="qr-wrap"><div class="qr-box" id="rp-v-qr"></div>' +
      '<div class="note-text" style="margin:6px 0 0;">Visitor pass QR: the guard can scan this at the gate instead of typing the OTP. Show it on your screen or take a screenshot to share. (WhatsApp links can only carry text, so the QR is not attached to the message.)</div></div></div>';
  }

  // Draws the QR as a crisp SVG from the library's own module grid. Nothing
  // is sent anywhere: it is generated in this browser.
  function qrSvg(text) {
    if (typeof qrcode !== "function") return "";
    try {
      const qr = qrcode(0, "M");
      qr.addData(text);
      qr.make();
      const n = qr.getModuleCount(), margin = 4, size = n + margin * 2;
      let d = "";
      for (let r = 0; r < n; r++) {
        for (let c = 0; c < n; c++) {
          if (qr.isDark(r, c)) d += "M" + (c + margin) + " " + (r + margin) + "h1v1h-1z";
        }
      }
      // 5 screen pixels per square keeps edges sharp, which cameras scan best
      const px = size * 5;
      return '<svg xmlns="http://www.w3.org/2000/svg" width="' + px + '" height="' + px + '" viewBox="0 0 ' + size + " " + size + '" shape-rendering="crispEdges" role="img" aria-label="Visitor pass QR code">' +
        '<rect width="' + size + '" height="' + size + '" fill="#fff"/><path d="' + d + '" fill="#000"/></svg>';
    } catch (e) {
      return "";
    }
  }

  $("rp-v-submit").addEventListener("click", async function () {
    const box = $("rp-v-result");
    box.classList.remove("hidden");

    const name = $("rp-v-name").value.trim();
    const phone = $("rp-v-phone").value.trim();
    const visitType = $("rp-v-type").value;
    const purpose = $("rp-v-purpose").value.trim();
    if (!name || !phone) { box.textContent = "Please fill in visitor name and phone."; return; }

    const payload = { name: name, phone: phone, host_resident_id: currentUser.resident_id, visit_type: visitType, purpose: purpose || null };
    if ($("rp-v-from").value) payload.valid_from = new Date($("rp-v-from").value).toISOString();
    if (visitType === "SHORT_TERM" && $("rp-v-svnum").value.trim()) payload.vehicle_number = $("rp-v-svnum").value.trim();
    if (visitType === "LONG_TERM") {
      const untilRaw = $("rp-v-until").value;
      if (!untilRaw) { box.textContent = "Long-term visits need a 'valid until' date/time."; return; }
      payload.valid_until = new Date(untilRaw).toISOString();
      const vnum = $("rp-v-vnum").value.trim();
      if (vnum) { payload.vehicle_number = vnum; payload.vehicle_type = $("rp-v-vtype").value || "CAR"; }
    }

    const result = await postJSON("/visitors", payload);
    if (!result.ok) { box.innerHTML = "Registration failed: " + esc(result.error); return; }
    const v = result.data;
    box.innerHTML =
      "Visitor <strong>" + esc(v.name) + "</strong> registered.<br/>" +
      "Share this OTP with them. It works for every entry until " + esc(fmtTime(v.valid_until)) + ":<br/>" +
      '<span class="otp-code">' + esc(v.otp_code) + "</span>" +
      shareBlock(v);
    const qrSlot = box.querySelector(".qr-box");
    if (qrSlot) {
      const svg = qrSvg(passText(v));
      if (svg) qrSlot.innerHTML = svg; else qrSlot.parentNode.classList.add("hidden");
    }
    $("rp-v-name").value = "";
    $("rp-v-phone").value = "";
    $("rp-v-purpose").value = "";
    $("rp-v-from").value = "";
    $("rp-v-svnum").value = "";
    await loadMyVisitors();
  });

  // ---- Resident deliveries (v7.0): announce what you expect, answer unexpected arrivals
  function toLocalInput(d) {
    const pad = function (n) { return String(n).padStart(2, "0"); };
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) + "T" + pad(d.getHours()) + ":" + pad(d.getMinutes());
  }
  function defaultDeliveryWindow() {
    const now = new Date();
    $("rp-d-from").value = toLocalInput(now);
    $("rp-d-until").value = toLocalInput(new Date(now.getTime() + 4 * 3600 * 1000));
  }
  defaultDeliveryWindow();

  let myDeliveries = [];

  async function decideDelivery(id, approve) {
    const result = await postJSON("/deliveries/" + id + "/decision", { approve: approve });
    if (!result.ok) alert("Could not send your answer: " + result.error);
    await loadMyDeliveries();
  }

  async function loadMyDeliveries() {
    const body = $("rp-d-body");
    const result = await getJSON("/deliveries");
    if (!result.ok) { body.innerHTML = emptyRow(5, "Could not load deliveries: " + result.error); return; }
    myDeliveries = result.data;

    // Unexpected couriers the guard is waiting on come first, in a highlighted box.
    const waiting = myDeliveries.filter(function (d) { return d.status === "AWAITING_APPROVAL"; });
    $("rp-d-approval").classList.toggle("hidden", waiting.length === 0);
    $("rp-d-approval-list").innerHTML = waiting.map(function (d) {
      const id = Number(d.id);
      return '<div class="approval-item"><div>' + deliveryWho(d) +
        '<div class="note-text" style="margin:2px 0 0;">At the gate since ' + esc(fmtTime(d.requested_at)) + "</div></div>" +
        '<div class="row-actions"><button class="approve" data-yes="' + id + '">Approve</button><button class="deny" data-no="' + id + '">Deny</button></div></div>';
    }).join("");
    $("rp-d-approval-list").querySelectorAll("button[data-yes]").forEach(function (b) { b.addEventListener("click", function () { decideDelivery(b.getAttribute("data-yes"), true); }); });
    $("rp-d-approval-list").querySelectorAll("button[data-no]").forEach(function (b) { b.addEventListener("click", function () { decideDelivery(b.getAttribute("data-no"), false); }); });

    if (myDeliveries.length === 0) { body.innerHTML = emptyRow(5, "Nothing announced yet."); return; }
    body.innerHTML = myDeliveries.map(function (d) {
      const id = Number(d.id);
      const open = d.status === "EXPECTED" || d.status === "AWAITING_APPROVAL" || d.status === "APPROVED";
      return "<tr>" +
        "<td>" + id + "</td>" +
        "<td>" + deliveryWho(d) + "</td>" +
        "<td>" + esc(deliveryWhen(d)) + "</td>" +
        "<td>" + deliveryBadge(d.status) +
          (d.leave_at_gate ? '<div class="note-text" style="margin:4px 0 0;">Leave at gate</div>' : "") +
          (d.rule_applied ? '<div class="note-text" style="margin:4px 0 0;">' + esc(d.rule_applied) + "</div>" : "") + "</td>" +
        '<td class="row-actions">' + (open ? '<button data-cancel-id="' + id + '">Cancel</button>' : "") +
          (d.has_parcel_photo ? ' <button data-parcel-id="' + id + '">Parcel photo</button>' : "") + (!open && !d.has_parcel_photo ? "—" : "") + "</td>" +
      "</tr>";
    }).join("");
    body.querySelectorAll("button[data-parcel-id]").forEach(function (b) {
      b.addEventListener("click", function () { window.MD.showImage("/deliveries/" + b.getAttribute("data-parcel-id") + "/parcel-photo", "Parcel photo"); });
    });
    body.querySelectorAll("button[data-cancel-id]").forEach(function (b) {
      b.addEventListener("click", async function () {
        const result = await postJSON("/deliveries/" + b.getAttribute("data-cancel-id") + "/cancel");
        if (!result.ok) alert("Could not cancel: " + result.error);
        await loadMyDeliveries();
      });
    });
  }

  $("rp-d-refresh").addEventListener("click", loadMyDeliveries);

  $("rp-d-submit").addEventListener("click", async function () {
    const box = $("rp-d-result");
    box.classList.remove("hidden");
    const platform = $("rp-d-platform").value.trim();
    const fromRaw = $("rp-d-from").value, untilRaw = $("rp-d-until").value;
    if (!platform) { box.textContent = "Please enter the platform or courier company."; return; }
    if (!fromRaw || !untilRaw) { box.textContent = "Please set when you expect it (from and until)."; return; }
    const from = new Date(fromRaw), until = new Date(untilRaw);
    if (until <= from) { box.textContent = "'Expected until' must be after 'Expected from'."; return; }
    if (until <= new Date()) { box.textContent = "That time window has already passed."; return; }

    const result = await postJSON("/deliveries/announce", {
      host_resident_id: currentUser.resident_id,
      platform: platform,
      description: $("rp-d-note").value.trim() || null,
      expected_from: from.toISOString(),
      expected_until: until.toISOString(),
      leave_at_gate: $("rp-d-leave").checked,
    });
    if (!result.ok) { box.innerHTML = "Could not announce: " + esc(result.error); return; }
    box.innerHTML = "Done. The guard will let <strong>" + esc(result.data.platform) + "</strong> in between " + esc(deliveryWhen(result.data)) + ".";
    $("rp-d-platform").value = "";
    $("rp-d-note").value = "";
    $("rp-d-leave").checked = false;
    defaultDeliveryWindow();
    await loadMyDeliveries();
  });

  async function loadMyComplaints() {
    const body = $("rp-c-body");
    const result = await getJSON("/complaints");
    if (!result.ok) { body.innerHTML = emptyRow(6, "Could not load complaints: " + result.error); return; }
    if (result.data.length === 0) { body.innerHTML = emptyRow(6, "No complaints raised yet."); return; }
    body.innerHTML = result.data.map(function (c) {
      const id = Number(c.id);
      return "<tr>" +
        "<td>" + id + "</td>" +
        "<td>" + esc(c.category || "—") + "</td>" +
        "<td>" + esc(c.description) + (c.assigned_to ? '<div class="note-text" style="margin:4px 0 0;">Assigned to: ' + esc(c.assigned_to) + "</div>" : "") + "</td>" +
        '<td class="row-actions">' + (c.has_image ? '<button data-photo-id="' + id + '">View</button>' : "—") + "</td>" +
        "<td>" + badge(c.status) + "</td>" +
        "<td>" + esc(c.resolution_notes || "—") + '<div class="row-actions" style="margin-top:6px;"><button data-thread-id="' + id + '">Messages</button>' +
          (c.status === "RESOLVED" ? ' <button data-reopen-id="' + id + '">Reopen</button>' : "") + "</div></td>" +
      "</tr>";
    }).join("");
    body.querySelectorAll("button[data-photo-id]").forEach(function (btn) {
      btn.addEventListener("click", function () { openComplaintPhoto(btn.getAttribute("data-photo-id")); });
    });
    body.querySelectorAll("button[data-thread-id]").forEach(function (btn) {
      btn.addEventListener("click", function () { window.MD.openThread(Number(btn.getAttribute("data-thread-id")), false, loadMyComplaints); });
    });
    body.querySelectorAll("button[data-reopen-id]").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        const r = await postJSON("/complaints/" + btn.getAttribute("data-reopen-id") + "/reopen");
        if (!r.ok) { alert("Could not reopen: " + r.error); return; }
        await loadMyComplaints();
      });
    });
  }

  const MAX_PHOTO_BYTES = 5 * 1024 * 1024;
  const photoInput = $("rp-c-photo");
  const photoPreview = $("rp-c-preview");

  function clearPhotoPreview() {
    if (photoPreview.getAttribute("src")) URL.revokeObjectURL(photoPreview.getAttribute("src"));
    photoPreview.removeAttribute("src");
    photoPreview.classList.add("hidden");
  }

  photoInput.addEventListener("change", function () {
    clearPhotoPreview();
    const file = photoInput.files && photoInput.files[0];
    if (!file) return;
    if (file.size > MAX_PHOTO_BYTES) {
      alert("That image is larger than 5 MB. Please choose a smaller one.");
      photoInput.value = "";
      return;
    }
    photoPreview.src = URL.createObjectURL(file);
    photoPreview.classList.remove("hidden");
  });

  $("rp-c-submit").addEventListener("click", async function () {
    const box = $("rp-c-result");
    box.classList.remove("hidden");
    const category = $("rp-c-category").value;
    const description = $("rp-c-description").value.trim();
    if (!category) { box.textContent = "Please select a category."; return; }
    if (!description) { box.textContent = "Please describe the issue."; return; }

    const result = await postJSON("/complaints", { resident_id: currentUser.resident_id, category: category, description: description });
    if (!result.ok) { box.innerHTML = "Could not raise complaint: " + esc(result.error); return; }

    let message = "Complaint raised. The admin will pick it up.";
    const file = photoInput.files && photoInput.files[0];
    if (file) {
      const form = new FormData();
      form.append("file", file);
      const upload = await postForm("/complaints/" + Number(result.data.id) + "/image", form);
      if (!upload.ok) message = "Complaint raised, but the photo could not be uploaded: " + upload.error;
    }
    box.textContent = message;

    $("rp-c-description").value = "";
    $("rp-c-category").value = "";
    photoInput.value = "";
    clearPhotoPreview();
    await loadMyComplaints();
  });

  $("rtab-visitors").addEventListener("click", loadMyVisitors);
  $("rtab-deliveries").addEventListener("click", loadMyDeliveries);
  $("rtab-complaints").addEventListener("click", loadMyComplaints);

  async function startResidentPortal() {
    $("header-sub").textContent = "Resident portal";
    $("rp-welcome").textContent = "Welcome, " + currentUser.name + (currentUser.apartment_no ? " — Apartment " + currentUser.apartment_no : "");
    $("resident-view").classList.remove("hidden");
    await loadComplaintCategories();
    fillCategorySelect("rp-c-category", "Select a category...");
    await Promise.all([loadMyVisitors(), loadMyDeliveries(), loadMyComplaints()]);
  }

  // =============================================================
  // LOGIN / BOOT
  // =============================================================

  function showLogin(message) {
    $("login-view").classList.remove("hidden");
    $("login-error").textContent = message || "";
    $("login-email").focus();
  }

  $("login-form").addEventListener("submit", async function (ev) {
    ev.preventDefault();
    const email = $("login-email").value.trim();
    const password = $("login-password").value;
    const errBox = $("login-error");
    errBox.textContent = "";
    if (!email || !password) { errBox.textContent = "Enter your email and password."; return; }

    const btn = $("btn-login");
    btn.disabled = true;
    const result = await loginRequest(email, password);
    btn.disabled = false;
    if (!result.ok) { errBox.textContent = result.error; return; }

    token = result.token;
    storeSet(TOKEN_KEY, token);
    $("login-password").value = "";
    $("login-view").classList.add("hidden");
    await boot();
  });

  $("btn-logout").addEventListener("click", function () { signOut(); });

  async function boot() {
    if (!token) { showLogin(takeFlashMessage()); return; }

    const me = await getJSON("/auth/me");
    if (!me.ok) {
      // A 401 already triggered signOut() (and a reload); anything else
      // (e.g. server unreachable) falls back to the login screen.
      if (me.status !== 401) showLogin(me.error);
      return;
    }
    currentUser = me.data;

    $("who").innerHTML = "<strong>" + esc(currentUser.name) + "</strong>" +
      '<span class="role-pill">' + esc(currentUser.role) + "</span>";
    $("user-info").classList.remove("hidden");

    if (currentUser.role === "RESIDENT") {
      await startResidentPortal();
    } else if (currentUser.role === "GUARD" || currentUser.role === "ADMIN") {
      await startStaffConsole();
    } else {
      signOut("Unknown account role.");
      return;
    }
    if (window.MD) window.MD.ready = true;
    document.dispatchEvent(new CustomEvent("md:ready", { detail: currentUser }));
  }

  function takeFlashMessage() {
    try {
      const msg = window.sessionStorage.getItem(MSG_KEY);
      window.sessionStorage.removeItem(MSG_KEY);
      return msg || "";
    } catch (e) { return ""; }
  }

  // ---- helpers shared with the extension modules (ext-*.js)
  function showImage(url, alt) {
    return fetch(url, { headers: { "Authorization": "Bearer " + token } }).then(function (res) {
      if (!res.ok) { alert("Could not load the photo."); return; }
      return res.blob().then(function (blob) {
        const img = $("img-modal-img");
        if (img.getAttribute("src")) URL.revokeObjectURL(img.getAttribute("src"));
        img.alt = alt || "Photo";
        img.src = URL.createObjectURL(blob);
        $("img-modal").classList.remove("hidden");
      });
    }).catch(function () { alert("Could not load the photo."); });
  }

  window.MD = Object.assign(window.MD || {}, {
    $: $, request: request, getJSON: getJSON, postJSON: postJSON, postForm: postForm, esc: esc, badge: badge,
    fmtTime: fmtTime, parseUTC: parseUTC, emptyRow: emptyRow, setStatus: setStatus, errorText: errorText,
    getToken: function () { return token; },
    setToken: function (t) { token = t; storeSet(TOKEN_KEY, t); },
    user: function () { return currentUser; },
    setUser: function (u) { currentUser = u; },
    residents: function () { return allResidents; },
    residentLabel: residentLabel, loadResidents: loadResidents, toLocalInput: toLocalInput,
    storeGet: storeGet, storeSet: storeSet, signOut: signOut, showImage: showImage,
    makeResidentPicker: makeResidentPicker, loadComplaints: loadComplaints, loadMyVisitors: loadMyVisitors,
    loadMyDeliveries: loadMyDeliveries, loadMyComplaints: loadMyComplaints, refreshDeliveries: refreshDeliveries,
    loadStaffDirectory: loadStaffDirectory, verifyOtpCode: verifyOtpCode,
    ready: false,
  });

  boot();
})();
