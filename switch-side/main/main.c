/*
 * Nintendo Switch Pro Controller emulation over Bluetooth Classic HID (ESP32, Bluedroid).
 * Phase 0: pairing test with an optional auto-press sequence.
 * Based on ESP-IDF example bt_hid_mouse_device; protocol ported from joycontrol.
 */
#include <inttypes.h>
#include <stdio.h>
#include <string.h>

#include "driver/gpio.h"
#include "esp_bt.h"
#include "esp_bt_device.h"
#include "esp_bt_main.h"
#include "esp_err.h"
#include "esp_gap_bt_api.h"
#include "esp_hidd_api.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "sdkconfig.h"

#include "procon_hid_descriptor.h"
#include "procon_protocol.h"

#define TAG "PROCON"

#define DEVICE_NAME      "Pro Controller"
#define NINTENDO_OUI     {0x98, 0xB6, 0xE9}
#define BOOT_GPIO        GPIO_NUM_0
#define BOOT_HOLD_MS     2000
#define REPORT_PERIOD_MS 15  /* protocol.py: send_delay = 0.015 */
#define REPLY_QUIET_MS   300 /* protocol.py: "avoid flooding during pairing" pause after a reply */

#define NVS_NS  "procon"
#define NVS_KEY "host"

static procon_state_t s_state;
static SemaphoreHandle_t s_lock; /* protects s_state and serialises sends */
static volatile bool s_connected;
static volatile int64_t s_mode_set_us;   /* time input mode 0x30 was set (0 = not set) */
static volatile int64_t s_quiet_until_us; /* no 0x30 reports before this time */
static uint8_t s_host[6];
static bool s_have_host;

/* ---------- helpers ---------- */

static void fmt_addr(const uint8_t *a, char *out)
{
    sprintf(out, "%02x:%02x:%02x:%02x:%02x:%02x", a[0], a[1], a[2], a[3], a[4], a[5]);
}

static bool nvs_load_host(uint8_t host[6])
{
    nvs_handle_t h;
    size_t len = 6;
    bool ok = false;
    if (nvs_open(NVS_NS, NVS_READONLY, &h) == ESP_OK) {
        ok = nvs_get_blob(h, NVS_KEY, host, &len) == ESP_OK && len == 6;
        nvs_close(h);
    }
    return ok;
}

static void nvs_store_host(const uint8_t host[6])
{
    nvs_handle_t h;
    if (nvs_open(NVS_NS, NVS_READWRITE, &h) == ESP_OK) {
        nvs_set_blob(h, NVS_KEY, host, 6);
        nvs_commit(h);
        nvs_close(h);
    }
}

static void nvs_erase_host(void)
{
    nvs_handle_t h;
    if (nvs_open(NVS_NS, NVS_READWRITE, &h) == ESP_OK) {
        nvs_erase_key(h, NVS_KEY);
        nvs_commit(h);
        nvs_close(h);
    }
}

/* Hold BOOT (GPIO0) for 2 s at power-up to forget the stored host. */
static bool boot_button_held_2s(void)
{
    gpio_config_t io = {
        .pin_bit_mask = 1ULL << BOOT_GPIO,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
    };
    gpio_config(&io);
    if (gpio_get_level(BOOT_GPIO) != 0) {
        return false;
    }
    ESP_LOGI(TAG, "BOOT held, keep holding for 2 s to clear pairing...");
    for (int t = 0; t < BOOT_HOLD_MS; t += 50) {
        vTaskDelay(pdMS_TO_TICKS(50));
        if (gpio_get_level(BOOT_GPIO) != 0) {
            return false;
        }
    }
    return true;
}

static void remove_all_bonds(void)
{
    int n = esp_bt_gap_get_bond_device_num();
    if (n <= 0) {
        return;
    }
    esp_bd_addr_t *list = malloc(sizeof(esp_bd_addr_t) * n);
    if (list && esp_bt_gap_get_bond_device_list(&n, list) == ESP_OK) {
        for (int i = 0; i < n; i++) {
            esp_bt_gap_remove_bond_device(list[i]);
        }
        ESP_LOGI(TAG, "removed %d bonded device(s)", n);
    }
    free(list);
}

/* ---------- report sending ---------- */

/* Caller must hold s_lock. */
static void send_report_locked(const procon_report_t *rep)
{
    esp_err_t err = esp_bt_hid_device_send_report(ESP_HIDD_REPORT_TYPE_INTRDATA, rep->id, rep->len,
                                                  (uint8_t *)rep->payload);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "send_report 0x%02x failed: %s", rep->id, esp_err_to_name(err));
    }
}

static void log_hex(const char *prefix, const uint8_t *d, size_t n)
{
    char line[3 * 40 + 1];
    size_t m = n > 40 ? 40 : n;
    for (size_t i = 0; i < m; i++) {
        sprintf(&line[3 * i], "%02x ", d[i]);
    }
    line[3 * m] = 0;
    ESP_LOGI(TAG, "%s %s%s", prefix, line, n > m ? "..." : "");
}

/* Handles an output report from the Switch (interrupt channel or SET_REPORT). */
static void on_output_report(uint8_t report_id, const uint8_t *data, uint16_t len)
{
    uint8_t buf[80];
    if (len > sizeof(buf) - 1) {
        len = sizeof(buf) - 1;
    }
    buf[0] = report_id;
    memcpy(&buf[1], data, len);

    if (report_id != PROCON_OUT_ID_SUBCMD && report_id != PROCON_OUT_ID_RUMBLE) {
        ESP_LOGW(TAG, "unhandled output report 0x%02x len=%u", report_id, len);
        return;
    }

    const uint8_t *bda = esp_bt_dev_get_address();
    procon_result_t res;

    xSemaphoreTake(s_lock, portMAX_DELAY);
    uint8_t old_mode = s_state.input_mode;
    procon_handle_output(&s_state, buf, (size_t)len + 1, bda, &res);
    if (res.is_subcmd) {
        char p[32];
        snprintf(p, sizeof(p), "subcmd 0x%02x args:", res.subcmd);
        log_hex(p, res.args, res.args_len > 12 ? 12 : res.args_len);
    }
    if (res.has_reply) {
        send_report_locked(&res.reply);
        s_quiet_until_us = esp_timer_get_time() + REPLY_QUIET_MS * 1000;
    }
    if (res.mode_changed) {
        ESP_LOGI(TAG, "input report mode set to 0x%02x (was 0x%02x)", s_state.input_mode, old_mode);
        s_mode_set_us = esp_timer_get_time();
    }
    xSemaphoreGive(s_lock);
}

/* ---------- 0x30 streaming + auto-press test ---------- */

#if CONFIG_AUTOPRESS_TEST
/* Returns the button bytes for `ms` milliseconds after mode 0x30 was set. */
static procon_buttons_t autopress_buttons(int64_t ms)
{
    procon_buttons_t b = {0};
    if (ms >= 3000 && ms < 3200) {
        /* L+R together: registers the controller on the "Change Grip/Order" screen. */
        b.b3 |= PROCON_BTN3_L;
        b.b1 |= PROCON_BTN1_R;
    } else if (ms >= 5200 && ((ms - 5200) % 2000) < 100) {
        b.b1 |= PROCON_BTN1_A;
    }
    return b;
}
#endif

static void report_task(void *arg)
{
#if CONFIG_AUTOPRESS_TEST
    procon_buttons_t last = {0};
#endif
    TickType_t wake = xTaskGetTickCount();
    for (;;) {
        vTaskDelayUntil(&wake, pdMS_TO_TICKS(REPORT_PERIOD_MS));
        if (!s_connected) {
            continue;
        }
        xSemaphoreTake(s_lock, portMAX_DELAY);
        int64_t now = esp_timer_get_time();
        if (s_state.input_mode == 0x30 && now >= s_quiet_until_us) {
#if CONFIG_AUTOPRESS_TEST
            s_state.buttons = autopress_buttons((now - s_mode_set_us) / 1000);
            if (memcmp(&last, &s_state.buttons, sizeof(last)) != 0) {
                if (s_state.buttons.b1 || s_state.buttons.b3) {
                    ESP_LOGI(TAG, "AUTOPRESS %s", s_state.buttons.b3 ? "L+R" : "A");
                } else {
                    ESP_LOGI(TAG, "AUTOPRESS release");
                }
                last = s_state.buttons;
            }
#endif
            procon_report_t rep;
            procon_build_full_report(&s_state, &rep);
            send_report_locked(&rep);
        }
        xSemaphoreGive(s_lock);
    }
}

/* ---------- Bluetooth callbacks ---------- */

static void gap_cb(esp_bt_gap_cb_event_t event, esp_bt_gap_cb_param_t *param)
{
    switch (event) {
    case ESP_BT_GAP_AUTH_CMPL_EVT:
        if (param->auth_cmpl.stat == ESP_BT_STATUS_SUCCESS) {
            char a[18];
            fmt_addr(param->auth_cmpl.bda, a);
            ESP_LOGI(TAG, "authentication success: '%s' %s", param->auth_cmpl.device_name, a);
        } else {
            ESP_LOGE(TAG, "authentication failed, status:%d", param->auth_cmpl.stat);
        }
        break;
    case ESP_BT_GAP_PIN_REQ_EVT: {
        ESP_LOGI(TAG, "legacy PIN request, replying 0000");
        esp_bt_pin_code_t pin = {'0', '0', '0', '0'};
        esp_bt_gap_pin_reply(param->pin_req.bda, true, 4, pin);
        break;
    }
    case ESP_BT_GAP_CFM_REQ_EVT:
        ESP_LOGI(TAG, "SSP confirm request %06" PRIu32 ", accepting", param->cfm_req.num_val);
        esp_bt_gap_ssp_confirm_reply(param->cfm_req.bda, true);
        break;
    case ESP_BT_GAP_MODE_CHG_EVT:
        ESP_LOGI(TAG, "ACL power mode changed: %d", param->mode_chg.mode);
        break;
    default:
        ESP_LOGD(TAG, "gap event %d", event);
        break;
    }
}

static void hidd_cb(esp_hidd_cb_event_t event, esp_hidd_cb_param_t *param)
{
    static esp_hidd_qos_param_t qos; /* all zero = don't care, as in the mouse example */
    static esp_hidd_app_param_t app = {
        .name = "Wireless Gamepad", /* SDP 0x0100..0x0102 from joycontrol's sdp_record_hid.xml */
        .description = "Gamepad",
        .provider = "Nintendo",
        .subclass = 0x08, /* gamepad, matches the CoD minor class */
    };

    switch (event) {
    case ESP_HIDD_INIT_EVT:
        if (param->init.status == ESP_HIDD_SUCCESS) {
            app.desc_list = (uint8_t *)procon_hid_descriptor;
            app.desc_list_len = sizeof(procon_hid_descriptor);
            esp_bt_hid_device_register_app(&app, &qos, &qos);
        } else {
            ESP_LOGE(TAG, "HID device init failed");
        }
        break;
    case ESP_HIDD_REGISTER_APP_EVT:
        if (param->register_app.status == ESP_HIDD_SUCCESS) {
            ESP_LOGI(TAG, "HID app registered; connectable + discoverable");
            esp_bt_gap_set_scan_mode(ESP_BT_CONNECTABLE, ESP_BT_GENERAL_DISCOVERABLE);
            if (s_have_host) {
                char a[18];
                fmt_addr(s_host, a);
                ESP_LOGI(TAG, "reconnecting to stored host %s", a);
                esp_bt_hid_device_connect(s_host);
            } else {
                ESP_LOGI(TAG, "no stored host: waiting for pairing (Controllers > Change Grip/Order)");
            }
        } else {
            ESP_LOGE(TAG, "HID app register failed");
        }
        break;
    case ESP_HIDD_OPEN_EVT:
        if (param->open.status != ESP_HIDD_SUCCESS) {
            ESP_LOGE(TAG, "connection open failed (status %d)", param->open.status);
        } else if (param->open.conn_status == ESP_HIDD_CONN_STATE_CONNECTING) {
            ESP_LOGI(TAG, "connection state: connecting");
        } else if (param->open.conn_status == ESP_HIDD_CONN_STATE_CONNECTED) {
            char a[18];
            fmt_addr(param->open.bd_addr, a);
            ESP_LOGI(TAG, "connection state: CONNECTED to %s", a);
            if (!s_have_host || memcmp(s_host, param->open.bd_addr, 6) != 0) {
                memcpy(s_host, param->open.bd_addr, 6);
                s_have_host = true;
                nvs_store_host(s_host);
                ESP_LOGI(TAG, "stored host in NVS");
            }
            xSemaphoreTake(s_lock, portMAX_DELAY);
            procon_init(&s_state); /* fresh session: timer 0, mode None */
            s_mode_set_us = 0;
            s_quiet_until_us = 0;
            xSemaphoreGive(s_lock);
            s_connected = true;
            esp_bt_gap_set_scan_mode(ESP_BT_NON_CONNECTABLE, ESP_BT_NON_DISCOVERABLE);
        }
        break;
    case ESP_HIDD_CLOSE_EVT:
        if (param->close.status == ESP_HIDD_SUCCESS &&
            param->close.conn_status == ESP_HIDD_CONN_STATE_DISCONNECTING) {
            ESP_LOGI(TAG, "connection state: disconnecting");
        } else {
            ESP_LOGI(TAG, "connection state: DISCONNECTED (status %d)", param->close.status);
            s_connected = false;
            xSemaphoreTake(s_lock, portMAX_DELAY);
            s_state.input_mode = 0;
            xSemaphoreGive(s_lock);
            esp_bt_gap_set_scan_mode(ESP_BT_CONNECTABLE, ESP_BT_GENERAL_DISCOVERABLE);
        }
        break;
    case ESP_HIDD_SEND_REPORT_EVT:
        if (param->send_report.status != ESP_HIDD_SUCCESS) {
            ESP_LOGW(TAG, "send report 0x%02x status %d reason %d", param->send_report.report_id,
                     param->send_report.status, param->send_report.reason);
        }
        break;
    case ESP_HIDD_INTR_DATA_EVT:
        on_output_report(param->intr_data.report_id, param->intr_data.data, param->intr_data.len);
        break;
    case ESP_HIDD_SET_REPORT_EVT:
        ESP_LOGI(TAG, "SET_REPORT type %d id 0x%02x len %u", param->set_report.report_type,
                 param->set_report.report_id, param->set_report.len);
        on_output_report(param->set_report.report_id, param->set_report.data, param->set_report.len);
        break;
    case ESP_HIDD_GET_REPORT_EVT:
        ESP_LOGI(TAG, "GET_REPORT type %d id 0x%02x (ignored)", param->get_report.report_type,
                 param->get_report.report_id);
        break;
    case ESP_HIDD_SET_PROTOCOL_EVT:
        ESP_LOGI(TAG, "SET_PROTOCOL mode %d", param->set_protocol.protocol_mode);
        break;
    case ESP_HIDD_VC_UNPLUG_EVT:
        ESP_LOGI(TAG, "virtual cable unplug (Switch forgot us)");
        s_connected = false;
        esp_bt_gap_set_scan_mode(ESP_BT_CONNECTABLE, ESP_BT_GENERAL_DISCOVERABLE);
        break;
    default:
        break;
    }
}

/* ---------- entry point ---------- */

void app_main(void)
{
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    bool clear_pairing = boot_button_held_2s();
    if (clear_pairing) {
        nvs_erase_host();
        ESP_LOGW(TAG, "stored host erased, pairing cleared");
    }
    s_have_host = nvs_load_host(s_host);

    /* Nintendo OUI + last 3 bytes of the factory MAC => stable per board. The BT MAC is the
     * base MAC with the last byte + 2 (ESP32 convention). */
    uint8_t mac[6];
    ESP_ERROR_CHECK(esp_efuse_mac_get_default(mac));
    uint8_t base[6] = NINTENDO_OUI;
    base[3] = mac[3];
    base[4] = mac[4];
    base[5] = mac[5];
    ESP_ERROR_CHECK(esp_base_mac_addr_set(base));

    s_lock = xSemaphoreCreateMutex();
    procon_init(&s_state);

    ESP_ERROR_CHECK(esp_bt_controller_mem_release(ESP_BT_MODE_BLE));
    esp_bt_controller_config_t bt_cfg = BT_CONTROLLER_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_bt_controller_init(&bt_cfg));
    ESP_ERROR_CHECK(esp_bt_controller_enable(ESP_BT_MODE_CLASSIC_BT));

    esp_bluedroid_config_t bd_cfg = BT_BLUEDROID_INIT_CONFIG_DEFAULT();
    bd_cfg.ssp_en = true;
    ESP_ERROR_CHECK(esp_bluedroid_init_with_cfg(&bd_cfg));
    ESP_ERROR_CHECK(esp_bluedroid_enable());

    if (clear_pairing) {
        remove_all_bonds();
    }

    ESP_ERROR_CHECK(esp_bt_gap_register_callback(gap_cb));
    esp_bt_gap_set_device_name(DEVICE_NAME);

    /* CoD 0x002508: major = peripheral (0x05), minor = gamepad. */
    esp_bt_cod_t cod = {0};
    cod.major = ESP_BT_COD_MAJOR_DEV_PERIPHERAL;
    cod.minor = ESP_BT_COD_MINOR_PERIPHERAL_GAMEPAD;
    esp_bt_gap_set_cod(cod, ESP_BT_SET_COD_MAJOR_MINOR);

    esp_bt_sp_param_t sp_type = ESP_BT_SP_IOCAP_MODE;
    esp_bt_io_cap_t iocap = ESP_BT_IO_CAP_NONE; /* NoInputNoOutput */
    esp_bt_gap_set_security_param(sp_type, &iocap, sizeof(uint8_t));
    esp_bt_pin_code_t pin = {0};
    esp_bt_gap_set_pin(ESP_BT_PIN_TYPE_VARIABLE, 0, pin);

    esp_bt_hid_device_register_callback(hidd_cb);
    ESP_ERROR_CHECK(esp_bt_hid_device_init());

    char a[18];
    fmt_addr(esp_bt_dev_get_address(), a);
    ESP_LOGI(TAG, "Pro Controller emulator up. BT address %s, autopress=%d", a, CONFIG_AUTOPRESS_TEST);

    xTaskCreate(report_task, "report_task", 4096, NULL, configMAX_PRIORITIES - 3, NULL);
}
