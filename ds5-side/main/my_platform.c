// Plataforma custom do Bluepad32: DualSense (+ estado do PC pela UART0) -> frames STATE na UART2;
// RUMBLE da UART2 -> DualSense.
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
#include "input_modes.h"
#include "nvs.h"
#include "nvs_flash.h"

static const char *TAG = "DS5";

#define BRIDGE_UART UART_NUM_2
#define BRIDGE_UART_TX 17
#define BRIDGE_UART_RX 16
#define BRIDGE_UART_BAUD 921600

#define PC_UART UART_NUM_0
#define PC_TIMEOUT_MS 100
#define TX_PERIOD_MS 2
#define IDLE_PERIOD_MS 50
#define STATUS_PERIOD_MS 500
#define SELFTEST_HOLD_MS 1000

// ---- estado compartilhado ------------------------------------------------
static SemaphoreHandle_t s_tx_mutex;
static uint8_t s_seq;
static volatile uint32_t s_frames_sent;
static volatile uint32_t s_rumble_rx;
static volatile bool s_connected;
static portMUX_TYPE s_mux = portMUX_INITIALIZER_UNLOCKED;
static bridge_state_t s_last_state; // para o log de 1 Hz (protegido por s_mux)
static bridge_state_t s_ds5_state;  // ultimo estado do DualSense (protegido por s_mux)
static bridge_state_t s_pc_state;   // ultimo estado vindo do PC (protegido por s_mux)
static int64_t s_pc_rx_ms;          // quando o PC enviou por ultimo (protegido por s_mux)
static volatile uint32_t s_pc_rx_count;  // quadros do PC recebidos (diagnostico)
static volatile uint32_t s_pc_gap_max_ms; // maior intervalo entre quadros do PC no ultimo segundo
static volatile bool s_pc_present;  // PC capturado (para o log)
static volatile trig_mode_t s_mode; // modo atual (escrito so na tx_task)

// So acessados na BT thread (callbacks do Bluepad32 / main thread do BTstack)
static uni_hid_device_t *s_dev;
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

// ---- lightbar do modo: marshalling para a BT thread -----------------------------------
static bool s_light_pending;
static btstack_context_callback_registration_t s_light_reg;

static void mode_color(trig_mode_t mode, uint8_t *r, uint8_t *g, uint8_t *b) {
    *r = 0;
    *g = 0;
    *b = 0;
    switch (mode) {
    case TRIG_MODE_STICK:
        *g = 255;
        break;
    case TRIG_MODE_PWM:
        *r = 255;
        break;
    default:
        *b = 255;
        break;
    }
}

static const char *mode_name(trig_mode_t mode) {
    switch (mode) {
    case TRIG_MODE_STICK:
        return "STICK";
    case TRIG_MODE_PWM:
        return "PWM";
    default:
        return "NORMAL";
    }
}

// Deve rodar na BT thread.
static void set_mode_color(uni_hid_device_t *d) {
    if (d == NULL || d->report_parser.set_lightbar_color == NULL) {
        return;
    }
    uint8_t r, g, b;
    mode_color(s_mode, &r, &g, &b);
    d->report_parser.set_lightbar_color(d, r, g, b);
}

static void light_on_bt_thread(void *ctx) {
    (void)ctx;
    portENTER_CRITICAL(&s_mux);
    s_light_pending = false;
    portEXIT_CRITICAL(&s_mux);
    set_mode_color(s_dev);
}

static void request_mode_color(void) {
    bool schedule = false;
    portENTER_CRITICAL(&s_mux);
    if (!s_light_pending) {
        s_light_pending = true;
        schedule = true;
    }
    portEXIT_CRITICAL(&s_mux);
    if (schedule) {
        s_light_reg.callback = light_on_bt_thread;
        s_light_reg.context = NULL;
        btstack_run_loop_execute_on_main_thread(&s_light_reg);
    }
}

// ---- estado vindo do PC (UART0) -----------------------------------------------------------
static void pc_rx_task(void *arg) {
    (void)arg;
    bridge_parser_t parser;
    bridge_parser_init(&parser);
    uint8_t buf[64];
    int64_t last_pc_ms = 0;
    for (;;) {
        int n = uart_read_bytes(PC_UART, buf, sizeof(buf), pdMS_TO_TICKS(20));
        for (int i = 0; i < n; i++) {
            if (!bridge_parser_feed(&parser, buf[i])) {
                continue;
            }
            if (parser.type != BRIDGE_TYPE_STATE || parser.len != sizeof(bridge_state_t)) {
                continue;
            }
            bridge_state_t st;
            memcpy(&st, parser.payload, sizeof(st));
            int64_t now_ms = esp_timer_get_time() / 1000;
            if (last_pc_ms != 0 && (uint32_t)(now_ms - last_pc_ms) > s_pc_gap_max_ms) {
                s_pc_gap_max_ms = (uint32_t)(now_ms - last_pc_ms);
            }
            last_pc_ms = now_ms;
            s_pc_rx_count++;
            portENTER_CRITICAL(&s_mux);
            s_pc_state = st;
            s_pc_rx_ms = now_ms;
            portEXIT_CRITICAL(&s_mux);
        }
    }
}

static void send_status(trig_mode_t mode, bool ds5_connected) {
    bridge_status_t status = {.trig_mode = (uint8_t)mode, .ds5_connected = ds5_connected ? 1 : 0};
    uint8_t buf[BRIDGE_MAX_PAYLOAD + BRIDGE_FRAME_OVERHEAD];
    size_t n = bridge_encode(BRIDGE_TYPE_STATUS, &status, sizeof(status), buf, sizeof(buf));
    if (n > 0) {
        uart_write_bytes(PC_UART, buf, n);
    }
}

// ---- tx: mescla DualSense + PC, aplica modos e envia ao switch-side a cada 2 ms ---------------
static void tx_task(void *arg) {
    (void)arg;
    input_modes_t modes;
    input_modes_init(&modes);
    TickType_t last_wake = xTaskGetTickCount();
    uint32_t last_idle_ms = 0;
    uint32_t last_status_ms = 0;
    bool first_status = true;
    for (;;) {
        vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(TX_PERIOD_MS));
        int64_t now64 = esp_timer_get_time() / 1000;
        uint32_t now_ms = (uint32_t)now64;

        bool ds5_ok = s_connected;
        bridge_state_t ds5, pc, merged;
        int64_t pc_rx;
        portENTER_CRITICAL(&s_mux);
        ds5 = s_ds5_state;
        pc = s_pc_state;
        pc_rx = s_pc_rx_ms;
        portEXIT_CRITICAL(&s_mux);
        bool pc_ok = (pc_rx != 0) && (now64 - pc_rx < PC_TIMEOUT_MS) && (pc.flags & BRIDGE_FLAG_CONNECTED);
        s_pc_present = pc_ok;

        input_merge(ds5_ok ? &ds5 : NULL, pc_ok ? &pc : NULL, &merged);
        bool mode_changed = input_modes_process(&modes, &merged, now_ms);
        merged.timestamp_ms = (uint16_t)now_ms;
        s_mode = input_modes_get(&modes);
        if (mode_changed) {
            ESP_LOGI(TAG, "Modo de gatilho: %s", mode_name(s_mode));
            request_mode_color();
        }

        if (ds5_ok || pc_ok) {
            send_state(&merged);
        } else if ((uint32_t)(now_ms - last_idle_ms) >= IDLE_PERIOD_MS) {
            last_idle_ms = now_ms;
            send_state(&merged);
        }

        if (mode_changed || first_status || (uint32_t)(now_ms - last_status_ms) >= STATUS_PERIOD_MS) {
            first_status = false;
            last_status_ms = now_ms;
            send_status(s_mode, ds5_ok);
        }
    }
}

// ---- log de 1 Hz ----------------------------------------------------
static void status_task(void *arg) {
    (void)arg;
    uint32_t last_sent = 0;
    uint32_t last_pc_rx = 0;
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(1000));
        bridge_state_t s;
        portENTER_CRITICAL(&s_mux);
        s = s_last_state;
        portEXIT_CRITICAL(&s_mux);
        uint32_t sent = s_frames_sent;
        uint32_t pc_rx = s_pc_rx_count;
        uint32_t gap_max = s_pc_gap_max_ms;
        s_pc_gap_max_ms = 0;
        ESP_LOGI(TAG,
                 "%s mode=%s pc=%d btn=%05" PRIx32 " L(%d,%d) R(%d,%d) L2=%u R2=%u gyro(%d,%d,%d) accel(%d,%d,%d) tx=%" PRIu32
                 "/s rumble_rx=%" PRIu32 " pc_rx=%" PRIu32 "/s pc_gap_max=%" PRIu32 "ms",
                 (s.flags & BRIDGE_FLAG_CONNECTED) ? "CONN" : "idle", mode_name(s_mode), s_pc_present ? 1 : 0,
                 s.buttons, s.lx, s.ly, s.rx, s.ry, s.l2, s.r2,
                 s.gyro[0], s.gyro[1], s.gyro[2], s.accel[0], s.accel[1], s.accel[2], sent - last_sent,
                 s_rumble_rx, pc_rx - last_pc_rx, gap_max);
        last_sent = sent;
        last_pc_rx = pc_rx;
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
    // UART0 (console USB): mantem o baud do console (115200); so instala o driver para ler frames do PC.
    ESP_ERROR_CHECK(uart_driver_install(PC_UART, 1024, 0, 0, NULL, 0));
    xTaskCreate(rumble_rx_task, "rumble_rx", 4096, NULL, 5, NULL);
    xTaskCreate(pc_rx_task, "pc_rx", 4096, NULL, 5, NULL);
    xTaskCreate(tx_task, "tx", 4096, NULL, 6, NULL);
    xTaskCreate(status_task, "status", 6144, NULL, 3, NULL);
    ESP_LOGI(TAG, "UART%d pronta: TX=%d RX=%d %d 8N1", BRIDGE_UART, BRIDGE_UART_TX, BRIDGE_UART_RX,
             BRIDGE_UART_BAUD);
}

static void block_load(void);

// ---- callbacks da plataforma Bluepad32 -------------------------------------------
static void my_platform_init(int argc, const char **argv) {
    ARG_UNUSED(argc);
    ARG_UNUSED(argv);
    block_load();
    bridge_uart_start();
}

static void my_platform_on_init_complete(void) {
    // Chamado na BT thread: as versoes _unsafe sao seguras aqui.
    uni_bt_start_scanning_and_autoconnect_unsafe();
    uni_bt_allow_incoming_connections(true);
    ESP_LOGI(TAG, "Bluepad32 pronto. Pareie o DualSense: segure PS + Create ate a luz piscar rapido.");
}

// ---- bloqueio de aparelhos que nao sao DualSense ------------------------------------
// O inquiry as vezes vem sem nome; ai o Bluepad32 conectava no proprio switch-side
// ("Pro Controller"), roubando banda do link com o Switch e injetando o stick dele.
// Quem nao for DualSense e' recusado em on_device_ready e o endereco fica bloqueado (NVS).
#define BLOCK_MAX 4
#define SONY_VID 0x054C
static bd_addr_t s_block[BLOCK_MAX];
static int s_block_n;

static bool is_blocked(const bd_addr_t addr) {
    for (int i = 0; i < s_block_n; i++) {
        if (memcmp(s_block[i], addr, sizeof(bd_addr_t)) == 0) {
            return true;
        }
    }
    return false;
}

static void block_load(void) {
    nvs_flash_init();
    nvs_handle_t h;
    if (nvs_open("ds5bridge", NVS_READONLY, &h) != ESP_OK) {
        return;
    }
    size_t len = sizeof(s_block);
    if (nvs_get_blob(h, "block", s_block, &len) == ESP_OK) {
        s_block_n = (int)(len / sizeof(bd_addr_t));
    }
    nvs_close(h);
    ESP_LOGI(TAG, "%d endereco(s) bloqueado(s)", s_block_n);
}

static void block_add(const bd_addr_t addr) {
    if (is_blocked(addr)) {
        return;
    }
    if (s_block_n == BLOCK_MAX) { // descarta o mais antigo
        memmove(s_block[0], s_block[1], sizeof(bd_addr_t) * (BLOCK_MAX - 1));
        s_block_n--;
    }
    memcpy(s_block[s_block_n++], addr, sizeof(bd_addr_t));
    nvs_handle_t h;
    if (nvs_open("ds5bridge", NVS_READWRITE, &h) == ESP_OK) {
        nvs_set_blob(h, "block", s_block, sizeof(bd_addr_t) * s_block_n);
        nvs_commit(h);
        nvs_close(h);
    }
}

static uni_error_t my_platform_on_device_discovered(bd_addr_t addr, const char *name, uint16_t cod, uint8_t rssi) {
    ARG_UNUSED(rssi);
    // So gamepads/joysticks.
    uint16_t minor = cod & UNI_BT_COD_MINOR_MASK;
    if ((minor & (UNI_BT_COD_MINOR_GAMEPAD | UNI_BT_COD_MINOR_JOYSTICK)) == 0) {
        return UNI_ERROR_IGNORE_DEVICE;
    }
    if (is_blocked(addr)) {
        return UNI_ERROR_IGNORE_DEVICE;
    }
    // So DualSense: o switch-side (e Pro Controllers reais) tambem anunciam COD de gamepad
    // e ocupariam a unica vaga. Sem nome no inquiry, deixa passar (verificado em on_device_ready).
    if (name != NULL && name[0] != '\0' && strstr(name, "DualSense") == NULL) {
        ESP_LOGI(TAG, "Ignorando \"%s\" (nao e DualSense)", name);
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
    if (d->vendor_id != SONY_VID) {
        ESP_LOGW(TAG, "Recusando \"%s\" vid=%04x (nao e DualSense); endereco bloqueado", d->name, d->vendor_id);
        block_add(d->conn.btaddr);
        return UNI_ERROR_IGNORE_DEVICE;
    }
    if (s_dev != NULL && s_dev != d) {
        return UNI_ERROR_IGNORE_DEVICE; // apenas um controle
    }
    s_dev = d;
    s_connected = true;
    ESP_LOGI(TAG, "Controle pronto: \"%s\" tipo=%d vid=%04x pid=%04x bateria=%u", d->name, (int)d->controller_type,
             d->vendor_id, d->product_id, d->controller.battery);
    set_mode_color(d);
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
    st.timestamp_ms = (uint16_t)(esp_timer_get_time() / 1000);

    selftest(st.buttons);

    // A tx_task mescla com o estado do PC e envia ao switch-side.
    portENTER_CRITICAL(&s_mux);
    s_ds5_state = st;
    portEXIT_CRITICAL(&s_mux);
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
