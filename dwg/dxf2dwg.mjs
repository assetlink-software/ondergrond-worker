// dxf2dwg.mjs — turns the worker's DXF into a DWG (AutoCAD 2018, AC1032).
// Uses acad-ts (MIT), the TypeScript port of ACadSharp. Called by main.py:
//   node dxf2dwg.mjs in.dxf out.dwg [xmin ymin xmax ymax]
import fs from 'node:fs';
import { DxfReader, DwgWriter, ACadVersion, XYZ } from '@node-projects/acad-ts';

const [, , inp, out, ...ext] = process.argv;
if (!inp || !out) {
  console.error('usage: node dxf2dwg.mjs in.dxf out.dwg [xmin ymin xmax ymax]');
  process.exit(2);
}

try {
  // DXF R2007+ is UTF-8 by definition, but ezdxf still writes $DWGCODEPAGE=ANSI_1252 and acad-ts
  // trusts that header, which would turn "·", "—", "é", "²" into mojibake. Force UTF-8 there.
  let text = new TextDecoder('utf-8').decode(fs.readFileSync(inp));
  const ver = (text.match(/\$ACADVER\r?\n\s*1\r?\n(AC\d{4})/) || [])[1] || '';
  if (ver >= 'AC1021') text = text.replace(/(\$DWGCODEPAGE\r?\n\s*3\r?\n)[^\r\n]*/, '$1UTF-8');

  const doc = DxfReader.readFromStream(new TextEncoder().encode(text), () => {});
  const h = doc.header;

  // The header may name a style the tables don't hold (ezdxf's ISO-25 dimstyle); the DWG writer
  // would throw on it, so fall back to the defaults every DWG has.
  const fix = (getter, setter, fallback) => { try { void h[getter]; } catch { h[setter] = fallback; } };
  fix('currentDimensionStyle', 'currentDimensionStyleName', 'Standard');
  fix('currentTextStyle', 'currentTextStyleName', 'Standard');
  fix('currentLayer', 'currentLayerName', '0');
  fix('currentLineType', 'currentLineTypeName', 'ByLayer');

  // Real extents, so "Zoom Extents" in CAD lands on the drawing straight away.
  if (ext.length === 4 && ext.every((v) => Number.isFinite(Number(v)))) {
    const [x0, y0, x1, y1] = ext.map(Number);
    h.modelSpaceExtMin = new XYZ(x0, y0, 0);
    h.modelSpaceExtMax = new XYZ(x1, y1, 0);
  }

  h.version = ACadVersion.AC1032;
  fs.writeFileSync(out, DwgWriter.writeToBuffer(doc));
} catch (err) {
  console.error(`dxf2dwg failed: ${err?.message || err}`);
  process.exit(1);
}
