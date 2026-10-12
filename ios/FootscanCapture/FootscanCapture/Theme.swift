// footscan's look on iPhone: the website's colours (light and dark), and the
// few building blocks every screen uses, so the app feels like one thing.
import SwiftUI
import UIKit

extension Color {
    /// A colour with a light and a dark version, like the website's CSS variables.
    init(light: UInt32, dark: UInt32) {
        self.init(uiColor: UIColor { traits in
            let hex = traits.userInterfaceStyle == .dark ? dark : light
            return UIColor(red: CGFloat((hex >> 16) & 0xff) / 255, green: CGFloat((hex >> 8) & 0xff) / 255,
                           blue: CGFloat(hex & 0xff) / 255, alpha: 1)
        })
    }

    static let fsBackground = Color(light: 0xf5f4ef, dark: 0x0e1312)
    static let fsSurface = Color(light: 0xffffff, dark: 0x161e1d)
    static let fsSurface2 = Color(light: 0xeceae3, dark: 0x1d2726)
    static let fsInk = Color(light: 0x15201f, dark: 0xe6ecea)
    static let fsMuted = Color(light: 0x5a6563, dark: 0x9aa7a4)
    static let fsLine = Color(light: 0xdcdfd9, dark: 0x2a3533)
    static let fsBrand = Color(light: 0x0e4f4a, dark: 0x5fc2b6)
    static let fsBrandInk = Color(light: 0xffffff, dark: 0x04211e)
    static let fsBrandSoft = Color(light: 0xd9e9e5, dark: 0x173633)
    static let fsAccent = Color(light: 0xd6ee3c, dark: 0xd6ee3c)
    static let fsAccentInk = Color(light: 0x1b2400, dark: 0x1b2400)
    static let fsOK = Color(light: 0x1d7648, dark: 0x5cc98f)
    static let fsOKSoft = Color(light: 0xdcefe3, dark: 0x173325)
    static let fsWarn = Color(light: 0x9a5a00, dark: 0xf1a940)
    static let fsWarnSoft = Color(light: 0xf7ead3, dark: 0x3a2b12)
    static let fsStop = Color(light: 0xb0271f, dark: 0xff8177)
}

// MARK: - Buttons

/// The main action on a screen: full width, brand colour, gives under the finger.
struct PrimaryButtonStyle: ButtonStyle {
    var tint: Color = .fsBrand
    var ink: Color = .fsBrandInk
    @Environment(\.isEnabled) private var enabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.headline)
            .frame(maxWidth: .infinity, minHeight: 54)
            .foregroundStyle(enabled ? ink : Color.fsMuted)
            .background(enabled ? tint : Color.fsSurface2, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .shadow(color: tint.opacity(enabled ? 0.28 : 0), radius: configuration.isPressed ? 4 : 12, y: configuration.isPressed ? 2 : 6)
            .scaleEffect(configuration.isPressed ? 0.97 : 1)
            .animation(.spring(duration: 0.25, bounce: 0.4), value: configuration.isPressed)
    }
}

/// A quieter action: outlined, same size.
struct SecondaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.headline)
            .frame(maxWidth: .infinity, minHeight: 50)
            .foregroundStyle(Color.fsBrand)
            .background(Color.fsSurface, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).stroke(Color.fsLine, lineWidth: 1))
            .scaleEffect(configuration.isPressed ? 0.97 : 1)
            .animation(.spring(duration: 0.25, bounce: 0.4), value: configuration.isPressed)
    }
}

/// Any tappable card: presses in slightly.
struct PressableStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.975 : 1)
            .opacity(configuration.isPressed ? 0.92 : 1)
            .animation(.spring(duration: 0.22, bounce: 0.35), value: configuration.isPressed)
    }
}

// MARK: - Surfaces

struct CardModifier: ViewModifier {
    var padding: CGFloat = 18
    func body(content: Content) -> some View {
        content
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.fsSurface, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 22, style: .continuous).stroke(Color.fsLine.opacity(0.7), lineWidth: 1))
            .shadow(color: .black.opacity(0.05), radius: 14, y: 6)
    }
}

extension View {
    func card(padding: CGFloat = 18) -> some View { modifier(CardModifier(padding: padding)) }

    /// Cards rise and settle as they scroll into view, and soften as they leave.
    func scrollReveal() -> some View {
        scrollTransition(.interactive, axis: .vertical) { content, phase in
            content
                .opacity(phase.isIdentity ? 1 : 0.35)
                .scaleEffect(phase.isIdentity ? 1 : 0.94)
                .offset(y: phase.value > 0 ? 18 * phase.value : 0)
                .blur(radius: phase.isIdentity ? 0 : 1.5)
        }
    }
}

/// A small status label: "Model ready", "Sent", "Needs scale reading".
struct Chip: View {
    let text: String
    var symbol: String?
    var tint: Color = .fsBrand
    var soft: Color = .fsBrandSoft

    var body: some View {
        HStack(spacing: 4) {
            if let symbol { Image(systemName: symbol).font(.caption2.weight(.bold)) }
            Text(text).font(.caption.weight(.semibold))
        }
        .padding(.horizontal, 9).padding(.vertical, 5)
        .foregroundStyle(tint)
        .background(soft, in: Capsule())
    }
}

/// The not-a-medical-device line, the same wording as the website's strip.
struct SafetyStrip: View {
    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text("NOT A MEDICAL DEVICE").font(.caption.weight(.heavy)).foregroundStyle(Color.fsAccent)
            Text("See a foot doctor before sport.").font(.caption).foregroundStyle(.white.opacity(0.85))
        }
        .padding(.horizontal, 12).padding(.vertical, 7)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(light: 0x15201f, dark: 0x0a0f0e), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(Color.fsAccent.opacity(0.35), lineWidth: 1))
        .accessibilityElement(children: .combine)
    }
}
