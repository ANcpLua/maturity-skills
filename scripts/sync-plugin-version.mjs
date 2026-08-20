// Keeps .claude-plugin/plugin.json's version in lockstep with package.json.
// `npm run version` calls this after `changeset version`; `--check` only verifies.
import { readFileSync, writeFileSync } from "node:fs";

const pkg = JSON.parse(readFileSync("package.json", "utf8"));
const pluginPath = ".claude-plugin/plugin.json";
const plugin = JSON.parse(readFileSync(pluginPath, "utf8"));

if (process.argv.includes("--check")) {
  if (plugin.version !== pkg.version) {
    console.error(`plugin.json ${plugin.version} != package.json ${pkg.version}`);
    process.exit(1);
  }
  process.exit(0);
}

plugin.version = pkg.version;
writeFileSync(pluginPath, JSON.stringify(plugin, null, 2) + "\n");
console.log(`plugin.json -> ${pkg.version}`);
