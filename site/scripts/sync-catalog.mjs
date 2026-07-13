import { copyFile, mkdir } from "node:fs/promises";

const source = new URL("../../catalog/plugins.v1.json", import.meta.url);
const destinations = [
  new URL("../public/catalog/plugins.v1.json", import.meta.url),
  new URL("../public/.well-known/mere-run/plugins.json", import.meta.url),
];

for (const destination of destinations) {
  await mkdir(new URL("./", destination), { recursive: true });
  await copyFile(source, destination);
}

console.log("Synced the public plugin catalog.");
