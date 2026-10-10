# switch-ds5-bridge

Projeto hobby: usar um controle DualSense (PS5) em um Nintendo Switch 2 fazendo o console enxergar um Pro Controller.

## Arquitetura

```
DualSense --BT--> ESP32 #1 (Bluepad32) --UART2 (GPIO17/16 cruzados + GND)--> ESP32 #2 (emula Pro Controller) --BT Classic HID--> Switch 2
```

- `switch-side/`: firmware do ESP32 #2 (ESP-IDF, C). Emula o Pro Controller via Bluetooth Classic HID, protocolo portado do joycontrol.
- ESP32 #1 (lado do DualSense, Bluepad32): ainda nao implementado.

## Fase atual: Fase 0

Testar se o Switch 2 aceita parear com o ESP32 como Pro Controller. O firmware aperta botoes sozinho (`CONFIG_AUTOPRESS_TEST`, ligado por padrao), sem entradas fisicas.

### Como testar

1. Conecte a placa ESP32 (WROOM classico) no USB.
2. Rode `tools\flash.ps1` (ou `tools\flash.ps1 -Port COM5`). Na primeira vez o ambiente ESP-IDF e ativado por `tools\idf-env.ps1` (instalado em `C:\Espressif\esp-idf`).
3. No Switch 2 abra Controles > Alterar empunhadura/ordem (Change Grip/Order) e aguarde.
4. Esperado: o controle aparece/registra sozinho (L+R automatico 3 s apos o modo de entrada 0x30), depois o botao A e apertado por 100 ms a cada 2 s.
5. Se falhar, copie o log do monitor serial (115200, tag `PROCON`) e envie para depuracao.

### Resetar o pareamento

Segure o botao BOOT (GPIO0) ao ligar a placa por 2 s: o host salvo (NVS) e as chaves de pareamento sao apagados e a placa volta a ficar visivel para parear.

Sem host salvo a placa fica descobrivel; com host salvo ela tenta reconectar sozinha ao ligar.
