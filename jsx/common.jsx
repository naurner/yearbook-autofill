// Shared helpers for autofill workers; run.jsx loads this before the worker.
// ASCII only: Photoshop misreads non-ASCII string literals in .jsx files.
app.displayDialogs = DialogModes.NO;
app.preferences.rulerUnits = Units.PIXELS;
app.preferences.typeUnits = TypeUnits.POINTS;

function cTID(s) { return charIDToTypeID(s); }
function sTID(s) { return stringIDToTypeID(s); }

function pad4(n) { var h = n.toString(16); while (h.length < 4) h = "0" + h; return h; }

function jsonQuote(s) {
    s = String(s);
    var out = '"';
    for (var i = 0; i < s.length; i++) {
        var c = s.charAt(i), code = s.charCodeAt(i);
        if (c === "\\") out += "\\\\";
        else if (c === '"') out += '\\"';
        else if (code < 0x20 || code === 0x2028 || code === 0x2029) out += "\\u" + pad4(code);
        else out += c;
    }
    return out + '"';
}

function toJSON(v) {
    if (v === null || v === undefined) return "null";
    var t = typeof v, parts = [], i;
    if (t === "number") return isFinite(v) ? String(v) : "null";
    if (t === "boolean") return v ? "true" : "false";
    if (t === "string") return jsonQuote(v);
    if (v instanceof Array) {
        for (i = 0; i < v.length; i++) parts.push(toJSON(v[i]));
        return "[" + parts.join(",") + "]";
    }
    for (var k in v) if (v.hasOwnProperty(k)) parts.push(jsonQuote(k) + ":" + toJSON(v[k]));
    return "{" + parts.join(",") + "}";
}

function writeText(path, text, append) {
    var f = new File(path);
    f.encoding = "UTF-8";
    f.open(append ? "a" : "w");
    f.write(text);
    f.close();
}

function progress(msg) { writeText(JOB.workDir + "/progress.log", msg + "\n", true); }

function finish(result) {
    writeText(JOB.workDir + "/result.json", toJSON(result), false);
    writeText(JOB.workDir + "/done", "ok", false);
}

function px(v) { return v.as("px"); }

function boundsObj(layer) {
    var b = layer.bounds;
    return {left: px(b[0]), top: px(b[1]), right: px(b[2]), bottom: px(b[3])};
}

function layerByPath(doc, path) {
    var coll = doc.layers, layer = null;
    for (var i = 0; i < path.length; i++) {
        if (!coll || path[i] >= coll.length) return null;
        layer = coll[path[i]];
        coll = (layer.typename === "LayerSet") ? layer.layers : null;
    }
    return layer;
}

function isTextLayer(layer) {
    return layer.typename === "ArtLayer" && String(layer.kind) === String(LayerKind.TEXT);
}

// Templates assembled from many files carry a huge photoshop:DocumentAncestors list in XMP
// (100k+ entries, ~7 MB) that gets copied into every saved file. Drop it before saving copies.
function stripAncestors(doc) {
    try {
        if (ExternalObject.AdobeXMPScript == undefined) ExternalObject.AdobeXMPScript = new ExternalObject("lib:AdobeXMPScript");
        var xmp = new XMPMeta(doc.xmpMetadata.rawData);
        xmp.deleteProperty(XMPConst.NS_PHOTOSHOP, "DocumentAncestors");
        doc.xmpMetadata.rawData = xmp.serialize();
        return true;
    } catch (e) { return false; }
}

// Under memory pressure Photoshop may silently open only the flattened composite of a big PSD
// (a single Background layer). Retry once, then fail loudly instead of producing an empty page.
function openLayered(file) {
    for (var attempt = 0; attempt < 2; attempt++) {
        var doc = app.open(file);
        var flat = doc.layers.length === 1 && doc.layers[0].typename === "ArtLayer" && doc.layers[0].isBackgroundLayer;
        if (!flat) return doc;
        doc.close(SaveOptions.DONOTSAVECHANGES);
        $.sleep(3000);
    }
    throw new Error("Photoshop opened only the flat composite of " + file.fsName +
                    " (layers not read) - restart Photoshop and run again");
}

function isAlreadyOpen(file) {
    for (var i = 0; i < app.documents.length; i++) {
        try { if (app.documents[i].fullName.fsName === file.fsName) return true; } catch (e) {}
    }
    return false;
}
