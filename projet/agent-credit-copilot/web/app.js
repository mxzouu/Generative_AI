/* Credit Copilot — frontend (vanilla JS, style Apple). Parle à l'API FastAPI. */
const $ = (s) => document.querySelector(s);
const api = (p, opt) => fetch(p, opt).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); });

const state = {
  tab: "a_traiter", data: null, currentId: null, currentDecision: null,
  convos: {}, chatView: "convo", convSeq: 0, busy: false, email: null,
  showCoT: localStorage.getItem("showCoT") !== "0",  // exposition du raisonnement de l'agent (défaut : on)
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

  // Un dossier « traité » (accord/refus) est clos ; « à traiter » et « en cours » restent actionnables.
  const isTraite = dm.statut === "traité";
  const lastActionHtml = d.decision
    ? `<div class="done">Dernière action : ${esc(d.decision.label)} — ${esc(d.decision.date_decision.slice(0, 10))}
        ${d.decision.commentaire ? `<div class="caption">📝 ${esc(d.decision.commentaire)}</div>` : ""}
        ${isTraite && d.decision.decision === "refus" ? `<div class="caption">💬 Ouvrez l'assistant pour rouvrir ce dossier.</div>` : ""}</div>`
    : "";
  const actionsHtml =
    `<p class="caption" style="margin:12px 0 10px">${d.decision ? "Vous pouvez faire évoluer ce dossier. " : ""}Un email sera rédigé par l'assistant pour validation avant envoi.</p>
     <div class="actions">${ACT.map(([c, l, k]) => `<button class="btn ${k}" data-dec="${c}">${l}</button>`).join("")}</div>`;
  const decisionBlock = isTraite ? lastActionHtml : lastActionHtml + actionsHtml;

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

  if (!isTraite) {
    $("#detail").querySelectorAll("[data-dec]").forEach((b) => {
      b.onclick = () => startDecision(b.dataset.dec, cl.client_id, dm.demande_id);
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
  // Activité de l'agent (chain of thought minimaliste) — visible seulement si l'exposition est activée.
  const act = $("#email-activity");
  if (state.showCoT) {
    act.hidden = false; act.className = "agent-activity working";
    act.innerHTML = `<span class="aa-dot"></span><span>L'agent rédige le courrier…</span>`;
  } else { act.hidden = true; }
  $("#email-modal").hidden = false;
  try {
    const d = await api("/api/draft-email", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ demande_id, kind, offer }),
    });
    $("#email-to").value = d.to; $("#email-subject").value = d.subject; $("#email-body").value = d.body;
    $("#email-send").disabled = false;
    if (state.showCoT && d.reasoning) {
      act.hidden = false; act.className = "agent-activity";
      act.innerHTML = `<span class="cot-ic">💭</span><span class="cot-tx">${mdBold(d.reasoning)}</span>`;
    } else { act.hidden = true; }
  } catch (e) {
    act.hidden = true;
    $("#email-body").value = ""; $("#email-status").textContent = "Erreur lors de la rédaction."; $("#email-status").className = "email-status err";
  }
}

// ====================================================== garde-fou : revue de décision (agentique)
async function startDecision(kind, client_id, demande_id, offer = null) {
  // L'agent étudie le dossier en autonomie AVANT que le conseiller ne finalise, et émet des warnings.
  state.pendingDecision = { kind, client_id, demande_id, offer };
  const proc = $("#review-proc"), verdict = $("#review-verdict"), cont = $("#review-continue"), intro = $("#review-intro");
  proc.innerHTML = ""; verdict.innerHTML = ""; verdict.className = "";
  cont.disabled = true; cont.textContent = "Continuer"; cont.className = "btn btn-accord";
  intro.hidden = false; intro.textContent = "L'agent étudie le dossier de façon autonome avant validation…";
  $("#review-modal").hidden = false;

  let procBox = null, curInput = null;
  if (state.showCoT) {
    procBox = document.createElement("div"); procBox.className = "agent-proc";
    procBox.innerHTML = `<div class="proc-label">⚙︎ Analyse autonome de l'agent</div>`;
    proc.appendChild(procBox);
  }
  const status = document.createElement("div");
  status.className = "typing"; status.textContent = "L'agent réfléchit…";
  proc.appendChild(status);

  try {
    const resp = await fetch("/api/review-decision", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ demande_id, decision: kind }),
    });
    if (!resp.ok || !resp.body) throw new Error("review indisponible");
    const reader = resp.body.getReader(), decd = new TextDecoder();
    let buf = "", verd = null;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decd.decode(value, { stream: true });
      let nl;
      while ((nl = buf.indexOf("\n\n")) >= 0) {
        const rawl = buf.slice(0, nl); buf = buf.slice(nl + 2);
        if (!rawl.startsWith("data:")) continue;
        const ev = JSON.parse(rawl.slice(5).trim());
        if (ev.type === "thought") {
          if (procBox) procBox.appendChild(cotEl(ev.text));
        } else if (ev.type === "tool_start") {
          curInput = ev.input;
          if (procBox) {
            const { el } = toolStepEl({ icon: ev.icon, label: ev.label, input: ev.input });
            el.classList.add("running"); procBox.appendChild(el);
          }
          status.textContent = state.showCoT ? `${ev.icon} ${ev.label}…` : "L'agent étudie le dossier…";
        } else if (ev.type === "tool_end") {
          if (procBox) {
            const run = procBox.querySelector(".tool-step.running");
            if (run) { run.classList.remove("running"); fillToolBody(run.querySelector(".ts-body"), { input: curInput, output: ev.output }); }
          }
        } else if (ev.type === "done") {
          verd = ev.verdict;
        }
      }
    }
    status.remove(); intro.hidden = true;
    renderVerdict(verd);
    cont.disabled = false;
  } catch (e) {
    status.remove(); intro.hidden = true;
    verdict.className = "verdict warn";
    verdict.innerHTML = `<div class="v-head">⚠️ Revue indisponible</div><div class="v-reco">L'analyse automatique a échoué — vous pouvez poursuivre manuellement.</div>`;
    cont.disabled = false;
  }
}

function renderVerdict(v) {
  const box = $("#review-verdict"), cont = $("#review-continue");
  const niveau = v ? (v.niveau || (v.coherent ? "ok" : "attention")) : "ok";
  const warns = v ? (v.avertissements || []).filter(Boolean) : [];
  const HEAD = {
    ok: ["ok", "✓ Décision cohérente selon l'agent"],
    attention: ["warn", "⚠️ Points de vigilance"],
    alerte: ["danger", "⛔ Décision à risque"],
  }[niveau] || ["warn", "⚠️ Points de vigilance"];
  box.className = "verdict " + HEAD[0];
  box.innerHTML = `<div class="v-head">${HEAD[1]}</div>`
    + (warns.length ? `<ul class="v-list">${warns.map((w) => `<li>${mdBold(w)}</li>`).join("")}</ul>` : "")
    + (v && v.recommandation ? `<div class="v-reco">💡 ${mdBold(v.recommandation)}</div>` : "");
  if (niveau === "ok") { cont.textContent = "Continuer"; cont.className = "btn btn-accord"; }
  else { cont.textContent = "Passer outre et continuer"; cont.className = "btn btn-refus"; }
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

// ---- rendu du « déroulé » de l'agent : chain of thought + détails des tools -------------
function fmtArgs(input) {
  if (!input || !Object.keys(input).length) return "";
  return Object.entries(input).map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : v}`).join(", ");
}
function prettyJSON(s) { try { return JSON.stringify(JSON.parse(s), null, 2); } catch { return s || ""; } }

function cotEl(text) {  // une étape de raisonnement (chain of thought)
  const el = document.createElement("div");
  el.className = "cot";
  el.innerHTML = `<span class="cot-ic">💭</span><span class="cot-tx">${mdBold(text)}</span>`;
  return el;
}
function fillToolBody(body, step) {  // remplit le détail (entrée + résultat) d'un tool
  const inp = step.input && Object.keys(step.input).length ? prettyJSON(JSON.stringify(step.input)) : "—";
  let out = prettyJSON(step.output || "");
  if (out.length > 1600) out = out.slice(0, 1600) + "\n… (tronqué)";
  body.innerHTML = `<div class="ts-k">Entrée</div><pre>${esc(inp)}</pre><div class="ts-k">Résultat</div><pre>${esc(out)}</pre>`;
}
function toolStepEl(step) {  // {icon,label,input,output?} -> <details> repliable
  const d = document.createElement("details");
  d.className = "tool-step";
  const args = fmtArgs(step.input);
  d.innerHTML = `<summary><span class="ts-chip"><span class="ts-ic">${step.icon}</span>${esc(step.label)}</span>` +
    (args ? `<code class="ts-args">${esc(args)}</code>` : "") + `</summary>`;
  const body = document.createElement("div");
  body.className = "ts-body";
  d.appendChild(body);
  if (step.output !== undefined && step.output !== null && step.output !== "") fillToolBody(body, step);
  return { el: d, body };
}
function renderProcess(steps) {  // bloc complet persistant, reconstruit depuis le message
  const wrap = document.createElement("div");
  wrap.className = "agent-proc";
  wrap.innerHTML = `<div class="proc-label">⚙︎ Déroulé de l'agent</div>`;
  for (const s of steps) wrap.appendChild(s.kind === "thought" ? cotEl(s.text) : toolStepEl(s).el);
  return wrap;
}

function bubble(m, log) {
  // Déroulé de l'agent (raisonnement + tools détaillés) rendu au-dessus de sa réponse — si activé.
  if (state.showCoT && m.role !== "user" && m.steps && m.steps.length) log.appendChild(renderProcess(m.steps));
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
  const log = $("#chat-log");

  // Déroulé EN TEMPS RÉEL : raisonnement (chain of thought) + tools détaillés au fil de l'eau.
  // Construit uniquement si l'exposition du raisonnement est activée (sinon simple indicateur).
  const showProc = state.showCoT;
  let proc = null;
  if (showProc) {
    proc = document.createElement("div");
    proc.className = "agent-proc"; proc.hidden = true;
    proc.innerHTML = `<div class="proc-label">⚙︎ Déroulé de l'agent</div>`;
    log.appendChild(proc);
  }
  const status = document.createElement("div");
  status.className = "typing"; status.textContent = "L'assistant réfléchit…";
  log.appendChild(status);
  log.scrollTop = log.scrollHeight;
  const finish = () => { status.remove(); if (proc) proc.remove(); };
  let curInput = null;  // entrée du tool en cours (pour remplir son détail à la fin)

  try {
    const resp = await fetch("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: conv.msgs.map((m) => ({ role: m.role, content: m.content })), demande_id: state.currentId }),
    });
    if (!resp.ok || !resp.body) throw new Error("stream indisponible");
    const reader = resp.body.getReader(), decoder = new TextDecoder();
    let buf = "", final = null;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let nl;
      while ((nl = buf.indexOf("\n\n")) >= 0) {
        const raw = buf.slice(0, nl); buf = buf.slice(nl + 2);
        if (!raw.startsWith("data:")) continue;
        const ev = JSON.parse(raw.slice(5).trim());
        if (ev.type === "thought") {
          if (proc) { proc.hidden = false; proc.appendChild(cotEl(ev.text)); log.scrollTop = log.scrollHeight; }
          status.textContent = "L'assistant réfléchit…";
        } else if (ev.type === "tool_start") {
          curInput = ev.input;
          if (proc) {
            proc.hidden = false;
            const { el } = toolStepEl({ icon: ev.icon, label: ev.label, input: ev.input });
            el.classList.add("running");
            proc.appendChild(el);
            log.scrollTop = log.scrollHeight;
          }
          status.textContent = showProc ? `${ev.icon} ${ev.label}…` : "L'assistant travaille…";
        } else if (ev.type === "tool_end") {
          if (proc) {
            const run = proc.querySelector(".tool-step.running");
            if (run) {
              run.classList.remove("running");
              fillToolBody(run.querySelector(".ts-body"), { input: curInput, output: ev.output });
            }
          }
          status.textContent = "L'assistant rédige sa réponse…";
        } else if (ev.type === "done") {
          final = ev;
        }
      }
    }
    finish();
    conv.msgs.push({ role: "assistant", content: (final && final.reply) || "",
                     sources: (final && final.sources) || [], steps: (final && final.steps) || [] });
    state.busy = false; renderChat();
    if (final && final.action) await handleAction(final.action);
  } catch (e) {
    finish();
    conv.msgs.push({ role: "assistant", content: "⚠️ Erreur : impossible de joindre l'assistant." });
    state.busy = false; renderChat();
  }
}

async function handleAction(a) {
  if (a.type === "counter_offer" && a.offer) { openOfferModal(a.offer); return; }
  if (a.type === "open_email" && a.kind) { startDecision(a.kind, a.client_id, a.demande_id); return; }
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

// ============================================================== exposition du raisonnement (on/off)
function applyCoT() {
  const t = $("#cot-toggle");
  t.classList.toggle("on", state.showCoT);
  t.setAttribute("aria-checked", state.showCoT ? "true" : "false");
}
function toggleCoT() {
  state.showCoT = !state.showCoT;
  localStorage.setItem("showCoT", state.showCoT ? "1" : "0");
  applyCoT();
  if (!$("#chat-panel").hidden) renderChat();  // reflète le changement sur les messages déjà affichés
}

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
  $("#review-close").onclick = $("#review-cancel").onclick = () => { $("#review-modal").hidden = true; };
  $("#review-continue").onclick = () => {
    $("#review-modal").hidden = true;
    const p = state.pendingDecision;
    if (p) openEmail(p.kind, p.client_id, p.demande_id, p.offer);
  };
  $("#email-send").onclick = sendEmail;
  $("#offer-close").onclick = $("#offer-drop").onclick = () => { $("#offer-modal").hidden = true; };
  $("#offer-validate").onclick = () => {
    $("#offer-modal").hidden = true;
    openEmail("contre_offre", state.currentClientId, state.currentId, state.offer);
  };
  $("#lightbox").onclick = () => { $("#lightbox").hidden = true; };
  const cot = $("#cot-toggle");
  cot.onclick = toggleCoT;
  cot.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleCoT(); } };
  applyCoT();
  window.addEventListener("resize", () => { if (!$("#list-view").hidden) movePill(); });
  load().catch(() => { $("#empty").hidden = false; $("#empty").textContent = "Erreur de chargement de l'API."; });
}
document.addEventListener("DOMContentLoaded", init);
