#include "input_modes.h"

#include <string.h>

#define SYS_LONG_PRESS_MS 500
#define SYS_PULSE_MS 100
#define TRIG_DEADZONE 40
#define TRIG_MAX 1023
#define PWM_HELD_ABOVE 983
#define PWM_PERIOD_MS 80

#define SYS_MASK BRIDGE_BTN_MASK(BRIDGE_BTN_SYSTEM)
#define R2_MASK BRIDGE_BTN_MASK(BRIDGE_BTN_R2_DIGITAL)
#define L2_MASK BRIDGE_BTN_MASK(BRIDGE_BTN_L2_DIGITAL)

void input_modes_init(input_modes_t *m) {
    memset(m, 0, sizeof(*m));
    m->mode = TRIG_MODE_NORMAL;
}

trig_mode_t input_modes_get(const input_modes_t *m) {
    return m->mode;
}

static int16_t sat16(int32_t v) {
    return (int16_t)(v > INT16_MAX ? INT16_MAX : (v < INT16_MIN ? INT16_MIN : v));
}

static int32_t iabs(int32_t v) {
    return v < 0 ? -v : v;
}

static int16_t pick_axis(int16_t a, int16_t b) {
    return iabs(b) > iabs(a) ? b : a;
}

void input_merge(const bridge_state_t *ds5, const bridge_state_t *pc, bridge_state_t *out) {
    if (ds5 == NULL && pc == NULL) {
        memset(out, 0, sizeof(*out));
        out->accel[1] = 8192;
        return;
    }
    if (ds5 == NULL || pc == NULL) {
        *out = (ds5 != NULL) ? *ds5 : *pc;
        out->flags |= BRIDGE_FLAG_CONNECTED;
        return;
    }
    bridge_state_t o = *ds5;
    o.flags = (uint8_t)(ds5->flags | BRIDGE_FLAG_CONNECTED);
    o.buttons = ds5->buttons | pc->buttons;
    o.lx = pick_axis(ds5->lx, pc->lx);
    o.ly = pick_axis(ds5->ly, pc->ly);
    o.rx = pick_axis(ds5->rx, pc->rx);
    o.ry = pick_axis(ds5->ry, pc->ry);
    o.l2 = ds5->l2 > pc->l2 ? ds5->l2 : pc->l2;
    o.r2 = ds5->r2 > pc->r2 ? ds5->r2 : pc->r2;
    for (int i = 0; i < 3; i++) {
        o.gyro[i] = sat16((int32_t)ds5->gyro[i] + (int32_t)pc->gyro[i]);
    }
    *out = o;
}

static bool r2_pressed(const bridge_state_t *st) {
    return (st->buttons & R2_MASK) != 0 || st->r2 > 512;
}

static void apply_stick(bridge_state_t *st) {
    int32_t r = st->r2 < TRIG_DEADZONE ? 0 : st->r2;
    int32_t l = st->l2 < TRIG_DEADZONE ? 0 : st->l2;
    if (r > 0 || l > 0) {
        int32_t y = (l - r) * 512 / TRIG_MAX; // R2 = stick para cima (Y negativo)
        st->ry = (int16_t)(y < -512 ? -512 : (y > 511 ? 511 : y));
    }
    st->r2 = 0;
    st->l2 = 0;
    st->buttons &= ~(R2_MASK | L2_MASK);
}

// Retorna true se o gatilho esta "apertado" no ciclo atual do PWM.
static bool pwm_held(uint16_t v16, bool digital, uint32_t now_ms) {
    int32_t val = v16;
    if (digital && val < TRIG_MAX) {
        val = TRIG_MAX;
    }
    if (val < TRIG_DEADZONE) {
        return false;
    }
    if (val > PWM_HELD_ABOVE) {
        return true;
    }
    return (int32_t)(now_ms % PWM_PERIOD_MS) < val * PWM_PERIOD_MS / TRIG_MAX;
}

static void apply_pwm(bridge_state_t *st, uint32_t now_ms) {
    bool r = pwm_held(st->r2, (st->buttons & R2_MASK) != 0, now_ms);
    bool l = pwm_held(st->l2, (st->buttons & L2_MASK) != 0, now_ms);
    st->r2 = r ? TRIG_MAX : 0;
    st->l2 = l ? TRIG_MAX : 0;
    st->buttons &= ~(R2_MASK | L2_MASK);
    if (r) {
        st->buttons |= R2_MASK;
    }
    if (l) {
        st->buttons |= L2_MASK;
    }
}

bool input_modes_process(input_modes_t *m, bridge_state_t *st, uint32_t now_ms) {
    bool changed = false;
    bool sys = (st->buttons & SYS_MASK) != 0;
    bool r2 = r2_pressed(st);

    if (sys && !m->sys_held) {
        m->sys_press_ms = now_ms;
        m->combo_used = false;
        m->passed_through = false;
        m->pulse_pending = false;
    }

    if (sys) {
        if (r2 && !m->r2_prev) {
            m->mode = (trig_mode_t)((m->mode + 1) % TRIG_MODE_COUNT);
            m->combo_used = true;
            m->r2_suppress = true;
            changed = true;
        }
        if (!m->combo_used && !m->passed_through && (uint32_t)(now_ms - m->sys_press_ms) >= SYS_LONG_PRESS_MS) {
            m->passed_through = true;
        }
    } else if (m->sys_held) {
        m->sys_release_ms = now_ms;
        m->pulse_pending = !m->combo_used && !m->passed_through;
    }

    m->sys_held = sys;
    m->r2_prev = r2;

    // R2 suprimido ate ser solto (mesmo que SYSTEM ja tenha sido solto)
    if (m->r2_suppress) {
        if (r2) {
            st->buttons &= ~R2_MASK;
            st->r2 = 0;
        } else {
            m->r2_suppress = false;
        }
    }

    // Saida de SYSTEM
    if (sys) {
        if (!m->passed_through) {
            st->buttons &= ~SYS_MASK;
        }
    } else if (m->pulse_pending) {
        if ((uint32_t)(now_ms - m->sys_release_ms) < SYS_PULSE_MS) {
            st->buttons |= SYS_MASK;
        } else {
            m->pulse_pending = false;
        }
    }

    switch (m->mode) {
    case TRIG_MODE_STICK:
        apply_stick(st);
        break;
    case TRIG_MODE_PWM:
        apply_pwm(st, now_ms);
        break;
    default:
        break;
    }
    return changed;
}
