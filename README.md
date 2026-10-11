# switch-ds5-bridge

Projeto hobby: usar um controle DualSense (PS5) em um Nintendo Switch 2 fazendo o console enxergar um Pro Controller.

## Arquitetura

```
DualSense --BT--> ESP32 #1 (Bluepad32) --UART2 (GPIO17/16 cruzados + GND)--> ESP32 #2 (emula Pro Controller) --BT Classic HID--> Switch 2
```

- `switch-side/`: firmware do ESP32 #2 (ESP-IDF, C). Emula o Pro Controller via Bluetooth Classic HID com BTstack, baseado no JereDev esp32-switch-controller (GPL-3.0). Recebe o estado do DualSense pela UART (`common/bridge_proto`) e devolve o rumble.
- `ds5-side/`: firmware do ESP32 #1 (ESP-IDF + Bluepad32), ja implementado. Le o DualSense por Bluetooth e envia o estado pela UART.

## Fase 1

Fiacao (so sinal e terra, sem fios de alimentacao): ESP32 #1 GPIO17 -> ESP32 #2 GPIO16, ESP32 #1 GPIO16 <- ESP32 #2 GPIO17, GND com GND.

Gravar (ambiente ESP-IDF ativado por `tools\idf-env.ps1`):

```
.\tools\flash.ps1 -Side ds5 -Port COM4
.\tools\flash.ps1 -Side switch -Port COM5
```

Mapeamento de botoes por posicao: cruz -> B, bolinha -> A, quadrado -> Y, triangulo -> X, Create -> -, Options -> +, PS -> Home, Mute -> Capture. L1/R1 -> L/R, L2/R2 -> ZL/ZR, L3/R3 -> cliques dos sticks, direcional -> direcional. Giroscopio/acelerometro e rumble tambem sao repassados.

## Teclado e mouse (PC)

Da para jogar usando teclado e mouse do PC (mouse vira giroscopio) pela serial da Placa-MicroB. Veja `tools/kbm/README.md`.

## Modos de gatilho

O combo PS+R2 no DualSense alterna normal -> stick -> pwm. A lightbar indica o modo: azul (normal), verde (stick), vermelha (pwm). O PS sozinho continua funcionando como Home (enviado ao soltar; segurar 0,5 s = Home longo).
