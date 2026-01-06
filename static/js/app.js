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
    
    config: {
        tmuxSocket: 'control-panel',
        sessionPrefix: 'cp-'
    },
    
    sessions: [],
    currentSession: null,
    customCommands: {},
    inCopyMode: false,
    
    displays: [],
    
    // Layout: 'terminals-only', 'split-1', 'split-2', 'split-3'
    layout: 'terminals-only',
    
    // GUI Panels - persist connections across layout changes
    guiPanels: [
        { displayNum: null, rfb: null, visible: false, detached: false, fullscreen: false },
        { displayNum: null, rfb: null, visible: false, detached: false, fullscreen: false },
        { displayNum: null, rfb: null, visible: false, detached: false, fullscreen: false }
    ],
    
    // Panel sizes (percentages)
    panelSizes: {
        guiContainer: 50,
        terminal: 50,
        guiRows: [33.33, 33.33, 33.33]
    },
    
    // Resizing state
    resizing: {
        active: false,
        type: null, // 'main' or 'gui'
        startPos: 0,
        startSize: 0,
        index: 0
    },
    
    // Dragging state for detached panels
    dragging: {
        active: false,
        panel: null,
        offsetX: 0,
        offsetY: 0
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
    dom.guiContainer = document.getElementById('guiContainer');
    dom.mainResizer = document.getElementById('mainResizer');
    dom.terminalPanel = document.getElementById('terminalPanel');
    dom.terminalTitle = document.getElementById('terminalTitle');
    dom.terminalContainer = document.getElementById('terminalContainer');
    dom.terminalPlaceholder = document.getElementById('terminalPlaceholder');
    dom.terminalBody = document.getElementById('terminalBody');
    dom.quickCommands = document.getElementById('quickCommands');
    dom.fullscreenOverlay = document.getElementById('fullscreenOverlay');
    dom.guiPanels = [
        document.getElementById('guiPanel1'),
        document.getElementById('guiPanel2'),
        document.getElementById('guiPanel3')
    ];
    dom.guiResizers = document.querySelectorAll('.gui-resizer');
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
        allowProposedApi: true,
        macOptionIsMeta: true,
        macOptionClickForcesSelection: true,
        rightClickSelectsWord: true,
        fastScrollModifier: 'alt',
        fastScrollSensitivity: 5,
        scrollSensitivity: 1,
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
    
    // Custom key event handler for special keys
    state.terminal.attachCustomKeyEventHandler((event) => {
        // Let browser handle Ctrl+Shift+C/V for copy/paste
        if (event.ctrlKey && event.shiftKey && (event.key === 'C' || event.key === 'V')) {
            return false;
        }
        // Let browser handle Ctrl+C for copy when text is selected
        if (event.ctrlKey && event.key === 'c' && state.terminal.hasSelection()) {
            return false;
        }
        // Let browser handle Ctrl+V for paste
        if (event.ctrlKey && event.key === 'v') {
            return false;
        }
        return true;
    });
    
    state.terminal.onData((data) => {
        if (state.currentSession && state.socket && state.socket.connected) {
            if (state.inCopyMode) {
                state.inCopyMode = false;
                state.socket.emit('input', { session: state.currentSession, keys: '\x1b' });
                setTimeout(() => {
                    state.socket.emit('input', { session: state.currentSession, keys: data });
                }, 10);
            } else {
                state.socket.emit('input', { session: state.currentSession, keys: data });
            }
        }
    });
    
    // Handle special keys that xterm.js might not send correctly
    state.terminal.onKey(({ key, domEvent }) => {
        if (!state.currentSession || !state.socket || !state.socket.connected) return;
        
        const modifiers = {
            ctrl: domEvent.ctrlKey,
            alt: domEvent.altKey,
            shift: domEvent.shiftKey,
            meta: domEvent.metaKey
        };
        
        let seq = null;
        
        switch (domEvent.key) {
            case 'Home':
                if (modifiers.ctrl) {
                    seq = '\x1b[1;5H'; // Ctrl+Home
                } else if (modifiers.shift) {
                    seq = '\x1b[1;2H'; // Shift+Home
                } else {
                    seq = '\x1b[H'; // Home
                }
                break;
            case 'End':
                if (modifiers.ctrl) {
                    seq = '\x1b[1;5F'; // Ctrl+End
                } else if (modifiers.shift) {
                    seq = '\x1b[1;2F'; // Shift+End
                } else {
                    seq = '\x1b[F'; // End
                }
                break;
            case 'PageUp':
                if (modifiers.shift) {
                    // Shift+PageUp: scroll terminal buffer up
                    if (!state.inCopyMode) {
                        state.socket.emit('scroll', { session: state.currentSession, command: 'enter' });
                        state.inCopyMode = true;
                    }
                    state.socket.emit('scroll', { session: state.currentSession, command: 'page-up' });
                    return;
                } else {
                    seq = '\x1b[5~'; // PageUp
                }
                break;
            case 'PageDown':
                if (modifiers.shift) {
                    // Shift+PageDown: scroll terminal buffer down
                    if (state.inCopyMode) {
                        state.socket.emit('scroll', { session: state.currentSession, command: 'page-down' });
                    }
                    return;
                } else {
                    seq = '\x1b[6~'; // PageDown
                }
                break;
            case 'Insert':
                if (modifiers.shift) {
                    // Shift+Insert: paste (let browser handle)
                    return;
                } else {
                    seq = '\x1b[2~'; // Insert
                }
                break;
            case 'Delete':
                if (modifiers.ctrl) {
                    seq = '\x1b[3;5~'; // Ctrl+Delete
                } else if (modifiers.shift) {
                    seq = '\x1b[3;2~'; // Shift+Delete
                } else {
                    seq = '\x1b[3~'; // Delete
                }
                break;
            case 'F1':
                seq = '\x1bOP';
                break;
            case 'F2':
                seq = '\x1bOQ';
                break;
            case 'F3':
                seq = '\x1bOR';
                break;
            case 'F4':
                seq = '\x1bOS';
                break;
            case 'F5':
                seq = '\x1b[15~';
                break;
            case 'F6':
                seq = '\x1b[17~';
                break;
            case 'F7':
                seq = '\x1b[18~';
                break;
            case 'F8':
                seq = '\x1b[19~';
                break;
            case 'F9':
                seq = '\x1b[20~';
                break;
            case 'F10':
                seq = '\x1b[21~';
                break;
            case 'F11':
                seq = '\x1b[23~';
                break;
            case 'F12':
                seq = '\x1b[24~';
                break;
        }
        
        if (seq) {
            domEvent.preventDefault();
            state.socket.emit('input', { session: state.currentSession, keys: seq });
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
    
    // Mouse wheel scrolling through tmux history
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
    
    // Focus terminal on click
    dom.terminalContainer.addEventListener('click', () => {
        state.terminal.focus();
    });
    
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
    state.inCopyMode = false; // Reset copy mode when switching sessions
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
            document.getElementById('sessionName').value = '';
            document.getElementById('sessionCwd').value = '';
            document.getElementById('sessionCmd').value = '';
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
    if (!confirm('Delete session "' + session + '"?')) return;
    
    try {
        await fetch('/api/sessions/' + session, { method: 'DELETE' });
        if (state.currentSession === session) {
            state.currentSession = null;
            dom.terminalPlaceholder.style.display = 'flex';
            dom.terminalContainer.style.display = 'none';
            dom.terminalTitle.textContent = 'No session selected';
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
        // Send Ctrl+L for clear (works better than 'clear' command)
        state.socket.emit('input', { session: state.currentSession, keys: '\x0c' });
    }
}

// ============================================================================
// Quick Commands
// ============================================================================

function renderQuickCommands() {
    const commands = state.customCommands[state.currentSession] || [];
    
    dom.quickCommands.innerHTML = '<span class="quick-commands__label">Quick:</span>' +
        commands.map((cmd, i) => 
            '<button class="btn btn--secondary btn--sm" onclick="runCommand(\'' + escapeHtml(cmd.command) + '\')">' + escapeHtml(cmd.label) + '</button>' +
            '<button class="btn btn--danger btn--sm" onclick="deleteCommand(' + i + ')">×</button>'
        ).join('') +
        '<button class="btn btn--secondary btn--sm" onclick="showModal(\'addCommandModal\')">+ Add</button>';
}

async function runCommand(command) {
    if (!state.currentSession) return;
    try {
        await fetch('/api/sessions/' + state.currentSession + '/command', {
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
        const response = await fetch('/api/commands/' + state.currentSession, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ label, command })
        });
        const data = await response.json();
        if (data.status === 'ok') {
            state.customCommands[state.currentSession] = data.commands;
            renderQuickCommands();
            hideModal('addCommandModal');
            document.getElementById('cmdLabel').value = '';
            document.getElementById('cmdCommand').value = '';
        }
    } catch (error) {
        console.error('Failed to add command:', error);
    }
}

async function deleteCommand(index) {
    if (!state.currentSession) return;
    try {
        const response = await fetch('/api/commands/' + state.currentSession + '/' + index, { method: 'DELETE' });
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
    
    dom.displayList.innerHTML = state.displays.map(d => 
        '<div class="display-item">' +
            '<div class="display-item__info">' +
                '<span class="display-item__label">' + d.display + '</span>' +
                '<span class="display-item__size">' + d.width + '×' + d.height + ' • Port ' + d.ws_port + '</span>' +
            '</div>' +
            '<button class="btn btn--danger btn--icon" onclick="deleteDisplay(' + d.display_num + ')" title="Stop">×</button>' +
        '</div>'
    ).join('');
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
        document.getElementById('displayNum').value = '';
        await refreshDisplays();
    } catch (error) {
        console.error('Failed to create display:', error);
    }
}

async function deleteDisplay(displayNum) {
    if (!confirm('Stop display :' + displayNum + '?')) return;
    
    try {
        await fetch('/api/x11/displays/' + displayNum, { method: 'DELETE' });
        
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
    
    const guiCount = parseInt(layout.replace('split-', '')) || 0;
    
    if (layout === 'terminals-only') {
        // Hide GUI container, terminal takes full width
        dom.guiContainer.style.display = 'none';
        dom.mainResizer.style.display = 'none';
        dom.terminalPanel.style.flex = '1';
        
        state.guiPanels.forEach((p, i) => {
            p.visible = false;
        });
    } else {
        // Terminal on left, GUI container on right
        dom.terminalPanel.style.flex = '0 0 ' + (100 - state.panelSizes.guiContainer) + '%';
        dom.mainResizer.style.display = 'block';
        dom.guiContainer.style.display = 'flex';
        dom.guiContainer.style.flex = '1';
        
        // Show/hide GUI panels based on count
        for (let i = 0; i < 3; i++) {
            if (i < guiCount) {
                dom.guiPanels[i].classList.remove('gui-panel--hidden');
                dom.guiPanels[i].style.flex = '1';
                state.guiPanels[i].visible = true;
            } else {
                dom.guiPanels[i].classList.add('gui-panel--hidden');
                state.guiPanels[i].visible = false;
            }
        }
        
        // Show/hide vertical resizers between GUI panels
        const resizers = document.querySelectorAll('.gui-resizer');
        resizers.forEach((r, i) => {
            if (i < guiCount - 1) {
                r.style.display = 'block';
            } else {
                r.style.display = 'none';
            }
        });
    }
    
    // Refit terminal
    setTimeout(() => {
        if (state.fitAddon) state.fitAddon.fit();
    }, 100);
}

// ============================================================================
// Resizing
// ============================================================================

function setupResizers() {
    // Main resizer (between Terminal and GUI container)
    dom.mainResizer.addEventListener('mousedown', (e) => {
        e.preventDefault();
        state.resizing = {
            active: true,
            type: 'main',
            startPos: e.clientX,
            startSize: dom.terminalPanel.getBoundingClientRect().width
        };
        document.body.classList.add('resizing');
        dom.mainResizer.classList.add('resizer--active');
    });
    
    // GUI panel resizers (vertical, between GUI panels)
    document.querySelectorAll('.gui-resizer').forEach((resizer, index) => {
        resizer.addEventListener('mousedown', (e) => {
            e.preventDefault();
            const panel = dom.guiPanels[index];
            state.resizing = {
                active: true,
                type: 'gui',
                index: index,
                startPos: e.clientY,
                startSize: panel.getBoundingClientRect().height
            };
            document.body.classList.add('resizing-v');
            resizer.classList.add('resizer--active');
        });
    });
    
    document.addEventListener('mousemove', handleResize);
    document.addEventListener('mouseup', stopResize);
}

function handleResize(e) {
    if (!state.resizing.active) return;
    
    if (state.resizing.type === 'main') {
        // Horizontal resize of terminal (left panel)
        const containerWidth = dom.workspaceContent.getBoundingClientRect().width;
        const delta = e.clientX - state.resizing.startPos;
        const newWidth = state.resizing.startSize + delta;
        const minWidth = 300;
        const maxWidth = containerWidth - 250;
        
        if (newWidth >= minWidth && newWidth <= maxWidth) {
            const percent = (newWidth / containerWidth) * 100;
            dom.terminalPanel.style.flex = '0 0 ' + percent + '%';
            state.panelSizes.guiContainer = 100 - percent;
        }
    } else if (state.resizing.type === 'gui') {
        // Vertical resize of GUI panels
        const containerHeight = dom.guiContainer.getBoundingClientRect().height;
        const delta = e.clientY - state.resizing.startPos;
        const panel = dom.guiPanels[state.resizing.index];
        const newHeight = state.resizing.startSize + delta;
        const minHeight = 100;
        
        if (newHeight >= minHeight) {
            panel.style.flex = '0 0 ' + newHeight + 'px';
        }
    }
    
    if (state.fitAddon) state.fitAddon.fit();
}

function stopResize() {
    if (!state.resizing.active) return;
    
    state.resizing.active = false;
    document.body.classList.remove('resizing', 'resizing-v');
    document.querySelectorAll('.resizer--active').forEach(r => r.classList.remove('resizer--active'));
    
    setTimeout(() => {
        if (state.fitAddon) state.fitAddon.fit();
    }, 50);
}

// ============================================================================
// GUI Panel - Fullscreen & Detach
// ============================================================================

function toggleFullscreen(panelIndex) {
    const panel = dom.guiPanels[panelIndex];
    const panelState = state.guiPanels[panelIndex];
    
    if (panelState.fullscreen) {
        // Exit fullscreen
        panel.classList.remove('gui-panel--fullscreen');
        dom.fullscreenOverlay.classList.remove('fullscreen-overlay--visible');
        panelState.fullscreen = false;
        
        // Restore to container if it was detached before fullscreen
        if (!panelState.detached) {
            // Already in container
        }
    } else {
        // Enter fullscreen
        panel.classList.add('gui-panel--fullscreen');
        dom.fullscreenOverlay.classList.add('fullscreen-overlay--visible');
        panelState.fullscreen = true;
    }
}

function toggleDetach(panelIndex) {
    const panel = dom.guiPanels[panelIndex];
    const panelState = state.guiPanels[panelIndex];
    
    if (panelState.fullscreen) {
        // Exit fullscreen first
        toggleFullscreen(panelIndex);
    }
    
    if (panelState.detached) {
        // Re-attach to container
        panel.classList.remove('gui-panel--detached');
        panel.style.position = '';
        panel.style.top = '';
        panel.style.left = '';
        panel.style.width = '';
        panel.style.height = '';
        panelState.detached = false;
        
        // Move back to container
        const guiCount = parseInt(state.layout.replace('split-', '')) || 0;
        if (panelIndex < guiCount) {
            panel.classList.remove('gui-panel--hidden');
        }
    } else {
        // Detach and make floating
        const rect = panel.getBoundingClientRect();
        panel.classList.add('gui-panel--detached');
        panel.style.position = 'fixed';
        panel.style.top = rect.top + 'px';
        panel.style.left = rect.left + 'px';
        panel.style.width = rect.width + 'px';
        panel.style.height = rect.height + 'px';
        panelState.detached = true;
        
        // Setup drag on header
        const header = panel.querySelector('.gui-panel__header');
        header.addEventListener('mousedown', (e) => startDrag(e, panelIndex));
    }
}

function startDrag(e, panelIndex) {
    if (!state.guiPanels[panelIndex].detached) return;
    if (e.target.tagName === 'BUTTON') return; // Don't drag when clicking buttons
    
    const panel = dom.guiPanels[panelIndex];
    const rect = panel.getBoundingClientRect();
    
    state.dragging = {
        active: true,
        panel: panel,
        offsetX: e.clientX - rect.left,
        offsetY: e.clientY - rect.top
    };
    
    document.addEventListener('mousemove', handleDrag);
    document.addEventListener('mouseup', stopDrag);
}

function handleDrag(e) {
    if (!state.dragging.active) return;
    
    const panel = state.dragging.panel;
    panel.style.left = (e.clientX - state.dragging.offsetX) + 'px';
    panel.style.top = (e.clientY - state.dragging.offsetY) + 'px';
}

function stopDrag() {
    state.dragging.active = false;
    document.removeEventListener('mousemove', handleDrag);
    document.removeEventListener('mouseup', stopDrag);
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
        //const RFB = (await import('https://cdn.jsdelivr.net/npm/@novnc/novnc@1.4.0/core/rfb.js')).default;
	const RFB = (await import('/static/js/novnc/core/rfb.js')).default;
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
    dom.socketInput.addEventListener('change', saveConfig);
    dom.prefixInput.addEventListener('change', saveConfig);
    
    // Debounced resize handler for better performance
    let resizeTimeout;
    window.addEventListener('resize', () => {
        clearTimeout(resizeTimeout);
        resizeTimeout = setTimeout(() => {
            if (state.fitAddon) state.fitAddon.fit();
        }, 100);
    });
    
    document.getElementById('sessionName').addEventListener('keydown', e => {
        if (e.key === 'Enter') createSession();
    });
    document.getElementById('cmdCommand').addEventListener('keydown', e => {
        if (e.key === 'Enter') addCommand();
    });
    
    document.querySelectorAll('.modal-overlay').forEach(overlay => {
        overlay.addEventListener('click', e => {
            if (e.target === overlay) overlay.classList.remove('modal-overlay--visible');
        });
    });
    
    // Escape to close modals or exit fullscreen
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') {
            // Check for fullscreen panels first
            const fullscreenPanel = state.guiPanels.findIndex(p => p.fullscreen);
            if (fullscreenPanel >= 0) {
                toggleFullscreen(fullscreenPanel);
                return;
            }
            document.querySelectorAll('.modal-overlay').forEach(o => o.classList.remove('modal-overlay--visible'));
        }
    });
    
    document.querySelectorAll('.layout-btn').forEach(btn => {
        btn.addEventListener('click', () => setLayout(btn.dataset.layout));
    });
    
    // Click on fullscreen overlay to exit
    dom.fullscreenOverlay.addEventListener('click', () => {
        const fullscreenPanel = state.guiPanels.findIndex(p => p.fullscreen);
        if (fullscreenPanel >= 0) {
            toggleFullscreen(fullscreenPanel);
        }
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
    setupResizers();
    setLayout('terminals-only');
});
