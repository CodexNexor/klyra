import { useRef, useMemo } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import * as THREE from 'three'

function Stars() {
  const ref = useRef<THREE.Points>(null!)
  const cubeRef = useRef<THREE.Mesh>(null!)
  const wireRef = useRef<THREE.LineSegments>(null!)

  const [positions, colors, sizes] = useMemo(() => {
    const count = 1200
    const p = new Float32Array(count * 3)
    const c = new Float32Array(count * 3)
    const s = new Float32Array(count)
    for (let i = 0; i < count; i++) {
      p[i * 3] = (Math.random() - 0.5) * 150
      p[i * 3 + 1] = (Math.random() - 0.5) * 150
      p[i * 3 + 2] = (Math.random() - 0.5) * 150
      const choice = Math.random()
      if (choice < 0.33) {
        c[i * 3] = 0; c[i * 3 + 1] = 1; c[i * 3 + 2] = 0.25
      } else if (choice < 0.66) {
        c[i * 3] = 0.1; c[i * 3 + 1] = 0.5; c[i * 3 + 2] = 1
      } else {
        c[i * 3] = 1; c[i * 3 + 1] = 1; c[i * 3 + 2] = 1
      }
      s[i] = 0.05 + Math.random() * 0.2
    }
    return [p, c, s]
  }, [])

  const starGeom = useMemo(() => {
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    g.setAttribute('color', new THREE.BufferAttribute(colors, 3))
    g.setAttribute('size', new THREE.BufferAttribute(sizes, 1))
    return g
  }, [positions, colors, sizes])

  const cubeGeom = useMemo(() => new THREE.BoxGeometry(2, 2, 2), [])
  const wireGeom = useMemo(() => new THREE.EdgesGeometry(new THREE.BoxGeometry(3.5, 3.5, 3.5)), [])

  useFrame((_, delta) => {
    ref.current.rotation.y += delta * 0.008
    ref.current.rotation.x += delta * 0.003
    if (cubeRef.current) {
      cubeRef.current.rotation.x += delta * 0.2
      cubeRef.current.rotation.y += delta * 0.3
    }
    if (wireRef.current) {
      wireRef.current.rotation.x += delta * 0.15
      wireRef.current.rotation.y += delta * 0.25
    }
  })

  return (
    <group>
      <points ref={ref} geometry={starGeom}>
        <pointsMaterial size={0.12} vertexColors transparent opacity={0.9} sizeAttenuation />
      </points>
      <mesh ref={cubeRef} geometry={cubeGeom} position={[0, 0, -15]}>
        <meshBasicMaterial color="#00ff41" transparent opacity={0.08} wireframe={false} />
      </mesh>
      <lineSegments ref={wireRef} geometry={wireGeom} position={[0, 0, -15]}>
        <lineBasicMaterial color="#00ff41" transparent opacity={0.15} />
      </lineSegments>
    </group>
  )
}

export default function Starfield() {
  return (
    <div id="starfield-canvas">
      <Canvas
        camera={{ position: [0, 0, 35], fov: 65 }}
        gl={{ antialias: false, alpha: true }}
        style={{ background: 'transparent' }}
      >
        <Stars />
      </Canvas>
    </div>
  )
}
