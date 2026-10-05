// Exports groups of leaf layers (by layer id) as transparent PNGs at preview size.
// JOB: {pages: [{page, psd, width, height, outDir, exports: [{name, ids: [..]}]}], workDir}.
// Only leaf visibility changes; the document is closed unsaved.

function collectLeaves(layers, out) {
    for (var i = 0; i < layers.length; i++) {
        var layer = layers[i];
        if (layer.typename === "LayerSet") collectLeaves(layer.layers, out);
        else out.push(layer);
    }
}

function exportPNG(doc, path) {
    var png = new PNGSaveOptions();
    png.compression = 1;
    png.interlaced = false;
    doc.saveAs(new File(path), png, true, Extension.LOWERCASE);
}

var result = {pages: []};
for (var p = 0; p < JOB.pages.length; p++) {
    var pg = JOB.pages[p], doc = null, done = 0;
    try {
        var file = new File(pg.psd);
        if (isAlreadyOpen(file)) throw new Error("template is open in Photoshop, close it: " + file.fsName);
        doc = openLayered(file);
        if (String(doc.bitsPerChannel) !== String(BitsPerChannelType.EIGHT)) doc.bitsPerChannel = BitsPerChannelType.EIGHT;
        doc.resizeImage(UnitValue(pg.width, "px"), UnitValue(pg.height, "px"), doc.resolution, ResampleMethod.BICUBIC);
        var leaves = [];
        collectLeaves(doc.layers, leaves);
        var ids = [], vis = [];
        for (var i = 0; i < leaves.length; i++) { ids.push(leaves[i].id); vis.push(leaves[i].visible); }
        for (var e = 0; e < pg.exports.length; e++) {
            var ex = pg.exports[e], want = {};
            for (var k = 0; k < ex.ids.length; k++) want[ex.ids[k]] = true;
            for (i = 0; i < leaves.length; i++) {
                var on = want[ids[i]] === true;
                if (vis[i] !== on) { leaves[i].visible = on; vis[i] = on; }
            }
            exportPNG(doc, pg.outDir + "/" + ex.name + ".png");
            done++;
        }
        doc.close(SaveOptions.DONOTSAVECHANGES);
        doc = null;
        result.pages.push({page: pg.page, ok: true, exported: done});
        progress("OK png " + pg.page + " " + done);
    } catch (err) {
        result.pages.push({page: pg.page, ok: false, error: String(err) + (err.line ? " (line " + err.line + ")" : "")});
        progress("ERROR " + pg.page + ": " + err);
        if (doc) { try { doc.close(SaveOptions.DONOTSAVECHANGES); } catch (e2) {} }
    }
}
finish(result);
