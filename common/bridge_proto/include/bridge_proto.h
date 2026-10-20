// Protocolo serial entre o app do PC (teclado/mouse) e o firmware switch-side (Pro Controller).
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

#define BRIDGE_TYPE_STATE 0x01  /* PC -> ESP32 */
#define BRIDGE_TYPE_STATUS 0x03 /* ESP32 -> PC (0x02 era reservado e nao e mais usado) */

// bridge_state_t.flags
#define BRIDGE_FLAG_CONNECTED (1u << 0)
#define BRIDGE_FLAG_BATTERY_LOW (1u << 1)
#define BRIDGE_FLAG_CHARGING (1u << 2)

// Bits de bridge_state_t.buttons. Letras baseadas na POSICAO fisica do botao
// (A = baixo). O mapeamento posicao -> rotulo Nintendo e feito no switch-side.
enum {
    BRIDGE_BTN_A = 0,  // baixo
    BRIDGE_BTN_B,      // direita
    BRIDGE_BTN_X,      // esquerda
    BRIDGE_BTN_Y,      // cima
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
    BRIDGE_BTN_SELECT,  // Minus
    BRIDGE_BTN_START,   // Plus
    BRIDGE_BTN_SYSTEM,  // Home
    BRIDGE_BTN_CAPTURE, // Captura
};
#define BRIDGE_BTN_MASK(b) (1u << (b))

// STATE (PC -> ESP32):
//   lx, ly, rx, ry: -512..511; Y positivo = PARA BAIXO.
//   l2, r2: 0..1023.
//   gyro[3]: eixos x,y,z (pitch, yaw, roll), em 1/16 grau/s por unidade (saturado em int16).
//   accel[3]: eixos x,y,z, em 1/8192 G por unidade (saturado em int16, +-4 G).
//   battery: 0 = desconhecido.
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

// STATUS (ESP32 -> PC): mantido so por compatibilidade de protocolo; o app ignora o conteudo.
typedef struct __attribute__((packed)) {
    uint8_t trig_mode; // sempre 0
    uint8_t reserved;  // sempre 0
} bridge_status_t;

_Static_assert(sizeof(bridge_status_t) == 2, "bridge_status_t size");
_Static_assert(sizeof(bridge_state_t) == 33, "bridge_state_t size");
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
