#include "esp_err.h"
#include "esp_log.h"
#include "nvs_flash.h"

#include "controller_state.h"
#include "btstack_hid.h"
#include "btstack_run_loop.h"

static const char *TAG = "MAIN";

static void init_nvs(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES ||
        err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);
}

void app_main(void)
{
    ESP_LOGI(TAG, "=== Switch controller experimental ===");

    init_nvs();
    controller_state_init(controller_state_get());

    esp_err_t err = btstack_hid_init();
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "No se pudo iniciar el transporte Bluetooth: %s",
                 esp_err_to_name(err));
        return;
    }
    btstack_run_loop_execute();
    ESP_LOGI(TAG, "Bluetooth Classic HID iniciado");
}
