// Reformats template pages to a print format: trim size W x H (A3 spread), bleed on every side,
// texts kept inside the safe margin. JOB: {pages: [{page, psd}], trimW, trimH, bleed, safe, save}.
// 1) image size -> trim (non-proportional; texts and small decor get their proportions back)
// 2) canvas + bleed  3) layers touching the trim edge grow into the bleed  4) texts moved into safety.
// Requires common.jsx.

function imageSize(w, h) {
    var d = new ActionDescriptor();
    d.putUnitDouble(cTID("Wdth"), cTID("#Pxl"), w);
    d.putUnitDouble(cTID("Hght"), cTID("#Pxl"), h);
    d.putBoolean(sTID("scaleStyles"), true);
    d.putBoolean(cTID("CnsP"), false);
    d.putEnumerated(cTID("Intr"), cTID("Intp"), sTID("bicubicAutomatic"));
    executeAction(cTID("ImgS"), d, DialogModes.NO);
}

function leaves(layers, out) {
    for (var i = 0; i < layers.length; i++) {
        if (layers[i].typename === "LayerSet") leaves(layers[i].layers, out);
        else out.push(layers[i]);
    }
    return out;
}

function isPhotoSlot(layer) {
    var n = (layer.name + " " + (layer.parent && layer.parent.name ? layer.parent.name : "")).toLowerCase();
    return n.indexOf("фото") >= 0 || n.indexOf("йото") >= 0 || n.indexOf("photo") >= 0;
}

function anchorFor(l, r, t, b) {
    // grow away from the edges the layer touches
    var h = l && r ? "MIDDLE" : l ? "RIGHT" : r ? "LEFT" : "MIDDLE";
    var v = t && b ? "MIDDLE" : t ? "BOTTOM" : b ? "TOP" : "MIDDLE";
    var map = {"TOPLEFT": AnchorPosition.TOPLEFT, "TOPMIDDLE": AnchorPosition.TOPCENTER, "TOPRIGHT": AnchorPosition.TOPRIGHT,
               "MIDDLELEFT": AnchorPosition.MIDDLELEFT, "MIDDLEMIDDLE": AnchorPosition.MIDDLECENTER,
               "MIDDLERIGHT": AnchorPosition.MIDDLERIGHT, "BOTTOMLEFT": AnchorPosition.BOTTOMLEFT,
               "BOTTOMMIDDLE": AnchorPosition.BOTTOMCENTER, "BOTTOMRIGHT": AnchorPosition.BOTTOMRIGHT};
    return map[v + h];
}

function reformat(doc) {
    var W0 = px(doc.width), H0 = px(doc.height);
    var sx = JOB.trimW / W0, sy = JOB.trimH / H0, area = W0 * H0;
    // remember which layers are "small decor" before resizing (texts too): they keep their proportions
    var all = leaves(doc.layers, []), keep = [], i;
    for (i = 0; i < all.length; i++) {
        var L = all[i], b;
        try { b = boundsObj(L); } catch (e) { continue; }
        var a = Math.max(0, b.right - b.left) * Math.max(0, b.bottom - b.top);
        if (isTextLayer(L) || (!isPhotoSlot(L) && a < 0.08 * area)) keep.push(L);
    }
    imageSize(JOB.trimW, JOB.trimH);
    var r = sx / sy, fixed = 0;
    if (Math.abs(r - 1) > 0.003) {
        for (i = 0; i < keep.length; i++) {
            try {
                if (r < 1) keep[i].resize(100, r * 100, AnchorPosition.MIDDLECENTER);
                else keep[i].resize(100 / r, 100, AnchorPosition.MIDDLECENTER);
                fixed++;
            } catch (e) {}
        }
    }
    var B = JOB.bleed;
    doc.resizeCanvas(UnitValue(JOB.trimW + 2 * B, "px"), UnitValue(JOB.trimH + 2 * B, "px"), AnchorPosition.MIDDLECENTER);
    var tl = B, tt = B, tr = B + JOB.trimW, tb = B + JOB.trimH, eps = 6, grown = 0, moved = 0;
    all = leaves(doc.layers, []);
    for (i = 0; i < all.length; i++) {
        var layer = all[i], bb;
        try { bb = boundsObj(layer); } catch (e) { continue; }
        if (bb.right - bb.left < 1 || bb.bottom - bb.top < 1) continue;
        if (isTextLayer(layer)) {
            var S = JOB.safe, dx = 0, dy = 0;
            if (bb.left < tl + S) dx = tl + S - bb.left;
            else if (bb.right > tr - S) dx = tr - S - bb.right;
            if (bb.top < tt + S) dy = tt + S - bb.top;
            else if (bb.bottom > tb - S) dy = tb - S - bb.bottom;
            if (dx || dy) { layer.translate(UnitValue(dx, "px"), UnitValue(dy, "px")); moved++; }
            continue;
        }
        var L2 = bb.left <= tl + eps, R2 = bb.right >= tr - eps, T2 = bb.top <= tt + eps, B2 = bb.bottom >= tb - eps;
        if (!(L2 || R2 || T2 || B2)) continue;
        var w = bb.right - bb.left, h = bb.bottom - bb.top;
        var nl = L2 ? Math.min(bb.left, 0) : bb.left, nr = R2 ? Math.max(bb.right, tr + B) : bb.right;
        var nt = T2 ? Math.min(bb.top, 0) : bb.top, nb = B2 ? Math.max(bb.bottom, tb + B) : bb.bottom;
        var kx = (nr - nl) / w, ky = (nb - nt) / h;
        if (kx < 1.0001 && ky < 1.0001) continue;
        try {
            layer.resize(kx * 100, ky * 100, anchorFor(L2, R2, T2, B2));
            var nb2 = boundsObj(layer);           // re-align exactly to the wanted box
            layer.translate(UnitValue(nl - nb2.left, "px"), UnitValue(nt - nb2.top, "px"));
            grown++;
        } catch (e) {}
    }
    return {sx: sx, sy: sy, fixed: fixed, grown: grown, moved: moved};
}

var result = {pages: []};
for (var p = 0; p < JOB.pages.length; p++) {
    var pg = JOB.pages[p], doc = null;
    try {
        doc = openLayered(new File(pg.psd));
        var info = reformat(doc);
        if (JOB.save) doc.save();
        else if (JOB.preview) {
            var copy = doc.duplicate("preview", true);
            var jpg = new JPEGSaveOptions(); jpg.quality = 8;
            copy.resizeImage(UnitValue(1400, "px"), null, null, ResampleMethod.BICUBIC);
            copy.saveAs(new File(JOB.preview + "/" + pg.page + ".jpg"), jpg, true, Extension.LOWERCASE);
            copy.close(SaveOptions.DONOTSAVECHANGES);
        }
        doc.close(SaveOptions.DONOTSAVECHANGES);
        doc = null;
        info.page = pg.page; info.ok = true;
        result.pages.push(info);
        progress("OK " + pg.page + " fixed=" + info.fixed + " grown=" + info.grown + " moved=" + info.moved);
    } catch (e) {
        result.pages.push({page: pg.page, ok: false, error: String(e) + (e.line ? " (line " + e.line + ")" : "")});
        progress("ERROR " + pg.page + ": " + e + (e.line ? " line " + e.line : ""));
        if (doc) { try { doc.close(SaveOptions.DONOTSAVECHANGES); } catch (e2) {} }
    }
}
finish(result);
