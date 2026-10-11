idf_component_register(SRCS "main.c" "my_platform.c"
                       INCLUDE_DIRS "."
                       REQUIRES nvs_flash bluepad32 btstack bridge_proto input_modes driver esp_timer)
