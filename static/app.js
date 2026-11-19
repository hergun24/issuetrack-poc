/* IssueTrack Lite — browser UI (vanilla JS, semantic/accessible).
   All user-provided strings are inserted via textContent only (SEC-021). */
"use strict";

const API = "/api";
let token = localStorage.getItem("it_token") || null;
let me = null;
let workspaces = [];
let currentWs = null; // {id,name}
let currentRole = null;
let members = [];

const $ = (id) => document.getElementById(id);
const views = ["view-dash", "view-projects", "view-issues", "view-activity", "view-auth", "view-pick"];
const tabs = {
  dash: "Dashboard", projects: "Projects", issues: "Issues", activity: "Activity",
};
let currentTab = "dash";

/* ---------------- API helpers ---------------- */

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = "Bearer " + token;
  const res = await fetch(API + path, { method: opts.method || "GET", headers, body: opts.body ? JSON.stringify(opts.body) : undefined });
  if (res.status === 204) return null;
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { /* html errors */ }
  if (!res.ok) {
    const err = new Error((data && data.error && data.error.message) || "Request failed");
    err.status = res.status;
    err.details = data && data.error && data.error.details;
    throw err;
  }
  return data;
}

function setStatus(el, message, ok = true) {
  el.textContent = message || "";
  el.className = "form-status " + (message ? (ok ? "ok" : "err") : "");
}

function el(tag, attrs = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid) node.appendChild(kid);
  return node;
}

/* ---------------- auth ---------------- */

function refreshTopbar() {
  const auth = $("auth-area");
  auth.replaceChildren();
  if (!me) return;
  auth.appendChild(el("span", { class: "me-label", text: "Signed in as " }));
  const who = el("strong", { text: me.display_name });
  auth.appendChild(who);
  auth.appendChild(el("button", { text: "Sign out", onclick: logout, "aria-label": "Sign out" }));
}

function renderWsNav() {
  const nav = $("ws-nav");
  nav.replaceChildren();
  if (!me) return;
  for (const ws of workspaces) {
    nav.appendChild(el("button", {
      text: `${ws.name} (${ws.role})`,
      "aria-current": ws.id === currentWs ? "true" : "false",
      title: "Switch to " + ws.name,
      onclick: () => {
        currentWs = ws;
        switchWorkspace();
      },
    }));
  }
}

async function fetchMe() {
  me = await api("/me");
  const wsResp = await api("/workspaces");
  workspaces = wsResp.items;
  if (workspaces.length === 0) {
    // empty state: prompt workspace creation
    showView("pick");
    $("ws-list").replaceChildren(el("li", { text: "No workspaces yet. Create one below." }));
    $("ws-list").appendChild(el("li", {}, el("button", {
      text: "Create workspace",
      onclick: promptCreateWorkspace,
    })));
    return;
  }
  if (!currentWs || !workspaces.find(w => w.id === currentWs)) {
    currentWs = workspaces[0];
  }
  switchWorkspace();
}

async function switchWorkspace() {
  currentRole = (workspaces.find(w => w.id === currentWs) || {}).role;
  members = (await api(`/workspaces/${currentWs}/members`)).items;
  renderWsNav();
  renderTabs();
  showView(currentTab);
}

async function promptCreateWorkspace() {
  const name = prompt("Workspace name (1-100 characters):");
  if (!name) return;
  try {
    const created = await api("/workspaces", { method: "POST", body: { name } });
    me && (await fetchMe());
  } catch (e) { alert("Could not create workspace: " + e.message); }
}

async function logout() {
  try { await api("/auth/logout", { method: "POST" }); } catch { /* already gone */ }
  token = null;
  me = null;
  localStorage.removeItem("it_token");
  refreshTopbar();
  showView("auth");
  $("view-pick").classList.add("hidden");
}

/* ---------------- view routing ---------------- */

function showView(name) {
  currentTab = name;
  views.forEach(v => $(v).classList.add("hidden"));
  $("view-" + name).classList.remove("hidden");
  const content = $("main").querySelector(`#view-${name}`);
  if (content) content.removeAttribute("inert");
  if (name !== "auth" && name !== "pick") {
    refreshTopbar();
  }
  renderTabs();
  if (name === "dash") loadDash();
  if (name === "projects") loadProjects();
  if (name === "issues") loadIssues();
  if (name === "activity") loadActivity();
}

function renderTabs() {
  const host = $("main-tabs");
  host.replaceChildren();
  if (!me) { host.classList.add("hidden"); return; }
  host.classList.remove("hidden");
  for (const [key, label] of Object.entries(tabs)) {
    host.appendChild(el("button", {
      text: label,
      "aria-current": key === currentTab ? "true" : "false",
      "data-tab": key,
      onclick: () => showView(key),
    }));
  }
}

/* ---------------- dashboard ---------------- */

async function loadDash() {
  $("dash-loading").classList.remove("hidden");
  $("dash-content").classList.add("hidden");
  $("dash-error").classList.add("hidden");
  try {
    const d = await api(`/workspaces/${currentWs}/dashboard`);
    $("dash-status").replaceChildren(
      ...Object.entries(d.status_totals).map(([k, v]) => el("li", {}, el("span", { text: k }), el("strong", { text: String(v) }))));
    $("dash-prio").replaceChildren(
      ...Object.entries(d.priority_totals).map(([k, v]) => el("li", {}, el("span", { text: k }), el("strong", { text: String(v) }))));
    const overdueHost = $("dash-overdue");
    overdueHost.replaceChildren();
    if (d.overdue_count === 0) {
      overdueHost.appendChild(el("p", { class: "empty", text: "No overdue issues." }));
    } else {
      const list = await api(`/workspaces/${currentWs}/issues?overdue=true&page=1&page_size=100`);
      for (const iss of list.items) overdueHost.appendChild(issueCard(iss, false));
    }
    $("dash-content").classList.remove("hidden");
  } catch (e) {
    $("dash-error").textContent = "Dashboard could not be loaded: " + e.message;
    $("dash-error").classList.remove("hidden");
  } finally {
    $("dash-loading").classList.add("hidden");
  }
}

/* ---------------- projects ---------------- */

async function loadProjects() {
  $("prj-loading").classList.remove("hidden");
  $("prj-content").classList.add("hidden");
  $("prj-error").classList.add("hidden");
  try {
    const resp = await api(`/workspaces/${currentWs}/projects`);
    renderProjects(resp.items);
    $("prj-content").classList.remove("hidden");
  } catch (e) {
    $("prj-error").textContent = e.message;
    $("prj-error").classList.remove("hidden");
  } finally {
    $("prj-loading").classList.add("hidden");
  }
}

function renderProjects(items) {
  const host = $("prj-list");
  host.replaceChildren();
  if (items.length === 0) host.appendChild(el("li", { class: "empty", text: "No projects yet." }));
  for (const p of items) {
    const btn = el("button", { text: p.archived ? `${p.name} (archived, read-only)` : p.name,
      "aria-label": `Open project ${p.name}${p.archived ? " (archived)" : ""}`, onclick: () => {
        selectedProject = p;
        $("new-issue-btn").disabled = p.archived;
        showView("issues");
      } });
    if (p.archived) btn.setAttribute("data-archived", "true");
    host.appendChild(el("li", {}, btn));
  }
}

let selectedProject = null;

$("prj-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const fd = new FormData(ev.target);
  const body = { name: fd.get("name").trim() };
  const desc = fd.get("description");
  if (desc && desc.trim()) body.description = desc.trim();
  try {
    const p = await api(`/workspaces/${currentWs}/projects`, { method: "POST", body });
    setStatus($("prj-status"), "Project created: " + p.name, true);
    ev.target.reset();
    await loadProjects();
  } catch (e) {
    setStatus($("prj-status"), e.message, false);
  }
});

/* ---------------- issues ---------------- */

let issueFilters = { status: "", priority: "", overdue: "", page: 1 };
const PAGE_SIZE = 10;

function issueCard(iss, withDelete) {
  const li = el("li", {});
  const badges = el("span", { class: "badges" });
  badges.appendChild(el("span", { class: "badge", text: iss.status }));
  badges.appendChild(el("span", { class: "badge", text: iss.priority }));
  badges.appendChild(el("span", { class: "badge type", text: iss.type }));
  li.appendChild(el("strong", { text: iss.title }));
  li.appendChild(badges);
  const meta = [iss.assignee_id ? "assigned" : "unassigned",
    iss.due_date ? "due " + iss.due_date : "no due date"].join(" · ");
  li.appendChild(el("small", { text: meta, class: "issue-meta" }));
  li.appendChild(el("button", {
    text: "Open",
    "aria-label": "Open issue " + iss.title,
    onclick: () => openIssueDetail(iss.id),
  }));
  return li;
}

async function loadIssues() {
  $("issues-loading").classList.remove("hidden");
  $("issues-content").classList.add("hidden");
  $("issues-error").classList.add("hidden");
  fillAssigneeSelects();
  try {
    const q = new URLSearchParams();
    if (issueFilters.status) q.set("status", issueFilters.status);
    if (issueFilters.priority) q.set("priority", issueFilters.priority);
    if (issueFilters.assignee) q.set("assignee_id", issueFilters.assignee);
    if (issueFilters.overdue) q.set("overdue", issueFilters.overdue);
    q.set("page", String(issueFilters.page));
    q.set("page_size", String(PAGE_SIZE));
    const resp = await api(`/workspaces/${currentWs}/issues?` + q.toString());
    const list = $("issue-list");
    list.replaceChildren();
    if (resp.items.length === 0) {
      $("issues-empty").classList.remove("hidden");
    } else {
      $("issues-empty").classList.add("hidden");
      for (const iss of resp.items) list.appendChild(issueCard(iss));
    }
    renderPager($("issue-pager"), resp, (p) => { issueFilters.page = p; loadIssues(); });
    $("issues-content").classList.remove("hidden");
  } catch (e) {
    $("issues-error").textContent = e.message;
    $("issues-error").classList.remove("hidden");
  } finally {
    $("issues-loading").classList.add("hidden");
  }
}

function renderPager(host, resp, onPage) {
  host.replaceChildren();
  const prev = el("button", { text: "Previous", "aria-label": "Previous page", onclick: () => onPage(resp.page - 1) });
  prev.disabled = resp.page <= 1;
  host.appendChild(prev);
  host.appendChild(el("span", { text: `Page ${resp.page} of ${resp.total_pages}`, "aria-live": "polite" }));
  const next = el("button", { text: "Next", "aria-label": "Next page", onclick: () => onPage(resp.page + 1) });
  next.disabled = resp.page >= resp.total_pages;
  host.appendChild(next);
}

function fillAssigneeSelects() {
  const sel = $("is-assignee");
  sel.replaceChildren(el("option", { value: "", text: "Unassigned" }));
  for (const m of members) sel.appendChild(el("option", { value: m.user_id, text: m.display_name + " (" + m.role + ")" }));
  const ds = $("detail-assignee");
  if (ds) {
    ds.replaceChildren(el("option", { value: "", text: "Unassigned" }));
    for (const m of members) ds.appendChild(el("option", { value: m.user_id, text: m.display_name }));
  }
}

$("issue-filters").addEventListener("submit", (ev) => {
  ev.preventDefault();
  issueFilters = {
    status: $("f-status").value,
    priority: $("f-priority").value,
    overdue: $("f-overdue").value,
    page: 1,
  };
  loadIssues();
});

$("new-issue-btn").addEventListener("click", () => {
  const f = $("issue-form");
  f.classList.toggle("hidden");
  if (!f.classList.contains("hidden")) $("is-title").focus();
});

$("issue-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const fd = new FormData(ev.target);
  const body = {
    project_id: selectedProject ? selectedProject.id : null,
    title: fd.get("title").trim(),
  };
  if (fd.get("description") && fd.get("description").trim()) body.description = fd.get("description").trim();
  body.type = fd.get("type");
  body.priority = fd.get("priority");
  if (fd.get("assignee_id")) body.assignee_id = fd.get("assignee_id");
  if (fd.get("due_date")) body.due_date = fd.get("due_date");
  if (!body.project_id) { setStatus($("is-status"), "Select a project first.", false); return; }
  try {
    const iss = await api(`/workspaces/${currentWs}/issues`, { method: "POST", body });
    setStatus($("is-status"), "Issue created: " + iss.title, true);
    ev.target.reset();
    await loadIssues();
  } catch (e) {
    setStatus($("is-status"), e.message, false);
  }
});

/* ---------------- issue detail ---------------- */

async function openIssueDetail(issueId) {
  const dialog = $("issue-detail");
  try {
    const iss = await api(`/workspaces/${currentWs}/issues/${issueId}`);
    $("detail-title").textContent = iss.title;
    $("detail-body").textContent = `${iss.type} · project issue ${iss.id.slice(0, 8)} · created ${iss.created_at}`;
    const dl = $("detail-fields");
    dl.replaceChildren(
      el("dt", { text: "Status" }), el("dd", { text: iss.status }),
      el("dt", { text: "Priority" }), el("dd", { text: iss.priority }),
      el("dt", { text: "Assignee" }), el("dd", { text: iss.assignee_id ? iss.assignee_id : "Unassigned" }),
      el("dt", { text: "Due date" }), el("dd", { text: iss.due_date ? iss.due_date : "None" }),
      el("dt", { text: "Description" }), el("dd", { text: iss.description || "—" }),
    );
    $("detail-status").value = iss.status;
    $("detail-assignee").value = iss.assignee_id || "";
    fillAssigneeSelects();
    $("detail-assignee").value = iss.assignee_id || "";
    const comments = await api(`/workspaces/${currentWs}/issues/${issueId}/comments?page=1&page_size=100`);
    const cl = $("detail-comments");
    cl.replaceChildren();
    if (comments.items.length === 0) cl.appendChild(el("li", { class: "empty", text: "No comments yet." }));
    for (const c of comments.items) {
      const author = (members.find(m => m.user_id === c.author_id) || {}).display_name || c.author_id;
      cl.appendChild(el("li", {}, el("strong", { text: author + " · " }), el("span", { text: c.created_at }), el("div", { text: c.body }))));
    }
    $("detail-delete").classList.toggle("hidden", !(currentRole === "ADMIN"));
    dialog.dataset.issueId = issueId;
    dialog.showModal();
  } catch (e) {
    $("detail-actions").textContent = "Could not load issue: " + e.message;
  }
}

$("detail-save").addEventListener("click", async () => {
  const id = $("issue-detail").dataset.issueId;
  if (!id) return;
  const body = {
    status: $("detail-status").value,
    assignee_id: $("detail-assignee").value || null,
  };
  try {
    await api(`/workspaces/${currentWs}/issues/${id}`, { method: "PATCH", body });
    $("issue-detail").close();
    setStatus($("detail-actions"), "Saved.");
    await Promise.all([loadIssues(), loadActivity()]);
  } catch (e) {
    setStatus($("detail-actions"), e.message, false);
  }
});

$("detail-delete").addEventListener("click", async () => {
  const id = $("issue-detail").dataset.issueId;
  if (!id || !confirm("Delete this issue? This cannot be undone.")) return;
  try {
    await api(`/workspaces/${currentWs}/issues/${id}`, { method: "DELETE" });
    $("issue-detail").close();
    await Promise.all([loadIssues()]);
  } catch (e) {
    setStatus($("detail-actions"), e.message, false);
  }
});

$("comment-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const id = $("issue-detail").dataset.issueId;
  const body = { body: $("comment-body").value.trim() };
  try {
    const c = await api(`/workspaces/${currentWs}/issues/${id}/comments`, { method: "POST", body });
    $("comment-body").value = "";
    setStatus($("comment-status"), "Comment posted.", true);
    openIssueDetail(id);
  } catch (e) {
    setStatus($("comment-status"), e.message, false);
  }
});

/* ---------------- activity ---------------- */

let actPage = 1;

async function loadActivity() {
  $("act-loading").classList.remove("hidden");
  $("act-content").classList.add("hidden");
  $("act-error").classList.add("hidden");
  try {
    const resp = await api(`/workspaces/${currentWs}/activity?page=${actPage}&page_size=20`);
    const list = $("activity-list");
    list.replaceChildren();
    if (resp.items.length === 0) list.appendChild(el("li", { class: "empty", text: "No activity yet." }));
    for (const ev2 of resp.items) {
      const who = (members.find(m => m.user_id === ev2.actor_id) || {}).display_name || ev2.actor_id;
      list.appendChild(el("li", {},
        el("strong", { text: ev2.action.replace(/_/g, " ").toLowerCase() }),
        el("span", { text: ` · by ${who} · ${ev2.created_at} · target ${ev2.target_type} ${ev2.target_id ? ev2.target_id.slice(0, 8) : "" }` })));
    }
    renderPager($("act-pager"), resp, (p) => { actPage = p; loadActivity(); });
    $("act-content").classList.remove("hidden");
  } catch (e) {
    $("act-error").textContent = e.message;
    $("act-error").classList.remove("hidden");
  } finally {
    $("act-loading").classList.add("hidden");
  }
}

/* ---------------- auth forms ---------------- */

$("login-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const fd = new FormData(ev.target);
  setStatus($("auth-status"), "", true);
  try {
    const resp = await api("/auth/login", { method: "POST", body: { email: fd.get("email").trim(), password: fd.get("password") } });
    token = resp.token;
    localStorage.setItem("it_token", token);
    me = resp.user;
    await fetchMe();
  } catch (e) {
    setStatus($("auth-status"), e.message, false);
  }
});

$("register-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const fd = new FormData(ev.target);
  setStatus($("reg-status"), "", true);
  try {
    await api("/auth/register", { method: "POST", body: {
      email: fd.get("email").trim(),
      password: fd.get("password"),
      display_name: fd.get("display_name").trim(),
    } });
    setStatus($("reg-status"), "Account created — you can sign in now.", true);
    ev.target.reset();
  } catch (e) {
    setStatus($("reg-status"), e.message, false);
  }
});

$("to-register").addEventListener("click", (e) => {
  e.preventDefault();
  $("login-form").classList.add("hidden");
  $("register-form").classList.remove("hidden");
  $("to-login").classList.remove("hidden");
  $("reg-email").focus();
});
$("to-login").addEventListener("click", (e) => {
  e.preventDefault();
  $("register-form").classList.add("hidden");
  $("login-form").classList.remove("hidden");
  $("to-login").classList.add("hidden");
  $("login-email").focus();
});

/* ---------------- boot ---------------- */

async function boot() {
  if (token) {
    try {
      me = await api("/me");
      await fetchMe();
      return;
    } catch {
      token = null;
      localStorage.removeItem("it_token");
    }
  }
  refreshTopbar();
  showView("auth");
}

boot();
