idf_component_register(
    SRCS
        "main.c"
        "controller_state.c"
        "input_report.c"
        "spi_flash.c"
        "switch_proto.c"
        "nfc_mcu.c"
        "hid_transport.c"
        "btstack_hid.c"
        "bridge_rx.c"
    INCLUDE_DIRS
        "."
        "include"
    PRIV_REQUIRES
        bt
        btstack
        bridge_proto
        input_modes
        esp_driver_uart
        esp_timer
        nvs_flash
)

target_compile_options(${COMPONENT_LIB} PRIVATE -Wno-error=format)
target_include_directories(${COMPONENT_LIB} PRIVATE
    "../components/btstack/src"
    "../components/btstack/src/classic"
    "../components/btstack/platform/freertos"
    "../components/btstack/port/include"
)
