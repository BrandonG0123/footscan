// Showing a scanned model: an inline 3D view you turn with a finger, and the
// small picture on each scan card. SceneKit, because it reads Object
// Capture's USDZ directly and behaves the same on the phone and in the
// simulator.
import SceneKit
import SwiftUI
import UIKit

enum ModelScene {
    /// The model, centred, with a camera framing it from slightly above.
    static func load(_ url: URL) -> (SCNScene, SCNNode)? {
        guard let scene = try? SCNScene(url: url, options: [.checkConsistency: false]) else { return nil }
        let (lo, hi) = scene.rootNode.boundingBox
        let centre = SCNVector3((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, (lo.z + hi.z) / 2)
        let size = max(hi.x - lo.x, hi.y - lo.y, hi.z - lo.z)
        guard size > 0 else { return nil }
        let camera = SCNNode()
        camera.camera = SCNCamera()
        camera.camera?.zNear = Double(size) * 0.01
        camera.camera?.zFar = Double(size) * 20
        camera.camera?.fieldOfView = 35
        camera.position = SCNVector3(centre.x + size * 0.95, centre.y + size * 1.0, centre.z + size * 1.55)
        camera.look(at: centre)
        scene.rootNode.addChildNode(camera)
        return (scene, camera)
    }

    /// A still picture of the model, for the scan cards.
    static func snapshot(_ url: URL, size: CGSize) -> UIImage? {
        guard let (scene, camera) = load(url) else { return nil }
        let renderer = SCNRenderer(device: MTLCreateSystemDefaultDevice(), options: nil)
        renderer.scene = scene
        renderer.pointOfView = camera
        renderer.autoenablesDefaultLighting = true
        scene.background.contents = UIColor.clear
        return renderer.snapshot(atTime: 0, with: size, antialiasingMode: .multisampling4X)
    }
}

/// The scanned model; drag to turn it, pinch to zoom.
struct ModelViewer: UIViewRepresentable {
    let url: URL

    func makeUIView(context: Context) -> SCNView {
        let view = SCNView()
        view.backgroundColor = .clear
        view.antialiasingMode = .multisampling4X
        view.autoenablesDefaultLighting = true
        view.allowsCameraControl = true
        view.defaultCameraController.interactionMode = .orbitTurntable
        view.defaultCameraController.inertiaEnabled = true
        if let (scene, camera) = ModelScene.load(url) {
            scene.background.contents = UIColor.clear
            view.scene = scene
            view.pointOfView = camera
        }
        return view
    }

    func updateUIView(_ view: SCNView, context: Context) {}
}
