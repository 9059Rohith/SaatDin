const state = {
  authenticated: false,
  adminName: 'admin',
  overview: null,
  workers: [],
  claims: [],
  escalations: [],
  reports: [],
  selected: null,
  activeTab: 'overview',
};

const refs = {};

const currency = new Intl.NumberFormat('en-IN');
const dateFormatter = new Intl.DateTimeFormat('en-IN', {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
});

function initRefs() {
  refs.loginScreen = document.getElementById('loginScreen');
  refs.dashboardScreen = document.getElementById('dashboardScreen');
  refs.loginForm = document.getElementById('loginForm');
  refs.loginError = document.getElementById('loginError');
  refs.passwordInput = document.getElementById('adminPassword');
  refs.refreshButton = document.getElementById('refreshButton');
  refs.logoutButton = document.getElementById('logoutButton');
  refs.kpiGrid = document.getElementById('kpiGrid');
  refs.overviewBreakdown = document.getElementById('overviewBreakdown');
  refs.workersTable = document.getElementById('workersTable');
  refs.claimsTable = document.getElementById('claimsTable');
  refs.escalationsTable = document.getElementById('escalationsTable');
  refs.reportsTable = document.getElementById('reportsTable');
  refs.detailContent = document.getElementById('detailContent');
  refs.toast = document.getElementById('toast');
  refs.tabButtons = Array.from(document.querySelectorAll('.tab-button'));
  refs.panels = Array.from(document.querySelectorAll('[data-panel]'));
  refs.workerFilters = document.getElementById('workerFilters');
  refs.claimFilters = document.getElementById('claimFilters');
  refs.escalationFilters = document.getElementById('escalationFilters');
  refs.reportFilters = document.getElementById('reportFilters');
}

function showToast(message, kind = 'success') {
  refs.toast.textContent = message;
  refs.toast.className = `toast ${kind}`;
  refs.toast.classList.remove('hidden');
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => refs.toast.classList.add('hidden'), 3000);
}

function formatDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return dateFormatter.format(date);
}

function formatMoney(value) {
  const amount = Number(value || 0);
  return `₹${currency.format(amount)}`;
}

function statusClass(status) {
  const value = String(status || '').toLowerCase();
  if (['settled', 'approved', 'auto_confirmed', 'active'].includes(value)) return 'good';
  if (['pending', 'pending_review', 'in_review'].includes(value)) return 'warn';
  if (['rejected', 'failed'].includes(value)) return 'bad';
  return 'neutral';
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
    ...options,
  });

  let body = null;
  try {
    body = await response.json();
  } catch (_) {
    body = null;
  }

  if (!response.ok) {
    const detail = body?.detail || body?.message || `Request failed (${response.status})`;
    throw new Error(detail);
  }

  return body;
}

function unwrapPayload(response) {
  return response?.data ?? response;
}

function setAuthenticated(authenticated, username = 'admin') {
  state.authenticated = authenticated;
  state.adminName = username;
  refs.loginScreen.classList.toggle('hidden', authenticated);
  refs.dashboardScreen.classList.toggle('hidden', !authenticated);
}

function setActiveTab(tab) {
  state.activeTab = tab;
  refs.tabButtons.forEach((button) => {
    button.classList.toggle('active', button.dataset.tab === tab);
  });
  refs.panels.forEach((panel) => {
    panel.classList.toggle('active', panel.dataset.panel === tab);
  });
  ensureSelectionForActiveTab();
  renderDetail();
}

function ensureSelectionForActiveTab() {
  if (state.activeTab === 'overview') {
    return;
  }

  if (state.activeTab === 'workers') {
    const currentIsWorker = state.selected?.kind === 'worker';
    if (!currentIsWorker && state.workers.length > 0) {
      state.selected = { kind: 'worker', item: state.workers[0] };
    }
    if (state.workers.length === 0) {
      state.selected = null;
    }
    return;
  }

  if (state.activeTab === 'claims') {
    const currentIsClaim = state.selected?.kind === 'claim';
    if (!currentIsClaim && state.claims.length > 0) {
      state.selected = { kind: 'claim', item: state.claims[0] };
    }
    if (state.claims.length === 0) {
      state.selected = null;
    }
    return;
  }

  if (state.activeTab === 'reviews') {
    const currentIsReview = state.selected?.kind === 'escalation' || state.selected?.kind === 'report';
    if (!currentIsReview) {
      if (state.escalations.length > 0) {
        state.selected = { kind: 'escalation', item: state.escalations[0] };
      } else if (state.reports.length > 0) {
        state.selected = { kind: 'report', item: state.reports[0] };
      } else {
        state.selected = null;
      }
    }
  }
}

function renderKpis() {
  const totals = state.overview?.totals || {};
  const cards = [
    { label: 'Workers', value: totals.workers || 0, copy: `${totals.zones || 0} active zones indexed` },
    { label: 'Claims', value: totals.claims || 0, copy: `${totals.settledClaims || 0} settled claims` },
    { label: 'Settled amount', value: formatMoney(totals.totalSettledAmount || 0), copy: 'Total paid out across the fleet' },
    { label: 'Pending escalations', value: totals.pendingEscalations || 0, copy: 'Manual claim review queue' },
    { label: 'Pending reports', value: totals.pendingZoneLockReports || 0, copy: 'ZoneLock moderation queue' },
    { label: 'Pending plan changes', value: totals.pendingPlanChanges || 0, copy: 'Queued for next cycle' },
  ];

  refs.kpiGrid.innerHTML = cards
    .map(
      (card) => `
        <article class="kpi-card">
          <div class="label">${escapeHtml(card.label)}</div>
          <div class="value">${escapeHtml(card.value)}</div>
          <p class="muted">${escapeHtml(card.copy)}</p>
        </article>
      `,
    )
    .join('');
}

function renderOverviewBreakdown() {
  const totals = state.overview?.totals || {};
  const claimCounts = state.overview?.claimStatusCounts || {};
  const escalationCounts = state.overview?.escalationStatusCounts || {};
  const reportCounts = state.overview?.reportStatusCounts || {};

  const metrics = [
    {
      title: 'Claim status mix',
      value: `${Object.values(claimCounts).reduce((sum, item) => sum + Number(item || 0), 0)} records`,
      copy: Object.entries(claimCounts)
        .map(([key, count]) => `${key}: ${count}`)
        .join(' • ') || 'No claims yet',
    },
    {
      title: 'Escalation queue',
      value: `${totals.pendingEscalations || 0} pending`,
      copy: Object.entries(escalationCounts)
        .map(([key, count]) => `${key}: ${count}`)
        .join(' • ') || 'No escalations yet',
    },
    {
      title: 'ZoneLock moderation',
      value: `${totals.pendingZoneLockReports || 0} pending`,
      copy: Object.entries(reportCounts)
        .map(([key, count]) => `${key}: ${count}`)
        .join(' • ') || 'No reports yet',
    },
    {
      title: 'Coverage capacity',
      value: `${totals.pendingPlanChanges || 0} queued`,
      copy: `${totals.workers || 0} workers across ${totals.zones || 0} zones`,
    },
  ];

  refs.overviewBreakdown.innerHTML = metrics
    .map(
      (metric) => `
        <article class="metric-card">
          <div class="metric-label">${escapeHtml(metric.title)}</div>
          <div class="metric-value">${escapeHtml(metric.value)}</div>
          <p class="metric-copy">${escapeHtml(metric.copy)}</p>
        </article>
      `,
    )
    .join('');
}

function workerRow(worker) {
  return `
    <tr data-kind="worker" data-id="${escapeHtml(worker.phone)}">
      <td>
        <p class="row-title">${escapeHtml(worker.name)}</p>
        <p class="row-subtitle">${escapeHtml(worker.phone)}</p>
      </td>
      <td>${escapeHtml(worker.platform)}</td>
      <td>
        <p class="row-title">${escapeHtml(worker.zone)}</p>
        <p class="row-subtitle">${escapeHtml(worker.zonePincode)}</p>
      </td>
      <td>
        <p class="row-title">${escapeHtml(worker.plan)}</p>
        <p class="row-subtitle">Active cover</p>
      </td>
      <td>${worker.pendingPlan ? `<span class="status-pill warn">${escapeHtml(worker.pendingPlan)}</span>` : '<span class="status-pill neutral">None</span>'}</td>
      <td>${escapeHtml(formatDate(worker.createdAt))}</td>
    </tr>
  `;
}

function claimRow(claim) {
  return `
    <tr data-kind="claim" data-id="${escapeHtml(claim.id)}">
      <td>
        <p class="row-title">${escapeHtml(claim.claimRef)}</p>
        <p class="row-subtitle">${escapeHtml(claim.description)}</p>
      </td>
      <td>
        <p class="row-title">${escapeHtml(claim.workerName || claim.phone)}</p>
        <p class="row-subtitle">${escapeHtml(claim.workerZone || claim.zonePincode || '')}</p>
      </td>
      <td>${escapeHtml(claim.claimType)}</td>
      <td><span class="status-pill ${statusClass(claim.status)}">${escapeHtml(claim.status)}</span></td>
      <td>${formatMoney(claim.amount)}</td>
      <td>
        <div class="inline-actions">
          <button class="ghost-button compact" type="button" data-action="select">Review</button>
        </div>
      </td>
    </tr>
  `;
}

function escalationRow(item) {
  return `
    <tr data-kind="escalation" data-id="${escapeHtml(item.id)}">
      <td>
        <p class="row-title">${escapeHtml(item.escalationRef)}</p>
        <p class="row-subtitle">${escapeHtml(item.reason)}</p>
      </td>
      <td>
        <p class="row-title">${escapeHtml(item.claimRef)}</p>
        <p class="row-subtitle">${escapeHtml(item.workerName || item.phone)}</p>
      </td>
      <td><span class="status-pill ${statusClass(item.status)}">${escapeHtml(item.status)}</span></td>
      <td><button class="ghost-button compact" type="button" data-action="select">Review</button></td>
    </tr>
  `;
}

function reportRow(item) {
  return `
    <tr data-kind="report" data-id="${escapeHtml(item.id)}">
      <td>
        <p class="row-title">${escapeHtml(item.reportRef)}</p>
        <p class="row-subtitle">${escapeHtml(item.workerName || item.phone)}</p>
      </td>
      <td>
        <p class="row-title">${escapeHtml(item.zoneName)}</p>
        <p class="row-subtitle">${escapeHtml(item.zonePincode)}</p>
      </td>
      <td><span class="status-pill ${statusClass(item.status)}">${escapeHtml(item.status)}</span></td>
      <td><button class="ghost-button compact" type="button" data-action="select">Review</button></td>
    </tr>
  `;
}

function renderTables() {
  refs.workersTable.innerHTML = state.workers.map(workerRow).join('') || '<tr><td colspan="6">No workers found.</td></tr>';
  refs.claimsTable.innerHTML = state.claims.map(claimRow).join('') || '<tr><td colspan="6">No claims found.</td></tr>';
  refs.escalationsTable.innerHTML = state.escalations.map(escalationRow).join('') || '<tr><td colspan="4">No escalations found.</td></tr>';
  refs.reportsTable.innerHTML = state.reports.map(reportRow).join('') || '<tr><td colspan="4">No reports found.</td></tr>';

  document.querySelectorAll('tbody tr').forEach((row) => {
    row.addEventListener('click', (event) => {
      const kind = row.dataset.kind;
      const id = row.dataset.id;
      if (!kind || !id) return;
      const item = lookupItem(kind, id);
      if (!item) return;
      if (event.target instanceof HTMLElement && event.target.closest('button')) {
        event.preventDefault();
      }
      selectItem(kind, item);
    });
  });
}

function lookupItem(kind, id) {
  const collection = {
    worker: state.workers,
    claim: state.claims,
    escalation: state.escalations,
    report: state.reports,
  }[kind] || [];
  return collection.find((item) => String(item.id ?? item.phone ?? '') === String(id));
}

function selectItem(kind, item) {
  state.selected = { kind, item };
  renderDetail();
}

function renderDetail() {
  const selection = state.selected;
  if (!selection) {
    refs.detailContent.innerHTML = '<p class="muted">Select a row in the active tab to view details and actions.</p>';
    return;
  }

  const { kind, item } = selection;
  if (kind === 'worker') {
    refs.detailContent.innerHTML = `
      <div class="detail-grid">
        <div class="detail-row"><span>Worker</span><strong>${escapeHtml(item.name)}</strong></div>
        <div class="detail-row"><span>Phone</span><strong>${escapeHtml(item.phone)}</strong></div>
        <div class="detail-row"><span>Platform</span><strong>${escapeHtml(item.platform)}</strong></div>
        <div class="detail-row"><span>Zone</span><strong>${escapeHtml(item.zone)} (${escapeHtml(item.zonePincode)})</strong></div>
        <div class="detail-row"><span>Plan</span><strong>${escapeHtml(item.plan)}</strong></div>
        <div class="detail-row"><span>Pending plan</span><strong>${escapeHtml(item.pendingPlan || 'None')}</strong></div>
        <div class="detail-row"><span>Joined</span><strong>${escapeHtml(formatDate(item.createdAt))}</strong></div>
      </div>
    `;
    return;
  }

  const actionOptions = kind === 'claim'
    ? ['pending', 'in_review', 'settled', 'rejected', 'escalated']
    : kind === 'escalation'
      ? ['pending_review', 'approved', 'rejected']
      : ['pending', 'auto_confirmed', 'approved', 'rejected'];
  const currentStatus = item.status || 'pending';
  const existingNotes = kind === 'escalation' ? (item.reviewNotes || '') : '';
  const notesField = kind === 'escalation'
    ? `<label class="field"><span>Review notes</span><textarea id="detailNotes" placeholder="Optional notes for the reviewer">${escapeHtml(existingNotes)}</textarea></label>`
    : '';

  refs.detailContent.innerHTML = `
    <div class="detail-grid">
      <div class="detail-row"><span>Record</span><strong>${escapeHtml(item.claimRef || item.escalationRef || item.reportRef || item.id)}</strong></div>
      <div class="detail-row"><span>Status</span><strong><span class="status-pill ${statusClass(currentStatus)}">${escapeHtml(currentStatus)}</span></strong></div>
      ${kind === 'claim' ? `<div class="detail-row"><span>Type</span><strong>${escapeHtml(item.claimType)}</strong></div>` : ''}
      ${kind === 'claim' ? `<div class="detail-row"><span>Amount</span><strong>${formatMoney(item.amount)}</strong></div>` : ''}
      ${kind !== 'worker' ? `<div class="detail-row"><span>Worker</span><strong>${escapeHtml(item.workerName || item.phone)}</strong></div>` : ''}
      ${kind === 'escalation' ? `<div class="detail-row"><span>Reason</span><strong>${escapeHtml(item.reason)}</strong></div>` : ''}
      ${kind === 'escalation' && item.reviewNotes ? `<div class="detail-row"><span>Current notes</span><strong>${escapeHtml(item.reviewNotes)}</strong></div>` : ''}
      ${kind === 'report' ? `<div class="detail-row"><span>Zone</span><strong>${escapeHtml(item.zoneName)} (${escapeHtml(item.zonePincode)})</strong></div>` : ''}
      <div class="detail-row"><span>Created</span><strong>${escapeHtml(formatDate(item.createdAt))}</strong></div>
      <div class="detail-actions">
        <label class="field">
          <span>Update status</span>
          <select id="detailStatus" class="inline-select">
            ${actionOptions.map((status) => `<option value="${escapeHtml(status)}" ${status === currentStatus ? 'selected' : ''}>${escapeHtml(status)}</option>`).join('')}
          </select>
        </label>
        ${notesField}
        <button class="primary-button" type="button" id="detailSaveButton" data-action="save-detail">Save changes</button>
      </div>
    </div>
  `;
}

async function refreshAfterAction(kind) {
  try {
    if (kind === 'claim') {
      await Promise.all([loadOverviewData(), loadClaimsData()]);
    } else if (kind === 'escalation') {
      await Promise.all([loadOverviewData(), loadEscalationsData()]);
    } else if (kind === 'report') {
      await Promise.all([loadOverviewData(), loadReportsData()]);
    }
    renderKpis();
    renderOverviewBreakdown();
    renderTables();
    ensureSelectionForActiveTab();
    renderDetail();
  } catch (error) {
    showToast(error.message, 'error');
  }
}

async function saveDetail(kind, item) {
  const statusValue = document.getElementById('detailStatus')?.value?.trim();
  const notes = document.getElementById('detailNotes')?.value?.trim();
  const saveButton = document.getElementById('detailSaveButton');

  if (!statusValue) {
    showToast('Please select a status before saving.', 'error');
    return;
  }

  if (saveButton) {
    saveButton.setAttribute('disabled', 'true');
    saveButton.textContent = 'Saving...';
  }

  try {
    if (kind === 'claim') {
      const result = await api(`/api/v1/admin/claims/${item.id}/status`, {
        method: 'POST',
        body: JSON.stringify({ status: statusValue }),
      });
      syncUpdatedItem('claim', result.data);
      showToast('Claim status updated');
    } else if (kind === 'escalation') {
      const result = await api(`/api/v1/admin/escalations/${item.id}/review`, {
        method: 'POST',
        body: JSON.stringify({ status: statusValue, reviewNotes: notes || null }),
      });
      syncUpdatedItem('escalation', result.data);
      showToast('Escalation reviewed');
    } else if (kind === 'report') {
      const result = await api(`/api/v1/admin/zonelock-reports/${item.id}/review`, {
        method: 'POST',
        body: JSON.stringify({ status: statusValue }),
      });
      syncUpdatedItem('report', result.data);
      showToast('ZoneLock report updated');
    }

    // Apply the immediate UI update first for snappy feedback.
    renderTables();
    ensureSelectionForActiveTab();
    renderDetail();

    // Re-sync from server in background for final consistency.
    refreshAfterAction(kind);
  } catch (error) {
    showToast(error.message, 'error');
  } finally {
    if (saveButton) {
      saveButton.removeAttribute('disabled');
      saveButton.textContent = 'Save changes';
    }
  }
}

function syncUpdatedItem(kind, item) {
  const collections = {
    claim: 'claims',
    escalation: 'escalations',
    report: 'reports',
  };
  const key = collections[kind];
  if (!key) return;
  state[key] = state[key].map((entry) => (String(entry.id) === String(item.id) ? item : entry));
  if (state.selected?.kind === kind && String(state.selected.item.id) === String(item.id)) {
    state.selected = { kind, item };
  }
}

function loadFilterValues() {
  return {
    workers: {
      search: document.getElementById('workerSearch').value.trim(),
      zone: document.getElementById('workerZone').value.trim(),
      platform: document.getElementById('workerPlatform').value.trim(),
    },
    claims: {
      search: document.getElementById('claimSearch').value.trim(),
      status: document.getElementById('claimStatus').value.trim(),
      claimType: document.getElementById('claimType').value.trim(),
      source: document.getElementById('claimSource').value.trim(),
    },
    escalations: {
      search: document.getElementById('escalationSearch').value.trim(),
      status: document.getElementById('escalationStatus').value.trim(),
    },
    reports: {
      search: document.getElementById('reportSearch').value.trim(),
      status: document.getElementById('reportStatus').value.trim(),
      zone: document.getElementById('reportZone').value.trim(),
    },
  };
}

async function loadOverviewData() {
  const overviewResponse = await api('/api/v1/admin/overview');
  state.overview = unwrapPayload(overviewResponse);
}

async function loadWorkersData() {
  const filters = loadFilterValues();
  const workersResponse = await api(
    `/api/v1/admin/workers?${new URLSearchParams({ ...filters.workers, limit: '60', offset: '0' }).toString()}`,
  );
  state.workers = unwrapPayload(workersResponse)?.items || [];
}

async function loadClaimsData() {
  const filters = loadFilterValues();
  const claimsResponse = await api(
    `/api/v1/admin/claims?${new URLSearchParams({ ...filters.claims, limit: '80', offset: '0' }).toString()}`,
  );
  state.claims = unwrapPayload(claimsResponse)?.items || [];
}

async function loadEscalationsData() {
  const filters = loadFilterValues();
  const escalationsResponse = await api(
    `/api/v1/admin/escalations?${new URLSearchParams({ ...filters.escalations, limit: '60', offset: '0' }).toString()}`,
  );
  state.escalations = unwrapPayload(escalationsResponse)?.items || [];
}

async function loadReportsData() {
  const filters = loadFilterValues();
  const reportsResponse = await api(
    `/api/v1/admin/zonelock-reports?${new URLSearchParams({ ...filters.reports, limit: '60', offset: '0' }).toString()}`,
  );
  state.reports = unwrapPayload(reportsResponse)?.items || [];
}

async function loadData() {
  try {
    await Promise.all([
      loadOverviewData(),
      loadWorkersData(),
      loadClaimsData(),
      loadEscalationsData(),
      loadReportsData(),
    ]);

    renderKpis();
    renderOverviewBreakdown();
    renderTables();
    ensureSelectionForActiveTab();
    renderDetail();
  } catch (error) {
    showToast(error.message, 'error');
  }
}

async function bootstrapSession() {
  try {
    const response = await api('/api/v1/admin/session');
    const data = unwrapPayload(response) || {};
    setAuthenticated(Boolean(data.authenticated), data.username || 'admin');
    if (data.authenticated) {
      await loadData();
    }
  } catch (_) {
    setAuthenticated(false);
  }
}

function bindEvents() {
  refs.loginForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    refs.loginError.textContent = '';

    try {
      const response = await api('/api/v1/admin/auth/login', {
        method: 'POST',
        body: JSON.stringify({ password: refs.passwordInput.value }),
      });
      const data = unwrapPayload(response) || {};
      setAuthenticated(Boolean(data.authenticated), data.username || 'admin');
      await loadData();
      showToast('Admin session restored');
    } catch (error) {
      refs.loginError.textContent = error.message;
    }
  });

  refs.logoutButton.addEventListener('click', async () => {
    try {
      await api('/api/v1/admin/auth/logout', { method: 'POST' });
      state.selected = null;
      setAuthenticated(false);
      showToast('Signed out');
    } catch (error) {
      showToast(error.message, 'error');
    }
  });

  refs.refreshButton.addEventListener('click', () => loadData());

  refs.detailContent.addEventListener('click', (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const saveTrigger = target.closest('[data-action="save-detail"]');
    if (!saveTrigger) return;

    const selection = state.selected;
    if (!selection) {
      showToast('Select a record first.', 'error');
      return;
    }
    saveDetail(selection.kind, selection.item);
  });

  refs.tabButtons.forEach((button) => {
    button.addEventListener('click', () => setActiveTab(button.dataset.tab));
  });

  refs.workerFilters.addEventListener('submit', (event) => {
    event.preventDefault();
    loadWorkersData()
      .then(() => {
        renderTables();
        ensureSelectionForActiveTab();
        renderDetail();
      })
      .catch((error) => showToast(error.message, 'error'));
  });
  refs.claimFilters.addEventListener('submit', (event) => {
    event.preventDefault();
    loadClaimsData()
      .then(() => {
        renderTables();
        ensureSelectionForActiveTab();
        renderDetail();
      })
      .catch((error) => showToast(error.message, 'error'));
  });
  refs.escalationFilters.addEventListener('submit', (event) => {
    event.preventDefault();
    loadEscalationsData()
      .then(() => {
        renderTables();
        ensureSelectionForActiveTab();
        renderDetail();
      })
      .catch((error) => showToast(error.message, 'error'));
  });
  refs.reportFilters.addEventListener('submit', (event) => {
    event.preventDefault();
    loadReportsData()
      .then(() => {
        renderTables();
        ensureSelectionForActiveTab();
        renderDetail();
      })
      .catch((error) => showToast(error.message, 'error'));
  });

  document.querySelectorAll('[data-reset-filters]').forEach((button) => {
    button.addEventListener('click', () => {
      if (button.dataset.resetFilters === 'workers') {
        refs.workerFilters.reset();
        loadWorkersData()
          .then(() => {
            renderTables();
            ensureSelectionForActiveTab();
            renderDetail();
          })
          .catch((error) => showToast(error.message, 'error'));
        return;
      }
      if (button.dataset.resetFilters === 'claims') {
        refs.claimFilters.reset();
        loadClaimsData()
          .then(() => {
            renderTables();
            ensureSelectionForActiveTab();
            renderDetail();
          })
          .catch((error) => showToast(error.message, 'error'));
        return;
      }
      if (button.dataset.resetFilters === 'reviews') {
        refs.escalationFilters.reset();
        refs.reportFilters.reset();
        Promise.all([loadEscalationsData(), loadReportsData()])
          .then(() => {
            renderTables();
            ensureSelectionForActiveTab();
            renderDetail();
          })
          .catch((error) => showToast(error.message, 'error'));
        return;
      }
    });
  });
}

async function main() {
  initRefs();
  bindEvents();
  await bootstrapSession();
  setActiveTab('overview');
}

main();