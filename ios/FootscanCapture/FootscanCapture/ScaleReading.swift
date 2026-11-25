// The bathroom-scale reading for a loaded foot scan (seated, foot on the scale), in the unit the scale shows.
//
// The studio wants kilograms, but many bathroom scales (most in the US) show pounds. Typed into a box that said
// "kg", a reading of 150 lb went to the studio as 150 kg: inside the range it accepts, and more than twice the
// real load. So the box has a kg / lb switch, set at first from the phone's region and then remembered, and the
// app turns pounds into kilograms before anything is saved or sent. The record and the studio only ever see kg.
import Foundation

enum ScaleUnit: String, CaseIterable, Identifiable {
    case kg, lb
    var id: String { rawValue }

    /// Exactly, by definition of the international pound.
    static let kgPerLb = 0.45359237

    /// What a phone set to this region most likely has on its scale: pounds where the US measurement system is
    /// in use (the US, Liberia, Myanmar), kilograms everywhere else. The UK's "uk" system weighs people in stone,
    /// which no box takes; kg is the nearer.
    static func usual(for locale: Locale) -> ScaleUnit {
        locale.measurementSystem == .us ? .lb : .kg
    }

    func kilograms(_ value: Double) -> Double { self == .kg ? value : value * Self.kgPerLb }
    func fromKilograms(_ kg: Double) -> Double { self == .kg ? kg : kg / Self.kgPerLb }
}

enum ScaleReading {
    /// The studio refuses a load of this or more (server.py's parse_load takes more than 0, less than 400 kg).
    static let studioLimitKg = 400.0

    /// The typed reading in kilograms, to 0.01 kg, or nil when it isn't a number the studio would take. Accepts a
    /// comma as the decimal mark ("68,5"), as a phone set to another region's keyboard types it. Rounding to 0.01 kg
    /// (far finer than any bathroom scale) keeps the studio's pages from showing 68.0388555 kg for 150 lb, and still
    /// shows 150 lb again when the scan is opened.
    static func kilograms(_ text: String, unit: ScaleUnit) -> Double? {
        let trimmed = text.trimmingCharacters(in: .whitespaces).replacingOccurrences(of: ",", with: ".")
        guard let value = Double(trimmed), value.isFinite else { return nil }
        let kg = (unit.kilograms(value) * 100).rounded() / 100
        return kg > 0 && kg < studioLimitKg ? kg : nil
    }

    /// A saved reading shown back in `unit`, to one decimal place without a trailing ".0" ("68.5", "150").
    static func text(kilograms kg: Double, unit: ScaleUnit) -> String {
        let v = (unit.fromKilograms(kg) * 10).rounded() / 10
        return v == v.rounded() ? String(Int(v)) : String(format: "%.1f", v)
    }

    /// What the reading comes to in kilograms, shown under the box when the unit is pounds, so the number the
    /// studio will get is on screen before Send.
    static func sentAs(_ kg: Double) -> String { String(format: "Sent to the studio as %.1f kg", kg) }

    /// The Details row: kilograms, and the pounds too when that's the unit in use.
    static func detail(kilograms kg: Double, unit: ScaleUnit) -> String {
        let inKg = String(format: "%.1f kg", kg)
        return unit == .kg ? inKg : "\(inKg) (\(text(kilograms: kg, unit: .lb)) lb)"
    }
}
