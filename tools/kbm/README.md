# Teclado e mouse (PC) -> Switch 2

## Programa (SwitchKBM.exe)

Interface gráfica para remapear teclado/mouse -> botões do Switch (como o menu de controles de um jogo) e iniciar/parar o bridge.

- Gerar o exe: `powershell -ExecutionPolicy Bypass -File tools\kbm\build_exe.ps1` (cria `dist\SwitchKBM.exe`; precisa de Python + pip). Sem exe: `python tools\kbm\kbm_app.py`.
- Uso: escolha o Perfil (um por jogo) e a Porta (a CH9102 vem pré-selecionada). Clique numa célula "Tecla 1/2", pressione a tecla (ou clique/roda do mouse); Esc cancela. Clique direito na célula: botões laterais do mouse, roda, Esc, Limpar. F7/F8/F10/F11/F12 são reservadas. Se a tecla já estava em outro botão, ela é movida. Movimento (WASD/Andar devagar) também é configurável.
- Ajuste a mira/sensibilidade no quadro "Mira e ajustes" (guardados no perfil). Clique em **Salvar** (título com `*` = alterações pendentes), depois **Iniciar**. No jogo, **F12** captura/libera. Salvar com o bridge rodando reinicia-o. F7/F8 durante o jogo mudam a sensibilidade na tela (marca como não salvo; clique Salvar para manter naquele perfil).
- Perfis ficam em `profiles\` ao lado do exe (a partir do código: `tools\kbm\profiles\`); `settings.json` na mesma pasta guarda o último perfil e a porta. Na primeira execução é criado "Padrão" (migra `config.json`).
- Selftest sem interação: `SwitchKBM.exe --selftest`.

App para Windows que captura teclado e mouse e envia um gamepad virtual pela serial (USB) para o ESP32 da Placa-MicroB, que repassa ao emulador de Pro Controller. O movimento do mouse vira GIROSCOPIO (mira por giro) por padrao.

## Como rodar

Requer Python 3 com `pyserial`. A porta COM e a da Placa-MicroB (CH9102, normalmente COM4).

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
| F11 | alterna mira giroscopio <-> analogico (stick direito) |
| F10 | troca o modo do gatilho no ESP32 (normal -> stick -> pwm) |
| F8 / F7 | sensibilidade do giro x1.1 / /1.1 (imprime o novo valor) |

Hotkeys nunca viram botao do gamepad. Enquanto capturado, todo teclado e mouse ficam bloqueados para o Windows (o cursor nao se mexe).

## Mapeamento padrao

- Movimento: W/A/S/D (stick esquerdo; diagonal normalizada; Alt = andar, 50%).
- Mouse: botao esquerdo = R2, direito = L2, meio = R3, laterais = direcional esq/dir, roda = Y (pulso de 80 ms).
- Teclas: Espaco=A, Ctrl esq/C=B, R/E/F=X, Q=L1, G=R1, Shift esq=L3, V=R3, Tab=Select, Esc=Start, Home=PS/Home, P=Captura, 1/2/3/4 = direcional cima/dir/baixo/esq.

## config.json

Chaves ausentes usam o padrao. `binds`, se presente, substitui todo o mapa padrao.

- `deg_per_count` (0.05): graus de giro por contagem do mouse.
- `gyro_sensitivity` (1.0): multiplicador inicial (ajustavel em F7/F8).
- `invert_yaw`, `invert_pitch` (true): invertem o sinal do giro.
- `aim_mode`: `gyro` ou `stick`.
- `stick_gain` (0.6), `stick_deadzone_comp` (60): usados no modo stick (velocidade do mouse -> stick direito).
- `walk_scale` (0.5): fator da tecla Alt.
- `wheel_pulse_ms` (80): duracao do pulso da roda.
- `binds`: nome da tecla -> botao. Teclas: letras, digitos, `f1`..`f12`, `space`, `tab`, `esc`, `enter`, `lshift`, `rshift`, `lctrl`, `rctrl`, `alt`, `home`, `end`, `insert`, `delete`, `pgup`, `pgdn`, `left`, `up`, `right`, `down`; mouse: `lmb`, `rmb`, `mmb`, `x1`, `x2`, `wheel_up`, `wheel_down`. Botoes: `A B X Y L1 R1 L3 R3 DPAD_UP DPAD_DOWN DPAD_LEFT DPAD_RIGHT SELECT START SYSTEM CAPTURE`, mais `L2` / `R2` (gatilho analogico no maximo + bit digital).

## Ajuste de sensibilidade

Dois botoes de ajuste: a sensibilidade de giro dentro do jogo (Fortnite/CoD) e o `deg_per_count` daqui (ou F7/F8 em tempo real). Comece com a sensibilidade de giro do jogo no padrao, ajuste F7/F8 ate a mira ficar boa e depois grave o valor final em `deg_per_count` (multiplique `deg_per_count` pelo fator impresso). Se o giro sair invertido, mude `invert_yaw` / `invert_pitch`. Se o jogo precisar de giro muito alto, o app limita a +-32000 unidades e carrega o resto para os proximos quadros.

## Seguranca

- F12 sempre libera (o hook ve a tecla antes de tudo).
- Ctrl+Alt+Del sempre funciona.
- Fechar o console ou Ctrl+C remove os hooks e envia quadros neutros ao ESP32.
- Eventos injetados (por software) sao ignorados.

## Modos de gatilho

O ESP32 tem 3 modos, trocados com F10 (ou PS+R2 no DualSense):
- normal: R2/L2 viram ZR/ZL digitais;
- stick: R2/L2 viram o eixo Y do stick direito;
- pwm: ZR/ZL pulsados proporcionalmente ao quanto o gatilho e apertado.

O app imprime "Modo gatilho: ..." quando o ESP32 informa a mudanca.
