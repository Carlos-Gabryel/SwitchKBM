// Protocolo UART entre ds5-side (DualSense via Bluepad32) e switch-side (Pro Controller).
// C puro, sem APIs do ESP (so tipos stdint). Little-endian, structs packed.
//
// Frame: 0xAA 0x55 type len payload[len] crc8
//   crc8 = CRC-8/ATM (poly 0x07, init 0x00) sobre type + len + payload.
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define BRIDGE_SOF0 0xAA
#define BRIDGE_SOF1 0x55
#define BRIDGE_MAX_PAYLOAD 48
#define BRIDGE_FRAME_OVERHEAD 5 /* SOF0 SOF1 type len crc */

#define BRIDGE_TYPE_STATE 0x01  /* ds5 -> switch */
#define BRIDGE_TYPE_RUMBLE 0x02 /* switch -> ds5 */

// bridge_state_t.flags
#define BRIDGE_FLAG_CONNECTED (1u << 0)
#define BRIDGE_FLAG_BATTERY_LOW (1u << 1)
#define BRIDGE_FLAG_CHARGING (1u << 2)

// Bits de bridge_state_t.buttons. Letras baseadas na POSICAO PlayStation
// (A = baixo/cruz). O mapeamento posicao -> rotulo Nintendo e feito no switch-side.
enum {
    BRIDGE_BTN_A = 0,  // cross
    BRIDGE_BTN_B,      // circle
    BRIDGE_BTN_X,      // square
    BRIDGE_BTN_Y,      // triangle
    BRIDGE_BTN_L1,
    BRIDGE_BTN_R1,
    BRIDGE_BTN_L2_DIGITAL,
    BRIDGE_BTN_R2_DIGITAL,
    BRIDGE_BTN_L3,
    BRIDGE_BTN_R3,
    BRIDGE_BTN_DPAD_UP,
    BRIDGE_BTN_DPAD_DOWN,
    BRIDGE_BTN_DPAD_LEFT,
    BRIDGE_BTN_DPAD_RIGHT,
    BRIDGE_BTN_SELECT,  // Create
    BRIDGE_BTN_START,   // Options
    BRIDGE_BTN_SYSTEM,  // PS
    BRIDGE_BTN_CAPTURE, // Bluepad32 4.2 nao expoe o clique do touchpad; usa o botao Mute (MISC_BUTTON_CAPTURE)
};
#define BRIDGE_BTN_MASK(b) (1u << (b))

// STATE (ds5 -> switch). Eixos como o Bluepad32 entrega:
//   lx, ly, rx, ry: -512..511; Y positivo = PARA BAIXO.
//   l2, r2: 0..1023.
//   gyro[3]: eixos x,y,z do DualSense (pitch, yaw, roll), em 1/16 grau/s por unidade
//            (valor do Bluepad32, que e' 1/1024 grau/s, deslocado >> 6 e saturado em int16).
//   accel[3]: eixos x,y,z do DualSense, em 1/8192 G por unidade (saturado em int16, +-4 G).
//   battery: valor do Bluepad32 (0 = desconhecido; DualSense: 1..251).
//   timestamp_ms: 16 bits baixos do relogio em ms.
typedef struct __attribute__((packed)) {
    uint8_t seq;
    uint8_t flags;
    uint8_t battery;
    uint32_t buttons;
    int16_t lx, ly, rx, ry;
    uint16_t l2, r2;
    int16_t gyro[3];
    int16_t accel[3];
    uint16_t timestamp_ms;
} bridge_state_t;

// RUMBLE (switch -> ds5). duration_ms == 0 para o motor.
typedef struct __attribute__((packed)) {
    uint8_t weak;
    uint8_t strong;
    uint16_t duration_ms;
} bridge_rumble_t;

_Static_assert(sizeof(bridge_state_t) == 33, "bridge_state_t size");
_Static_assert(sizeof(bridge_rumble_t) == 4, "bridge_rumble_t size");
_Static_assert(sizeof(bridge_state_t) <= BRIDGE_MAX_PAYLOAD, "payload max");

uint8_t bridge_crc8(const uint8_t *data, size_t len);

// Codifica um frame em out. Retorna bytes escritos, ou 0 se nao couber/parametro invalido.
size_t bridge_encode(uint8_t type, const void *payload, uint8_t len, uint8_t *out, size_t out_cap);

typedef struct {
    uint8_t state; // interno
    uint8_t idx;   // interno
    uint8_t crc;   // interno
    uint8_t type;
    uint8_t len;
    uint8_t payload[BRIDGE_MAX_PAYLOAD];
    uint32_t crc_errors;
    uint32_t len_errors;
    uint32_t frames_ok;
} bridge_parser_t;

void bridge_parser_init(bridge_parser_t *p);

// Alimenta um byte. Retorna true quando um frame valido esta pronto
// (p->type, p->len, p->payload valem ate o proximo feed).
bool bridge_parser_feed(bridge_parser_t *p, uint8_t byte);

#ifdef __cplusplus
}
#endif
