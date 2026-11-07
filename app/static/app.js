/* Interactions : enregistrement du service worker, glisser-déposer du tableau,
   notifications push, invite d'installation. Pas de dépendance externe. */

// --- Service worker (PWA + push) -------------------------------------------
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}

// --- Tableau Kanban : glisser-déposer --------------------------------------
(function board() {
  if (!window.__board) return;
  let dragId = null;

  document.querySelectorAll(".kard").forEach((k) => {
    k.addEventListener("dragstart", (e) => {
      dragId = k.dataset.id;
      k.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
      try { e.dataTransfer.setData("text/plain", dragId); } catch (_) {}
    });
    k.addEventListener("dragend", () => { k.classList.remove("dragging"); dragId = null; });
    // Un vrai clic (sans glisser) suit le lien normalement.
  });

  document.querySelectorAll(".board-drop").forEach((col) => {
    col.addEventListener("dragover", (e) => { e.preventDefault(); col.classList.add("over"); });
    col.addEventListener("dragleave", () => col.classList.remove("over"));
    col.addEventListener("drop", async (e) => {
      e.preventDefault();
      col.classList.remove("over");
      const id = dragId || e.dataTransfer.getData("text/plain");
      if (!id) return;
      const card = document.querySelector(`.kard[data-id="${id}"]`);
      const status = col.dataset.status;
      if (card) col.appendChild(card);
      try {
        await fetch(`/candidature/${id}/statut`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status, position: 0 }),
        });
        updateCounts();
      } catch (_) { location.reload(); }
    });
  });

  function updateCounts() {
    document.querySelectorAll(".board-col").forEach((c) => {
      const n = c.querySelectorAll(".kard").length;
      const badge = c.querySelector(".count");
      if (badge) badge.textContent = n;
    });
  }
})();

// --- Notifications push -----------------------------------------------------
const pushSupported = () =>
  "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;

function urlB64ToUint8Array(base64) {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const b64 = (base64 + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(b64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

async function swReady() {
  try { await navigator.serviceWorker.register("/sw.js"); } catch (_) {}
  return navigator.serviceWorker.ready;
}

async function enablePush() {
  if (!pushSupported()) return { ok: false, reason: "unsupported" };
  const perm = await Notification.requestPermission();
  if (perm !== "granted") return { ok: false, reason: "denied" };
  const res = await fetch("/push/public-key").then((r) => r.json());
  if (!res.enabled || !res.key) return { ok: false, reason: "no-key" };
  const reg = await swReady();
  let sub = await reg.pushManager.getSubscription();
  if (!sub) {
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlB64ToUint8Array(res.key),
    });
  }
  const j = sub.toJSON();
  await fetch("/push/subscribe", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ endpoint: j.endpoint, keys: j.keys }),
  });
  return { ok: true };
}

async function disablePush() {
  const reg = await swReady();
  const sub = await reg.pushManager.getSubscription();
  if (!sub) return;
  const endpoint = sub.endpoint;
  try { await sub.unsubscribe(); } catch (_) {}
  try {
    await fetch("/push/unsubscribe", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ endpoint }),
    });
  } catch (_) {}
}

(function settings() {
  if (!window.__settings) return;
  const stateEl = document.getElementById("push-state");
  const enableBtn = document.getElementById("push-enable");
  const disableBtn = document.getElementById("push-disable");
  const testBtn = document.getElementById("push-test");

  async function refresh() {
    if (!pushSupported()) {
      stateEl.textContent = "❌ Cet appareil/navigateur ne gère pas les notifications.";
      enableBtn.hidden = true;
      return;
    }
    const reg = await swReady();
    const sub = await reg.pushManager.getSubscription();
    if (sub && Notification.permission === "granted") {
      stateEl.textContent = "✅ Notifications activées sur cet appareil.";
      enableBtn.hidden = true; disableBtn.hidden = false; testBtn.hidden = false;
    } else {
      stateEl.textContent = Notification.permission === "denied"
        ? "🚫 Notifications bloquées (autorise-les dans les réglages du navigateur)."
        : "Non activées sur cet appareil.";
      enableBtn.hidden = false; disableBtn.hidden = true; testBtn.hidden = true;
    }
  }

  enableBtn?.addEventListener("click", async () => {
    enableBtn.disabled = true;
    const r = await enablePush();
    enableBtn.disabled = false;
    if (!r.ok) {
      const msg = { unsupported: "Appareil non compatible.", denied: "Permission refusée.",
        "no-key": "Push non configuré côté serveur.", error: "Erreur." }[r.reason] || "Erreur.";
      stateEl.textContent = "❌ " + msg;
    }
    refresh();
  });
  disableBtn?.addEventListener("click", async () => { await disablePush(); refresh(); });
  testBtn?.addEventListener("click", async () => {
    await fetch("/push/test", { method: "POST" });
  });
  refresh();
})();

// --- Invite d'installation (Android/Chrome) --------------------------------
let deferredPrompt = null;
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  deferredPrompt = e;
  const btn = document.getElementById("install-btn");
  if (btn) {
    btn.hidden = false;
    btn.addEventListener("click", async () => {
      btn.hidden = true;
      deferredPrompt.prompt();
      deferredPrompt = null;
    }, { once: true });
  }
});
