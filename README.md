# Switch KBM

Jogue no Nintendo Switch / Switch 2 com o teclado e o mouse do PC. A placa ESP32 aparece para o console como um Pro Controller, e o movimento do mouse vira giroscópio.

## Download

Baixe o **SwitchKBM.exe** em [Releases](https://github.com/Carlos-Gabryel/switch-ds5-bridge/releases/latest) (Windows 10/11). Não precisa instalar nada.

O exe não é assinado, então o SmartScreen pode avisar: clique em **Mais informações > Executar assim mesmo**.

## O que você precisa

- 1 placa **ESP32 original** (ESP32-WROOM / DevKit). Modelos S2, S3, C3 e C6 **não servem**: não têm Bluetooth Classic.
- Cabo USB **de dados** (alguns cabos só carregam).
- Se o Windows não reconhecer a porta COM da placa, instale o driver CP210x ou CH340 (conforme o chip da sua placa).

## Como usar

1. Abra o SwitchKBM, aba **Placa**: escolha a porta e clique em **Preparar placa** (só na primeira vez ou ao atualizar o firmware).
2. No Switch, abra a tela de parear controles (Configurações > Controles e acessórios). A placa aparece como Pro Controller.
3. Aba **Controles**: escolha ou edite o perfil e clique em **Iniciar**.
4. Clique em **Capturar mouse e teclado** (ou aperte **F12**). **F12** solta a captura.

Atalhos durante o uso: **F12** captura/solta, **F11** alterna a mira entre giroscópio e analógico, **F7 / F8** diminuem/aumentam a sensibilidade do giro. Essas teclas nunca viram botão do controle.

No jogo, use o espaço do giroscópio **Local** (ex.: Fortnite, "Espaço do giroscópio" = Local).

## Onde ficam os perfis

`%LOCALAPPDATA%\SwitchKBM`

## Compilar do código-fonte

Requisitos: Python 3.12+ e ESP-IDF 5.4 em `C:\Espressif\esp-idf`.

```
powershell -ExecutionPolicy Bypass -File tools\kbm\build_exe.ps1
```

Gera `dist\SwitchKBM.exe` (recompila o firmware e o embute). Use `-SkipFirmware` para reaproveitar o firmware já compilado. Sem exe: `python tools\kbm\kbm_app.py`. Testes: `python -m unittest discover -s tools/kbm`.

Só o firmware: `tools\flash.ps1 -Side switch -Port COMx`.

## Estrutura

- `switch-side/`: firmware do ESP32 (ESP-IDF, C) que emula o Pro Controller por Bluetooth Classic.
- `tools/kbm/`: o aplicativo Windows (interface Flet, captura de teclado/mouse, gravação da placa). Detalhes em `tools/kbm/README.md`.
- `common/`: protocolo serial compartilhado.
- `ds5-side/`: lado DualSense experimental, não usado pelo app.

## Experimental: DualSense (2 placas)

Antes do app existia um modo com controle DualSense: `DualSense --BT--> ESP32 #1 (ds5-side, Bluepad32) --UART--> ESP32 #2 (switch-side) --BT--> Switch`. Fiação só de sinal e terra (GPIO17 -> GPIO16 cruzados + GND). Gravação: `.\tools\flash.ps1 -Side ds5 -Port COMx` e `.\tools\flash.ps1 -Side switch -Port COMy` (ambiente ESP-IDF via `tools\idf-env.ps1`). Não faz parte do app.

## Licença

O código deste projeto é **GPL-3.0** (veja `LICENSE`), pois deriva de projetos GPL-3.0. O firmware inclui o **BTstack**, de uso **somente não comercial**: o exe pode ser compartilhado, mas não vendido nem usado comercialmente. Detalhes em `THIRD_PARTY_NOTICES.md`.

## Créditos

Feito por **Carlos Gabryel**. Baseado em [JereDev esp32-switch-controller](https://github.com/JereDev-Source/esp32-switch-controller), [Poohl/joycontrol](https://github.com/Poohl/joycontrol), [BTstack](https://github.com/bluekitchen/btstack) (BlueKitchen) e [Bluepad32](https://github.com/ricardoquesada/bluepad32).
