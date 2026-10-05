// Dumps each page's leaf layers to <outDir>/<page>.json plus a flattened <page>_preview.jpg.
// JOB: {psdDir, pages: [...], outDir, previewWidth, workDir}. Requires common.jsx.

// Number of character-style runs and rotation in degrees (from the text transform matrix;
// 0 when the layer has no transform). Rotation is null if it could not be read.
function textInfo(layer) {
    var info = {styleRuns: -1, rotation: null};
    try {
        var ref = new ActionReference();
        ref.putIdentifier(cTID("Lyr "), layer.id);
        var tk = executeActionGet(ref).getObjectValue(sTID("textKey"));
        info.styleRuns = tk.getList(sTID("textStyleRange")).count;
        info.rotation = 0;
        if (tk.hasKey(sTID("transform"))) {
            var t = tk.getObjectValue(sTID("transform"));
            info.rotation = Math.atan2(t.getDouble(sTID("xy")), t.getDouble(sTID("xx"))) * 180 / Math.PI;
        }
    } catch (e) {}
    return info;
}

function sizeOf(ti) {
    try { var s = ti.size; return (s && s.value !== undefined) ? s.value : Number(s); } catch (e) { return null; }
}

function collectLeaves(layers, prefix, parents, parentVisible, out) {
    for (var i = 0; i < layers.length; i++) {
        var layer = layers[i], path = prefix.concat([i]);
        var vis = parentVisible && layer.visible;
        if (layer.typename === "LayerSet") {
            collectLeaves(layer.layers, path, parents.concat([layer.name]), vis, out);
            continue;
        }
        var item = {path: path, name: layer.name, parents: parents, visible: layer.visible,
                    parentVisible: parentVisible, effectiveVisible: vis, kind: "other"};
        try { item.bounds = boundsObj(layer); } catch (e) { continue; }
        if (isTextLayer(layer)) {
            var ti = layer.textItem;
            item.kind = "text";
            item.text = ti.contents;
            try { item.font = ti.font; } catch (e1) { item.font = null; }
            item.size = sizeOf(ti);
            try { item.justification = String(ti.justification); } catch (e2) { item.justification = ""; }
            try { item.textKind = String(ti.kind); } catch (e3) { item.textKind = ""; }
            var info = textInfo(layer);
            item.styleRuns = info.styleRuns;
            item.rotation = info.rotation;
        } else {
            try { item.kind = String(layer.kind).replace("LayerKind.", "").toLowerCase(); } catch (e4) {}
        }
        out.push(item);
    }
}

function savePreview(doc, path, width) {
    stripAncestors(doc);
    doc.flatten();
    if (String(doc.bitsPerChannel) !== String(BitsPerChannelType.EIGHT)) doc.bitsPerChannel = BitsPerChannelType.EIGHT;
    if (String(doc.mode) !== String(DocumentMode.RGB)) doc.changeMode(ChangeMode.RGB);
    var w = px(doc.width), h = px(doc.height);
    if (w > width) {
        doc.resizeImage(UnitValue(width, "px"), UnitValue(Math.round(h * width / w), "px"),
                        doc.resolution, ResampleMethod.BICUBIC);
    }
    var jpg = new JPEGSaveOptions();
    jpg.quality = 8;
    doc.saveAs(new File(path), jpg, true, Extension.LOWERCASE);
}

var result = {pages: []};
for (var p = 0; p < JOB.pages.length; p++) {
    var pageName = JOB.pages[p], doc = null;
    try {
        var psdFile = new File(JOB.psdDir + "/" + pageName + ".psd");
        if (isAlreadyOpen(psdFile)) throw new Error("template is open in Photoshop, close it: " + psdFile.fsName);
        doc = openLayered(psdFile);
        var layout = {page: pageName, width: px(doc.width), height: px(doc.height),
                      resolution: doc.resolution, mode: String(doc.mode), leaves: []};
        collectLeaves(doc.layers, [], [], true, layout.leaves);
        writeText(JOB.outDir + "/" + pageName + ".json", toJSON(layout), false);
        savePreview(doc, JOB.outDir + "/" + pageName + "_preview.jpg", JOB.previewWidth);
        doc.close(SaveOptions.DONOTSAVECHANGES);
        doc = null;
        result.pages.push({page: pageName, ok: true, leaves: layout.leaves.length});
        progress("OK " + pageName + " leaves=" + layout.leaves.length);
    } catch (e) {
        result.pages.push({page: pageName, ok: false, error: String(e)});
        progress("ERROR " + pageName + ": " + e);
        if (doc) { try { doc.close(SaveOptions.DONOTSAVECHANGES); } catch (e2) {} }
    }
}
finish(result);
