/**
 * Geometry Dash TAS/ML Dashboard Client Controller
 * Manages live telemetry polling, Chart.js updates, jump timeline rendering,
 * and UI state transitions.
 */

(function () {
    'use strict';

    // State & Config
    let pollingIntervalMs = 1000;
    let pollTimer = null;
    let isMonitoringActive = true;
    let lastEventId = 0;
    let lastSuccessfulUpdate = null;

    // Charts
    let progressChart = null;
    let fitnessChart = null;

    // DOM Elements
    const dom = {
        connectionBadge: document.getElementById('connection-badge'),
        connectionText: document.getElementById('connection-text'),
        agentBadge: document.getElementById('agent-badge'),
        agentText: document.getElementById('agent-text'),
        sessionDuration: document.getElementById('session-duration'),
        lastUpdate: document.getElementById('last-update'),
        pollLatency: document.getElementById('poll-latency'),

        // Overview metrics
        currentGen: document.getElementById('metric-current-gen'),
        currentAttempt: document.getElementById('metric-current-attempt'),
        bestCompletion: document.getElementById('metric-best-completion'),
        totalAttempts: document.getElementById('metric-total-attempts'),
        successCount: document.getElementById('metric-success-count'),
        bestFitness: document.getElementById('metric-best-fitness'),

        // Live attempt monitor
        attemptNum: document.getElementById('attempt-number-badge'),
        attemptOutcome: document.getElementById('attempt-outcome-badge'),
        levelProgressText: document.getElementById('level-progress-text'),
        levelProgressBar: document.getElementById('level-progress-bar'),
        attemptElapsedTime: document.getElementById('attempt-elapsed-time'),
        latestAction: document.getElementById('attempt-latest-action'),
        plannedJumps: document.getElementById('attempt-planned-jumps'),
        executedJumps: document.getElementById('attempt-executed-jumps'),
        attemptFitness: document.getElementById('attempt-fitness'),

        // Timeline
        timelineRail: document.getElementById('timeline-rail'),
        timelineCursor: document.getElementById('timeline-cursor'),
        timelineStatusNote: document.getElementById('timeline-status-note'),
        verticalScroll: document.getElementById('vertical-timeline-scroll'),
        verticalRail: document.getElementById('vertical-timeline-rail'),
        verticalCursor: document.getElementById('vertical-timeline-cursor'),
        verticalCursorBadge: document.getElementById('vertical-cursor-badge'),
        verticalMarkersContainer: document.getElementById('vertical-markers-container'),

        // Event feed
        eventFeed: document.getElementById('event-feed-list'),
        eventCountBadge: document.getElementById('event-count-badge'),

        // Controls
        btnToggleMonitoring: document.getElementById('btn-toggle-monitoring'),
        btnClearEvents: document.getElementById('btn-clear-events'),
        btnSimError: document.getElementById('btn-sim-error'),
        btnSimDisconnect: document.getElementById('btn-sim-disconnect'),

        // Real TAS Agent Controls
        countdownBanner: document.getElementById('countdown-banner'),
        countdownNumber: document.getElementById('countdown-number'),
        btnCancelCountdown: document.getElementById('btn-cancel-countdown'),
        btnStartAgent: document.getElementById('btn-start-agent'),
        btnPauseAgent: document.getElementById('btn-pause-agent'),
        btnStopAgent: document.getElementById('btn-stop-agent'),
        btnResetBest: document.getElementById('btn-reset-best'),
        btnConfigRois: document.getElementById('btn-config-rois'),
        liveFrameImg: document.getElementById('live-frame-img'),
        ocrReadingsLive: document.getElementById('ocr-readings-live'),
        roiModal: document.getElementById('roi-modal'),
        roiInputsContainer: document.getElementById('roi-inputs-container'),
        btnRoiSave: document.getElementById('btn-roi-save'),
        btnRoiClose: document.getElementById('btn-roi-close'),
        btnRoiSelectInteractive: document.getElementById('btn-roi-select-interactive'),
    };

    /**
     * Format seconds to HH:MM:SS or MM:SS
     */
    function formatDuration(seconds) {
        if (isNaN(seconds) || seconds === null) return '--:--';
        const s = Math.floor(seconds);
        const hrs = Math.floor(s / 3600);
        const mins = Math.floor((s % 3600) / 60);
        const secs = s % 60;
        if (hrs > 0) {
            return `${hrs}:${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
        }
        return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
    }

    /**
     * Format ISO timestamp to local time HH:MM:SS
     */
    function formatTime(isoString) {
        if (!isoString) return '--:--:--';
        try {
            const d = new Date(isoString);
            return d.toLocaleTimeString([], { hour12: false });
        } catch {
            return isoString;
        }
    }

    /**
     * Initialize Chart.js instances with dark technical theme
     */
    function initCharts(initialGenerations) {
        const gridColor = 'rgba(255, 255, 255, 0.05)';
        const tickColor = '#64748b';

        // 1. Completion Progress Chart
        const ctxProgress = document.getElementById('progress-chart');
        if (ctxProgress) {
            progressChart = new Chart(ctxProgress, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [
                        {
                            label: 'Best Completion (%)',
                            data: [],
                            borderColor: '#00f2fe',
                            backgroundColor: 'rgba(0, 242, 254, 0.1)',
                            borderWidth: 2,
                            tension: 0.2,
                            fill: true,
                            pointRadius: 3,
                            pointHoverRadius: 5,
                        },
                        {
                            label: 'Avg Completion (%)',
                            data: [],
                            borderColor: '#38bdf8',
                            borderDash: [4, 4],
                            borderWidth: 1.5,
                            tension: 0.2,
                            fill: false,
                            pointRadius: 2,
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: { duration: 400 },
                    scales: {
                        x: {
                            grid: { color: gridColor },
                            ticks: {
                                color: tickColor,
                                font: { family: 'ui-monospace, monospace', size: 10 },
                                autoSkip: true,
                                maxTicksLimit: 8,
                                maxRotation: 0,
                            },
                            title: { display: true, text: 'Generation', color: tickColor, font: { size: 11 } }
                        },
                        y: {
                            min: 0,
                            max: 100,
                            grid: { color: gridColor },
                            ticks: {
                                color: tickColor,
                                font: { family: 'ui-monospace, monospace', size: 10 },
                                callback: val => `${val}%`
                            }
                        }
                    },
                    plugins: {
                        legend: {
                            labels: { color: '#94a3b8', font: { size: 11, family: 'sans-serif' }, boxWidth: 12 }
                        },
                        tooltip: {
                            backgroundColor: '#161a22',
                            titleColor: '#00f2fe',
                            borderColor: 'rgba(255, 255, 255, 0.1)',
                            borderWidth: 1,
                            padding: 10,
                            displayColors: false
                        }
                    }
                }
            });
        }

        // 2. Fitness Chart
        const ctxFitness = document.getElementById('fitness-chart');
        if (ctxFitness) {
            fitnessChart = new Chart(ctxFitness, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [
                        {
                            label: 'Best Fitness',
                            data: [],
                            borderColor: '#a855f7',
                            backgroundColor: 'rgba(168, 85, 247, 0.1)',
                            borderWidth: 2,
                            tension: 0.2,
                            fill: true,
                            pointRadius: 3,
                        },
                        {
                            label: 'Avg Fitness',
                            data: [],
                            borderColor: '#c084fc',
                            borderDash: [3, 3],
                            borderWidth: 1.5,
                            tension: 0.2,
                            fill: false,
                            pointRadius: 2,
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: { duration: 400 },
                    scales: {
                        x: {
                            grid: { color: gridColor },
                            ticks: {
                                color: tickColor,
                                font: { family: 'ui-monospace, monospace', size: 10 },
                                autoSkip: true,
                                maxTicksLimit: 8,
                                maxRotation: 0,
                            },
                            title: { display: true, text: 'Generation', color: tickColor, font: { size: 11 } }
                        },
                        y: {
                            grid: { color: gridColor },
                            ticks: { color: tickColor, font: { family: 'ui-monospace, monospace', size: 10 } }
                        }
                    },
                    plugins: {
                        legend: {
                            labels: { color: '#94a3b8', font: { size: 11, family: 'sans-serif' }, boxWidth: 12 }
                        },
                        tooltip: {
                            backgroundColor: '#161a22',
                            borderColor: 'rgba(255, 255, 255, 0.1)',
                            borderWidth: 1,
                            padding: 10,
                            displayColors: false
                        }
                    }
                }
            });
        }

        if (initialGenerations && initialGenerations.length > 0) {
            updateCharts(initialGenerations);
        }
    }

    /**
     * Update Chart data safely without full re-render
     */
    function updateCharts(generations) {
        if (!generations || generations.length === 0) return;

        const labels = generations.map(g => `Gen ${g.generation}`);
        const bestComp = generations.map(g => g.best_completion);
        const avgComp = generations.map(g => g.avg_completion);
        const bestFit = generations.map(g => g.best_fitness ?? null);
        const avgFit = generations.map(g => g.avg_fitness ?? null);

        if (progressChart) {
            progressChart.data.labels = labels;
            progressChart.data.datasets[0].data = bestComp;
            progressChart.data.datasets[1].data = avgComp;
            progressChart.update('none'); // Update smoothly without disruptive reflow
        }

        if (fitnessChart) {
            fitnessChart.data.labels = labels;
            fitnessChart.data.datasets[0].data = bestFit;
            fitnessChart.data.datasets[1].data = avgFit;
            fitnessChart.update('none');
        }
    }

    /**
     * Update top status bar & overview metrics
     */
    function updateSessionUI(session) {
        if (!session) return;

        // Connection badge
        dom.connectionBadge.className = 'status-badge';
        if (session.connection_state === 'Connected') {
            dom.connectionBadge.classList.add('badge-connected');
            dom.connectionText.textContent = 'Agent Connected';
        } else if (session.connection_state === 'Simulated') {
            dom.connectionBadge.classList.add('badge-simulated');
            dom.connectionText.textContent = 'Simulated Telemetry';
        } else {
            dom.connectionBadge.classList.add('badge-disconnected');
            dom.connectionText.textContent = 'Agent Offline';
        }

        // Agent status badge
        dom.agentBadge.className = 'status-badge';
        const st = session.agent_status || 'Idle';
        dom.agentText.textContent = st;
        if (st === 'Running') dom.agentBadge.classList.add('badge-agent-running');
        else if (st === 'Paused') dom.agentBadge.classList.add('badge-agent-paused');
        else if (st === 'Evaluating') dom.agentBadge.classList.add('badge-agent-evaluating');
        else if (st === 'Error') dom.agentBadge.classList.add('badge-agent-error');
        else dom.agentBadge.classList.add('badge-simulated');

        // Stats
        dom.sessionDuration.textContent = formatDuration(session.uptime_seconds);
        dom.lastUpdate.textContent = formatTime(session.last_update);

        // Metric cards
        dom.currentGen.textContent = session.current_generation ?? '--';
        dom.currentAttempt.textContent = session.current_attempt ?? '--';
        dom.bestCompletion.textContent = session.best_completion !== null && session.best_completion !== undefined 
            ? `${session.best_completion.toFixed(2)}s` 
            : '0.00s';
        dom.totalAttempts.textContent = session.total_attempts ?? '--';
        dom.successCount.textContent = session.successful_completions ?? 0;
        dom.bestFitness.textContent = session.best_fitness !== null && session.best_fitness !== undefined 
            ? session.best_fitness 
            : '--';
    }

    /**
     * Update live attempt monitor & progress bar
     */
    function updateAttemptUI(attempt) {
        if (!attempt) return;

        dom.attemptNum.textContent = `Attempt #${attempt.attempt_number || 0}`;
        
        // Outcome tag
        const outcome = attempt.outcome || 'Unknown';
        dom.attemptOutcome.textContent = outcome;
        dom.attemptOutcome.className = 'panel-badge';
        if (outcome === 'Completed') {
            dom.attemptOutcome.style.color = '#10b981';
            dom.attemptOutcome.style.borderColor = 'rgba(16, 185, 129, 0.4)';
        } else if (outcome === 'Crashed') {
            dom.attemptOutcome.style.color = '#ef4444';
            dom.attemptOutcome.style.borderColor = 'rgba(239, 68, 68, 0.4)';
        } else {
            dom.attemptOutcome.style.color = '#00f2fe';
            dom.attemptOutcome.style.borderColor = 'rgba(0, 242, 254, 0.4)';
        }

        const survivalSec = attempt.level_progress ?? 0;
        dom.levelProgressText.textContent = survivalSec.toFixed(2);
        // Stereo Madness 85.0s timeline progress fill
        const barPct = Math.min(100, Math.max(0, (survivalSec / 85.0) * 100));
        dom.levelProgressBar.style.width = `${barPct}%`;

        dom.attemptElapsedTime.textContent = `${attempt.elapsed_time ? attempt.elapsed_time.toFixed(2) : '0.00'}s`;
        dom.latestAction.textContent = attempt.latest_action || 'None';
        dom.plannedJumps.textContent = attempt.planned_jumps_count ?? 0;
        dom.executedJumps.textContent = attempt.executed_jumps_count ?? 0;
        dom.attemptFitness.textContent = attempt.fitness !== null && attempt.fitness !== undefined ? attempt.fitness : '--';

        // Update Jump Timeline
        renderTimeline(attempt);
    }

    /**
     * Render the Jump Timeline with planned/executed markers
     * Supports both desktop horizontal rail and mobile vertical chronological list
     */
    function renderTimeline(attempt) {
        if (!dom.timelineRail && !dom.verticalMarkersContainer) return;

        // Stereo Madness reference duration
        const totalDuration = 85.0;
        const currentElapsed = attempt.elapsed_time || 0.0;
        const cursorPct = Math.min(100, (currentElapsed / totalDuration) * 100);

        // --- 1. Desktop Horizontal Timeline ---
        if (dom.timelineCursor) {
            dom.timelineCursor.style.left = `${cursorPct}%`;
        }

        if (dom.timelineRail) {
            const existingMarkers = dom.timelineRail.querySelectorAll('.timeline-jump-marker');
            existingMarkers.forEach(el => el.remove());
        }

        const jumps = attempt.jumps || [];
        if (jumps.length === 0) {
            if (dom.timelineStatusNote) dom.timelineStatusNote.textContent = 'Awaiting jump policy from agent...';
            if (dom.verticalMarkersContainer) dom.verticalMarkersContainer.innerHTML = '';
            return;
        }

        if (dom.timelineStatusNote) {
            dom.timelineStatusNote.textContent = `${jumps.length} planned jumps mapped (Synthetic/Policy timings)`;
        }

        if (dom.timelineRail) {
            jumps.forEach(jump => {
                const plannedPct = (jump.planned_time / totalDuration) * 100;
                if (plannedPct < 0 || plannedPct > 100) return;

                const marker = document.createElement('div');
                marker.className = 'timeline-jump-marker';
                marker.style.left = `${plannedPct}%`;

                if (jump.executed_time !== null && jump.executed_time !== undefined) {
                    marker.classList.add('marker-executed');
                    marker.title = `Jump executed @ ${jump.executed_time}s (Offset: ${jump.delta_ms}ms)`;
                } else {
                    marker.classList.add('marker-planned');
                    marker.title = `Planned jump @ ${jump.planned_time.toFixed(2)}s`;
                }

                dom.timelineRail.appendChild(marker);
            });

            // Mark crash location on horizontal rail if crashed
            if (attempt.outcome === 'Crashed' && currentElapsed > 0) {
                const crashMarker = document.createElement('div');
                crashMarker.className = 'timeline-jump-marker marker-crashed';
                crashMarker.style.left = `${cursorPct}%`;
                crashMarker.style.width = '6px';
                crashMarker.title = `Collision / Crash @ ${currentElapsed.toFixed(2)}s`;
                dom.timelineRail.appendChild(crashMarker);
            }
        }

        // --- 2. Mobile Vertical Timeline ---
        if (dom.verticalMarkersContainer) {
            dom.verticalMarkersContainer.innerHTML = '';

            let activeItemEl = null;

            jumps.forEach((jump, idx) => {
                const item = document.createElement('div');
                item.className = 'vertical-timeline-item';
                item.setAttribute('data-time', jump.planned_time);

                const isExecuted = jump.executed_time !== null && jump.executed_time !== undefined;
                const isPast = currentElapsed >= jump.planned_time;
                const isNext = !isPast && (!activeItemEl);

                // Time Column
                const timeCol = document.createElement('span');
                timeCol.className = 'v-item-time';
                timeCol.textContent = `${jump.planned_time.toFixed(2)}s`;

                // Node/Dot Slot Column
                const slotCol = document.createElement('div');
                slotCol.className = 'v-item-node-slot';

                const dot = document.createElement('div');
                dot.className = 'v-node-dot';
                if (isExecuted) {
                    dot.classList.add('executed');
                } else if (attempt.outcome === 'Crashed' && currentElapsed >= jump.planned_time) {
                    dot.classList.add('crashed');
                }
                slotCol.appendChild(dot);

                // Content / Action / Delta Column
                const contentCol = document.createElement('div');
                contentCol.className = 'v-item-content';

                const label = document.createElement('span');
                label.className = 'v-item-label';
                label.textContent = `Jump #${idx + 1} (${jump.action || 'jump'})`;

                const deltaBadge = document.createElement('span');
                deltaBadge.className = 'v-item-delta';

                if (isExecuted) {
                    deltaBadge.classList.add('delta-executed');
                    deltaBadge.textContent = `${jump.delta_ms > 0 ? '+' : ''}${jump.delta_ms}ms`;
                } else if (attempt.outcome === 'Crashed' && currentElapsed < jump.planned_time) {
                    deltaBadge.classList.add('delta-planned');
                    deltaBadge.textContent = 'Unreached';
                } else {
                    deltaBadge.classList.add('delta-planned');
                    deltaBadge.textContent = 'Planned';
                }

                contentCol.appendChild(label);
                contentCol.appendChild(deltaBadge);

                item.appendChild(timeCol);
                item.appendChild(slotCol);
                item.appendChild(contentCol);

                dom.verticalMarkersContainer.appendChild(item);

                if (isPast) {
                    activeItemEl = item;
                }
            });

            // If crashed, add a dedicated collision node in the vertical timeline
            if (attempt.outcome === 'Crashed' && currentElapsed > 0) {
                const crashItem = document.createElement('div');
                crashItem.className = 'vertical-timeline-item';
                crashItem.style.background = 'rgba(239, 68, 68, 0.1)';

                const cTime = document.createElement('span');
                cTime.className = 'v-item-time';
                cTime.style.color = '#ef4444';
                cTime.textContent = `${currentElapsed.toFixed(2)}s`;

                const cSlot = document.createElement('div');
                cSlot.className = 'v-item-node-slot';
                const cDot = document.createElement('div');
                cDot.className = 'v-node-dot crashed';
                cSlot.appendChild(cDot);

                const cContent = document.createElement('div');
                cContent.className = 'v-item-content';
                const cLabel = document.createElement('span');
                cLabel.className = 'v-item-label';
                cLabel.style.color = '#ef4444';
                cLabel.textContent = 'Collision / Crash';

                const cDelta = document.createElement('span');
                cDelta.className = 'v-item-delta delta-crashed';
                cDelta.textContent = 'CRASH';

                cContent.appendChild(cLabel);
                cContent.appendChild(cDelta);
                crashItem.appendChild(cTime);
                crashItem.appendChild(cSlot);
                crashItem.appendChild(cContent);

                // Insert crash item in chronological position
                let inserted = false;
                const children = dom.verticalMarkersContainer.children;
                for (let i = 0; i < children.length; i++) {
                    const t = parseFloat(children[i].getAttribute('data-time') || '0');
                    if (t > currentElapsed) {
                        dom.verticalMarkersContainer.insertBefore(crashItem, children[i]);
                        inserted = true;
                        break;
                    }
                }
                if (!inserted) {
                    dom.verticalMarkersContainer.appendChild(crashItem);
                }
                activeItemEl = crashItem;
            }

            // Update Vertical Playhead Cursor Position & Time Badge
            if (dom.verticalCursor && dom.verticalCursorBadge) {
                dom.verticalCursorBadge.textContent = `${currentElapsed.toFixed(1)}s`;

                if (activeItemEl) {
                    const itemTop = activeItemEl.offsetTop;
                    const itemHeight = activeItemEl.offsetHeight;
                    dom.verticalCursor.style.top = `${itemTop + itemHeight / 2}px`;
                    dom.verticalCursor.style.display = 'flex';

                    // Smooth auto-scroll vertical container to keep the active playhead centered
                    if (dom.verticalScroll) {
                        const scrollTarget = itemTop - dom.verticalScroll.clientHeight / 2 + itemHeight / 2;
                        dom.verticalScroll.scrollTop = Math.max(0, scrollTarget);
                    }
                } else {
                    dom.verticalCursor.style.top = '10px';
                    dom.verticalCursor.style.display = 'flex';
                }
            }
        }
    }

    /**
     * Render events feed incrementally
     */
    function appendEvents(events) {
        if (!events || events.length === 0) return;

        events.forEach(evt => {
            if (evt.id && evt.id <= lastEventId) return; // Avoid duplicates
            if (evt.id && evt.id > lastEventId) lastEventId = evt.id;

            const item = document.createElement('div');
            item.className = `event-item severity-${evt.severity || 'info'}`;

            const contentDiv = document.createElement('div');
            contentDiv.className = 'event-content';

            const tag = document.createElement('span');
            tag.className = 'event-category-tag';
            tag.textContent = evt.category || 'general';

            const text = document.createElement('span');
            text.className = 'event-text';
            text.textContent = evt.message;

            contentDiv.appendChild(tag);
            contentDiv.appendChild(text);

            const timeSpan = document.createElement('span');
            timeSpan.className = 'event-timestamp';
            timeSpan.textContent = formatTime(evt.timestamp);

            item.appendChild(contentDiv);
            item.appendChild(timeSpan);

            // Prepend new event to top of feed
            dom.eventFeed.insertBefore(item, dom.eventFeed.firstChild);
        });

        // Bound event feed length in DOM to prevent browser slowdown
        while (dom.eventFeed.children.length > 100) {
            dom.eventFeed.removeChild(dom.eventFeed.lastChild);
        }

        if (dom.eventCountBadge) {
            dom.eventCountBadge.textContent = `${dom.eventFeed.children.length} events`;
        }
    }

    let lastFrameTime = 0;

    /**
     * Main polling function fetching consolidated telemetry snapshot
     */
    async function pollTelemetry() {
        if (!isMonitoringActive) return;

        const startTime = performance.now();
        try {
            const res = await fetch(`/api/snapshot?since_id=${lastEventId}`);
            if (!res.ok) {
                throw new Error(`HTTP ${res.status}`);
            }

            const data = await res.json();
            const latency = Math.round(performance.now() - startTime);
            dom.pollLatency.textContent = `${latency}ms`;

            // Update UI elements
            updateSessionUI(data.session);
            updateAttemptUI(data.attempt);
            updateCharts(data.generations);
            appendEvents(data.events);

            lastSuccessfulUpdate = new Date();

            // Poll TAS Agent Status
            try {
                const agentRes = await fetch('/api/agent/status');
                if (agentRes.ok) {
                    const agentStatus = await agentRes.json();
                    if (agentStatus.available) {
                        // Handle Countdown Banner
                        if (agentStatus.is_counting_down && dom.countdownBanner) {
                            dom.countdownBanner.classList.remove('hidden');
                            if (dom.countdownNumber) {
                                dom.countdownNumber.textContent = Math.ceil(agentStatus.countdown_remaining);
                            }
                            if (dom.agentText) {
                                dom.agentText.textContent = `Countdown (${Math.ceil(agentStatus.countdown_remaining)}s)`;
                            }
                        } else if (dom.countdownBanner) {
                            dom.countdownBanner.classList.add('hidden');
                            if (dom.agentText) {
                                if (agentStatus.paused) dom.agentText.textContent = 'Paused';
                                else if (agentStatus.running) dom.agentText.textContent = 'Running';
                                else dom.agentText.textContent = 'Idle';
                            }
                        }

                        // Update Pause/Resume button label
                        if (dom.btnPauseAgent) {
                            dom.btnPauseAgent.textContent = agentStatus.paused ? '▶ Resume Agent' : '⏸ Pause Agent';
                        }

                        // Update Connection Badge
                        if (dom.connectionBadge && dom.connectionText) {
                            dom.connectionBadge.className = 'status-badge badge-connected';
                            dom.connectionText.textContent = agentStatus.mock_mode
                                ? 'Simulated Agent'
                                : (agentStatus.dry_run ? 'Live (Dry-Run)' : 'Live (Real GD)');
                        }

                        // Update Live OCR text
                        if (dom.ocrReadingsLive && agentStatus.ocr_telemetry) {
                            const o = agentStatus.ocr_telemetry;
                            dom.ocrReadingsLive.textContent = `Pct: ${o.percentage ?? 0}% | Att: ${o.attempt ?? 1} | Time: ${o.time ?? 0}s | Taps: ${o.tap_count ?? 0}`;
                        }

                        // Update Live Frame Image (throttled to ~750ms)
                        if (dom.liveFrameImg && (Date.now() - lastFrameTime > 750)) {
                            dom.liveFrameImg.src = `/api/agent/frame?t=${Date.now()}`;
                            lastFrameTime = Date.now();
                        }
                    }
                }
            } catch (agentErr) {
                // Non-fatal if agent endpoint is temporarily busy
            }
        } catch (err) {
            console.warn('[Dashboard] Telemetry poll failed:', err);
            dom.pollLatency.textContent = 'ERR';
            dom.connectionBadge.className = 'status-badge badge-disconnected';
            dom.connectionText.textContent = 'API Offline';
        }
    }

    /**
     * Set up UI controls & actions
     */
    function setupControls() {
        // Start RL Agent with 10s Countdown
        if (dom.btnStartAgent) {
            dom.btnStartAgent.addEventListener('click', async () => {
                try {
                    await fetch('/api/agent/start', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ countdown: 10.0 })
                    });
                    pollTelemetry();
                } catch (err) {
                    console.error('Failed to start agent:', err);
                }
            });
        }

        // Pause / Resume Agent
        if (dom.btnPauseAgent) {
            dom.btnPauseAgent.addEventListener('click', async () => {
                try {
                    const statusRes = await fetch('/api/agent/status');
                    const statusData = await statusRes.json();
                    const action = statusData.paused ? 'resume' : 'pause';
                    await fetch(`/api/agent/${action}`, { method: 'POST' });
                    pollTelemetry();
                } catch (err) {
                    console.error('Failed to toggle agent pause:', err);
                }
            });
        }

        // Stop / Halt Agent
        if (dom.btnStopAgent) {
            dom.btnStopAgent.addEventListener('click', async () => {
                try {
                    await fetch('/api/agent/stop', { method: 'POST' });
                    pollTelemetry();
                } catch (err) {
                    console.error('Failed to stop agent:', err);
                }
            });
        }

        // Cancel Countdown Button
        if (dom.btnCancelCountdown) {
            dom.btnCancelCountdown.addEventListener('click', async () => {
                try {
                    await fetch('/api/agent/stop', { method: 'POST' });
                    if (dom.countdownBanner) dom.countdownBanner.classList.add('hidden');
                    pollTelemetry();
                } catch (err) {
                    console.error('Failed to abort countdown:', err);
                }
            });
        }

        // Reset Best Elite Baseline
        if (dom.btnResetBest) {
            dom.btnResetBest.addEventListener('click', async () => {
                if (confirm('Reset elite baseline tap sequence?')) {
                    try {
                        await fetch('/api/agent/reset', { method: 'POST' });
                        pollTelemetry();
                    } catch (err) {
                        console.error('Failed to reset elite baseline:', err);
                    }
                }
            });
        }

        // ROI Modal Open
        if (dom.btnConfigRois && dom.roiModal) {
            dom.btnConfigRois.addEventListener('click', async () => {
                try {
                    const res = await fetch('/api/agent/rois');
                    const data = await res.json();
                    const rois = data.rois || {};

                    if (dom.roiInputsContainer) {
                        dom.roiInputsContainer.innerHTML = '';
                        for (const [name, coords] of Object.entries(rois)) {
                            const row = document.createElement('div');
                            row.style.display = 'grid';
                            row.style.gridTemplateColumns = '120px 1fr';
                            row.style.alignItems = 'center';
                            row.style.gap = '8px';

                            const label = document.createElement('span');
                            label.style.fontFamily = 'var(--font-mono)';
                            label.style.fontSize = '12px';
                            label.textContent = name;

                            const input = document.createElement('input');
                            input.type = 'text';
                            input.id = `roi-input-${name}`;
                            input.value = coords.join(', ');
                            input.style.background = 'var(--bg-panel-subtle)';
                            input.style.border = '1px solid var(--border-subtle)';
                            input.style.color = '#fff';
                            input.style.padding = '4px 8px';
                            input.style.borderRadius = '4px';
                            input.style.fontFamily = 'var(--font-mono)';
                            input.style.fontSize = '12px';

                            row.appendChild(label);
                            row.appendChild(input);
                            dom.roiInputsContainer.appendChild(row);
                        }
                    }
                    dom.roiModal.style.display = 'flex';
                } catch (err) {
                    console.error('Failed to fetch ROIs:', err);
                }
            });
        }

        // ROI Modal Close
        if (dom.btnRoiClose && dom.roiModal) {
            dom.btnRoiClose.addEventListener('click', () => {
                dom.roiModal.style.display = 'none';
            });
        }

        // ROI Modal Save
        if (dom.btnRoiSave && dom.roiModal) {
            dom.btnRoiSave.addEventListener('click', async () => {
                const keys = ['percentage', 'attempt_count', 'time', 'tap_count'];
                const updated = {};
                for (const k of keys) {
                    const el = document.getElementById(`roi-input-${k}`);
                    if (el) {
                        const parts = el.value.split(',').map(s => parseInt(s.trim(), 10));
                        if (parts.length === 4 && parts.every(n => !isNaN(n))) {
                            updated[k] = parts;
                        }
                    }
                }
                try {
                    await fetch('/api/agent/rois', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(updated)
                    });
                    dom.roiModal.style.display = 'none';
                    pollTelemetry();
                } catch (err) {
                    console.error('Failed to save ROIs:', err);
                }
            });
        }

        // Interactive Snipping Tool ROI Selection
        if (dom.btnRoiSelectInteractive) {
            dom.btnRoiSelectInteractive.addEventListener('click', async () => {
                const roiName = prompt('Enter ROI to select (percentage, attempt_count, time, tap_count):', 'percentage');
                if (roiName) {
                    try {
                        await fetch('/api/agent/select-roi', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ roi_name: roiName.trim() })
                        });
                        alert(`Interactive ROI snipping tool initiated for "${roiName}". Use mouse to drag rectangle.`);
                    } catch (err) {
                        console.error('Failed to launch interactive ROI selection:', err);
                    }
                }
            });
        }

        if (dom.btnToggleMonitoring) {
            dom.btnToggleMonitoring.addEventListener('click', async () => {
                const nextAction = isMonitoringActive ? 'pause' : 'resume';
                try {
                    await fetch('/api/controls/monitoring', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ action: nextAction })
                    });
                    isMonitoringActive = !isMonitoringActive;
                    dom.btnToggleMonitoring.textContent = isMonitoringActive ? 'Pause Monitoring' : 'Resume Monitoring';
                } catch (err) {
                    console.error('Failed to toggle monitoring:', err);
                }
            });
        }

        if (dom.btnClearEvents) {
            dom.btnClearEvents.addEventListener('click', async () => {
                try {
                    await fetch('/api/events/clear', { method: 'POST' });
                    dom.eventFeed.innerHTML = '';
                    lastEventId = 0;
                    if (dom.eventCountBadge) dom.eventCountBadge.textContent = '0 events';
                } catch (err) {
                    console.error('Failed to clear events:', err);
                }
            });
        }

        if (dom.btnSimError) {
            dom.btnSimError.addEventListener('click', async () => {
                try {
                    await fetch('/api/controls/monitoring', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ action: 'error', message: 'Simulated CV frame grab timeout (Camera 0)' })
                    });
                    pollTelemetry();
                } catch (err) {
                    console.error('Failed to trigger simulated error:', err);
                }
            });
        }

        if (dom.btnSimDisconnect) {
            dom.btnSimDisconnect.addEventListener('click', async () => {
                try {
                    await fetch('/api/controls/monitoring', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ action: 'disconnect' })
                    });
                    pollTelemetry();
                } catch (err) {
                    console.error('Failed to trigger disconnect:', err);
                }
            });
        }
    }

    /**
     * Initialize dashboard on page load
     */
    function init() {
        const initialData = window.__INITIAL_TELEMETRY__ || {};
        
        // Initialize charts
        initCharts(initialData.generations || []);

        // Initial UI paint
        if (initialData.session) updateSessionUI(initialData.session);
        if (initialData.attempt) updateAttemptUI(initialData.attempt);
        if (initialData.events) appendEvents(initialData.events);

        setupControls();

        // Start polling loop
        pollTimer = setInterval(pollTelemetry, pollingIntervalMs);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
