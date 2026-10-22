// How to lie and how to scan, as a looping low-poly scene (faceted white figures in a white
// world, the things to watch in red, in the manner of the game Superhot).
//
// One clock drives everything, so the captions always match what's moving:
//   0.0-1.2 s  lying face down on a bed, legs straight
//   1.2-3.0 s  the knee bends until the lower leg points straight up: the sole faces the ceiling
//   3.0-3.6 s  the sole lights up red: this is what gets scanned
//   3.6-8.6 s  a red phone circles the foot from above, looking down at the sole, and a red ring
//              fills in behind it, segment by segment, like the app's own capture ring
//   8.6-10 s   ring full: done; the leg lowers and it starts again
// With Reduce Motion on, it holds still at the moment that says the most (knee bent, phone part
// way round, ring half full) and lists the steps instead.
import ModelIO
import SceneKit
import SceneKit.ModelIO
import SwiftUI

struct SoleScanAnimation: View {
    /// Mirror the scene for a left foot (the bent leg is the one being scanned).
    var left = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var clock = SoleScanClock()

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            SoleScanSceneView(clock: clock, left: left, still: reduceMotion)
                .frame(height: 220)
                .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(Color.black.opacity(0.06), lineWidth: 1))
                .accessibilityHidden(true)
            if reduceMotion {
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(Array(SoleScanClock.captions.enumerated()), id: \.offset) { i, c in
                        Text("\(i + 1). \(c.text)").font(.subheadline.weight(.semibold)).foregroundStyle(Color.fsInk)
                    }
                }
            } else {
                TimelineView(.animation(minimumInterval: 0.2)) { context in
                    let step = clock.step(at: context.date)
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text("\(step + 1)").font(.subheadline.weight(.heavy).monospacedDigit())
                            .foregroundStyle(.white)
                            .frame(width: 24, height: 24)
                            .background(Color(red: 0.89, green: 0.12, blue: 0.10), in: Circle())
                        Text(SoleScanClock.captions[step].text)
                            .font(.subheadline.weight(.semibold)).foregroundStyle(Color.fsInk)
                            .contentTransition(.opacity)
                            .id(step)
                            .transition(.opacity)
                    }
                    .animation(.easeInOut(duration: 0.25), value: step)
                }
                .accessibilityElement(children: .combine)
                .accessibilityLabel(SoleScanClock.captions.map(\.text).joined(separator: ". "))
            }
        }
    }
}

/// The shared clock: the scene (on SceneKit's render thread) and the captions both read it. A plain value.
struct SoleScanClock: Sendable {
    static let period: Double = 10
    static let captions: [(start: Double, text: String)] = [
        (0.0, "Lie face down on a bed or sofa"),
        (1.2, "Bend this knee: sole up to the ceiling"),
        (3.0, "Let the foot relax and keep it still"),
        (3.6, "Your helper circles slowly, phone pointing down at the sole"),
        (8.6, "Ring full all the way round: tap Finish"),
    ]
    var start = Date()

    func t(at date: Date) -> Double {
        date.timeIntervalSince(start).truncatingRemainder(dividingBy: Self.period)
    }

    func step(at date: Date) -> Int {
        let t = t(at: date)
        return Self.captions.lastIndex { $0.start <= t } ?? 0
    }
}

private struct SoleScanSceneView: UIViewRepresentable {
    let clock: SoleScanClock
    let left: Bool
    let still: Bool

    func makeCoordinator() -> SoleScanScene { SoleScanScene(clock: clock, left: left, still: still) }

    func makeUIView(context: Context) -> SCNView {
        let view = SCNView()
        view.scene = context.coordinator.scene
        view.pointOfView = context.coordinator.camera
        view.backgroundColor = SoleScanScene.world
        view.antialiasingMode = .multisampling4X
        view.preferredFramesPerSecond = 30
        view.isUserInteractionEnabled = false
        view.delegate = context.coordinator
        view.rendersContinuously = !still
        view.isPlaying = !still
        context.coordinator.apply(t: still ? 6.1 : 0)
        return view
    }

    func updateUIView(_ view: SCNView, context: Context) {}

    static func dismantleUIView(_ view: SCNView, coordinator: SoleScanScene) {
        view.isPlaying = false
        view.delegate = nil
    }
}

/// The scene itself. Units are metres, y up; the figure lies along x, head toward -x.
final class SoleScanScene: NSObject, SCNSceneRendererDelegate {
    static let world = UIColor(white: 0.94, alpha: 1)
    static let red = UIColor(red: 0.89, green: 0.12, blue: 0.10, alpha: 1)

    let scene = SCNScene()
    let camera = SCNNode()
    private let clock: SoleScanClock
    private let still: Bool
    private let knee = SCNNode()        // the bending knee: its lower leg turns about z
    private let solePlate = SCNNode()
    private let phone = SCNNode()
    private let helper = SCNNode()       // the person scanning: red, faceted, see-through (the game's figures)
    private var ring: [SCNNode] = []
    private let footCentre = SCNVector3(0.62, 0.77, 0.09)

    init(clock: SoleScanClock, left: Bool, still: Bool) {
        self.clock = clock
        self.still = still
        super.init()
        build(left: left)
    }

    // MARK: driving it

    nonisolated func renderer(_ renderer: SCNSceneRenderer, updateAtTime time: TimeInterval) {
        apply(t: clock.t(at: Date()))
    }

    nonisolated func apply(t: Double) {
        // knee: bends 1.2-3.0 s, lowers again 9.2-10 s
        let bend = ease((t - 1.2) / 1.8) * (1 - ease((t - 9.2) / 0.8))
        knee.eulerAngles.z = Float(bend * .pi / 2)
        // sole: lights up 3.0-3.6 s, stays lit while it's scanned, fades with the lowering
        let glow = ease((t - 3.0) / 0.6) * (1 - ease((t - 9.2) / 0.5))
        solePlate.opacity = CGFloat(glow)
        // phone: once round the foot 3.6-8.6 s, from the far side, looking down at the sole
        let lap = (t - 3.6) / 5.0
        let shown = lap > -0.08 && t < 9.0
        phone.opacity = shown ? CGFloat(min(1, (lap + 0.08) / 0.08, (9.0 - t) / 0.3)) : 0
        let a = -.pi / 2 + 2 * .pi * min(1, max(0, lap))
        phone.position = SCNVector3(footCentre.x + 0.30 * Float(cos(a)), footCentre.y + 0.24, footCentre.z + 0.30 * Float(sin(a)))
        // the helper stands further out at the same angle, leaning in, facing the foot
        helper.opacity = phone.opacity
        helper.position = SCNVector3(footCentre.x + 0.55 * Float(cos(a)), footCentre.y + 0.02, footCentre.z + 0.55 * Float(sin(a)))
        helper.eulerAngles.y = .pi / 2 - Float(a)  // its front (local -z) toward the foot
        // ring: each segment appears as the phone passes it; all go at the end
        for (i, seg) in ring.enumerated() {
            let at = Double(i) / Double(ring.count)
            seg.opacity = (lap >= at && t < 9.4) ? 1 : 0
        }
    }

    private nonisolated func ease(_ x: Double) -> Double {
        let c = min(1, max(0, x))
        return c * c * (3 - 2 * c)
    }

    // MARK: building it

    private func build(left: Bool) {
        let root = SCNNode()
        if left { root.scale = SCNVector3(1, 1, -1) }  // the other leg
        scene.rootNode.addChildNode(root)
        scene.background.contents = Self.world

        let white = material(UIColor(white: 0.98, alpha: 1))
        let grey = material(UIColor(white: 0.80, alpha: 1))
        let red = material(Self.red, glow: true)

        // the bed
        root.addChildNode(node(box(2.1, 0.24, 1.0), grey, at: SCNVector3(-0.15, 0.12, 0)))
        // the figure, face down
        root.addChildNode(node(prism(0.56, 0.18, 0.36), white, at: SCNVector3(-0.36, 0.33, 0)))        // torso
        root.addChildNode(node(ball(0.11), white, at: SCNVector3(-0.78, 0.36, 0)))                     // head
        root.addChildNode(node(box(0.16, 0.08, 0.34), white, at: SCNVector3(-0.82, 0.29, 0)))          // arms, folded under the chin
        root.addChildNode(node(prism(0.2, 0.16, 0.32), white, at: SCNVector3(-0.02, 0.32, 0)))         // hips
        // the straight leg (the one not being scanned)
        root.addChildNode(node(limb(0.44, 0.065), white, at: SCNVector3(0.27, 0.32, -0.09), along: .x)) // thigh
        root.addChildNode(node(limb(0.42, 0.05), white, at: SCNVector3(0.70, 0.30, -0.09), along: .x))  // lower leg
        root.addChildNode(node(box(0.06, 0.22, 0.09), white, at: SCNVector3(0.93, 0.21, -0.09)))        // foot, toes down
        // the leg being scanned: thigh, then the knee that bends
        root.addChildNode(node(limb(0.44, 0.065), white, at: SCNVector3(0.27, 0.32, 0.09), along: .x))
        knee.position = SCNVector3(0.49, 0.31, 0.09)
        root.addChildNode(knee)
        // in the knee's own frame the lower leg points +x; bent 90 degrees about z it points up.
        // The foot hangs off its end toward -y (its toes), its sole facing +x: bent, the sole faces up.
        knee.addChildNode(node(limb(0.40, 0.05), white, at: SCNVector3(0.21, 0, 0), along: .x))
        let foot = node(box(0.06, 0.24, 0.095), white, at: SCNVector3(0.43, -0.08, 0))
        knee.addChildNode(foot)
        solePlate.geometry = box(0.006, 0.22, 0.085)
        solePlate.geometry?.firstMaterial = red
        solePlate.position = SCNVector3(0.462, -0.08, 0)
        knee.addChildNode(solePlate)

        // the phone: red, always looking down at the sole
        phone.geometry = box(0.075, 0.15, 0.01)
        phone.geometry?.firstMaterial = red
        let target = SCNNode()
        target.position = footCentre
        root.addChildNode(target)
        let look = SCNLookAtConstraint(target: target)
        look.isGimbalLockEnabled = true
        look.localFront = SCNVector3(0, 0, -1)
        phone.constraints = [look]
        root.addChildNode(phone)

        // the helper: a figure leaning over the foot with the phone, red glass like the game's figures
        let glass = material(Self.red.withAlphaComponent(1), glow: false)
        glass.transparency = 0.6
        glass.isDoubleSided = false
        let chest = node(prism(0.16, 0.42, 0.26), glass, at: SCNVector3(0, 0.12, 0))
        chest.eulerAngles.x = -0.35                       // leaning in toward the foot (local -z)
        helper.addChildNode(chest)
        helper.addChildNode(node(ball(0.085), glass, at: SCNVector3(0, 0.40, -0.11)))
        let arms = node(box(0.22, 0.06, 0.34), glass, at: SCNVector3(0, 0.22, -0.26))
        arms.eulerAngles.x = -0.45                        // reaching down and in, to the phone
        helper.addChildNode(arms)
        helper.opacity = 0
        helper.scale = SCNVector3(0.8, 0.8, 0.8)
        root.addChildNode(helper)

        // the capture ring round the foot
        let n = 28
        for i in 0..<n {
            let a = -.pi / 2 + 2 * .pi * (Double(i) + 0.5) / Double(n)
            let seg = node(box(0.05, 0.012, 0.022), red,
                           at: SCNVector3(footCentre.x + 0.22 * Float(cos(a)), footCentre.y - 0.02, footCentre.z + 0.22 * Float(sin(a))))
            seg.eulerAngles.y = Float(-a) + .pi / 2
            seg.opacity = 0
            root.addChildNode(seg)
            ring.append(seg)
        }

        // light: a key light from above with crisp shadows, and a soft fill
        let key = SCNNode()
        key.light = SCNLight()
        key.light?.type = .directional
        key.light?.intensity = 900
        key.light?.castsShadow = true
        key.light?.shadowMode = .deferred
        key.light?.shadowColor = UIColor(white: 0, alpha: 0.18)
        key.light?.shadowRadius = 2
        key.eulerAngles = SCNVector3(-1.1, -0.5, 0)
        scene.rootNode.addChildNode(key)
        let fill = SCNNode()
        fill.light = SCNLight()
        fill.light?.type = .ambient
        fill.light?.intensity = 420
        scene.rootNode.addChildNode(fill)

        // camera: a three-quarter view from the side of the scanned leg, above
        camera.camera = SCNCamera()
        camera.camera?.fieldOfView = 38
        camera.position = SCNVector3(1.05, 1.75, left ? -1.85 : 1.85)
        let aim = SCNNode()
        aim.position = SCNVector3(0.2, 0.55, 0)
        scene.rootNode.addChildNode(aim)
        camera.constraints = [SCNLookAtConstraint(target: aim)]
        scene.rootNode.addChildNode(camera)
    }

    private func material(_ colour: UIColor, glow: Bool = false) -> SCNMaterial {
        let m = SCNMaterial()
        m.diffuse.contents = colour
        m.lightingModel = .lambert
        if glow { m.emission.contents = colour.withAlphaComponent(0.55) }
        return m
    }

    private enum Axis { case x, y }

    private func node(_ g: SCNGeometry, _ m: SCNMaterial, at p: SCNVector3, along axis: Axis = .y) -> SCNNode {
        let n = SCNNode(geometry: g)
        n.geometry?.firstMaterial = m
        n.position = p
        if axis == .x { n.eulerAngles.z = .pi / 2 }  // a ModelIO cylinder stands along y
        n.castsShadow = true
        return n
    }

    // Faceted shapes: few sides, every face its own flat normal (no smoothing), so the light picks out facets.
    private func faceted(_ mesh: MDLMesh) -> SCNGeometry {
        try? mesh.makeVerticesUniqueAndReturnError()
        mesh.addNormals(withAttributeNamed: MDLVertexAttributeNormal, creaseThreshold: 0)
        return SCNGeometry(mdlMesh: mesh)
    }

    private func box(_ x: Float, _ y: Float, _ z: Float) -> SCNGeometry {
        faceted(MDLMesh(boxWithExtent: [x, y, z], segments: [1, 1, 1], inwardNormals: false,
                        geometryType: .triangles, allocator: MDLMeshBufferDataAllocator()))
    }

    private func limb(_ length: Float, _ radius: Float) -> SCNGeometry {
        faceted(MDLMesh(cylinderWithExtent: [2 * radius, length, 2 * radius], segments: [6, 1], inwardNormals: false,
                        topCap: true, bottomCap: true, geometryType: .triangles, allocator: MDLMeshBufferDataAllocator()))
    }

    /// A body part: a six-sided prism, long along x, flattened to the given size. Faceted.
    private func prism(_ x: Float, _ y: Float, _ z: Float) -> SCNGeometry {
        let mesh = MDLMesh(cylinderWithExtent: [y, x, z], segments: [6, 1], inwardNormals: false,
                           topCap: true, bottomCap: true, geometryType: .triangles, allocator: MDLMeshBufferDataAllocator())
        // stand it along x: turn the vertices (ModelIO cylinders stand along y)
        mesh.transform = MDLTransform(matrix: simd_float4x4(simd_quatf(angle: .pi / 2, axis: [0, 0, 1])))
        return faceted(flatten(mesh))
    }

    private func flatten(_ mesh: MDLMesh) -> MDLMesh {
        // bake the transform into the vertices so SceneKit sees the turned shape
        if let t = mesh.transform?.matrix, t != matrix_identity_float4x4,
           let attr = mesh.vertexAttributeData(forAttributeNamed: MDLVertexAttributePosition, as: .float3) {
            let stride = attr.stride
            let base = attr.dataStart
            for i in 0..<mesh.vertexCount {
                let p = base.advanced(by: i * stride).assumingMemoryBound(to: Float.self)
                let v = t * SIMD4<Float>(p[0], p[1], p[2], 1)
                p[0] = v.x; p[1] = v.y; p[2] = v.z
            }
            mesh.transform = nil
        }
        return mesh
    }

    private func ball(_ radius: Float) -> SCNGeometry {
        faceted(MDLMesh(sphereWithExtent: [2 * radius, 2.2 * radius, 2 * radius], segments: [7, 5], inwardNormals: false,
                        geometryType: .triangles, allocator: MDLMeshBufferDataAllocator()))
    }
}
