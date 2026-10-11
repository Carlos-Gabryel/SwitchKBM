#include "bridge_proto.h"

#include <string.h>

enum { S_SOF0, S_SOF1, S_TYPE, S_LEN, S_PAYLOAD, S_CRC };

uint8_t bridge_crc8(const uint8_t *data, size_t len) {
    uint8_t crc = 0x00;
    for (size_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (int b = 0; b < 8; b++) {
            crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0x07) : (uint8_t)(crc << 1);
        }
    }
    return crc;
}

size_t bridge_encode(uint8_t type, const void *payload, uint8_t len, uint8_t *out, size_t out_cap) {
    if (out == NULL || len > BRIDGE_MAX_PAYLOAD || (len > 0 && payload == NULL)) {
        return 0;
    }
    size_t total = (size_t)len + BRIDGE_FRAME_OVERHEAD;
    if (out_cap < total) {
        return 0;
    }
    out[0] = BRIDGE_SOF0;
    out[1] = BRIDGE_SOF1;
    out[2] = type;
    out[3] = len;
    if (len > 0) {
        memcpy(&out[4], payload, len);
    }
    out[4 + len] = bridge_crc8(&out[2], (size_t)len + 2);
    return total;
}

void bridge_parser_init(bridge_parser_t *p) {
    memset(p, 0, sizeof(*p));
    p->state = S_SOF0;
}

bool bridge_parser_feed(bridge_parser_t *p, uint8_t byte) {
    switch (p->state) {
    case S_SOF0:
        if (byte == BRIDGE_SOF0) {
            p->state = S_SOF1;
        }
        break;
    case S_SOF1:
        if (byte == BRIDGE_SOF1) {
            p->state = S_TYPE;
        } else if (byte != BRIDGE_SOF0) { // 0xAA 0xAA 0x55: continua no segundo 0xAA
            p->state = S_SOF0;
        }
        break;
    case S_TYPE:
        p->type = byte;
        p->crc = bridge_crc8(&byte, 1);
        p->state = S_LEN;
        break;
    case S_LEN:
        if (byte > BRIDGE_MAX_PAYLOAD) {
            p->len_errors++;
            p->state = (byte == BRIDGE_SOF0) ? S_SOF1 : S_SOF0;
            break;
        }
        p->len = byte;
        p->idx = 0;
        // crc incremental: recalcula sobre type+len
        {
            uint8_t tl[2] = {p->type, byte};
            p->crc = bridge_crc8(tl, 2);
        }
        p->state = (byte == 0) ? S_CRC : S_PAYLOAD;
        break;
    case S_PAYLOAD:
        p->payload[p->idx++] = byte;
        if (p->idx >= p->len) {
            p->state = S_CRC;
        }
        break;
    case S_CRC: {
        p->state = S_SOF0;
        uint8_t buf[2 + BRIDGE_MAX_PAYLOAD];
        buf[0] = p->type;
        buf[1] = p->len;
        memcpy(&buf[2], p->payload, p->len);
        if (bridge_crc8(buf, (size_t)p->len + 2) == byte) {
            p->frames_ok++;
            return true;
        }
        p->crc_errors++;
        if (byte == BRIDGE_SOF0) { // o byte pode ser o inicio do proximo frame
            p->state = S_SOF1;
        }
        break;
    }
    default:
        p->state = S_SOF0;
        break;
    }
    return false;
}
