const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function load() {
    const code = fs.readFileSync(path.join(__dirname, '../../web/audio_segments_editor.js'), 'utf8')
        .replace(/^import .*;\s*$/gm, '');
    const app = { graph: { links: {}, getNodeById() {} }, registerExtension(extension) { this.extension = extension; } };
    const scope = {
        app, api: { apiURL: (url) => '/comfy' + url }, URLSearchParams,
        console, AbortController, window: { removeEventListener() {} },
    };
    vm.createContext(scope);
    vm.runInContext(code + '\nthis.exports = { AudioSegmentsEditor, parseSegments, findAudioSourceFile, viewUrl };', scope);
    return { ...scope.exports, scope, app };
}

function player() {
    const { AudioSegmentsEditor } = load();
    const editor = new AudioSegmentsEditor({ widgets: [] });
    editor.duration = 10;
    editor.buffer = { duration: 10, sampleRate: 1000, length: 10000 };
    editor.render = () => {};
    editor.elements.status = {};
    const sources = [];
    editor.audioCtx = {
        state: 'running', currentTime: 0, destination: {},
        createBufferSource() {
            const source = { connect() {}, disconnect() {}, start(...args) { this.args = args; }, stop() { this.stopped = true; } };
            sources.push(source);
            return source;
        },
    };
    return { editor, sources };
}

test('stop still stops later segments after the first one ends', async () => {
    const { editor, sources } = player();
    editor.segments = [[0, 1], [2, 3], [4, 5]];
    await editor.playResult();
    sources[0].onended();
    editor.stopPlayback();
    assert.equal(sources[1].stopped, true);
    assert.equal(sources[2].stopped, true);
});

test('preview follows backend chronological order after manual edits', async () => {
    const { editor, sources } = player();
    editor.segments = [[7, 8], [1, 2]];
    await editor.playResult();
    assert.equal(sources[0].args[1], 1);
    assert.equal(sources[1].args[1], 7);
});

test('bad JSON raises instead of silently replacing segments with empty data', () => {
    const { parseSegments } = load();
    assert.throws(() => parseSegments('[[1, 2]'), /JSON/);
});

test('source lookup refuses audio whose timing has been transformed', () => {
    const { findAudioSourceFile, app } = load();
    const loader = { id: 1, type: 'Optional Load Audio', widgets: [{ name: 'audio', value: 'clip.wav' }] };
    const quickEdit = { id: 2, type: 'Quick Audio Edit', inputs: [{ name: 'audio', type: 'AUDIO', link: 1 }] };
    const trim = { id: 3, inputs: [{ name: 'audio', type: 'AUDIO', link: 2 }] };
    app.graph.links = { 1: { origin_id: 1 }, 2: { origin_id: 2 } };
    app.graph.getNodeById = (id) => ({ 1: loader, 2: quickEdit })[id];
    assert.equal(findAudioSourceFile(trim), null);
});

test('close releases the AudioContext', () => {
    const { editor } = player();
    let closed = false;
    editor.audioCtx.close = async () => { closed = true; };
    editor.close();
    assert.equal(closed, true);
});

test('accepts trailing commas and objects, excludes degenerate pairs', () => {
    const { parseSegments } = load();
    const parsed = parseSegments('[{"start":3,"end":4},[1,2,],[0,0],]');
    assert.equal(JSON.stringify(parsed), '[[1,2],[3,4]]');
    for (const input of ['{}', '[[null,1]]', '[[false,1]]', '[["bad",2]]', '[[1]]']) {
        assert.throws(() => parseSegments(input));
    }
});

test('source lookup uses the node graph and permits reroutes, handles cycles', () => {
    const { findAudioSourceFile } = load();
    const loader = { id: 1, type: 'LoadAudio', widgets: [{ name: 'audio', value: 'sub/tone.wav' }] };
    const reroute = { id: 2, type: 'Reroute', inputs: [{ link: 1 }] };
    const graph = { links: { 1: { origin_id: 1 }, 2: { origin_id: 2 } }, getNodeById: (id) => ({ 1: loader, 2: reroute })[id] };
    const trim = { id: 3, graph, inputs: [{ name: 'audio', type: 'AUDIO', link: 2 }] };
    assert.equal(findAudioSourceFile(trim).filename, 'sub/tone.wav');
    loader.widgets[0].value = 'none';
    assert.equal(findAudioSourceFile(trim), null);
    graph.links[1].origin_id = 2;
    assert.equal(findAudioSourceFile(trim), null);
});

test('view URL encodes filenames and respects storage annotations', () => {
    const { viewUrl } = load();
    const parsed = new URL(viewUrl('sub\\a &b.wav [output]'), 'http://test');
    assert.equal(parsed.pathname, '/view');
    assert.equal(parsed.searchParams.get('filename'), 'a &b.wav');
    assert.equal(parsed.searchParams.get('subfolder'), 'sub');
    assert.equal(parsed.searchParams.get('type'), 'output');
});

test('normalization clips and sorts without merging overlapping ranges', () => {
    const { editor } = player();
    editor.segments = [[8, 12], [-1, 2], [1.23456, 3], [12, 13], [2, 2]];
    assert.equal(JSON.stringify(editor.normalizedSegments()), '[[0,2],[1.235,3],[8,10]]');
});

test('Stop cancels playback awaiting a suspended AudioContext', async () => {
    const { editor, sources } = player();
    let resume;
    editor.audioCtx.state = 'suspended';
    editor.audioCtx.resume = () => new Promise((resolve) => { resume = resolve; });
    editor.segments = [[0, 1]];
    const pending = editor.playResult();
    editor.stopPlayback();
    resume();
    await pending;
    assert.equal(sources.length, 0);
});

test('playback rounds to sample boundaries and schedules contiguous chunks', async () => {
    const { editor, sources } = player();
    editor.segments = [[0.001, 0.011], [1, 1.025]];
    await editor.playResult();
    assert.equal(sources[0].args[1], 0.001);
    assert.equal(sources[0].args[2], 0.01);
    assert.ok(Math.abs(sources[1].args[0] - sources[0].args[0] - 0.01) < 1e-10);
    sources[0].onended();
    assert.equal(editor.playing.length, 1);
    sources[1].onended();
    assert.equal(editor.playing.length, 0);
});

test('closing while decoding aborts and never publishes a late audio buffer', async () => {
    const { AudioSegmentsEditor, scope } = load();
    const editor = new AudioSegmentsEditor({ widgets: [] });
    editor.render = () => {};
    editor.controller = new AbortController();
    scope.api.fetchApi = async () => ({ ok: true, arrayBuffer: async () => new ArrayBuffer(0) });
    let resolveDecode, started;
    const startedPromise = new Promise((resolve) => { started = resolve; });
    let closed = false;
    scope.window.AudioContext = class {
        state = 'running';
        decodeAudioData() { started(); return new Promise((resolve) => { resolveDecode = resolve; }); }
        async close() { closed = true; }
    };
    const pending = editor.loadAudio('tone.wav');
    await startedPromise;
    editor.close();
    resolveDecode({ duration: 8 });
    await pending;
    assert.equal(closed, true);
    assert.equal(editor.buffer, null);
    assert.equal(editor.controller.signal.aborted, true);
});

test('an old open request cannot enable a newly opened dialog', async () => {
    const { AudioSegmentsEditor, app } = load();
    app.graph.links[1] = { origin_id: 1 };
    app.graph.getNodeById = () => ({ id: 1, type: 'LoadAudio', widgets: [{ name: 'audio', value: 'tone.wav' }] });
    const editor = new AudioSegmentsEditor({ inputs: [{ name: 'audio', type: 'AUDIO', link: 1 }], widgets: [] });
    editor.render = () => {};
    editor.buildDialog = () => { editor.elements.overlay = { remove() {} }; };
    const pending = [];
    editor.loadAudio = () => new Promise((resolve) => pending.push(resolve));
    let enabled = 0;
    editor.setLoading = () => { enabled++; };
    const first = editor.open();
    editor.close();
    const second = editor.open();
    pending[0]();
    await first;
    assert.equal(enabled, 0);
    pending[1]();
    await second;
    assert.equal(enabled, 1);
});

test('extension adds a non-serialized button and preserves node hooks', async () => {
    const { app } = load();
    let created = 0, removed = 0;
    class Node {
        onNodeCreated() { created++; }
        onRemoved() { removed++; }
        addWidget(type, name, value, callback) { this.button = { type, callback }; return this.button; }
    }
    await app.extension.beforeRegisterNodeDef(Node, { name: 'Audio Trim by Segments' });
    const node = new Node();
    node.onNodeCreated();
    assert.equal(node.button.serialize, false);
    node.onRemoved();
    assert.equal(created, 1);
    assert.equal(removed, 1);
});

test('numeric edit redraw keeps the existing input elements', () => {
    const { AudioSegmentsEditor, scope } = load();
    const inputs = [{ value: '0' }, { value: '1' }];
    const row = { children: [{}, {}, {}, {}, {}], querySelectorAll: () => inputs };
    const list = { children: [row], contains: () => false };
    Object.defineProperty(list, 'innerHTML', { set() { throw new Error('numeric editing must not replace the focused input'); } });
    scope.document = { activeElement: {} }; // During blur/change, focus is temporarily on body.
    const editor = new AudioSegmentsEditor({ widgets: [] });
    editor.elements = { list, status: {} };
    editor.duration = 4;
    editor.segments = [[0.5, 2]];
    editor.editingNumberChange = true;
    editor.renderList();
    assert.equal(inputs[0].value, '0.500');
    assert.equal(row.children[4].textContent, '1.50s');
});

test('Apply persists clipped chronological ranges and invokes the widget callback', () => {
    const { AudioSegmentsEditor, app } = load();
    const loader = { id: 1, type: 'LoadAudio', widgets: [{ name: 'audio', value: 'tone.wav' }] };
    app.graph.links[1] = { origin_id: 1 };
    app.graph.getNodeById = () => loader;
    let callback, changes = 0;
    const widget = { name: 'segments', value: '[]', callback(value) { callback = value; } };
    const node = { inputs: [{ name: 'audio', type: 'AUDIO', link: 1 }], widgets: [widget], graph: app.graph };
    node.graph.change = () => { changes++; };
    const editor = new AudioSegmentsEditor(node);
    editor.buffer = {};
    editor.duration = 8;
    editor.sourceNode = loader;
    editor.sourceFilename = 'tone.wav';
    editor.segments = [[6, 10], [1.23456, 3]];
    let closed = false;
    editor.close = () => { closed = true; };
    editor.apply();
    assert.equal(widget.value, '[[1.235,3],[6,8]]');
    assert.equal(callback, widget.value);
    assert.equal(changes, 1);
    assert.equal(closed, true);
});

test('Apply refuses connected segments or a changed source without overwriting text', () => {
    const { AudioSegmentsEditor, scope, app } = load();
    const alerts = [];
    scope.alert = (text) => alerts.push(text);
    const widget = { name: 'segments', value: '[[1,2]]' };
    const node = { widgets: [widget], inputs: [{ name: 'segments', link: 42 }] };
    const editor = new AudioSegmentsEditor(node);
    editor.buffer = {};
    editor.apply();
    node.inputs = [{ name: 'audio', type: 'AUDIO', link: 1 }];
    app.graph.links[1] = { origin_id: 1 };
    app.graph.getNodeById = () => ({ id: 1, type: 'LoadAudio', widgets: [{ name: 'audio', value: 'other.wav' }] });
    editor.apply();
    assert.equal(alerts.length, 2);
    assert.equal(widget.value, '[[1,2]]');
});
