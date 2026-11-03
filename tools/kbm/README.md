# Teclado e mouse (PC) -> Switch 2

## Programa (SwitchKBM.exe)

Interface gráfica para remapear teclado/mouse -> botões do Switch (como o menu de controles de um jogo) e iniciar/parar o bridge.

- Linux: AppImage (`dist/SwitchKBM-x86_64.AppImage`, gerado por `python tools/kbm/build.py`). Captura teclado/mouse via evdev com grab exclusivo e exige o usuário no grupo `input` (`sudo usermod -aG input $USER`; no Bazzite/Fedora Atomic antes: `grep -E '^input:' /usr/lib/group | sudo tee -a /etc/group`); a porta é `/dev/ttyUSB*`/`/dev/ttyACM*` (grupo `dialout` ou a regra `packaging/linux/60-switchkbm-serial.rules`). Perfis em `~/.local/share/SwitchKBM`. Auto-atualização só quando roda como AppImage.
- Gerar o exe: `powershell -ExecutionPolicy Bypass -File tools\kbm\build_exe.ps1` (cria `dist\SwitchKBM.exe`; precisa de Python + pip). Sem exe: `python tools\kbm\kbm_app.py`.
- Uso: escolha o Perfil (um por jogo) e a Porta (a CH9102 vem pré-selecionada). Clique numa célula "Tecla 1/2", pressione a tecla (ou clique/roda do mouse); Esc cancela. Clique direito na célula: botões laterais do mouse, roda, Esc, Limpar. F7/F8/F9/F11/F12 são reservadas. Se a tecla já estava em outro botão, ela é movida. Movimento (WASD/Andar devagar) também é configurável.
- Ajuste a mira/sensibilidade na aba Controles (Modo de mira e Sensibilidade) e em Ajustes (guardados no perfil). Clique em **Salvar** (título com `*` = alterações pendentes), depois **Iniciar**. Com o bridge rodando, o botão **Capturar mouse e teclado** (abaixo de Iniciar/Parar) ou **F12** captura; só **F12** libera. Salvar com o bridge rodando reinicia-o. F7/F8 durante o jogo mudam a sensibilidade na tela (marca como não salvo; clique Salvar para manter naquele perfil).
- Perfis ficam em `%LOCALAPPDATA%\SwitchKBM\profiles\` (Linux: `~/.local/share/SwitchKBM/profiles/`; a partir do código: `tools\kbm\profiles\`); `settings.json` na pasta acima guarda o último perfil e a porta. Na primeira execução o exe copia os perfis de versões antigas (`profiles\` ao lado do exe) ou cria "Padrão".
- Selftest sem interação: `SwitchKBM.exe --selftest`.

App para Windows que captura teclado e mouse e envia um gamepad virtual pela serial (USB) para a placa ESP32, que repassa ao emulador de Pro Controller. O movimento do mouse vira GIROSCOPIO (mira por giro) por padrao.

## Como rodar

Requer Python 3 com `pyserial` (e `evdev` no Linux). A porta (COM no Windows, `/dev/ttyUSB0` no Linux) e a da placa ESP32 (a que aparece como porta serial no Gerenciador de Dispositivos).

```
python tools\kbm\kbm_bridge.py --port COM4
python tools\kbm\kbm_bridge.py --port COM4 --verbose      # mostra o log de texto do ESP
python tools\kbm\kbm_bridge.py --dry-run                  # sem serial, imprime o estado a 5 Hz
python tools\kbm\kbm_bridge.py --port COM4 --config meu.json
```

A serial e aberta com DTR/RTS desligados para nao resetar o ESP32. Envio a 200 Hz. Testes: `python -m unittest discover -s tools/kbm -v`.

## Hotkeys

| Tecla | Acao |
|-------|------|
| F12 | captura / libera teclado e mouse |
| F9 | liga / desliga o modo digitacao (teclado do Switch 2) |
| F11 | alterna mira giroscopio <-> analogico (stick direito) |
| F8 / F7 | sensibilidade do giro x1.1 / /1.1 (imprime o novo valor) |

## Modo digitacao

Aba **Digitação** do app (ou **F9**, em qualquer situação): escreve texto no teclado da tela do Switch 2, igual ao do navegador. Com o modo ligado o bridge manda só os botões do teclado (direcionais, A, B, Y, +, L3; nunca X, L, R) e nenhum comando de jogo; se a captura estava ligada, ela é encerrada e volta ao sair (F9 de novo). F12 é ignorado enquanto o modo está ligado ("Saia do modo digitação com F9").

- **Confira na TV se o teclado está aberto antes de digitar:** o app não vê a TV. Com o teclado fechado, os comandos vão para o que estiver na tela.
- Enter envia (+), Esc limpa a fila e o campo, setas (campo vazio) movem o cursor, Home (campo vazio) = "teclado reaberto" (cursor volta ao 1).
- Velocidade: Seguro 50/50 ms, Normal 42/42 (padrão), Rápido 34/34, ou personalizado de 25 a 100 ms. "Sem acentos" digita só a letra base (mais rápido). Valores salvos em `settings.json`.
- A prévia do teclado mostra a página e o cursor que o app acredita estarem na TV; clique na célula onde o cursor está de verdade se errar letras.
- Protocolo no stdin do bridge (`--stdin-control`): `type {json}` com `op` = on, off, text, backspace, submit, clear, nav, reset, cursor, page, speed, strip; o bridge responde `DIGITACAO ON/OFF` e `DIGITACAO_ESTADO {json}` (até 10x/s).

- Na prática: a macro anda pelo teclado da tela (cerca de 2 a 3 letras por segundo no padrão; acentos trocam de página e custam mais). Ao entrar e sair do modo, a caixa é limpa, a fila é descartada e o cursor volta ao `1`, então abra o teclado antes do F9. Layout medido no teclado em português do Switch 2; outros idiomas e o Switch 1 não foram testados. Testado no console no Linux; no Windows não foi testado no console.
- No KDE com Wayland, o app pede ao KWin para vir para a frente ao apertar F9 (`winfocus.py`).
- Arquivos: `typing_engine.py` (motor da macro, com paridade em JS na pasta `web/` via `web/test/typing-vectors.json`), `kb_layout.py` (layout do teclado do Switch 2), `winfocus.py` (traz a janela para a frente). Testes: `test_typing.py`, `test_typing_bridge.py`, `test_digitacao.py`. A versão web do programa (pasta `web/`) é uma alternativa; o programa é o recomendado.

Hotkeys nunca viram botao do gamepad. Enquanto capturado, todo teclado e mouse ficam bloqueados para o Windows (o cursor nao se mexe).

## Setas

As setas mirando com o que o mouse nao controla: no modo giroscopio o mouse gira o giroscopio e as setas movem o analogico direito; no modo analogico o mouse move o analogico direito e as setas giram o giroscopio a taxa constante (`arrow_gyro_dps`). Seta usada como botao ou como movimento no perfil mantem essa funcao.

## Mapeamento padrao

- Movimento: W/A/S/D (stick esquerdo; diagonal normalizada; Alt = andar, 50%).
- Mouse: botao esquerdo = R2, direito = L2, meio = R3, laterais = direcional esq/dir, roda = Y (pulso de 80 ms).
- Teclas: Espaco=A, Ctrl esq/C=B, R/E/F=X, Q=L1, G=R1, Shift esq=L3, V=R3, Tab=Select, Esc=Start, Home=PS/Home, P=Captura, 1/2/3/4 = direcional cima/dir/baixo/esq.

## config.json

Chaves ausentes usam o padrao. `binds`, se presente, substitui todo o mapa padrao.

- `deg_per_count` (0.05): graus de giro por contagem do mouse.
- `arrow_gyro_dps` (90): velocidade do giro das setas no modo analogico (graus/s).
- `arrow_stick_scale` (1.0): deflexao do analogico direito das setas no modo giroscopio (0..1).
- `gyro_sensitivity` (1.0): multiplicador inicial (ajustavel em F7/F8).
- `invert_yaw`, `invert_pitch` (true): invertem o sinal do giro.
- `aim_mode`: `gyro` ou `stick`.
- `stick_sens` (1.0), `stick_full_speed` (5000 contagens/s), `stick_curve` (1.0), `stick_max` (0.92), `stick_drain_ms` (30), `stick_stop_counts` (0.5), `stick_deadzone_comp` (60, em circulo; ajustavel na UI, 0-200): modo stick (saldo de contagens do mouse drenado ao stick direito, preservando a distancia). F7/F8 no modo stick ajustam `stick_sens`.
- `walk_scale` (0.5): fator da tecla Alt.
- `wheel_pulse_ms` (80): duracao do pulso da roda.
- `binds`: nome da tecla -> botao. Teclas: letras, digitos, `f1`..`f12`, `space`, `tab`, `esc`, `enter`, `lshift`, `rshift`, `lctrl`, `rctrl`, `alt`, `home`, `end`, `insert`, `delete`, `pgup`, `pgdn`, `left`, `up`, `right`, `down`; mouse: `lmb`, `rmb`, `mmb`, `x1`, `x2`, `wheel_up`, `wheel_down`. Botoes: `A B X Y L1 R1 L3 R3 DPAD_UP DPAD_DOWN DPAD_LEFT DPAD_RIGHT SELECT START SYSTEM CAPTURE`, mais `L2` / `R2` (gatilho analogico no maximo + bit digital).

## Ajuste de sensibilidade

**Importante:** no jogo, use o espaco do giroscopio **Local** (Fortnite: "Espaco do giroscopio" = Local).
No espaco "Jogador"/"Mundo" o jogo usa a gravidade estimada pelo Switch; com o controle virtual
ela se perde com o tempo e a mira para de girar na horizontal.

Dois botoes de ajuste: a sensibilidade de giro dentro do jogo (Fortnite/CoD) e o `deg_per_count` daqui (ou F7/F8 em tempo real). Comece com a sensibilidade de giro do jogo no padrao, ajuste F7/F8 ate a mira ficar boa e depois grave o valor final em `deg_per_count` (multiplique `deg_per_count` pelo fator impresso). Se o giro sair invertido, mude `invert_yaw` / `invert_pitch`. Se o jogo precisar de giro muito alto, o app limita a +-32000 unidades e carrega o resto para os proximos quadros.

## Seguranca

- F12 sempre libera (o hook ve a tecla antes de tudo).
- Ctrl+Alt+Del sempre funciona.
- Fechar o console ou Ctrl+C remove os hooks e envia quadros neutros ao ESP32.
- Eventos injetados (por software) sao ignorados.

**Firmware embutido.** O exe já contém o firmware switch-side; o botão "Preparar placa" grava na porta serial selecionada (esptool embutido). `build.py` (no Windows, `build_exe.ps1` o chama) recompila o firmware (ESP-IDF 5.4.4) antes de empacotar; `--skip-firmware` (`-SkipFirmware`) pula e usa o `switch-side\build` existente. O build gera o exe em `.pack\dist` e copia só o `SwitchKBM.exe` para `dist\` (o flet pack apaga a pasta de saída inteira).
