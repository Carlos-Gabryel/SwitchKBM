idf_component_register(SRCS "main.c" "my_platform.c"
                       INCLUDE_DIRS "."
                       REQUIRES bluepad32 btstack bridge_proto driver esp_timer)
