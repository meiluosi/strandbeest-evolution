// Strandbeest test rig firmware. Prints one CSV line per sample (see rigcore.h) and holds the crank at a commanded speed.
// Serial commands (115200 baud, newline-terminated): ZERO, S <rad/s>, START, STOP.
// NOT compiled or run on hardware by the authors yet; the logic lives in lib/rigcore, which is unit-tested on the host.
#include <Arduino.h>
#include "config.h"
#include "rigcore.h"

#ifdef USE_INA219
#include <Adafruit_INA219.h>
Adafruit_INA219 ina;
#endif
#ifdef USE_HX711
#include <HX711.h>
HX711 scale;
#endif

static volatile int32_t g_count = 0;
static volatile uint32_t g_wind_pulses = 0;
static volatile uint8_t g_last_ab = 0;

// Standard quadrature decoding by table lookup on the previous and current (A,B) state.
static const int8_t kQuadTable[16] = {0, +1, -1, 0, -1, 0, 0, +1, +1, 0, 0, -1, 0, -1, +1, 0};
void IRAM_ATTR encoder_isr() {
  uint8_t ab = (digitalRead(PIN_ENC_A) << 1) | digitalRead(PIN_ENC_B);
  g_count += kQuadTable[(g_last_ab << 2) | ab];
  g_last_ab = ab;
}
void IRAM_ATTR wind_isr() { g_wind_pulses++; }

static rig::SpeedEstimator speed_est(COUNTS_PER_MOTOR_REV, GEAR_RATIO);
static rig::PiController pi(PI_KP, PI_KI, 0.0f, PWM_MAX);
static float g_target = 0.0f;  // crank rad/s
static bool g_running = false;
static int g_pwm = 0;
static uint32_t g_t0_ms = 0;
static char g_line[48];
static size_t g_len = 0;

static void drive(int pwm) {
  g_pwm = pwm;
  digitalWrite(PIN_MOTOR_DIR, LOW);
  ledcWrite(0, pwm);
}

static void handle(const rig::Parsed& p) {
  switch (p.cmd) {
    case rig::Cmd::SetSpeed: g_target = p.value; break;
    case rig::Cmd::Start: pi.reset(); g_t0_ms = millis(); g_running = true; break;
    case rig::Cmd::Stop: g_running = false; drive(0); break;
    case rig::Cmd::Zero: noInterrupts(); g_count = 0; interrupts(); g_wind_pulses = 0; break;
    case rig::Cmd::Bad: Serial.println("# error: unknown or out-of-range command"); break;
    case rig::Cmd::None: break;
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_ENC_A, INPUT_PULLUP);
  pinMode(PIN_ENC_B, INPUT_PULLUP);
  g_last_ab = (digitalRead(PIN_ENC_A) << 1) | digitalRead(PIN_ENC_B);
  attachInterrupt(digitalPinToInterrupt(PIN_ENC_A), encoder_isr, CHANGE);
  attachInterrupt(digitalPinToInterrupt(PIN_ENC_B), encoder_isr, CHANGE);
  pinMode(PIN_MOTOR_DIR, OUTPUT);
  ledcSetup(0, PWM_FREQ_HZ, 8);
  ledcAttachPin(PIN_MOTOR_PWM, 0);
  drive(0);
#ifdef USE_INA219
  ina.begin();
#endif
#ifdef USE_HX711
  scale.begin(PIN_HX711_DT, PIN_HX711_SCK);
#endif
#ifdef USE_ANEMOMETER
  pinMode(PIN_ANEMOMETER, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PIN_ANEMOMETER), wind_isr, FALLING);
#endif
  Serial.printf("# fw=%s cpr=%.1f gear=%.1f sample_hz=%d\n", STRANDBEEST_FW_VERSION, COUNTS_PER_MOTOR_REV, GEAR_RATIO, SAMPLE_HZ);
  Serial.println(rig::kCsvHeader);
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      g_line[g_len] = 0;
      if (g_len) handle(rig::parse_command(g_line));
      g_len = 0;
    } else if (g_len < sizeof g_line - 1) {
      g_line[g_len++] = c;
    }
  }

  static uint32_t next_us = 0;
  uint32_t now_us = micros();
  if ((int32_t)(now_us - next_us) < 0) return;
  next_us = now_us + 1000000UL / SAMPLE_HZ;

  noInterrupts();
  int32_t count = g_count;
  interrupts();
  float t_s = millis() / 1000.0f;
  speed_est.update(t_s, count);
  float crank_speed = ENC_SIGN * speed_est.speed();

  // Safety: cut the motor on overspeed.
  if (fabsf(crank_speed) > MAX_CRANK_RAD_S) { g_running = false; drive(0); Serial.println("# error: overspeed, motor cut"); }

  if (g_running) {
    float u = pi.step(g_target, crank_speed, 1.0f / SAMPLE_HZ);
    drive((int)u);
  }

  rig::Sample s{};
  s.t_ms = g_running ? millis() - g_t0_ms : millis();
  s.enc = ENC_SIGN * count;
#ifdef USE_INA219
  s.has_current = true;
  s.current_ma = ina.getCurrent_mA();
#endif
#ifdef USE_HX711
  if (scale.is_ready()) { s.has_load = true; s.load_raw = scale.read(); }
#endif
#ifdef USE_ANEMOMETER
  s.has_wind = true;
  s.wind_pulses = g_wind_pulses;
#endif
  s.pwm = g_pwm;
  char buf[96];
  rig::format_sample(buf, sizeof buf, s);
  Serial.println(buf);
}
