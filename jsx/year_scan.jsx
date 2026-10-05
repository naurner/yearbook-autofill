// Finds year texts (19xx/20xx) in every text layer, including text inside smart objects (recursively),
// and optionally replaces them. JOB: {pages: [{page, psd}], replace: {"2024": "2026", ...} | null,
// save: bool}. With save=false nothing is written (scan only). Requires common.jsx.

var YEAR = /(19|20)\d\d|\b\d\d\b/;

function selectLayer(layer) {
    var ref = new ActionReference();
    ref.putIdentifier(cTID("Lyr "), layer.id);
    var d = new ActionDescriptor();
    d.putReference(cTID("null"), ref);
    d.putBoolean(cTID("MkVs"), false);
    executeAction(cTID("slct"), d, DialogModes.NO);
}

function isSmart(layer) {
    return layer.typename === "ArtLayer" && String(layer.kind) === String(LayerKind.SMARTOBJECT);
}

function replaceIn(text, map) {
    var out = text;
    for (var k in map) if (map.hasOwnProperty(k)) out = out.split(k).join(map[k]);
    return out;
}

// Walks doc; returns [{where, text, changed}]. Smart objects are opened, walked, saved (if changed & save).
function walk(doc, layers, where, found) {
    var changed = false;
    for (var i = 0; i < layers.length; i++) {
        var layer = layers[i];
        var here = where + "/" + layer.name;
        if (layer.typename === "LayerSet") {
            if (walk(doc, layer.layers, here, found)) changed = true;
            continue;
        }
        if (isTextLayer(layer)) {
            var t = layer.textItem.contents;
            if (YEAR.test(t)) {
                var rec = {where: here, text: t};
                if (JOB.replace) {
                    var nt = replaceIn(t, JOB.replace);
                    if (nt !== t) { layer.textItem.contents = nt; rec.now = nt; changed = true; }
                }
                found.push(rec);
            }
        } else if (isSmart(layer)) {
            app.activeDocument = doc;
            selectLayer(layer);
            executeAction(sTID("placedLayerEditContents"), new ActionDescriptor(), DialogModes.NO);
            var inner = app.activeDocument;
            var innerChanged = false;
            try {
                innerChanged = walk(inner, inner.layers, here + "[SO]", found);
                if (innerChanged && JOB.save) inner.save();
            } finally {
                inner.close(SaveOptions.DONOTSAVECHANGES);
            }
            app.activeDocument = doc;
            if (innerChanged) changed = true;
        }
    }
    return changed;
}

var result = {pages: []};
for (var p = 0; p < JOB.pages.length; p++) {
    var pg = JOB.pages[p], doc = null;
    try {
        doc = openLayered(new File(pg.psd));
        var found = [];
        var changed = walk(doc, doc.layers, "", found);
        if (changed && JOB.save) doc.save();
        doc.close(SaveOptions.DONOTSAVECHANGES);
        doc = null;
        result.pages.push({page: pg.page, ok: true, found: found, changed: changed});
        progress("OK " + pg.page + " found=" + found.length + " changed=" + changed);
    } catch (e) {
        result.pages.push({page: pg.page, ok: false, error: String(e) + (e.line ? " (line " + e.line + ")" : "")});
        progress("ERROR " + pg.page + ": " + e);
        if (doc) { try { doc.close(SaveOptions.DONOTSAVECHANGES); } catch (e2) {} }
    }
}
finish(result);
