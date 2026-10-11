const byId = (id) => document.getElementById(id);

function showNotice(message, isError = false) {
  const notice = byId("proposal-notice");
  notice.textContent = message;
  notice.classList.toggle("error", isError);
  notice.hidden = false;
}

async function responseJson(response) {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body.detail || `Request failed (${response.status}).`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return body;
}

function setServiceCard(name, status, detail) {
  const card = byId(`service-${name}`);
  const state = card.querySelector(".service-state");
  const light = card.querySelector(".status-light");
  state.textContent = detail;
  light.className = `status-light ${status === "ok" ? "status-ok" : status === "unavailable" ? "status-failed" : "status-unknown"}`;
}

async function refreshHealth() {
  try {
    const response = await fetch("/health/dependencies", { cache: "no-store" });
    const payload = await responseJson(response);
    const dependencies = payload.dependencies;
    setServiceCard("postgres", dependencies.postgres.status, dependencies.postgres.status === "ok" ? "Connected" : "Unavailable");
    const redisDetail = dependencies.redis.status !== "ok"
      ? "Unavailable"
      : dependencies.redis.cache_enabled ? "Connected · cache enabled" : "Connected · cache disabled";
    setServiceCard("redis", dependencies.redis.status, redisDetail);
    const kafkaDetail = dependencies.kafka.status !== "ok"
      ? "Unavailable"
      : dependencies.kafka.topic_exists ? "Connected · topic ready" : "Connected · topic missing";
    setServiceCard("kafka", dependencies.kafka.status, kafkaDetail);
  } catch (error) {
    for (const name of ["postgres", "redis", "kafka"]) {
      setServiceCard(name, "unavailable", "Status check failed");
    }
    console.error("Dependency status check failed", error);
  }
}

function setBusy(form, busy, busyLabel) {
  const button = form.querySelector('button[type="submit"]');
  if (!button.dataset.idleLabel) button.dataset.idleLabel = button.textContent.trim();
  button.disabled = busy;
  button.textContent = busy ? busyLabel : button.dataset.idleLabel;
}

function addAgentEvent(label, message, isError = false) {
  const log = byId("agent-events");
  log.querySelector(".empty-state")?.remove();
  const entry = document.createElement("div");
  entry.className = `event-entry${isError ? " error" : ""}`;
  const labelElement = document.createElement("span");
  labelElement.className = "event-label";
  labelElement.textContent = label;
  const content = document.createElement("span");
  content.textContent = message;
  entry.append(labelElement, content);
  log.append(entry);
  log.scrollTop = log.scrollHeight;
}

async function streamAgent(question) {
  const response = await fetch("/agent/ask/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    throw new Error(errorBody.detail || `Agent request failed (${response.status}).`);
  }
  if (!response.body) throw new Error("This browser does not support streaming responses.");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  function handleFrame(frame) {
    let eventName = "message";
    const dataLines = [];
    for (const line of frame.split(/\r?\n/)) {
      if (line.startsWith("event:")) eventName = line.slice(6).trim();
      if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
    }
    if (dataLines.length === 0) return;
    let data;
    try {
      data = JSON.parse(dataLines.join("\n"));
    } catch {
      data = { message: dataLines.join("\n") };
    }

    if (eventName === "status") addAgentEvent("STATUS", data.stage || "Working");
    else if (eventName === "tool_call") addAgentEvent("TOOL CALL", `${data.name}: ${JSON.stringify(data.arguments)}`);
    else if (eventName === "tool_result") addAgentEvent("TOOL RESULT", JSON.stringify(data.result));
    else if (eventName === "approval_required") {
      addAgentEvent("HUMAN REVIEW", `Proposal ${data.approval_id} is pending. Review it in the Approval inbox.`);
      void refreshApprovals();
    } else if (eventName === "answer") addAgentEvent("ANSWER", data.answer || "The agent returned an empty answer.");
    else if (eventName === "error") addAgentEvent("ERROR", data.message || "Agent request failed.", true);
    else addAgentEvent(eventName.toUpperCase(), JSON.stringify(data));
  }

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    buffer = buffer.replace(/\r\n/g, "\n");
    const frames = buffer.split("\n\n");
    buffer = frames.pop() || "";
    for (const frame of frames) handleFrame(frame);
    if (done) break;
  }
  if (buffer.trim()) handleFrame(buffer);
}

byId("rag-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const question = byId("rag-question").value.trim();
  const result = byId("rag-result");
  if (!question) return;
  setBusy(form, true, "Retrieving…");
  result.replaceChildren();
  const answer = document.createElement("p");
  answer.className = "result-text";
  answer.textContent = "";
  result.append(answer);

  try {
    const response = await fetch(`/ask?question=${encodeURIComponent(question)}`);
    if (!response.ok) throw new Error((await response.text()) || `Request failed (${response.status}).`);
    if (!response.body) throw new Error("This browser does not support streaming responses.");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      answer.textContent += decoder.decode(value, { stream: true });
      result.scrollTop = result.scrollHeight;
    }
    answer.textContent += decoder.decode();
  } catch (error) {
    answer.textContent = error.message;
    answer.classList.add("error");
  } finally {
    setBusy(form, false);
  }
});

byId("agent-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const question = byId("agent-question").value.trim();
  if (!question) return;
  byId("agent-events").replaceChildren();
  setBusy(form, true, "Agent working…");
  try {
    await streamAgent(question);
  } catch (error) {
    addAgentEvent("ERROR", error.message, true);
  } finally {
    setBusy(form, false);
  }
});

byId("workflow-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const resultBox = byId("workflow-result");
  const payload = {
    question: "Check this load against the requested carrier and fictional HOS policy.",
    load_request: {
      load_id: byId("check-load-id").value.trim(),
      equipment_type: byId("check-equipment").value,
      weight_lbs: Number(byId("check-weight").value),
      hazmat: byId("check-hazmat").checked,
      origin: byId("check-origin").value.trim(),
      destination: byId("check-destination").value.trim(),
      pickup_at: new Date(byId("check-pickup").value).toISOString(),
      delivery_at: new Date(byId("check-delivery").value).toISOString(),
      requested_carrier_id: byId("check-carrier-id").value.trim(),
      estimated_driving_hours_for_load: Number(byId("check-estimated-hours").value),
      driver_hours_driven_since_qualifying_rest: Number(byId("check-rest-hours").value),
      driver_hours_since_last_30m_break: Number(byId("check-break-hours").value),
      break_scheduled_before_8_hour_limit: byId("check-break-scheduled").checked,
    },
  };

  resultBox.replaceChildren();
  const output = document.createElement("pre");
  output.textContent = "Running matchmaking and compliance checks…";
  resultBox.append(output);
  setBusy(form, true, "Checking…");
  try {
    const response = await fetch("/workflow/check-load", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await responseJson(response);
    const matchStatus = result.matchmaking_result?.status || "not run";
    const complianceStatus = result.compliance_result?.status || "not run";
    output.textContent = `Matchmaking: ${matchStatus}\nCompliance: ${complianceStatus}\n\n${JSON.stringify(result, null, 2)}`;
  } catch (error) {
    output.textContent = `Load check failed: ${error.message}`;
  } finally {
    setBusy(form, false);
  }
});

byId("pdf-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const file = byId("pdf-file").files?.[0];
  const notice = byId("pdf-notice");
  const resultBox = byId("pdf-result");
  if (!file) return;
  if (!file.name.toLowerCase().endsWith(".pdf")) {
    notice.textContent = "Choose a file with a .pdf extension.";
    notice.classList.add("error");
    notice.hidden = false;
    return;
  }
  if (file.size > 8 * 1024 * 1024) {
    notice.textContent = "PDF uploads must be 8 MB or smaller.";
    notice.classList.add("error");
    notice.hidden = false;
    return;
  }

  notice.hidden = true;
  notice.classList.remove("error");
  resultBox.replaceChildren();
  const output = document.createElement("pre");
  output.textContent = `Extracting ${file.name}…`;
  resultBox.append(output);
  setBusy(form, true, "Extracting…");

  try {
    const response = await fetch("/extract/load-fields", {
      method: "POST",
      headers: { "Content-Type": "application/pdf" },
      body: file,
    });
    const extracted = await responseJson(response);
    output.textContent = JSON.stringify(extracted, null, 2);
    notice.textContent = `Extraction complete for ${file.name}. Review null and ambiguous fields before using this data.`;
    notice.hidden = false;
  } catch (error) {
    output.textContent = `Extraction failed: ${error.message}`;
    const detail = error.message.toLowerCase();
    if (detail.includes("no selectable text")) {
      notice.textContent = "This PDF has no selectable text. Scanned-image OCR is not supported.";
    } else if (detail.includes("quota") || detail.includes("api key") || detail.includes("api_key")) {
      notice.textContent = "Gemini reported a configuration or quota issue. See the detailed response below.";
    } else {
      notice.textContent = "The extraction request failed. Read the detailed error below before changing the PDF or API settings.";
    }
    notice.classList.add("error");
    notice.hidden = false;
  } finally {
    setBusy(form, false);
  }
});

function formatDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function createApprovalCard(proposal) {
  const card = document.createElement("article");
  card.className = "approval-card";
  const title = document.createElement("div");
  title.className = "approval-title";
  const loadId = document.createElement("strong");
  loadId.textContent = proposal.load_id;
  const status = document.createElement("span");
  status.className = "approval-status";
  status.textContent = proposal.status.replaceAll("_", " ");
  title.append(loadId, status);

  const meta = document.createElement("div");
  meta.className = "approval-meta";
  const fields = [
    ["Carrier", proposal.carrier_id],
    ["Rate", `$${Number(proposal.rate_usd).toLocaleString(undefined, { minimumFractionDigits: 2 })}`],
    ["Pickup", formatDate(proposal.pickup_at)],
    ["Delivery", formatDate(proposal.delivery_at)],
  ];
  for (const [label, value] of fields) {
    const item = document.createElement("div");
    item.textContent = label;
    const strong = document.createElement("b");
    strong.textContent = value;
    item.append(strong);
    meta.append(item);
  }

  const actions = document.createElement("div");
  actions.className = "approval-actions";
  const reject = document.createElement("button");
  reject.className = "button button-small button-danger";
  reject.type = "button";
  reject.textContent = "Reject";
  reject.addEventListener("click", () => decideProposal(proposal, "reject"));
  const approve = document.createElement("button");
  approve.className = "button button-small button-primary";
  approve.type = "button";
  approve.textContent = "Review & approve";
  approve.addEventListener("click", () => decideProposal(proposal, "approve"));
  actions.append(reject, approve);
  card.append(title, meta, actions);
  return card;
}

async function refreshApprovals() {
  const list = byId("approval-list");
  try {
    const response = await fetch("/approvals/proposals", { cache: "no-store" });
    const proposals = await responseJson(response);
    byId("pending-count").textContent = String(proposals.length);
    list.replaceChildren();
    if (proposals.length === 0) {
      const empty = document.createElement("p");
      empty.className = "empty-state";
      empty.textContent = "No proposals are waiting for review.";
      list.append(empty);
      return;
    }
    for (const proposal of proposals) list.append(createApprovalCard(proposal));
  } catch (error) {
    list.replaceChildren();
    const message = document.createElement("p");
    message.className = "empty-state";
    message.textContent = `Could not load approvals: ${error.message}`;
    list.append(message);
  }
}

async function refreshEvents() {
  const list = byId("event-list");
  try {
    const response = await fetch("/events/recent", { cache: "no-store" });
    const events = await responseJson(response);
    list.replaceChildren();
    if (events.length === 0) {
      const empty = document.createElement("p");
      empty.className = "empty-state";
      empty.textContent = "No booking events yet. Approving a proposal creates one.";
      list.append(empty);
      return;
    }

    for (const item of events) {
      const card = document.createElement("article");
      card.className = "event-card";
      const top = document.createElement("div");
      top.className = "event-card-top";
      const load = document.createElement("strong");
      load.textContent = item.load_id || item.event_type;
      const stage = document.createElement("span");
      stage.className = "event-stage";
      if (item.last_error) {
        stage.textContent = "Publish failed";
        stage.classList.add("failed");
      } else if (item.processed_at) {
        stage.textContent = "Consumer processed";
        stage.classList.add("done");
      } else if (item.published_at) {
        stage.textContent = "Published · awaiting consumer";
      } else {
        stage.textContent = "Waiting for publisher";
      }
      top.append(load, stage);

      const meta = document.createElement("div");
      meta.className = "event-card-meta";
      const details = [
        `${item.topic} · attempts ${item.attempts}`,
        `Event ${item.event_id}`,
        `Created ${formatDate(item.created_at)}`,
      ];
      if (item.booking_id) details.push(`Booking ${item.booking_id}`);
      if (item.last_error) details.push(`Error: ${item.last_error}`);
      meta.textContent = details.join("\n");
      card.append(top, meta);
      list.append(card);
    }
  } catch (error) {
    list.replaceChildren();
    const message = document.createElement("p");
    message.className = "empty-state";
    message.textContent = `Could not load booking events: ${error.message}`;
    list.append(message);
  }
}

async function decideProposal(proposal, decision) {
  const isApprove = decision === "approve";
  const prompt = isApprove
    ? `Approve ${proposal.load_id} for ${proposal.carrier_id} at $${proposal.rate_usd}? This creates a mock booking and Kafka event.`
    : `Reject proposal ${proposal.load_id}? No booking will be created.`;
  if (!window.confirm(prompt)) return;
  try {
    const response = await fetch(`/approvals/proposals/${proposal.approval_id}/${decision}`, { method: "POST" });
    const result = await responseJson(response);
    showNotice(`${result.detail}${result.booking_id ? ` Booking ID: ${result.booking_id}` : ""}`);
    await Promise.all([refreshApprovals(), refreshHealth(), refreshEvents()]);
  } catch (error) {
    showNotice(error.message, true);
  }
}

function toLocalDateTimeValue(date) {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function setProposalDefaults() {
  const now = new Date();
  byId("proposal-load-id").value = `LOAD-DEMO-${now.toISOString().slice(0, 10).replaceAll("-", "")}-01`;
  byId("proposal-pickup").value = toLocalDateTimeValue(new Date(now.getTime() + 48 * 60 * 60 * 1000));
  byId("proposal-delivery").value = toLocalDateTimeValue(new Date(now.getTime() + 56 * 60 * 60 * 1000));
}

function setLoadCheckDefaults() {
  const now = new Date();
  byId("check-load-id").value = `LOAD-CHECK-${now.toISOString().slice(0, 10).replaceAll("-", "")}-01`;
  byId("check-pickup").value = toLocalDateTimeValue(new Date(now.getTime() + 48 * 60 * 60 * 1000));
  byId("check-delivery").value = toLocalDateTimeValue(new Date(now.getTime() + 56 * 60 * 60 * 1000));
}

byId("proposal-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  setBusy(form, true, "Saving…");
  byId("proposal-notice").hidden = true;
  const payload = {
    load_id: byId("proposal-load-id").value.trim(),
    carrier_id: byId("proposal-carrier-id").value.trim(),
    rate_usd: Number(byId("proposal-rate").value),
    pickup_at: new Date(byId("proposal-pickup").value).toISOString(),
    delivery_at: new Date(byId("proposal-delivery").value).toISOString(),
  };
  try {
    const response = await fetch("/approvals/proposals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const proposal = await responseJson(response);
    showNotice(`Proposal ${proposal.approval_id} is pending. Review it in the Approval inbox.`);
    await refreshApprovals();
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    setBusy(form, false);
  }
});

byId("refresh-all").addEventListener("click", () => {
  void Promise.all([refreshHealth(), refreshApprovals(), refreshEvents()]);
});
byId("refresh-approvals").addEventListener("click", () => void refreshApprovals());
byId("refresh-events").addEventListener("click", () => void refreshEvents());

setProposalDefaults();
setLoadCheckDefaults();
void Promise.all([refreshHealth(), refreshApprovals(), refreshEvents()]);
window.setInterval(() => void refreshEvents(), 5000);
