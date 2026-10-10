#pragma once
/*
 * SPI flash regions served to the Switch (subcommand 0x10).
 *
 * joycontrol serves reads from a 512 KiB flash dump; with no dump it is all 0xFF
 * except the factory stick calibration (memory.py: FlashMemory). We do the same:
 * everything not listed here reads as 0xFF. Regions marked "extra" are NOT in
 * joycontrol's blank image; values come from dekuNukem's spi_flash_notes.md
 * (recalled from memory, not re-fetched) and approximate a real Pro Controller.
 */
#include <stdint.h>
#include <stddef.h>

typedef struct {
    uint32_t addr;
    uint8_t len;
    const uint8_t *data;
} procon_spi_region_t;

/* 0x6000: serial number, 16 bytes. 0xFF = "no serial" (joycontrol blank). */
static const uint8_t spi_serial[16] = {
    0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
};

/* 0x6020: factory 6-axis calibration, 24 bytes (extra). acc origin(3xs16), acc sens(3xs16 =0x4000),
 * gyro origin(3xs16), gyro sens(3xs16 =0x343B). */
static const uint8_t spi_imu_calib[24] = {
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x40, 0x00, 0x40, 0x00, 0x40,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x3B, 0x34, 0x3B, 0x34, 0x3B, 0x34,
};

/* 0x603D: factory stick calibration, 18 bytes (joycontrol memory.py default).
 * Each stick: 3 x 12-bit pairs packed in 3 bytes (left: above-center, center, below-center;
 * right: center, below-center, above-center). */
static const uint8_t spi_stick_calib[18] = {
    0x00, 0x07, 0x70, 0x00, 0x08, 0x80, 0x00, 0x07, 0x70, /* left  */
    0x00, 0x08, 0x80, 0x00, 0x07, 0x70, 0x00, 0x07, 0x70, /* right */
};

/* 0x6050: body/buttons/left grip/right grip colours, 12 bytes (extra). Dark grey body. */
static const uint8_t spi_colors[12] = {
    0x32, 0x32, 0x32, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
};

/* 0x6080: 6-axis horizontal offsets, 6 bytes (extra). */
static const uint8_t spi_sensor_params[6] = {0x50, 0xFD, 0x00, 0x00, 0xC6, 0x0F};

/* 0x6086 / 0x6098: stick device parameters 1 and 2, 18 bytes each (extra). */
static const uint8_t spi_stick_params[18] = {
    0x0F, 0x30, 0x61, 0x96, 0x30, 0xF3, 0xD4, 0x14, 0x54,
    0x41, 0x15, 0x54, 0xC7, 0x79, 0x9C, 0x33, 0x36, 0x63,
};

/* 0x8010 user stick calibration (22 bytes) and 0x8026 user IMU calibration (26 bytes):
 * "not present" = magic bytes absent = 0xFF (also what joycontrol's blank flash returns). */
static const uint8_t spi_user_absent[26] = {
    0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
    0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
};

static const procon_spi_region_t procon_spi_regions[] = {
    {0x6000, sizeof(spi_serial), spi_serial},
    {0x6020, sizeof(spi_imu_calib), spi_imu_calib},
    {0x603D, sizeof(spi_stick_calib), spi_stick_calib},
    {0x6050, sizeof(spi_colors), spi_colors},
    {0x6080, sizeof(spi_sensor_params), spi_sensor_params},
    {0x6086, sizeof(spi_stick_params), spi_stick_params},
    {0x6098, sizeof(spi_stick_params), spi_stick_params},
    {0x8010, 22, spi_user_absent},
    {0x8026, 26, spi_user_absent},
};
#define PROCON_SPI_REGION_COUNT (sizeof(procon_spi_regions) / sizeof(procon_spi_regions[0]))
