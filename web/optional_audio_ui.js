/**
 * Companion frontend extension for the plugin's audio nodes.
 *
 * Why this exists: the core frontend's `Comfy.UploadAudio` extension adds an
 * upload widget to ANY node whose `audio` combo carries `audio_upload: true`,
 * but the matching `audioUI` player widget is only injected for a hardcoded
 * list of stock node classes (`LoadAudio`, `PreviewAudio`, ...). Without an
 * `audioUI` widget the upload widget throws when the node is added to the
 * canvas, so "Optional Load Audio" fails to load.
 *
 * This extension mirrors the core injection for our node: add an `audioUI`
 * input so the stock AUDIO_UI / AUDIOUPLOAD widgets find each other. The
 * `audioUI` input must be inserted BEFORE the injected `upload` input,
 * because the AUDIOUPLOAD widget is created in input order and immediately
 * looks up the `audioUI` widget. No core files are modified and no APIs are
 * monkey-patched.
 */
import { app } from "../../scripts/app.js";

const OUR_AUDIO_NODES = new Set(["Optional Load Audio"]);

app.registerExtension({
    name: "Mosael.OptionalAudioUI",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!OUR_AUDIO_NODES.has(nodeData?.name)) return;
        const required = nodeData.input?.required;
        if (
            required?.audio?.[1]?.audio_upload !== true ||
            required.audioUI !== undefined
        ) {
            return;
        }
        // Re-insert the injected upload input (if any) after audioUI so the
        // widget creation order is audio, ..., audioUI, upload.
        const upload = required.upload;
        delete required.upload;
        required.audioUI = ["AUDIO_UI", {}];
        if (upload !== undefined) {
            required.upload = upload;
        }
    },
});
