(() => {
  "use strict";

  const API = "/api";
  const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  if (tg) {
    tg.ready();
    tg.expand();
  }

  const USER_ID = tg ? tg.initDataUnsafe.user.id : 0;
  const q = (s) => document.querySelector(s);

  const screens = {
    login: q("#screen-login"),
    password: q("#screen-password"),
    main: q("#screen-main"),
    list: q("#screen-list"),
  };

  let state = {
    sort: "members",
    rows: [],
    selected: new Set(),
    qrTimer: null,
    qrExpiresAt: 0,
  };

  function show(screenName) {
    Object.values(screens).forEach((s) => s.classList.add("hidden"));
    screens[screenName].classList.remove("hidden");
  }

  function toast(text, ms = 4000) {
    const t = q("#toast");
    t.textContent = text;
    t.classList.remove("hidden");
    clearTimeout(t._h);
    t._h = setTimeout(() => t.classList.add("hidden"), ms);
  }

  async function api(path, opts = {}) {
    const res = await fetch(`${API}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
    const data = await res.json().catch(() => ({ ok: false, error: "bad response" }));
    if (!data.ok) throw new Error(data.error || "Ошибка");
    return data;
  }

  function esc(s) {
    const d = document.createElement("div");
    d.textContent = String(s ?? "");
    return d.innerHTML;
  }

  function applyTheme() {
    const dark = tg ? tg.colorScheme === "dark" : localStorage.getItem("theme") === "dark";
    document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
    const btn = q("#themeToggle");
    btn.textContent = dark ? "☀️" : "🌙";
    btn.style.display = tg ? "none" : "";
  }
  applyTheme();
  q("#themeToggle").onclick = () => {
    const dark = document.documentElement.getAttribute("data-theme") === "dark";
    localStorage.setItem("theme", dark ? "light" : "dark");
    applyTheme();
  };

  /* ---------- ВХОД (QR) ---------- */

  function startQrTimer(expiresIso) {
    clearInterval(state.qrTimer);
    state.qrExpiresAt = expiresIso ? new Date(expiresIso).getTime() : 0;
    const el = q("#qrTimer");
    const tick = () => {
      if (!state.qrExpiresAt) return;
      const left = Math.max(0, state.qrExpiresAt - Date.now());
      const deg = (left / 30000) * 360;
      el.style.setProperty("--rot", deg + "deg");
      if (left <= 0) {
        refreshQr();
      }
    };
    tick();
    state.qrTimer = setInterval(tick, 500);
  }

  async function loadQr() {
    const status = q("#qr-status");
    status.textContent = "Загружаю QR-код...";
    try {
      const data = await api("/qr/start?user_id=" + USER_ID);
      q("#qr-img").src = "data:image/png;base64," + data.url;
      status.textContent = "📲 Сканируй код приложением Telegram";
      startQrTimer(null);
      pollQrStatus();
    } catch (e) {
      status.textContent = "❌ " + e.message;
    }
  }

  async function refreshQr() {
    try {
      const data = await api("/qr/refresh?user_id=" + USER_ID);
      if (data.url) {
        q("#qr-img").src = "data:image/png;base64," + data.url;
        q("#qr-status").textContent = "🔄 Код обновлён. Сканируй!";
      } else {
        showPassword();
      }
    } catch (e) {
      q("#qr-status").textContent = "❌ " + e.message;
    }
  }

  let polling = false;
  async function pollQrStatus() {
    if (polling) return;
    polling = true;
    try {
      while (true) {
        await new Promise((r) => setTimeout(r, 2500));
        const data = await api("/qr/status?user_id=" + USER_ID);
        if (data.status === "ok") {
          q("#qr-status").textContent = "✅ Успех! Входим...";
          await boot();
          return;
        }
        if (data.status === "password") {
          showPassword();
          return;
        }
        if (data.status === "none") return;
      }
    } catch (e) {
      q("#qr-status").textContent = "❌ " + e.message;
    } finally {
      polling = false;
    }
  }

  q("#qrRefreshBtn").onclick = refreshQr;

  /* ---------- ПАРОЛЬ 2FA ---------- */

  function showPassword() {
    clearInterval(state.qrTimer);
    show("password");
  }

  q("#passwordBtn").onclick = async () => {
    const input = q("#passwordInput");
    const err = q("#passwordError");
    err.classList.add("hidden");
    try {
      await api("/login/password?user_id=" + USER_ID, {
        method: "POST",
        body: JSON.stringify({ password: input.value }),
      });
      input.value = "";
      await boot();
    } catch (e) {
      err.textContent = e.message;
      err.classList.remove("hidden");
    }
  };

  /* ---------- ГЛАВНЫЙ ЭКРАН ---------- */

  async function boot() {
    try {
      const me = await api("/me?user_id=" + USER_ID);
      if (!me.authed) {
        q("#qr-img").src = "";
        show("login");
        loadQr();
        return;
      }
      q("#userName").textContent = (me.first + " " + me.last).trim() || "Аккаунт";
      q("#userSub").textContent = "@" + (me.username || "—") + " · " + (me.phone || "");
      await refreshStats();
      const ak = await api("/autokill?user_id=" + USER_ID);
      q("#autokillToggle").checked = !!ak.enabled;
      show("main");
    } catch (e) {
      toast(e.message);
    }
  }

  async function refreshStats() {
    const data = await api("/dialogs?user_id=" + USER_ID + "&sort=members");
    const total = data.rows.length;
    const unread = data.rows.reduce((s, r) => s + (r.unread || 0), 0);
    q("#statTotal").textContent = total;
    q("#statUnread").textContent = unread;
    q("#statRemoved").textContent = data.removed ?? "…";
    q("#statRemoved").textContent = total; // placeholder until API supports
  }

  q("#autokillToggle").onchange = async (e) => {
    try {
      await api("/autokill?user_id=" + USER_ID, {
        method: "POST",
        body: JSON.stringify({ enabled: e.target.checked }),
      });
      toast(e.target.checked ? "Авто-уборка включена" : "Авто-уборка выключена");
    } catch (err) {
      toast(err.message);
      e.target.checked = !e.target.checked;
    }
  };

  q("#logoutBtn").onclick = async () => {
    if (!confirm("Выйти из аккаунта?")) return;
    await api("/logout?user_id=" + USER_ID, { method: "POST" });
    location.reload();
  };

  /* ---------- СПИСОК ---------- */

  const ICONS = { private: "💬", group: "👥", channel: "📢" };

  q("#listBtn").onclick = () => {
    state.selected.clear();
    renderList();
  };

  q("#backBtn").onclick = () => show("main");
  q("#selectAllBtn").onclick = () => {
    if (state.selected.size === state.rows.length) state.selected.clear();
    else state.rows.forEach((r) => state.selected.add(r.id));
    renderList();
  };

  document.querySelectorAll(".tab").forEach((btn) => {
    btn.onclick = () => {
      document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.sort = btn.dataset.sort;
      loadList();
    };
  });

  async function loadList() {
    q("#list").innerHTML = '<div class="empty">Загрузка...</div>';
    try {
      const data = await api("/dialogs?user_id=" + USER_ID + "&sort=" + state.sort);
      state.rows = data.rows;
      renderList();
    } catch (e) {
      q("#list").innerHTML = `<div class="empty">❌ ${esc(e.message)}</div>`;
    }
  }

  function renderList() {
    const list = q("#list");
    if (!state.rows.length) {
      list.innerHTML = '<div class="empty">📭 Диалогов нет</div>';
    } else {
      list.innerHTML = state.rows
        .map((r) => {
          const sel = state.selected.has(r.id);
          const date = r.date ? new Date(r.date * 1000).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" }) : "—";
          return `<div class="item${sel ? " selected" : ""}" data-id="${r.id}">
            <div class="ic">${ICONS[r.kind] || "❓"}</div>
            <div class="info">
              <div class="title">${esc(r.title || r.id)}</div>
              <div class="meta">👥 ${r.members} · 🔔 ${r.unread} · 🕒 ${date}</div>
            </div>
            <div class="check">✓</div>
          </div>`;
        })
        .join("");
      list.querySelectorAll(".item").forEach((el) => {
        el.onclick = () => {
          const id = Number(el.dataset.id);
          if (state.selected.has(id)) state.selected.delete(id);
          else state.selected.add(id);
          renderList();
        };
      });
    }
    const bar = q("#deleteBar");
    q("#delCount").textContent = "Выбрано: " + state.selected.size;
    bar.classList.toggle("hidden", state.selected.size === 0);
  }

  q("#deleteBtn").onclick = async () => {
    const ids = [...state.selected];
    if (!confirm(`Удалить ${ids.length} чат(ов)? Это необратимо.`)) return;
    try {
      const data = await api("/remove?user_id=" + USER_ID, {
        method: "POST",
        body: JSON.stringify({ ids }),
      });
      state.selected.clear();
      toast("✅ " + data.results.join("\n").replace(/^✅ /gm, ""), 5000);
      await loadList();
    } catch (e) {
      toast("❌ " + e.message);
    }
  };

  /* ---------- СТАРТ ---------- */
  boot();
})();