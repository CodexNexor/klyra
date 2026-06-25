import { useRef, useMemo } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import * as THREE from 'three'

const vertexShader = `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`

const fragmentShader = `
uniform float uTime;
uniform vec2 uResolution;
varying vec2 vUv;

#define COLUMNS 40.0

float hash(vec2 p) {
  return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

float matrixColumn(vec2 uv, float offset) {
  float col = floor(uv.x * COLUMNS + offset);
  float row = uv.y * 50.0;
  float id = hash(vec2(col, floor(row)));
  float trail = fract(row - id * 12.0 + uTime * (0.3 + id * 0.4));
  float glyph = step(0.95, trail) * 0.8;
  float glow = exp(-trail * 6.0) * 0.4;
  float dist = abs(fract(uv.x * COLUMNS + offset) - 0.5) * 2.0;
  return (glyph + glow) * (1.0 - dist * 0.5);
}

float grid(vec2 uv) {
  vec2 gv = fract(uv * 8.0);
  vec2 gw = abs(gv - 0.5);
  float line = 1.0 - smoothstep(0.0, 0.02, min(gw.x, gw.y));
  return line * 0.15;
}

float glowCircle(vec2 uv, vec2 center, float radius) {
  float d = length(uv - center);
  return exp(-d * d * 8.0) * 0.3;
}

void main() {
  vec2 uv = vUv;
  vec2 suv = (gl_FragCoord.xy - 0.5 * uResolution) / min(uResolution.x, uResolution.y);

  float mx = 0.0;
  for (float i = 0.0; i < 6.0; i++) {
    float offset = i * 3.7 + uTime * 0.02;
    mx += matrixColumn(uv, offset) * (0.5 + 0.5 * sin(i + 1.0));
  }
  mx = mx / 6.0;

  float g = grid(uv + uTime * 0.005 * vec2(0.3, 0.1));
  float pulse = 0.5 + 0.5 * sin(uTime * 0.5);

  vec3 col = vec3(0.02, 0.01, 0.04);

  vec3 green = vec3(0.0, 1.0, 0.25);
  vec3 gold = vec3(0.98, 0.82, 0.0);
  vec3 cyan = vec3(0.0, 1.0, 1.0);

  vec3 matrixCol = mix(green, gold, sin(uv.y * 10.0 + uTime * 0.3) * 0.5 + 0.5);
  col += matrixCol * mx * (0.6 + 0.4 * pulse);

  col += vec3(0.0, 0.3, 0.1) * g * (0.8 + 0.2 * pulse);

  float gc = glowCircle(suv, vec2(sin(uTime * 0.15) * 0.4, cos(uTime * 0.2) * 0.3), 0.8);
  col += vec3(0.0, 0.2, 0.1) * gc;

  float scanline = sin(gl_FragCoord.y * 0.5) * 0.5 + 0.5;
  col *= 0.85 + 0.15 * scanline;

  float vignette = 1.0 - length(uv - 0.5) * 0.6;
  col *= vignette;

  col = pow(col, vec3(0.8));

  gl_FragColor = vec4(col, 0.7);
}
`

function ShaderPlane() {
  const ref = useRef<THREE.Mesh>(null!)
  const uniforms = useMemo(() => ({
    uTime: { value: 0 },
    uResolution: { value: new THREE.Vector2(window.innerWidth, window.innerHeight) },
  }), [])

  useFrame((_, delta) => {
    uniforms.uTime.value += delta
  })

  return (
    <mesh ref={ref}>
      <planeGeometry args={[2, 2]} />
      <shaderMaterial
        fragmentShader={fragmentShader}
        vertexShader={vertexShader}
        uniforms={uniforms}
        transparent
        depthWrite={false}
      />
    </mesh>
  )
}

export default function ShaderBackground() {
  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      zIndex: 0,
      pointerEvents: 'none',
    }}>
      <Canvas
        camera={{ position: [0, 0, 1] }}
        gl={{ antialias: false, alpha: true }}
        style={{ background: 'transparent' }}
      >
        <ShaderPlane />
      </Canvas>
    </div>
  )
}
