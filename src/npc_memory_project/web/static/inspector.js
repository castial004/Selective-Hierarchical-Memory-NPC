/**
 * Live Neuro-Symbolic XAI Brain Inspector Dashboard
 */
let currentNPC = 'mira';
let currentTier = 'all';
let ablatedMemoryIds = new Set();

async function initInspector() {
  await fetchState();
  await refreshBrain(currentNPC);
  await fetchDialogueMode();
}

// Global functions exposed to window
window.selectNPCTab = function(npcId) {
  currentNPC = npcId;
  ablatedMemoryIds.clear();
  document.querySelectorAll('.npc-tab').forEach(tab => {
    tab.classList.toggle('active', tab.dataset.npc === npcId);
  });
  refreshBrain(npcId);
};

window.selectTierTab = function(tier) {
  currentTier = tier;
  document.querySelectorAll('.tier-tab').forEach(tab => {
    tab.classList.toggle('active', tab.dataset.tier === tier);
  });
  refreshBrain(currentNPC);
};

window.interactWithNPC = async function(npcId) {
  try {
    const res = await fetch('/api/interact', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ npc_id: npcId })
    });
    const data = await res.json();
    renderDialogue(data);
    await fetchState();
    await refreshBrain(npcId);
  } catch (err) {
    console.error('Failed to interact:', err);
  }
};

window.advanceGameDay = async function() {
  try {
    const res = await fetch('/api/day/advance', { method: 'POST' });
    const data = await res.json();
    document.getElementById('currentDayDisplay').textContent = `Day ${data.current_day}`;
    await fetchState();
    await refreshBrain(currentNPC);
  } catch (err) {
    console.error('Failed to advance day:', err);
  }
};

window.presentEvidence = async function(target) {
  try {
    const res = await fetch('/api/action/evidence', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target: target || 'kael' })
    });
    await fetchState();
    await refreshBrain(currentNPC);
    window.interactWithNPC(target || 'kael');
  } catch (err) {
    console.error('Failed to present evidence:', err);
  }
};

window.persuadeRohan = async function() {
  try {
    const res = await fetch('/api/action/persuade_rohan', { method: 'POST' });
    await fetchState();
    await refreshBrain('rohan');
    window.interactWithNPC('rohan');
  } catch (err) {
    console.error('Failed to persuade Rohan:', err);
  }
};

window.shareRumour = async function() {
  try {
    const res = await fetch('/api/rumour/share', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ speaker: 'arun', listener: 'mira' })
    });
    await fetchState();
    await refreshBrain('mira');
  } catch (err) {
    console.error('Failed to share rumour:', err);
  }
};

window.resetSimulation = async function() {
  try {
    const res = await fetch('/api/scenario/reset', { method: 'POST' });
    const data = await res.json();
    document.getElementById('currentDayDisplay').textContent = `Day 1`;
    ablatedMemoryIds.clear();
    await fetchState();
    await refreshBrain(currentNPC);
    document.getElementById('dialogueText').textContent = "Simulation reset to Day 1. Arun's accusation active.";
    document.getElementById('dialogueSpeakerName').textContent = "System";
  } catch (err) {
    console.error('Failed to reset:', err);
  }
};

async function fetchState() {
  try {
    const res = await fetch('/api/state');
    const state = await res.json();
    document.getElementById('currentDayDisplay').textContent = `Day ${state.game_day}`;

    // Update log
    const logEl = document.getElementById('eventLogStream');
    logEl.innerHTML = '';
    (state.event_log || []).slice().reverse().forEach(entry => {
      const div = document.createElement('div');
      div.className = 'log-entry';
      div.innerHTML = `<span class="log-day">[Day ${entry.day}]</span> ${escapeHtml(entry.text)}`;
      logEl.appendChild(div);
    });
  } catch (err) {
    console.error('Error fetching state:', err);
  }
}

async function refreshBrain(npcId) {
  try {
    const res = await fetch(`/api/npc/${npcId}/brain`);
    const brain = await res.json();

    // 1. Trust & Personality
    renderTrustAndPersonality(brain);

    // 2. Action Scoring Bars
    renderUtilityScores(brain);

    // 3. Memory Tier Heatmap
    renderMemoryHeatmap(brain.tiers);

    // 4. Hierarchical Memory Cards
    renderMemoryCards(brain.tiers);

    // 5. Counterfactual Ablation Studio
    renderCounterfactualStudio(brain);

  } catch (err) {
    console.error('Error fetching brain:', err);
  }
}

function renderTrustAndPersonality(brain) {
  const trustVal = brain.trust !== undefined ? brain.trust : 0;
  const trustTextEl = document.getElementById('trustScoreValue');
  const trustFillEl = document.getElementById('trustFillBar');

  trustTextEl.textContent = `${trustVal > 0 ? '+' : ''}${trustVal.toFixed(1)}`;
  if (trustVal < 0) {
    trustTextEl.style.color = '#ef4444';
    trustFillEl.style.backgroundColor = '#ef4444';
  } else {
    trustTextEl.style.color = '#10b981';
    trustFillEl.style.backgroundColor = '#10b981';
  }

  // Normalize [-100, 100] to [0%, 100%]
  const pct = Math.max(0, Math.min(100, ((trustVal + 100) / 200) * 100));
  trustFillEl.style.width = `${pct}%`;

  // Personality badges
  const persEl = document.getElementById('personalityBadges');
  persEl.innerHTML = '';
  for (const [trait, val] of Object.entries(brain.personality || {})) {
    const badge = document.createElement('span');
    badge.className = 'status-badge corroborated';
    badge.textContent = `${trait}: ${Math.round(val * 100)}%`;
    persEl.appendChild(badge);
  }
}

function renderUtilityScores(brain) {
  const container = document.getElementById('actionScoreBars');
  container.innerHTML = '';

  const scores = brain.action_scores || [];
  const maxScore = Math.max(...scores.map(s => s.score), 0.6);

  scores.forEach(s => {
    const isSelected = (s.action === brain.current_action);
    const pct = Math.max(5, (s.score / maxScore) * 100);

    const row = document.createElement('div');
    row.className = 'action-score-row';
    row.innerHTML = `
      <div class="action-meta">
        <span class="action-name">${isSelected ? '★ ' : ''}${s.action}</span>
        <span class="action-score-val">${s.score.toFixed(3)}</span>
      </div>
      <div class="score-bar-bg" title="${formatFactors(s.factors)}">
        <div class="score-bar-fill ${isSelected ? 'selected' : 'candidate'}" style="width: ${pct}%"></div>
      </div>
    `;
    container.appendChild(row);
  });
}

function formatFactors(factors) {
  if (!factors) return '';
  return Object.entries(factors)
    .map(([k, v]) => `${k}: ${v.toFixed(3)}`)
    .join(' | ');
}

function renderMemoryCards(tiers) {
  const container = document.getElementById('memoryCardsList');
  container.innerHTML = '';

  let list = [];
  if (currentTier === 'all') {
    for (const [t, items] of Object.entries(tiers || {})) {
      items.forEach(i => list.push({ ...i, tier: t }));
    }
  } else {
    (tiers[currentTier] || []).forEach(i => list.push({ ...i, tier: currentTier }));
  }

  // Sort by game_day descending
  list.sort((a, b) => b.game_day - a.game_day);

  if (list.length === 0) {
    container.innerHTML = '<div style="color: var(--text-muted); font-size: 0.8rem; padding: 10px;">No memories in this tier.</div>';
    return;
  }

  list.forEach(m => {
    const card = document.createElement('div');
    card.className = 'memory-card';

    const statusClass = (m.status || 'active').toLowerCase();
    card.innerHTML = `
      <div class="memory-header">
        <span style="color: var(--tier-${m.tier}); font-weight: 700; text-transform: uppercase; font-size: 0.7rem;">${m.tier}</span>
        <span class="status-badge ${statusClass}">${m.status}</span>
      </div>
      <div class="memory-text">${escapeHtml(m.summary)}</div>
      <div class="memory-footer">
        <span>Day ${m.game_day} | I=${m.importance.toFixed(2)} | C=${m.confidence.toFixed(2)}</span>
        <span>${escapeHtml(m.source || 'direct')}</span>
      </div>
    `;
    container.appendChild(card);
  });
}

function renderCounterfactualStudio(brain) {
  const container = document.getElementById('cfEvidenceList');
  container.innerHTML = '';

  const evidence = brain.causal_evidence || [];
  if (evidence.length === 0) {
    container.innerHTML = '<div style="color: var(--text-muted); font-size: 0.8rem;">No causal factors identified in this state.</div>';
    return;
  }

  evidence.forEach((ev, idx) => {
    const item = document.createElement('div');
    item.className = 'cf-evidence-item';

    const isAblated = ablatedMemoryIds.has(ev.factor);
    const badgeClass = ev.changed_action ? 'flip' : 'noflip';
    const badgeText = ev.changed_action ? `Action Flips to '${ev.action_without}' (ΔU=${ev.score_delta.toFixed(3)})` : `No Flip (ΔU=${ev.score_delta.toFixed(3)})`;

    item.innerHTML = `
      <div style="display: flex; align-items: center; gap: 8px; flex: 1;">
        <input type="checkbox" class="cf-toggle" ${isAblated ? '' : 'checked'} data-factor="${escapeHtml(ev.factor)}" title="Toggle memory to test causal impact">
        <span style="color: ${isAblated ? 'var(--text-muted)' : '#f1f5f9'}; text-decoration: ${isAblated ? 'line-through' : 'none'};">${escapeHtml(ev.factor)}</span>
      </div>
      <span class="cf-delta-badge ${badgeClass}">${badgeText}</span>
    `;

    const checkbox = item.querySelector('.cf-toggle');
    checkbox.addEventListener('change', async (e) => {
      const factor = e.target.dataset.factor;
      if (e.target.checked) {
        ablatedMemoryIds.delete(factor);
      } else {
        ablatedMemoryIds.add(factor);
      }
      await runSimulatedAblation();
    });

    container.appendChild(item);
  });
}

async function runSimulatedAblation() {
  try {
    // Find event_ids corresponding to ablated factor names
    const brainRes = await fetch(`/api/npc/${currentNPC}/brain`);
    const brain = await brainRes.json();
    const allMems = [];
    for (const items of Object.values(brain.tiers || {})) {
      items.forEach(i => allMems.push(i));
    }

    const disabledIds = [];
    allMems.forEach(m => {
      if (ablatedMemoryIds.has(m.summary)) {
        disabledIds.push(m.event_id);
      }
    });

    const simRes = await fetch('/api/counterfactual/simulate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        npc_id: currentNPC,
        disabled_event_ids: disabledIds
      })
    });
    const simData = await simRes.json();

    // Update action scores live
    renderUtilityScores({
      current_action: simData.selected_action,
      action_scores: simData.action_scores
    });

    // Show/hide the What-If result panel
    const cfPanel = document.getElementById('cfResultPanel');
    const cfAction = document.getElementById('cfResultAction');
    const cfNote   = document.getElementById('cfResultNote');
    const originalAction = brain.current_action;

    if (ablatedMemoryIds.size > 0 && simData.selected_action && simData.selected_action !== originalAction) {
      cfPanel.style.display = 'block';
      cfAction.textContent = simData.selected_action;
      cfNote.textContent = `Without ${ablatedMemoryIds.size} memory(s), the original "${originalAction}" decision flips — confirming their causal role.`;
    } else if (ablatedMemoryIds.size > 0) {
      cfPanel.style.display = 'block';
      cfAction.textContent = simData.selected_action || originalAction;
      cfNote.textContent = `Action unchanged with ${ablatedMemoryIds.size} memory(s) ablated — those memories are not individually decisive.`;
      cfAction.style.color = 'var(--accent-indigo)';
    } else {
      cfPanel.style.display = 'none';
    }

  } catch (err) {
    console.error('Failed to run ablation:', err);
  }
}

function renderDialogue(data) {
  const speakerEl = document.getElementById('dialogueSpeakerName');
  const roleEl = document.getElementById('dialogueSpeakerRole');
  const textEl = document.getElementById('dialogueText');
  const badgeEl = document.getElementById('dialogueBadge');

  speakerEl.textContent = data.npc_id ? data.npc_id.charAt(0).toUpperCase() + data.npc_id.slice(1) : 'NPC';
  roleEl.textContent = (data.role || 'NPC').toUpperCase();
  textEl.textContent = data.dialogue || `[Performs ${data.selected_action}].`;

  if (badgeEl) {
    // dialogue_source is reported by the backend: "deterministic" (template),
    // "llm_verified" (model text that passed the grounding check) or
    // "llm_rejected" (model text discarded, template restored).
    const source = data.dialogue_source || 'deterministic';
    const sourceLabel = {
      deterministic: 'offline template',
      llm_verified: 'LLM paraphrase, grounding verified',
      llm_rejected: 'LLM output rejected — template restored'
    }[source] || source;
    const sourceColor = source === 'llm_rejected' ? '#f6ad55' : '#a0aec0';
    const faithful = data.faithful !== false;

    const prefix = faithful
      ? (data.grounded_factor ? '<span style="color:#68d391;">✓ Certified Causal Reason:</span>' : '<span>✓ Grounded in persona & standing</span>')
      : '<span style="color:#fc8181;">⚠ Ungrounded response withheld</span>';
    const quoted = data.grounded_factor
      ? ` "${escapeHtml(data.grounded_factor)}"`
      : '';

    badgeEl.innerHTML = `${prefix}${quoted} ` +
      `<span style="color:${sourceColor}; margin-left:8px; font-size:11px;">` +
      `[${escapeHtml(sourceLabel)} · Persona: ${escapeHtml(data.persona || 'in-character')}]</span>`;
  }
}

function renderMemoryHeatmap(tiers) {
  const bar = document.getElementById('memoryHeatmapBar');
  const legend = document.getElementById('memoryHeatmapLegend');
  const totalLabel = document.getElementById('heatmapTotalLabel');
  if (!bar || !legend) return;

  const tierConfig = [
    { key: 'working',  label: '⚡ Working',  color: 'var(--tier-working)' },
    { key: 'episodic', label: '📖 Episodic', color: 'var(--tier-episodic)' },
    { key: 'semantic', label: '🧠 Semantic', color: 'var(--tier-semantic)' },
    { key: 'archive',  label: '🗄 Archive',  color: 'var(--tier-archive)' },
  ];

  const counts = {};
  let total = 0;
  tierConfig.forEach(t => {
    const n = (tiers && tiers[t.key]) ? tiers[t.key].length : 0;
    counts[t.key] = n;
    total += n;
  });

  totalLabel.textContent = `${total} memor${total === 1 ? 'y' : 'ies'}`;

  bar.innerHTML = '';
  legend.innerHTML = '';

  if (total === 0) {
    const empty = document.createElement('div');
    empty.className = 'heatmap-segment';
    empty.style.flex = '1';
    empty.style.background = 'rgba(255,255,255,0.05)';
    empty.dataset.label = 'No memories yet';
    bar.appendChild(empty);
  } else {
    tierConfig.forEach(t => {
      const n = counts[t.key];
      if (n === 0) return;
      const seg = document.createElement('div');
      seg.className = 'heatmap-segment';
      seg.style.flex = String(n);
      seg.style.background = t.color;
      seg.style.opacity = '0.85';
      seg.dataset.label = `${t.label}: ${n}`;
      bar.appendChild(seg);
    });
  }

  tierConfig.forEach(t => {
    const n = counts[t.key];
    const item = document.createElement('div');
    item.className = 'heatmap-legend-item';
    const dot = document.createElement('div');
    dot.className = 'heatmap-legend-dot';
    dot.style.background = t.color;
    dot.style.opacity = n > 0 ? '1' : '0.3';
    item.appendChild(dot);
    const txt = document.createElement('span');
    txt.textContent = `${t.label.replace(/^[^ ]+ /, '')}: ${n}`;
    txt.style.opacity = n > 0 ? '1' : '0.4';
    item.appendChild(txt);
    legend.appendChild(item);
  });
}

async function fetchDialogueMode() {
  try {
    const res = await fetch('/api/dialogue/config');
    const data = await res.json();
    const pill = document.getElementById('dialogueModePill');
    if (!pill) return;
    if (data.llm_configured) {
      pill.textContent = `✨ LLM: ${data.model}`;
      pill.classList.add('llm-active');
    } else {
      pill.textContent = '⚙ Offline Persona';
      pill.classList.remove('llm-active');
    }
  } catch (_) {}
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

window.addEventListener('DOMContentLoaded', () => {
  window.townGame = new TownGame('gameCanvas');
  initInspector();
});
