const params = new URLSearchParams(location.search);
const token = params.get('token') || sessionStorage.getItem('mere-graph-studio-token') || '';
if (token) sessionStorage.setItem('mere-graph-studio-token', token);
if (params.has('token')) history.replaceState({}, '', location.pathname);

const DEFAULT_GRAPH = () => ({
  schema_version: 1,
  kind: 'mere.run/workflow-graph',
  name: 'Untitled workflow',
  inputs: {},
  execution: { max_parallel_nodes: 1 },
  nodes: [],
  outputs: {},
  metadata: {},
});
const DEFAULT_SIDECAR = () => ({
  schema_version: 1,
  kind: 'mere.run/workflow-editor',
  viewport: { x: 0, y: 0, zoom: 1 },
  nodes: {},
});

const state = {
  graph: DEFAULT_GRAPH(),
  inputs: {},
  sidecar: DEFAULT_SIDECAR(),
  catalog: [],
  executors: ['local'],
  selectedNode: null,
  selectedRun: null,
  projectPath: null,
  view: 'canvas',
  libraryTab: 'nodes',
  runs: [],
  diagnosticDocument: null,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const escapeHTML = (value) => String(value ?? '')
  .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;').replaceAll("'", '&#39;');
const clone = (value) => JSON.parse(JSON.stringify(value));

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', 'X-Mere-Studio-Token': token, ...(options.headers || {}) },
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || `Request failed: ${response.status}`);
  return body;
}

function commandPayload(document) {
  return document?.result ?? document;
}

function entryForNode(node) {
  return state.catalog.find((entry) => entry.kind === node.kind
    && (!node.provider || node.provider === 'mere.run' || entry.provider?.id === node.provider));
}

function nodePosition(nodeId, index = 0) {
  if (!state.sidecar.nodes[nodeId]) {
    state.sidecar.nodes[nodeId] = { x: 70 + (index % 3) * 270, y: 70 + Math.floor(index / 3) * 150 };
  }
  return state.sidecar.nodes[nodeId];
}

function referencesIn(value, found = []) {
  if (Array.isArray(value)) value.forEach((item) => referencesIn(item, found));
  else if (value && typeof value === 'object') {
    if (Object.keys(value).length === 1 && typeof value.$ref === 'string') found.push(value.$ref);
    else Object.values(value).forEach((item) => referencesIn(item, found));
  }
  return found;
}

function replaceReference(value, from, to) {
  if (Array.isArray(value)) return value.map((item) => replaceReference(item, from, to));
  if (!value || typeof value !== 'object') return value;
  if (Object.keys(value).length === 1 && typeof value.$ref === 'string') {
    return { $ref: value.$ref.replace(from, to) };
  }
  return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, replaceReference(item, from, to)]));
}

function uniqueId(base, existing) {
  const clean = base.toLowerCase().replace(/[^a-z0-9-]+/g, '-').replace(/^[^a-z]+/, '').replace(/-+$/g, '') || 'node';
  if (!existing.has(clean)) return clean;
  let index = 2;
  while (existing.has(`${clean}-${index}`)) index += 1;
  return `${clean}-${index}`;
}

function defaultFieldValue(field) {
  if (field.default !== undefined) return clone(field.default);
  if (field.secret) return { $secret: '' };
  if (field.required === false) return undefined;
  if (field.type === 'boolean') return false;
  if (field.type === 'integer' || field.type === 'number') return field.minimum ?? 0;
  if (field.type === 'enum') return field.values?.[0] ?? '';
  if (field.type === 'json') return {};
  if (field.type === 'asset_collection' || field.type === 'asset_array') return [];
  return '';
}

function addNode(entry) {
  const ids = new Set(state.graph.nodes.map((node) => node.id));
  const id = uniqueId(entry.kind.split('.').at(-1), ids);
  const node = { id, kind: entry.kind, arguments: {} };
  if (entry.provider?.id && entry.provider.id !== 'mere.run') node.provider = entry.provider.id;
  for (const field of entry.inputs || []) {
    const value = defaultFieldValue(field);
    if (value !== undefined) node.arguments[field.name] = value;
  }
  if ((entry.inputs || []).some((field) => field.secret)) node.execution = { cache: 'never' };
  state.graph.nodes.push(node);
  const index = state.graph.nodes.length - 1;
  state.sidecar.nodes[id] = { x: 70 + (index % 3) * 270, y: 70 + Math.floor(index / 3) * 150 };
  state.selectedNode = id;
  renderAll();
}

function renderCatalog() {
  const query = $('#catalog-search').value.trim().toLowerCase();
  const filtered = state.catalog.filter((entry) => [entry.kind, entry.title, entry.description, entry.category]
    .some((value) => String(value || '').toLowerCase().includes(query)));
  const groups = Object.groupBy ? Object.groupBy(filtered, (entry) => entry.category || 'Other')
    : filtered.reduce((result, entry) => {
      const key = entry.category || 'Other';
      (result[key] ||= []).push(entry);
      return result;
    }, {});
  $('#catalog-list').innerHTML = Object.entries(groups).sort(([a], [b]) => a.localeCompare(b)).map(([group, entries]) => `
    <section class="catalog-group">
      <strong>${escapeHTML(group)}</strong>
      ${entries.map((entry) => `
        <button class="catalog-item" data-add-kind="${escapeHTML(entry.kind)}" data-add-provider="${escapeHTML(entry.provider?.id || 'mere.run')}">
          <span class="node-glyph">${escapeHTML(entry.kind.split('.').at(-1).slice(0, 1).toUpperCase())}</span>
          <span><b>${escapeHTML(entry.title)}</b><small>${escapeHTML(entry.kind)}</small></span>
          <span aria-hidden="true">＋</span>
        </button>`).join('')}
    </section>`).join('') || '<div class="empty-state">No matching nodes</div>';
  $$('[data-add-kind]').forEach((button) => button.addEventListener('click', () => {
    const entry = state.catalog.find((candidate) => candidate.kind === button.dataset.addKind
      && (candidate.provider?.id || 'mere.run') === button.dataset.addProvider);
    if (entry) addNode(entry);
  }));
}

function renderCanvas() {
  const layer = $('#node-layer');
  $('#empty-add').classList.toggle('hidden', state.graph.nodes.length > 0);
  layer.innerHTML = state.graph.nodes.map((node, index) => {
    const entry = entryForNode(node) || { title: node.kind, inputs: [], outputs: [] };
    const position = nodePosition(node.id, index);
    return `<article class="graph-node ${state.selectedNode === node.id ? 'selected' : ''}" data-node-id="${escapeHTML(node.id)}" style="left:${position.x}px;top:${position.y}px">
      <header class="node-header" data-drag-node="${escapeHTML(node.id)}">
        <span class="node-glyph">${escapeHTML(node.kind.split('.').at(-1).slice(0, 1).toUpperCase())}</span>
        <span><b>${escapeHTML(entry.title || node.kind)}</b><small>${escapeHTML(node.id)}</small></span>
        <span class="node-index">${String(index + 1).padStart(2, '0')}</span>
      </header>
      <div class="node-ports">
        <div>${(entry.inputs || []).slice(0, 5).map((field) => `<span class="port-row">${escapeHTML(field.name)}</span>`).join('')}</div>
        <div>${(entry.outputs || []).slice(0, 5).map((field) => `<span class="port-row">${escapeHTML(field.name)}</span>`).join('')}</div>
      </div>
    </article>`;
  }).join('');
  applyViewport();
  layer.querySelectorAll('.graph-node').forEach((element) => element.addEventListener('click', (event) => {
    event.stopPropagation();
    state.selectedNode = element.dataset.nodeId;
    renderCanvas();
    renderInspector();
  }));
  layer.querySelectorAll('[data-drag-node]').forEach((header) => attachNodeDrag(header));
  renderEdges();
}

function renderEdges() {
  const paths = [];
  for (const target of state.graph.nodes) {
    const targetPosition = nodePosition(target.id);
    for (const reference of referencesIn(target.arguments)) {
      const match = reference.match(/^nodes\.([a-z][a-z0-9-]*)\.outputs\./);
      if (!match) continue;
      const source = state.graph.nodes.find((node) => node.id === match[1]);
      if (!source) continue;
      const sourcePosition = nodePosition(source.id);
      const x1 = sourcePosition.x + 230;
      const y1 = sourcePosition.y + 67;
      const x2 = targetPosition.x;
      const y2 = targetPosition.y + 67;
      const curve = Math.max(50, Math.abs(x2 - x1) * 0.45);
      const selected = state.selectedNode === source.id || state.selectedNode === target.id ? 'selected' : '';
      paths.push(`<path class="${selected}" d="M ${x1} ${y1} C ${x1 + curve} ${y1}, ${x2 - curve} ${y2}, ${x2} ${y2}"/>`);
    }
  }
  $('#edge-layer').innerHTML = paths.join('');
  applyViewport();
}

function applyViewport() {
  const viewport = state.sidecar.viewport || (state.sidecar.viewport = { x: 0, y: 0, zoom: 1 });
  const transform = `translate(${viewport.x || 0}px, ${viewport.y || 0}px) scale(${viewport.zoom || 1})`;
  $('#node-layer').style.transform = transform;
  $('#edge-layer').style.transform = transform;
  $('#zoom-label').textContent = `${Math.round((viewport.zoom || 1) * 100)}%`;
}

function attachNodeDrag(header) {
  header.addEventListener('pointerdown', (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    const id = header.dataset.dragNode;
    const position = nodePosition(id);
    const start = { clientX: event.clientX, clientY: event.clientY, nodeX: position.x, nodeY: position.y };
    const move = (moveEvent) => {
      const zoom = state.sidecar.viewport.zoom || 1;
      state.sidecar.nodes[id] = {
        x: Math.round(start.nodeX + (moveEvent.clientX - start.clientX) / zoom),
        y: Math.round(start.nodeY + (moveEvent.clientY - start.clientY) / zoom),
      };
      const element = document.querySelector(`[data-node-id="${CSS.escape(id)}"]`);
      element.style.left = `${state.sidecar.nodes[id].x}px`;
      element.style.top = `${state.sidecar.nodes[id].y}px`;
      renderEdges();
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  });
}

function referenceOptions(node, field) {
  const options = [];
  for (const [name, definition] of Object.entries(state.graph.inputs)) {
    if (compatibleTypes(definition.type, field.type)) options.push({ value: `inputs.${name}`, label: `Input / ${name}` });
  }
  for (const candidate of state.graph.nodes) {
    if (candidate.id === node.id) continue;
    const entry = entryForNode(candidate);
    for (const output of entry?.outputs || []) {
      if (compatibleTypes(output.type, field.type)) {
        options.push({ value: `nodes.${candidate.id}.outputs.${output.name}`, label: `${candidate.id} / ${output.name}` });
      }
    }
  }
  return options;
}

function compatibleTypes(source, target) {
  if (source === target) return true;
  if (source === 'integer' && target === 'number') return true;
  if (['asset_collection', 'asset_array'].includes(source) && ['asset_collection', 'asset_array'].includes(target)) return true;
  return false;
}

function argumentMode(value, field) {
  if (value && typeof value === 'object' && Object.keys(value).length === 1 && '$ref' in value) return 'reference';
  if (value && typeof value === 'object' && Object.keys(value).length === 1 && '$secret' in value) return 'secret';
  return field.secret ? 'secret' : 'constant';
}

function valueControl(field, value, mode) {
  if (mode === 'secret') return `<input type="text" data-field-value="${escapeHTML(field.name)}" value="${escapeHTML(value?.$secret || '')}" placeholder="secret-name">`;
  if (mode === 'reference') return '';
  if (field.type === 'boolean') return `<label class="check-row"><input type="checkbox" data-field-value="${escapeHTML(field.name)}" ${value ? 'checked' : ''}>Enabled</label>`;
  if (field.type === 'enum') return `<select data-field-value="${escapeHTML(field.name)}">${(field.values || []).map((item) => `<option ${item === value ? 'selected' : ''}>${escapeHTML(item)}</option>`).join('')}</select>`;
  if (field.type === 'integer' || field.type === 'number') return `<input type="number" data-field-value="${escapeHTML(field.name)}" value="${escapeHTML(value ?? '')}" ${field.minimum !== undefined ? `min="${field.minimum}"` : ''} ${field.maximum !== undefined ? `max="${field.maximum}"` : ''} ${field.step !== undefined ? `step="${field.step}"` : ''}>`;
  if (field.type === 'json' || field.type === 'asset_collection' || field.type === 'asset_array') return `<textarea data-field-value="${escapeHTML(field.name)}">${escapeHTML(JSON.stringify(value ?? (field.type === 'json' ? {} : []), null, 2))}</textarea>`;
  if (field.multiline) return `<textarea data-field-value="${escapeHTML(field.name)}">${escapeHTML(value ?? '')}</textarea>`;
  return `<input type="text" data-field-value="${escapeHTML(field.name)}" value="${escapeHTML(value ?? '')}">`;
}

function renderInspector() {
  const node = state.graph.nodes.find((candidate) => candidate.id === state.selectedNode);
  $('#selection-kind').textContent = node ? node.kind : 'Graph';
  if (!node) {
    renderGraphInspector();
    return;
  }
  const entry = entryForNode(node) || { inputs: [], outputs: [] };
  const fields = (entry.inputs || []).map((field) => {
    const value = node.arguments[field.name];
    const mode = argumentMode(value, field);
    const options = referenceOptions(node, field);
    const availableModes = field.secret ? ['secret'] : ['constant', 'reference'];
    return `<div class="field" data-argument-field="${escapeHTML(field.name)}">
      <span class="field-label">${escapeHTML(field.name)}${field.required ? ' *' : ''}</span>
      <div class="field-row">
        <select class="field-mode" data-field-mode="${escapeHTML(field.name)}">${availableModes.map((item) => `<option value="${item}" ${item === mode ? 'selected' : ''}>${item}</option>`).join('')}</select>
        <div data-field-editor="${escapeHTML(field.name)}">${mode === 'reference'
          ? `<select data-field-reference="${escapeHTML(field.name)}">${options.map((option) => `<option value="${escapeHTML(option.value)}" ${value?.$ref === option.value ? 'selected' : ''}>${escapeHTML(option.label)}</option>`).join('')}</select>`
          : valueControl(field, value, mode)}</div>
      </div>
    </div>`;
  }).join('');
  const policy = node.execution || {};
  $('#inspector').innerHTML = `
    <section class="inspector-section">
      <div class="field"><label>Node ID</label><input type="text" id="node-id" value="${escapeHTML(node.id)}"></div>
      <div class="field"><label>Kind</label><input type="text" value="${escapeHTML(node.kind)}" disabled></div>
    </section>
    <section class="inspector-section"><strong>Arguments</strong>${fields || '<span class="empty-state">No arguments</span>'}</section>
    <section class="inspector-section"><strong>Execution</strong>
      <div class="field"><label>Cache</label><select id="node-cache">${['auto', 'never', 'refresh'].map((item) => `<option ${item === (policy.cache || 'auto') ? 'selected' : ''}>${item}</option>`).join('')}</select></div>
      <div class="field-row"><div class="field"><label>Attempts</label><input id="node-attempts" type="number" min="1" max="10" value="${policy.max_attempts || 1}"></div><div class="field"><label>Timeout (s)</label><input id="node-timeout" type="number" min="1" max="604800" value="${policy.timeout_seconds || ''}"></div></div>
    </section>
    <section class="inspector-section"><strong>Outputs</strong>${(entry.outputs || []).map((output) => `<div class="field"><span class="field-label">${escapeHTML(output.name)}</span><button class="command-button" data-expose-output="${escapeHTML(output.name)}">Expose as graph output</button></div>`).join('')}</section>
    <section class="inspector-section"><div class="section-actions"><button class="command-button danger" data-delete-node>Delete node</button></div></section>`;
  bindNodeInspector(node, entry);
}

function bindNodeInspector(node, entry) {
  $('#node-id').addEventListener('change', (event) => renameNode(node, event.target.value));
  $$('[data-field-mode]').forEach((control) => control.addEventListener('change', () => {
    const field = entry.inputs.find((item) => item.name === control.dataset.fieldMode);
    if (!field) return;
    if (control.value === 'reference') {
      const first = referenceOptions(node, field)[0];
      node.arguments[field.name] = { $ref: first?.value || '' };
    } else if (control.value === 'secret') node.arguments[field.name] = { $secret: '' };
    else node.arguments[field.name] = defaultFieldValue({ ...field, secret: false });
    renderInspector();
    renderCanvas();
  }));
  $$('[data-field-reference]').forEach((control) => control.addEventListener('change', () => {
    node.arguments[control.dataset.fieldReference] = { $ref: control.value };
    renderCanvas();
  }));
  $$('[data-field-value]').forEach((control) => {
    const eventName = control.type === 'checkbox' ? 'change' : 'input';
    control.addEventListener(eventName, () => {
      const field = entry.inputs.find((item) => item.name === control.dataset.fieldValue);
      if (!field) return;
      const mode = argumentMode(node.arguments[field.name], field);
      try {
        if (mode === 'secret') node.arguments[field.name] = { $secret: control.value };
        else if (field.type === 'boolean') node.arguments[field.name] = control.checked;
        else if (field.type === 'integer') node.arguments[field.name] = Number.parseInt(control.value, 10);
        else if (field.type === 'number') node.arguments[field.name] = Number.parseFloat(control.value);
        else if (field.type === 'json' || field.type === 'asset_collection' || field.type === 'asset_array') node.arguments[field.name] = JSON.parse(control.value);
        else node.arguments[field.name] = control.value;
      } catch { control.setAttribute('aria-invalid', 'true'); }
    });
  });
  $('#node-cache').addEventListener('change', updateNodePolicy);
  $('#node-attempts').addEventListener('change', updateNodePolicy);
  $('#node-timeout').addEventListener('change', updateNodePolicy);
  $('[data-delete-node]').addEventListener('click', () => deleteNode(node.id));
  $$('[data-expose-output]').forEach((button) => button.addEventListener('click', () => {
    const outputName = uniqueId(button.dataset.exposeOutput.replaceAll('_', '-'), new Set(Object.keys(state.graph.outputs)));
    state.graph.outputs[outputName] = { $ref: `nodes.${node.id}.outputs.${button.dataset.exposeOutput}` };
    state.selectedNode = null;
    renderInspector();
  }));
}

function updateNodePolicy() {
  const node = state.graph.nodes.find((candidate) => candidate.id === state.selectedNode);
  if (!node) return;
  node.execution = { cache: $('#node-cache').value, max_attempts: Number($('#node-attempts').value || 1) };
  if ($('#node-timeout').value) node.execution.timeout_seconds = Number($('#node-timeout').value);
}

function renameNode(node, desired) {
  const valid = /^[a-z][a-z0-9-]{0,63}$/.test(desired);
  const collision = state.graph.nodes.some((candidate) => candidate !== node && candidate.id === desired);
  if (!valid || collision) {
    showDiagnostics([{ severity: 'blocker', title: 'Invalid node ID', message: 'Use a unique lowercase identifier with letters, numbers, and hyphens.' }], 'Rename blocked');
    renderInspector();
    return;
  }
  const old = node.id;
  node.id = desired;
  for (const candidate of state.graph.nodes) {
    candidate.arguments = replaceReference(candidate.arguments, `nodes.${old}.`, `nodes.${desired}.`);
    if (candidate.depends_on) candidate.depends_on = candidate.depends_on.map((id) => id === old ? desired : id);
  }
  state.graph.outputs = replaceReference(state.graph.outputs, `nodes.${old}.`, `nodes.${desired}.`);
  state.sidecar.nodes[desired] = state.sidecar.nodes[old];
  delete state.sidecar.nodes[old];
  state.selectedNode = desired;
  renderAll();
}

function deleteNode(id) {
  state.graph.nodes = state.graph.nodes.filter((node) => node.id !== id);
  state.graph.outputs = Object.fromEntries(Object.entries(state.graph.outputs)
    .filter(([, value]) => !referencesIn(value).some((reference) => reference.startsWith(`nodes.${id}.`))));
  delete state.sidecar.nodes[id];
  state.selectedNode = null;
  renderAll();
}

function allOutputOptions() {
  const options = [];
  for (const node of state.graph.nodes) {
    for (const output of entryForNode(node)?.outputs || []) {
      options.push({ value: `nodes.${node.id}.outputs.${output.name}`, label: `${node.id} / ${output.name}` });
    }
  }
  return options;
}

function renderGraphInspector() {
  const outputs = allOutputOptions();
  $('#inspector').innerHTML = `
    <section class="inspector-section"><strong>Workflow</strong>
      <div class="field"><label>Name</label><input id="graph-name" type="text" value="${escapeHTML(state.graph.name)}"></div>
      <div class="field"><label>Parallel nodes</label><input id="graph-parallel" type="number" min="1" max="32" value="${state.graph.execution?.max_parallel_nodes || 1}"></div>
    </section>
    <section class="inspector-section"><strong>Graph outputs</strong>
      ${Object.entries(state.graph.outputs).map(([name, value]) => `<div class="field" data-output-row="${escapeHTML(name)}"><label>${escapeHTML(name)}</label><div class="field-row"><select data-output-ref="${escapeHTML(name)}">${outputs.map((option) => `<option value="${escapeHTML(option.value)}" ${value?.$ref === option.value ? 'selected' : ''}>${escapeHTML(option.label)}</option>`).join('')}</select><button class="icon-button small" data-remove-output="${escapeHTML(name)}" aria-label="Remove output">×</button></div></div>`).join('') || '<div class="empty-state">No graph outputs</div>'}
      <div class="section-actions"><button class="command-button" data-add-output ${outputs.length ? '' : 'disabled'}>＋ Output</button></div>
    </section>`;
  $('#graph-name').addEventListener('input', (event) => {
    state.graph.name = event.target.value;
    $('#project-label').textContent = state.graph.name;
  });
  $('#graph-parallel').addEventListener('change', (event) => {
    state.graph.execution ||= {};
    state.graph.execution.max_parallel_nodes = Math.max(1, Math.min(32, Number(event.target.value || 1)));
  });
  $$('[data-output-ref]').forEach((control) => control.addEventListener('change', () => { state.graph.outputs[control.dataset.outputRef] = { $ref: control.value }; }));
  $$('[data-remove-output]').forEach((button) => button.addEventListener('click', () => { delete state.graph.outputs[button.dataset.removeOutput]; renderGraphInspector(); }));
  $('[data-add-output]')?.addEventListener('click', () => {
    const name = uniqueId('output', new Set(Object.keys(state.graph.outputs)));
    state.graph.outputs[name] = { $ref: outputs[0].value };
    renderGraphInspector();
  });
}

function renderInputs() {
  const types = ['string', 'integer', 'number', 'boolean', 'enum', 'json', 'asset', 'asset_directory', 'asset_collection'];
  $('#input-list').innerHTML = Object.entries(state.graph.inputs).map(([name, definition]) => `
    <section class="input-item" data-input-name="${escapeHTML(name)}">
      <div class="input-item-header"><b>${escapeHTML(name)}</b><button data-remove-input="${escapeHTML(name)}" aria-label="Remove input">×</button></div>
      <div class="compact-grid"><input data-input-id="${escapeHTML(name)}" value="${escapeHTML(name)}"><select data-input-type="${escapeHTML(name)}">${types.map((type) => `<option ${type === definition.type ? 'selected' : ''}>${type}</option>`).join('')}</select></div>
      <div class="compact-grid"><input data-input-value="${escapeHTML(name)}" value="${escapeHTML(formatInputValue(state.inputs[name]))}" placeholder="Value"><label class="check-row"><input data-input-required="${escapeHTML(name)}" type="checkbox" ${definition.required === false ? '' : 'checked'}>Required</label></div>
    </section>`).join('') || '<div class="empty-state">No graph inputs</div>';
  $$('[data-remove-input]').forEach((button) => button.addEventListener('click', () => removeInput(button.dataset.removeInput)));
  $$('[data-input-id]').forEach((control) => control.addEventListener('change', () => renameInput(control.dataset.inputId, control.value)));
  $$('[data-input-type]').forEach((control) => control.addEventListener('change', () => {
    state.graph.inputs[control.dataset.inputType].type = control.value;
  }));
  $$('[data-input-required]').forEach((control) => control.addEventListener('change', () => {
    state.graph.inputs[control.dataset.inputRequired].required = control.checked;
  }));
  $$('[data-input-value]').forEach((control) => control.addEventListener('input', () => {
    const type = state.graph.inputs[control.dataset.inputValue].type;
    state.inputs[control.dataset.inputValue] = parseInputValue(control.value, type);
  }));
}

function formatInputValue(value) {
  if (typeof value === 'object' && value !== null) return JSON.stringify(value);
  return value ?? '';
}

function parseInputValue(value, type) {
  if (type === 'integer') return Number.parseInt(value, 10);
  if (type === 'number') return Number.parseFloat(value);
  if (type === 'boolean') return value === 'true';
  if (type === 'json' || type === 'asset_collection') {
    try { return JSON.parse(value); } catch { return value; }
  }
  return value;
}

function addInput() {
  const name = uniqueId('input', new Set(Object.keys(state.graph.inputs)));
  state.graph.inputs[name] = { type: 'string', required: true };
  state.inputs[name] = '';
  renderInputs();
  renderInspector();
}

function renameInput(oldName, desired) {
  if (!/^[a-z][a-z0-9-]{0,63}$/.test(desired) || (desired !== oldName && state.graph.inputs[desired])) {
    renderInputs();
    return;
  }
  state.graph.inputs[desired] = state.graph.inputs[oldName];
  state.inputs[desired] = state.inputs[oldName];
  delete state.graph.inputs[oldName];
  delete state.inputs[oldName];
  for (const node of state.graph.nodes) node.arguments = replaceReference(node.arguments, `inputs.${oldName}`, `inputs.${desired}`);
  renderAll();
}

function removeInput(name) {
  delete state.graph.inputs[name];
  delete state.inputs[name];
  renderAll();
}

function renderJSON() {
  $('#graph-json').value = JSON.stringify(state.graph, null, 2);
}

function applyJSON() {
  try {
    const graph = JSON.parse($('#graph-json').value);
    if (graph.kind !== 'mere.run/workflow-graph' || graph.schema_version !== 1) throw new Error('Expected a Workflow Graph V1 document.');
    state.graph = graph;
    state.selectedNode = null;
    for (const [index, node] of state.graph.nodes.entries()) nodePosition(node.id, index);
    showDiagnostics([], 'JSON applied');
    renderAll();
  } catch (error) {
    showDiagnostics([{ severity: 'blocker', title: 'JSON not applied', message: error.message }], 'JSON blocked');
  }
}

function renderView() {
  ['canvas', 'json', 'runs'].forEach((view) => {
    $(`#${view}-view`).classList.toggle('hidden', state.view !== view);
    $(`[data-view="${view}"]`).classList.toggle('active', state.view === view);
  });
  $('#canvas-tools').classList.toggle('hidden', state.view !== 'canvas');
  if (state.view === 'json') renderJSON();
  if (state.view === 'runs') refreshRuns();
}

function renderAll() {
  $('#project-label').textContent = state.graph.name;
  renderCatalog();
  renderInputs();
  renderCanvas();
  renderInspector();
  renderView();
}

function showDiagnostics(diagnostics, title = 'Results') {
  const values = diagnostics || [];
  $('#diagnostics').innerHTML = values.map((item) => `
    <div class="diagnostic ${escapeHTML(item.severity || 'info')}">
      <span class="diagnostic-icon">${item.severity === 'blocker' ? '!' : item.severity === 'warning' ? '△' : 'i'}</span>
      <span><b>${escapeHTML(item.title || item.id || 'Diagnostic')}</b><span>${escapeHTML(item.message || '')}</span></span>
    </div>`).join('') || '<div class="empty-state">No diagnostics</div>';
  $('#drawer-title').textContent = title;
  $('#drawer-count').textContent = `${values.length} item${values.length === 1 ? '' : 's'}`;
  const blocked = values.some((item) => item.severity === 'blocker');
  $('#drawer-state-dot').className = blocked ? 'failed' : 'finished';
  $('#result-drawer').classList.remove('collapsed');
}

async function checkGraph(mode) {
  try {
    const document = await api('/api/check', {
      method: 'POST',
      body: JSON.stringify({ mode, graph: state.graph, inputs: state.inputs, executor: $('#executor-select').value }),
    });
    const envelope = commandPayload(document);
    state.diagnosticDocument = envelope;
    showDiagnostics(envelope?.diagnostics || [], envelope?.summary || (mode === 'validate' ? 'Validation complete' : 'Preflight complete'));
  } catch (error) {
    showDiagnostics([{ severity: 'blocker', title: 'Request failed', message: error.message }], 'Check failed');
  }
}

async function saveProject(path = null) {
  const target = path || $('#save-path').value.trim();
  try {
    await api('/api/project', {
      method: 'POST',
      body: JSON.stringify({ path: target, graph: state.graph, inputs: state.inputs, sidecar: state.sidecar }),
    });
    state.projectPath = target;
    $('#save-dialog').close();
    showDiagnostics([], 'Workflow saved');
  } catch (error) {
    showDiagnostics([{ severity: 'blocker', title: 'Save failed', message: error.message }], 'Save failed');
  }
}

async function openProjects() {
  try {
    const document = await api('/api/projects');
    $('#project-list').innerHTML = document.projects.map((project) => `
      <button class="project-row" data-open-project="${escapeHTML(project.path)}"><span><b>${escapeHTML(project.name)}</b><span>${escapeHTML(project.path)}</span></span><time>${new Date(project.modified_at).toLocaleDateString()}</time></button>`).join('') || '<div class="empty-state">No saved workflows</div>';
    $$('[data-open-project]').forEach((button) => button.addEventListener('click', () => loadProject(button.dataset.openProject)));
    $('#open-dialog').showModal();
  } catch (error) {
    showDiagnostics([{ severity: 'blocker', title: 'Open failed', message: error.message }], 'Open failed');
  }
}

async function loadProject(path) {
  try {
    const document = await api(`/api/project?path=${encodeURIComponent(path)}`);
    state.graph = document.graph;
    state.inputs = document.inputs;
    state.sidecar = document.sidecar;
    state.projectPath = path;
    state.selectedNode = null;
    $('#open-dialog').close();
    renderAll();
  } catch (error) {
    showDiagnostics([{ severity: 'blocker', title: 'Open failed', message: error.message }], 'Open failed');
  }
}

async function startRun() {
  try {
    const run = await api('/api/runs', {
      method: 'POST',
      body: JSON.stringify({ graph: state.graph, inputs: state.inputs, executor: $('#executor-select').value }),
    });
    state.selectedRun = run.id;
    state.view = 'runs';
    renderView();
    await refreshRuns();
  } catch (error) {
    showDiagnostics([{ severity: 'blocker', title: 'Run failed to start', message: error.message }], 'Run failed');
  }
}

async function refreshRuns() {
  try {
    const document = await api('/api/runs');
    state.runs = document.runs;
    renderRuns();
    if (state.selectedRun) await loadRunDetail(state.selectedRun, false);
  } catch (error) {
    $('#run-list').innerHTML = `<div class="empty-state">${escapeHTML(error.message)}</div>`;
  }
}

function renderRuns() {
  $('#run-list').innerHTML = state.runs.map((run) => `
    <button class="run-row ${state.selectedRun === run.id ? 'active' : ''}" data-run-id="${escapeHTML(run.id)}">
      <span class="state-dot ${escapeHTML(run.state)}"></span><span><b>${escapeHTML(run.executor)}</b><small>${escapeHTML(run.state)} · ${escapeHTML(run.id)}</small></span><time>${new Date(run.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time>
    </button>`).join('') || '<div class="empty-state">No runs</div>';
  $$('[data-run-id]').forEach((button) => button.addEventListener('click', () => loadRunDetail(button.dataset.runId, true)));
}

async function loadRunDetail(id, rerenderList = true) {
  state.selectedRun = id;
  if (rerenderList) renderRuns();
  try {
    const run = await api(`/api/runs/${encodeURIComponent(id)}`);
    const events = run.events || [];
    $('#run-detail').innerHTML = `
      <div class="run-summary"><h2>${escapeHTML(run.executor)}</h2><span class="status-pill ${escapeHTML(run.state)}">${escapeHTML(run.state)}</span>${['running', 'queued', 'submitting'].includes(run.state) ? '<button class="command-button danger" data-cancel-run>Cancel</button>' : ''}</div>
      <div class="field"><span class="field-label">Run directory</span><code>${escapeHTML(run.run_directory)}</code></div>
      ${run.remote_reference ? `<div class="field"><span class="field-label">Remote reference</span><code>${escapeHTML(run.remote_reference)}</code></div>` : ''}
      <section><h3>Events</h3><div class="event-list">${events.map((event) => `<div class="event-row"><span>#${escapeHTML(event.sequence ?? '')}</span><b>${escapeHTML(event.type || '')}</b><span>${escapeHTML(event.message || event.phase || event.state || '')}</span></div>`).join('') || '<div class="empty-state">No events yet</div>'}</div></section>
      ${(run.stderr || run.result) ? `<section><h3>Result</h3><pre class="run-json">${escapeHTML(JSON.stringify({ result: run.result, stderr: run.stderr }, null, 2))}</pre></section>` : ''}`;
    $('[data-cancel-run]')?.addEventListener('click', async () => {
      await api(`/api/runs/${encodeURIComponent(id)}/cancel`, { method: 'POST', body: '{}' });
      await refreshRuns();
    });
  } catch (error) {
    $('#run-detail').innerHTML = `<div class="empty-state">${escapeHTML(error.message)}</div>`;
  }
}

function zoom(delta) {
  const viewport = state.sidecar.viewport;
  viewport.zoom = Math.max(0.4, Math.min(1.8, (viewport.zoom || 1) + delta));
  applyViewport();
}

function fitGraph() {
  if (!state.graph.nodes.length) return;
  const positions = state.graph.nodes.map((node) => nodePosition(node.id));
  const minX = Math.min(...positions.map((position) => position.x));
  const minY = Math.min(...positions.map((position) => position.y));
  const maxX = Math.max(...positions.map((position) => position.x + 230));
  const maxY = Math.max(...positions.map((position) => position.y + 110));
  const bounds = $('#canvas-view').getBoundingClientRect();
  const zoomValue = Math.max(0.4, Math.min(1.2, Math.min((bounds.width - 80) / (maxX - minX), (bounds.height - 80) / (maxY - minY))));
  state.sidecar.viewport = { zoom: zoomValue, x: 40 - minX * zoomValue, y: 40 - minY * zoomValue };
  applyViewport();
}

function newWorkflow() {
  state.graph = DEFAULT_GRAPH();
  state.inputs = {};
  state.sidecar = DEFAULT_SIDECAR();
  state.selectedNode = null;
  state.projectPath = null;
  renderAll();
}

function bindActions() {
  document.addEventListener('click', (event) => {
    const action = event.target.closest('[data-action]')?.dataset.action;
    if (!action) return;
    const actions = {
      new: newWorkflow,
      open: openProjects,
      save: () => {
        if (state.projectPath) saveProject(state.projectPath);
        else { $('#save-path').value = `workflows/${state.graph.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'workflow'}`; $('#save-dialog').showModal(); }
      },
      validate: () => checkGraph('validate'),
      preflight: () => checkGraph('preflight'),
      run: startRun,
      'add-input': addInput,
      'apply-json': applyJSON,
      'toggle-drawer': () => $('#result-drawer').classList.toggle('collapsed'),
      'zoom-in': () => zoom(0.1),
      'zoom-out': () => zoom(-0.1),
      fit: fitGraph,
      'focus-catalog': () => $('#catalog-search').focus(),
      'close-open': () => $('#open-dialog').close(),
    };
    actions[action]?.();
  });
  $$('[data-view]').forEach((button) => button.addEventListener('click', () => { state.view = button.dataset.view; renderView(); }));
  $$('[data-library-tab]').forEach((button) => button.addEventListener('click', () => {
    state.libraryTab = button.dataset.libraryTab;
    $$('[data-library-tab]').forEach((item) => item.classList.toggle('active', item === button));
    $('#node-library').classList.toggle('hidden', state.libraryTab !== 'nodes');
    $('#input-library').classList.toggle('hidden', state.libraryTab !== 'inputs');
  }));
  $('#catalog-search').addEventListener('input', renderCatalog);
  $('#canvas-view').addEventListener('click', (event) => {
    if (event.target.closest('.graph-node')) return;
    state.selectedNode = null;
    renderCanvas();
    renderInspector();
  });
  $('#canvas-view').addEventListener('pointerdown', (event) => {
    if (event.button !== 0 || event.target.closest('.graph-node') || event.target.closest('button')) return;
    const viewport = state.sidecar.viewport;
    const start = { clientX: event.clientX, clientY: event.clientY, x: viewport.x || 0, y: viewport.y || 0 };
    const move = (moveEvent) => {
      viewport.x = start.x + moveEvent.clientX - start.clientX;
      viewport.y = start.y + moveEvent.clientY - start.clientY;
      applyViewport();
    };
    const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  });
  $('#confirm-save').addEventListener('click', (event) => { event.preventDefault(); saveProject(); });
}

function collectExecutorReferences(value, found = new Set()) {
  if (Array.isArray(value)) value.forEach((item) => collectExecutorReferences(item, found));
  else if (value && typeof value === 'object') {
    if (typeof value.name === 'string' && ['ssh', 'relay'].includes(value.kind)) found.add(`${value.kind}:${value.name}`);
    Object.values(value).forEach((item) => collectExecutorReferences(item, found));
  }
  return found;
}

async function initialize() {
  bindActions();
  try {
    const [catalogDocument, executorDocument] = await Promise.all([api('/api/catalog'), api('/api/executors')]);
    const catalog = commandPayload(catalogDocument);
    state.catalog = catalog?.nodes || [];
    state.executors = ['local', ...collectExecutorReferences(commandPayload(executorDocument))];
    $('#executor-select').innerHTML = state.executors.map((executor) => `<option>${escapeHTML(executor)}</option>`).join('');
    $('#health').classList.add('ready');
    $('#health b').textContent = `${state.catalog.length} nodes`;
  } catch (error) {
    $('#health').classList.add('error');
    $('#health b').textContent = 'CLI unavailable';
    showDiagnostics([{ severity: 'blocker', title: 'Catalog unavailable', message: error.message }], 'Studio blocked');
  }
  renderAll();
  setInterval(() => {
    if (state.runs.some((run) => ['starting', 'running', 'submitting', 'queued'].includes(run.state))) refreshRuns();
  }, 1500);
}

initialize();
