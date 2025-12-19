/**
 * Tmux Control Panel v4 - Main Application
 * 
 * Modular terminal manager with configurable layouts and X11 GUI support.
 */

// ============================================================================
// State Management
// ============================================================================

const state = {
    socket: null,
    terminal: null,
    fitAddon: null,
    
    // Configuration
    config: {
        tmuxSocket: 'control-panel',
        sessionPrefix: 'cp-'
    },
    
    // Sessions
    sessions: [],
    currentSession: null,
    customCommands: {},
    inCopyMode: false,
    
    // X11 Displays
    displays: [],
    
    // Layout: 'terminals-only', 'split-1', 'split-2', 'split-3'
    layout: 'terminals-only',
    
    // GUI Panels - persist connections across layout changes
    guiPanels: [
        { displayNum: null, rfb: null, visible: false },
        { displayNum: null, rfb: null, visible: false },
        { displayNum: null, rfb: null, visible: false }
    ],
    
    // Panel sizes (percentages)
    panelSizes: {
        terminal: 50,
        gui: [50, 50, 50]
    },
    
    // Resizing state
    resizing: {
        active: false,
        startX: 0,
        startY: 0,
        startSize: 0,
        element: null,
        direction: 'horizontal'
    }
};

// ============================================================================
// DOM Elements
// ============================================================================

const dom = {};

function cacheDomElements() {
    dom.statusDot = document.getElementById('statusDot');
    dom.statusText = document.getElementById('statusText');
    dom.socketInput = document.getElementById('socketInput');
    dom.prefixInput = document.getElementById('prefixInput');
    dom.sessionList = document.getElementById('sessionList');
    dom.displayList = document.getElementById('displayList');
    dom.workspace = document.getElementById('workspace');
    dom.workspaceContent = document.getElementById('workspaceContent');
    dom.terminalPanel = document.getElementById('terminalPanel');
    dom.terminalTitle = document.getElementById('terminalTitle');
    dom.terminalContainer = document.getElementById('terminalContainer');
    dom.terminalPlaceholder = document.getElementById('terminalPlaceholder');
    dom.terminalBody = document.getElementById('terminalBody');
    dom.quickCommands = document.getElementById('quickCommands');
    dom.guiPanels = [
        document.getElementById('guiPanel1'),
        document.getElementById('guiPanel2'),
        document.getElementById('guiPanel3')
    ];
    dom.newSessionModal = document.getElementById('newSessionModal');
    dom.newDisplayModal = document.getElementById('newDisplayModal');
    dom.addCommandModal = document.getElementById('addCommandModal');
    dom.bindDisplayModal = document.getElementById('bindDisplayModal');
}

// ============================================================================
// Configuration
// ============================================================================

async function loadConfig() {
    try {
        const response = await fetch('/api/config');
        const config = await response.json();
        state.config.tmuxSocket = config.tmux_socket;
        state.config.sessionPrefix = config.session_prefix;
        dom.socketInput.value = config.tmux_socket;
        dom.prefixInput.value = config.session_prefix;
    } catch (error) {
        console.error('Failed to load config:', error);
    }
}

async function saveConfig() {
    const tmuxSocket = dom.socketInput.value.trim();
    const sessionPrefix = dom.prefixInput.value.trim();
    if (!tmuxSocket || !sessionPrefix) return;
    
    try {
        await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tmux_socket: tmuxSocket, session_prefix: sessionPrefix })
        });
        state.config.tmuxSocket = tmuxSocket;
        state.config.sessionPrefix = sessionPrefix;
        await refreshSessions();
    } catch (error) {
        console.error('Failed to save config:', error);
    }
}

// ============================================================================
// WebSocket Connection
// ============================================================================

function connectWebSocket() {
    updateStatus('connecting');
    
    state.socket = io({
        transports: ['websocket'],
        reconnection: true,
        reconnectionDelay: 1000,
        reconnectionAttempts: 10
    });
    
    state.socket.on('connect', () => {
        console.log('WebSocket connected');
        updateStatus('connected');
        refreshSessions();
        refreshDisplays();
    });
    
    state.socket.on('disconnect', () => {
        console.log('WebSocket disconnected');
        updateStatus('disconnected');
    });
    
    state.socket.on('connect_error', (err) => {
        console.error('WebSocket connection error:', err);
        updateStatus('error');
    });
    
    state.socket.on('subscribed', (data) => {
        console.log('Subscribed to session:', data.session);
        if (state.terminal) {
            state.terminal.clear();
            state.terminal.reset();
        }
        setTimeout(() => {
            if (state.socket && state.socket.connected && state.terminal) {
                state.socket.emit('resize', {
                    session: data.session,
                    cols: state.terminal.cols,
                    rows: state.terminal.rows
                });
            }
        }, 100);
    });
    
    state.socket.on('output', (data) => {
        if (state.terminal && data.session === state.currentSession) {
            state.terminal.write(data.data);
        }
    });
    
    state.socket.on('error', (data) => {
        console.error('Server error:', data.message);
    });
}

function updateStatus(status) {
    dom.statusDot.className = 'status-dot';
    const statusMap = {
        'connected': ['status-dot--connected', 'Connected'],
        'connecting': ['status-dot--connecting', 'Connecting...'],
        'disconnected': [null, 'Disconnected'],
        'error': [null, 'Error']
    };
    const [cls, text] = statusMap[status] || [null, status];
    if (cls) dom.statusDot.classList.add(cls);
    dom.statusText.textContent = text;
}

// ============================================================================
// Terminal Setup
// ============================================================================

function initTerminal() {
    state.terminal = new Terminal({
        cursorBlink: true,
        cursorStyle: 'block',
        fontSize: 14,
        fontFamily: '"JetBrains Mono", "Fira Code", Consolas, monospace',
        scrollback: 50000,
        theme: {
            background: '#080a0d',
            foreground: '#d4dae4',
            cursor: '#4ecca3',
            cursorAccent: '#080a0d',
            selection: 'rgba(74, 158, 255, 0.3)',
            black: '#1a1e25',
            red: '#ff6b6b',
            green: '#3dd68c',
            yellow: '#ff9f43',
            blue: '#4a9eff',
            magenta: '#a78bfa',
            cyan: '#22d3ee',
            white: '#d4dae4',
            brightBlack: '#5a6474',
            brightRed: '#ff8787',
            brightGreen: '#4ee09a',
            brightYellow: '#ffb366',
            brightBlue: '#6cb4ff',
            brightMagenta: '#b8a3fb',
            brightCyan: '#44e5f5',
            brightWhite: '#ffffff'
        }
    });
    
    state.fitAddon = new FitAddon.FitAddon();
    state.terminal.loadAddon(state.fitAddon);
    state.terminal.loadAddon(new WebLinksAddon.WebLinksAddon());
    
    state.terminal.onData((data) => {
        if (state.currentSession && state.socket && state.socket.connected) {
            // If in copy mode, exit it first but don't send 'q' - just send the actual key
            // The terminal input will naturally exit copy-mode in tmux
            if (state.inCopyMode) {
                state.inCopyMode = false;
                // Send Escape to exit copy-mode cleanly, then send the actual key
                state.socket.emit('input', { session: state.currentSession, keys: '\x1b' });
                setTimeout(() => {
                    state.socket.emit('input', { session: state.currentSession, keys: data });
                }, 10);
            } else {
                state.socket.emit('input', { session: state.currentSession, keys: data });
            }
        }
    });
    
    state.terminal.onResize(({ cols, rows }) => {
        if (state.currentSession && state.socket && state.socket.connected) {
            state.socket.emit('resize', { session: state.currentSession, cols, rows });
        }
    });
}

function attachTerminal() {
    dom.terminalContainer.innerHTML = '';
    state.terminal.open(dom.terminalContainer);
    state.terminal.clear();
    
    dom.terminalContainer.addEventListener('wheel', (e) => {
        e.preventDefault();
        if (!state.currentSession || !state.socket || !state.socket.connected) return;
        
        const scrollUp = e.deltaY < 0;
        const lines = Math.max(1, Math.abs(Math.round(e.deltaY / 30)));
        
        if (scrollUp) {
            if (!state.inCopyMode) {
                state.socket.emit('scroll', { session: state.currentSession, command: 'enter' });
                state.inCopyMode = true;
                setTimeout(() => state.socket.emit('scroll', { session: state.currentSession, command: 'up', lines }), 50);
            } else {
                state.socket.emit('scroll', { session: state.currentSession, command: 'up', lines });
            }
        } else if (state.inCopyMode) {
            state.socket.emit('scroll', { session: state.currentSession, command: 'down', lines });
        }
    }, { passive: false, capture: true });
    
    setTimeout(() => {
        state.fitAddon.fit();
        state.terminal.focus();
    }, 100);
}

// ============================================================================
// Session Management
// ============================================================================

async function refreshSessions() {
    try {
        const response = await fetch('/api/sessions');
        state.sessions = (await response.json()).sessions;
        renderSessionList();
        
        const cmdResponse = await fetch('/api/commands');
        state.customCommands = await cmdResponse.json();
        if (state.currentSession) renderQuickCommands();
    } catch (error) {
        console.error('Failed to refresh sessions:', error);
    }
}

function renderSessionList() {
    if (state.sessions.length === 0) {
        dom.sessionList.innerHTML = '<div class="empty-message">No sessions</div>';
        return;
    }
    
    dom.sessionList.innerHTML = state.sessions.map(session => `
        <div class="session-item ${session === state.currentSession ? 'session-item--active' : ''}" 
             onclick="selectSession('${session}')">
            <span class="session-item__name">${session}</span>
            <div class="session-item__actions">
                <button class="btn btn--danger btn--icon" onclick="event.stopPropagation(); deleteSession('${session}')" title="Delete">×</button>
            </div>
        </div>
    `).join('');
}

async function selectSession(session) {
    if (state.currentSession && state.socket && state.socket.connected) {
        state.socket.emit('unsubscribe', { session: state.currentSession });
    }
    
    state.currentSession = session;
    dom.terminalPlaceholder.style.display = 'none';
    dom.terminalContainer.style.display = 'block';
    dom.terminalTitle.textContent = session;
    
    attachTerminal();
    renderSessionList();
    renderQuickCommands();
    
    setTimeout(() => {
        state.fitAddon.fit();
        if (state.socket && state.socket.connected) {
            state.socket.emit('subscribe', {
                session: session,
                cols: state.terminal.cols,
                rows: state.terminal.rows
            });
        }
    }, 150);
}

async function createSession() {
    const name = document.getElementById('sessionName').value.trim();
    const cwd = document.getElementById('sessionCwd').value.trim();
    const cmd = document.getElementById('sessionCmd').value.trim();
    
    if (!name) { alert('Please enter a session name'); return; }
    
    try {
        const response = await fetch('/api/sessions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, cwd: cwd || undefined, command: cmd || undefined })
        });
        const data = await response.json();
        
        if (data.status === 'ok') {
            hideModal('newSessionModal');
            await refreshSessions();
            selectSession(data.session);
        } else {
            alert('Failed: ' + data.message);
        }
    } catch (error) {
        console.error('Failed to create session:', error);
    }
}

async function deleteSession(session) {
    if (!confirm(`Delete session "${session}"?`)) return;
    
    try {
        await fetch(`/api/sessions/${session}`, { method: 'DELETE' });
        if (state.currentSession === session) {
            state.currentSession = null;
            dom.terminalPlaceholder.style.display = 'flex';
            dom.terminalContainer.style.display = 'none';
        }
        await refreshSessions();
    } catch (error) {
        console.error('Failed to delete session:', error);
    }
}

// ============================================================================
// Terminal Actions
// ============================================================================

function sendSignal(sig) {
    if (state.currentSession && state.socket && state.socket.connected) {
        state.socket.emit('signal', { session: state.currentSession, signal: sig });
    }
}

function clearTerminal() {
    if (state.currentSession && state.socket && state.socket.connected) {
        state.socket.emit('input', { session: state.currentSession, keys: 'clear\r' });
    }
}

// ============================================================================
// Quick Commands
// ============================================================================

function renderQuickCommands() {
    const commands = state.customCommands[state.currentSession] || [];
    
    dom.quickCommands.innerHTML = `
        <span class="quick-commands__label">Quick:</span>
        ${commands.map((cmd, i) => `
            <button class="btn btn--secondary btn--sm" onclick="runCommand('${escapeHtml(cmd.command)}')">${escapeHtml(cmd.label)}</button>
            <button class="btn btn--danger btn--sm" onclick="deleteCommand(${i})">×</button>
        `).join('')}
        <button class="btn btn--secondary btn--sm" onclick="showModal('addCommandModal')">+ Add</button>
    `;
}

async function runCommand(command) {
    if (!state.currentSession) return;
    try {
        await fetch(`/api/sessions/${state.currentSession}/command`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ command })
        });
    } catch (error) {
        console.error('Failed to run command:', error);
    }
}

async function addCommand() {
    const label = document.getElementById('cmdLabel').value.trim();
    const command = document.getElementById('cmdCommand').value.trim();
    
    if (!label || !command || !state.currentSession) { alert('Fill all fields'); return; }
    
    try {
        const response = await fetch(`/api/commands/${state.currentSession}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ label, command })
        });
        const data = await response.json();
        if (data.status === 'ok') {
            state.customCommands[state.currentSession] = data.commands;
            renderQuickCommands();
            hideModal('addCommandModal');
        }
    } catch (error) {
        console.error('Failed to add command:', error);
    }
}

async function deleteCommand(index) {
    if (!state.currentSession) return;
    try {
        const response = await fetch(`/api/commands/${state.currentSession}/${index}`, { method: 'DELETE' });
        const data = await response.json();
        if (data.status === 'ok') {
            state.customCommands[state.currentSession] = data.commands;
            renderQuickCommands();
        }
    } catch (error) {
        console.error('Failed to delete command:', error);
    }
}

// ============================================================================
// X11 Display Management
// ============================================================================

async function refreshDisplays() {
    try {
        const response = await fetch('/api/x11/displays');
        state.displays = (await response.json()).displays || [];
        renderDisplayList();
    } catch (error) {
        console.error('Failed to refresh displays:', error);
    }
}

function renderDisplayList() {
    if (state.displays.length === 0) {
        dom.displayList.innerHTML = '<div class="empty-message">No displays</div>';
        return;
    }
    
    dom.displayList.innerHTML = state.displays.map(d => `
        <div class="display-item">
            <div class="display-item__info">
                <span class="display-item__label">${d.display}</span>
                <span class="display-item__size">${d.width}×${d.height} • Port ${d.ws_port}</span>
            </div>
            <button class="btn btn--danger btn--icon" onclick="deleteDisplay(${d.display_num})" title="Stop">×</button>
        </div>
    `).join('');
}

async function createDisplay() {
    const displayNum = parseInt(document.getElementById('displayNum').value) || null;
    const width = parseInt(document.getElementById('displayWidth').value) || 1280;
    const height = parseInt(document.getElementById('displayHeight').value) || 800;
    
    try {
        const response = await fetch('/api/x11/displays', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ display_num: displayNum, width, height })
        });
        const data = await response.json();
        
        if (data.status === 'error') {
            if (data.message.includes('Missing dependencies')) {
                alert('GUI requires X11 packages:\n\nsudo apt install xvfb x11vnc websockify');
            } else {
                alert('Failed: ' + data.message);
            }
            return;
        }
        
        hideModal('newDisplayModal');
        await refreshDisplays();
    } catch (error) {
        console.error('Failed to create display:', error);
    }
}

async function deleteDisplay(displayNum) {
    if (!confirm('Stop display :' + displayNum + '?')) return;
    
    try {
        await fetch('/api/x11/displays/' + displayNum, { method: 'DELETE' });
        
        // Disconnect any GUI panels using this display
        state.guiPanels.forEach((panel, i) => {
            if (panel.displayNum === displayNum) {
                disconnectGuiPanel(i);
            }
        });
        
        await refreshDisplays();
    } catch (error) {
        console.error('Failed to delete display:', error);
    }
}

// ============================================================================
// Layout Management
// ============================================================================

function setLayout(layout) {
    state.layout = layout;
    
    // Update layout buttons
    document.querySelectorAll('.layout-btn').forEach(btn => {
        btn.classList.toggle('layout-btn--active', btn.dataset.layout === layout);
    });
    
    // Clear resizers first
    document.querySelectorAll('.resizer').forEach(r => r.remove());
    
    // Update workspace class
    dom.workspaceContent.className = 'workspace__content';
    
    const guiCount = parseInt(layout.replace('split-', '')) || 0;
    
    if (layout === 'terminals-only') {
        dom.workspaceContent.classList.add('workspace__content--terminals-only');
        // Just hide GUI panels visually, don't disconnect
        state.guiPanels.forEach((_, i) => {
            dom.guiPanels[i].classList.add('gui-panel--hidden');
            state.guiPanels[i].visible = false;
        });
        // Terminal takes full width
        dom.terminalPanel.style.flex = '1';
    } else {
        dom.workspaceContent.classList.add('workspace__content--split-h');
        
        // Show/hide panels based on count
        for (let i = 0; i < 3; i++) {
            if (i < guiCount) {
                dom.guiPanels[i].classList.remove('gui-panel--hidden');
                state.guiPanels[i].visible = true;
            } else {
                dom.guiPanels[i].classList.add('gui-panel--hidden');
                state.guiPanels[i].visible = false;
            }
        }
        
        // Add resizers between panels
        addResizers(guiCount);
        
        // Set initial sizes
        applyPanelSizes(guiCount);
    }
    
    // Refit terminal
    setTimeout(() => {
        if (state.fitAddon) state.fitAddon.fit();
    }, 100);
}

function addResizers(guiCount) {
    // Add resizer after terminal panel
    const resizer1 = document.createElement('div');
    resizer1.className = 'resizer resizer--horizontal';
    resizer1.dataset.index = '0';
    dom.terminalPanel.after(resizer1);
    
    // Add resizers between GUI panels
    for (let i = 0; i < guiCount - 1; i++) {
        const resizer = document.createElement('div');
        resizer.className = 'resizer resizer--horizontal';
        resizer.dataset.index = String(i + 1);
        dom.guiPanels[i].after(resizer);
    }
    
    // Setup resizer event handlers
    setupResizers();
}

function applyPanelSizes(guiCount) {
    const totalPanels = 1 + guiCount;
    const equalSize = 100 / totalPanels;
    
    dom.terminalPanel.style.flex = '0 0 ' + state.panelSizes.terminal + '%';
    
    for (let i = 0; i < guiCount; i++) {
        dom.guiPanels[i].style.flex = '0 0 ' + (state.panelSizes.gui[i] || equalSize) + '%';
    }
}

function setupResizers() {
    document.querySelectorAll('.resizer').forEach(resizer => {
        resizer.addEventListener('mousedown', startResize);
    });
}

function startResize(e) {
    e.preventDefault();
    
    const resizer = e.target;
    const index = parseInt(resizer.dataset.index);
    
    // Determine which panels we're resizing between
    let leftPanel, rightPanel;
    if (index === 0) {
        leftPanel = dom.terminalPanel;
        // Find first visible GUI panel
        rightPanel = dom.guiPanels.find((p, i) => state.guiPanels[i].visible);
    } else {
        leftPanel = dom.guiPanels[index - 1];
        rightPanel = dom.guiPanels[index];
    }
    
    if (!leftPanel || !rightPanel) return;
    
    const containerRect = dom.workspaceContent.getBoundingClientRect();
    const leftRect = leftPanel.getBoundingClientRect();
    const rightRect = rightPanel.getBoundingClientRect();
    
    state.resizing = {
        active: true,
        startX: e.clientX,
        leftPanel,
        rightPanel,
        leftStartWidth: leftRect.width,
        rightStartWidth: rightRect.width,
        containerWidth: containerRect.width,
        index
    };
    
    document.body.classList.add('resizing');
    resizer.classList.add('resizer--active');
    
    document.addEventListener('mousemove', doResize);
    document.addEventListener('mouseup', stopResize);
}

function doResize(e) {
    if (!state.resizing.active) return;
    
    const r = state.resizing;
    const delta = e.clientX - r.startX;
    
    const newLeftWidth = r.leftStartWidth + delta;
    const newRightWidth = r.rightStartWidth - delta;
    
    // Minimum sizes
    const minSize = 150;
    if (newLeftWidth < minSize || newRightWidth < minSize) return;
    
    // Convert to percentages
    const leftPercent = (newLeftWidth / r.containerWidth) * 100;
    const rightPercent = (newRightWidth / r.containerWidth) * 100;
    
    r.leftPanel.style.flex = '0 0 ' + leftPercent + '%';
    r.rightPanel.style.flex = '0 0 ' + rightPercent + '%';
    
    // Save sizes
    if (r.index === 0) {
        state.panelSizes.terminal = leftPercent;
        const guiIndex = dom.guiPanels.findIndex(p => p === r.rightPanel);
        if (guiIndex >= 0) state.panelSizes.gui[guiIndex] = rightPercent;
    } else {
        state.panelSizes.gui[r.index - 1] = leftPercent;
        state.panelSizes.gui[r.index] = rightPercent;
    }
    
    // Refit terminal during resize
    if (state.fitAddon) state.fitAddon.fit();
}

function stopResize() {
    if (!state.resizing.active) return;
    
    state.resizing.active = false;
    document.body.classList.remove('resizing');
    document.querySelectorAll('.resizer--active').forEach(r => r.classList.remove('resizer--active'));
    
    document.removeEventListener('mousemove', doResize);
    document.removeEventListener('mouseup', stopResize);
    
    // Final terminal fit
    setTimeout(() => {
        if (state.fitAddon) state.fitAddon.fit();
    }, 50);
}

// ============================================================================
// GUI Panel VNC Connection
// ============================================================================

async function connectGuiPanel(panelIndex, displayNum) {
    const display = state.displays.find(d => d.display_num === displayNum);
    if (!display) {
        alert('Display :' + displayNum + ' not found. Create it first.');
        return;
    }
    
    // Disconnect existing connection for this panel
    if (state.guiPanels[panelIndex].rfb) {
        state.guiPanels[panelIndex].rfb.disconnect();
        state.guiPanels[panelIndex].rfb = null;
    }
    
    state.guiPanels[panelIndex].displayNum = displayNum;
    
    const panel = dom.guiPanels[panelIndex];
    const body = panel.querySelector('.gui-panel__body');
    const titleSpan = panel.querySelector('.gui-panel__display-num');
    
    titleSpan.textContent = ':' + displayNum;
    body.innerHTML = '<div style="color: var(--text-muted);">Connecting...</div>';
    
    try {
        const RFB = (await import('https://cdn.jsdelivr.net/npm/@novnc/novnc@1.4.0/core/rfb.js')).default;
        const wsUrl = 'ws://' + window.location.hostname + ':' + display.ws_port;
        
        body.innerHTML = '';
        const rfb = new RFB(body, wsUrl, { scaleViewport: true, resizeSession: false });
        
        rfb.addEventListener('connect', () => console.log('GUI Panel ' + (panelIndex + 1) + ' connected to :' + displayNum));
        rfb.addEventListener('disconnect', () => console.log('GUI Panel ' + (panelIndex + 1) + ' disconnected'));
        
        state.guiPanels[panelIndex].rfb = rfb;
    } catch (error) {
        console.error('VNC connection failed:', error);
        body.innerHTML = '<div style="color: var(--accent-red);">Connection failed</div>';
    }
}

function disconnectGuiPanel(panelIndex) {
    const panelState = state.guiPanels[panelIndex];
    if (panelState.rfb) {
        panelState.rfb.disconnect();
        panelState.rfb = null;
    }
    panelState.displayNum = null;
    
    const panel = dom.guiPanels[panelIndex];
    if (panel) {
        const body = panel.querySelector('.gui-panel__body');
        const titleSpan = panel.querySelector('.gui-panel__display-num');
        titleSpan.textContent = 'Not connected';
        body.innerHTML = '<div class="gui-panel__placeholder"><div class="gui-panel__placeholder-icon">🖼️</div><div class="gui-panel__placeholder-text">Click "Connect" to attach a display</div></div>';
    }
}

function showConnectDisplayModal(panelIndex) {
    window.currentConnectPanelIndex = panelIndex;
    
    const select = document.getElementById('connectDisplaySelect');
    select.innerHTML = state.displays.map(d => 
        '<option value="' + d.display_num + '">' + d.display + ' (' + d.width + '×' + d.height + ')</option>'
    ).join('');
    
    if (state.displays.length === 0) {
        select.innerHTML = '<option disabled>No displays available</option>';
    }
    
    showModal('bindDisplayModal');
}

function connectSelectedDisplay() {
    const panelIndex = window.currentConnectPanelIndex;
    const displayNum = parseInt(document.getElementById('connectDisplaySelect').value);
    
    if (isNaN(displayNum)) {
        alert('Select a display first');
        return;
    }
    
    connectGuiPanel(panelIndex, displayNum);
    hideModal('bindDisplayModal');
}

// ============================================================================
// Bind Display to Session
// ============================================================================

async function bindDisplayToSession(displayNum) {
    if (!state.currentSession) {
        alert('Select a session first');
        return;
    }
    
    if (!displayNum) {
        alert('Connect this panel to a display first');
        return;
    }
    
    try {
        const response = await fetch('/api/sessions/' + state.currentSession + '/bind-display', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ display_num: displayNum })
        });
        const data = await response.json();
        
        if (data.status === 'ok') {
            alert('Display :' + displayNum + ' bound to ' + state.currentSession + '\nDISPLAY variable is now set.');
        } else {
            alert('Failed: ' + data.message);
        }
    } catch (error) {
        console.error('Failed to bind display:', error);
    }
}

// ============================================================================
// Modal Helpers
// ============================================================================

function showModal(id) {
    document.getElementById(id).classList.add('modal-overlay--visible');
    const firstInput = document.querySelector('#' + id + ' input');
    if (firstInput) setTimeout(() => firstInput.focus(), 100);
}

function hideModal(id) {
    document.getElementById(id).classList.remove('modal-overlay--visible');
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ============================================================================
// Event Listeners
// ============================================================================

function setupEventListeners() {
    // Config inputs
    dom.socketInput.addEventListener('change', saveConfig);
    dom.prefixInput.addEventListener('change', saveConfig);
    
    // Window resize
    window.addEventListener('resize', () => {
        if (state.fitAddon) state.fitAddon.fit();
    });
    
    // Modal Enter keys
    document.getElementById('sessionName').addEventListener('keydown', e => {
        if (e.key === 'Enter') createSession();
    });
    document.getElementById('cmdCommand').addEventListener('keydown', e => {
        if (e.key === 'Enter') addCommand();
    });
    
    // Close modals on overlay click
    document.querySelectorAll('.modal-overlay').forEach(overlay => {
        overlay.addEventListener('click', e => {
            if (e.target === overlay) overlay.classList.remove('modal-overlay--visible');
        });
    });
    
    // Escape to close modals
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') {
            document.querySelectorAll('.modal-overlay').forEach(o => o.classList.remove('modal-overlay--visible'));
        }
    });
    
    // Layout buttons
    document.querySelectorAll('.layout-btn').forEach(btn => {
        btn.addEventListener('click', () => setLayout(btn.dataset.layout));
    });
}

// ============================================================================
// Initialization
// ============================================================================

document.addEventListener('DOMContentLoaded', () => {
    cacheDomElements();
    initTerminal();
    loadConfig();
    connectWebSocket();
    setupEventListeners();
    setLayout('terminals-only');
});