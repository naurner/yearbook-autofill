// Writes Photoshop's own document JSON (layer tree, bounds, clipping, full text styles) per page.
// JOB: {pages: [{page, psd}], outDir, workDir}. Requires common.jsx.

function documentJSON() {
    var ref = new ActionReference();
    ref.putProperty(cTID("Prpr"), sTID("json"));
    ref.putEnumerated(sTID("document"), cTID("Ordn"), cTID("Trgt"));
    var desc = new ActionDescriptor();
    desc.putReference(cTID("null"), ref);
    desc.putBoolean(sTID("expandSmartObjects"), false);
    desc.putBoolean(sTID("getTextStyles"), true);
    desc.putBoolean(sTID("getFullTextStyles"), true);
    desc.putBoolean(sTID("getDefaultLayerFX"), false);
    desc.putBoolean(sTID("getPathData"), false);
    return executeAction(cTID("getd"), desc, DialogModes.NO).getString(sTID("json"));
}

var result = {pages: []};
for (var p = 0; p < JOB.pages.length; p++) {
    var pg = JOB.pages[p], doc = null;
    try {
        var file = new File(pg.psd);
        if (isAlreadyOpen(file)) throw new Error("template is open in Photoshop, close it: " + file.fsName);
        doc = openLayered(file);
        writeText(JOB.outDir + "/" + pg.page + ".doc.json", documentJSON(), false);
        doc.close(SaveOptions.DONOTSAVECHANGES);
        doc = null;
        result.pages.push({page: pg.page, ok: true});
        progress("OK json " + pg.page);
    } catch (e) {
        result.pages.push({page: pg.page, ok: false, error: String(e)});
        progress("ERROR " + pg.page + ": " + e);
        if (doc) { try { doc.close(SaveOptions.DONOTSAVECHANGES); } catch (e2) {} }
    }
}
finish(result);
