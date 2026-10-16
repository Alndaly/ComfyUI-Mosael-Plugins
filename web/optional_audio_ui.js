/** Install the stock audio player for plugin loaders and previews.
 * AUDIOUPLOAD requires AUDIO_UI to be created first. The stock frontend
 * only adds it for its own node names, so use the same extension hook here.
 */
import { app } from "../../scripts/app.js";

const OUR_AUDIO_NODES = new Set(["Optional Load Audio", "Optional Audio Preview"]);

function clearPlayer(node) {
    const widget = node.widgets?.find((w) => w.name === "audioUI");
    if (!widget?.element) return;
    widget.element.pause();
    widget.element.removeAttribute("src");
    widget.element.load();
    widget.element.classList.add("empty-audio-widget");
    widget.value = "";
    widget.callback?.("");
}

app.registerExtension({
    name: "Mosael.OptionalAudioUI",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!OUR_AUDIO_NODES.has(nodeData?.name)) return;
        const required = nodeData.input?.required;
        if (!required || required.audioUI !== undefined) return;
        // The player must precede any upload widget injected by ComfyUI.
        const upload = required.upload;
        delete required.upload;
        required.audioUI = ["AUDIO_UI", {}];
        if (upload !== undefined) required.upload = upload;
    },
    nodeCreated(node) {
        const type = node.comfyClass || node.type;
        if (type === "Optional Load Audio") {
            const audio = node.widgets?.find((w) => w.name === "audio");
            if (!audio) return;
            const callback = audio.callback;
            audio.callback = function () {
                if (audio.value === "none") clearPlayer(node);
                else return callback?.apply(this, arguments);
            };
            const onGraphConfigured = node.onGraphConfigured;
            node.onGraphConfigured = function () {
                const result = onGraphConfigured?.apply(this, arguments);
                if (audio.value === "none") clearPlayer(this);
                return result;
            };
            if (audio.value === "none") clearPlayer(node);
        } else if (type === "Optional Audio Preview") {
            const onExecuted = node.onExecuted;
            node.onExecuted = function (output) {
                const result = onExecuted?.apply(this, arguments);
                if (output.audio?.length === 0) clearPlayer(this);
                return result;
            };
        }
    },
});
