/**
 * Visual audio segments editor for the "Audio Trim by Segments" node.
 *
 * Adds a button widget to the node that opens a dialog:
 *   - waveform rendering of the source audio (decoded via Web Audio API)
 *   - create segments by dragging on the waveform; move / resize / delete
 *     existing segments; zoom and pan
 *   - audition each segment, or play the concatenated trim result
 *   - Apply writes the segments back into the node's `segments` widget as
 *     the same JSON string format the backend parses
 *
 * Audio source discovery: accept a directly connected "Optional Load Audio"
 * or "LoadAudio", with Reroute nodes allowed, then load that file via
 * ComfyUI's /view API. Do not cross audio transformations. Segments are relative to that original audio — the same
 * semantics as the backend node (re-trim the ORIGINAL audio).
 */
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const EDITED_NODE = "Audio Trim by Segments";
const WAVE_BG = "#141414";
const WAVE_FG_DIM = "#3c4a5e";
const SEGMENT_FILL = "rgba(80, 160, 255, 0.22)";
const SEGMENT_BORDER = "#50a0ff";
const SEGMENT_SELECTED = "#ffb454";
const RULER_BG = "#1d1d1d";

function viewUrl(filename) {
    const annotation = filename.match(/\s+\[(input|output|temp)\]$/);
    const type = annotation?.[1] || "input";
    const path = filename.replace(/\s+\[(input|output|temp)\]$/, "").replaceAll("\\", "/");
    const i = path.lastIndexOf("/");
    const q = new URLSearchParams({
        filename: path.slice(i + 1), subfolder: i < 0 ? "" : path.slice(0, i), type,
    });
    return `/view?${q.toString()}`;
}

/** Only follow reroutes: transformations can change the source time axis. */
function findAudioSourceFile(node) {
    const seen = new Set();
    const graph = node.graph || app.graph;
    let current = node;
    while (current && !seen.has(current.id)) {
        seen.add(current.id);
        const type = current.comfyClass || current.type;
        if (type === "Optional Load Audio" || type === "LoadAudio") {
            if (current.inputs?.some((input) => input.name === "audio" && input.link != null)) return null;
            const widget = current.widgets?.find((w) => w.name === "audio");
            return typeof widget?.value === "string" && widget.value && widget.value !== "none"
                ? { node: current, filename: widget.value } : null;
        }
        if (current !== node && type !== "Reroute") return null;
        const input = current.inputs?.find((i) => i.name === "audio" && i.type === "AUDIO")
            || (type === "Reroute" ? current.inputs?.[0] : null);
        const link = input?.link != null ? graph?.links[input.link] : null;
        current = link ? graph.getNodeById(link.origin_id) : null;
    }
    return null;
}

function parseSegments(text) {
    const value = String(text ?? "").trim();
    if (!value) return [];
    let raw;
    try {
        raw = JSON.parse(value.replace(/,\s*([\]}])/g, "$1"));
    } catch {
        throw new Error("Segments is not valid JSON. Expected [[start, end], ...].");
    }
    if (!Array.isArray(raw)) throw new Error("Segments JSON must be a list.");
    return raw.map((item) => {
        const pair = Array.isArray(item) ? item : item && typeof item === "object" ? [item.start, item.end] : [];
        if (pair.length !== 2 || pair.some((v) => !["number", "string"].includes(typeof v) || String(v).trim() === "" || !Number.isFinite(Number(v)))) {
            throw new Error("Each segment must contain two finite numbers: [start, end].");
        }
        return pair.map(Number);
    }).filter(([s, e]) => e > s).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
}

function formatTime(t) {
    if (!Number.isFinite(t)) return "0.00";
    const m = Math.floor(t / 60);
    const s = t - m * 60;
    return m > 0 ? `${m}:${s.toFixed(2).padStart(5, "0")}` : s.toFixed(2);
}

class AudioSegmentsEditor {
    constructor(trimNode) {
        this.node = trimNode;
        this.audioCtx = null;
        this.buffer = null;
        this.segments = [];
        this.selected = -1;
        this.viewStart = 0; // seconds
        this.viewDur = 0; // seconds
        this.drag = null;
        this.playing = [];
        this.elements = {};
        this.duration = 0;
    }

    get segmentsWidget() {
        return this.node.widgets?.find((w) => w.name === "segments");
    }

    get segmentsConnected() {
        return this.node.inputs?.some((input) => input.name === "segments" && input.link != null);
    }

    normalizedSegments() {
        return this.segments.map(([s, e]) => [s, e].map((v) =>
            Number(Math.max(0, Math.min(this.duration, v)).toFixed(3))))
            .filter(([s, e]) => e > s)
            .sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    }

    async open() {
        if (this.elements.overlay) return;
        if (this.segmentsConnected) {
            alert("Disconnect the segments input before editing its widget value.");
            return;
        }
        const source = findAudioSourceFile(this.node);
        if (!source) {
            alert("Connect Optional Load Audio or LoadAudio directly (or through Reroute) and select a file. " +
                "Audio transformations such as Quick Audio Edit or VAD change the timeline; " +
                "connect the original loader output to this trim node.");
            return;
        }
        try {
            this.segments = parseSegments(this.segmentsWidget?.value);
        } catch (err) {
            alert(err.message);
            return;
        }
        this.sourceFilename = source.filename;
        this.sourceNode = source.node;
        const controller = new AbortController();
        this.controller = controller;
        this.buildDialog(source.filename);
        try {
            await this.loadAudio(source.filename);
            if (controller.signal.aborted || this.controller !== controller || !this.elements.overlay) return;
            this.segments = this.normalizedSegments();
            this.fitView();
            this.setLoading(false);
            this.render();
        } catch (err) {
            if (controller.signal.aborted || this.controller !== controller || !this.elements.overlay) return;
            alert(`Could not load audio "${source.filename}": ${err.message}. ` +
                "For video/unsupported codecs, extract a WAV file and select it in the loader.");
            this.close();
        }
    }

    async loadAudio(filename) {
        const signal = this.controller.signal;
        const resp = await api.fetchApi(viewUrl(filename), { signal });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.arrayBuffer();
        if (signal.aborted) return;
        const context = new (window.AudioContext || window.webkitAudioContext)();
        this.audioCtx = context;
        const buffer = await context.decodeAudioData(data);
        if (signal.aborted) return;
        this.buffer = buffer;
        this.duration = buffer.duration;
        if (!this.duration) throw new Error("Audio file is empty");
    }

    setLoading(loading) {
        this.elements.dialog.querySelectorAll("button, input").forEach((control) => {
            if (!control.classList.contains("oi-cancel")) control.disabled = loading;
        });
        this.elements.status.textContent = loading ? "Loading audio…" : "";
    }

    // ----- dialog ------------------------------------------------------------

    buildDialog(filename) {
        const overlay = document.createElement("div");
        overlay.style.cssText =
            "position:fixed;inset:0;z-index:100000;background:rgba(0,0,0,0.6);display:flex;align-items:center;justify-content:center;";
        const dialog = document.createElement("div");
        dialog.style.cssText =
            "background:#1e1e1e;color:#ddd;border:1px solid #444;border-radius:10px;width:min(920px,92vw);max-height:92vh;display:flex;flex-direction:column;font-family:inherit;box-shadow:0 12px 40px rgba(0,0,0,0.5);";
        this.previousFocus = document.activeElement;
        dialog.setAttribute("role", "dialog");
        dialog.setAttribute("aria-modal", "true");
        dialog.setAttribute("aria-label", "Audio Segments Editor");
        dialog.tabIndex = -1;
        dialog.innerHTML = `
            <div style="display:flex;align-items:center;gap:10px;padding:12px 16px;border-bottom:1px solid #333;">
                <b style="font-size:15px;">Audio Segments Editor</b>
                <span class="oi-filename" style="color:#999;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"></span>
                <span class="oi-duration" style="color:#888;font-size:12px;"></span>
                <span style="flex:1"></span>
                <span style="color:#888;font-size:12px;">drag = new segment · edges = resize · inside = move · wheel = zoom · Shift+drag = pan · Del = delete</span>
            </div>
            <div style="padding:12px 16px;overflow:auto;">
                <canvas class="oi-wave" style="width:100%;height:220px;display:block;background:${WAVE_BG};border-radius:6px;cursor:crosshair;touch-action:none;"></canvas>
                <div style="display:flex;gap:8px;align-items:center;margin-top:10px;flex-wrap:wrap;">
                    <button class="oi-btn oi-play-all">▶ Play result</button>
                    <button class="oi-btn oi-play-seg">▶ Play selected</button>
                    <button class="oi-btn oi-stop">■ Stop</button>
                    <span style="flex:1"></span>
                    <button class="oi-btn oi-zoom-out">−</button>
                    <button class="oi-btn oi-fit">Fit</button>
                    <button class="oi-btn oi-zoom-in">+</button>
                    <button class="oi-btn oi-clear">Clear all</button>
                </div>
                <input class="oi-pan" type="range" min="0" max="0" step="0.001" value="0" aria-label="Waveform position" style="width:100%;margin-top:8px;">
                <div class="oi-list" style="margin-top:10px;max-height:160px;overflow:auto;"></div>
            </div>
            <div style="display:flex;gap:8px;justify-content:flex-end;padding:12px 16px;border-top:1px solid #333;">
                <span class="oi-status" style="color:#888;font-size:12px;align-self:center;margin-right:auto;"></span>
                <button class="oi-btn oi-cancel">Cancel</button>
                <button class="oi-btn oi-apply" style="background:#3b6fb5;color:#fff;">Apply to node</button>
            </div>`;
        dialog.querySelector(".oi-filename").textContent = filename;
        overlay.appendChild(dialog);
        document.body.appendChild(overlay);
        overlay.addEventListener("mousedown", (e) => {
            if (e.target === overlay) this.close();
        });

        const $ = (cls) => dialog.querySelector("." + cls);
        this.elements = {
            overlay,
            dialog,
            wave: $("oi-wave"),
            duration: $("oi-duration"),
            list: $("oi-list"),
            status: $("oi-status"),
            pan: $("oi-pan"),
        };
        for (const name of ["oi-btn"]) {
            dialog.querySelectorAll("." + name).forEach((b) => {
                const primary = b.classList.contains("oi-apply");
                b.style.cssText =
                    `background:${primary ? "#3b6fb5" : "#2d2d2d"};color:#ddd;border:1px solid #444;border-radius:6px;padding:5px 12px;cursor:pointer;font-size:12px;`;
                b.addEventListener("mouseenter", () => (b.style.background = primary ? "#487fc8" : "#3a3a3a"));
                b.addEventListener("mouseleave", () => (b.style.background = primary ? "#3b6fb5" : "#2d2d2d"));
            });
        }
        this.setLoading(true);
        dialog.focus();
        $("oi-pan").oninput = (event) => {
            this.viewStart = Number(event.target.value);
            this.render();
        };
        $("oi-play-all").onclick = () => this.playResult();
        $("oi-play-seg").onclick = () => this.playSelected();
        $("oi-stop").onclick = () => this.stopPlayback();
        $("oi-zoom-in").onclick = () => this.zoom(0.6);
        $("oi-zoom-out").onclick = () => this.zoom(1 / 0.6);
        $("oi-fit").onclick = () => {
            this.fitView();
            this.render();
        };
        $("oi-clear").onclick = () => {
            this.stopPlayback();
            this.segments = [];
            this.selected = -1;
            this.render();
        };
        $("oi-cancel").onclick = () => this.close();
        $("oi-apply").onclick = () => this.apply();

        const canvas = this.elements.wave;
        canvas.addEventListener("pointerdown", (e) => this.pointerDown(e));
        canvas.addEventListener("pointercancel", () => this.pointerUp());
        window.addEventListener("pointermove", this._moveHandler = (e) => this.pointerMove(e));
        window.addEventListener("pointerup", this._upHandler = () => this.pointerUp());
        canvas.addEventListener("wheel", (e) => {
            e.preventDefault();
            this.zoom(e.deltaY < 0 ? 0.8 : 1 / 0.8, e);
        }, { passive: false });
        window.addEventListener("keydown", this._keyHandler = (e) => {
            const editing = e.target?.matches?.("input, textarea, select, [contenteditable=true]");
            // Keep dialog shortcuts away from the workflow canvas.
            e.stopPropagation();
            if (e.key === "Escape") {
                e.preventDefault();
                this.close();
            } else if (e.key === "Tab") {
                const controls = [...dialog.querySelectorAll("button:not(:disabled), input:not(:disabled)")];
                const first = controls[0], last = controls.at(-1);
                if (e.shiftKey && (document.activeElement === first || document.activeElement === dialog)) {
                    e.preventDefault(); last?.focus();
                } else if (!e.shiftKey && (document.activeElement === last || document.activeElement === dialog)) {
                    e.preventDefault(); first?.focus();
                }
            } else if (!editing && (e.key === "Delete" || e.key === "Backspace")) {
                e.preventDefault();
                if (this.selected >= 0) {
                    this.stopPlayback();
                    this.segments.splice(this.selected, 1);
                    this.selected = -1;
                    this.render();
                }
            } else if (!editing && e.key === " " && e.target?.tagName !== "BUTTON") {
                e.preventDefault();
                this.playResult();
            }
        }, true);
        this._resizeHandler = () => this.render();
        window.addEventListener("resize", this._resizeHandler);
    }

    close() {
        this.stopPlayback();
        window.removeEventListener("pointermove", this._moveHandler);
        window.removeEventListener("pointerup", this._upHandler);
        window.removeEventListener("keydown", this._keyHandler, true);
        window.removeEventListener("resize", this._resizeHandler);
        this.controller?.abort();
        const context = this.audioCtx;
        this.audioCtx = null;
        if (context && context.state !== "closed") context.close().catch(() => {});
        this.buffer = null;
        this.drag = null;
        this.elements.overlay?.remove();
        this.elements = {};
        this.previousFocus?.focus();
    }

    apply() {
        if (!this.buffer) return;
        if (this.segmentsConnected) {
            alert("Disconnect the segments input before applying edits.");
            return;
        }
        const source = findAudioSourceFile(this.node);
        if (!source || source.filename !== this.sourceFilename || source.node !== this.sourceNode) {
            alert("The audio source changed. Close and reopen the editor before applying.");
            return;
        }
        const widget = this.segmentsWidget;
        if (widget) {
            widget.value = JSON.stringify(
                this.normalizedSegments()
            );
            widget.callback?.(widget.value);
            this.node.setDirtyCanvas?.(true, true);
            this.node.graph?.change();
        }
        this.close();
    }

    // ----- view / zoom ---------------------------------------------------------

    fitView() {
        this.viewStart = 0;
        this.viewDur = this.duration || 1;
    }

    viewRange() {
        return [this.viewStart, Math.min(this.duration, this.viewStart + this.viewDur)];
    }

    zoom(factor, event) {
        if (!this.buffer) return;
        const canvas = this.elements.wave;
        const rect = canvas.getBoundingClientRect();
        const [vs, ve] = this.viewRange();
        const frac = event ? Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)) : 0.5;
        const center = vs + (ve - vs) * frac;
        let newDur = Math.min(this.duration, Math.max(0.05, (ve - vs) * factor));
        let newStart = center - newDur * frac;
        newStart = Math.max(0, Math.min(newStart, this.duration - newDur));
        this.viewStart = newStart;
        this.viewDur = newDur;
        this.render();
    }

    // ----- pointer interactions -------------------------------------------------

    timeAt(e) {
        const rect = this.elements.wave.getBoundingClientRect();
        const [vs, ve] = this.viewRange();
        return vs + (ve - vs) * Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    }

    hitTest(t) {
        const canvas = this.elements.wave;
        const rect = canvas.getBoundingClientRect();
        const [vs, ve] = this.viewRange();
        const pxPerSec = rect.width / (ve - vs);
        for (let i = this.segments.length - 1; i >= 0; i--) {
            const [s, e] = this.segments[i];
            if (Math.abs(t - s) * pxPerSec <= 6) return { index: i, edge: "start" };
            if (Math.abs(t - e) * pxPerSec <= 6) return { index: i, edge: "end" };
            if (t >= s && t <= e) return { index: i, edge: null };
        }
        return null;
    }

    pointerDown(e) {
        if (e.button !== 0 || !this.buffer) return;
        e.preventDefault();
        this.stopPlayback();
        this.elements.wave.setPointerCapture?.(e.pointerId);
        if (e.shiftKey) {
            this.drag = { kind: "pan", startX: e.clientX, viewStart: this.viewStart };
            return;
        }
        const t = this.timeAt(e);
        const hit = this.hitTest(t);
        if (hit) {
            this.selected = hit.index;
            this.drag = {
                kind: hit.edge === "start" ? "resize-start" : hit.edge === "end" ? "resize-end" : "move",
                index: hit.index,
                startT: t,
                orig: [...this.segments[hit.index]],
            };
        } else {
            this.segments.push([t, t]);
            this.selected = this.segments.length - 1;
            this.drag = { kind: "create", index: this.selected, startT: t, orig: [t, t] };
        }
        this.render();
    }

    pointerMove(e) {
        if (!this.drag) return;
        const d = this.drag;
        if (d.kind === "pan") {
            const width = this.elements.wave.getBoundingClientRect().width;
            this.viewStart = Math.max(0, Math.min(this.duration - this.viewDur,
                d.viewStart - (e.clientX - d.startX) / width * this.viewDur));
            this.render();
            return;
        }
        const t = this.timeAt(e);
        const seg = this.segments[d.index];
        if (!seg) return;
        const minDuration = Math.min(0.01, this.duration);
        if (d.kind === "create") {
            seg[0] = Math.min(t, d.startT);
            seg[1] = Math.max(t, d.startT);
        } else if (d.kind === "resize-start") {
            seg[0] = Math.max(0, Math.min(t, seg[1] - minDuration));
        } else if (d.kind === "resize-end") {
            seg[1] = Math.min(this.duration, Math.max(seg[0] + minDuration, t));
        } else if (d.kind === "move") {
            const len = d.orig[1] - d.orig[0];
            let start = t - (d.startT - d.orig[0]);
            start = Math.max(0, Math.min(start, this.duration - len));
            seg[0] = start;
            seg[1] = start + len;
        }
        this.render();
    }

    pointerUp() {
        // Drop degenerate segments created by a click without drag.
        if (this.drag) {
            const seg = this.segments[this.drag.index];
            if (seg && this.drag.kind === "create" && seg[1] - seg[0] < 0.001) {
                this.segments.splice(this.drag.index, 1);
                this.selected = -1;
                this.render();
            }
        }
        this.drag = null;
    }

    // ----- playback --------------------------------------------------------------

    stopPlayback() {
        const sources = this.playing;
        this.playing = [];
        for (const source of sources) {
            source.onended = null;
            try { source.stop(); } catch { /* already ended */ }
            source.disconnect();
        }
        this.render();
    }

    async playSegments(segments) {
        this.stopPlayback();
        if (!this.buffer || !this.audioCtx) return;
        const context = this.audioCtx;
        const buffer = this.buffer;
        // An older resume() must not schedule after Stop, Close, or a newer play.
        const session = this.playing;
        try {
            if (context.state === "suspended") await context.resume();
            if (this.audioCtx !== context || this.playing !== session) return;
            let when = context.currentTime + 0.05;
            for (const [start, end] of segments) {
                const sr = buffer.sampleRate;
                const s = Math.max(0, Math.round(start * sr));
                const e = Math.min(buffer.length, Math.round(end * sr));
                if (e <= s) continue;
                const source = context.createBufferSource();
                source.buffer = buffer;
                source.connect(context.destination);
                source.onended = () => {
                    source.disconnect();
                    this.playing = this.playing.filter((item) => item !== source);
                    this.render();
                };
                source.start(when, s / sr, (e - s) / sr);
                when += (e - s) / sr;
                this.playing.push(source);
            }
            this.render();
        } catch (err) {
            this.stopPlayback();
            if (this.elements.status) this.elements.status.textContent = `Could not play audio: ${err.message}`;
        }
    }

    playRange(start, end) {
        return this.playSegments([[Math.max(0, start), Math.min(this.duration, end)]]);
    }

    playSelected() {
        const seg = this.segments[this.selected];
        if (seg) return this.playRange(seg[0], seg[1]);
    }

    playResult() {
        return this.playSegments(this.normalizedSegments());
    }

    // ----- rendering ---------------------------------------------------------------

    render() {
        const canvas = this.elements.wave;
        if (!canvas || !this.buffer) return;
        const cssWidth = canvas.clientWidth || 800;
        const height = 220;
        const dpr = window.devicePixelRatio || 1;
        canvas.width = cssWidth * dpr;
        canvas.height = height * dpr;
        const ctx = canvas.getContext("2d");
        ctx.scale(dpr, dpr);

        const [vs, ve] = this.viewRange();
        const channel = this.buffer.getChannelData(0);
        const sr = this.buffer.sampleRate;
        const i0 = Math.floor(vs * sr);
        const i1 = Math.ceil(ve * sr);
        const columns = Math.floor(cssWidth);

        ctx.fillStyle = WAVE_BG;
        ctx.fillRect(0, 0, cssWidth, height);

        // waveform
        const mid = (height - 18) / 2;
        const pixelsPerSec = cssWidth / (ve - vs);
        for (let x = 0; x < columns; x++) {
            const a = i0 + Math.floor(((i1 - i0) * x) / columns);
            const b = i0 + Math.floor(((i1 - i0) * (x + 1)) / columns);
            let min = 1, max = -1;
            const step = Math.max(1, Math.floor((b - a) / 50));
            for (let i = a; i < b && i < channel.length; i += step) {
                const v = channel[i];
                if (v < min) min = v;
                if (v > max) max = v;
            }
            if (min > max) continue;
            ctx.fillStyle = WAVE_FG_DIM;
            ctx.fillRect(x, mid - max * (mid - 10), 1, Math.max(1, (max - min) * (mid - 10)));
        }

        // segments
        const y0 = 6, y1 = height - 20;
        this.segments.forEach(([s, e], i) => {
            const x0 = (s - vs) * pixelsPerSec;
            const x1 = (e - vs) * pixelsPerSec;
            const isSel = i === this.selected;
            ctx.fillStyle = isSel ? "rgba(255,180,84,0.20)" : SEGMENT_FILL;
            ctx.fillRect(x0, y0, Math.max(2, x1 - x0), y1 - y0);
            ctx.strokeStyle = isSel ? SEGMENT_SELECTED : SEGMENT_BORDER;
            ctx.lineWidth = isSel ? 2 : 1;
            ctx.strokeRect(x0, y0, Math.max(2, x1 - x0), y1 - y0);
            // edge handles
            ctx.fillStyle = isSel ? SEGMENT_SELECTED : SEGMENT_BORDER;
            ctx.fillRect(x0 - 2, y0, 4, y1 - y0);
            ctx.fillRect(x1 - 2, y0, 4, y1 - y0);
            // label
            ctx.fillStyle = isSel ? SEGMENT_SELECTED : "#9bb8dd";
            ctx.font = "10px sans-serif";
            const label = `#${i + 1} ${formatTime(e - s)}s`;
            ctx.fillText(label, Math.max(2, x0 + 4), y0 + 12);
        });

        // time ruler
        ctx.fillStyle = RULER_BG;
        ctx.fillRect(0, height - 18, cssWidth, 18);
        ctx.fillStyle = "#777";
        ctx.font = "10px sans-serif";
        const targetTicks = 10;
        const rawStep = (ve - vs) / targetTicks;
        const steps = [0.01, 0.02, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
        const step = steps.find((s) => s >= rawStep) || 600;
        for (let t = Math.ceil(vs / step) * step; t <= ve; t += step) {
            const x = (t - vs) * pixelsPerSec;
            ctx.fillRect(x, height - 18, 1, 5);
            ctx.fillText(formatTime(t), x + 3, height - 6);
        }

        this.elements.duration.textContent = this.duration ? `· ${formatTime(this.duration)}s total` : "";
        if (this.elements.pan) {
            this.elements.pan.max = Math.max(0, this.duration - this.viewDur);
            this.elements.pan.value = this.viewStart;
        }
        this.renderList();
    }

    renderList() {
        const list = this.elements.list;
        if (!list) return;
        const kept = this.segments.reduce((acc, [s, e]) => acc + (e - s), 0);
        this.elements.status.textContent = this.playing.length
            ? `Playing… ${this.playing.length} segment(s) remaining`
            : this.segments.length
                ? `${this.segments.length} segment(s) · keeps ${formatTime(kept)}s of ${formatTime(this.duration)}s`
                : "No segments — drag on the waveform to create one.";
        if ((this.editingNumberChange || (list.contains(document.activeElement) && document.activeElement.tagName === "INPUT"))
                && list.children.length === this.segments.length) {
            // Preserve focus and Tab/click targets while numeric edits or playback
            // trigger redraws. Replacing the list here would detach the active input.
            [...list.children].forEach((row, i) => {
                const [s, e] = this.segments[i];
                row.querySelectorAll("input").forEach((input, edge) => {
                    if (input !== document.activeElement) input.value = this.segments[i][edge].toFixed(3);
                });
                row.children[4].textContent = `${(e - s).toFixed(2)}s`;
            });
            return;
        }
        list.innerHTML = "";
        this.segments.forEach(([s, e], i) => {
            const row = document.createElement("div");
            row.style.cssText = "display:flex;gap:6px;align-items:center;margin-bottom:4px;";
            const selected = i === this.selected;
            row.innerHTML = `
                <span style="width:26px;color:${selected ? SEGMENT_SELECTED : "#888"};font-size:12px;">#${i + 1}</span>`;
            const make = (value, onchange) => {
                const input = document.createElement("input");
                input.type = "number";
                input.step = "0.001";
                input.min = "0";
                input.max = String(this.duration);
                input.setAttribute("aria-label", `Segment ${i + 1} ${row.querySelectorAll("input").length ? "end" : "start"}`);
                input.value = value.toFixed(3);
                input.style.cssText =
                    "width:80px;background:#141414;color:#ddd;border:1px solid #444;border-radius:4px;padding:3px 6px;font-size:12px;";
                input.onchange = () => {
                    const edge = [...row.querySelectorAll("input")].indexOf(input);
                    const v = parseFloat(input.value);
                    this.editingNumberChange = true;
                    try {
                        this.stopPlayback();
                        if (Number.isFinite(v)) onchange(v);
                        input.value = this.segments[i][edge].toFixed(3);
                        this.render();
                    } finally {
                        this.editingNumberChange = false;
                    }
                };
                return input;
            };
            row.appendChild(make(s, (v) => { this.segments[i][0] = Math.max(0, Math.min(v, this.segments[i][1] - Math.min(0.01, this.duration))); }));
            const arrow = document.createElement("span");
            arrow.textContent = "→";
            arrow.style.cssText = "color:#666;font-size:11px;";
            row.appendChild(arrow);
            row.appendChild(make(e, (v) => { this.segments[i][1] = Math.min(this.duration, Math.max(v, this.segments[i][0] + Math.min(0.01, this.duration))); }));
            const dur = document.createElement("span");
            dur.textContent = `${(this.segments[i][1] - this.segments[i][0]).toFixed(2)}s`;
            dur.style.cssText = "color:#888;font-size:12px;width:52px;";
            row.appendChild(dur);
            const play = document.createElement("button");
            play.textContent = "▶";
            play.style.cssText = "background:#2d2d2d;color:#ddd;border:1px solid #444;border-radius:4px;padding:2px 8px;cursor:pointer;font-size:11px;";
            play.onclick = () => this.playRange(this.segments[i][0], this.segments[i][1]);
            row.appendChild(play);
            const del = document.createElement("button");
            del.textContent = "✕";
            del.style.cssText = "background:#2d2d2d;color:#e77;border:1px solid #444;border-radius:4px;padding:2px 8px;cursor:pointer;font-size:11px;";
            del.onclick = () => {
                this.stopPlayback();
                this.segments.splice(i, 1);
                if (this.selected === i) this.selected = -1;
                else if (this.selected > i) this.selected--;
                this.render();
            };
            row.appendChild(del);
            row.addEventListener("mousedown", () => {
                if (this.selected !== i) {
                    this.selected = i;
                    // Do not replace a number input while it is receiving focus.
                    [...list.children].forEach((child, index) => {
                        child.firstElementChild.style.color = index === i ? SEGMENT_SELECTED : "#888";
                    });
                }
            });
            list.appendChild(row);
        });
    }
}

app.registerExtension({
    name: "Mosael.AudioSegmentsEditor",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== EDITED_NODE) return;
        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            const editor = new AudioSegmentsEditor(this);
            const onRemoved = this.onRemoved;
            this.onRemoved = function () {
                editor.close();
                return onRemoved?.apply(this, arguments);
            };
            const button = this.addWidget("button", "✂ Open visual editor", null, () => {
                editor.open();
            });
            button.serialize = false;
        };
    },
});
