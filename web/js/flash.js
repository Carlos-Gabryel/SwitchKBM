// Gravacao do firmware na ESP32 com esptool-js (manifest firmware/flasher_args.json, igual ao flasher.py).
import { ESPLoader, Transport } from "../vendor/esptool-js/bundle.js";
import { md5 } from "./md5.js";

const FW_DIR = "firmware/";
export const FLASH_BAUD = 460800;

export class FirmwareMissing extends Error {}

function arg(list, flag) {
  const i = (list || []).indexOf(flag);
  return i >= 0 ? list[i + 1] : undefined;
}

export async function loadManifest() {
  let r;
  try {
    r = await fetch(FW_DIR + "flasher_args.json", { cache: "no-cache" });
  } catch (e) {
    throw new FirmwareMissing("Não foi possível ler firmware/flasher_args.json: " + e.message);
  }
  if (!r.ok) {
    throw new FirmwareMissing(
      "Firmware não encontrado neste site (firmware/flasher_args.json, HTTP " + r.status + "). " +
      "No site publicado ele é incluído automaticamente; localmente, copie build/firmware para web/firmware.");
  }
  const m = await r.json();
  if (!m.flash_files || !Object.keys(m.flash_files).length) throw new FirmwareMissing("flasher_args.json sem flash_files.");
  return m;
}

// cb: { log(msg), progress(fileIdx, nFiles, nome, escrito, total), step(msg) }
export async function flashFirmware(board, cb) {
  const manifest = await loadManifest();
  const extra = manifest.extra_esptool_args || {};
  const fs = manifest.flash_settings || {};
  const wfa = manifest.write_flash_args || [];
  const flashMode = fs.flash_mode || arg(wfa, "--flash_mode") || "keep";
  const flashFreq = fs.flash_freq || arg(wfa, "--flash_freq") || "keep";
  const flashSize = fs.flash_size || arg(wfa, "--flash_size") || "keep";
  const entries = Object.entries(manifest.flash_files).sort((a, b) => parseInt(a[0], 16) - parseInt(b[0], 16));

  cb.step("Fechando a conexão atual…");
  await board.disconnect();
  cb.step("Escolha a porta da placa na janela do navegador…");
  const port = await navigator.serial.requestPort(); // precisa vir logo apos o clique

  cb.step("Lendo arquivos do firmware…");
  const fileArray = [];
  for (const [off, rel] of entries) {
    const r = await fetch(FW_DIR + rel, { cache: "no-cache" });
    if (!r.ok) throw new FirmwareMissing("Arquivo de firmware ausente: " + rel + " (HTTP " + r.status + ")");
    fileArray.push({ data: new Uint8Array(await r.arrayBuffer()), address: parseInt(off, 16), name: rel });
  }

  const transport = new Transport(port, false);
  const loader = new ESPLoader({
    transport,
    baudrate: FLASH_BAUD,
    romBaudrate: 115200,
    terminal: { clean() {}, writeLine: (s) => cb.log(s), write: (s) => cb.log(s) },
  });
  try {
    cb.step("Conectando ao bootloader…");
    await loader.main(extra.before || "default_reset");
    const want = String(extra.chip || "esp32").toLowerCase().replace(/[^a-z0-9]/g, "");
    const got = String(loader.chip.CHIP_NAME || "").toLowerCase().replace(/[^a-z0-9]/g, "");
    if (got && want && got !== want) throw new Error("Chip diferente do esperado: " + loader.chip.CHIP_NAME + " (firmware para " + extra.chip + ").");
    cb.step("Gravando…");
    await loader.writeFlash({
      fileArray: fileArray.map(({ data, address }) => ({ data, address })),
      flashMode,
      flashFreq,
      flashSize,
      eraseAll: false,
      compress: true,
      calculateMD5Hash: md5, // verificacao: compara com o MD5 calculado pela placa
      reportProgress: (i, written, total) => cb.progress(i, fileArray.length, fileArray[i].name, written, total),
    });
    cb.step("Reiniciando a placa…");
    await loader.after(extra.after || "hard_reset");
  } finally {
    try { await transport.disconnect(); } catch { /* ignora */ }
  }
  cb.step("Gravação concluída e verificada.");
}
