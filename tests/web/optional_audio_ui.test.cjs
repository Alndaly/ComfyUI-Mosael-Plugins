const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function extension() {
    let result;
    const source = fs.readFileSync(path.join(__dirname, '../../web/optional_audio_ui.js'), 'utf8').replace(/^import .*;\s*$/gm, '');
    vm.runInNewContext(source, { app: { registerExtension(value) { result = value; } } });
    return result;
}

function playerNode(type) {
    const state = { cleared: 0, paused: 0, loaded: 0, callbacks: 0, executed: 0 };
    const audioUI = {
        name: 'audioUI', value: 'old.wav', element: {
            pause() { state.paused++; },
            removeAttribute(name) { if (name === 'src') state.cleared++; },
            load() { state.loaded++; }, classList: { add() {} },
        },
    };
    const audio = { name: 'audio', value: 'none', callback() { state.callbacks++; } };
    const node = { comfyClass: type, widgets: [audio, audioUI], onExecuted() { state.executed++; } };
    return { state, audio, audioUI, node };
}

test('preview gets the stock AUDIO_UI widget despite having no upload input', async () => {
    const data = { name: 'Optional Audio Preview', input: { required: { condition: ['BOOLEAN', {}] } } };
    await extension().beforeRegisterNodeDef({}, data);
    assert.equal(data.input.required.audioUI?.[0], 'AUDIO_UI');
});

test('loader injects audio UI before upload and leaves existing UI alone', async () => {
    const data = { name: 'Optional Load Audio', input: { required: { audio: [['none'], { audio_upload: true }], upload: ['AUDIOUPLOAD', {}] } } };
    const ext = extension();
    await ext.beforeRegisterNodeDef({}, data);
    assert.deepEqual(Object.keys(data.input.required), ['audio', 'audioUI', 'upload']);
    const widget = data.input.required.audioUI;
    await ext.beforeRegisterNodeDef({}, data);
    assert.equal(data.input.required.audioUI, widget);
});

test('none hides the loader player; real filenames retain the stock callback', () => {
    const { node, audio, audioUI, state } = playerNode('Optional Load Audio');
    extension().nodeCreated(node);
    assert.equal(audioUI.value, '');
    audio.callback('none');
    assert.equal(state.callbacks, 0);
    audio.value = 'clip.flac';
    audio.callback('clip.flac');
    assert.equal(state.callbacks, 1);
    audio.value = 'none';
    node.onGraphConfigured();
    assert.ok(state.cleared >= 2);
});

test('preview clears stale playback for an empty result and preserves other hooks', () => {
    const { node, audioUI, state } = playerNode('Optional Audio Preview');
    extension().nodeCreated(node);
    node.onExecuted({ audio: [{ filename: 'new.flac' }] });
    assert.equal(state.executed, 1);
    node.onExecuted({ audio: [] });
    assert.equal(state.executed, 2);
    assert.equal(audioUI.value, '');
    assert.equal(state.paused, 1);
    assert.equal(state.cleared, 1);
});
