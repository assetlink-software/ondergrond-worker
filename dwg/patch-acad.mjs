// patch-acad.mjs — speed fix for acad-ts 3.6.0, run once after `npm ci`.
//
// DwgObjectWriter._writeBlockHeader looks every entity up with Array.includes / Array.find
// inside a loop over all entities, which makes writing model space O(n²): 30 000 objects
// take ~10 s, 60 000 ~60 s. The same lookups with a Set / Map make it linear.
// Output is byte-for-byte the same. If acad-ts changes this code, the script fails loudly
// so the pinned version can be re-checked (and the patch dropped once fixed upstream).
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const file = path.join(here, 'node_modules/@node-projects/acad-ts/dist/IO/DWG/DwgStreamWriters/DwgObjectWriter.js');
let src = fs.readFileSync(file, 'utf8');
if (src.includes('/* ondergrond-patch */')) {
  console.log('acad-ts already patched');
  process.exit(0);
}

const swaps = [
  [ // owned handles: includes() in a loop → Set
    `        for (const handle of ownedEntityHandles) {
            if (!ownedObjectHandles.includes(handle)) {
                ownedObjectHandles.push(handle);
            }
        }`,
    `        /* ondergrond-patch */
        const entityByHandle = new Map(entities.map((entity) => [entity.handle, entity]));
        const ownedSet = new Set(ownedObjectHandles);
        for (const handle of ownedEntityHandles) {
            if (!ownedSet.has(handle)) {
                ownedSet.add(handle);
                ownedObjectHandles.push(handle);
            }
        }`,
  ],
  [ // insert handles: includes() in a loop → Set
    `        for (const insert of inserts) {
            if (!insertHandles.includes(insert.handle)) {
                insertHandles.push(insert.handle);
            }
        }`,
    `        const insertSet = new Set(insertHandles);
        for (const insert of inserts) {
            if (!insertSet.has(insert.handle)) {
                insertSet.add(insert.handle);
                insertHandles.push(insert.handle);
            }
        }`,
  ],
  [ // entity lookup: find() in a loop → Map
    `                const entity = entities.find((item) => item.handle === handle);`,
    `                const entity = entityByHandle.get(handle);`,
  ],
];

for (const [from, to] of swaps) {
  const n = src.split(from).length - 1;
  if (n !== 1) {
    console.error(`patch-acad: expected 1 match, found ${n}:\n${from.split('\n')[0]}`);
    process.exit(1);
  }
  src = src.replace(from, to);
}
fs.writeFileSync(file, src);
console.log('acad-ts patched (linear block header writer)');
