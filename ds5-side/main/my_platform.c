// Plataforma custom do Bluepad32: DualSense -> frames STATE na UART2; RUMBLE da UART2 -> DualSense.
#include <inttypes.h>
#include <stdio.h>
#include <string.h>

#include <btstack_run_loop.h>
#include <uni.h>

#include "bridge_proto.h"
#include "driver/uart.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

static const char *TAG = "DS5";

#define BRIDGE_UART UART_NUM_2
#define BRIDGE_UART_TX 17
#define BRIDGE_UART_RX 16
#define BRIDGE_UART_BAUD 921600

#define MIN_STATE_INTERVAL_US 1000 // limite de 1 kHz
#define HEARTBEAT_MS 50
#define SELFTEST_HOLD_MS 1000

// ---- estado compartilhado ------------------------------------------------
static SemaphoreHandle_t s_tx_mutex;
static uint8_t s_seq;
static volatile uint32_t s_frames_sent;
static volatile uint32_t s_rumble_rx;
static volatile bool s_connected;
static portMUX_TYPE s_mux = portMUX_INITIALIZER_UNLOCKED;
static bridge_state_t s_last_state; // para o log de 1 Hz (protegido por s_mux)

// So acessados na BT thread (callbacks do Bluepad32 / main thread do BTstack)
static uni_hid_device_t *s_dev;
static int64_t s_last_tx_us;
static int64_t s_l1r1_since_ms;
static bool s_selftest_fired;

// ---- helpers --------------------------------------------------------------
static int16_t sat16(int32_t v) {
    return (int16_t)(v > INT16_MAX ? INT16_MAX : (v < INT16_MIN ? INT16_MIN : v));
}

static uint16_t clamp_u16(int32_t v, int32_t max) {
    return (uint16_t)(v < 0 ? 0 : (v > max ? max : v));
}

static void send_state(bridge_state_t *st) {
    uint8_t buf[BRIDGE_MAX_PAYLOAD + BRIDGE_FRAME_OVERHEAD];
    xSemaphoreTake(s_tx_mutex, portMAX_DELAY);
    st->seq = s_seq++;
    size_t n = bridge_encode(BRIDGE_TYPE_STATE, st, sizeof(*st), buf, sizeof(buf));
    if (n > 0) {
        uart_write_bytes(BRIDGE_UART, buf, n);
        s_frames_sent++;
    }
    xSemaphoreGive(s_tx_mutex);
    portENTER_CRITICAL(&s_mux);
    s_last_state = *st;
    portEXIT_CRITICAL(&s_mux);
}

// Deve rodar na BT thread.
static void apply_rumble(uint8_t weak, uint8_t strong, uint16_t duration_ms) {
    uni_hid_device_t *d = s_dev;
    if (d == NULL || d->report_parser.play_dual_rumble == NULL) {
        return;
    }
    if (duration_ms == 0) {
        weak = 0;
        strong = 0;
    }
    d->report_parser.play_dual_rumble(d, 0, duration_ms, weak, strong);
}

// ---- RUMBLE vindo da UART: marshalling para a BT thread -----------------------
static bridge_rumble_t s_pending_rumble;
static bool s_rumble_pending;
static btstack_context_callback_registration_t s_rumble_reg;

static void rumble_on_bt_thread(void *ctx) {
    (void)ctx;
    bridge_rumble_t r;
    portENTER_CRITICAL(&s_mux);
    r = s_pending_rumble;
    s_rumble_pending = false;
    portEXIT_CRITICAL(&s_mux);
    apply_rumble(r.weak, r.strong, r.duration_ms);
}

static void rumble_rx_task(void *arg) {
    (void)arg;
    bridge_parser_t parser;
    bridge_parser_init(&parser);
    uint8_t buf[64];
    for (;;) {
        int n = uart_read_bytes(BRIDGE_UART, buf, sizeof(buf), pdMS_TO_TICKS(20));
        for (int i = 0; i < n; i++) {
            if (!bridge_parser_feed(&parser, buf[i])) {
                continue;
            }
            if (parser.type != BRIDGE_TYPE_RUMBLE || parser.len != sizeof(bridge_rumble_t)) {
                continue;
            }
            bridge_rumble_t r;
            memcpy(&r, parser.payload, sizeof(r));
            s_rumble_rx++;
            bool schedule = false;
            portENTER_CRITICAL(&s_mux);
            s_pending_rumble = r; // o mais recente vence
            if (!s_rumble_pending) {
                s_rumble_pending = true;
                schedule = true;
            }
            portEXIT_CRITICAL(&s_mux);
            if (schedule) {
                s_rumble_reg.callback = rumble_on_bt_thread;
                s_rumble_reg.context = NULL;
                btstack_run_loop_execute_on_main_thread(&s_rumble_reg);
            }
        }
    }
}

// ---- heartbeat + log de 1 Hz ----------------------------------------------------
static void status_task(void *arg) {
    (void)arg;
    uint32_t last_sent = 0;
    int ms_since_log = 0;
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(HEARTBEAT_MS));
        if (!s_connected) {
            bridge_state_t hb;
            memset(&hb, 0, sizeof(hb));
            hb.timestamp_ms = (uint16_t)(esp_timer_get_time() / 1000);
            send_state(&hb);
        }
        ms_since_log += HEARTBEAT_MS;
        if (ms_since_log < 1000) {
            continue;
        }
        ms_since_log = 0;
        bridge_state_t s;
        portENTER_CRITICAL(&s_mux);
        s = s_last_state;
        portEXIT_CRITICAL(&s_mux);
        uint32_t sent = s_frames_sent;
        ESP_LOGI(TAG,
                 "%s btn=%05" PRIx32 " L(%d,%d) R(%d,%d) L2=%u R2=%u gyro(%d,%d,%d) accel(%d,%d,%d) tx=%" PRIu32
                 "/s rumble_rx=%" PRIu32,
                 (s.flags & BRIDGE_FLAG_CONNECTED) ? "CONN" : "idle", s.buttons, s.lx, s.ly, s.rx, s.ry, s.l2, s.r2,
                 s.gyro[0], s.gyro[1], s.gyro[2], s.accel[0], s.accel[1], s.accel[2], sent - last_sent,
                 s_rumble_rx);
        last_sent = sent;
    }
}

static void bridge_uart_start(void) {
    const uart_config_t cfg = {
        .baud_rate = BRIDGE_UART_BAUD,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    ESP_ERROR_CHECK(uart_driver_install(BRIDGE_UART, 1024, 2048, 0, NULL, 0));
    ESP_ERROR_CHECK(uart_param_config(BRIDGE_UART, &cfg));
    ESP_ERROR_CHECK(uart_set_pin(BRIDGE_UART, BRIDGE_UART_TX, BRIDGE_UART_RX, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));
    s_tx_mutex = xSemaphoreCreateMutex();
    xTaskCreate(rumble_rx_task, "rumble_rx", 3072, NULL, 5, NULL);
    xTaskCreate(status_task, "status", 3072, NULL, 3, NULL);
    ESP_LOGI(TAG, "UART%d pronta: TX=%d RX=%d %d 8N1", BRIDGE_UART, BRIDGE_UART_TX, BRIDGE_UART_RX,
             BRIDGE_UART_BAUD);
}

// ---- callbacks da plataforma Bluepad32 -------------------------------------------
static void my_platform_init(int argc, const char **argv) {
    ARG_UNUSED(argc);
    ARG_UNUSED(argv);
    bridge_uart_start();
}

static void my_platform_on_init_complete(void) {
    // Chamado na BT thread: as versoes _unsafe sao seguras aqui.
    uni_bt_start_scanning_and_autoconnect_unsafe();
    uni_bt_allow_incoming_connections(true);
    ESP_LOGI(TAG, "Bluepad32 pronto. Pareie o DualSense: segure PS + Create ate a luz piscar rapido.");
}

static uni_error_t my_platform_on_device_discovered(bd_addr_t addr, const char *name, uint16_t cod, uint8_t rssi) {
    ARG_UNUSED(addr);
    ARG_UNUSED(name);
    ARG_UNUSED(rssi);
    // So gamepads/joysticks.
    uint16_t minor = cod & UNI_BT_COD_MINOR_MASK;
    if ((minor & (UNI_BT_COD_MINOR_GAMEPAD | UNI_BT_COD_MINOR_JOYSTICK)) == 0) {
        return UNI_ERROR_IGNORE_DEVICE;
    }
    return UNI_ERROR_SUCCESS;
}

static void my_platform_on_device_connected(uni_hid_device_t *d) {
    ESP_LOGI(TAG, "Dispositivo conectado: %s", d->name);
}

static void my_platform_on_device_disconnected(uni_hid_device_t *d) {
    ESP_LOGI(TAG, "Desconectado: %s", d->name);
    if (d == s_dev) {
        s_dev = NULL;
        s_connected = false;
        s_l1r1_since_ms = 0;
        s_selftest_fired = false;
    }
}

static uni_error_t my_platform_on_device_ready(uni_hid_device_t *d) {
    if (s_dev != NULL && s_dev != d) {
        return UNI_ERROR_IGNORE_DEVICE; // apenas um controle
    }
    s_dev = d;
    s_connected = true;
    ESP_LOGI(TAG, "Controle pronto: \"%s\" tipo=%d vid=%04x pid=%04x bateria=%u", d->name, (int)d->controller_type,
             d->vendor_id, d->product_id, d->controller.battery);
    if (d->report_parser.set_lightbar_color != NULL) {
        d->report_parser.set_lightbar_color(d, 0, 0, 255);
    }
    return UNI_ERROR_SUCCESS;
}

static uint32_t map_buttons(const uni_gamepad_t *gp) {
    uint32_t b = 0;
#define MAP(cond, bit)                 \
    do {                               \
        if (cond)                      \
            b |= BRIDGE_BTN_MASK(bit); \
    } while (0)
    MAP(gp->buttons & BUTTON_A, BRIDGE_BTN_A);
    MAP(gp->buttons & BUTTON_B, BRIDGE_BTN_B);
    MAP(gp->buttons & BUTTON_X, BRIDGE_BTN_X);
    MAP(gp->buttons & BUTTON_Y, BRIDGE_BTN_Y);
    MAP(gp->buttons & BUTTON_SHOULDER_L, BRIDGE_BTN_L1);
    MAP(gp->buttons & BUTTON_SHOULDER_R, BRIDGE_BTN_R1);
    MAP(gp->buttons & BUTTON_TRIGGER_L, BRIDGE_BTN_L2_DIGITAL);
    MAP(gp->buttons & BUTTON_TRIGGER_R, BRIDGE_BTN_R2_DIGITAL);
    MAP(gp->buttons & BUTTON_THUMB_L, BRIDGE_BTN_L3);
    MAP(gp->buttons & BUTTON_THUMB_R, BRIDGE_BTN_R3);
    MAP(gp->dpad & DPAD_UP, BRIDGE_BTN_DPAD_UP);
    MAP(gp->dpad & DPAD_DOWN, BRIDGE_BTN_DPAD_DOWN);
    MAP(gp->dpad & DPAD_LEFT, BRIDGE_BTN_DPAD_LEFT);
    MAP(gp->dpad & DPAD_RIGHT, BRIDGE_BTN_DPAD_RIGHT);
    MAP(gp->misc_buttons & MISC_BUTTON_SELECT, BRIDGE_BTN_SELECT);
    MAP(gp->misc_buttons & MISC_BUTTON_START, BRIDGE_BTN_START);
    MAP(gp->misc_buttons & MISC_BUTTON_SYSTEM, BRIDGE_BTN_SYSTEM);
    MAP(gp->misc_buttons & MISC_BUTTON_CAPTURE, BRIDGE_BTN_CAPTURE);
#undef MAP
    return b;
}

static void selftest(uint32_t buttons) {
    const uint32_t both = BRIDGE_BTN_MASK(BRIDGE_BTN_L1) | BRIDGE_BTN_MASK(BRIDGE_BTN_R1);
    int64_t now_ms = esp_timer_get_time() / 1000;
    if ((buttons & both) != both) {
        s_l1r1_since_ms = 0;
        s_selftest_fired = false;
        return;
    }
    if (s_l1r1_since_ms == 0) {
        s_l1r1_since_ms = now_ms;
    } else if (!s_selftest_fired && now_ms - s_l1r1_since_ms >= SELFTEST_HOLD_MS) {
        s_selftest_fired = true;
        ESP_LOGI(TAG, "Auto-teste de rumble (L1+R1 por 1 s): 300 ms weak=128 strong=128");
        apply_rumble(128, 128, 300);
    }
}

static void my_platform_on_controller_data(uni_hid_device_t *d, uni_controller_t *ctl) {
    if (ctl->klass != UNI_CONTROLLER_CLASS_GAMEPAD || d != s_dev) {
        return;
    }
    const uni_gamepad_t *gp = &ctl->gamepad;
    bridge_state_t st;
    memset(&st, 0, sizeof(st));
    st.flags = BRIDGE_FLAG_CONNECTED;
    st.battery = ctl->battery;
    if (ctl->battery != 0 && ctl->battery <= 50) {
        st.flags |= BRIDGE_FLAG_BATTERY_LOW; // Bluepad32 4.2 nao informa "carregando" no DS5
    }
    st.buttons = map_buttons(gp);
    st.lx = sat16(gp->axis_x);
    st.ly = sat16(gp->axis_y);
    st.rx = sat16(gp->axis_rx);
    st.ry = sat16(gp->axis_ry);
    st.l2 = clamp_u16(gp->brake, 1023);
    st.r2 = clamp_u16(gp->throttle, 1023);
    for (int i = 0; i < 3; i++) {
        st.gyro[i] = sat16(gp->gyro[i] >> 6); // 1/1024 deg/s -> 1/16 deg/s
        st.accel[i] = sat16(gp->accel[i]);    // 1/8192 G
    }
    int64_t now_us = esp_timer_get_time();
    st.timestamp_ms = (uint16_t)(now_us / 1000);

    selftest(st.buttons);

    if (now_us - s_last_tx_us < MIN_STATE_INTERVAL_US) {
        return;
    }
    s_last_tx_us = now_us;
    send_state(&st);
}

static const uni_property_t *my_platform_get_property(uni_property_idx_t idx) {
    ARG_UNUSED(idx);
    return NULL;
}

static void my_platform_on_oob_event(uni_platform_oob_event_t event, void *data) {
    ARG_UNUSED(event);
    ARG_UNUSED(data);
}

struct uni_platform *get_my_platform(void) {
    static struct uni_platform plat = {
        .name = "ds5-bridge",
        .init = my_platform_init,
        .on_init_complete = my_platform_on_init_complete,
        .on_device_discovered = my_platform_on_device_discovered,
        .on_device_connected = my_platform_on_device_connected,
        .on_device_disconnected = my_platform_on_device_disconnected,
        .on_device_ready = my_platform_on_device_ready,
        .on_oob_event = my_platform_on_oob_event,
        .on_controller_data = my_platform_on_controller_data,
        .get_property = my_platform_get_property,
    };
    return &plat;
}
