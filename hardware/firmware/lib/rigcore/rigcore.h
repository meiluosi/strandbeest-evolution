// rigcore: the hardware-independent logic of the test rig. Pure C++ with no Arduino headers, so it is unit-tested on the host
// (see ../../test/host_test.cpp) and used unchanged by the firmware.
#pragma once
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace rig {

constexpr float kTwoPi = 6.28318530718f;

// Converts a motor-shaft quadrature count into crank speed (rad/s), smoothed over a short window.
class SpeedEstimator {
 public:
  SpeedEstimator(float counts_per_motor_rev, float gear_ratio, float window_s = 0.1f)
      : rad_per_count_(kTwoPi / counts_per_motor_rev / gear_ratio), window_(window_s) {}

  // Call at every control tick with the monotonic time in seconds and the current signed count.
  void update(float t_s, int32_t count) {
    if (!init_) { t0_ = t_s; c0_ = count; speed_ = 0; init_ = true; return; }
    if (t_s - t0_ >= window_) {
      speed_ = (count - c0_) * rad_per_count_ / (t_s - t0_);
      t0_ = t_s; c0_ = count;
    }
  }
  float speed() const { return speed_; }  // crank rad/s, sign follows the count direction

 private:
  float rad_per_count_, window_, t0_ = 0, speed_ = 0;
  int32_t c0_ = 0;
  bool init_ = false;
};

// PI speed controller with output clamping and anti-windup (integrator frozen while the output is saturated in the error's direction).
class PiController {
 public:
  PiController(float kp, float ki, float out_min, float out_max) : kp_(kp), ki_(ki), lo_(out_min), hi_(out_max) {}
  float step(float target, float measured, float dt) {
    float err = target - measured;
    float unclamped = kp_ * err + integral_ + ki_ * err * dt;
    float out = unclamped < lo_ ? lo_ : (unclamped > hi_ ? hi_ : unclamped);
    bool saturated_against = (unclamped > hi_ && err > 0) || (unclamped < lo_ && err < 0);
    if (!saturated_against) integral_ += ki_ * err * dt;
    return out;
  }
  void reset() { integral_ = 0; }

 private:
  float kp_, ki_, lo_, hi_, integral_ = 0;
};

// Serial command parser: "S <rad/s>", "START", "STOP", "ZERO". One command per line.
enum class Cmd { None, SetSpeed, Start, Stop, Zero, Bad };
struct Parsed { Cmd cmd = Cmd::None; float value = 0; };

inline Parsed parse_command(const char* line) {
  while (*line == ' ') ++line;
  if (!*line) return {};
  if (std::strncmp(line, "START", 5) == 0) return {Cmd::Start, 0};
  if (std::strncmp(line, "STOP", 4) == 0) return {Cmd::Stop, 0};
  if (std::strncmp(line, "ZERO", 4) == 0) return {Cmd::Zero, 0};
  if (line[0] == 'S' && line[1] == ' ') {
    char* end = nullptr;
    float v = std::strtof(line + 2, &end);
    if (end != line + 2 && std::isfinite(v) && v >= 0 && v < 50) return {Cmd::SetSpeed, v};
  }
  return {Cmd::Bad, 0};
}

// One CSV sample line, matching the columns the host tools expect:
//   t_ms,enc,current_mA,load_raw,wind_pulses,pwm
// A missing channel is printed as an empty field.
struct Sample {
  uint32_t t_ms; int32_t enc; bool has_current; float current_ma; bool has_load; int32_t load_raw; bool has_wind; uint32_t wind_pulses; int pwm;
};

inline int format_sample(char* buf, size_t n, const Sample& s) {
  char cur[24] = "", load[24] = "", wind[24] = "";
  if (s.has_current) std::snprintf(cur, sizeof cur, "%.1f", s.current_ma);
  if (s.has_load) std::snprintf(load, sizeof load, "%ld", static_cast<long>(s.load_raw));
  if (s.has_wind) std::snprintf(wind, sizeof wind, "%lu", static_cast<unsigned long>(s.wind_pulses));
  return std::snprintf(buf, n, "%lu,%ld,%s,%s,%s,%d", static_cast<unsigned long>(s.t_ms), static_cast<long>(s.enc), cur, load, wind, s.pwm);
}

constexpr const char* kCsvHeader = "t_ms,enc,current_mA,load_raw,wind_pulses,pwm";

}  // namespace rig
