/*
 * bridge_rx: recebe bridge_state_t do ds5-side pela UART2 e entrega ao codigo JereDev
 * (controller_state_t + IMU) e devolve o rumble do Switch como bridge_rumble_t.
 */
#include "bridge_rx.h"

#include <string.h>

#include "bridge_proto.h"
#include "driver/uart.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "BRIDGE";

#define BRIDGE_UART UART_NUM_2
#define BRIDGE_TX_PIN 17
#define BRIDGE_RX_PIN 16
#define BRIDGE_BAUD 921600

#define STALE_US 200000
#define STICK_DEADZONE 24
#define TRIGGER_THRESHOLD 512
#define RUMBLE_KEEPALIVE_US 100000
#define RUMBLE_DURATION_MS 200

/* Remap de eixos DualSense (SDL: x=pitch, y=yaw, z=roll) -> Pro Controller.
 * Aplicado igual a accel e gyro. Ajustar aqui se os eixos estiverem trocados/invertidos. */
#define IMU_SW_X(ds) (-(int32_t)(ds)[2])
#define IMU_SW_Y(ds) (-(int32_t)(ds)[0])
#define IMU_SW_Z(ds) ((int32_t)(ds)[1])
#define ACCEL_SHIFT 1 /* 1/8192 G -> 1/4096 G */
#define GYRO_NUM 1024 /* 1/16 dps -> ~1/16.384 dps */
#define GYRO_DEN 1000

typedef struct {
    int16_t v[6]; /* ax ay az gx gy gz */
} imu_sample_t;

static portMUX_TYPE s_lock = portMUX_INITIALIZER_UNLOCKED;
static bridge_state_t s_state;
static int64_t s_state_us;
static bool s_have_state;
static imu_sample_t s_imu[3]; /* ring, mais antigo em s_imu_head */
static uint8_t s_imu_head;
static uint8_t s_imu_count;

static volatile uint32_t s_rumble_sent;
static uint8_t s_last_weak, s_last_strong;
static int64_t s_last_rumble_us;

static int16_t sat16(int32_t v)
{
    if (v > 32767) return 32767;
    if (v < -32768) return -32768;
    return (int16_t)v;
}

static void convert_imu(const bridge_state_t *s, imu_sample_t *o)
{
    int16_t accel[3] = { s->accel[0], s->accel[1], s->accel[2] };
    int16_t gyro[3] = { s->gyro[0], s->gyro[1], s->gyro[2] };
    o->v[0] = sat16(IMU_SW_X(accel) / (1 << ACCEL_SHIFT));
    o->v[1] = sat16(IMU_SW_Y(accel) / (1 << ACCEL_SHIFT));
    o->v[2] = sat16(IMU_SW_Z(accel) / (1 << ACCEL_SHIFT));
    o->v[3] = sat16(IMU_SW_X(gyro) * GYRO_NUM / GYRO_DEN);
    o->v[4] = sat16(IMU_SW_Y(gyro) * GYRO_NUM / GYRO_DEN);
    o->v[5] = sat16(IMU_SW_Z(gyro) * GYRO_NUM / GYRO_DEN);
}

static void put_frame(uint8_t *dst, const imu_sample_t *s)
{
    for (int i = 0; i < 6; i++) {
        dst[2 * i] = (uint8_t)((uint16_t)s->v[i] & 0xFF);
        dst[2 * i + 1] = (uint8_t)((uint16_t)s->v[i] >> 8);
    }
}

static void neutral_frame(uint8_t *dst)
{
    imu_sample_t n = { { 0, 0, 4096, 0, 0, 0 } };
    put_frame(dst, &n);
}

static int stick_axis(int v, int sign)
{
    if (v > -STICK_DEADZONE && v < STICK_DEADZONE) v = 0;
    int r = 2048 + sign * v * 4;
    if (r < 0) r = 0;
    if (r > 4095) r = 4095;
    return r;
}

#define HAS(st, b) (((st).buttons & BRIDGE_BTN_MASK(b)) != 0)

void bridge_rx_apply(controller_state_t *st)
{
    bridge_state_t s;
    int64_t t;
    bool have;
    portENTER_CRITICAL(&s_lock);
    s = s_state;
    t = s_state_us;
    have = s_have_state;
    portEXIT_CRITICAL(&s_lock);

    if (!have || (esp_timer_get_time() - t) > STALE_US || !(s.flags & BRIDGE_FLAG_CONNECTED)) {
        controller_state_init(st);
        return;
    }

    uint8_t right = 0, shared = 0, left = 0;
    /* Por posicao fisica: baixo->B, direita->A, esquerda->Y, cima->X */
    if (HAS(s, BRIDGE_BTN_A)) right |= BTN_B;
    if (HAS(s, BRIDGE_BTN_B)) right |= BTN_A;
    if (HAS(s, BRIDGE_BTN_X)) right |= BTN_Y;
    if (HAS(s, BRIDGE_BTN_Y)) right |= BTN_X;
    if (HAS(s, BRIDGE_BTN_R1)) right |= BTN_R;
    if (HAS(s, BRIDGE_BTN_R2_DIGITAL) || s.r2 > TRIGGER_THRESHOLD) right |= BTN_ZR;
    if (HAS(s, BRIDGE_BTN_L1)) left |= BTN_L;
    if (HAS(s, BRIDGE_BTN_L2_DIGITAL) || s.l2 > TRIGGER_THRESHOLD) left |= BTN_ZL;
    if (HAS(s, BRIDGE_BTN_DPAD_UP)) left |= BTN_UP;
    if (HAS(s, BRIDGE_BTN_DPAD_DOWN)) left |= BTN_DOWN;
    if (HAS(s, BRIDGE_BTN_DPAD_LEFT)) left |= BTN_LEFT;
    if (HAS(s, BRIDGE_BTN_DPAD_RIGHT)) left |= BTN_RIGHT;
    if (HAS(s, BRIDGE_BTN_L3)) shared |= BTN_STICK_L;
    if (HAS(s, BRIDGE_BTN_R3)) shared |= BTN_STICK_R;
    if (HAS(s, BRIDGE_BTN_SELECT)) shared |= BTN_MINUS;
    if (HAS(s, BRIDGE_BTN_START)) shared |= BTN_PLUS;
    if (HAS(s, BRIDGE_BTN_SYSTEM)) shared |= BTN_HOME;
    if (HAS(s, BRIDGE_BTN_CAPTURE)) shared |= BTN_CAPTURE;

    st->right_buttons = right;
    st->shared_buttons = shared;
    st->left_buttons = left;
    st->left_stick_x = (uint16_t)stick_axis(s.lx, +1);
    st->left_stick_y = (uint16_t)stick_axis(s.ly, -1);
    st->right_stick_x = (uint16_t)stick_axis(s.rx, +1);
    st->right_stick_y = (uint16_t)stick_axis(s.ry, -1);
}

void bridge_rx_fill_imu(uint8_t *dst36)
{
    imu_sample_t ring[3];
    uint8_t head, count;
    int64_t t;
    portENTER_CRITICAL(&s_lock);
    memcpy(ring, s_imu, sizeof(ring));
    head = s_imu_head;
    count = s_imu_count;
    t = s_state_us;
    portEXIT_CRITICAL(&s_lock);

    bool stale = (esp_timer_get_time() - t) > STALE_US;
    int missing = 3 - count; /* slots sem amostra ficam no inicio (mais antigos) */
    for (int i = 0; i < 3; i++) {
        if (stale || i < missing) {
            neutral_frame(dst36 + 12 * i);
        } else {
            put_frame(dst36 + 12 * i, &ring[(head + (i - missing)) % 3]);
        }
    }
}

/* ---- Rumble ---- */

static uint8_t hf_level(const uint8_t *b)
{
    uint32_t code = b[1] & 0xFE;
    uint32_t v = code * 255 / 0xC8;
    return v > 255 ? 255 : (uint8_t)v;
}

static uint8_t lf_level(const uint8_t *b)
{
    uint32_t c = b[3] & 0x7F;
    uint32_t code = c >= 0x40 ? c - 0x40 : 0;
    uint32_t v = code * 255 / 0x32;
    return v > 255 ? 255 : (uint8_t)v;
}

static void send_rumble(uint8_t weak, uint8_t strong, uint16_t duration_ms)
{
    bridge_rumble_t r = { weak, strong, duration_ms };
    uint8_t frame[BRIDGE_FRAME_OVERHEAD + sizeof(r)];
    size_t n = bridge_encode(BRIDGE_TYPE_RUMBLE, &r, sizeof(r), frame, sizeof(frame));
    if (n) {
        uart_write_bytes(BRIDGE_UART, frame, n);
        s_rumble_sent++;
    }
}

void bridge_rx_handle_rumble(const uint8_t *rumble8)
{
    uint8_t hf_l = hf_level(rumble8), hf_r = hf_level(rumble8 + 4);
    uint8_t lf_l = lf_level(rumble8), lf_r = lf_level(rumble8 + 4);
    uint8_t weak = hf_l > hf_r ? hf_l : hf_r;
    uint8_t strong = lf_l > lf_r ? lf_l : lf_r;
    int64_t now = esp_timer_get_time();
    bool changed = weak != s_last_weak || strong != s_last_strong;
    bool nonzero = weak || strong;

    if (changed) {
        send_rumble(weak, strong, nonzero ? RUMBLE_DURATION_MS : 0);
    } else if (nonzero && (now - s_last_rumble_us) >= RUMBLE_KEEPALIVE_US) {
        send_rumble(weak, strong, RUMBLE_DURATION_MS);
    } else {
        return;
    }
    s_last_weak = weak;
    s_last_strong = strong;
    s_last_rumble_us = now;
}

void bridge_rx_rumble_stop(void)
{
    static const uint8_t neutral[8] = { 0x00, 0x01, 0x40, 0x40, 0x00, 0x01, 0x40, 0x40 };
    bridge_rx_handle_rumble(neutral);
}

/* ---- RX task ---- */

static void rx_task(void *arg)
{
    (void)arg;
    bridge_parser_t parser;
    bridge_parser_init(&parser);
    uint8_t buf[128];
    int64_t last_log = esp_timer_get_time();
    uint32_t last_ok = 0;

    for (;;) {
        int n = uart_read_bytes(BRIDGE_UART, buf, sizeof(buf), pdMS_TO_TICKS(20));
        for (int i = 0; i < n; i++) {
            if (!bridge_parser_feed(&parser, buf[i])) continue;
            if (parser.type != BRIDGE_TYPE_STATE || parser.len != sizeof(bridge_state_t)) continue;
            bridge_state_t s;
            memcpy(&s, parser.payload, sizeof(s));
            imu_sample_t imu;
            convert_imu(&s, &imu);
            int64_t t = esp_timer_get_time();
            portENTER_CRITICAL(&s_lock);
            s_state = s;
            s_state_us = t;
            s_have_state = true;
            s_imu[(s_imu_head + s_imu_count) % 3] = imu;
            if (s_imu_count < 3) {
                s_imu_count++;
            } else {
                s_imu_head = (s_imu_head + 1) % 3;
            }
            portEXIT_CRITICAL(&s_lock);
        }

        int64_t now = esp_timer_get_time();
        if (now - last_log >= 1000000) {
            bridge_state_t s;
            bool have;
            portENTER_CRITICAL(&s_lock);
            s = s_state;
            have = s_have_state;
            portEXIT_CRITICAL(&s_lock);
            ESP_LOGI(TAG, "ok/s=%u crc_err=%u conn=%d btn=%08lx L=%d,%d R=%d,%d rumble_tx=%u",
                     (unsigned)(parser.frames_ok - last_ok), (unsigned)parser.crc_errors,
                     (have && (s.flags & BRIDGE_FLAG_CONNECTED)) ? 1 : 0,
                     (unsigned long)s.buttons, s.lx, s.ly, s.rx, s.ry,
                     (unsigned)s_rumble_sent);
            last_ok = parser.frames_ok;
            last_log = now;
        }
    }
}

void bridge_rx_init(void)
{
    const uart_config_t cfg = {
        .baud_rate = BRIDGE_BAUD,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    ESP_ERROR_CHECK(uart_driver_install(BRIDGE_UART, 1024, 1024, 0, NULL, 0));
    ESP_ERROR_CHECK(uart_param_config(BRIDGE_UART, &cfg));
    ESP_ERROR_CHECK(uart_set_pin(BRIDGE_UART, BRIDGE_TX_PIN, BRIDGE_RX_PIN,
                                 UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));
    xTaskCreate(rx_task, "bridge_rx", 3072, NULL, 5, NULL);
    ESP_LOGI(TAG, "UART2 pronta (TX=%d RX=%d %d baud)", BRIDGE_TX_PIN, BRIDGE_RX_PIN, BRIDGE_BAUD);
}
