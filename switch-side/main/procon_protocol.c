#include "procon_protocol.h"
#include "procon_spi_data.h"
#include <string.h>

/* Payload offsets (input report id excluded) = joycontrol's data[] index minus 1. */
#define P_TIMER 0
#define P_MISC  1
#define P_BTN   2
#define P_STICK 5
#define P_VIB   11
#define P_ACK   12 /* 0x21 only */
#define P_SUBID 13 /* 0x21 only */
#define P_DATA  14 /* 0x21 only, 35 bytes */
#define P_IMU   12 /* 0x30 only, 36 bytes */

/* report.py set_misc(): battery level + connection info. Kept identical. */
#define MISC_BATTERY_CONN 0x8E
/* report.py set_vibrator_input(): only set on 0x30 reports; 0x21 replies keep 0x00. */
#define VIB_0x30 0x80

#define STICK_CENTER 0x800

void procon_init(procon_state_t *st)
{
    memset(st, 0, sizeof(*st));
}

/* Pack two 12-bit values into 3 bytes (dekuNukem bluetooth_hid_notes.md: stick data). */
static void pack_stick(uint8_t *out, uint16_t h, uint16_t v)
{
    out[0] = h & 0xFF;
    out[1] = ((h >> 8) & 0x0F) | ((v & 0x0F) << 4);
    out[2] = (v >> 4) & 0xFF;
}

/* Common header of both report kinds. Consumes one timer value. */
static void fill_header(procon_state_t *st, procon_report_t *rep)
{
    memset(rep->payload, 0, sizeof(rep->payload));
    rep->payload[P_TIMER] = st->timer++;
    rep->payload[P_MISC] = MISC_BATTERY_CONN;
    rep->payload[P_BTN + 0] = st->buttons.b1;
    rep->payload[P_BTN + 1] = st->buttons.b2;
    rep->payload[P_BTN + 2] = st->buttons.b3;
    pack_stick(&rep->payload[P_STICK], STICK_CENTER, STICK_CENTER);
    pack_stick(&rep->payload[P_STICK + 3], STICK_CENTER, STICK_CENTER);
}

void procon_build_full_report(procon_state_t *st, procon_report_t *rep)
{
    rep->id = PROCON_IN_ID_FULL;
    rep->len = PROCON_PAYLOAD_0x30_LEN;
    fill_header(st, rep);
    rep->payload[P_VIB] = VIB_0x30;
    /* IMU: 3 samples x 12 bytes, left zeroed (real data comes in a later phase). */
    memset(&rep->payload[P_IMU], 0, 36);
}

/* Start a 0x21 reply: ack byte + echoed subcommand id. */
static void begin_reply(procon_state_t *st, procon_report_t *rep, uint8_t ack, uint8_t subcmd)
{
    rep->id = PROCON_IN_ID_SUBCMD_REPLY;
    rep->len = PROCON_PAYLOAD_0x21_LEN;
    fill_header(st, rep);
    rep->payload[P_ACK] = ack;
    rep->payload[P_SUBID] = subcmd;
}

void procon_spi_read(uint32_t offset, uint8_t size, uint8_t *out)
{
    memset(out, 0xFF, size); /* unlisted areas = blank flash */
    for (size_t r = 0; r < PROCON_SPI_REGION_COUNT; r++) {
        const procon_spi_region_t *reg = &procon_spi_regions[r];
        for (uint32_t i = 0; i < size; i++) {
            uint32_t a = offset + i;
            if (a >= reg->addr && a < reg->addr + reg->len) {
                out[i] = reg->data[a - reg->addr];
            }
        }
    }
}

static void reply_subcommand(procon_state_t *st, uint8_t sub, const uint8_t *a, size_t alen,
                             const uint8_t bd_addr[6], procon_report_t *rep)
{
    switch (sub) {
    case SUBCMD_DEVICE_INFO: {
        /* report.py sub_0x02_device_info: ack 0x82, fw 04.00, type, 0x02, MAC, 0x01, 0x01. */
        begin_reply(st, rep, 0x82, sub);
        uint8_t *d = &rep->payload[P_DATA];
        d[0] = 0x04;
        d[1] = 0x00;
        d[2] = 0x03; /* 3 = Pro Controller */
        d[3] = 0x02;
        memcpy(&d[4], bd_addr, 6);
        d[10] = 0x01;
        d[11] = 0x01; /* "use SPI colors" */
        break;
    }
    case SUBCMD_SPI_READ: {
        /* ack 0x90, echo 4-byte LE offset + size, then data. Max 0x1D bytes (report.py). */
        begin_reply(st, rep, 0x90, sub);
        uint32_t off = 0;
        uint8_t size = 0;
        if (alen >= 5) {
            off = a[0] | (a[1] << 8) | (a[2] << 16) | ((uint32_t)a[3] << 24);
            size = a[4];
        }
        if (size > 0x1D) {
            size = 0x1D;
        }
        uint8_t *d = &rep->payload[P_DATA];
        d[0] = off & 0xFF;
        d[1] = (off >> 8) & 0xFF;
        d[2] = (off >> 16) & 0xFF;
        d[3] = (off >> 24) & 0xFF;
        d[4] = size;
        procon_spi_read(off, size, &d[5]);
        break;
    }
    case SUBCMD_TRIGGER_ELAPSED: {
        /* protocol.py hack: ack 0x83; assume pairing, report L and R held 3000 ms so the Switch
         * assigns a player number. Values are in 10 ms units, little-endian: 300 = 0x012C. */
        begin_reply(st, rep, 0x83, sub);
        uint8_t *d = &rep->payload[P_DATA];
        d[0] = 0x2C; d[1] = 0x01; /* L */
        d[2] = 0x2C; d[3] = 0x01; /* R */
        break;
    }
    case SUBCMD_MCU_CONFIG: {
        /* protocol.py: ack 0xA0 + fixed 34-byte MCU status blob (no real NFC/IR). */
        static const uint8_t blob[34] = {1, 0, 255, 0, 8, 0, 27, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0,
                                         0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 200};
        begin_reply(st, rep, 0xA0, sub);
        memcpy(&rep->payload[P_DATA], blob, sizeof(blob));
        break;
    }
    default:
        /* 0x03, 0x08, 0x22, 0x30, 0x40, 0x48: ack 0x80 + id, as joycontrol.
         * 0x01, 0x38 and unknown ids: joycontrol ignores them; we send the generic ACK 0x80. */
        begin_reply(st, rep, 0x80, sub);
        break;
    }
}

void procon_handle_output(procon_state_t *st, const uint8_t *buf, size_t len,
                          const uint8_t bd_addr[6], procon_result_t *res)
{
    memset(res, 0, sizeof(*res));
    if (len < 1 || buf[0] != PROCON_OUT_ID_SUBCMD) {
        return; /* 0x10 rumble only / 0x11 MCU: nothing to answer (joycontrol: TODO) */
    }
    if (len < 11) {
        return; /* no subcommand byte */
    }
    res->is_subcmd = true;
    res->subcmd = buf[10];
    res->args = &buf[11];
    res->args_len = len - 11;

    if (res->subcmd == SUBCMD_INPUT_MODE && res->args_len >= 1) {
        /* protocol.py: only 0x30/0x31 start streaming; 0x31 (NFC/IR) is treated as 0x30 here.
         * Other modes: joycontrol sends no ACK; we still ACK (deviation) but do not stream. */
        uint8_t mode = res->args[0];
        if (mode == 0x30 || mode == 0x31) {
            st->input_mode = 0x30;
            res->mode_changed = true;
        }
    }
    reply_subcommand(st, res->subcmd, res->args, res->args_len, bd_addr, &res->reply);
    res->has_reply = true;
}
