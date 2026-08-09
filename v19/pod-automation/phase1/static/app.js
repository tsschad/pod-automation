/*
 * app.js -- single-player kiosk picker.
 *
 * Navigation model, deliberately kept simple so a later wheel/pedal
 * input layer can drive it without a rewrite: every screen exposes a
 * `keyHandler(event)` function that understands four abstract actions
 *   - "prev" / "next"  (Left/Right today; wheel rotation later)
 *   - "select"         (Enter today; gas pedal later)
 *   - "back"           (Backspace/Escape today; brake pedal later)
 * Mouse/touch clicking a card selects it directly, in parallel with
 * keyboard nav -- both fully work today, per the current phase scope.
 *
 * Each screen function re-renders from global state `S` and can be
 * safely re-entered (e.g. when the user goes Back to it), refetching
 * from the API as needed rather than assuming cached data is still
 * valid.
 */

const app = document.getElementById("app");

// Sentinel id for the "surprise me" card prepended to car/track
// carousels. Picking it selects a uniformly random item from whatever
// real list is currently showing (so it respects the chosen pack /
// category, rather than pulling from the whole AC library).
const RANDOM_ID = "__random__";

function randomCard(label) {
  return {
    id: RANDOM_ID,
    render: () => `
      <div class="card random-card">
        <div class="thumb">?</div>
        <div class="label"><div class="name">${escapeHtml(label)}</div></div>
      </div>`,
  };
}

const S = {
  customerName: "",
  packId: null,
  packLabel: "",
  carId: null,
  carName: "",
  trackId: null,
  trackName: "",
  layoutId: "",
  layoutName: "",
  sessionType: null, // "practice" | "race"
  durationMinutes: 20,
  aiCount: 3,
  aiLevel: 90,

  // Multiplayer. mode is "single" or "multiplayer" -- most of the
  // existing single-player screens (pack/car/track/session/duration)
  // are reused for the inviter's setup either way, branching on this.
  mode: "single",
  mpAvailable: false,   // this pod has mp_config.json -- see initMultiplayer()
  mpPodId: null,
  mpControlPcUrl: null,
  mpGroupId: null,
  mpIsInviter: false,
  mpGroup: null,        // latest known state of our current group, from GET or SSE push
};

let history = [];
let currentScreen = null;
let currentKeyHandler = null;

function goto(screenFn) {
  if (currentScreen) history.push(currentScreen);
  currentScreen = screenFn;
  screenFn();
}

function back() {
  const prev = history.pop();
  if (prev) {
    currentScreen = prev;
    prev();
  }
}

document.addEventListener("keydown", (e) => {
  // Don't hijack Backspace while the customer is actually typing in a
  // text field (name entry) -- only treat it as "go back" elsewhere.
  const activeTag = document.activeElement && document.activeElement.tagName;
  const typingInField = activeTag === "INPUT" || activeTag === "TEXTAREA";

  if (e.key === "Escape" || (e.key === "Backspace" && !typingInField)) {
    e.preventDefault();
    back();
    return;
  }
  if (currentKeyHandler) currentKeyHandler(e);
});

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `Request to ${path} failed (${res.status})`);
  }
  return res.json();
}

// ------------------------------------------------------------ multiplayer
//
// The invite/group/live-status state itself lives on the control PC's
// coordinator service, not here -- this pod's browser talks to it
// directly (see phase1/app.py's /api/mp/config for how it finds it,
// and control-pc/coordinator.py for the actual state machine). This
// pod's own Flask app only gets involved for the one thing the
// browser can't do itself: writing race.ini and launching acs.exe
// once a session actually starts (POST /api/mp/join).

async function mpApi(path, opts) {
  const res = await fetch(`${S.mpControlPcUrl}${path}`, opts);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `Request to ${path} failed (${res.status})`);
  }
  return res.json();
}

/* Fire-and-forget: pushes one or more config fields to the group as
 * the inviter picks pack/car/track/session/duration, so invited pods
 * see the live preview update. Only the inviter is allowed to call
 * this (coordinator enforces it too) and only while actually in a
 * multiplayer group -- a no-op otherwise, so it's safe to sprinkle
 * into the same screens single-player uses without an if-check at
 * every call site. */
function postMpConfig(fields) {
  if (S.mode !== "multiplayer" || !S.mpGroupId || !S.mpIsInviter) return;
  mpApi(`/api/groups/${S.mpGroupId}/config`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pod_id: S.mpPodId, ...fields }),
  }).catch((err) => console.warn("[mp] config update failed:", err));
}

/* Called once at boot. If this pod has no mp_config.json, S.mpAvailable
 * stays false and Multiplayer just doesn't show up as an option --
 * single-player works the same either way. */
async function initMultiplayer() {
  let cfg;
  try {
    cfg = await api("/api/mp/config");
  } catch (err) {
    console.warn("[mp] couldn't load /api/mp/config:", err);
    return;
  }
  if (!cfg.available) return;

  S.mpAvailable = true;
  S.mpPodId = cfg.pod_id;
  S.mpControlPcUrl = cfg.control_pc_url;

  try {
    await mpApi(`/api/pods/${S.mpPodId}/register`, { method: "POST" });
  } catch (err) {
    console.warn("[mp] couldn't reach the control PC's coordinator:", err);
    S.mpAvailable = false;
    return;
  }

  // One persistent connection, opened as soon as the app loads (even
  // on the idle welcome screen) -- this is how a pod finds out it's
  // been invited in the first place, and everything that happens in
  // whatever group it's part of afterward arrives on this same stream.
  const source = new EventSource(`${S.mpControlPcUrl}/api/pods/${S.mpPodId}/events`);

  source.addEventListener("invited", (e) => {
    const group = JSON.parse(e.data);
    // Don't interrupt an in-progress single-player flow just because
    // another pod invited this one -- only honor it while genuinely
    // idle. A declined/missed invite still resolves on its own via
    // the coordinator's timeout.
    if (currentScreen !== screenWelcome) {
      console.warn("[mp] invite arrived while busy -- ignoring:", group.group_id);
      return;
    }
    S.mode = "multiplayer";
    S.mpGroupId = group.group_id;
    S.mpIsInviter = false;
    S.mpGroup = group;
    goto(screenMpStatus);
  });

  const refreshAndRerender = (e) => {
    const data = JSON.parse(e.data);
    if (data.group_id && data.group_id !== S.mpGroupId) return;
    mpApi(`/api/groups/${S.mpGroupId}`)
      .then((group) => {
        S.mpGroup = group;
        if (currentScreen === screenMpStatus) screenMpStatus();
      })
      .catch((err) => console.warn("[mp] refresh failed:", err));
  };
  source.addEventListener("config_updated", refreshAndRerender);
  source.addEventListener("member_responded", refreshAndRerender);
  source.addEventListener("all_accepted", refreshAndRerender);

  source.addEventListener("session_started", (e) => {
    const data = JSON.parse(e.data);
    if (data.group_id !== S.mpGroupId) return;
    goto(() => screenMpLaunching(data));
  });

  source.addEventListener("session_ended", (e) => {
    const data = JSON.parse(e.data);
    if (data.group_id !== S.mpGroupId) return;
    goto(() => screenMpEnded(data.reason));
  });
}

// ---------------------------------------------------------- helpers

function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstChild;
}

function renderScreen(innerHtml) {
  app.innerHTML = "";
  const screen = el(`<div class="screen">${innerHtml}</div>`);
  app.appendChild(screen);
  return screen;
}

/* A single-row, keyboard + click navigable list of items. `items` is
 * an array of {id, render(): htmlString}. Calls onSelect(item) when
 * chosen. Returns nothing -- wires currentKeyHandler itself.
 *
 * Builds each card's DOM element exactly once. Moving focus (hover or
 * arrow keys) only toggles the "focused" class -- it does NOT rebuild
 * the DOM. Rebuilding on every mouseenter (the original approach) let
 * a hover-triggered rebuild swap out the very element the browser was
 * about to fire a click on, which made clicks silently do nothing
 * with no console error -- exactly the symptom hit on real hardware. */
function mountCarousel(container, items, onSelect, startIndex = 0) {
  let focusIndex = Math.min(startIndex, items.length - 1);
  const cardEls = [];

  function updateFocus() {
    cardEls.forEach((cardEl, i) => cardEl.classList.toggle("focused", i === focusIndex));
    const focused = cardEls[focusIndex];
    if (focused) focused.scrollIntoView({ block: "nearest", inline: "nearest" });
  }

  container.innerHTML = "";
  items.forEach((item, i) => {
    const cardEl = el(item.render());
    cardEl.addEventListener("click", () => onSelect(item));
    cardEl.addEventListener("mouseenter", () => {
      focusIndex = i;
      updateFocus();
    });
    container.appendChild(cardEl);
    cardEls.push(cardEl);
  });
  updateFocus();

  currentKeyHandler = (e) => {
    if (e.key === "ArrowRight") {
      e.preventDefault();
      focusIndex = Math.min(focusIndex + 1, items.length - 1);
      updateFocus();
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      focusIndex = Math.max(focusIndex - 1, 0);
      updateFocus();
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (items[focusIndex]) onSelect(items[focusIndex]);
    }
  };
}

/* A simple N-option menu (big buttons in a row). Same fix as
 * mountCarousel above: build once, toggle "focused" on hover/arrow
 * keys instead of rebuilding the DOM out from under a click. */
function mountMenu(container, options, onSelect, startIndex = 0) {
  let focusIndex = startIndex;
  const btnEls = [];

  function updateFocus() {
    btnEls.forEach((btn, i) => btn.classList.toggle("focused", i === focusIndex));
  }

  container.innerHTML = "";
  options.forEach((opt, i) => {
    const btn = el(`<div class="menu-btn">${opt.label}</div>`);
    btn.addEventListener("click", () => onSelect(opt));
    btn.addEventListener("mouseenter", () => {
      focusIndex = i;
      updateFocus();
    });
    container.appendChild(btn);
    btnEls.push(btn);
  });
  updateFocus();

  currentKeyHandler = (e) => {
    if (e.key === "ArrowRight") {
      e.preventDefault();
      focusIndex = Math.min(focusIndex + 1, options.length - 1);
      updateFocus();
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      focusIndex = Math.max(focusIndex - 1, 0);
      updateFocus();
    } else if (e.key === "Enter") {
      e.preventDefault();
      onSelect(options[focusIndex]);
    }
  };
}

/* A single slider with keyboard Left/Right adjust + Enter to confirm. */
function mountSlider(valueEl, sliderEl, { min, max, step, value, onChange, onConfirm }) {
  sliderEl.min = min;
  sliderEl.max = max;
  sliderEl.step = step;
  sliderEl.value = value;
  valueEl.textContent = value;

  sliderEl.addEventListener("input", () => {
    onChange(Number(sliderEl.value));
    valueEl.textContent = sliderEl.value;
  });

  currentKeyHandler = (e) => {
    if (e.key === "ArrowRight") {
      e.preventDefault();
      sliderEl.value = Math.min(Number(sliderEl.value) + step, max);
      sliderEl.dispatchEvent(new Event("input"));
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      sliderEl.value = Math.max(Number(sliderEl.value) - step, min);
      sliderEl.dispatchEvent(new Event("input"));
    } else if (e.key === "Enter") {
      e.preventDefault();
      onConfirm();
    }
  };
}

// ----------------------------------------------------------- screens

function screenWelcome() {
  const screen = renderScreen(`
    <div class="welcome">
      <div class="eyebrow">The Swing Spot</div>
      <div class="title">Ready to Race?</div>
      <div class="tap-cta">Tap anywhere or press Enter to start</div>
    </div>
  `);
  const start = () => goto(screenName);
  screen.addEventListener("click", start);
  currentKeyHandler = (e) => {
    if (e.key === "Enter") start();
  };
}

function screenName() {
  const screen = renderScreen(`
    <div class="eyebrow">Step 1 of 6</div>
    <div class="title">What's your name?</div>
    <input class="name-input" type="text" placeholder="Enter your name" maxlength="24" />
    <div class="hint">Press Enter to continue, or leave blank for "Guest"</div>
  `);
  const input = screen.querySelector("input");
  input.value = S.customerName;
  input.focus();

  const submit = () => {
    S.customerName = input.value.trim() || "Guest";
    // Pods without mp_config.json never offer Multiplayer -- straight
    // to the same single-player flow as before.
    goto(S.mpAvailable ? screenMode : screenPack);
  };

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") submit();
  });
  currentKeyHandler = null; // input field owns its own key events
}

function screenMode() {
  const screen = renderScreen(`
    <div class="eyebrow">Step 2 of 6</div>
    <div class="title">Single Player or Multiplayer?</div>
    <div class="menu" id="menu"></div>
    <div class="hint">Use ← / → and Enter, or click an option</div>
  `);
  const container = screen.querySelector("#menu");
  mountMenu(
    container,
    [
      { id: "single", label: "Single Player" },
      { id: "multiplayer", label: "Multiplayer" },
    ],
    (opt) => {
      S.mode = opt.id;
      if (opt.id === "multiplayer") {
        goto(screenMpInvitePods);
      } else {
        goto(screenPack);
      }
    }
  );
}

// -------------------------------------------------------- multiplayer UI

async function screenMpInvitePods() {
  const screen = renderScreen(`
    <div class="eyebrow">Multiplayer</div>
    <div class="title">Invite pods to race</div>
    <div class="carousel" id="pod-list"></div>
    <div class="primary-btn" id="send-btn">Send Invites</div>
    <div class="hint">Click pods to select them, then Send Invites. Only idle pods can be invited.</div>
  `);

  let pods;
  try {
    const data = await mpApi("/api/pods");
    pods = data.pods.filter((p) => p.pod_id !== S.mpPodId);
  } catch (err) {
    renderError(screen, `Couldn't reach the control PC: ${err.message}`, screenMpInvitePods);
    return;
  }

  const listEl = screen.querySelector("#pod-list");
  const sendBtn = screen.querySelector("#send-btn");
  const selected = new Set();

  function paintPods() {
    listEl.innerHTML = "";
    if (pods.length === 0) {
      listEl.innerHTML = `<div class="hint">No other pods are online right now.</div>`;
      return;
    }
    pods.forEach((p) => {
      const idle = p.status === "idle";
      const card = el(`
        <div class="card ${selected.has(p.pod_id) ? "focused" : ""}" style="${idle ? "" : "opacity:0.4;cursor:default;"}">
          <div class="thumb">${idle ? (selected.has(p.pod_id) ? "Selected" : "Idle") : escapeHtml(p.status)}</div>
          <div class="label"><div class="name">${escapeHtml(p.pod_id)}</div></div>
        </div>`);
      if (idle) {
        card.addEventListener("click", () => {
          if (selected.has(p.pod_id)) selected.delete(p.pod_id);
          else selected.add(p.pod_id);
          paintPods();
        });
      }
      listEl.appendChild(card);
    });
  }
  paintPods();

  const sendInvites = async () => {
    if (selected.size === 0) return;
    try {
      const group = await mpApi("/api/groups", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          inviter_pod_id: S.mpPodId,
          invitee_pod_ids: [...selected],
          inviter_name: S.customerName,
        }),
      });
      S.mpGroupId = group.group_id;
      S.mpIsInviter = true;
      S.mpGroup = group;
      goto(screenPack);
    } catch (err) {
      renderError(screen, err.message, screenMpInvitePods);
    }
  };
  sendBtn.addEventListener("click", sendInvites);
  currentKeyHandler = (e) => {
    if (e.key === "Enter") sendInvites();
  };
}

function screenMpStatus() {
  const group = S.mpGroup;
  const isInviter = S.mpIsInviter;
  const myStatus = group.invite_status[S.mpPodId];
  const allAccepted = Object.values(group.invite_status).every((v) => v === "accepted");
  const cfg = group.config || {};

  const configRows = [
    ["Pack", cfg.pack_id || "—"],
    ["Car", cfg.car_id || "—"],
    ["Track", cfg.track_id || "—"],
    ["Session", cfg.session_type || "—"],
    ["Length", cfg.duration_minutes ? `${cfg.duration_minutes} min` : "—"],
  ];

  const statusRows = group.member_pod_ids
    .map((pid) => {
      const label = pid === group.inviter_pod_id ? `${pid} (host)` : pid;
      return `<div class="summary-row"><span class="k">${escapeHtml(label)}</span><span class="v">${escapeHtml(group.invite_status[pid])}</span></div>`;
    })
    .join("");

  let actionHtml = "";
  if (isInviter) {
    actionHtml = allAccepted
      ? `<div class="primary-btn focused" id="start-btn">Start Session</div>`
      : `<div class="hint">Waiting for everyone to accept...</div>`;
    actionHtml += `<div class="hint" id="cancel-btn" style="cursor:pointer;text-decoration:underline;">Cancel invite</div>`;
  } else if (myStatus === "pending") {
    actionHtml = `
      <div class="menu" id="respond-menu"></div>`;
  } else {
    actionHtml = `<div class="hint">Waiting for the host to start the race...</div>`;
  }

  const screen = renderScreen(`
    <div class="eyebrow">Multiplayer &middot; ${isInviter ? "You're hosting" : `Invited by ${escapeHtml(group.inviter_pod_id)}`}</div>
    <div class="title">${myStatus === "pending" ? "Join the race?" : "Race setup"}</div>
    <div class="summary" style="margin-bottom:16px;">
      ${configRows.map(([k, v]) => `<div class="summary-row"><span class="k">${escapeHtml(k)}</span><span class="v">${escapeHtml(v)}</span></div>`).join("")}
    </div>
    <div class="summary">${statusRows}</div>
    ${actionHtml}
  `);

  if (isInviter) {
    if (allAccepted) {
      const startBtn = screen.querySelector("#start-btn");
      const start = async () => {
        try {
          await mpApi(`/api/groups/${S.mpGroupId}/start`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ pod_id: S.mpPodId }),
          });
          // The session_started SSE event (fired to every member,
          // inviter included) is what actually advances the screen --
          // no direct goto() here, so all pods transition together.
        } catch (err) {
          renderError(screen, err.message, screenMpStatus);
        }
      };
      startBtn.addEventListener("click", start);
      currentKeyHandler = (e) => {
        if (e.key === "Enter") start();
      };
    } else {
      currentKeyHandler = null;
    }
    const cancelBtn = screen.querySelector("#cancel-btn");
    cancelBtn.addEventListener("click", () => {
      mpApi(`/api/groups/${S.mpGroupId}/end`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pod_id: S.mpPodId, reason: "cancelled_by_host" }),
      }).catch((err) => console.warn("[mp] cancel failed:", err));
    });
  } else if (myStatus === "pending") {
    const menuContainer = screen.querySelector("#respond-menu");
    mountMenu(
      menuContainer,
      [
        { id: "accept", label: "Accept" },
        { id: "decline", label: "Decline" },
      ],
      (opt) => {
        mpApi(`/api/groups/${S.mpGroupId}/respond`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ pod_id: S.mpPodId, response: opt.id, customer_name: S.customerName }),
        }).catch((err) => console.warn("[mp] respond failed:", err));
        // Same as Start above -- member_responded / session_ended SSE
        // events drive the actual screen transition.
      }
    );
  } else {
    currentKeyHandler = null;
  }
}

async function screenMpLaunching(startedData) {
  renderScreen(`
    <div class="status-screen">
      <div class="spinner"></div>
      <div class="title" style="font-size:28px;">Connecting to the race&hellip;</div>
    </div>
  `);
  currentKeyHandler = null;

  const cfg = startedData.config || {};
  const conn = startedData.connection || {};

  try {
    const result = await api("/api/mp/join", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        server_ip: conn.server_ip,
        server_port: conn.server_port,
        server_http_port: conn.server_http_port,
        car_id: cfg.car_id,
        track_id: cfg.track_id,
        track_layout: cfg.track_layout || "",
        customer_name: S.customerName,
      }),
    });
    renderScreen(`
      <div class="status-screen">
        <div class="success-msg">Connecting!</div>
        <div class="hint">${escapeHtml(result.race_ini_path || "")}</div>
      </div>
    `);
  } catch (err) {
    renderScreen(`
      <div class="status-screen">
        <div class="title" style="font-size:28px;color:var(--error);">Couldn't connect</div>
        <div class="error-msg">${escapeHtml(err.message)}</div>
      </div>
    `);
  }
}

function screenMpEnded(reason) {
  const screen = renderScreen(`
    <div class="status-screen">
      <div class="title" style="font-size:28px;">Session ended</div>
      <div class="hint">${escapeHtml(reason || "")}</div>
      <div class="hint" style="margin-top:24px;">Press Enter or tap to return to the start</div>
    </div>
  `);
  const resetAndReturn = () => {
    S.mode = "single";
    S.mpGroupId = null;
    S.mpIsInviter = false;
    S.mpGroup = null;
    history = [];
    goto(screenWelcome);
  };
  screen.addEventListener("click", resetAndReturn);
  currentKeyHandler = (e) => {
    if (e.key === "Enter") resetAndReturn();
  };
}

function stepLabel(n) {
  // The same screens serve both flows; multiplayer's step count
  // doesn't match single-player's (extra invite-pods screen, no AI
  // step), so just say "Multiplayer setup" there instead of a
  // misleading step number.
  return S.mode === "multiplayer" ? "Multiplayer setup" : `Step ${n} of 6`;
}

async function screenPack() {
  const screen = renderScreen(`
    <div class="eyebrow">${stepLabel(2)}</div>
    <div class="title">Choose a content pack</div>
    <div class="carousel" id="carousel"></div>
    <div class="hint">Use ← / → and Enter, or click a pack</div>
  `);
  let data;
  try {
    data = await api("/api/packs");
  } catch (err) {
    renderError(screen, err.message, screenPack);
    return;
  }

  const container = screen.querySelector("#carousel");
  const items = data.packs.map((p) => ({
    id: p.id,
    render: () => `
      <div class="card">
        <div class="thumb"><img src="/api/packs/${encodeURIComponent(p.id)}/preview" onerror="this.parentElement.textContent='${escapeHtml(p.label).replace(/'/g, "\\'")}'" /></div>
        <div class="label"><div class="name">${escapeHtml(p.label)}</div></div>
      </div>`,
  }));

  mountCarousel(container, items, (item) => {
    S.packId = item.id;
    S.packLabel = data.packs.find((p) => p.id === item.id).label;
    postMpConfig({ pack_id: S.packId });
    goto(screenCar);
  });
}

async function screenCar() {
  const screen = renderScreen(`
    <div class="eyebrow">${stepLabel(3)} &middot; ${escapeHtml(S.packLabel)}</div>
    <div class="title">Choose your car</div>
    <div class="carousel" id="carousel"></div>
    <div class="hint">Use ← / → and Enter, or click a car</div>
  `);
  let data;
  try {
    data = await api(`/api/packs/${encodeURIComponent(S.packId)}`);
  } catch (err) {
    renderError(screen, err.message, screenCar);
    return;
  }

  const container = screen.querySelector("#carousel");
  const items = [
    randomCard("Random Car"),
    ...data.cars.map((c) => ({
      id: c.id,
      render: () => `
        <div class="card">
          <div class="thumb"><img src="/api/content/car/${encodeURIComponent(c.id)}/preview" onerror="this.parentElement.textContent='No preview'" /></div>
          <div class="label">
            <div class="name">${escapeHtml(c.name)}</div>
            <div class="sub">${escapeHtml(c.brand || "")}</div>
          </div>
        </div>`,
    })),
  ];

  mountCarousel(container, items, (item) => {
    const car = item.id === RANDOM_ID
      ? data.cars[Math.floor(Math.random() * data.cars.length)]
      : data.cars.find((c) => c.id === item.id);
    S.carId = car.id;
    S.carName = car.name;
    postMpConfig({ car_id: S.carId });
    goto(screenTrack);
  });
}

async function screenTrack() {
  const screen = renderScreen(`
    <div class="eyebrow">${stepLabel(4)} &middot; ${escapeHtml(S.packLabel)}</div>
    <div class="title">Choose your track</div>
    <div class="carousel" id="carousel"></div>
    <div class="hint">Use ← / → and Enter, or click a track</div>
  `);
  let data;
  try {
    data = await api(`/api/packs/${encodeURIComponent(S.packId)}`);
  } catch (err) {
    renderError(screen, err.message, screenTrack);
    return;
  }

  const container = screen.querySelector("#carousel");
  const items = [
    randomCard("Random Track"),
    ...data.tracks.map((t) => ({
      id: t.id,
      render: () => `
        <div class="card">
          <div class="thumb"><img src="/api/content/track/${encodeURIComponent(t.id)}/preview" onerror="this.parentElement.textContent='No preview'" /></div>
          <div class="label"><div class="name">${escapeHtml(t.name)}</div></div>
        </div>`,
    })),
  ];

  mountCarousel(container, items, (item) => {
    const track = item.id === RANDOM_ID
      ? data.tracks[Math.floor(Math.random() * data.tracks.length)]
      : data.tracks.find((t) => t.id === item.id);
    S.trackId = track.id;
    S.trackName = track.name;
    postMpConfig({ track_id: S.trackId });
    if (track.layouts.length > 1) {
      goto(() => screenLayout(track));
    } else {
      S.layoutId = track.layouts[0] ? track.layouts[0].id : "";
      S.layoutName = track.layouts[0] ? track.layouts[0].name : "";
      postMpConfig({ track_layout: S.layoutId });
      goto(screenSessionType);
    }
  });
}

function screenLayout(track) {
  const screen = renderScreen(`
    <div class="eyebrow">${stepLabel(4)} &middot; ${escapeHtml(S.trackName)}</div>
    <div class="title">Choose a layout</div>
    <div class="carousel" id="carousel"></div>
    <div class="hint">Use ← / → and Enter, or click a layout</div>
  `);
  const container = screen.querySelector("#carousel");
  // Note: the API serializes each layout as {id, name} (see app.py's
  // api_pack_detail) -- not {layout_id, name}. Using the wrong field
  // name here previously made every layout resolve to `undefined`,
  // which JSON.stringify then silently drops from the request body,
  // leaving race.ini's CONFIG_TRACK empty (the "track is missing"
  // launch error).
  const items = track.layouts.map((l) => ({
    id: l.id,
    render: () => `
      <div class="card">
        <div class="thumb"><img src="/api/content/track/${encodeURIComponent(track.id)}/preview?layout=${encodeURIComponent(l.id)}" onerror="this.parentElement.textContent='No preview'" /></div>
        <div class="label"><div class="name">${escapeHtml(l.name)}</div></div>
      </div>`,
  }));

  mountCarousel(container, items, (item) => {
    const layout = track.layouts.find((l) => l.id === item.id);
    S.layoutId = layout.id;
    S.layoutName = layout.name;
    postMpConfig({ track_layout: S.layoutId });
    goto(screenSessionType);
  });
}

function screenSessionType() {
  const screen = renderScreen(`
    <div class="eyebrow">${stepLabel(5)}</div>
    <div class="title">Practice or Race?</div>
    <div class="menu" id="menu"></div>
    <div class="hint">Use ← / → and Enter, or click an option</div>
  `);
  const container = screen.querySelector("#menu");
  // Multiplayer has no AI opponents, so the "(with AI opponents)"
  // hint on Race only applies in single-player.
  const raceLabel = S.mode === "multiplayer" ? "Race" : "Race (with AI opponents)";
  mountMenu(
    container,
    [
      { id: "practice", label: "Practice" },
      { id: "race", label: raceLabel },
    ],
    (opt) => {
      S.sessionType = opt.id;
      postMpConfig({ session_type: S.sessionType });
      goto(screenDuration);
    }
  );
}

function screenDuration() {
  const screen = renderScreen(`
    <div class="eyebrow">${stepLabel(6)}</div>
    <div class="title">How long do you want to drive?</div>
    <div class="slider-block">
      <div class="slider-value" id="value"></div>
      <div class="slider-row">
        <input type="range" id="slider" />
      </div>
      <div class="slider-hint">1 to 60 minutes &middot; press Enter to continue</div>
    </div>
  `);
  const valueEl = screen.querySelector("#value");
  const sliderEl = screen.querySelector("#slider");

  const paintValue = (v) => (valueEl.textContent = `${v} min`);
  paintValue(S.durationMinutes);

  mountSlider(valueEl, sliderEl, {
    min: 1,
    max: 60,
    step: 1,
    value: S.durationMinutes,
    onChange: (v) => {
      S.durationMinutes = v;
      paintValue(v);
    },
    onConfirm: () => {
      postMpConfig({ duration_minutes: S.durationMinutes });
      if (S.mode === "multiplayer") {
        // No AI step in multiplayer -- straight to the shared waiting
        // room/status screen (also used by invitees to accept/decline).
        goto(screenMpStatus);
      } else if (S.sessionType === "race") {
        goto(screenAiSettings);
      } else {
        goto(screenConfirm);
      }
    },
  });
}

function screenAiSettings() {
  const screen = renderScreen(`
    <div class="eyebrow">AI Opponents</div>
    <div class="title">Number of opponents</div>
    <div class="slider-block">
      <div class="slider-value" id="countValue"></div>
      <div class="slider-row"><input type="range" id="countSlider" /></div>
      <div class="slider-hint">0 to 8 &middot; press Enter to continue to skill level</div>
    </div>
  `);
  const countValueEl = screen.querySelector("#countValue");
  const countSliderEl = screen.querySelector("#countSlider");
  const paintCount = (v) => (countValueEl.textContent = `${v} car${v === 1 ? "" : "s"}`);
  paintCount(S.aiCount);

  mountSlider(countValueEl, countSliderEl, {
    min: 0,
    max: 8,
    step: 1,
    value: S.aiCount,
    onChange: (v) => {
      S.aiCount = v;
      paintCount(v);
    },
    onConfirm: () => {
      if (S.aiCount === 0) {
        goto(screenConfirm);
      } else {
        goto(screenAiSkill);
      }
    },
  });
}

function screenAiSkill() {
  const screen = renderScreen(`
    <div class="eyebrow">AI Opponents</div>
    <div class="title">Opponent skill level</div>
    <div class="slider-block">
      <div class="slider-value" id="skillValue"></div>
      <div class="slider-row"><input type="range" id="skillSlider" /></div>
      <div class="slider-hint">80 (relaxed) to 100 (very fast) &middot; press Enter to continue</div>
    </div>
  `);
  const skillValueEl = screen.querySelector("#skillValue");
  const skillSliderEl = screen.querySelector("#skillSlider");
  const paintSkill = (v) => (skillValueEl.textContent = v);
  paintSkill(S.aiLevel);

  mountSlider(skillValueEl, skillSliderEl, {
    min: 80,
    max: 100,
    step: 1,
    value: S.aiLevel,
    onChange: (v) => {
      S.aiLevel = v;
      paintSkill(v);
    },
    onConfirm: () => goto(screenConfirm),
  });
}

function screenConfirm() {
  const rows = [
    ["Driver", S.customerName],
    ["Pack", S.packLabel],
    ["Car", S.carName],
    ["Track", S.layoutName || S.trackName],
    ["Session", S.sessionType === "race" ? "Race" : "Practice"],
    ["Length", `${S.durationMinutes} min`],
  ];
  if (S.sessionType === "race") {
    rows.push(["AI opponents", `${S.aiCount} @ skill ${S.aiLevel}`]);
  }

  const screen = renderScreen(`
    <div class="eyebrow">Ready to go, ${escapeHtml(S.customerName)}?</div>
    <div class="title">Confirm your session</div>
    <div class="summary">
      ${rows.map(([k, v]) => `<div class="summary-row"><span class="k">${escapeHtml(k)}</span><span class="v">${escapeHtml(String(v))}</span></div>`).join("")}
    </div>
    <div class="primary-btn focused" id="startBtn">Start Session</div>
    <div class="hint">Press Enter to start, or Backspace to change something</div>
  `);

  const startBtn = screen.querySelector("#startBtn");
  const start = () => goto(screenLaunching);
  startBtn.addEventListener("click", start);
  currentKeyHandler = (e) => {
    if (e.key === "Enter") start();
  };
}

async function screenLaunching() {
  renderScreen(`
    <div class="status-screen">
      <div class="spinner"></div>
      <div class="title" style="font-size:28px;">Starting your session&hellip;</div>
    </div>
  `);
  currentKeyHandler = null;

  try {
    const result = await api("/api/session/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        customer_name: S.customerName,
        car_id: S.carId,
        track_id: S.trackId,
        track_layout: S.layoutId,
        session_type: S.sessionType,
        duration_minutes: S.durationMinutes,
        ai_count: S.aiCount,
        ai_level: S.aiLevel,
      }),
    });
    renderScreen(`
      <div class="status-screen">
        <div class="success-msg">Session launched!</div>
        <div class="hint">${escapeHtml(result.race_ini_path || "")}</div>
      </div>
    `);
  } catch (err) {
    const screen = renderScreen(`
      <div class="status-screen">
        <div class="title" style="font-size:28px;color:var(--error);">Couldn't start the session</div>
        <div class="error-msg">${escapeHtml(err.message)}</div>
        <div class="primary-btn focused" id="retryBtn" style="margin-top:32px;">Back to Confirm</div>
      </div>
    `);
    const retryBtn = screen.querySelector("#retryBtn");
    const retry = () => goto(screenConfirm);
    retryBtn.addEventListener("click", retry);
    currentKeyHandler = (e) => {
      if (e.key === "Enter") retry();
    };
  }
}

function renderError(screen, message, retryScreenFn) {
  screen.insertAdjacentHTML(
    "beforeend",
    `<div class="error-msg">${escapeHtml(message)}</div>
     <div class="primary-btn focused" id="retryBtn" style="margin-top:24px;">Retry</div>`
  );
  const retryBtn = screen.querySelector("#retryBtn");
  // Re-run the same screen directly (it's already `currentScreen` --
  // goto() was called to get here) rather than going through goto(),
  // which would push a duplicate entry onto the back-navigation history.
  const retry = () => retryScreenFn();
  retryBtn.addEventListener("click", retry);
  currentKeyHandler = (e) => {
    if (e.key === "Enter") retry();
  };
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str == null ? "" : str;
  return div.innerHTML;
}

// ------------------------------------------------------------- boot

goto(screenWelcome);
// Doesn't block the welcome screen from showing -- by the time a
// customer taps through past name entry (where S.mpAvailable is
// actually checked), this local-network call has long since resolved.
initMultiplayer();
