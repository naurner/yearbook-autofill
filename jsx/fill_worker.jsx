// Fills PSD pages per JOB (built by autofill/job.py) and exports <out>.psd/.jpg/.pdf.
// JOB: {pages: [{page, psd, out, texts: [...], photos: [...]}], anchorY, workDir}. Requires common.jsx.
// Originals are never saved: every output is a saveAs copy, then the document is closed unsaved.

function lineStarts(text, soft) {
    var starts = [0];
    for (var i = 0; i < text.length; i++) {
        var c = text.charCodeAt(i);
        if (c === 13 || (soft && c === 3)) starts.push(i + 1);
    }
    return starts;
}

function rangeCovering(list, pos) {
    var last = null;
    for (var i = 0; i < list.count; i++) {
        var d = list.getObjectValue(i);
        last = d;
        if (d.getInteger(sTID("from")) <= pos && pos < d.getInteger(sTID("to"))) return d;
    }
    return last;
}

// Rebuilds a style-range list for newText: line i gets the style of original line i
// (extra lines reuse the last one). Keeps Photoshop's trailing-range convention (to = len or len+1).
function remapRanges(list, rangeClass, styleKey, oldText, newText, soft) {
    var extra = list.count ? list.getObjectValue(list.count - 1).getInteger(sTID("to")) - oldText.length : 0;
    if (extra < 0) extra = 0;
    var oldStarts = lineStarts(oldText, soft), newStarts = lineStarts(newText, soft);
    var out = new ActionList();
    for (var i = 0; i < newStarts.length; i++) {
        var from = newStarts[i];
        var to = (i === newStarts.length - 1) ? newText.length + extra : newStarts[i + 1];
        if (to <= from) continue;
        var src = rangeCovering(list, oldStarts[Math.min(i, oldStarts.length - 1)]);
        var d = new ActionDescriptor();
        d.putInteger(sTID("from"), from);
        d.putInteger(sTID("to"), to);
        d.putObject(sTID(styleKey), sTID(styleKey), src.getObjectValue(sTID(styleKey)));
        out.putObject(sTID(rangeClass), d);
    }
    return out;
}

function isSpace(code) { return code === 32 || code === 9 || code === 13 || code === 3; }

// Start index of every word within text[from, to).
function wordStarts(text, from, to) {
    var starts = [], inWord = false;
    for (var i = from; i < to; i++) {
        if (isSpace(text.charCodeAt(i))) { inWord = false; }
        else if (!inWord) { starts.push(i); inWord = true; }
    }
    return starts;
}

// Character styles for newText: word k of line i takes the style of word k of original line i
// (clamped to the last word/line), so "11 <A> class" with two styles keeps both after editing.
function remapTextStyles(list, oldText, newText) {
    var extra = list.count ? list.getObjectValue(list.count - 1).getInteger(sTID("to")) - oldText.length : 0;
    if (extra < 0) extra = 0;
    var oldLines = lineStarts(oldText, true), newLines = lineStarts(newText, true);
    var segs = [], i, k;
    for (i = 0; i < newLines.length; i++) {
        var nFrom = newLines[i], nTo = (i + 1 < newLines.length) ? newLines[i + 1] : newText.length;
        var oi = Math.min(i, oldLines.length - 1);
        var oFrom = oldLines[oi], oTo = (oi + 1 < oldLines.length) ? oldLines[oi + 1] : oldText.length;
        var oWords = wordStarts(oldText, oFrom, oTo);
        if (!oWords.length) oWords = [Math.min(oFrom, Math.max(0, oldText.length - 1))];
        var nWords = wordStarts(newText, nFrom, nTo);
        segs.push({from: nFrom, anchor: oWords[0]});
        for (k = 1; k < nWords.length; k++) segs.push({from: nWords[k], anchor: oWords[Math.min(k, oWords.length - 1)]});
    }
    var out = new ActionList();
    for (i = 0; i < segs.length; i++) {
        var to = (i + 1 < segs.length) ? segs[i + 1].from : newText.length + extra;
        if (to <= segs[i].from) continue;
        var d = new ActionDescriptor();
        d.putInteger(sTID("from"), segs[i].from);
        d.putInteger(sTID("to"), to);
        d.putObject(sTID("textStyle"), sTID("textStyle"), rangeCovering(list, segs[i].anchor).getObjectValue(sTID("textStyle")));
        out.putObject(sTID("textStyleRange"), d);
    }
    return out;
}

function activeLayerRef() {
    var ref = new ActionReference();
    ref.putEnumerated(cTID("Lyr "), cTID("Ordn"), cTID("Trgt"));
    return ref;
}

// Replace the text of the active text layer keeping per-line character/paragraph styles.
function setTextKeepingLineStyles(value) {
    var tk = executeActionGet(activeLayerRef()).getObjectValue(sTID("textKey"));
    var oldText = tk.getString(sTID("textKey"));
    var styles = remapTextStyles(tk.getList(sTID("textStyleRange")), oldText, value);
    var paras = remapRanges(tk.getList(sTID("paragraphStyleRange")), "paragraphStyleRange", "paragraphStyle",
                            oldText, value, false);
    tk.putString(sTID("textKey"), value);
    tk.putList(sTID("textStyleRange"), styles);
    tk.putList(sTID("paragraphStyleRange"), paras);
    var desc = new ActionDescriptor();
    desc.putReference(cTID("null"), activeLayerRef());
    desc.putObject(cTID("T   "), sTID("textLayer"), tk);
    executeAction(cTID("setd"), desc, DialogModes.NO);
}

// Shrink the layer (keeping it live text) if its run along the text direction exceeds limit.
function fitToLimit(layer, horizontal, limit, justification) {
    var b = boundsObj(layer);
    var run = horizontal ? b.right - b.left : b.bottom - b.top;
    if (!(run > limit)) return 1;
    var k = Math.max(0.6, limit / run);
    var anchor = AnchorPosition.MIDDLECENTER;
    if (horizontal && justification.indexOf("LEFT") >= 0) anchor = AnchorPosition.MIDDLELEFT;
    if (horizontal && justification.indexOf("RIGHT") >= 0) anchor = AnchorPosition.MIDDLERIGHT;
    layer.resize(k * 100, k * 100, anchor);
    return k;
}

function applyText(doc, layer, t, rep) {
    if (t.styleRuns > 1) {
        doc.activeLayer = layer;
        try {
            setTextKeepingLineStyles(t.value);
        } catch (e) {
            layer.textItem.contents = t.value;
            rep.warnings.push({kind: "styles_lost", layer: t.name, value: String(e)});
        }
    } else {
        layer.textItem.contents = t.value;
    }
    if (String(t.textKind).indexOf("PARAGRAPH") >= 0) return;
    var k = fitToLimit(layer, t.horizontal, t.limit, String(t.justification));
    if (k < 1) rep.warnings.push({kind: "shrink", layer: t.name, value: k});
}

// Cover-fit the photo into the slot rectangle, paste it right above the slot and clip it
// to the slot (keeps the frame shape and its effects). A designer-hidden slot is switched on,
// otherwise the clipped photo would be invisible too.
// crop = [zoom, fx, fy] (zoom on top of cover-fit; fx/fy = window position in the scaled photo, 0..1)
// or null for the default: centered horizontally, anchorY from the top.
function placePhoto(doc, slot, file, anchorY, crop) {
    if (!slot.visible) slot.visible = true;
    var b = boundsObj(slot);
    var W = Math.round(b.right - b.left), H = Math.round(b.bottom - b.top);
    var src = app.open(new File(file));
    try {
        if (src.layers.length > 1) src.flatten();
        var mode = String(src.mode);
        if (mode !== String(DocumentMode.RGB) && mode !== String(DocumentMode.CMYK)) src.changeMode(ChangeMode.RGB);
        if (crop && crop.length > 3 && crop[3]) src.rotateCanvas(crop[3]);
        var sw = px(src.width), sh = px(src.height);
        var zoom = crop ? Math.max(1, crop[0]) : 1, fx = crop ? crop[1] : 0.5, fy = crop ? crop[2] : anchorY;
        var s = Math.max(W / sw, H / sh) * zoom;
        var nw = Math.max(W, Math.round(sw * s)), nh = Math.max(H, Math.round(sh * s));
        src.resizeImage(UnitValue(nw, "px"), UnitValue(nh, "px"), src.resolution, ResampleMethod.BICUBIC);
        var ox = Math.round((nw - W) * fx), oy = Math.round((nh - H) * fy);
        src.crop([UnitValue(ox, "px"), UnitValue(oy, "px"), UnitValue(ox + W, "px"), UnitValue(oy + H, "px")]);
        src.selection.selectAll();
        src.selection.copy();
    } finally {
        src.close(SaveOptions.DONOTSAVECHANGES);
    }
    app.activeDocument = doc;
    doc.selection.deselect();
    doc.activeLayer = slot;
    var layer = doc.paste();
    var pb = boundsObj(layer);
    layer.translate(UnitValue(b.left - pb.left, "px"), UnitValue(b.top - pb.top, "px"));
    layer.grouped = true;
    layer.name = new File(file).name;
    return layer;
}

// The studio logo (PNG with transparency) as the top layer, logo.width px wide, centered on logo.center.
function placeLogo(doc, logo) {
    var src = app.open(new File(logo.file));
    try {
        if (String(src.mode) !== String(DocumentMode.RGB)) src.changeMode(ChangeMode.RGB);
        var w = Math.round(logo.width), h = Math.round(px(src.height) * logo.width / px(src.width));
        src.resizeImage(UnitValue(w, "px"), UnitValue(h, "px"), src.resolution, ResampleMethod.BICUBIC);
        src.selection.selectAll();
        src.selection.copy();
    } finally {
        src.close(SaveOptions.DONOTSAVECHANGES);
    }
    app.activeDocument = doc;
    doc.selection.deselect();
    doc.activeLayer = doc.layers[0];
    var layer = doc.paste();
    layer.move(doc, ElementPlacement.PLACEATBEGINNING);
    var b = boundsObj(layer);
    layer.translate(UnitValue(logo.center[0] - (b.left + b.right) / 2, "px"),
                    UnitValue(logo.center[1] - (b.top + b.bottom) / 2, "px"));
    layer.name = "logo";
    return layer;
}

function hasFormat(formats, f) {
    for (var i = 0; i < formats.length; i++) if (formats[i] === f) return true;
    return false;
}

// formats: any of "psd" (layered copy), "jpg", "pdf"; default all three.
function exportPage(doc, outBase, formats) {
    formats = formats || ["psd", "jpg", "pdf"];
    stripAncestors(doc);
    if (hasFormat(formats, "psd")) {
        var psd = new PhotoshopSaveOptions();
        psd.layers = true;
        psd.embedColorProfile = true;
        doc.saveAs(new File(outBase + ".psd"), psd, true, Extension.LOWERCASE);
    }
    doc.flatten();
    if (String(doc.bitsPerChannel) !== String(BitsPerChannelType.EIGHT)) doc.bitsPerChannel = BitsPerChannelType.EIGHT;
    if (hasFormat(formats, "jpg")) {
        var jpg = new JPEGSaveOptions();
        jpg.quality = 12;
        jpg.embedColorProfile = true;
        doc.saveAs(new File(outBase + ".jpg"), jpg, true, Extension.LOWERCASE);
    }
    if (hasFormat(formats, "pdf")) {
        var pdf = new PDFSaveOptions();
        pdf.encoding = PDFEncoding.JPEG;
        pdf.jpegQuality = 12;
        pdf.embedColorProfile = true;
        pdf.layers = false;
        pdf.preserveEditing = false;
        doc.saveAs(new File(outBase + ".pdf"), pdf, true, Extension.LOWERCASE);
    }
    doc.close(SaveOptions.DONOTSAVECHANGES);
}

function resolveSlot(doc, slot, wantText) {
    var layer = layerByPath(doc, slot.path);
    if (!layer || layer.name !== slot.name) {
        throw new Error("layer mismatch at [" + slot.path.join(",") + "]: expected '" + slot.name +
                        "', found '" + (layer ? layer.name : "none") + "' - template changed, rebuild manifest");
    }
    if (wantText && !isTextLayer(layer)) throw new Error("not a text layer: " + slot.name);
    return layer;
}

var result = {pages: []};
for (var p = 0; p < JOB.pages.length; p++) {
    var pg = JOB.pages[p], doc = null, i;
    var rep = {page: pg.page, ok: false, texts: 0, photos: 0, warnings: []};
    try {
        var psdFile = new File(pg.psd);
        if (!psdFile.exists) throw new Error("template file not found: " + pg.psd);
        if (isAlreadyOpen(psdFile)) throw new Error("template is open in Photoshop, close it: " + pg.psd);
        doc = openLayered(psdFile);
        var textLayers = [], photoLayers = [], cloneLayers = [], clones = pg.clones || [];
        for (i = 0; i < pg.texts.length; i++) textLayers.push(resolveSlot(doc, pg.texts[i], true));
        for (i = 0; i < pg.photos.length; i++) photoLayers.push(resolveSlot(doc, pg.photos[i], false));
        for (i = 0; i < clones.length; i++) cloneLayers.push(resolveSlot(doc, clones[i], true));
        var hidden = pg.hide || [];
        for (i = 0; i < hidden.length; i++) resolveSlot(doc, hidden[i], false).visible = false;
        // Extra text lines not in the template: a copy of a styled text layer, moved by dx/dy.
        for (i = 0; i < cloneLayers.length; i++) {
            cloneLayers[i] = cloneLayers[i].duplicate();
            cloneLayers[i].translate(UnitValue(clones[i].dx, "px"), UnitValue(clones[i].dy, "px"));
        }
        for (i = 0; i < textLayers.length; i++) { applyText(doc, textLayers[i], pg.texts[i], rep); rep.texts++; }
        for (i = 0; i < cloneLayers.length; i++) { applyText(doc, cloneLayers[i], clones[i], rep); rep.texts++; }
        for (i = 0; i < photoLayers.length; i++) {
            placePhoto(doc, photoLayers[i], pg.photos[i].file, JOB.anchorY, pg.photos[i].crop || null);
            rep.photos++;
        }
        if (pg.logo) placeLogo(doc, pg.logo);
        exportPage(doc, pg.out, JOB.formats);
        doc = null;
        rep.ok = true;
        progress("OK " + pg.page + " texts=" + rep.texts + " photos=" + rep.photos);
    } catch (e) {
        rep.error = String(e) + (e.line ? " (line " + e.line + ")" : "");
        progress("ERROR " + pg.page + ": " + rep.error);
        if (doc) { try { doc.close(SaveOptions.DONOTSAVECHANGES); } catch (e2) {} }
    }
    result.pages.push(rep);
}
finish(result);
