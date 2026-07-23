import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

function args(argv) {
  const parsed = {};
  for (let index = 2; index < argv.length; index += 2) parsed[argv[index].replace(/^--/, "")] = argv[index + 1];
  return parsed;
}

function outputText(exports) {
  const ptr = exports.tako_output_ptr();
  const len = exports.tako_output_len();
  const text = new TextDecoder().decode(new Uint8Array(exports.memory.buffer, ptr, len));
  exports.tako_clear_output();
  return text;
}

function put(exports, bytes) {
  const ptr = exports.tako_alloc(bytes.length);
  new Uint8Array(exports.memory.buffer, ptr, bytes.length).set(bytes);
  return ptr;
}

function call(exports, payload) {
  const bytes = new TextEncoder().encode(JSON.stringify(payload));
  const ptr = put(exports, bytes);
  const code = exports.tako_run_operation(ptr, bytes.length);
  exports.tako_dealloc(ptr, bytes.length);
  const text = outputText(exports);
  if (code !== 0) {
    let message = text;
    try { message = JSON.parse(text).message || text; } catch {}
    throw new Error(message);
  }
  return JSON.parse(text);
}

const options = args(process.argv);
const job = JSON.parse(await readFile(options.job, "utf8"));
const manifest = JSON.parse(await readFile(options.manifest, "utf8"));
if (job.schemaVersion !== "tako-job-v1") throw new Error("Unsupported Tako job schema");
if (manifest.schemaVersion !== "tako-ci-runtime-v1") throw new Error("Unsupported Tako runtime schema");
const assetDir = resolve(options["asset-dir"]);
const wasmAsset = manifest.assets.find((asset) => asset.role === "wasm");
if (!wasmAsset) throw new Error("Runtime manifest has no WASM asset");
const wasmBytes = await readFile(resolve(assetDir, wasmAsset.file));
let wasmExports;
const imports = { env: { tako_emit_event(ptr, len) {
  if (!wasmExports) return;
  const text = new TextDecoder().decode(new Uint8Array(wasmExports.memory.buffer, ptr, len));
  process.stdout.write("TAKO_EVENT " + text.replace(/\n/g, " ") + "\n");
} } };
const { instance } = await WebAssembly.instantiate(wasmBytes, imports);
wasmExports = instance.exports;

const modelAsset = manifest.assets.find((asset) => asset.role === "model");
if (modelAsset) {
  const modelBytes = await readFile(resolve(assetDir, modelAsset.file));
  const bytesPtr = put(wasmExports, modelBytes);
  let code;
  if (manifest.runtime === "mlip") {
    const runtimeBytes = new TextEncoder().encode(manifest.model.runtime);
    const nameBytes = new TextEncoder().encode(manifest.model.name);
    const runtimePtr = put(wasmExports, runtimeBytes);
    const namePtr = put(wasmExports, nameBytes);
    code = wasmExports.tako_set_mlip_model(runtimePtr, runtimeBytes.length, namePtr, nameBytes.length, bytesPtr, modelBytes.length);
    wasmExports.tako_dealloc(runtimePtr, runtimeBytes.length);
    wasmExports.tako_dealloc(namePtr, nameBytes.length);
  } else {
    code = wasmExports.tako_set_qc_model(bytesPtr, modelBytes.length);
  }
  wasmExports.tako_dealloc(bytesPtr, modelBytes.length);
  const text = outputText(wasmExports);
  if (code !== 0) throw new Error(JSON.parse(text).message || text);
}

const payload = { operation: job.operation, ...job.executionInput };
const result = call(wasmExports, payload);
const encoded = JSON.stringify(result);
if (Buffer.byteLength(encoded) > job.envelope.maxOutputBytes) {
  throw new Error("PLAN_ESCALATION_REQUIRED: maxOutputBytes exceeded");
}
await writeFile(options.output, encoded);
process.stdout.write("TAKO_RESULT " + options.output + "\n");
