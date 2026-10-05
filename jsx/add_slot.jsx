// Adds a rectangular photo slot (solid color shape layer) to a template page, right above a given layer.
// JOB: {psd, name, rect: [left, top, right, bottom], above: layer name (top level), save}. Requires common.jsx.

function makeRect(name, r) {
    var d = new ActionDescriptor();
    var ref = new ActionReference();
    ref.putClass(sTID("contentLayer"));
    d.putReference(cTID("null"), ref);
    var layer = new ActionDescriptor();
    var fill = new ActionDescriptor();
    var color = new ActionDescriptor();
    color.putDouble(cTID("Rd  "), 197);
    color.putDouble(cTID("Grn "), 198);
    color.putDouble(cTID("Bl  "), 199);
    fill.putObject(cTID("Clr "), cTID("RGBC"), color);
    layer.putObject(cTID("Type"), sTID("solidColorLayer"), fill);
    var shape = new ActionDescriptor();
    shape.putUnitDouble(cTID("Top "), cTID("#Pxl"), r[1]);
    shape.putUnitDouble(cTID("Left"), cTID("#Pxl"), r[0]);
    shape.putUnitDouble(cTID("Btom"), cTID("#Pxl"), r[3]);
    shape.putUnitDouble(cTID("Rght"), cTID("#Pxl"), r[2]);
    layer.putObject(cTID("Shp "), cTID("Rctn"), shape);
    d.putObject(cTID("Usng"), sTID("contentLayer"), layer);
    executeAction(cTID("Mk  "), d, DialogModes.NO);
    app.activeDocument.activeLayer.name = name;
    return app.activeDocument.activeLayer;
}

var result = {ok: false};
var doc = null;
try {
    doc = openLayered(new File(JOB.psd));
    var anchor = null;
    for (var i = 0; i < doc.layers.length; i++) if (doc.layers[i].name === JOB.above) anchor = doc.layers[i];
    if (!anchor) throw new Error("no layer " + JOB.above);
    for (i = 0; i < doc.layers.length; i++) if (doc.layers[i].name === JOB.name) throw new Error("slot exists: " + JOB.name);
    doc.activeLayer = anchor;
    var slot = makeRect(JOB.name, JOB.rect);
    slot.move(anchor, ElementPlacement.PLACEBEFORE);
    var b = boundsObj(slot);
    if (JOB.save) doc.save();
    doc.close(SaveOptions.DONOTSAVECHANGES);
    doc = null;
    result = {ok: true, bounds: b};
    progress("OK slot " + b.left + "," + b.top + "," + b.right + "," + b.bottom);
} catch (e) {
    result = {ok: false, error: String(e) + (e.line ? " (line " + e.line + ")" : "")};
    progress("ERROR " + e);
    if (doc) { try { doc.close(SaveOptions.DONOTSAVECHANGES); } catch (e2) {} }
}
finish(result);
