const tokenInput = document.querySelector("#control-token");
const connectButton = document.querySelector("#connect-control");
const statusLine = document.querySelector("#control-status");
const list = document.querySelector("#control-list");
let currentView = "pending";

tokenInput.value = sessionStorage.getItem("lyra-control-token") || "";

function headers() {
  return {
    "Content-Type": "application/json",
    "X-Lyra-Control-Token": tokenInput.value,
  };
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { ...headers(), ...(options.headers || {}) },
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status})`);
  return payload;
}

function text(tag, value, className) {
  const element = document.createElement(tag);
  element.textContent = value;
  if (className) element.className = className;
  return element;
}

function action(label, handler) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.addEventListener("click", handler);
  return button;
}

function proposalCard(item) {
  const card = document.createElement("article");
  card.className = "proposal-card";
  if (item.approval_mode) {
    card.append(text("p", `${item.trust_lane} / ${item.approval_mode}`, "proposal-meta"));
  }
  card.append(text("p", `${item.destination_plane} · ${item.ledger} · ${item.status}`, "proposal-meta"));
  card.append(text("p", item.content, "proposal-content"));
  card.append(text("p", `Why: ${item.proposal_reason}`, "proposal-meta"));
  const source = `${item.provenance.source_type}${item.provenance.channel ? ` · ${item.provenance.channel}` : ""}`;
  card.append(text("p", `Source: ${source}`, "proposal-meta"));
  if (item.sensitivity_flags.length) {
    card.append(text("p", `Flags: ${item.sensitivity_flags.join(", ")}`, "proposal-meta"));
  }
  const actions = document.createElement("div");
  actions.className = "control-actions";
  if (item.status === "pending") {
    actions.append(action("Approve", () => mutate(item.proposal_id, "approve", {})));
    actions.append(action("Correct", async () => {
      const content = prompt("Corrected memory text", item.content);
      if (content !== null) await mutate(item.proposal_id, "correct", { content });
    }));
    actions.append(action("Reject", async () => {
      const reason = prompt("Reason for rejection");
      if (reason) await mutate(item.proposal_id, "reject", { reason });
    }));
  } else {
    if (item.destination_plane === "semantic_memory") {
      actions.append(action("Correct", async () => {
        const content = prompt("Corrected memory text", item.content);
        if (content !== null) await mutate(item.proposal_id, "correct-approved", { content });
      }));
    }
    actions.append(action("Forget", async () => {
      if (confirm("Permanently remove this item from retrieval?")) {
        await mutate(item.proposal_id, "forget", { confirmed: true });
      }
    }));
  }
  card.append(actions);
  return card;
}

function auditCard(item) {
  const card = document.createElement("article");
  card.className = "audit-card";
  card.append(text("p", `${item.action} · proposal ${item.proposal_id} · ${item.destination_plane}`, "proposal-content"));
  card.append(text("p", `${item.created_at} · ${item.content_sha256}`, "proposal-meta"));
  if (item.reason) card.append(text("p", `Reason: ${item.reason}`, "proposal-meta"));
  return card;
}

async function refresh() {
  list.replaceChildren();
  try {
    const payload = currentView === "audit"
      ? await api("/api/control/audit")
      : currentView === "recent"
        ? await api("/api/control/recent")
        : await api(`/api/control/proposals?status=${currentView}`);
    const items = currentView === "audit" ? payload.audit : payload.proposals;
    items.forEach((item) => {
      list.append(currentView === "audit" ? auditCard(item) : proposalCard(item));
    });
    if (!items.length) list.append(text("p", "Nothing here.", "proposal-meta"));
    statusLine.textContent = "Control center unlocked for this tab.";
    statusLine.className = "proposal-meta";
  } catch (error) {
    statusLine.textContent = error.message;
    statusLine.className = "control-error";
  }
}

async function mutate(id, operation, body) {
  try {
    await api(`/api/control/proposals/${id}/${operation}`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    await refresh();
  } catch (error) {
    statusLine.textContent = error.message;
    statusLine.className = "control-error";
  }
}

connectButton.addEventListener("click", () => {
  sessionStorage.setItem("lyra-control-token", tokenInput.value);
  refresh();
});

document.querySelectorAll("[data-view]").forEach((button) => {
  button.addEventListener("click", () => {
    currentView = button.dataset.view;
    refresh();
  });
});
