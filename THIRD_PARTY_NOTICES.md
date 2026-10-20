# Avisos de terceiros

O código deste projeto (Carlos Gabryel, 2026) é distribuído sob **GPL-3.0** (veja `LICENSE`). Ele usa e/ou redistribui os componentes abaixo, que mantêm suas próprias licenças.

## AVISO IMPORTANTE: uso não comercial (BTstack)

O firmware embutido no `SwitchKBM.exe` inclui o **BTstack** (BlueKitchen GmbH), cuja licença
(`switch-side/components/btstack/LICENSE`, cláusula 4) permite redistribuição e uso **somente em benefício pessoal, sem finalidade comercial ou ganho monetário**.

Consequência: o firmware e o `SwitchKBM.exe` podem ser compartilhados livremente, mas **não podem ser vendidos nem usados comercialmente**. A GPL-3.0 do código próprio não anula essa restrição do BTstack.

## Firmware (switch-side/, embutido no exe)

| Componente | Licença | Onde |
|---|---|---|
| [JereDev-Source/esp32-switch-controller](https://github.com/JereDev-Source/esp32-switch-controller) | GPL-3.0 | Base de `switch-side/main` (licença original em `third_party/jeredev/LICENSE`) |
| [Poohl/joycontrol](https://github.com/Poohl/joycontrol) | GPL-3.0 | `switch-side/main/nfc_mcu.c` (adaptado de `joycontrol/mcu.py`) |
| [BTstack](https://github.com/bluekitchen/btstack) (BlueKitchen) | Própria, **não comercial** | `switch-side/components/btstack/` |
| micro-ecc | BSD-2-Clause | `switch-side/components/btstack/3rd-party/` |
| [ESP-IDF](https://github.com/espressif/esp-idf) (Espressif) | Apache-2.0 | Compilação do firmware (não incluído no repositório) |

## Aplicativo para Windows (tools/kbm/, SwitchKBM.exe)

| Componente | Licença | Observação |
|---|---|---|
| [esptool](https://github.com/espressif/esptool) 4.8.1 | GPL-2.0-ou-posterior | Embutido no exe para gravar a placa |
| [Flet](https://flet.dev) / flet-desktop 1.0.2 | Apache-2.0 | Interface; o motor Flutter embutido é BSD-3-Clause |
| [pyserial](https://github.com/pyserial/pyserial) 3.5 | BSD-3-Clause | Comunicação serial |
| [PyInstaller](https://pyinstaller.org) 6.x (bootloader) | GPL-2.0-ou-posterior com exceção que permite distribuir programas não-GPL | Empacotamento do exe |
| Python | PSF License | Interpretador embutido no exe |
| [Lucide](https://lucide.dev) (ícones) | ISC | `tools/kbm/ui/assets/icons/` (licença em `LICENSE` na mesma pasta) |

As licenças originais completas acompanham cada componente no respectivo diretório ou pacote.
