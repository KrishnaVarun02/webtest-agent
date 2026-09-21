import { cp, readdir, rm } from "node:fs/promises";
import { resolve } from "node:path";
import { spawn } from "node:child_process";
import { build } from "esbuild";

const root = resolve(new URL("..", import.meta.url).pathname);
const testsDirectory = resolve(root, "tests");
const outputDirectory = resolve(root, ".test-dist");
const entries = (await readdir(testsDirectory))
  .filter((name) => name.endsWith(".test.ts"))
  .map((name) => resolve(testsDirectory, name));

await rm(outputDirectory, { recursive: true, force: true });
try {
  await build({
    entryPoints: entries,
    outdir: outputDirectory,
    bundle: true,
    platform: "node",
    format: "esm",
    target: "node22",
    packages: "external",
    sourcemap: "inline",
    legalComments: "none"
  });
  await cp(resolve(testsDirectory, "fixtures"), resolve(outputDirectory, "fixtures"), { recursive: true });
  const exitCode = await new Promise((resolveExit, reject) => {
    const compiledTests = entries.map((entry) => resolve(outputDirectory, entry.split("/").at(-1).replace(/\.ts$/, ".js")));
    const child = spawn(process.execPath, ["--test", ...compiledTests], { stdio: "inherit" });
    child.once("error", reject);
    child.once("exit", (code) => resolveExit(code ?? 1));
  });
  if (exitCode !== 0) process.exitCode = exitCode;
} finally {
  await rm(outputDirectory, { recursive: true, force: true });
}
