import { useEffect, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import * as THREE from 'three'
import { useViewer } from '../state/store'

// Reused scratch vectors (avoid per-frame allocation).
const _look = new THREE.Vector3()
const _fwdH = new THREE.Vector3()
const _rightH = new THREE.Vector3()
const _move = new THREE.Vector3()
const _pivot = new THREE.Vector3()
const _camPos = new THREE.Vector3()

const SPAWN = new THREE.Vector3(0, 0, 16)
const EYE = 1.55
const GRAVITY = 18
const JUMP = 6
const LOOK_SENS = 0.0022

/**
 * Third-person-shooter controller (custom kinematic — no physics engine).
 * - Pointer-lock mouse-look, WASD relative to camera, Shift to run, Space to jump.
 * - Press F to toggle free-fly / noclip (Space = up, C/Ctrl = down) so you can
 *   rise above the multi-metre detector.
 * - Camera orbits behind a human-scale avatar and is clamped above the ground.
 */
export function Player() {
  const camera = useThree((s) => s.camera)
  const gl = useThree((s) => s.gl)
  const setLookEngaged = useViewer((s) => s.setLookEngaged)

  const avatarRef = useRef<THREE.Group>(null)
  const keys = useRef<Record<string, boolean>>({})
  const yaw = useRef(0)
  const pitch = useRef(-0.06)
  const dist = useRef(5)
  const velY = useRef(0)
  const grounded = useRef(true)
  const locked = useRef(false)

  // Pointer-lock + mouse-look + zoom wired to the WebGL canvas.
  useEffect(() => {
    const dom = gl.domElement
    const onClick = () => {
      if (document.pointerLockElement !== dom) dom.requestPointerLock()
    }
    const onLockChange = () => {
      locked.current = document.pointerLockElement === dom
      setLookEngaged(locked.current)
    }
    const onMouseMove = (e: MouseEvent) => {
      if (document.pointerLockElement !== dom) return
      yaw.current -= e.movementX * LOOK_SENS
      pitch.current -= e.movementY * LOOK_SENS
      const lim = Math.PI / 2 - 0.05
      pitch.current = Math.max(-lim, Math.min(lim, pitch.current))
    }
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      dist.current = Math.max(2, Math.min(18, dist.current + e.deltaY * 0.01))
    }
    dom.addEventListener('click', onClick)
    document.addEventListener('pointerlockchange', onLockChange)
    document.addEventListener('mousemove', onMouseMove)
    dom.addEventListener('wheel', onWheel, { passive: false })
    return () => {
      dom.removeEventListener('click', onClick)
      document.removeEventListener('pointerlockchange', onLockChange)
      document.removeEventListener('mousemove', onMouseMove)
      dom.removeEventListener('wheel', onWheel)
    }
  }, [gl, setLookEngaged])

  // Keyboard state + F to toggle fly.
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      keys.current[e.code] = true
      if (e.code === 'KeyF' && !e.repeat) useViewer.getState().toggleMode()
      if (e.code === 'Space') e.preventDefault()
    }
    const up = (e: KeyboardEvent) => {
      keys.current[e.code] = false
    }
    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    return () => {
      window.removeEventListener('keydown', down)
      window.removeEventListener('keyup', up)
    }
  }, [])

  useFrame((_, dtRaw) => {
    const avatar = avatarRef.current
    if (!avatar) return
    const dt = Math.min(dtRaw, 0.05)
    const k = keys.current
    const flying = useViewer.getState().mode === 'fly'

    const cosP = Math.cos(pitch.current)
    _look.set(-Math.sin(yaw.current) * cosP, Math.sin(pitch.current), -Math.cos(yaw.current) * cosP)
    _fwdH.set(-Math.sin(yaw.current), 0, -Math.cos(yaw.current))
    _rightH.set(Math.cos(yaw.current), 0, -Math.sin(yaw.current))

    if (locked.current) {
      const run = k['ShiftLeft'] || k['ShiftRight']
      const speed = flying ? (run ? 36 : 12) : run ? 9 : 4.2
      const fdir = flying ? _look : _fwdH
      _move.set(0, 0, 0)
      if (k['KeyW']) _move.add(fdir)
      if (k['KeyS']) _move.addScaledVector(fdir, -1)
      if (k['KeyD']) _move.add(_rightH)
      if (k['KeyA']) _move.addScaledVector(_rightH, -1)
      if (_move.lengthSq() > 0) _move.normalize().multiplyScalar(speed * dt)
      avatar.position.x += _move.x
      avatar.position.z += _move.z

      if (flying) {
        avatar.position.y += _move.y
        if (k['Space']) avatar.position.y += speed * dt
        if (k['KeyC'] || k['ControlLeft']) avatar.position.y -= speed * dt
        velY.current = 0
      } else {
        if (k['Space'] && grounded.current) {
          velY.current = JUMP
          grounded.current = false
        }
      }
    }

    // Gravity (walk mode only) — also settles to ground when idle.
    if (!flying) {
      velY.current -= GRAVITY * dt
      avatar.position.y += velY.current * dt
      if (avatar.position.y <= 0) {
        avatar.position.y = 0
        velY.current = 0
        grounded.current = true
      }
    }

    // Face the avatar along the horizontal look direction.
    avatar.rotation.y = Math.atan2(_fwdH.x, _fwdH.z)

    // Orbit the camera behind the avatar, clamped above the floor.
    _pivot.set(avatar.position.x, avatar.position.y + EYE, avatar.position.z)
    _camPos.copy(_pivot).addScaledVector(_look, -dist.current)
    if (_camPos.y < 0.4) _camPos.y = 0.4
    camera.position.copy(_camPos)
    camera.lookAt(_pivot)
  })

  return (
    <group ref={avatarRef} position={[SPAWN.x, SPAWN.y, SPAWN.z]}>
      {/* torso */}
      <mesh castShadow position={[0, 0.9, 0]}>
        <capsuleGeometry args={[0.34, 1.12, 8, 16]} />
        <meshStandardMaterial color="#3b6fd4" metalness={0.15} roughness={0.55} />
      </mesh>
      {/* head */}
      <mesh castShadow position={[0, 1.62, 0]}>
        <sphereGeometry args={[0.21, 24, 24]} />
        <meshStandardMaterial color="#e4ecff" metalness={0.1} roughness={0.5} />
      </mesh>
      {/* facing indicator */}
      <mesh castShadow position={[0, 1.18, 0.34]} rotation={[Math.PI / 2, 0, 0]}>
        <coneGeometry args={[0.1, 0.3, 16]} />
        <meshStandardMaterial color="#ffcf5a" emissive="#6e4f0e" emissiveIntensity={0.6} roughness={0.5} />
      </mesh>
    </group>
  )
}
