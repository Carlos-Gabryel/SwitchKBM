<div align="center">

<img src="tools/kbm/ui/assets/icon.png" width="112" alt="Switch KBM">

# Switch KBM

**Jogue no Nintendo Switch e no Switch 2 com teclado e mouse do PC, usando uma placa ESP32 de poucos reais.**

[![Última versão](https://img.shields.io/github/v/release/Carlos-Gabryel/SwitchKBM?label=vers%C3%A3o&color=e8445a)](https://github.com/Carlos-Gabryel/SwitchKBM/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/Carlos-Gabryel/SwitchKBM/total?color=00b4d8)](https://github.com/Carlos-Gabryel/SwitchKBM/releases)
![Windows](https://img.shields.io/badge/Windows-10%20%7C%2011-0078d4?logo=windows)
![Linux](https://img.shields.io/badge/Linux-AppImage-fcc624?logo=linux&logoColor=black)
[![Licença GPL-3.0](https://img.shields.io/badge/licen%C3%A7a-GPL--3.0-ffcb05)](LICENSE)

[**⬇ Baixar para Windows**](https://github.com/Carlos-Gabryel/SwitchKBM/releases/latest/download/SwitchKBM.exe) ·
[**⬇ Baixar para Linux**](https://github.com/Carlos-Gabryel/SwitchKBM/releases/latest/download/SwitchKBM-x86_64.AppImage)

<img src="docs/screenshot.png" width="720" alt="Tela de Controles do Switch KBM">

</div>

---

O Switch KBM transforma uma placa **ESP32** num Pro Controller. O console enxerga a placa como
um controle de verdade, e o app no PC lê o seu teclado e o seu mouse e manda tudo para ela pelo
cabo USB. O mouse vira o **giroscópio** (mira por giro, como num controle), ou, se você preferir,
o analógico direito.

## ✨ O que ele faz

- **Remapeamento por perfil:** cada botão do Switch aceita até duas teclas ou botões do mouse.
- **Mouse como giroscópio ou analógico:** escolha o modo de mira e ajuste a sensibilidade.
- **Setas na mira oposta:** no modo giroscópio, as setas movem o analógico direito; no modo analógico, elas giram o giroscópio.
- **Roda do mouse como botão:** cada giro vira um toque rápido.
- **Andar devagar:** uma tecla (Alt) reduz o analógico esquerdo pela metade.
- **Captura com F12 ou com um botão:** enquanto capturado, o teclado e o mouse ficam só para o jogo. O F12 sempre solta.
- **Prepara a placa com um clique:** o firmware vai dentro do programa, sem instalar mais nada.
- **Atualiza sozinho:** avisa quando sai versão nova.
- **Perfis por jogo:** crie, duplique e troque de perfil sem mexer em arquivos.

## 🧰 Do que você precisa

| Item | Detalhes |
|---|---|
| **Placa ESP32 original** | ESP32-WROOM / DevKit. Os modelos S2, S3, C3 e C6 **não servem**: não têm Bluetooth Classic. |
| **Cabo USB de dados** | Cabo só de carga não funciona. |
| **Windows 10/11 x64** ou **Linux x86_64** | No Windows não precisa instalar nada. No Linux veja [Linux](#-linux). |
| **Nintendo Switch ou Switch 2** | Em qualquer um dos dois a placa aparece como Pro Controller. |

## 🚀 Primeiros passos

1. **Baixe** o [`SwitchKBM.exe`](https://github.com/Carlos-Gabryel/SwitchKBM/releases/latest/download/SwitchKBM.exe) e abra.
   > Se aparecer *"O Windows protegeu o computador"*, clique em **Mais informações → Executar assim mesmo**. O programa não tem assinatura digital, que é paga.
2. **Prepare a placa:** plugue a ESP32, abra a aba **Placa**, escolha a porta e clique em **Preparar placa**. É só na primeira vez e quando sair firmware novo.
3. **Pareie no console:** no Switch, abra **Configurações do sistema → Controles e acessórios** e entre na tela de parear controles (por exemplo, **Mudar estilo/ordem**). A placa aparece como Pro Controller.
4. **Jogue:** na aba **Controles**, escolha o perfil e clique em **Iniciar**. Depois clique em **Capturar mouse e teclado** ou aperte **F12**.

Seus perfis e ajustes ficam em `%LOCALAPPDATA%\SwitchKBM` (no Linux, `~/.local/share/SwitchKBM`).

## 🐧 Linux

1. Baixe o [`SwitchKBM-x86_64.AppImage`](https://github.com/Carlos-Gabryel/SwitchKBM/releases/latest/download/SwitchKBM-x86_64.AppImage), dê permissão e abra:
   ```bash
   chmod +x SwitchKBM-x86_64.AppImage
   ./SwitchKBM-x86_64.AppImage
   ```
   Sem FUSE, rode com `--appimage-extract-and-run`. O AppImage se atualiza sozinho; fora dele só avisa que há versão nova.
2. **Grupo `input` (obrigatório).** O programa captura teclado e mouse de forma exclusiva lendo `/dev/input` (evdev), por isso funciona em Wayland e X11, mas o usuário precisa estar no grupo `input`:
   ```bash
   sudo usermod -aG input $USER
   ```
   Saia e entre na sessão. No **Bazzite / Fedora Atomic** rode antes: `grep -E '^input:' /usr/lib/group | sudo tee -a /etc/group`.
   Sem a permissão o programa mostra essa instrução no log em vez de capturar.
3. **Porta da placa:** entre no grupo `dialout` (`sudo usermod -aG dialout $USER`; no Fedora, `uucp` no lugar de `dialout`) **ou** instale a regra udev, que dá acesso ao usuário logado e evita o ModemManager:
   ```bash
   sudo cp packaging/linux/60-switchkbm-serial.rules /etc/udev/rules.d/
   sudo udevadm control --reload && sudo udevadm trigger
   ```
4. A porta aparece como `/dev/ttyUSB0` (CP210x/CH340) ou `/dev/ttyACM0` (USB nativa). Daí é igual ao Windows: **Placa › Preparar placa**.

Com a captura ligada o teclado e o mouse ficam exclusivos do programa (a área de trabalho não recebe nada); **F12** libera. Não há "perder o foco libera": só F12 ou o botão do app.

## ⌨️ Atalhos

| Tecla | O que faz |
|---|---|
| **F12** | Captura ou solta o teclado e o mouse (soltar sempre funciona) |
| **F11** | Alterna a mira entre giroscópio e analógico |
| **F7 / F8** | Diminui / aumenta a sensibilidade do giro (marca o perfil como não salvo) |

Essas teclas nunca viram botão do controle.

## 🎮 Perfis

Cada jogo pode ter o seu perfil, com teclas e sensibilidade próprias. Use os botões ao lado da lista
para criar, duplicar, renomear e apagar. Depois de mexer, clique em **Salvar**.

> **Dica para Fortnite e outros jogos com giroscópio:** no jogo, deixe o **"Espaço do giroscópio" em
> Local**. Nos modos "Jogador" ou "Mundo", o jogo usa a gravidade estimada pelo Switch, que um
> controle virtual perde com o tempo, e a mira para de girar na horizontal.

## 🛠️ Problemas comuns

<details>
<summary><b>Placa desatualizada</b></summary>

- Aparece um aviso âmbar quando a placa tem um firmware mais antigo. Vá em **Placa › Preparar placa**; o bridge continua funcionando enquanto isso.

</details>

<details>
<summary><b>A porta da placa não aparece</b></summary>

- No Linux, veja o passo 3 da seção [Linux](#-linux) (grupo `dialout`/`uucp` ou regra udev).
- No Windows, instale o driver do chip USB da placa. O nome vem escrito perto do conector: **CP210x**
  ([driver](https://www.silabs.com/developer-tools/usb-to-uart-bridge-vcp-drivers)) ou
  **CH340 / CH9102** ([driver](https://www.wch-ic.com/downloads/CH341SER_EXE.html)).
- Troque o cabo. Muitos só carregam e não transmitem dados.
- Replugue a placa e atualize a lista de portas.
</details>

<details>
<summary><b>O console não acha o controle</b></summary>

Abra **Placa → Preparar placa** e grave o firmware de novo. Se não resolver, desplugue e plugue a
placa (ou aperte o botão EN/RESET dela) e entre de novo na tela de parear controles do console.
</details>

<details>
<summary><b>A mira desvia ou fica rápida/lenta demais</b></summary>

- Ajuste a **Sensibilidade** na aba Controles (ou use **F7 / F8** durante o jogo) e salve o perfil.
- Se o giro sair invertido, mude as opções de inverter nos **Ajustes**.
- Confira se o jogo está com o espaço do giroscópio em **Local**.
</details>

<details>
<summary><b>O Windows avisa que o programa não é seguro</b></summary>

É o SmartScreen. O programa não tem assinatura digital, que é paga. Clique em
**Mais informações → Executar assim mesmo**.
</details>

## 👩‍💻 Desenvolvimento

Requer Python 3.12+ e o ESP-IDF **5.4.4** (Windows: `C:\Espressif\esp-idf`; Linux: `~/esp/esp-idf-v5.4`).

```powershell
git clone https://github.com/Carlos-Gabryel/SwitchKBM
cd SwitchKBM

python -m unittest discover -s tools/kbm      # testes
python tools\kbm\kbm_app.py                   # roda o app sem gerar o exe

powershell -ExecutionPolicy Bypass -File tools\kbm\build_exe.ps1   # gera dist\SwitchKBM.exe (recompila o firmware)
powershell -ExecutionPolicy Bypass -File tools\kbm\build_exe.ps1 -SkipFirmware   # reaproveita o firmware já compilado

tools\flash.ps1 -Port COM4                    # só o firmware: grava e abre o monitor serial
```

No Linux:

```bash
git clone -b v5.4.4 --depth 1 --recursive --shallow-submodules https://github.com/espressif/esp-idf ~/esp/esp-idf-v5.4
~/esp/esp-idf-v5.4/install.sh esp32            # uma vez (IDF_PATH padrão: ~/esp/esp-idf-v5.4)

python -m venv tools/kbm/.venv && tools/kbm/.venv/bin/pip install -r tools/kbm/requirements.txt pytest
tools/kbm/.venv/bin/python -m pytest -q tools/kbm      # testes
tools/kbm/.venv/bin/python tools/kbm/kbm_app.py        # roda o app sem empacotar

tools/kbm/.venv/bin/python tools/kbm/build.py          # gera dist/SwitchKBM-x86_64.AppImage (--skip-firmware reaproveita o firmware)
tools/flash.sh /dev/ttyUSB0                            # só o firmware: grava e abre o monitor serial
```

<details>
<summary>Estrutura do projeto</summary>

```
switch-side/       firmware da ESP32 (ESP-IDF + BTstack): emula o Pro Controller por Bluetooth Classic
tools/kbm/         app Windows/Linux (Flet): captura de teclado/mouse, perfis e gravação da placa
common/bridge_proto/   protocolo serial entre o app e o firmware
tools/             flash.ps1/.sh, idf-env.ps1/.sh e utilitários
packaging/linux/   regra udev da porta serial
```

Mais detalhes do app em [`tools/kbm/README.md`](tools/kbm/README.md).
</details>

## 📜 Licença e créditos

O código deste repositório é [GPL-3.0](LICENSE), pois deriva de projetos GPL-3.0. O firmware inclui
o **BTstack**, de uso **somente não comercial**: o programa pode ser compartilhado, mas **não pode
ser vendido** nem usado comercialmente. Detalhes em [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

- **Base do Pro Controller:** [JereDev esp32-switch-controller](https://github.com/JereDev-Source/esp32-switch-controller)
- **NFC/MCU:** [Poohl/joycontrol](https://github.com/Poohl/joycontrol)
- **Bluetooth:** [BTstack](https://github.com/bluekitchen/btstack) (BlueKitchen)
- **Firmware:** [ESP-IDF](https://github.com/espressif/esp-idf) (Espressif)
- **Interface:** [Flet](https://flet.dev) · **Ícones:** [Lucide](https://lucide.dev) (ISC)

Feito por **Carlos Gabryel**.

<sub>Nintendo Switch é marca da Nintendo. Este é um projeto de fãs, sem fins lucrativos e sem afiliação
com ela.</sub>
