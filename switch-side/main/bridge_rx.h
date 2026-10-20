/* Recepcao do estado enviado pelo app do PC (UART0, console USB) e mapeamento para o Pro Controller. */
#pragma once
#include <stdint.h>
#include "controller_state.h"

void bridge_rx_init(void);                    /* instala a UART0 (PC) e inicia as tasks */
void bridge_rx_apply(controller_state_t *st); /* chamar na thread BTstack antes de cada report */
void bridge_rx_fill_imu(uint8_t *dst36);      /* 3 frames IMU x 12 bytes (report 0x30) */
