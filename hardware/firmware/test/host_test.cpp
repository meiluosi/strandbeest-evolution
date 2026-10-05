// Host-side tests of rigcore. Build and run: make -C hardware/firmware test
#include <cstdio>
#include <cstring>
#include "../lib/rigcore/rigcore.h"

static int failures = 0;
#define CHECK(cond) do { if (!(cond)) { std::printf("FAIL %s:%d  %s\n", __FILE__, __LINE__, #cond); ++failures; } } while (0)
#define NEAR(a, b, tol) CHECK(std::fabs((a) - (b)) <= (tol))

static void test_speed_estimator() {
  // 12 counts/rev motor, 100:1 gearbox, crank at 2 rad/s => 2/(2pi)*100*12 counts/s
  rig::SpeedEstimator est(12, 100);
  const float counts_per_s = 2.0f / rig::kTwoPi * 100 * 12;
  for (int i = 0; i <= 100; ++i) { float t = i * 0.01f; est.update(t, static_cast<int32_t>(counts_per_s * t)); }
  NEAR(est.speed(), 2.0f, 0.05f);
  rig::SpeedEstimator rev(12, 100);
  for (int i = 0; i <= 100; ++i) { float t = i * 0.01f; rev.update(t, -static_cast<int32_t>(counts_per_s * t)); }
  NEAR(rev.speed(), -2.0f, 0.05f);  // sign follows the count direction
}

static void test_pi_converges_on_a_first_order_plant() {
  rig::PiController pi(40.0f, 120.0f, 0.0f, 255.0f);
  float speed = 0, dt = 0.01f;
  for (int i = 0; i < 600; ++i) {
    float pwm = pi.step(2.0f, speed, dt);
    speed += (pwm * 0.02f - speed) * dt / 0.15f;  // plant: 0.02 rad/s per pwm count, time constant 0.15 s
  }
  NEAR(speed, 2.0f, 0.05f);
}

static void test_pi_is_clamped_and_does_not_wind_up() {
  rig::PiController pi(10.0f, 50.0f, 0.0f, 255.0f);
  for (int i = 0; i < 1000; ++i) CHECK(pi.step(1000.0f, 0.0f, 0.01f) <= 255.0f);  // unreachable target: saturated for a long time
  // when the target becomes reachable the output must come down promptly (integrator did not wind up)
  float out = 255;
  for (int i = 0; i < 50; ++i) out = pi.step(1.0f, 5.0f, 0.01f);
  CHECK(out < 255.0f);
  CHECK(out >= 0.0f);
}

static void test_commands() {
  CHECK(rig::parse_command("START").cmd == rig::Cmd::Start);
  CHECK(rig::parse_command("  STOP").cmd == rig::Cmd::Stop);
  CHECK(rig::parse_command("ZERO").cmd == rig::Cmd::Zero);
  auto s = rig::parse_command("S 2.5");
  CHECK(s.cmd == rig::Cmd::SetSpeed); NEAR(s.value, 2.5f, 1e-6f);
  CHECK(rig::parse_command("S abc").cmd == rig::Cmd::Bad);
  CHECK(rig::parse_command("S -1").cmd == rig::Cmd::Bad);
  CHECK(rig::parse_command("S 500").cmd == rig::Cmd::Bad);  // refuse absurd speeds
  CHECK(rig::parse_command("").cmd == rig::Cmd::None);
  CHECK(rig::parse_command("garbage").cmd == rig::Cmd::Bad);
}

static void test_csv_format_matches_the_host_parser() {
  char buf[96];
  rig::Sample s{1234, -56, true, 321.5f, false, 0, false, 0, 128};
  rig::format_sample(buf, sizeof buf, s);
  CHECK(std::strcmp(buf, "1234,-56,321.5,,,128") == 0);
  rig::Sample full{4000000000u, 7, true, 0.0f, true, -12345, true, 99u, 0};
  rig::format_sample(buf, sizeof buf, full);
  CHECK(std::strcmp(buf, "4000000000,7,0.0,-12345,99,0") == 0);
  CHECK(std::strcmp(rig::kCsvHeader, "t_ms,enc,current_mA,load_raw,wind_pulses,pwm") == 0);
}

int main() {
  test_speed_estimator(); test_pi_converges_on_a_first_order_plant(); test_pi_is_clamped_and_does_not_wind_up();
  test_commands(); test_csv_format_matches_the_host_parser();
  if (failures) { std::printf("%d failure(s)\n", failures); return 1; }
  std::printf("all rigcore tests passed\n");
  return 0;
}
