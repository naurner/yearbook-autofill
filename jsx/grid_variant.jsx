// Grid variant of a class page for N people (vignette/gridfit.py plans it): every cell (portrait frame +
// caption layers) is moved and scaled to its new place; cells needed more than once are duplicated from the
// template's cells first, cells not needed are removed. Saved as a new PSD next to the template.
// JOB: {pages: [{psd, out, scale, targets: [{photo: path, texts: [path], box: [l, t], textBoxes: [[l, t]]}],
//                remove: [path]}]}. Requires common.jsx.

function moveTo(layer, scale, left, top) {
    if (Math.abs(scale - 1) > 0.001) layer.resize(scale * 100, scale * 100, AnchorPosition.TOPLEFT);
    var b = boundsObj(layer);
    layer.translate(UnitValue(left - b.left, "px"), UnitValue(top - b.top, "px"));
}

function variant(pg) {
    var doc = openLayered(new File(pg.psd)), i, j;
    try {
        // resolve every layer while the template's paths are still valid
        var cells = [], removals = [];
        for (i = 0; i < pg.targets.length; i++) {
            var t = pg.targets[i], c = {photo: layerByPath(doc, t.photo), texts: []};
            if (!c.photo) throw new Error("no cell layer at [" + t.photo.join(",") + "]");
            for (j = 0; j < t.texts.length; j++) c.texts.push(layerByPath(doc, t.texts[j]));
            cells.push(c);
        }
        for (i = 0; i < pg.remove.length; i++) removals.push(layerByPath(doc, pg.remove[i]));
        // a template cell used again gets copies made before anything moves
        var used = {}, work = [];
        for (i = 0; i < cells.length; i++) {
            var key = pg.targets[i].photo.join(",");
            if (!used[key]) {
                used[key] = true;
                work.push(cells[i]);
            } else {
                var copy = {photo: cells[i].photo.duplicate(), texts: []};
                for (j = 0; j < cells[i].texts.length; j++) copy.texts.push(cells[i].texts[j].duplicate());
                work.push(copy);
            }
        }
        for (i = 0; i < removals.length; i++) if (removals[i]) removals[i].remove();
        for (i = 0; i < work.length; i++) {
            var tg = pg.targets[i];
            moveTo(work[i].photo, pg.scale, tg.box[0], tg.box[1]);
            for (j = 0; j < work[i].texts.length; j++) moveTo(work[i].texts[j], pg.scale, tg.textBoxes[j][0], tg.textBoxes[j][1]);
        }
        var opts = new PhotoshopSaveOptions();
        opts.layers = true;
        opts.embedColorProfile = true;
        doc.saveAs(new File(pg.out), opts, true, Extension.LOWERCASE);
    } finally {
        doc.close(SaveOptions.DONOTSAVECHANGES);
    }
}

var result = {pages: []};
for (var p = 0; p < JOB.pages.length; p++) {
    try {
        variant(JOB.pages[p]);
        result.pages.push({out: JOB.pages[p].out, ok: true});
        progress("OK " + JOB.pages[p].out);
    } catch (e) {
        result.pages.push({out: JOB.pages[p].out, ok: false, error: String(e) + (e.line ? " (line " + e.line + ")" : "")});
        progress("ERROR " + JOB.pages[p].out + ": " + e);
    }
}
finish(result);
