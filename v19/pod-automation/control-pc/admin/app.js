// Pod Control admin GUI. Plain JS, no build step, no framework --
// same-origin as coordinator.py (served from /admin), so every fetch
// below just hits relative /api/... paths directly.

const INSTANCES_POLL_MS = 3000;
const PODS_POLL_MS = 5000;

const instanceCardsEl = document.getElementById("instance-cards");
const podsTbodyEl = document.getElementById("pods-tbody");
const connIndicatorEl = document.getElementById("conn-indicator");

const startDialog = document.getElementById("start-dialog");
const startForm = document.getElementById("start-form");
const startDialogTitle = document.getElementById("start-dialog-title");
const startDialogWarning = document.getElementById("start-dialog-warning");
const startDialogCancel = document.getElementById("start-dialog-cancel");
const sessionTypeSelect = startForm.elements["session_type"];
const durationField = startForm.querySelector(".duration-field");
const lapsField = startForm.querySelector(".laps-field");

let pendingStartInstanceId = null;
let consecutiveFailures = 0;

sessionTypeSelect.addEventListener("change", () => {
  const isRace = sessionTypeSelect.value === "race";
  durationField.hidden = isRace;
  lapsField.hidden = !isRace;
});

startDialogCancel.addEventListener("click", () => {
  startDialog.close();
});

startForm.addEventListener("submit", async (e) => {
  // dialog method="dialog" already closes it; we just need to fire the
  // request before/along with that using the data captured here.
  const fd = new FormData(startForm);
  const body = {
    name: fd.get("name") || "",
    track: fd.get("track") || "",
    track_layout: fd.get("track_layout") || "",
    cars: fd.get("cars") || "",
    session_type: fd.get("session_type"),
    duration_minutes: Number(fd.get("duration_minutes") || 20),
    laps: Number(fd.get("laps") || 10),
    max_clients: Number(fd.get("max_clients") || 4),
    password: fd.get("password") || "",
  };
  const instanceId = pendingStartInstanceId;
  pendingStartInstanceId = null;
  try {
    const resp = await fetch(`/api/admin/instances/${instanceId}/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (!resp.ok) {
      alert(`Couldn't start instance ${instanceId}: ${data.error || resp.status}`);
    }
  } catch (err) {
    alert(`Couldn't start instance ${instanceId}: ${err}`);
  }
  refreshInstances();
});

function openStartDialog(instance) {
  pendingStartInstanceId = instance.id;
  startForm.reset();
  sessionTypeSelect.value = "practice";
  durationField.hidden = false;
  lapsField.hidden = true;

  const assignment = instance.assignment;
  if (assignment && assignment.type === "group") {
    startDialogTitle.textContent = `Reassign instance ${instance.id} (port ${instance.port})`;
    startDialogWarning.hidden = false;
    startDialogWarning.textContent =
      `This instance is currently running a customer session (group ${assignment.group_id}, ` +
      `${assignment.member_pod_ids.length} pod${assignment.member_pod_ids.length === 1 ? "" : "s"}). ` +
      `Starting a new server here will end that session and disconnect them.`;
  } else if (assignment && assignment.type === "admin") {
    startDialogTitle.textContent = `Reconfigure instance ${instance.id} (port ${instance.port})`;
    startDialogWarning.hidden = true;
    // Prefill with the current admin config as a starting point.
    const c = assignment.config;
    startForm.elements["name"].value = c.name || "";
    startForm.elements["track"].value = c.track || "";
    startForm.elements["track_layout"].value = c.track_layout || "";
    startForm.elements["cars"].value = (c.cars || []).join(", ");
    startForm.elements["session_type"].value = c.session_type || "practice";
    startForm.elements["duration_minutes"].value = c.duration_minutes || 20;
    startForm.elements["laps"].value = c.laps || 10;
    startForm.elements["max_clients"].value = c.max_clients || 4;
    sessionTypeSelect.dispatchEvent(new Event("change"));
  } else {
    startDialogTitle.textContent = `Start instance ${instance.id} (port ${instance.port})`;
    startDialogWarning.hidden = true;
  }

  startDialog.showModal();
}

async function stopInstance(instance) {
  const assignment = instance.assignment;
  let confirmMsg = `Stop instance ${instance.id} (port ${instance.port})?`;
  let reason = "admin_stopped";
  if (assignment && assignment.type === "group") {
    confirmMsg =
      `Instance ${instance.id} is running a live customer session (group ${assignment.group_id}, ` +
      `${assignment.member_pod_ids.length} pod${assignment.member_pod_ids.length === 1 ? "" : "s"}). ` +
      `Stopping it will disconnect them and end their session. Continue?`;
    reason = "admin_stopped_active_group";
  }
  if (!confirm(confirmMsg)) return;

  try {
    const resp = await fetch(`/api/admin/instances/${instance.id}/stop`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      alert(`Couldn't stop instance ${instance.id}: ${data.error || resp.status}`);
    }
  } catch (err) {
    alert(`Couldn't stop instance ${instance.id}: ${err}`);
  }
  refreshInstances();
}

function fmtLiveStatus(liveStatus) {
  if (!liveStatus) return null;
  try {
    return JSON.stringify(liveStatus, null, 2);
  } catch {
    return String(liveStatus);
  }
}

function renderInstanceCard(instance) {
  const card = document.createElement("div");
  card.className = "instance-card";

  const assignment = instance.assignment;
  let pillClass = "status-idle";
  let pillLabel = "Idle";
  if (assignment && assignment.type === "group") {
    pillClass = "status-group";
    pillLabel = "Customer session";
  } else if (assignment && assignment.type === "admin") {
    pillClass = "status-admin";
    pillLabel = "Admin session";
  } else if (instance.running) {
    // Running but this coordinator doesn't recognize why (e.g. just
    // restarted and lost in-memory state) -- still worth flagging.
    pillClass = "status-admin";
    pillLabel = "Running (untracked)";
  }

  const head = document.createElement("div");
  head.className = "instance-card-head";
  head.innerHTML = `
    <div>
      <div class="instance-title">Instance ${instance.id}</div>
      <div class="instance-ports">UDP/TCP ${instance.port} &middot; HTTP ${instance.http_port}</div>
    </div>
    <span class="status-pill ${pillClass}">${pillLabel}</span>
  `;
  card.appendChild(head);

  const detail = document.createElement("div");
  detail.className = "assignment-detail";
  if (assignment && assignment.type === "group") {
    const cfg = assignment.config || {};
    detail.innerHTML =
      `Group <b>${assignment.group_id}</b> &middot; ${assignment.member_pod_ids.length} pod(s)<br>` +
      `Track: <b>${cfg.track_id || "?"}</b> &middot; Car: <b>${cfg.car_id || "?"}</b>`;
  } else if (assignment && assignment.type === "admin") {
    const cfg = assignment.config;
    detail.innerHTML =
      `<b>${cfg.name || "Admin server"}</b><br>` +
      `Track: <b>${cfg.track || "?"}</b> &middot; Cars: <b>${(cfg.cars || []).join(", ") || "?"}</b><br>` +
      `${cfg.session_type === "race" ? `Race, ${cfg.laps} laps` : `Practice, ${cfg.duration_minutes} min`}` +
      `${cfg.password_protected ? " &middot; password-protected" : ""}`;
  } else {
    detail.textContent = "Not running.";
  }
  card.appendChild(detail);

  const liveText = fmtLiveStatus(instance.live_status);
  const live = document.createElement("div");
  live.className = "live-status" + (liveText ? "" : " empty");
  live.textContent = liveText || (instance.running ? "No live status yet (instance may still be booting, or /INFO is unreachable)." : "");
  if (instance.running || liveText) card.appendChild(live);

  const actions = document.createElement("div");
  actions.className = "card-actions";

  const startBtn = document.createElement("button");
  startBtn.className = "btn-primary";
  startBtn.textContent = assignment ? "Reassign…" : "Start…";
  startBtn.addEventListener("click", () => openStartDialog(instance));
  actions.appendChild(startBtn);

  if (instance.running) {
    const stopBtn = document.createElement("button");
    stopBtn.className = "btn-danger";
    stopBtn.textContent = "Stop";
    stopBtn.addEventListener("click", () => stopInstance(instance));
    actions.appendChild(stopBtn);
  }

  card.appendChild(actions);
  return card;
}

function setConnStatus(ok) {
  if (ok) {
    consecutiveFailures = 0;
    connIndicatorEl.textContent = "connected";
    connIndicatorEl.className = "conn-indicator conn-ok";
  } else {
    consecutiveFailures += 1;
    if (consecutiveFailures >= 2) {
      connIndicatorEl.textContent = "can't reach coordinator";
      connIndicatorEl.className = "conn-indicator conn-error";
    }
  }
}

async function refreshInstances() {
  try {
    const resp = await fetch("/api/instances");
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || resp.status);
    setConnStatus(true);

    instanceCardsEl.innerHTML = "";
    for (const instance of data.instances) {
      instanceCardsEl.appendChild(renderInstanceCard(instance));
    }
  } catch (err) {
    setConnStatus(false);
  }
}

function fmtLastSeen(lastSeen) {
  if (!lastSeen) return "never";
  const seconds = Math.max(0, Math.round(Date.now() / 1000 - lastSeen));
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  return `${Math.round(minutes / 60)}h ago`;
}

async function refreshPods() {
  try {
    const resp = await fetch("/api/pods");
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || resp.status);
    setConnStatus(true);

    podsTbodyEl.innerHTML = "";
    if (!data.pods.length) {
      podsTbodyEl.innerHTML = `<tr><td colspan="5" class="empty-row">No pods registered yet.</td></tr>`;
      return;
    }
    for (const pod of data.pods) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${pod.pod_id}</td>
        <td>${pod.ip || "?"}</td>
        <td class="pod-status-${pod.status}">${pod.status}</td>
        <td>${pod.group_id || "—"}</td>
        <td>${fmtLastSeen(pod.last_seen)}</td>
      `;
      podsTbodyEl.appendChild(tr);
    }
  } catch (err) {
    setConnStatus(false);
  }
}

refreshInstances();
refreshPods();
setInterval(refreshInstances, INSTANCES_POLL_MS);
setInterval(refreshPods, PODS_POLL_MS);
