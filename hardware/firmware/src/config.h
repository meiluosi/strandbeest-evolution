// Edit these for your build, then re-flash. Pins are for a generic ESP32 dev board; any free GPIO with interrupt support works.
#pragma once

// --- encoder on the MOTOR shaft (quadrature) ---
#define PIN_ENC_A 32
#define PIN_ENC_B 33
// Counts per motor-shaft revolution as the ISR below counts them (4x decoding: 4 x pulses-per-rev of one channel).
#define COUNTS_PER_MOTOR_REV 48.0f
// Motor revolutions per crank revolution (gearbox ratio).
#define GEAR_RATIO 100.0f
// Flip to -1 if positive counts turn the crank backwards.
#define ENC_SIGN 1

// --- motor driver (e.g. DRV8833 / TB6612): PWM on one input, direction on the other ---
#define PIN_MOTOR_PWM 25
#define PIN_MOTOR_DIR 26
#define PWM_FREQ_HZ 20000
#define PWM_MAX 255

// --- optional sensors (comment out to disable) ---
#define USE_INA219            // current sensor on I2C (SDA 21, SCL 22)
// #define USE_HX711          // load cell amplifier
#define PIN_HX711_DT 18
#define PIN_HX711_SCK 19
// #define USE_ANEMOMETER     // reed/hall cup anemometer, one pulse per interrupt
#define PIN_ANEMOMETER 27

// --- control and logging ---
#define SAMPLE_HZ 100
#define PI_KP 30.0f           // PWM counts per rad/s of error: tune on your motor
#define PI_KI 90.0f
// Safety: the motor is cut if the crank speed exceeds this (rad/s) or if no command or sample tick has been seen for a while.
#define MAX_CRANK_RAD_S 8.0f
