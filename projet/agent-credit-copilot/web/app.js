/* Credit Copilot — frontend (vanilla JS, style Apple). Parle à l'API FastAPI. */
const $ = (s) => document.querySelector(s);
const api = (p, opt) => fetch(p, opt).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); });

const state = {
  tab: "a_traiter", data: null, currentId: null, currentDecision: null,
  convos: {}, chatView: "convo", convSeq: 0, busy: false, email: null,
};

const RISK_LABEL = { low: "Risque faible", medium: "Risque modéré", high: "Risque élevé" };
const RISK_COLOR = { low: "var(--green)", medium: "var(--orange)", high: "var(--red)" };
const ACT = [
  ["accord", "Accorder", "btn-accord"], ["analyse_manuelle", "Analyse manuelle", "btn-analyse"],
  ["refus", "Refuser", "btn-refus"], ["escalade", "Escalader", "btn-escalade"],
];
const EMAIL_TITLE = {
  accord: "✉️ Email d'acceptation", refus: "✉️ Email de refus",
  analyse_manuelle: "✉️ Demande d'informations au client", escalade: "✉️ Escalade au responsable",
  contre_offre: "✉️ Proposition de contre-offre au client",
};

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmtEUR = (n) => Math.round(n).toLocaleString("fr-FR") + " €";
const mdBold = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/\n/g, "<br>");

async function load() { state.data = await api("/api/dossiers"); renderList(); }

function movePill() {
  const seg = $("#segmented"), active = seg.querySelector("button.active"), pill = seg.querySelector(".pill");
  pill.style.width = active.offsetWidth + "px";
  pill.style.transform = `translateX(${active.offsetLeft - 3}px)`;
}

// ============================================================== vue liste
function renderList() {
  state.currentId = null; state.currentDecision = null;
  $("#list-view").hidden = false;
  $("#detail-view").hidden = true;
  $("#chat-fab").hidden = false;
  movePill();
  syncChat();

  const grid = $("#grid"), empty = $("#empty");
  grid.innerHTML = "";
  const EMPTY_MSG = {
    a_traiter: "Aucun dossier à traiter 🎉", en_cours: "Aucun dossier en cours de suivi.",
    traites: "Aucun dossier traité pour l'instant.",
  };
  const items = state.data[state.tab] || [];
  if (!items.length) {
    empty.hidden = false;
    empty.textContent = EMPTY_MSG[state.tab] || "Aucun dossier.";
    return;
  }
  empty.hidden = true;
  const EMO = { accord: "✅", refus: "❌", analyse_manuelle: "🔎", escalade: "⬆️", contre_offre: "✉️" };
  for (const it of items) {
    const card = document.createElement("div");
    card.className = "card";
    if (state.tab === "a_traiter") {
      card.innerHTML = `
        <div class="top"><span class="id">${esc(it.demande_id)}</span><span class="dot risk-${it.risk}"></span></div>
        <div class="name">${esc(it.prenom)} ${esc(it.nom)}</div>
        <div class="meta">${esc(it.type_credit)} · ${fmtEUR(it.montant_demande)}</div>
        <div class="foot"><span class="chip chip-${it.risk}">${RISK_LABEL[it.risk]} · ${Math.round(it.proba * 100)} %</span></div>`;
    } else {
      const emo = EMO[it.decision] || "•";
      card.innerHTML = `
        <div class="top"><span class="id">${esc(it.demande_id)}</span></div>
        <div class="name">${esc(it.prenom)} ${esc(it.nom)}</div>
        <div class="meta">${esc(it.type_credit || "—")} · ${it.montant_demande ? fmtEUR(it.montant_demande) : ""}</div>
        <div class="foot"><span class="status"><span class="em">${emo}</span>${esc(it.decision_label)}</span></div>`;
    }
    card.onclick = () => openDossier(it.demande_id);
    grid.appendChild(card);
  }
}

// ============================================================== vue détail
async function openDossier(id) {
  state.currentId = id;
  const d = await api(`/api/dossier/${id}`);
  state.currentClientId = d.client.client_id;
  state.currentDecision = d.decision ? d.decision.decision : null;
  renderDetail(d);
  $("#list-view").hidden = true;
  $("#detail-view").hidden = false;
  $("#chat-fab").hidden = false;
  syncChat();
  window.scrollTo(0, 0);
}

function renderDetail(d) {
  const s = d.score, pct = Math.round(s.probability_default * 100), cl = d.client, dm = d.demande;
  const profil = [
    ["Âge", `${cl.age} ans`], ["Catégorie", cl.categorie_socio_pro],
    ["Revenu net mensuel", fmtEUR(cl.revenu_mensuel_net)], ["Contrat", cl.type_contrat],
    ["Ancienneté emploi", `${cl.anciennete_emploi_mois} mois`], ["Situation familiale", cl.situation_familiale],
    ["Crédit demandé", `${dm.type_credit} — ${fmtEUR(dm.montant_demande)} sur ${dm.duree_mois} mois`],
  ];
  const topFactor = d.factors[0], sens = topFactor.effet === "augmente" ? "pénalisé" : "favorisé";
  const factorsRows = d.factors.map((f) => `
    <tr><td>${esc(f.facteur)}</td><td>${esc(f.valeur)}</td>
    <td class="${f.effet === "augmente" ? "eff-up" : "eff-down"}">${f.effet === "augmente" ? "⬆︎ Augmente" : "⬇︎ Diminue"}</td></tr>`).join("");
  const mini = (rows, cols) => rows.length
    ? `<table class="mini"><thead><tr>${cols.map((c) => `<th>${c}</th>`).join("")}</tr></thead>
       <tbody>${rows.map((r) => `<tr>${r.map((v) => `<td>${esc(v)}</td>`).join("")}</tr>`).join("")}</tbody></table>`
    : `<p class="caption">Aucun élément.</p>`;

  const decisionBlock = d.decision
    ? `<div class="done">Dernière action : ${esc(d.decision.label)} — ${esc(d.decision.date_decision.slice(0, 10))}
        ${d.decision.commentaire ? `<div class="caption">📝 ${esc(d.decision.commentaire)}</div>` : ""}
        ${d.decision.decision === "refus" ? `<div class="caption">💬 Ouvrez l'assistant pour rouvrir ce dossier.</div>` : ""}</div>`
    : `<p class="caption" style="margin-bottom:10px">Un email sera rédigé par l'assistant pour validation avant envoi.</p>
       <div class="actions">${ACT.map(([c, l, k]) => `<button class="btn ${k}" data-dec="${c}">${l}</button>`).join("")}</div>`;

  $("#detail").innerHTML = `
    <div class="detail-head">
      <h2>${esc(cl.prenom)} ${esc(cl.nom)}</h2>
      <span class="sub">${esc(dm.demande_id)} · ${esc(dm.type_credit)} · ${fmtEUR(dm.montant_demande)}</span>
    </div>
    <div class="panel">
      <h3>Score de risque</h3>
      <div class="score-row">
        <div class="ring" style="--p:${pct}; --c:${RISK_COLOR[s.risk]}">
          <div class="val"><b>${pct}%</b><span>probabilité<br>de défaut</span></div>
        </div>
        <div class="score-meta">
          <span class="band">${esc(s.decision_band)}</span>
          <span class="reco">Recommandation du modèle : <b>${esc(s.recommandation)}</b></span>
        </div>
      </div>
      ${s.no_auto_processing ? `<div class="banner">⛔ Risque critique — pas de traitement automatique. Escalade obligatoire.</div>` : ""}
    </div>
    <div class="cols">
      <div class="panel">
        <h3>Profil client</h3>
        <table class="kv">${profil.map(([k, v]) => `<tr><td>${k}</td><td>${esc(v)}</td></tr>`).join("")}</table>
      </div>
      <div class="panel">
        <h3>Pourquoi ce score ?</h3>
        <div class="hint">En clair : ce dossier est surtout <strong>${sens}</strong> par « ${esc(topFactor.facteur.toLowerCase())} ».</div>
        <table class="kv factors"><tr><td>Facteur</td><td>Situation du client</td><td>Effet</td></tr>${factorsRows}</table>
        <p class="caption">Facteurs classés du plus au moins influent sur la décision.</p>
      </div>
    </div>
    <details class="disc">
      <summary>📚 Historique du client</summary>
      <div class="disc-body">
        <h4>Crédits</h4>${mini(d.history.credits.map((c) => [c.type_credit, fmtEUR(c.montant), c.statut, fmtEUR(c.mensualite)]), ["Type", "Montant", "Statut", "Mensualité"])}
        <h4>Incidents</h4>${mini(d.history.incidents.map((i) => [i.date_incident, i.type, i.nb_jours_retard + " j", i.regularise ? "régularisé" : "non régularisé"]), ["Date", "Type", "Retard", "État"])}
        <h4>Garanties</h4>${mini(d.history.garanties.map((g) => [g.type, fmtEUR(g.valeur_estimee), g.statut]), ["Type", "Valeur", "Statut"])}
      </div>
    </details>
    <div class="panel"><h3>Décision du conseiller</h3>${decisionBlock}</div>`;

  if (!d.decision) {
    $("#detail").querySelectorAll("[data-dec]").forEach((b) => {
      b.onclick = () => openEmail(b.dataset.dec, cl.client_id, dm.demande_id);
    });
  }
}

// ============================================================== composer email
async function openEmail(kind, client_id, demande_id, offer = null) {
  state.email = { kind, client_id, demande_id, offer };
  $("#email-title").textContent = EMAIL_TITLE[kind] || "Email";
  $("#email-to").value = ""; $("#email-subject").value = "";
  $("#email-body").value = "L'assistant rédige l'email…";
  $("#email-status").textContent = ""; $("#email-status").className = "email-status";
  $("#email-send").disabled = true;
  $("#email-modal").hidden = false;
  try {
    const d = await api("/api/draft-email", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ demande_id, kind, offer }),
    });
    $("#email-to").value = d.to; $("#email-subject").value = d.subject; $("#email-body").value = d.body;
    $("#email-send").disabled = false;
  } catch (e) {
    $("#email-body").value = ""; $("#email-status").textContent = "Erreur lors de la rédaction."; $("#email-status").className = "email-status err";
  }
}

async function sendEmail() {
  const { kind, client_id, demande_id, offer } = state.email;
  $("#email-send").disabled = true;
  $("#email-status").textContent = "Envoi en cours…"; $("#email-status").className = "email-status";
  try {
    const res = await api("/api/send-email", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        demande_id, client_id, kind, to: $("#email-to").value,
        subject: $("#email-subject").value, body: $("#email-body").value, offer,
      }),
    });
    const m = res.email;
    $("#email-status").textContent = (m.simulated ? "🟡 " : "✅ ") + m.detail;
    $("#email-status").className = "email-status " + (m.sent ? "ok" : "");
    state.data = await api("/api/dossiers");
    setTimeout(() => { $("#email-modal").hidden = true; renderList(); }, 1600);
  } catch (e) {
    $("#email-status").textContent = "Échec de l'envoi."; $("#email-status").className = "email-status err";
    $("#email-send").disabled = false;
  }
}

// ============================================================== chatbot (multi-conversations)
const scopeKey = () => state.currentId || "__global__";
const store = () => (state.convos[scopeKey()] ||= { list: [], activeId: null });
const activeConv = () => store().list.find((c) => c.id === store().activeId);

function newConv() {
  const s = store();
  const cur = s.list.find((c) => c.id === s.activeId);
  if (cur && !cur.msgs.length) { state.chatView = "convo"; return cur; }  // réutilise une conv vide
  const c = { id: "conv" + (++state.convSeq), title: "Nouvelle conversation", msgs: [] };
  s.list.push(c); s.activeId = c.id; state.chatView = "convo"; return c;
}
function ensureActive() {
  const s = store();
  if (!s.activeId || !s.list.find((c) => c.id === s.activeId)) {
    if (s.list.length) s.activeId = s.list[s.list.length - 1].id; else newConv();
  }
}
function syncChat() {  // appelé quand on navigue : réaligne le chat sur le nouveau contexte
  if ($("#chat-panel").hidden) return;
  ensureActive(); state.chatView = "convo"; renderChat();
}
function updateChatContext() {
  $("#chat-context").textContent = state.currentId ? `Dossier ${state.currentId}` : "Assistant général";
}

function chipsFor() {
  if (!state.currentId) {
    return [
      { icon: "📂", label: "Ajouter un dossier (client existant)", text: "Je veux ajouter un nouveau dossier de crédit pour un client existant.", send: true },
      { icon: "📄", label: "Poser une question réglementaire", send: false },
    ];
  }
  const c = [
    { icon: "🔍", label: "Analyser ce dossier", text: "Analyse ce dossier : donne le score, l'explication et ta recommandation.", send: true },
    { icon: "💡", label: "Préparer une contre-offre", text: "Ce dossier est proche du refus. Prépare-moi une contre-offre acceptable pour ce client.", send: true },
    { icon: "📄", label: "Poser une question réglementaire", send: false },
  ];
  if (state.currentDecision === "refus") {
    c.unshift({ icon: "🔄", label: "Rouvrir ce dossier (refusé)", text: "Rouvre ce dossier maintenant, sans me demander de confirmation.", send: true });
  }
  return c;
}

function bubble(m, log) {
  const b = document.createElement("div");
  b.className = "bubble " + (m.role === "user" ? "user" : "bot");
  b.innerHTML = m.role === "user" ? esc(m.content) : mdBold(m.content);
  log.appendChild(b);
  if (m.sources && m.sources.length) {
    const wrap = document.createElement("div");
    wrap.className = "sources";
    for (const src of m.sources) {
      const t = document.createElement("div");
      t.className = "thumb";
      t.innerHTML = `<img src="/api/pdf/${encodeURIComponent(src.source)}/${src.page}" alt="">
                     <div class="cap">${esc(src.source.replace(".pdf", ""))} · p.${src.page}</div>`;
      t.onclick = () => openLightbox(`/api/pdf/${encodeURIComponent(src.source)}/${src.page}`);
      wrap.appendChild(t);
    }
    log.appendChild(wrap);
  }
}

function renderChips(log) {
  const box = document.createElement("div");
  box.className = "chips";
  box.innerHTML = `<div class="chips-title">${state.currentId ? "Posez une question sur ce dossier, ou :" : "Que puis-je faire pour vous ?"}</div>`;
  for (const c of chipsFor()) {
    const b = document.createElement("button");
    b.className = "chip-btn";
    b.innerHTML = `<span>${c.icon}</span> ${esc(c.label)}`;
    b.onclick = () => { if (c.send) sendMessage(c.text); else $("#chat-input").focus(); };
    box.appendChild(b);
  }
  log.appendChild(box);
}

function renderHistory(log) {
  $("#chat-title").textContent = "Conversations";
  const box = document.createElement("div");
  box.className = "conv-list";
  const nw = document.createElement("button");
  nw.className = "conv-new"; nw.textContent = "✎  Nouvelle conversation";
  nw.onclick = () => { newConv(); renderChat(); $("#chat-input").focus(); };
  box.appendChild(nw);
  const past = store().list.filter((c) => c.msgs.length).reverse();
  if (!past.length) {
    const e = document.createElement("div"); e.className = "conv-empty";
    e.textContent = "Aucune conversation précédente.";
    box.appendChild(e);
  } else {
    for (const c of past) {
      const last = c.msgs[c.msgs.length - 1];
      const it = document.createElement("button");
      it.className = "conv-item";
      const snippet = (last.content || "").replace(/\*\*/g, "").slice(0, 70);
      it.innerHTML = `<div class="t">${esc(c.title.replace(/\*\*/g, ""))}</div><div class="s">${esc(snippet)}</div>`;
      it.onclick = () => { store().activeId = c.id; state.chatView = "convo"; renderChat(); };
      box.appendChild(it);
    }
  }
  log.appendChild(box);
}

function renderChat() {
  updateChatContext();
  const log = $("#chat-log");
  log.innerHTML = "";
  if (state.chatView === "history") { renderHistory(log); return; }
  $("#chat-title").textContent = "Assistant réglementaire";
  const conv = activeConv();
  const msgs = conv ? conv.msgs : [];
  if (!msgs.length) { renderChips(log); return; }
  for (const m of msgs) bubble(m, log);
  log.scrollTop = log.scrollHeight;
}

async function sendMessage(text) {
  if (state.busy || !text.trim()) return;
  ensureActive(); state.chatView = "convo";
  const conv = activeConv();
  conv.msgs.push({ role: "user", content: text.trim() });
  if (conv.title === "Nouvelle conversation") conv.title = text.trim().slice(0, 42);
  renderChat();
  state.busy = true;
  const typing = document.createElement("div");
  typing.className = "typing"; typing.textContent = "L'assistant réfléchit…";
  $("#chat-log").appendChild(typing); $("#chat-log").scrollTop = $("#chat-log").scrollHeight;
  try {
    const history = conv.msgs.map((m) => ({ role: m.role, content: m.content }));
    const res = await api("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: history, demande_id: state.currentId }),
    });
    conv.msgs.push({ role: "assistant", content: res.reply, sources: res.sources || [] });
    state.busy = false; renderChat();
    if (res.action) await handleAction(res.action);
  } catch (e) {
    conv.msgs.push({ role: "assistant", content: "⚠️ Erreur : impossible de joindre l'assistant." });
    state.busy = false; renderChat();
  }
}

async function handleAction(a) {
  if (a.type === "counter_offer" && a.offer) { openOfferModal(a.offer); return; }
  state.data = await api("/api/dossiers");
  if (a.type === "open_dossier" && a.demande_id) await openDossier(a.demande_id);
  else if (a.type === "refresh" && $("#list-view").hidden === false) renderList();
}

// ============================================================== contre-offre
function openOfferModal(offer) {
  state.offer = offer;
  const p = offer.params || {}, av = offer.avant || {}, ap = offer.apres || {};
  const pctA = Math.round((av.probability_default || 0) * 100), pctB = Math.round((ap.probability_default || 0) * 100);
  $("#offer-body").innerHTML = `
    <table class="kv">
      <tr><td>Montant financé</td><td>${fmtEUR(p.montant_finance || 0)} <span class="muted">(apport ${fmtEUR(p.apport || 0)})</span></td></tr>
      <tr><td>Durée</td><td>${p.duree_mois} mois</td></tr>
      <tr><td>Mensualité estimée</td><td>~${fmtEUR(p.mensualite_estimee || 0)}</td></tr>
      <tr><td>Garantie</td><td>${fmtEUR(p.valeur_garantie || 0)}</td></tr>
      <tr><td>Risque de défaut</td><td>${pctA} % <span class="muted">(${esc(av.decision_band || "")})</span> → <strong>${pctB} % (${esc(ap.decision_band || "")})</strong></td></tr>
    </table>
    ${offer.justification ? `<p class="caption">${mdBold(offer.justification)}</p>` : ""}`;
  $("#offer-modal").hidden = false;
}

function openLightbox(src) { $("#lightbox-img").src = src; $("#lightbox").hidden = false; }

// ============================================================== init
function init() {
  $("#segmented").querySelectorAll("button").forEach((b) => {
    b.onclick = () => {
      $("#segmented").querySelectorAll("button").forEach((x) => x.classList.remove("active"));
      b.classList.add("active"); state.tab = b.dataset.tab; renderList();
    };
  });
  $("#back").onclick = () => renderList();
  $("#chat-fab").onclick = () => {
    $("#chat-panel").hidden = false; $("#chat-fab").hidden = true;
    ensureActive(); state.chatView = "convo"; renderChat(); $("#chat-input").focus();
  };
  $("#chat-close").onclick = () => { $("#chat-panel").hidden = true; $("#chat-fab").hidden = false; };
  $("#chat-back").onclick = () => { state.chatView = "history"; renderChat(); };
  $("#chat-new").onclick = () => { newConv(); renderChat(); $("#chat-input").focus(); };
  $("#chat-form").onsubmit = (e) => { e.preventDefault(); const v = $("#chat-input").value; $("#chat-input").value = ""; sendMessage(v); };
  $("#email-close").onclick = $("#email-cancel").onclick = () => { $("#email-modal").hidden = true; };
  $("#email-send").onclick = sendEmail;
  $("#offer-close").onclick = $("#offer-drop").onclick = () => { $("#offer-modal").hidden = true; };
  $("#offer-validate").onclick = () => {
    $("#offer-modal").hidden = true;
    openEmail("contre_offre", state.currentClientId, state.currentId, state.offer);
  };
  $("#lightbox").onclick = () => { $("#lightbox").hidden = true; };
  window.addEventListener("resize", () => { if (!$("#list-view").hidden) movePill(); });
  load().catch(() => { $("#empty").hidden = false; $("#empty").textContent = "Erreur de chargement de l'API."; });
}
document.addEventListener("DOMContentLoaded", init);
