const dom = {
  sessionId: document.getElementById("sessionId"),
  userId: document.getElementById("userId"),
  userRole: document.getElementById("userRole"),
  topK: document.getElementById("topK"),
  intentText: document.getElementById("intentText"),
  submitBtn: document.getElementById("submitBtn"),
  fillDemoBtn: document.getElementById("fillDemoBtn"),
  clearBtn: document.getElementById("clearBtn"),
  healthBtn: document.getElementById("healthBtn"),
  healthBadge: document.getElementById("healthBadge"),
  nluView: document.getElementById("nluView"),
  responseView: document.getElementById("responseView"),
  compareBtn: document.getElementById("compareBtn"),
  compareIsolateSession: document.getElementById("compareIsolateSession"),
  compareSummary: document.getElementById("compareSummary"),
  compareView: document.getElementById("compareView"),
  timeline: document.getElementById("timeline"),
  confirmPanel: document.getElementById("confirmPanel"),
  confirmToken: document.getElementById("confirmToken"),
  confirmAcceptBtn: document.getElementById("confirmAcceptBtn"),
  confirmRejectBtn: document.getElementById("confirmRejectBtn"),
  deviceQuery: document.getElementById("deviceQuery"),
  deviceDomain: document.getElementById("deviceDomain"),
  deviceLimit: document.getElementById("deviceLimit"),
  deviceStatus: document.getElementById("deviceStatus"),
  deviceRefreshBtn: document.getElementById("deviceRefreshBtn"),
  deviceList: document.getElementById("deviceList"),
  templateHint: document.getElementById("templateHint"),
  templateButtons: document.getElementById("templateButtons"),
  historyRefreshBtn: document.getElementById("historyRefreshBtn"),
  historyClearBtn: document.getElementById("historyClearBtn"),
  historyList: document.getElementById("historyList"),
};

const STORAGE_KEY = "smarthome-web-profile-v1";

const state = {
  pendingToken: "",
  selectedDeviceId: "",
  devices: [],
};

function nowLabel() {
  return new Date().toLocaleTimeString();
}

function setText(el, text) {
  el.textContent = text;
}

function pushTimeline(title, detail) {
  const item = document.createElement("li");
  const strong = document.createElement("strong");
  strong.textContent = title;
  const desc = document.createElement("div");
  desc.textContent = detail;
  const small = document.createElement("small");
  small.textContent = nowLabel();

  item.appendChild(strong);
  item.appendChild(document.createElement("br"));
  item.appendChild(desc);
  item.appendChild(document.createElement("br"));
  item.appendChild(small);
  dom.timeline.prepend(item);
}

function setBadge(kind, text) {
  dom.healthBadge.className = "badge";
  if (kind === "ok") {
    dom.healthBadge.classList.add("badge-ok");
  } else if (kind === "error") {
    dom.healthBadge.classList.add("badge-error");
  } else {
    dom.healthBadge.classList.add("badge-muted");
  }
  dom.healthBadge.textContent = text;
}

function setBusy(busy) {
  dom.submitBtn.disabled = busy;
  dom.compareBtn.disabled = busy;
  dom.confirmAcceptBtn.disabled = busy;
  dom.confirmRejectBtn.disabled = busy;
  dom.submitBtn.textContent = busy ? "发送中..." : "发送指令";
  dom.compareBtn.textContent = busy ? "对比执行中..." : "执行双通道对比";
}

function showResponse(payload) {
  setText(dom.responseView, JSON.stringify(payload, null, 2));
}

function extractNluResult(payload) {
  const data = payload?.data || {};
  if (data?.sub_intent === "multi_command" && Array.isArray(data.items)) {
    return {
      intent: data.intent || "BATCH",
      sub_intent: data.sub_intent || "multi_command",
      status: data.status || "",
      items: data.items.map((item) => ({
        index: item.index,
        text: item.text,
        code: item.code,
        status: item.status,
        nlu: item.nlu || null,
      })),
    };
  }
  if (data?.nlu) {
    return data.nlu;
  }
  return { message: "本次响应未返回语义解析详情" };
}

function showNlu(payload) {
  setText(dom.nluView, JSON.stringify(payload, null, 2));
}

function showCompare(summary, payload) {
  setText(dom.compareSummary, summary);
  setText(dom.compareView, JSON.stringify(payload, null, 2));
}

function showConfirm(token) {
  state.pendingToken = token || "";
  if (!state.pendingToken) {
    dom.confirmPanel.classList.add("hidden");
    setText(dom.confirmToken, "-");
    return;
  }
  dom.confirmPanel.classList.remove("hidden");
  setText(dom.confirmToken, state.pendingToken);
}

function defaultSessionId() {
  return `sess_web_${new Date().toISOString().slice(0, 10).replace(/-/g, "")}`;
}

function loadProfile() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return;
    }
    const parsed = JSON.parse(raw);
    if (parsed.session_id) {
      dom.sessionId.value = String(parsed.session_id);
    }
    if (parsed.user_id) {
      dom.userId.value = String(parsed.user_id);
    }
    if (parsed.user_role) {
      dom.userRole.value = String(parsed.user_role);
    }
    if (parsed.top_k) {
      dom.topK.value = String(parsed.top_k);
    }
  } catch (_) {
    // ignore malformed local storage payload
  }
}

function saveProfile() {
  const payload = {
    session_id: dom.sessionId.value.trim() || defaultSessionId(),
    user_id: dom.userId.value.trim() || "usr_web_001",
    user_role: dom.userRole.value,
    top_k: Number(dom.topK.value || 3),
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
}

function currentSessionId() {
  const sid = dom.sessionId.value.trim() || defaultSessionId();
  dom.sessionId.value = sid;
  return sid;
}

function currentUserId() {
  const uid = dom.userId.value.trim() || "usr_web_001";
  dom.userId.value = uid;
  return uid;
}

function buildPayload(textOverride = "") {
  const text = (textOverride || dom.intentText.value).trim();
  return {
    session_id: currentSessionId(),
    user_id: currentUserId(),
    user_role: dom.userRole.value,
    top_k: Math.max(1, Math.min(5, Number(dom.topK.value || 3))),
    text,
  };
}

async function requestJson(url, options = {}) {
  const resp = await fetch(url, options);
  const data = await resp.json();
  return { httpStatus: resp.status, data };
}

function selectedDevice() {
  return state.devices.find((d) => d.entity_id === state.selectedDeviceId) || null;
}

function templateByDevice(device) {
  const commonTemplates = ["关闭某设备"];

  if (!device) {
    return [
      "把客厅灯调到60%",
      ...commonTemplates,
      "查询客厅空调状态",
      "把前门解锁",
      "启动回家模式",
    ];
  }

  const name = device.name || device.entity_id;
  const domain = String(device.entity_id || "").split(".")[0];

  if (domain === "light") {
    return [...commonTemplates, `打开${name}`, `关闭${name}`, `把${name}调到60%`, `查询${name}状态`];
  }
  if (domain === "climate") {
    return [...commonTemplates, `打开${name}`, `关闭${name}`, `把${name}温度调到26度`, `查询${name}状态`];
  }
  if (domain === "lock") {
    return [...commonTemplates, `把${name}解锁`, `查询${name}状态`];
  }
  if (domain === "scene") {
    return [...commonTemplates, `启动${name}`, `查询${name}状态`];
  }

  return [...commonTemplates, `查询${name}状态`, `打开${name}`, `关闭${name}`];
}

function renderTemplates() {
  const device = selectedDevice();
  const templates = templateByDevice(device);
  if (!device) {
    setText(dom.templateHint, "未选择设备，显示通用模板。");
  } else {
    setText(dom.templateHint, `当前设备：${device.name || device.entity_id}（点击模板将直接发送）`);
  }

  dom.templateButtons.innerHTML = "";
  templates.forEach((text) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "ghost-btn";
    btn.textContent = text;
    btn.addEventListener("click", () => {
      dom.intentText.value = text;
      submitCommand(text);
    });
    dom.templateButtons.appendChild(btn);
  });
}

function renderDeviceList() {
  dom.deviceList.innerHTML = "";
  if (!state.devices.length) {
    const li = document.createElement("li");
    li.textContent = "未找到设备";
    dom.deviceList.appendChild(li);
    return;
  }

  state.devices.forEach((device) => {
    const li = document.createElement("li");
    li.className = "device-item";
    if (device.entity_id === state.selectedDeviceId) {
      li.classList.add("active");
    }

    const title = document.createElement("strong");
    title.textContent = device.name || device.entity_id;
    li.appendChild(title);

    const meta = document.createElement("div");
    meta.className = "history-meta";
    meta.textContent = device.entity_id;
    li.appendChild(meta);

    const area = document.createElement("span");
    area.className = "pill";
    area.textContent = `area: ${device.area || "-"}`;
    li.appendChild(area);

    const status = document.createElement("span");
    status.className = "pill";
    status.textContent = `state: ${device.state ?? "unknown"}`;
    li.appendChild(status);

    li.addEventListener("click", () => {
      state.selectedDeviceId = device.entity_id;
      renderDeviceList();
      renderTemplates();
      pushTimeline("device-selected", `${device.name || device.entity_id}`);
    });

    dom.deviceList.appendChild(li);
  });
}

async function loadDevices() {
  const query = dom.deviceQuery.value.trim();
  const domain = dom.deviceDomain.value;
  const limit = Math.max(1, Math.min(500, Number(dom.deviceLimit.value || 200)));

  const params = new URLSearchParams();
  if (query) {
    params.set("query", query);
  }
  if (domain) {
    params.set("domain", domain);
  }
  params.set("limit", String(limit));

  try {
    const { data } = await requestJson(`/api/v1/entities?${params.toString()}`);
    if (data.code !== "OK") {
      pushTimeline("devices", `load failed: ${data.code}`);
      setText(dom.deviceStatus, `设备发现状态：请求失败（${data.code}）`);
      return;
    }

    const mode = data?.data?.mode || "unknown";
    const warning = data?.data?.diagnostics?.warning || "";
    const count = Number(data?.data?.count || 0);
    setText(dom.deviceStatus, `设备发现状态：mode=${mode}，count=${count}${warning ? `，${warning}` : ""}`);

    state.devices = Array.isArray(data?.data?.items) ? data.data.items : [];
    if (!state.devices.find((item) => item.entity_id === state.selectedDeviceId)) {
      state.selectedDeviceId = state.devices[0]?.entity_id || "";
    }

    if (mode === "stub") {
      pushTimeline("devices", "当前为 stub 模式，请配置 HA 通道环境变量后重启运行时");
    } else if (!state.devices.length) {
      pushTimeline("devices", "上游 HA 未返回设备，请检查通道连通性与权限");
    }

    renderDeviceList();
    renderTemplates();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setText(dom.deviceStatus, `设备发现状态：异常（${message}）`);
    pushTimeline("devices-error", message);
  }
}

function renderHistory(items) {
  dom.historyList.innerHTML = "";
  if (!items.length) {
    const li = document.createElement("li");
    li.textContent = "当前会话暂无历史记录";
    dom.historyList.appendChild(li);
    return;
  }

  items.forEach((entry) => {
    const li = document.createElement("li");

    const top = document.createElement("strong");
    top.textContent = `${entry.action || "-"} | ${entry.code || "-"}`;
    li.appendChild(top);

    const text = document.createElement("div");
    text.textContent = `Q: ${entry.request_text || ""}`;
    li.appendChild(text);

    const reply = document.createElement("div");
    reply.textContent = `A: ${entry.reply_text || ""}`;
    li.appendChild(reply);

    const meta = document.createElement("div");
    meta.className = "history-meta";
    const dt = entry.ts ? new Date(entry.ts).toLocaleString() : "";
    meta.textContent = `${dt} ${entry.intent ? `| ${entry.intent}/${entry.sub_intent || ""}` : ""}`;
    li.appendChild(meta);

    dom.historyList.appendChild(li);
  });
}

async function loadHistory() {
  const sessionId = currentSessionId();
  try {
    const params = new URLSearchParams({ session_id: sessionId, limit: "100" });
    const { data } = await requestJson(`/api/v1/history?${params.toString()}`);
    if (data.code !== "OK") {
      renderHistory([]);
      return;
    }
    const items = Array.isArray(data?.data?.items) ? data.data.items : [];
    renderHistory(items);
  } catch (_) {
    renderHistory([]);
  }
}

async function clearHistory() {
  const sessionId = currentSessionId();
  try {
    const params = new URLSearchParams({ session_id: sessionId });
    const { data } = await requestJson(`/api/v1/history?${params.toString()}`, { method: "DELETE" });
    showResponse(data);
    pushTimeline("history", "当前会话历史已清空");
    await loadHistory();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    pushTimeline("history-error", message);
  }
}

async function submitCommand(textOverride = "") {
  const payload = buildPayload(textOverride);
  if (!payload.text) {
    pushTimeline("输入校验", "请先输入意图文本");
    return;
  }

  saveProfile();
  setBusy(true);
  try {
    const { httpStatus, data } = await requestJson("/api/v1/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    showResponse(data);
    showNlu(extractNluResult(data));
    const code = data.code || "UNKNOWN";
    const replyText = data?.data?.reply_text || "";
    pushTimeline("command", `code=${code}, http=${httpStatus}${replyText ? `, reply=${replyText}` : ""}`);

    if (code === "POLICY_CONFIRM_REQUIRED") {
      showConfirm(data?.data?.confirm_token || "");
    } else {
      showConfirm("");
    }

    await loadHistory();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    pushTimeline("command-error", message);
    showResponse({ error: message });
  } finally {
    setBusy(false);
  }
}

function summarizeCompare(report) {
  const consistency = report?.consistency || {};
  const pass = Boolean(consistency.pass);
  const gwCode = report?.channels?.ha_gateway?.response?.code || "-";
  const mcpCode = report?.channels?.ha_mcp?.response?.code || "-";
  const checkCount = Array.isArray(consistency.checks) ? consistency.checks.length : 0;
  const failedCount = Array.isArray(consistency.checks)
    ? consistency.checks.filter((item) => !item.pass).length
    : 0;
  return `一致性: ${pass ? "PASS" : "FAIL"} | gw=${gwCode}, mcp=${mcpCode} | checks=${checkCount}, failed=${failedCount}`;
}

async function submitCompare() {
  const payload = buildPayload();
  if (!payload.text) {
    pushTimeline("输入校验", "请先输入意图文本");
    return;
  }

  payload.isolate_session = dom.compareIsolateSession.checked;

  saveProfile();
  setBusy(true);
  try {
    const { httpStatus, data } = await requestJson("/api/v1/compare-channels", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    showResponse(data);
    if (data.code !== "OK") {
      const summary = `对比失败: code=${data.code}, http=${httpStatus}`;
      showCompare(summary, data);
      pushTimeline("compare-error", summary);
      return;
    }

    const report = data.data || {};
    const summary = summarizeCompare(report);
    showCompare(summary, report);
    pushTimeline("compare", summary);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    showCompare(`对比请求异常: ${message}`, { error: message });
    pushTimeline("compare-error", message);
  } finally {
    setBusy(false);
  }
}

async function submitConfirm(accept) {
  if (!state.pendingToken) {
    pushTimeline("confirm", "当前没有待确认 token");
    return;
  }

  setBusy(true);
  try {
    const { httpStatus, data } = await requestJson("/api/v1/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm_token: state.pendingToken, accept }),
    });

    showResponse(data);
    const code = data.code || "UNKNOWN";
    const replyText = data?.data?.reply_text || "";
    pushTimeline("confirm", `accept=${accept}, code=${code}, http=${httpStatus}${replyText ? `, reply=${replyText}` : ""}`);

    if (code !== "POLICY_CONFIRM_REQUIRED") {
      showConfirm("");
    }
    await loadHistory();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    pushTimeline("confirm-error", message);
    showResponse({ error: message });
  } finally {
    setBusy(false);
  }
}

async function refreshHealth() {
  setBadge("muted", "检查中...");
  try {
    const { data } = await requestJson("/api/v1/health");
    if (data.code === "OK") {
      setBadge("ok", "服务在线");
    } else {
      setBadge("error", "服务异常");
    }
  } catch (_) {
    setBadge("error", "连接失败");
  }
}

function fillDemo() {
  dom.intentText.value = "把客厅灯调到60%";
}

function clearTimeline() {
  dom.timeline.innerHTML = "";
  setText(dom.nluView, "等待请求...");
  setText(dom.responseView, "等待请求...");
  setText(dom.compareSummary, "等待对比执行...");
  setText(dom.compareView, "等待对比结果...");
  showConfirm("");
}

function onProfileChanged() {
  saveProfile();
  loadHistory();
}

dom.submitBtn.addEventListener("click", () => submitCommand());
dom.compareBtn.addEventListener("click", submitCompare);
dom.confirmAcceptBtn.addEventListener("click", () => submitConfirm(true));
dom.confirmRejectBtn.addEventListener("click", () => submitConfirm(false));
dom.healthBtn.addEventListener("click", refreshHealth);
dom.fillDemoBtn.addEventListener("click", fillDemo);
dom.clearBtn.addEventListener("click", clearTimeline);
dom.deviceRefreshBtn.addEventListener("click", loadDevices);
dom.historyRefreshBtn.addEventListener("click", loadHistory);
dom.historyClearBtn.addEventListener("click", clearHistory);

dom.sessionId.addEventListener("change", onProfileChanged);
dom.userId.addEventListener("change", onProfileChanged);
dom.userRole.addEventListener("change", onProfileChanged);
dom.topK.addEventListener("change", onProfileChanged);

dom.deviceQuery.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    loadDevices();
  }
});

dom.intentText.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
    submitCommand();
  }
});

loadProfile();
if (!dom.sessionId.value.trim()) {
  dom.sessionId.value = defaultSessionId();
}
if (!dom.userId.value.trim()) {
  dom.userId.value = "usr_web_001";
}
saveProfile();
renderTemplates();
refreshHealth();
loadDevices();
loadHistory();
