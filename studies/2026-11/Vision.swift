import AppKit
import Foundation
import Vision

// Images are constructed entirely from the synthetic sheet. Emit only gray pixels.
struct Sheet: Decodable {
    var number: String
    var heading: String
    var rows: [[String]]
}
struct OCR: Encodable {
    let flat: [String]
    let tables: [[[String]]]
    let flat_s: Double
    let tables_s: Double
}
func paint(_ sheet: Sheet, to file: URL) throws {
    let w = 1160, h = 170 + (sheet.rows.count + 1) * 62
    var pixels = [UInt8](repeating: 255, count: w * h)
    try pixels.withUnsafeMutableBytes { buffer in
        guard let ctx = CGContext(data: buffer.baseAddress, width: w, height: h,
            bitsPerComponent: 8, bytesPerRow: w, space: CGColorSpaceCreateDeviceGray(),
            bitmapInfo: CGImageAlphaInfo.none.rawValue) else { throw CocoaError(.coderInvalidValue) }
        NSGraphicsContext.saveGraphicsState()
        defer { NSGraphicsContext.restoreGraphicsState() }
        NSGraphicsContext.current = NSGraphicsContext(cgContext: ctx, flipped: false)
        func label(_ s: String, _ x: Int, _ top: Int, _ size: CGFloat) {
            let attrs: [NSAttributedString.Key: Any] = [
                .font: NSFont.systemFont(ofSize: size), .foregroundColor: NSColor.black
            ]
            (s as NSString).draw(at: NSPoint(x: x, y: h - top - Int(size) - 8), withAttributes: attrs)
        }
        label(sheet.heading + "  " + sheet.number, 38, 12, 40)
        let xs = [32, 254, 520, 681, 1128], top = 85, step = 62
        let rows = [["品番", "品名", "納入数", "備考"]] + sheet.rows
        ctx.setStrokeColor(gray: 0.15, alpha: 1); ctx.setLineWidth(2)
        for x in xs {
            ctx.move(to: CGPoint(x: x, y: h - top))
            ctx.addLine(to: CGPoint(x: x, y: h - top - rows.count * step))
        }
        for i in 0...rows.count {
            let y = h - top - i * step
            ctx.move(to: CGPoint(x: xs[0], y: y))
            ctx.addLine(to: CGPoint(x: xs.last!, y: y))
        }
        ctx.strokePath()
        for (i, row) in rows.enumerated() {
            for (j, value) in row.enumerated() { label(value, xs[j] + 14, top + i * step + 9, 28) }
        }
        ctx.flush()
    }
    var pgm = Data("P5\n\(w) \(h)\n255\n".utf8)
    pgm.append(contentsOf: pixels)
    try pgm.write(to: file)
}

func recognize(_ src: URL, _ dst: URL, _ mode: String = "ocr") async throws {
    var flat = RecognizeTextRequest()
    flat.recognitionLanguages = ["ja-JP", "en-US"].map { Locale.Language(identifier: $0) }
    flat.recognitionLevel = .accurate
    var tables = RecognizeDocumentsRequest()
    tables.textRecognitionOptions.recognitionLanguages = flat.recognitionLanguages
    let t0 = ProcessInfo.processInfo.systemUptime
    let words = mode == "table" ? [] : try await flat.perform(on: src).compactMap { $0.topCandidates(1).first?.string }
    let t1 = ProcessInfo.processInfo.systemUptime
    let docs = mode == "flat" ? [] : try await tables.perform(on: src)
    let values = docs.flatMap { $0.document.tables }.map { table in
        table.rows.map { row in row.map { $0.content.text.transcript } }
    }
    let data = OCR(flat: words, tables: values, flat_s: t1 - t0,
                   tables_s: ProcessInfo.processInfo.systemUptime - t1)
    try JSONEncoder().encode(data).write(to: dst, options: .atomic)
}

@main struct VisionTool {
    static func main() async throws {
        let args = CommandLine.arguments
        guard args.count == 4 else { throw CocoaError(.validationMissingMandatoryProperty) }
        let src = URL(fileURLWithPath: args[2]), dst = URL(fileURLWithPath: args[3])
        if args[1] == "paint" {
            try paint(JSONDecoder().decode(Sheet.self, from: Data(contentsOf: src)), to: dst)
        } else if ["flat","table","ocr"].contains(args[1]) {
            try await recognize(src, dst, args[1])
        } else if args[1] == "batch" {
            let entries = try JSONDecoder().decode([[String]].self, from: Data(contentsOf: src))
            for entry in entries {
                let output = dst.appendingPathComponent(entry[0] + ".json")
                if !FileManager.default.fileExists(atPath: output.path) {
                    try await recognize(URL(fileURLWithPath: entry[1]), output)
                }
            }
        } else { throw CocoaError(.validationMissingMandatoryProperty) }
    }
}
