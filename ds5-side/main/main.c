// ds5-side: DualSense (Bluepad32) -> UART2 -> switch-side
#include <btstack_port_esp32.h>
#include <btstack_run_loop.h>
#include <uni.h>

#include "sdkconfig.h"

#ifndef CONFIG_BLUEPAD32_PLATFORM_CUSTOM
#error "Must use BLUEPAD32_PLATFORM_CUSTOM"
#endif

struct uni_platform *get_my_platform(void);

int app_main(void) {
    // Sem btstack_stdio_init(): ele assumiria o stdin da UART0, que aqui recebe frames do PC
    // (lidos por uart_read_bytes na pc_rx_task em my_platform.c).

    btstack_init();
    uni_platform_set_custom(get_my_platform());
    uni_init(0, NULL);

    // Roda o loop do BTstack nesta task (a "BT thread" do Bluepad32).
    btstack_run_loop_execute();
    return 0;
}
