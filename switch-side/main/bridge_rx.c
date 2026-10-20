/*
 * bridge_rx: recebe bridge_state_t do app do PC (UART0, console USB), converte para o
 * controller_state_t + IMU do Pro Controller e envia o STATUS de volta ao PC.
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

#define PC_UART UART_NUM_0 /* console USB: frames do app do PC (115200) */
#define PC_TIMEOUT_US 100000
#define INGEST_PERIOD_MS 2
#define STATUS_PERIOD_MS 500

#define STALE_US 200000
#define STICK_DEADZONE 24
#define TRIGGER_THRESHOLD 512

/* Remap dos eixos do protocolo (x=pitch, y=yaw, z=roll) -> Pro Controller.
 * Aplicado igual a accel e gyro. Ajustar aqui se os eixos estiverem trocados/invertidos. */
#define IMU_SW_X(v) (-(int32_t)(v)[2])
#define IMU_SW_Y(v) (-(int32_t)(v)[0])
#define IMU_SW_Z(v) ((int32_t)(v)[1])
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

/* Ultimo frame cru do PC */
static bridge_state_t s_pc_state;
static int64_t s_pc_us;
static volatile uint32_t s_pc_frames, s_pc_crc_errors, s_pc_gap_max_ms;

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

/* Grava o estado ja mesclado e empilha a amostra IMU */
static void ingest_state(const bridge_state_t *s)
{
    imu_sample_t imu;
    convert_imu(s, &imu);
    int64_t t = esp_timer_get_time();
    portENTER_CRITICAL(&s_lock);
    s_state = *s;
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

/* Le frames da UART0 (PC); guarda o ultimo STATE cru */
static void pc_rx_task(void *arg)
{
    (void)arg;
    bridge_parser_t parser;
    bridge_parser_init(&parser);
    uint8_t buf[128];
    int64_t last_frame_us = 0;

    for (;;) {
        int n = uart_read_bytes(PC_UART, buf, sizeof(buf), pdMS_TO_TICKS(20));
        for (int i = 0; i < n; i++) {
            if (!bridge_parser_feed(&parser, buf[i])) continue;
            if (parser.type != BRIDGE_TYPE_STATE || parser.len != sizeof(bridge_state_t)) continue;
            bridge_state_t s;
            memcpy(&s, parser.payload, sizeof(s));
            int64_t t = esp_timer_get_time();
            if (last_frame_us != 0 && (uint32_t)((t - last_frame_us) / 1000) > s_pc_gap_max_ms) {
                s_pc_gap_max_ms = (uint32_t)((t - last_frame_us) / 1000);
            }
            last_frame_us = t;
            portENTER_CRITICAL(&s_lock);
            s_pc_state = s;
            s_pc_us = t;
            portEXIT_CRITICAL(&s_lock);
        }
        s_pc_frames = parser.frames_ok;
        s_pc_crc_errors = parser.crc_errors;
    }
}

/* Repete o ultimo frame do PC a cada INGEST_PERIOD_MS enquanto ele estiver fresco
 * e envia o STATUS periodico ao PC */
static void ingest_task(void *arg)
{
    (void)arg;
    TickType_t last_wake = xTaskGetTickCount();
    int64_t last_log = esp_timer_get_time();
    int64_t last_status = 0;
    bool first_status = true;
    uint32_t last_pc = 0;

    for (;;) {
        vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(INGEST_PERIOD_MS));

        bridge_state_t pc;
        int64_t pc_us;
        portENTER_CRITICAL(&s_lock);
        pc = s_pc_state;
        pc_us = s_pc_us;
        portEXIT_CRITICAL(&s_lock);

        int64_t now = esp_timer_get_time();
        bool pc_ok = pc_us != 0 && (now - pc_us) < PC_TIMEOUT_US && (pc.flags & BRIDGE_FLAG_CONNECTED);

        /* Sem frame valido: nao atualiza, o estado envelhece e vira neutro */
        if (pc_ok) {
            ingest_state(&pc);
        }

        if (first_status || (now - last_status) >= STATUS_PERIOD_MS * 1000) {
            bridge_status_t st = { .trig_mode = 0, .fw_version = BRIDGE_FW_VERSION };
            uint8_t frame[BRIDGE_FRAME_OVERHEAD + sizeof(st)];
            size_t n = bridge_encode(BRIDGE_TYPE_STATUS, &st, sizeof(st), frame, sizeof(frame));
            if (n) uart_write_bytes(PC_UART, frame, n);
            first_status = false;
            last_status = now;
        }

        if (now - last_log >= 1000000) {
            uint32_t pc_f = s_pc_frames;
            ESP_LOGI(TAG, "pc/s=%u crc_err=%u conn=%d btn=%08lx L=%d,%d R=%d,%d gap_max=%ums",
                     (unsigned)(pc_f - last_pc), (unsigned)s_pc_crc_errors, pc_ok ? 1 : 0,
                     (unsigned long)pc.buttons, pc.lx, pc.ly, pc.rx, pc.ry,
                     (unsigned)s_pc_gap_max_ms);
            s_pc_gap_max_ms = 0;
            last_pc = pc_f;
            last_log = now;
        }
    }
}

void bridge_rx_init(void)
{
    ESP_ERROR_CHECK(uart_driver_install(PC_UART, 1024, 0, 0, NULL, 0));
    xTaskCreate(pc_rx_task, "pc_rx", 4096, NULL, 5, NULL);
    xTaskCreate(ingest_task, "ingest", 4096, NULL, 6, NULL);
    ESP_LOGI(TAG, "UART0 (PC) pronta");
}