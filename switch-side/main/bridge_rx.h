/* Recepcao do estado pela UART2 (ds5-side) e/ou UART0 (PC), merge, modos de gatilho e mapeamento para o Pro Controller. */
#pragma once
#include <stdint.h>
#include "controller_state.h"

void bridge_rx_init(void);                            /* instala UART2 + UART0 (PC) e inicia as tasks */
void bridge_rx_apply(controller_state_t *st);         /* chamar na thread BTstack antes de cada report */
void bridge_rx_fill_imu(uint8_t *dst36);              /* 3 frames IMU x 12 bytes (report 0x30) */
void bridge_rx_handle_rumble(const uint8_t *rumble8); /* 8 bytes HD rumble (L4 + R4) */
void bridge_rx_rumble_stop(void);                     /* para o rumble (ex.: desconexao) */
