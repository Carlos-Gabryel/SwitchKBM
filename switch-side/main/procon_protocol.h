#pragma once
/*
 * Pro Controller protocol: report building and subcommand replies.
 * Pure functions - no Bluetooth calls - so this can be unit-tested on the host.
 * Ported from joycontrol (protocol.py, report.py, controller_state.py, memory.py).
 *
 * Buffer convention: the 0xA1/0xA2 HID transaction header is NOT included (the BT stack adds it).
 * Output report buffer : [0]=report id, [1]=timer, [2..9]=rumble, [10]=subcommand id, [11..]=args.
 * Input report payload : bytes after the report id, sent together with that id.
 */
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

#define PROCON_OUT_ID_SUBCMD 0x01
#define PROCON_OUT_ID_RUMBLE 0x10
#define PROCON_OUT_ID_MCU    0x11

#define PROCON_IN_ID_SUBCMD_REPLY 0x21
#define PROCON_IN_ID_FULL         0x30

#define PROCON_PAYLOAD_0x21_LEN 49 /* timer, misc, btn[3], sticks[6], vib, ack, subid, data[35] */
#define PROCON_PAYLOAD_0x30_LEN 48 /* timer, misc, btn[3], sticks[6], vib, imu[36] */

/* Subcommand ids (report.py: SubCommand, plus 0x01 / 0x38 from dekuNukem). */
enum {
    SUBCMD_BT_PAIRING       = 0x01,
    SUBCMD_DEVICE_INFO      = 0x02,
    SUBCMD_INPUT_MODE       = 0x03,
    SUBCMD_TRIGGER_ELAPSED  = 0x04,
    SUBCMD_SHIPMENT         = 0x08,
    SUBCMD_SPI_READ         = 0x10,
    SUBCMD_MCU_CONFIG       = 0x21,
    SUBCMD_MCU_STATE        = 0x22,
    SUBCMD_PLAYER_LIGHTS    = 0x30,
    SUBCMD_HOME_LIGHT       = 0x38,
    SUBCMD_ENABLE_IMU       = 0x40,
    SUBCMD_ENABLE_VIBRATION = 0x48,
};

/* Button bytes, bit layout from controller_state.py (Pro Controller). */
typedef struct {
    uint8_t b1; /* bit0 Y, 1 X, 2 B, 3 A, 6 R, 7 ZR */
    uint8_t b2; /* bit0 Minus, 1 Plus, 2 R-stick, 3 L-stick, 4 Home, 5 Capture */
    uint8_t b3; /* bit0 Down, 1 Up, 2 Right, 3 Left, 6 L, 7 ZL */
} procon_buttons_t;

#define PROCON_BTN1_A (1u << 3)
#define PROCON_BTN1_R (1u << 6)
#define PROCON_BTN3_L (1u << 6)

typedef struct {
    uint8_t timer;      /* shared by every input report sent, wraps at 0x100 */
    uint8_t input_mode; /* 0 = "just answer subcommands" (joycontrol: None), else 0x30 */
    procon_buttons_t buttons;
} procon_state_t;

typedef struct {
    uint8_t id;
    uint8_t len; /* payload length, id excluded */
    uint8_t payload[PROCON_PAYLOAD_0x21_LEN];
} procon_report_t;

/* Result of handling one output report. */
typedef struct {
    bool is_subcmd;      /* output report 0x01 */
    uint8_t subcmd;      /* valid when is_subcmd */
    const uint8_t *args; /* subcommand args (points into the input buffer) */
    size_t args_len;
    bool has_reply;      /* reply filled */
    procon_report_t reply;
    bool mode_changed;   /* input mode was (re)set by this report */
} procon_result_t;

void procon_init(procon_state_t *st);

/* Parse an output report (buffer layout above). `bd_addr` is our 6-byte BT address (big-endian order). */
void procon_handle_output(procon_state_t *st, const uint8_t *buf, size_t len,
                          const uint8_t bd_addr[6], procon_result_t *res);

/* Build the periodic 0x30 report: neutral sticks, zeroed IMU. Advances the timer. */
void procon_build_full_report(procon_state_t *st, procon_report_t *rep);

/* Read `size` (<=0x1D) bytes of emulated SPI flash at `offset` into `out`. */
void procon_spi_read(uint32_t offset, uint8_t size, uint8_t *out);
