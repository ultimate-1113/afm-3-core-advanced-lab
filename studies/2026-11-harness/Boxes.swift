import Foundation
import Vision

struct Box: Encodable {
    let text: String
    let x: Double
    let y: Double
    let width: Double
    let height: Double
}

@main struct Boxes {
    static func main() throws {
        guard CommandLine.arguments.count == 2 else { throw CocoaError(.fileReadInvalidFileName) }
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.recognitionLanguages = ["ja-JP", "en-US"]
        let file = URL(fileURLWithPath: CommandLine.arguments[1])
        try VNImageRequestHandler(url: file).perform([request])
        let boxes = (request.results ?? []).compactMap { observation -> Box? in
            guard let text = observation.topCandidates(1).first?.string else { return nil }
            let rect = observation.boundingBox
            return Box(text: text, x: rect.minX, y: 1 - rect.midY, width: rect.width, height: rect.height)
        }
        FileHandle.standardOutput.write(try JSONEncoder().encode(boxes))
    }
}
