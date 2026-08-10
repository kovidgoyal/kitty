#language slang 2026

// Northern Lights — Volumetric Aurora Borealis - by Sami Farin
//
// Some ideas taken from a shader by gerardo-lcdf (MIT license):
// https://godotshaders.com/shader/volumetric-aurora-borealis-with-polar-reflection/
// The star field has been redesigned.
//
// Some important floats for tuning:
//   AURORA_INTENSITY                             - brightness of the aurora effect
//   ACCUMULATION_DECAY / MOUSE_PERSIST_INTENSITY - persistent trail on mouse click settings
//   STAR_BRIGHTNESS                              - set to 0.0f to disable star field
//   STAR_FIELD_ROTATIONS_SPEED                   - star field rotation speed
//   RESEED_INTERVAL                              - every RESEED_INTERVAL seconds the aurora is randomized again
//   DEBUG_MOUSE_OVERLAY                          - 1.0f enables debugging for mouse press location/effect

import kitty_custom_shader_types;

static const float PI = 3.14159265359f;
static const float INITIAL_RANDOM_SEED = 0.12138f;

// === TERMINAL BLENDING CONTROLS ===
static const float BLACK_BLEND_THRESHOLD = 0.15f;
static const float EFFECT_INTENSITY = 0.25f;
static const float TIME_SCALE = 0.25f;
static const float EFFECT_FLOOR = 0.015f;
static const float EFFECT_CEILING = 0.12f;

// === AURORA TUNING KNOBS ===
static const float AURORA_INTENSITY = 0.2f;
static const float AURORA_ALTITUDE = 0.6f;
static const float AURORA_SCALE = 1.0f;
static const float WAVE_SPEED = 0.55f;
static const float MARCH_STEPS = 50.0f;
static const float CURTAIN_SHARPNESS = 39.0f;
static const float CURTAIN_SOFTNESS = 1.3f;
static const float COLOR_VARIATION = 0.28f;
static const float VERTICAL_FADE = 25.0f;
static const float CAMERA_DISTANCE = 9.7f;

// === PERSISTENCE & DECAY CONTROLS ===
static const float ACCUMULATION_DECAY = 0.03f; // Decay per frame: 0.0 = infinite, 0.005 = slow fade
static const float MOUSE_PERSIST_INTENSITY = 1.1f; // Brightness multiplier for persistent rays

// === STAR FIELD CONTROLS ===
static const float STAR_FIELD_ROTATIONS_SPEED =
    (2 * PI) / (86400 * TIME_SCALE);
static const float STAR_BRIGHTNESS = 0.7f;
static const float STAR_SIZE = 1.6f;
static const float STAR_TWINKLE_SPEED = 0.05f;
static const float STAR_DENSITY = 6.0f;
static const float STAR_BRIGHTNESS_VARIATION = 6.0f;

// === TURBULENCE & CHROMATIC TWINKLE TUNING KNOBS ===
static const float STAR_TURBULENCE_SCALE = 8.0f;
static const float3 STAR_WIND_DRIFT_SPEED = float3(0.12f, 0.04f, 0.08f);
static const float STAR_DISPERSION_SCALE = 0.06f;
static const float STAR_DISPERSION_HORIZON_FACTOR = 1.2f;
static const float3 STAR_DISPERSION_DIR = float3(0.3f, 0.8f, 0.2f);

static const float STAR_TWINKLE_BASE = 0.7f;
static const float STAR_TWINKLE_AMPLITUDE = 0.2f;
static const float STAR_TWINKLE_WAVE_B_MULT = 0.9f;
static const float STAR_TWINKLE_WAVE_C_MULT = 2.3f;
static const float STAR_TWINKLE_CORRELATION = 0.85f;

static const float3 TWINKLE_WAVE_DIR_A = float3(1.618f, 2.718f, 1.414f);
static const float3 TWINKLE_WAVE_DIR_B = float3(2.414f, 1.732f, 3.141f);
static const float3 TWINKLE_WAVE_DIR_C = float3(2.236f, 3.302f, 1.732f);

// === RANDOMIZATION CONTROLS ===
static const float RANDOMIZE = 1.0f;
static const float RESEED_INTERVAL = 300.0f;
static const float TRANSITION_DIP = 2.5f;
static const float DIP_LEVEL = 0.30f;

// === MOUSE TRAIL & RADIAL RAY SHAPE CONTROLS ===
static const float MOUSE_AURORA_INTENSITY = 0.15f;
static const float MOUSE_TRAIL_WIDTH = 0.06f;
static const float MOUSE_RAY_WIDTH = 0.015f;      // Tangential ray width
static const float MOUSE_RAY_LENGTH = 0.11f;      // Radial ray length along center alignment
static const float MOUSE_RAY_FREQUENCY = 160.0f;  // Fine curtain thread streaking frequency
static const float MOUSE_TRAIL_NOISE_SCALE = 3.0f;
static const float MOUSE_PRESS_BOOST = 0.3f;
static const float MOUSE_IGNORE_WHEN_HIDDEN = 0.0f;
static const float DEBUG_MOUSE_OVERLAY = 0.0f;

static const float3 SKY_COLOR_TOP = float3(0.05f, 0.1f, 0.2f);
static const float3 SKY_COLOR_BOTTOM = float3(0.1f, 0.05f, 0.2f);

static const float2x2 TRI_ROT_MATRIX =
    float2x2(0.95534f, 0.29552f, -0.29552f, 0.95534f);

static const float LATITUDE_DEGREES = 61.2f;
static const float LAT_RAD = LATITUDE_DEGREES * (3.14159265359f / 180.0f);
static const float3 CELESTIAL_POLE = float3(0.0f, sin(LAT_RAD), cos(LAT_RAD));
static const float PERSPECTIVE_TILT = 0.12f;

static const int STAR_LAYERS = 4;
static const float STAR_LAYER_DENSITY[STAR_LAYERS] = {0.0005f, 0.0015f, 0.0045f, 0.0125f};

static const float TWINKLE_FREQ_A = 1.618034f;
static const float TWINKLE_FREQ_B = 2.414214f;

static const int STAGE = 0;  // internal use only

// === TRIANGLE WAVE NOISE ===

float triWave(float x) { return clamp(abs(frac(x) - 0.5f), 0.01f, 0.49f); }

float2 triWave2(float2 p) {
  return float2(triWave(p.x) + triWave(p.y), triWave(p.y + triWave(p.x)));
}

float triNoise2d(float2 p, float spd, float timestamp, float sharpness) {
  float z = 1.8f;
  float z2 = 2.5f;
  float rz = 0.0f;

  float c = cos(p.x * 0.06f);
  float s = sin(p.x * 0.06f);
  p = mul(float2x2(c, s, -s, c), p);

  float2 bp = p;

  [ForceUnroll] for (int i = 0; i < 5; i++) {
    float2 dg = triWave2(bp * 1.85f) * 0.75f;
    float tc = cos(timestamp * spd);
    float ts = sin(timestamp * spd);
    dg = mul(float2x2(tc, ts, -ts, tc), dg);
    p -= dg / z2;

    bp *= 1.3f;
    z2 *= 0.45f;
    z *= 0.42f;
    p *= 1.21f + (rz - 1.0f) * 0.02f;

    rz += triWave(p.x + triWave(p.y)) * z;
    p = mul(TRI_ROT_MATRIX, p) * -1.0f;
  }

  return clamp(1.0f / pow(rz * sharpness, CURTAIN_SOFTNESS), 0.0f, 0.55f);
}

// === HASH FUNCTIONS ===

float hash21(float2 n) {
  return frac(sin(dot(n, float2(12.9898f, 4.1414f))) * 43758.5453f);
}

uint pcgHash(uint v) {
  v = v * 747796405u + 2891336453u;
  uint w = ((v >> ((v >> 28u) + 4u)) ^ v) * 277803737u;
  return (w >> 22u) ^ w;
}

float epochRand(uint epoch, uint channel) {
  uint seed = epoch * 0x9E3779B9u ^ (channel * 0x85EBCA6Bu + 0x27D4EB2Fu);
  return float(pcgHash(seed)) * (1.0f / 4294967295.0f);
}

float3 pcgHash33(float3 q) {
  const uint STREAM_X = 0x9E3779B9u;
  const uint STREAM_Y = 0x85EBCA6Bu;
  const uint STREAM_Z = 0xC2B2AE35u;

  uint3 p = uint3(int3(floor(q)));

  const uint MULT = 0x5851F42Du;

  uint h = p.x * MULT + p.y * 0x27D4EB2Fu + p.z * 0x165667B1u + STREAM_X;
  h = ((h >> ((h >> 28u) + 4u)) ^ h) * 277803737u;
  uint outX = (h >> 22u) ^ h;

  h = p.y * MULT + p.z * 0x27D4EB2Fu + p.x * 0x165667B1u + STREAM_Y;
  h = ((h >> ((h >> 28u) + 4u)) ^ h) * 277803737u;
  uint outY = (h >> 22u) ^ h;

  h = p.z * MULT + p.x * 0x27D4EB2Fu + p.y * 0x165667B1u + STREAM_Z;
  h = ((h >> ((h >> 28u) + 4u)) ^ h) * 277803737u;
  uint outZ = (h >> 22u) ^ h;

  return float3(outX, outY, outZ) * (1.0f / 4294967295.0f);
}

// === PER-EPOCH RANDOM PARAMETERS ===

struct AuroraRandParams {
  float timeOffset;
  float2 startOffset;
  float waveSpeedMul;
  float scaleMul;
  float sharpMul;
  float colorJitter;
  float intensityMul;
};

AuroraRandParams identityParams() {
  AuroraRandParams rp;
  rp.timeOffset = 0.0f;
  rp.startOffset = float2(0.0f, 0.0f);
  rp.waveSpeedMul = 1.0f;
  rp.scaleMul = 1.0f;
  rp.sharpMul = 1.0f;
  rp.colorJitter = 0.0f;
  rp.intensityMul = 1.0f;
  return rp;
}

AuroraRandParams epochParams(uint epoch) {
  AuroraRandParams rp;
  rp.timeOffset = epochRand(epoch, 1u) * 4096.0f;
  rp.startOffset = float2(0.0f, 0.0f);
  rp.waveSpeedMul = lerp(0.75f, 1.25f, epochRand(epoch, 6u));
  rp.scaleMul = lerp(0.85f, 1.15f, epochRand(epoch, 7u));
  rp.sharpMul = lerp(0.80f, 1.20f, epochRand(epoch, 8u));
  rp.colorJitter = lerp(-0.6f, 0.6f, epochRand(epoch, 9u));
  rp.intensityMul = lerp(0.85f, 1.15f, epochRand(epoch, 10u));
  return rp;
}

AuroraRandParams lerpParams(AuroraRandParams a, AuroraRandParams b, float t) {
  AuroraRandParams rp;
  rp.timeOffset = lerp(a.timeOffset, b.timeOffset, t);
  rp.startOffset = lerp(a.startOffset, b.startOffset, t);
  rp.waveSpeedMul = lerp(a.waveSpeedMul, b.waveSpeedMul, t);
  rp.scaleMul = lerp(a.scaleMul, b.scaleMul, t);
  rp.sharpMul = lerp(a.sharpMul, b.sharpMul, t);
  rp.colorJitter = lerp(a.colorJitter, b.colorJitter, t);
  rp.intensityMul = lerp(a.intensityMul, b.intensityMul, t);
  return rp;
}

AuroraRandParams getAuroraParams(float rawTimestamp, float randomFloat) {
  if (RANDOMIZE <= 0.001f)
    return identityParams();
  uint launchOffset = uint(randomFloat * 100000.0f);
  uint epoch = uint(floor(rawTimestamp / RESEED_INTERVAL)) + launchOffset;
  return lerpParams(identityParams(), epochParams(epoch), RANDOMIZE);
}

float transitionBrightness(float rawTimestamp) {
  if (RANDOMIZE <= 0.001f)
    return 1.0f;
  float ph = frac(rawTimestamp / RESEED_INTERVAL);
  float dEpoch = min(ph, 1.0f - ph) * RESEED_INTERVAL;
  float halfDip = TRANSITION_DIP * 0.5f;
  if (dEpoch >= halfDip)
    return 1.0f;
  float u = dEpoch / max(halfDip, 1e-4f);
  return lerp(DIP_LEVEL, 1.0f, smoothstep(0.0f, 1.0f, u));
}

// === PROCEDURAL STARS ===

float magnitudeToBrightness(float hashVal) {
  float mag = hashVal * STAR_BRIGHTNESS_VARIATION;
  return pow(10.0f, -0.4f * mag);
}

float evalTwinkleWave(float3 pos, float seed, float horizonFactor) {
  float variance = 1.0f - STAR_TWINKLE_CORRELATION;

  float seedPhaseA = seed * 6.2831853f * variance;
  float seedPhaseB = seed * 3.14159265f * variance;
  float seedPhaseC = seed * 4.71238898f * variance;
  float freqMod = 1.0f + (frac(seed * 17.13f) - 0.5f) * 0.6f * variance;

  float spd = STAR_TWINKLE_SPEED * freqMod * horizonFactor;

  float waveA = sin(dot(pos, TWINKLE_WAVE_DIR_A) * spd + seedPhaseA);
  float waveB = cos(dot(pos, TWINKLE_WAVE_DIR_B) * spd * STAR_TWINKLE_WAVE_B_MULT +
                    seedPhaseB + waveA * 0.7f);
  float waveC = sin(dot(pos, TWINKLE_WAVE_DIR_C) * spd * STAR_TWINKLE_WAVE_C_MULT +
                    seedPhaseC);
  float microFlash = pow(clamp(waveC * 0.5f + 0.5f, 0.0f, 1.0f), 3.0f);

  float combined = waveA * 0.45f + waveB * 0.35f + (microFlash - 0.2f) * 0.4f;

  return max(0.0f, STAR_TWINKLE_BASE +
                       STAR_TWINKLE_AMPLITUDE * combined * horizonFactor);
}

float3 continuousChromaticTwinkle(float3 rd, float time, float seed) {
  float3 turbulencePos = rd * STAR_TURBULENCE_SCALE;
  float3 windDrift = time * STAR_WIND_DRIFT_SPEED;
  float3 p = turbulencePos + windDrift;

  float horizonFactor = 1.0f + 0.8f * saturate(STAR_DISPERSION_HORIZON_FACTOR - rd.y);
  float dispersionScale = STAR_DISPERSION_SCALE * saturate(STAR_DISPERSION_HORIZON_FACTOR - rd.y);

  float3 pR = p - STAR_DISPERSION_DIR * dispersionScale;
  float3 pG = p;
  float3 pB = p + STAR_DISPERSION_DIR * dispersionScale;

  float twR = evalTwinkleWave(pR, seed, horizonFactor);
  float twG = evalTwinkleWave(pG, seed, horizonFactor);
  float twB = evalTwinkleWave(pB, seed, horizonFactor);

  return float3(twR, twG, twB);
}

float3 sampleStars(float3 rd, float2 res, float time) {
  if (STAR_BRIGHTNESS <= 0.0f)
    return float3(0.0f, 0.0f, 0.0f);

  float rotSpeed = STAR_FIELD_ROTATIONS_SPEED;
  float angle = time * rotSpeed;
  float ca = cos(angle);
  float sa = sin(angle);

  float3 rotRd = rd * ca + cross(CELESTIAL_POLE, rd) * sa +
                 CELESTIAL_POLE * dot(CELESTIAL_POLE, rd) * (1.0f - ca);

  float3 c = float3(0.0f, 0.0f, 0.0f);

  [ForceUnroll] for (int i = 0; i < STAR_LAYERS; i++) {
    float scale = (0.15f + float(i) * 0.02f) * res.x;

    float3 layerOffset = float3(float(i) * 0.371f, float(i) * 0.519f, float(i) * 0.163f);
    float3 scaledRd = rotRd * scale + layerOffset;

    float3 q = frac(scaledRd) - 0.5f;
    float3 id = floor(scaledRd);
    float3 rn = pcgHash33(id);

    float threshold = STAR_LAYER_DENSITY[i] * STAR_DENSITY;
    if (rn.x >= threshold)
      continue;

    float c2 = 1.0f - smoothstep(0.0f, STAR_SIZE, length(q));
    float3 twinkleRGB = continuousChromaticTwinkle(rotRd, time, rn.y);
    float starFlux = magnitudeToBrightness(rn.y);
    float3 starCol = lerp(float3(1.0f, 0.49f, 0.1f), float3(0.75f, 0.9f, 1.0f), rn.z);

    c += c2 * starCol * starFlux * twinkleRGB;
  }
  return c * c * STAR_BRIGHTNESS;
}

// === MOUSE TRAIL FIELD ===

float mouseTrailField(float3 worldPos, float2 mouseWorld, float mouseValid,
                      float strength) {
  if (strength <= 0.0f || mouseValid <= 0.5f)
    return 0.0f;

  float dist = length(worldPos.xz - mouseWorld);

  float falloff = saturate(1.0f - dist / MOUSE_TRAIL_WIDTH);
  falloff = falloff * falloff * (3.0f - 2.0f * falloff);

  return falloff * strength;
}

// === ZENITH PROJECTION HELPER ===

float3 zenithRayDir(float2 centeredUV, float aspect, float horizonRadius,
                    float spinCos, float spinSin) {
  float2 scaledUV = centeredUV * float2(aspect, 1.0f) * horizonRadius;
  float r2 = dot(scaledUV, scaledUV);
  float rd_y = 1.0f / sqrt(1.0f + r2);
  float3 rd = normalize(float3(scaledUV.x, rd_y, scaledUV.y));

  float ct = cos(PERSPECTIVE_TILT);
  float st = sin(PERSPECTIVE_TILT);
  rd.yz = float2(rd.y * ct - rd.z * st, rd.y * st + rd.z * ct);

  rd.xz = mul(float2x2(spinCos, spinSin, -spinSin, spinCos), rd.xz);
  return rd;
}

// === VOLUMETRIC AURORA RAY MARCH ===

float4 rayMarchAurora(float3 ro, float3 rd, float2 fragCoord, float noiseTime,
                      AuroraRandParams rp, float2 mouseWorld, float mouseValid,
                      float genStrength, float persistentTrail) {
  float stepCount = MARCH_STEPS;

  float effSpeed = WAVE_SPEED * rp.waveSpeedMul;
  float effSharpness = CURTAIN_SHARPNESS * rp.sharpMul;
  float effScale = AURORA_SCALE * rp.scaleMul;

  float3 accColor = float3(0.0f);
  float accAlpha = 0.0f;

  [ForceUnroll] for (int i = 0; i < 60; i++) {
    if (float(i) >= stepCount)
      break;

    float of = 0.006f * hash21(fragCoord) * smoothstep(0.0f, 15.0f, float(i));
    float pt = ((AURORA_ALTITUDE + pow(float(i), 1.4f) * 0.002f) - ro.y) /
               (rd.y * 2.0f + 0.4f);
    pt -= of;

    if (pt < 0.0f)
      continue;

    float3 bpos = ro + pt * rd;
    float2 p = bpos.zx * effScale + rp.startOffset;
    float density = triNoise2d(p, effSpeed, noiseTime, effSharpness);

    float trailField = mouseTrailField(bpos, mouseWorld, mouseValid, genStrength) + persistentTrail;
    float trailNoise = triNoise2d(p * MOUSE_TRAIL_NOISE_SCALE + mouseWorld * 0.5f,
                               effSpeed * 1.5f, noiseTime, effSharpness * 0.8f);
    density = saturate(density + trailField * (trailNoise + 0.6f));

    float h = float(i) / MARCH_STEPS;
    float3 colLow = float3(0.1f, 0.95f, 0.4f);
    float3 colMid = float3(0.1f, 0.85f, 0.85f);
    float3 colHigh = float3(0.65f, 0.25f, 0.95f);
    float t1 = smoothstep(0.0f, 0.45f, h);
    float t2 = smoothstep(0.35f, 1.0f, h);
    float3 baseCol = lerp(lerp(colLow, colMid, t1), colHigh, t2);
    baseCol += sin(float3(0.0f, 1.0f, 2.0f) + h * 6.0f + rp.colorJitter) * 0.06f;
    baseCol = max(baseCol, float3(0.0f));

    float3 mouseCol = float3(0.15f, 0.75f, 1.0f);
    float3 stepColor = lerp(baseCol, mouseCol, saturate(trailField * 1.5f));

    float absorption = exp(-accAlpha * 2.0f);
    accColor += stepColor * density * absorption;
    accAlpha += density * 0.05f;
  }

  accColor *= AURORA_INTENSITY * rp.intensityMul;

  return float4(accColor, saturate(accAlpha));
}

// === SMOOTH CUTOFF ===

float smoothCutoff(float value, float floor_, float ceiling) {
  float t = saturate((value - floor_) / max(ceiling - floor_, 0.001f));
  return t * t * (3.0f - 2.0f * t);
}

// === ENTRY POINT ===

public
float4 fragment_main(float4 color, KittyTextures t, KittyCustomShaderData d) {
  float2 pixelDims = float2(d.viewport_size_pixels) * t.viewport.zw;
  float timestamp = fmod(d.timestamp, 86400.0f) * TIME_SCALE;

  float2 uv = t.pos;
  float aspect = pixelDims.x / max(pixelDims.y, 1.0f);

  float2 mouseUV = (d.mouse_pos.xy - t.viewport.xy) / max(t.viewport.zw, float2(1e-5f, 1e-5f));
  bool inWindow = all(mouseUV >= float2(0.0f)) && all(mouseUV <= float2(1.0f));
  float mouseValid = float(inWindow);
  if (MOUSE_IGNORE_WHEN_HIDDEN > 0.5f && d.mouse_pointer_hidden > 0.5f)
    mouseValid = 0.0f;

  // First group: Accumulate radial aurora rays cast from sky center into scratch texture 'a'
  if (STAGE == 0) {
    float prev = t.persist.Sample(uv).r;
    float decayed = prev * saturate(1.0f - ACCUMULATION_DECAY);

    float deposit = 0.0f;
    if (mouseValid > 0.5f && d.mouse_button_pressed.x > 0.5f) {
      // Aspect-corrected UVs relative to screen center (0.5, 0.5)
      float2 cUV = (uv - 0.5f) * float2(aspect, 1.0f);
      float2 mUV = (mouseUV - 0.5f) * float2(aspect, 1.0f);

      // Radial direction vector from sky center through the mouse click
      float mLen = length(mUV);
      float2 mDir = (mLen > 0.0001f) ? (mUV / mLen) : float2(0.0f, 1.0f);
      float2 mTangent = float2(-mDir.y, mDir.x); // Perpendicular to radial ray

      // Difference vector from click point to current pixel
      float2 diff = cUV - mUV;

      // Project onto radial (along) and tangential (across) axes
      float distAlongRay = dot(diff, mDir);
      float distAcrossRay = dot(diff, mTangent);

      // Asymmetric ray length extending outward from the click point
      float yMax = (distAlongRay >= 0.0f) ? MOUSE_RAY_LENGTH : (MOUSE_RAY_LENGTH * 0.25f);

      float hDist = abs(distAcrossRay) / max(MOUSE_RAY_WIDTH, 0.001f);
      float vDist = abs(distAlongRay) / max(yMax, 0.001f);

      // High-frequency curtain thread streaking along the ray width
      float streaks1 = sin(distAcrossRay * MOUSE_RAY_FREQUENCY) * 0.35f + 0.65f;
      float streaks2 = cos(distAcrossRay * MOUSE_RAY_FREQUENCY * 2.3f) * 0.25f + 0.75f;

      float hFalloff = smoothstep(1.0f, 0.0f, hDist);
      float vFalloff = smoothstep(1.0f, 0.0f, vDist);

      deposit = hFalloff * vFalloff * streaks1 * streaks2 * MOUSE_PRESS_BOOST;
    }

    return float4(saturate(decayed + deposit), 0.0f, 0.0f, 1.0f);
  }

  // Second group: Copy scratch texture 'a' to 'persist'
  if (STAGE == 1) {
    return t.a.Sample(uv);
  }

  // Third group: Main composite pass
  AuroraRandParams rp = getAuroraParams(d.timestamp, INITIAL_RANDOM_SEED);
  float epochBrightness = transitionBrightness(d.timestamp);
  float noiseTime = timestamp + rp.timeOffset;

  float2 fragCoord = uv * pixelDims;

  float persistentTrail = t.persist.Sample(uv).r * MOUSE_PERSIST_INTENSITY;

  float3 ro = float3(0.0f, 0.0f, -CAMERA_DISTANCE);
  float2 centeredUV = uv - 0.5f;

  float horizonRadius = 1.5f;

  float spinAngle = timestamp * 0.02f;
  float cs = cos(spinAngle), ss = sin(spinAngle);

  float3 rd = zenithRayDir(centeredUV, aspect, horizonRadius, cs, ss);

  float3 bgCol = lerp(SKY_COLOR_TOP, SKY_COLOR_BOTTOM, 1.0f - rd.y) * 0.63f;
  float3 col = bgCol;

  float2 mouseWorld = float2(0.0f, 0.0f);

  if (mouseValid > 0.5f) {
    float2 mCenteredUV = mouseUV - 0.5f;
    float3 mrd = zenithRayDir(mCenteredUV, aspect, horizonRadius, cs, ss);

    float denom = mrd.y * 2.0f + 0.4f;
    if (denom > 0.001f) {
      float dist = (AURORA_ALTITUDE - ro.y) / denom;
      mouseWorld = (ro + mrd * dist).xz;
    }
  }

  float genStrength = MOUSE_AURORA_INTENSITY *
                      (1.0f + d.mouse_button_pressed.x * MOUSE_PRESS_BOOST);

  float4 aur = smoothstep(0.0f, 1.5f,
                          rayMarchAurora(ro, rd, fragCoord, noiseTime, rp,
                                         mouseWorld, mouseValid, genStrength, persistentTrail));
  col += sampleStars(rd, pixelDims, timestamp);
  col = col * (1.0f - aur.a) + aur.rgb;

  col *= EFFECT_INTENSITY * epochBrightness;

  float effectLum = dot(col, float3(0.299f, 0.587f, 0.114f));
  float gate = smoothCutoff(effectLum, EFFECT_FLOOR, EFFECT_CEILING);
  col *= gate;

  float4 terminalColor = t.backbuffer.Sample(t.pos);
  float termLum = dot(terminalColor.rgb, float3(0.299f, 0.587f, 0.114f));
  float isBlack = step(termLum, 0.001f);
  float textPreserve = 1.0f - smoothstep(BLACK_BLEND_THRESHOLD,
                                         BLACK_BLEND_THRESHOLD + 0.2f, termLum);
  float blendFactor = lerp(textPreserve * EFFECT_INTENSITY, 1.0f, isBlack);
  float3 blendedColor = terminalColor.rgb + col * blendFactor;

  if (DEBUG_MOUSE_OVERLAY > 0.5f && mouseValid > 0.5f) {
    float ptProxy = (AURORA_ALTITUDE - ro.y) / (rd.y * 2.0f + 0.4f);
    float g = mouseTrailField(ro + rd * ptProxy, mouseWorld, 1.0f, genStrength);
    blendedColor =
        lerp(blendedColor, float3(1.0f, 0.25f, 0.05f), saturate(g * 2.0f));
  }

  return float4(blendedColor, terminalColor.a);
}
