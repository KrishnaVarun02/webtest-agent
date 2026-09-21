import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const outdir = resolve(root, "dist");

await rm(outdir, { recursive: true, force: true });
await mkdir(outdir, { recursive: true });
await build({
  entryPoints: {
    devtools: resolve(root, "src/devtools.ts"),
    panel: resolve(root, "src/panel/panel.ts"),
    content: resolve(root, "src/content/recorder.ts")
  },
  bundle: true,
  outdir,
  format: "iife",
  target: "chrome120",
  sourcemap: true,
  legalComments: "none"
});

await Promise.all([
  cp(resolve(root, "manifest.json"), resolve(outdir, "manifest.json")),
  cp(resolve(root, "devtools.html"), resolve(outdir, "devtools.html")),
  cp(resolve(root, "src/panel/index.html"), resolve(outdir, "panel.html")),
  cp(resolve(root, "src/panel/styles.css"), resolve(outdir, "styles.css")),
  cp(resolve(root, "schema"), resolve(outdir, "schema"), { recursive: true })
]);

const manifestPath = resolve(outdir, "manifest.json");
const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
manifest.version = JSON.parse(await readFile(resolve(root, "package.json"), "utf8")).version;
await writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);

console.log(`Built unpacked extension at ${outdir}`);
