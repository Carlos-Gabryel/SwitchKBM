// Mescla DualSense + PC e aplica os modos de gatilho. C puro, sem APIs do ESP.
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "bridge_proto.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    TRIG_MODE_NORMAL = 0,
    TRIG_MODE_STICK = 1,
    TRIG_MODE_PWM = 2,
    TRIG_MODE_COUNT
} trig_mode_t;

typedef struct {
    trig_mode_t mode;
    bool sys_held;        // SYSTEM estava pressionado na chamada anterior
    bool combo_used;      // combo PS+R2 usado nesta pressao de SYSTEM
    bool passed_through;  // SYSTEM ja foi repassado (pressao longa)
    uint32_t sys_press_ms;
    uint32_t sys_release_ms;
    bool pulse_pending;   // pulso de 100 ms apos soltar SYSTEM
    bool r2_prev;         // R2 pressionado na chamada anterior
    bool r2_suppress;     // R2 suprimido ate ser solto
} input_modes_t;

void input_modes_init(input_modes_t *m);
trig_mode_t input_modes_get(const input_modes_t *m);

// Mescla ds5 e pc em out. Qualquer ponteiro pode ser NULL (= ausente).
// out->flags tem CONNECTED se alguma entrada esta presente.
void input_merge(const bridge_state_t *ds5, const bridge_state_t *pc, bridge_state_t *out);

// Aplica combo + modo de gatilho em st. Retorna true se o modo mudou nesta chamada.
bool input_modes_process(input_modes_t *m, bridge_state_t *st, uint32_t now_ms);

#ifdef __cplusplus
}
#endif
